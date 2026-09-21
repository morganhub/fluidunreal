"""game.smoke_test: play the imported character in a headless editor and report what happened.

The scene is built in code: a floor, a wall, a prop and a `Character` carrying the imported mesh.
No `.uasset` or `.umap` is shipped, so there is nothing to keep in step with the engine.

Four things lot 0 had to get right, each of which was wrong first and looked fine:

- `editor_request_begin_play`, not `editor_play_simulate`. Simulate-In-Editor left the pawn at the
  origin with zero velocity for 180 ticks: alive-looking, and measuring a statue.
- the measured actor lives in the PIE world; the editor actor never moves.
- `add_movement_input` needs `force=True` and a possessed pawn, or the input is dropped.
- the PIE duplicate does not inherit single-node playback: it has to be re-armed.

The report is written **before** the editor is asked to quit. A run that writes no report proves
nothing, and the engine treats a missing one as an unknown state rather than a failure.

**Known failure, unsolved.** `walk_clip_moves_bones` reads exactly 0.0 cm of bone travel over
fifteen samples: `play_animation` returns successfully on the PIE component, but the clip does not
advance. Lot 0 reported this check as passing, and it was wrong: its measuring window overlapped
the window in which the character was walking, so it measured the actor translating rather than the
skeleton deforming. Moving the window exposed it. Until this is solved, `game.smoke_test` stays
unavailable rather than shipping a test that cannot pass.
"""

import os

import unreal

from fluidunreal_runtime.errors import OpError
from fluidunreal_runtime.report import write_json_atomic

DEFERRED = "deferred"

CUBE = "/Engine/BasicShapes/Cube.Cube"
FLOOR_Z = 0.0
WALL_X = 400.0
PROP_X = 200.0
# The movement component parks the capsule slightly above the floor. Measured at 2.15 cm on 5.8.2,
# so the tolerance is 3 cm and the reason is written down rather than the number fudged.
FLOOR_TOLERANCE_CM = 3.0
TOTAL_TICKS = 180
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
        self.sample_bone = None
        self.first_bone = None
        self.start_x = None
        self.wall_samples = []
        self.closest_to_prop = None
        self.finished = False
        self.report = None
        self.on_finished = None
        self.ready_tick = 0
        self.bone_travel = 0.0
        self.tick_options = []

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
        }

    # --- scene --------------------------------------------------------------------------

    def build(self):
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        subsystem.new_level("/Game/Fluid/_testbed/SmokeBed")
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
        block("Prop", unreal.Vector(PROP_X, 0.0, 20.0), unreal.Vector(0.4, 0.4, 0.4))

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
        play_single_animation(component, self.anim, self.builder)

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
        self.play_via = play_single_animation(chosen.mesh, self.anim, self.builder)
        return chosen

    def probe_bone(self, component):
        wanted = [r["bone"].replace(".", "_") for r in self.instance.get("reference_pose") or []]
        try:
            present = set(str(component.get_bone_name(i)) for i in range(component.get_num_bones()))
        except Exception as error:  # noqa: BLE001
            self.builder.warn("the PIE skeleton could not be enumerated: %s" % error)
            return wanted[0] if wanted else None
        for name in wanted:
            if name in present:
                return name
        return next(iter(sorted(present)), None)

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
            count = component.get_num_bones()
            names = [str(component.get_bone_name(i)) for i in range(count)]
            added = [n for n in names if n.lower().endswith(PROXY_SUFFIX)]
            expected = int(self.instance.get("bone_count") or 0)
            self.check(
                "skeleton_bone_count",
                (count - len(added)) == expected if expected else None,
                {"got": count, "expected": expected, "added_by_importer": added},
            )
            self.check("walk_clip_found", self.anim is not None, {"played_via": self.play_via})
            self.start_x = actor.get_actor_location().x
        if step == 30:
            half = 88.0
            try:
                half = actor.capsule_component.get_scaled_capsule_half_height()
            except Exception as error:  # noqa: BLE001
                self.builder.warn("the capsule half height is unreadable: %s" % error)
            bottom = actor.get_actor_location().z - half
            self.check(
                "stands_on_floor",
                abs(bottom - FLOOR_Z) <= FLOOR_TOLERANCE_CM,
                {
                    "bottom_z": round(bottom, 3),
                    "half_height": round(half, 3),
                    "tolerance_cm": FLOOR_TOLERANCE_CM,
                    "why": "the movement component parks the capsule just above the floor",
                },
            )
            self.check(
                "walk_plays_looping",
                None,
                {
                    "api": self.play_via,
                    "why": "the call succeeded, which is not the same as the clip advancing; "
                    "walk_clip_moves_bones is what would measure that",
                },
            )
            self.sample_bone = self.probe_bone(component)
            self.first_bone = self.bone(component, self.sample_bone)
            self.check("idle_plays_nothing", None, "no idle clip in this bundle: not measured")
        if 30 < step <= 45 and self.first_bone is not None:
            # Sampled over a window, not at two instants: a toe can sit still between two phases
            # of a walk, and a single pair of samples then reports a clip that is playing as dead.
            here = self.bone(component, self.sample_bone)
            if here is not None:
                self.bone_travel = max(self.bone_travel, (here - self.first_bone).length())
        if step == 46:
            self.check(
                "walk_clip_moves_bones",
                None if self.first_bone is None else self.bone_travel > 0.01,
                {
                    "bone": self.sample_bone,
                    "max_travel_cm": round(self.bone_travel, 4),
                    "over_steps": [30, 45],
                },
            )
        if 45 < step <= 150:
            actor.add_movement_input(unreal.Vector(1.0, 0.0, 0.0), 1.0, True)
            position = actor.get_actor_location().x
            self.wall_samples.append(position)
            distance = abs(position - PROP_X)
            if self.closest_to_prop is None or distance < self.closest_to_prop:
                self.closest_to_prop = distance
        if step == 151:
            travelled = actor.get_actor_location().x - self.start_x
            self.check("character_moves", travelled > 10.0, {"delta_x_cm": round(travelled, 2)})
            peak = max(self.wall_samples) if self.wall_samples else 0.0
            # Both halves matter: it has to reach the wall and be stopped by it.
            self.check(
                "wall_stops_it",
                peak > PROP_X and peak <= WALL_X + 2.0,
                {"peak_x": round(peak, 2), "wall_x": WALL_X},
            )
            self.check(
                "reaches_pickup",
                self.closest_to_prop is not None and self.closest_to_prop < 50.0,
                {"closest_cm": round(self.closest_to_prop or -1.0, 2), "note": "closest approach"},
            )
        if step >= TOTAL_TICKS:
            self.check("back_to_idle", None, "no idle state in this bed: not measured")
            self.check("holds_prop", None, "prop attachment is not built in this lot")
            self.check("pickup_empty", None, "prop attachment is not built in this lot")
            self.finish()

    def bone(self, component, name):
        """How far this bone has moved from its reference pose.

        A world socket location also moves when the actor walks, which is how the first version of
        this check passed while measuring nothing about the clip. The delta from the rest pose
        cannot: it is zero unless the skeleton is actually deformed.
        """
        if not name:
            return None
        try:
            delta = component.get_delta_transform_from_ref_pose(name)
            return delta.translation
        except Exception as error:  # noqa: BLE001
            self.builder.warn("the delta from the ref pose of %s is unreadable: %s" % (name, error))
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


