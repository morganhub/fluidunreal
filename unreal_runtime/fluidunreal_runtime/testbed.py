"""game.smoke_test: play the imported character in a headless editor and report what happened.

The scene is built in code: a floor, a wall, a prop and a `Character` carrying the imported mesh.
No `.uasset` or `.umap` is shipped, so there is nothing to keep in step with the engine.

Four things lot 0 had to get right, each of which was wrong first and looked fine:

- `editor_request_begin_play`, not `editor_play_simulate`. Simulate-In-Editor left the pawn at the
  origin with zero velocity for 180 ticks: alive-looking, and measuring a statue.
- the measured actor lives in the PIE world; the editor actor never moves.
- `add_movement_input` needs `force=True` and a possessed pawn, or the input is dropped.
- the PIE duplicate does not inherit single-node playback: it has to be re-armed.

The bed runs three phases, as a game would: the character stands with nothing playing, walks
with the clip looping until the clip has wrapped at least once, then stands again and the clip is
stopped. On the way it passes the prop, which the bed attaches to the right hand.

The report is written **before** the editor is asked to quit. A run that writes no report proves
nothing, and the engine treats a missing one as an unknown state rather than a failure.

**What `walk_clip_moves_bones` got wrong, three times.** Lot 0 passed it by measuring the actor
translating: its window overlapped the walk. The next version read a big toe's offset from the
reference pose, a local translation that stays constant for a bone that only rotates, and read
0.0 cm, which looked like a clip that does not play. It does play (probe P6). The next read positions
relative to the actor and found every bone, spine and forehead included, moving the same 10 cm in
0.34 s: that was the clip carrying the whole body forward at 30 cm/s. The reference walk is declared
in place and travels 0.58 m per loop; the audit now fails it for that. The check reads the distance
between the two feet, which no displacement of the whole body can change, so it is read while the
character walks.
"""

import math
import os
import platform
import time

import unreal

from fluidunreal_runtime.errors import OpError
from fluidunreal_runtime.report import write_json_atomic

DEFERRED = "deferred"

CUBE = "/Engine/BasicShapes/Cube.Cube"
FLOOR_Z = 0.0
WALL_X = 400.0
PROP_X = 200.0
PLAYER_START = unreal.Vector(-800.0, -900.0, 150.0)
# Input is along +X only: a character that drifts sideways more than this was pushed.
LATERAL_CM = 5.0
# The movement component parks the capsule slightly above the floor. Measured at 2.15 cm on 5.8.2,
# so the tolerance is 3 cm and the reason is written down rather than the number fudged.
FLOOR_TOLERANCE_CM = 3.0
# Phases, counted in steps from the tick the bed became ready. The capsule has settled by
# IDLE_FROM; the idle window is long enough to see a pose that should not move.
IDLE_FROM = 40
IDLE_UNTIL = 80
# The walk lasts until the clip has wrapped, which is what looping means, and at least long enough
# to reach the wall. Ticks are not a fixed 1/60 s under PIE (0.0085 s of clip per tick was measured
# on 5.8.2), so a fixed count would either miss the wrap or waste minutes.
WALK_MIN_STEPS = 120
WALK_MAX_STEPS = 600
STOP_STEPS = 60
# Speed below which the character counts as standing, and at which the bed stops the clip.
STANDING_CM_S = 1.0
# How much the distance between the feet must change while walking; and how little it may while
# standing (a pose that is not played does not move at all, so the margin is only float noise).
BONE_TRAVEL_CM = 1.0
STILL_CM = 0.05
# First walking steps are skipped: the pose may still be the reference one.
SETTLE_STEPS = 5
PAIRS = (("DEF-foot_L", "DEF-foot_R"), ("DEF-hand_L", "DEF-hand_R"))
FEET = PAIRS[0]
# The spec's pickup distance, measured as the closest approach.
PICKUP_CM = 50.0
# Where the bed picks the prop up: before the capsule (radius 34 cm) meets the prop's near face at
# 180 cm. Picking it up at 50 cm let the capsule hit it first and slide 17.6 cm sideways.
GRAB_CM = 60.0
UNREADABLE = "unreadable"
HOLD_CM = 5.0
HAND_TRAVEL_CM = 10.0
EMPTY_CM = 25.0
# The PIE world takes a few ticks to exist; beyond this it never will.
READY_DEADLINE_TICKS = 120
PROXY_SUFFIX = "proxytruerootjoint"


