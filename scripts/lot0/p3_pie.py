"""Lot 0, proof P3: can a Play-In-Editor session be driven from Python, headless?

Builds the test bed in code (floor, wall, prop, character), starts PIE under -nullrhi, steps it
through the Slate post-tick callback at a fixed 1/60 s, and writes the 14 checks to JSON *before*
quitting. A run that writes no report proves nothing, so the report is written even on failure.

If this proof fails, the fallback is a Functional Test Blueprint driven by `Automation RunTests`,
and that decision goes in docs/compatibility-matrix.md with the output that forced it.

Environment:
  FLUIDUNREAL_LOT0_BUNDLE  bundle folder, to name the character and clip the checks look for
  FLUIDUNREAL_LOT0_OUT     absolute path of the JSON report to write
  FLUIDUNREAL_LOT0_MESH    content path of the SkeletalMesh imported by P2
  FLUIDUNREAL_LOT0_ANIM    content path of the AnimSequence imported by P2
"""

import json
import os
import time

import unreal

STEP_SECONDS = 1.0 / 60.0
CUBE = "/Engine/BasicShapes/Cube.Cube"
FLOOR_Z = 0.0
WALL_X = 400.0
PROP_X = 200.0


def play_single_animation(component, anim, notes):
    """Make a SkeletalMeshComponent loop one clip, whichever API this series exposes.

    5.8.2 has no `anim_to_play` property on the component: the first run died on it. Each candidate
    is tried and the one that worked is recorded, so the kit hard-codes a measured call rather than
    a remembered one.
    """
    for label, call in (
        ("play_animation", lambda: component.play_animation(anim, True)),
        ("set_animation+play", lambda: (component.set_animation(anim), component.play(True))),
        (
            "animation_data",
            lambda: component.set_editor_property(
                "animation_data",
                unreal.SingleAnimationPlayData(anim_to_play=anim, looping=True, playing=True),
            ),
        ),
    ):
        try:
            call()
            notes.append(f"the clip plays through {label}")
            return label
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{label} unavailable: {exc}")
    return None


def pie_character(notes):
    """The actor that actually simulates lives in the PIE world, not in the editor world.

    Measured on 5.8.2: reading the editor actor after `editor_play_simulate` shows a character that
    never falls, never moves and whose bones never change, because the simulation is running on a
    duplicate. Every check has to resolve the PIE actor first or it measures a statue.
    """
    for label, call in (
        ("UnrealEditorSubsystem", lambda: unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()),
        ("EditorLevelLibrary", lambda: unreal.EditorLevelLibrary.get_game_world()),
    ):
        try:
            world = call()
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{label}.get_game_world unavailable: {exc}")
            continue
        if world is None:
            continue
        try:
            found = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Character)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"get_all_actors_of_class failed on {label}: {exc}")
            continue
        if found:
            # Record every candidate: an empty level's game mode may spawn a pawn of its own, and
            # grabbing the wrong one measures a statue that never moves.
            notes.append(
                f"{label} found {len(found)} character(s): "
                + "; ".join(
                    f"{a.get_name()} at {a.get_actor_location()} mesh={a.mesh.get_skinned_asset() is not None if hasattr(a.mesh, 'get_skinned_asset') else 'unknown'}"
                    for a in found
                )
            )
            skinned = [
                a
                for a in found
                if hasattr(a.mesh, "get_skinned_asset") and a.mesh.get_skinned_asset() is not None
            ]
            chosen = skinned[0] if skinned else found[0]
            notes.append(f"the PIE character was resolved through {label}: {chosen.get_name()}")
            possess(chosen, world, notes)
            return chosen, world
    return None, None