def _published(ctx, asset_id, builder):
    version = ctx.next_version - 1
    if version < 1:
        raise OpError(
            "VALIDATION_FAILED",
            "asset %s has not been imported yet" % asset_id,
            recovery="run asset.import first",
        )
    content_path = "%s/%s/v%03d" % (ctx.destination_root, asset_id, version)
    mesh = anim = None
    for path in unreal.EditorAssetLibrary.list_assets(content_path, recursive=True) or []:
        asset = unreal.EditorAssetLibrary.load_asset(str(path))
        kind = type(asset).__name__ if asset else ""
        if kind == "SkeletalMesh" and mesh is None:
            mesh = asset
        elif kind == "AnimSequence" and anim is None:
            anim = asset
    if mesh is None or anim is None:
        raise OpError(
            "VALIDATION_FAILED",
            "the published version has no %s" % ("skeletal mesh" if mesh is None else "animation"),
        )
    return content_path, version, mesh, anim


def run(ctx, request, builder):
    """Build the bed, play it, and wait for the ticks to finish before writing anything."""
    asset_id = request["target"].get("asset_id")
    instance = ctx.instance(asset_id)
    content_path, version, mesh, anim = _published(ctx, asset_id, builder)

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
        builder.limit("this is the kit's test bed, not your game: one character, one clip, no image")
        errors = []
        status = "succeeded"
        if report["failed_checks"]:
            status = "failed"
            errors.append(
                {
                    "code": "VALIDATION_FAILED",
                    "message": "the prototype failed: %s" % ", ".join(report["failed_checks"]),
                    "recovery": "read smoke-report.json: each check says what it measured",
                    "details": {"failed_checks": report["failed_checks"]},
                }
            )
        write_json_atomic(os.path.join(ctx.task_dir, "result.json"), builder.result(status, errors))
        unreal.SystemLibrary.quit_editor()

    bed = Bed(ctx, request, builder, mesh, anim, instance)
    bed.on_finished = publish
    bed.run()
    # The editor ticks from here. Waiting for it on this call is what would stop it ticking.
    return DEFERRED