def force_pose_ticking(component, builder):
    """Make the component advance its pose even though nothing is rendered.

    A skeletal mesh defaults to ticking its pose only when it is rendered. Under `-nullrhi` nothing
    ever is, so the clip never advances and every bone reads the same position forever: which is
    exactly the 0.0 cm this bed measured.
    """
    applied = []
    # Measured on 5.8.2: the default is ONLY_TICK_POSE_WHEN_RENDERED, and under -nullrhi nothing
    # ever is, so the pose never advances. The enum value is ..._AND_REFRESH_BONES on this series.
    try:
        option = unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES
        component.set_editor_property("visibility_based_anim_tick_option", option)
        applied.append("visibility_based_anim_tick_option")
    except Exception as error:  # noqa: BLE001
        builder.warn("visibility_based_anim_tick_option could not be set: %s" % error)
    for prop, value in (
        ("no_skeleton_update", False),
        ("skip_bounds_update_when_interpolating", False),
        ("enable_update_rate_optimizations", False),
    ):
        try:
            component.set_editor_property(prop, value)
            applied.append(prop)
        except Exception as error:  # noqa: BLE001
            # Not every knob exists on every series; which ones took is what the report records.
            builder.warn("%s could not be set: %s" % (prop, error))
    try:
        component.set_component_tick_enabled(True)
        applied.append("set_component_tick_enabled")
    except Exception as error:  # noqa: BLE001
        builder.warn("set_component_tick_enabled unavailable: %s" % error)
    return applied


def play_single_animation(component, anim, builder):
    """Loop one clip, whichever API this series exposes. There is no `anim_to_play` on 5.8."""
    for label, call in (
        ("play_animation", lambda: component.play_animation(anim, True)),
        ("set_animation+play", lambda: (component.set_animation(anim), component.play(True))),
    ):
        try:
            call()
            return label
        except Exception as error:  # noqa: BLE001
            builder.warn("%s unavailable: %s" % (label, error))
    return None


def game_world(builder):
    for label, call in (
        (
            "UnrealEditorSubsystem",
            lambda: unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world(),
        ),
        ("EditorLevelLibrary", lambda: unreal.EditorLevelLibrary.get_game_world()),
    ):
        try:
            world = call()
        except Exception as error:  # noqa: BLE001
            builder.warn("%s.get_game_world unavailable: %s" % (label, error))
            continue
        if world is not None:
            return world
    return None