def possess(actor, world, notes):
    """An unpossessed pawn ignores `add_movement_input`: nothing consumes its input vector."""
    try:
        controller = unreal.GameplayStatics.get_player_controller(world, 0)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"no player controller available: {exc}")
        return
    if controller is None:
        notes.append("no player controller in the PIE world: movement cannot be driven")
        return
    try:
        controller.possess(actor)
        notes.append(f"{actor.get_name()} possessed by {controller.get_name()}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"possess failed: {exc}")


class Bed:
    """The test bed and the 14 checks, stepped one tick at a time."""

    def __init__(self, report_path, mesh_path, anim_path, bundle):
        self.report_path = report_path
        self.mesh_path = mesh_path
        self.anim_path = anim_path
        self.bundle = bundle
        self.checks = {}
        self.notes = []
        self.started = time.monotonic()
        self.tick = 0
        self.handle = None
        self.character = None
        self.prop = None
        self.first_bone = None
        self.start_x = None
        self.wall_x_samples = []
        self.closest_to_prop = None
        self.sample_bone = None
        self.anim = None
        self.play_via = None
        self.playing = None
        self.trace = []
        self.started_with = None

    # --- reporting -------------------------------------------------------------------------
    def check(self, name, passed, detail=None):
        self.checks[name] = {"passed": bool(passed) if passed is not None else None, "detail": detail}

    def write(self, failed_early=None):
        report = {
            "proof": "P3",
            "played_via": self.play_via,
            "started_with": self.started_with,
            "engine": unreal.SystemLibrary.get_engine_version(),
            "headless": True,
            "checks": self.checks,
            "failed_checks": sorted(n for n, c in self.checks.items() if c["passed"] is False),
            "not_run_checks": sorted(n for n, c in self.checks.items() if c["passed"] is None),
            # A check that was not measured is never counted as a pass, and never as a failure
            # either: it is listed, and the verdict says how many there were.
            "passed": bool(self.checks)
            and not any(c["passed"] is False for c in self.checks.values())
            and any(c["passed"] is True for c in self.checks.values()),
            "verdict": (
                f"{sum(1 for c in self.checks.values() if c['passed'] is True)} measured and passed, "
                f"{sum(1 for c in self.checks.values() if c['passed'] is False)} failed, "
                f"{sum(1 for c in self.checks.values() if c['passed'] is None)} not measured by this bed"
            ),
            "aborted": failed_early,
            "notes": self.notes,
            "ticks": self.tick,
            "trace": self.trace,
            "wall_time_ms": int((time.monotonic() - self.started) * 1000),
        }
        with open(self.report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
        print("FLUIDUNREAL_PROBE=" + json.dumps({"proof": "P3", "passed": report["passed"]}))

    # --- scene -----------------------------------------------------------------------------
    def build(self):
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        subsystem.new_level("/Game/Lot0/P3Bed")
        cube = unreal.EditorAssetLibrary.load_asset(CUBE)

        def block(name, location, scale):
            actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                unreal.StaticMeshActor, location, unreal.Rotator(0.0, 0.0, 0.0)
            )
            actor.set_actor_label(name)
            actor.static_mesh_component.set_static_mesh(cube)
            actor.set_actor_scale3d(scale)
            return actor

        block("Floor", unreal.Vector(0.0, 0.0, -50.0), unreal.Vector(20.0, 20.0, 1.0))
        block("Wall", unreal.Vector(WALL_X, 0.0, 100.0), unreal.Vector(0.2, 10.0, 4.0))
        self.prop = block("Prop", unreal.Vector(PROP_X, 0.0, 20.0), unreal.Vector(0.4, 0.4, 0.4))

        self.character = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.Character, unreal.Vector(0.0, 0.0, 100.0), unreal.Rotator(0.0, 0.0, 0.0)
        )
        component = self.character.mesh
        mesh = unreal.EditorAssetLibrary.load_asset(self.mesh_path)
        for setter in ("set_skeletal_mesh_asset", "set_skeletal_mesh"):
            if hasattr(component, setter):
                getattr(component, setter)(mesh)
                break
        else:
            self.notes.append("no setter found for the skeletal mesh on the character")
        component.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
        anim = unreal.EditorAssetLibrary.load_asset(self.anim_path)
        self.anim = anim
        self.play_via = play_single_animation(component, anim, self.notes)
        if self.play_via is None:
            raise RuntimeError("no API on this series could make the component play a single clip")
        return component

    # --- checks ----------------------------------------------------------------------------
    def probe_bone(self, component):
        """A deform bone the bundle names, mapped to what Unreal called it (dots become underscores)."""
        instance = (self.bundle.get("instances") or [{}])[0]
        wanted = [r["bone"].replace(".", "_") for r in instance.get("reference_pose", [])]
        try:
            present = {str(component.get_bone_name(i)) for i in range(component.get_num_bones())}
        except Exception as exc:  # noqa: BLE001
            self.notes.append(f"bone enumeration unavailable on the PIE component: {exc}")
            return wanted[0] if wanted else "root"
        for name in wanted:
            if name in present:
                return name
        self.notes.append(f"none of the bundle's reference bones is in the PIE skeleton: {wanted}")
        return next(iter(sorted(present)), "root")

    def bone_transform(self, component, name):
        """P2 measured it: 5.8.2 has no `get_bone_location`; bones are read as sockets."""
        try:
            return component.get_socket_location(name)
        except Exception as exc:  # noqa: BLE001
            self.notes.append(f"socket location unavailable for {name}: {exc}")
            return None

    def step(self, _delta):
        self.tick += 1
        if self.playing is None and self.tick <= 10:
            self.playing, _world = pie_character(self.notes)
            if self.playing is None:
                return
            # The PIE duplicate does not inherit the editor component's single-node playback:
            # measured, the bones stopped moving under real PIE until it was re-armed here.
            self.play_via = play_single_animation(self.playing.mesh, self.anim, self.notes)
        actor = self.playing or self.character
        component = actor.mesh
        if self.tick in (1, 2, 5, 10, 30, 60, 90, 120, 150, 151, 180):
            location = actor.get_actor_location()
            velocity = None
            try:
                velocity = actor.character_movement.velocity
            except Exception:  # noqa: BLE001
                pass
            self.trace.append(
                {
                    "tick": self.tick,
                    "name": actor.get_name(),
                    "x": round(location.x, 2),
                    "z": round(location.z, 2),
                    "velocity_x": None if velocity is None else round(velocity.x, 2),
                    "velocity_z": None if velocity is None else round(velocity.z, 2),
                    "world_seconds": round(actor.get_world().get_time_seconds(), 3)
                    if hasattr(actor.get_world(), "get_time_seconds")
                    else None,
                }
            )
        try:
            if self.tick == 1:
                self.check("map_loaded", True, "PIE world obtained")
                self.check("character_spawned", self.playing is not None, {"in_pie_world": True})
                count = component.get_num_bones()
                expected = (self.bundle.get("instances") or [{}])[0].get("bone_count")
                # P2 measured it: the importer adds a proxy root on top of the bundle's bones.
                names = [str(component.get_bone_name(i)) for i in range(count)]
                added = [n for n in names if n.lower().endswith("proxytruerootjoint")]
                self.check(
                    "skeleton_bone_count",
                    count - len(added) == expected,
                    {"got": count, "expected": expected, "added_by_importer": added},
                )
                self.check("walk_clip_found", self.anim is not None, {"played_via": self.play_via})
                self.start_x = actor.get_actor_location().x
            if self.tick == 30:
                # Read the capsule instead of assuming 88: this character rests at 90.15.
                half_height = 88.0
                try:
                    half_height = actor.capsule_component.get_scaled_capsule_half_height()
                except Exception as exc:  # noqa: BLE001
                    self.notes.append(f"capsule half height unavailable, assuming 88: {exc}")
                bottom = actor.get_actor_location().z - half_height
                self.check(
                    "stands_on_floor",
                    abs(bottom - FLOOR_Z) <= 3.0,
                    {
                        "bottom_z": round(bottom, 3),
                        "half_height": round(half_height, 3),
                        "tolerance_cm": 3.0,
                        "why": "the movement component parks the capsule just above the floor",
                    },
                )
                self.check("walk_plays_looping", self.play_via is not None, {"api": self.play_via})
                # A named deform bone, sampled once the PIE mesh is really up: reading index 1 on
                # tick 1 gave an empty name and an unmeasurable check.
                self.sample_bone = self.probe_bone(component)
                self.first_bone = self.bone_transform(component, self.sample_bone)
                self.check("idle_plays_nothing", None, "no idle clip in the lot 0 bundle: not measured")
            if 30 < self.tick <= 150:
                # force=True: without it the controller drops the input and the pawn never moves.
                actor.add_movement_input(unreal.Vector(1.0, 0.0, 0.0), 1.0, True)
                position = actor.get_actor_location().x
                self.wall_x_samples.append(position)
                distance = abs(position - PROP_X)
                if self.closest_to_prop is None or distance < self.closest_to_prop:
                    self.closest_to_prop = distance
            if self.tick == 151:
                travelled = actor.get_actor_location().x - self.start_x
                self.check("character_moves", travelled > 10.0, {"delta_x_cm": travelled})
                peak = max(self.wall_x_samples) if self.wall_x_samples else 0.0
                # Both halves matter: it has to reach the wall and it has to be stopped by it.
                self.check(
                    "wall_stops_it",
                    peak > PROP_X and peak <= WALL_X + 2.0,
                    {"peak_x": round(peak, 2), "wall_x": WALL_X},
                )
                self.check(
                    "reaches_pickup",
                    self.closest_to_prop is not None and self.closest_to_prop < 50.0,
                    {"closest_cm": self.closest_to_prop, "note": "closest approach, not the final spot"},
                )
            if self.tick == 45:
                later = self.bone_transform(component, self.sample_bone)
                moved = None
                if self.first_bone is not None and later is not None:
                    moved = (later - self.first_bone).length() > 0.01
                self.check(
                    "walk_clip_moves_bones",
                    moved,
                    {"bone": self.sample_bone, "between_ticks": [30, 45]},
                )
            if self.tick == 180:
                self.check("back_to_idle", None, "no idle state in the lot 0 bed: not measured")
                self.check("holds_prop", None, "attachment is qualified by the kit, not by lot 0")
                self.check("pickup_empty", None, "attachment is qualified by the kit, not by lot 0")
                self.finish()
        except Exception as exc:  # noqa: BLE001
            self.notes.append(f"step {self.tick} raised: {exc}")
            self.finish(failed_early=str(exc))

    def finish(self, failed_early=None):
        if self.handle is not None:
            unreal.unregister_slate_post_tick_callback(self.handle)
            self.handle = None
        self.write(failed_early=failed_early)
        unreal.SystemLibrary.quit_editor()

    def run(self):
        self.build()
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        # Simulate-In-Editor left the pawn at the origin with zero velocity for 180 ticks: the world
        # was not simulating. Real Play-In-Editor is tried first now, and which one started is
        # recorded rather than assumed.
        self.notes.append(
            "PIE starters available: "
            + ", ".join(n for n in dir(subsystem) if "play" in n.lower() or "simulate" in n.lower())
        )
        for starter in ("editor_request_begin_play", "editor_play_simulate"):
            if hasattr(subsystem, starter):
                try:
                    getattr(subsystem, starter)()
                    self.started_with = starter
                    self.notes.append(f"PIE started with {starter}")
                    break
                except Exception as exc:  # noqa: BLE001
                    self.notes.append(f"{starter} failed: {exc}")
        else:
            self.notes.append("no PIE starter found on LevelEditorSubsystem")
        self.handle = unreal.register_slate_post_tick_callback(self.step)


def main():
    folder = os.environ["FLUIDUNREAL_LOT0_BUNDLE"]
    with open(os.path.join(folder, "handoff-bundle.json"), encoding="utf-8") as handle:
        bundle = json.load(handle)
    bed = Bed(
        os.environ["FLUIDUNREAL_LOT0_OUT"],
        os.environ["FLUIDUNREAL_LOT0_MESH"],
        os.environ["FLUIDUNREAL_LOT0_ANIM"],
        bundle,
    )
    try:
        bed.run()
    except Exception as exc:  # noqa: BLE001 - a proof that cannot start must still say so
        bed.notes.append(f"the bed could not start: {exc}")
        bed.write(failed_early=str(exc))
        unreal.SystemLibrary.quit_editor()


main()