class Bed:
    """The bed and its checks, stepped one tick at a time."""

    def __init__(self, ctx, request, builder, mesh, anim, instance):
        self.ctx = ctx
        self.request = request
        self.builder = builder
        self.mesh = mesh
        self.anim = anim
        self.instance = instance
        self.checks = {}
        self.notes = []
        self.tick = 0
        self.handle = None
        self.editor_character = None
        self.playing = None
        self.play_via = None
        self.started_with = None
        self.wall_samples = []
        self.closest_to_prop = None
        self.finished = False
        self.report = None
        self.on_finished = None
        self.ready_tick = 0
        self.first_playback = (None, None)
        self.last_position = None
        self.tick_options = []
        self.anim_name = None
        self.prop = None
        self.prop_origin = None
        self.held = None
        self.hand_at_pickup = None
        self.mesh_offset = None
        self.facing_error = None
        self.positions = {}
        self.start = None
        self.idle_spans = []
        self.idle_playing = []
        self.idle_assets = set()
        self.walk_from = 0
        self.walk_until = 0
        self.walk_spans = {}
        self.walk_playing = []
        self.wraps = 0
        self.stopped_at = None
        self.stand_spans = []
        self.stand_playing = []
        self.started = time.monotonic()

    # --- reporting ----------------------------------------------------------------------

    def check(self, name, passed, detail=None):
        self.checks[name] = {"passed": None if passed is None else bool(passed), "detail": detail}

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    def build_report(self, aborted=None):
        measured = [c for c in self.checks.values() if c["passed"] is not None]
        return {
            "schema_version": "1.0",
            "engine": unreal.SystemLibrary.get_engine_version(),
            "headless": True,
            "bundle_id": self.ctx.bundle.get("bundle_id"),
            "asset_id": self.instance.get("asset_id"),
            "started_with": self.started_with,
            "played_via": self.play_via,
            "checks": self.checks,
            "failed_checks": sorted(n for n, c in self.checks.items() if c["passed"] is False),
            "not_run_checks": sorted(n for n, c in self.checks.items() if c["passed"] is None),
            # A check that was not measured is never a pass and never a failure.
            "passed": bool(measured) and not any(c["passed"] is False for c in self.checks.values()),
            "verdict": "%d measured and passed, %d failed, %d not measured by this bed"
            % (
                sum(1 for c in self.checks.values() if c["passed"] is True),
                sum(1 for c in self.checks.values() if c["passed"] is False),
                sum(1 for c in self.checks.values() if c["passed"] is None),
            ),
            "aborted": aborted,
            "notes": self.notes,
            "ticks": self.tick,
            "wall_time_ms": int((time.monotonic() - self.started) * 1000),
            # Never a frame rate or a GPU figure: what ran, not how fast it could.
            "machine": {"platform": platform.platform(), "processor": platform.processor()},
        }

    # --- scene --------------------------------------------------------------------------

    def build(self):
        # A blank map that is never saved. `new_level` wrote SmokeBed.umap into the project on every
        # run, and on the next run failed on the existing path, so the bed was built into whatever
        # map was open: its sky, its landscape and its lights changed with the project's history.
        world = unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
        if world is None:
            raise OpError("INTERNAL_ERROR", "the editor could not open a blank map for the bed")
        cube = unreal.EditorAssetLibrary.load_asset(CUBE)

        def block(label, location, scale):
            actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                unreal.StaticMeshActor, location, unreal.Rotator(0.0, 0.0, 0.0)
            )
            actor.set_actor_label(label)
            actor.static_mesh_component.set_static_mesh(cube)
            actor.set_actor_scale3d(scale)
            return actor

        block("Floor", unreal.Vector(0.0, 0.0, -50.0), unreal.Vector(20.0, 20.0, 1.0))
        block("Wall", unreal.Vector(WALL_X, 0.0, 100.0), unreal.Vector(0.2, 10.0, 4.0))
        # Without a PlayerStart, PIE spawns its default pawn at the origin, inside the character's
        # capsule: measured, it threw the character from (0, 0) to (187, -191) before any input,
        # and character_moves counted those 187 cm as walking. It starts behind the camera instead.
        unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.PlayerStart, PLAYER_START, unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0)
        )
        prop = block("Prop", unreal.Vector(PROP_X, 0.0, 20.0), unreal.Vector(0.4, 0.4, 0.4))
        # A static actor cannot be attached to anything: the pickup needs it movable.
        prop.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)

        self.editor_character = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.Character, unreal.Vector(0.0, 0.0, 100.0), unreal.Rotator(0.0, 0.0, 0.0)
        )
        component = self.editor_character.mesh
        for setter in ("set_skeletal_mesh_asset", "set_skeletal_mesh"):
            if hasattr(component, setter):
                getattr(component, setter)(self.mesh)
                break
        else:
            raise OpError("INTERNAL_ERROR", "no setter for the skeletal mesh on this series")
        component.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
        force_pose_ticking(component, self.builder)
        self.place_mesh(self.editor_character, component)

    def place_mesh(self, actor, component):
        """Stand the mesh on the capsule's floor, facing the way the character walks.

        A `Character` carries its mesh at the capsule's centre and walks along +X. Left as it was,
        the imported mesh stood 88 cm above the floor, and it walked sideways: its skeleton faces
        +Y, which is where glTF's forward lands. Nothing measured headless showed either; the
        frame of lot 0 did. The facing is measured on the skeleton, from the foot to its toe, not
        assumed from the axis convention.
        """
        half = 88.0
        try:
            half = actor.capsule_component.get_scaled_capsule_half_height()
        except Exception as error:  # noqa: BLE001
            self.builder.warn("the capsule half height is unreadable: %s" % error)
        origin = actor.get_actor_location()
        facing = None
        pair = self.foot_and_toe()
        if pair:
            try:
                foot = component.get_socket_location(pair[0]) - origin
                toe = component.get_socket_location(pair[1]) - origin
                facing = math.degrees(math.atan2(toe.y - foot.y, toe.x - foot.x))
            except Exception as error:  # noqa: BLE001
                self.builder.warn("the facing could not be measured: %s" % error)
        if facing is None:
            # glTF's +Z forward lands on +Y: stated as an assumption, not passed off as measured.
            facing = 90.0
            self.builder.limit("the mesh's facing was not measured: +Y, glTF's forward, is assumed")
        # A foot splays a few degrees: a facing that close to an axis is that axis.
        snapped = round(facing / 90.0) * 90.0
        yaw = -(snapped if abs(facing - snapped) <= 15.0 else facing)
        component.set_relative_location(unreal.Vector(0.0, 0.0, -half), False, False)
        component.set_relative_rotation(unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw), False, False)
        self.mesh_offset = {
            "z_cm": round(-half, 3),
            "yaw_deg": round(yaw, 2),
            "measured_facing_deg": round(facing, 2),
            "measured_on": list(pair) if pair else None,
            "why": "a Character walks along +X with its mesh at the capsule's centre",
        }

    def foot_and_toe(self):
        """A foot and a toe of the same side, from the bundle's reference pose."""
        names = [r["bone"] for r in self.instance.get("reference_pose") or []]
        for foot in names:
            if "foot" not in foot.lower():
                continue
            side = foot.rsplit(".", 1)[-1]
            for toe in names:
                if "toe" in toe.lower() and toe.rsplit(".", 1)[-1] == side:
                    return foot.replace(".", "_"), toe.replace(".", "_")
        return None

    def facing_error_deg(self, actor, component):
        """Angle between where the standing mesh faces and where the character walks, +X."""
        pair = self.foot_and_toe()
        if not pair:
            return None
        try:
            foot, toe = component.get_socket_location(pair[0]), component.get_socket_location(pair[1])
        except Exception as error:  # noqa: BLE001
            self.builder.warn("the facing is unreadable: %s" % error)
            return None
        forward = actor.get_actor_forward_vector()
        angle = math.degrees(math.atan2(toe.y - foot.y, toe.x - foot.x) - math.atan2(forward.y, forward.x))
        return round((angle + 180.0) % 360.0 - 180.0, 2)

    def track(self, label, actor):
        where = actor.get_actor_location()
        self.positions[label] = [round(where.x, 2), round(where.y, 2), round(where.z, 2)]

    def lowest_reference_bone(self):
        rows = self.instance.get("reference_pose") or []
        if not rows:
            return None, None
        row = min(rows, key=lambda r: float(r["head_m"][2]))
        return row["bone"].replace(".", "_"), float(row["head_m"][2]) * 100.0

    def resolve(self):
        """The actor that simulates lives in the PIE world; the editor one is a statue."""
        world = game_world(self.builder)
        if world is None:
            return None
        found = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Character)
        if not found:
            return None
        skinned = [
            a
            for a in found
            if hasattr(a.mesh, "get_skinned_asset") and a.mesh.get_skinned_asset() is not None
        ]
        chosen = skinned[0] if skinned else found[0]
        try:
            controller = unreal.GameplayStatics.get_player_controller(world, 0)
            if controller is not None:
                controller.possess(chosen)
                self.note("possessed by %s" % controller.get_name())
        except Exception as error:  # noqa: BLE001
            self.builder.warn("the character could not be possessed: %s" % error)
        # Any other pawn is taken out of the bed: hidden and without collision, never destroyed.
        # Destroying the default pawn ended the PIE session in lot 0.
        for pawn in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Pawn):
            if pawn != chosen:
                pawn.set_actor_hidden_in_game(True)
                pawn.set_actor_enable_collision(False)
                self.note("taken out of the bed: %s" % pawn.get_name())
        # The PIE duplicate does not inherit single-node playback: re-arm it, and make it tick
        # its pose although nothing is rendered under -nullrhi.
        try:
            chosen.mesh.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
        except Exception as error:  # noqa: BLE001
            self.builder.warn("the PIE animation mode could not be set: %s" % error)
        self.tick_options = force_pose_ticking(chosen.mesh, self.builder)
        self.note("pose ticking forced through %s" % ", ".join(self.tick_options or ["nothing"]))
        try:
            self.note("PIE animation mode: %s" % chosen.mesh.get_animation_mode())
            self.note("PIE anim instance: %s" % (chosen.mesh.get_anim_instance() is not None))
        except Exception as error:  # noqa: BLE001
            self.builder.warn("the PIE animation mode is unreadable: %s" % error)
        for candidate in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor):
            if candidate.get_actor_label() == "Prop":
                self.prop = candidate
                self.prop_origin = candidate.get_actor_location()
        if self.prop is None:
            self.note("the prop was not found in the PIE world")
        return chosen

    def hand_socket(self, component):
        """Where the prop goes: a grip socket if the bundle has one, else the right hand bone."""
        grips = self.instance.get("grips") or {}
        names = self.bone_names(component)
        for name in ["grip_primary"] + sorted(grips):
            if name in names or component.does_socket_exist(name):
                return name, "grip socket"
        hand = "DEF-hand_R"
        if hand in names:
            self.builder.limit("the bundle declares no grip: the prop is held at the right hand bone")
            return hand, "right hand bone"
        self.builder.limit("no grip and no right hand bone: the prop is held at the root")
        return names[0] if names else "", "root"

    def assigned_clip(self, component):
        """The clip the single-node player holds, by name; "None" when it holds nothing."""
        try:
            asset = component.get_anim_instance().get_animation_asset()
        except Exception as error:  # noqa: BLE001
            self.builder.warn("the assigned clip is unreadable: %s" % error)
            return UNREADABLE
        return "None" if asset is None else asset.get_name()

    def bone_names(self, component):
        try:
            return [str(component.get_bone_name(i)) for i in range(component.get_num_bones())]
        except Exception as error:  # noqa: BLE001
            self.builder.warn("the PIE skeleton could not be enumerated: %s" % error)
            return []

    def span(self, component, pair):
        """Distance between two bones. No displacement of the whole body can change it."""
        left, right = self.bone(component, pair[0]), self.bone(component, pair[1])
        if left is None or right is None:
            return None
        return (left - right).length()

    @staticmethod
    def spread(values):
        values = [v for v in values if v is not None]
        return round(max(values) - min(values), 3) if len(values) >= 2 else None

    def playback(self, component):
        """Where the single-node player is in the clip, and whether it says it is playing."""
        position = playing = None
        try:
            position = float(component.get_position())
        except Exception as error:  # noqa: BLE001
            self.builder.warn("the playback position is unreadable: %s" % error)
        try:
            playing = bool(component.is_playing())
        except Exception as error:  # noqa: BLE001
            self.builder.warn("is_playing is unreadable: %s" % error)
        return position, playing

    # --- the checks ---------------------------------------------------------------------

    def step(self, _delta):
        if self.finished:
            return
        self.tick += 1
        if self.playing is None:
            # The PIE world is not up on the first tick. Milestones count from the tick the bed
            # became ready, not from the first callback: keying them to absolute ticks meant the
            # first milestone was spent resolving and its checks never ran at all.
            if self.tick > READY_DEADLINE_TICKS:
                self.finish(aborted="no character appeared in the PIE world")
                return
            self.playing = self.resolve()
            if self.playing is None:
                return
            self.ready_tick = self.tick
            self.note("the bed became ready on tick %d" % self.tick)
        actor = self.playing
        component = actor.mesh
        try:
            self.measure(actor, component, self.tick - self.ready_tick + 1)
        except Exception as error:  # noqa: BLE001
            self.note("step %d raised: %s" % (self.tick - self.ready_tick + 1, error))
            self.finish(aborted=str(error))

    def measure(self, actor, component, step):
        if step == 1:
            self.check("map_loaded", True, "PIE world obtained")
            self.check("character_spawned", self.playing is not None, {"in_pie_world": True})
            names = self.bone_names(component)
            added = [n for n in names if n.lower().endswith(PROXY_SUFFIX)]
            expected = int(self.instance.get("bone_count") or 0)
            self.check(
                "skeleton_bone_count",
                (len(names) - len(added)) == expected if expected else None,
                {"got": len(names), "expected": expected, "added_by_importer": added},
            )
            self.check("walk_clip_found", self.anim is not None, {"clip": self.anim_name})
            self.track("ready", actor)
        if step == IDLE_FROM:
            half = 88.0
            try:
                half = actor.capsule_component.get_scaled_capsule_half_height()
            except Exception as error:  # noqa: BLE001
                self.builder.warn("the capsule half height is unreadable: %s" % error)
            bottom = actor.get_actor_location().z - half
            # The feet, not the capsule: the capsule stood on the floor for three lots while the
            # mesh floated 88 cm above it. The lowest reference bone must be at its bundle height.
            bone, expected = self.lowest_reference_bone()
            height = None
            if bone:
                try:
                    height = component.get_socket_location(bone).z - FLOOR_Z
                except Exception as error:  # noqa: BLE001
                    self.builder.warn("the height of %s is unreadable: %s" % (bone, error))
            self.check(
                "stands_on_floor",
                None if height is None else abs(height - expected) <= FLOOR_TOLERANCE_CM,
                {
                    "bone": bone,
                    "bone_height_cm": None if height is None else round(height, 3),
                    "bundle_height_cm": None if expected is None else round(expected, 3),
                    "capsule_bottom_z": round(bottom, 3),
                    "tolerance_cm": FLOOR_TOLERANCE_CM,
                    "mesh_offset": self.mesh_offset,
                    "why": "the movement component parks the capsule 2.15 cm above the floor",
                },
            )
        if step == IDLE_FROM:
            self.facing_error = self.facing_error_deg(actor, component)
            self.track("idle", actor)
        if IDLE_FROM <= step <= IDLE_UNTIL:
            self.idle_spans.append(self.span(component, FEET))
            self.idle_playing.append(self.playback(component)[1])
            self.idle_assets.add(self.assigned_clip(component))
        if step == IDLE_UNTIL:
            moved = self.spread(self.idle_spans)
            assigned = sorted(str(a) for a in self.idle_assets if a != UNREADABLE)
            self.check(
                "idle_plays_nothing",
                None if moved is None else (moved <= STILL_CM and assigned == ["None"]),
                {
                    "feet_distance_range_cm": moved,
                    "assigned_clip": assigned,
                    "reported_playing": any(self.idle_playing),
                    "over_steps": [IDLE_FROM, IDLE_UNTIL],
                    "why": "no idle clip in this bundle: no clip is assigned and the pose holds. "
                    "is_playing is reported, not used: on 5.8.2 it is true with no clip at all",
                },
            )
            if self.anim is not None:
                self.play_via = play_single_animation(component, self.anim, self.builder)
            self.walk_from = step + 1
            self.start = actor.get_actor_location()
            self.track("walk_start", actor)
            self.first_playback = self.playback(component)
            self.last_position = self.first_playback[0]
        if self.walk_from and not self.walk_until and step >= self.walk_from:
            self.walk(actor, component, step)
        if self.walk_until and step > self.walk_until:
            self.stand(actor, component, step)

    def walk(self, actor, component, step):
        walked = step - self.walk_from
        actor.add_movement_input(unreal.Vector(1.0, 0.0, 0.0), 1.0, True)
        location = actor.get_actor_location()
        self.wall_samples.append(location.x)
        distance = abs(location.x - PROP_X)
        if self.closest_to_prop is None or distance < self.closest_to_prop:
            self.closest_to_prop = distance
        if self.prop is not None and not self.held and distance < GRAB_CM:
            self.pick_up(actor, component, step)
        position, playing = self.playback(component)
        if position is not None and self.last_position is not None and position < self.last_position - 1e-4:
            self.wraps += 1
        if position is not None:
            self.last_position = position
        self.walk_playing.append(playing)
        if walked >= SETTLE_STEPS:
            for pair in PAIRS:
                self.walk_spans.setdefault(pair, []).append(self.span(component, pair))
        if walked < WALK_MIN_STEPS or (not self.wraps and walked < WALK_MAX_STEPS):
            return
        self.walk_until = step
        self.track("walked", actor)
        # Measured from where the walk started: counting from the first tick counted the push.
        travelled = location.x - self.start.x
        lateral = location.y - self.start.y
        self.check(
            "character_moves",
            travelled > 10.0 and abs(lateral) <= LATERAL_CM,
            {
                "delta_x_cm": round(travelled, 2),
                "lateral_cm": round(lateral, 2),
                "lateral_tolerance_cm": LATERAL_CM,
                "positions_cm": self.positions,
                # Reported, not gated: the bed turned the mesh itself, from the same skeleton.
                "facing_error_deg": self.facing_error,
            },
        )
        peak = max(self.wall_samples) if self.wall_samples else 0.0
        # Both halves matter: it has to reach the wall and be stopped by it.
        self.check(
            "wall_stops_it",
            peak > PROP_X and peak <= WALL_X + 2.0,
            {"peak_x": round(peak, 2), "wall_x": WALL_X},
        )
        self.check(
            "reaches_pickup",
            self.closest_to_prop is not None and self.closest_to_prop < PICKUP_CM,
            {"closest_cm": round(self.closest_to_prop or -1.0, 2), "threshold_cm": PICKUP_CM},
        )
        position_then = self.first_playback[0]
        self.check(
            "walk_plays_looping",
            None if position is None else bool(self.wraps > 0 and all(self.walk_playing)),
            {
                "position_from_s": None if position_then is None else round(position_then, 4),
                "position_to_s": None if position is None else round(position, 4),
                "wraps": self.wraps,
                "always_playing": all(self.walk_playing),
                "steps": walked,
                "why": "looping is the position going back to the start while the player still plays",
            },
        )
        ranges = {"%s~%s" % pair: self.spread(values) for pair, values in self.walk_spans.items()}
        feet = ranges.get("%s~%s" % FEET)
        self.check(
            "walk_clip_moves_bones",
            None if feet is None else feet > BONE_TRAVEL_CM,
            {
                "distance_range_cm_by_pair": ranges,
                "threshold_cm": BONE_TRAVEL_CM,
                "why": "the distance between the feet ignores the body moving; only the skeleton "
                "deforming can make it change. The hands are read too: this walk does not swing them",
            },
        )
        hands = ranges.get("%s~%s" % PAIRS[1])
        if feet is not None and hands is not None and feet > BONE_TRAVEL_CM and hands <= BONE_TRAVEL_CM:
            # A human watching the reference walk saw "arms held out" before any number said so: the
            # clip leaves the arms in the rest pose, which for this character is an A-pose. Not a
            # failure of the import; a limit of the clip, said where it will be read.
            self.builder.warn(
                "the walk leaves the arms still: the hands keep their distance (%.2f cm of change) "
                "while the feet move %.1f cm, so the arms hold the rest pose. Fix it in the clip, "
                "where it was made" % (hands, feet)
            )

    def pick_up(self, actor, component, step):
        """Attach the prop to the hand, the way a game's pickup would, and say where."""
        socket, kind = self.hand_socket(component)
        try:
            self.prop.set_actor_enable_collision(False)
            rule = unreal.AttachmentRule
            self.prop.attach_to_component(
                component, socket, rule.SNAP_TO_TARGET, rule.SNAP_TO_TARGET, rule.KEEP_WORLD, False
            )
            self.held = {"socket": socket, "kind": kind, "at_step": step}
            self.hand_at_pickup = component.get_socket_location(socket)
        except Exception as error:  # noqa: BLE001
            self.note("the prop could not be attached: %s" % error)

    def stand(self, actor, component, step):
        speed = actor.get_velocity().length()
        position, playing = self.playback(component)
        if speed < STANDING_CM_S and playing and not self.stopped_at:
            # The bed's own state machine: no input and no speed means idle, and idle plays nothing.
            component.stop()
            self.stopped_at = step
        if step > self.walk_until + STOP_STEPS - 20:
            self.stand_spans.append(self.span(component, FEET))
            self.stand_playing.append(self.playback(component)[1])
        if step < self.walk_until + STOP_STEPS:
            return
        moved = self.spread(self.stand_spans)
        self.check(
            "back_to_idle",
            None
            if moved is None
            else bool(speed < STANDING_CM_S and moved <= STILL_CM and not any(self.stand_playing)),
            {
                "speed_cm_s": round(speed, 3),
                "feet_distance_range_cm": moved,
                "clip_stopped_at_step": self.stopped_at,
                "why": "without input the character stops, and the clip is stopped with it",
            },
        )
        self.check_prop(component)
        self.finish()

    def check_prop(self, component):
        if self.prop is None:
            self.check("holds_prop", None, "the prop was not found in the PIE world")
            self.check("pickup_empty", None, "the prop was not found in the PIE world")
            return
        parent = self.prop.get_attach_parent_actor()
        gap = moved = None
        if self.held:
            target = component.get_socket_location(self.held["socket"])
            gap = (self.prop.get_actor_location() - target).length()
            moved = (target - self.hand_at_pickup).length()
        # Snapping puts the prop on the hand by construction, so a gap of zero at pickup proves
        # nothing. A zero after the hand has carried it across the floor is what holding means.
        self.check(
            "holds_prop",
            bool(self.held)
            and parent == self.playing
            and gap is not None
            and gap <= HOLD_CM
            and moved > HAND_TRAVEL_CM,
            {
                "attached_to": None if parent is None else parent.get_name(),
                "held_at": self.held or None,
                "distance_to_hand_cm": None if gap is None else round(gap, 3),
                "hand_moved_since_pickup_cm": None if moved is None else round(moved, 2),
                "tolerance_cm": HOLD_CM,
            },
        )
        world = game_world(self.builder)
        occupants = []
        for candidate in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor):
            if candidate.get_actor_label() in ("Floor", "Wall"):
                continue
            if (candidate.get_actor_location() - self.prop_origin).length() <= EMPTY_CM:
                occupants.append(candidate.get_actor_label())
        self.check(
            "pickup_empty",
            not occupants,
            {
                "occupants": occupants,
                "prop_moved_cm": round((self.prop.get_actor_location() - self.prop_origin).length(), 2),
                "radius_cm": EMPTY_CM,
            },
        )

    def bone(self, component, name):
        """Where a bone is relative to its own actor, so the actor walking does not count.

        It does not remove the clip's own travel: see the module docstring. Nor does
        `get_delta_transform_from_ref_pose`, tried first: it is a local translation, and a bone that
        only rotates keeps it constant.
        """
        if not name:
            return None
        try:
            return component.get_socket_location(name) - self.playing.get_actor_location()
        except Exception as error:  # noqa: BLE001
            self.builder.warn("the location of %s is unreadable: %s" % (name, error))
            return None

    def finish(self, aborted=None):
        if self.finished:
            return
        self.finished = True
        if self.handle is not None:
            unreal.unregister_slate_post_tick_callback(self.handle)
            self.handle = None
        self.report = self.build_report(aborted=aborted)
        if self.on_finished is not None:
            self.on_finished(self.report)

    def run(self):
        self.build()
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        for starter in ("editor_request_begin_play", "editor_play_simulate"):
            if hasattr(subsystem, starter):
                try:
                    getattr(subsystem, starter)()
                    self.started_with = starter
                    break
                except Exception as error:  # noqa: BLE001
                    self.builder.warn("%s failed: %s" % (starter, error))
        if self.started_with is None:
            raise OpError("UNSUPPORTED_CAPABILITY", "no way to start Play-In-Editor on this series")
        self.handle = unreal.register_slate_post_tick_callback(self.step)


def _published(ctx, asset_id, clip_id, builder):
    """The published mesh, and the clip to play: the one named, or the first when none is.

    A clip that is named and absent is not an error here. The bed runs without it and says which
    checks that fails, by name: that is the negative control, and it is what a caller needs to read.
    """
    version = ctx.next_version - 1
    if version < 1:
        raise OpError(
            "VALIDATION_FAILED",
            "asset %s has not been imported yet" % asset_id,
            recovery="run asset.import first",
        )
    content_path = "%s/%s/v%03d" % (ctx.destination_root, asset_id, version)
    mesh = None
    anims = []
    for path in unreal.EditorAssetLibrary.list_assets(content_path, recursive=True) or []:
        asset = unreal.EditorAssetLibrary.load_asset(str(path))
        kind = type(asset).__name__ if asset else ""
        if kind == "SkeletalMesh" and mesh is None:
            mesh = asset
        elif kind == "AnimSequence":
            anims.append((str(path).rsplit("/", 1)[-1].split(".")[0], asset))
    if mesh is None:
        raise OpError("VALIDATION_FAILED", "the published version has no skeletal mesh")
    if clip_id:
        # The importer names a clip A_<asset>_<clip_id>.
        named = [asset for name, asset in anims if name.endswith("_" + clip_id)]
        anim = named[0] if named else None
        if anim is None:
            builder.warn("clip %s is not in %s: the bed runs without a clip" % (clip_id, content_path))
    else:
        # The first clip whose id says walk; the first clip at all when none does.
        walks = [pair for pair in anims if "walk" in pair[0].lower()]
        chosen = (walks or anims or [(None, None)])[0]
        anim = chosen[1]
    if anim is None and not clip_id:
        raise OpError("VALIDATION_FAILED", "the published version has no animation")
    name = next((n for n, a in anims if a is anim), None) if anim is not None else None
    return content_path, version, mesh, anim, name


def run(ctx, request, builder):
    """Build the bed, play it, and wait for the ticks to finish before writing anything."""
    asset_id = request["target"].get("asset_id")
    instance = ctx.instance(asset_id)
    clip_id = (request.get("parameters") or {}).get("clip_id")
    content_path, version, mesh, anim, anim_name = _published(ctx, asset_id, clip_id, builder)

    def publish(report):
        """Called on the tick when the bed is done. Writes the result, then quits."""
        report["content_path"] = content_path
        report["version"] = version
        builder.write_report("smoke-report.json", report)
        builder.metrics.update(
            {
                "asset_id": asset_id,
                "version": version,
                "passed": report["passed"],
                "verdict": report["verdict"],
                "failed_checks": report["failed_checks"],
                "not_run_checks": report["not_run_checks"],
                "ticks": report["ticks"],
            }
        )
        for name in report["not_run_checks"]:
            builder.limit("check %s was not measured by this bed" % name)
        builder.limit(
            "this is the kit's test bed, not your game: one character, one clip, input injected by "
            "add_movement_input, no image"
        )
        errors = []
        status = "succeeded"
        if report["failed_checks"]:
            status = "failed"
            errors.append(
                {
                    "code": "VALIDATION_FAILED",
                    "message": "the prototype failed: %s" % ", ".join(report["failed_checks"]),
                    # A failed run publishes nothing, so the report stays where it was written.
                    "recovery": "read %s: each check says what it measured"
                    % os.path.join(ctx.out_dir, "smoke-report.json"),
                    "details": {"failed_checks": report["failed_checks"]},
                }
            )
        write_json_atomic(os.path.join(ctx.task_dir, "result.json"), builder.result(status, errors))
        unreal.SystemLibrary.quit_editor()

    bed = Bed(ctx, request, builder, mesh, anim, instance)
    bed.anim_name = anim_name
    bed.on_finished = publish
    bed.run()
    # The editor ticks from here. Waiting for it on this call is what would stop it ticking.
    return DEFERRED
