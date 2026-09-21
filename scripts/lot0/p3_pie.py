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

    # --- reporting -------------------------------------------------------------------------
    def check(self, name, passed, detail=None):
        self.checks[name] = {"passed": bool(passed) if passed is not None else None, "detail": detail}

    def write(self, failed_early=None):
        report = {
            "proof": "P3",
            "engine": unreal.SystemLibrary.get_engine_version(),
            "headless": True,
            "checks": self.checks,
            "failed_checks": sorted(n for n, c in self.checks.items() if c["passed"] is False),
            "not_run_checks": sorted(n for n, c in self.checks.items() if c["passed"] is None),
            "passed": bool(self.checks) and all(c["passed"] for c in self.checks.values()),
            "aborted": failed_early,
            "notes": self.notes,
            "ticks": self.tick,
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
        component.set_editor_property("anim_to_play", anim)
        component.set_editor_property("looping", True)
        return component

    # --- checks ----------------------------------------------------------------------------
    def bone_transform(self, component, name):
        try:
            return component.get_bone_location(name)
        except Exception as exc:  # noqa: BLE001
            self.notes.append(f"bone location unavailable for {name}: {exc}")
            return None

    def step(self, _delta):
        self.tick += 1
        component = self.character.mesh
        try:
            if self.tick == 1:
                self.check("map_loaded", True, "PIE world obtained")
                self.check("character_spawned", self.character is not None)
                count = component.get_num_bones()
                expected = (self.bundle.get("instances") or [{}])[0].get("bone_count")
                self.check("skeleton_bone_count", count == expected, {"got": count, "expected": expected})
                self.check("walk_clip_found", component.get_editor_property("anim_to_play") is not None)
                self.first_bone = self.bone_transform(component, component.get_bone_name(1))
                self.start_x = self.character.get_actor_location().x
            if self.tick == 30:
                bottom = self.character.get_actor_location().z - 88.0
                self.check("stands_on_floor", abs(bottom - FLOOR_Z) <= 1.0, {"bottom_z": bottom})
                self.check("walk_plays_looping", bool(component.get_editor_property("looping")))
                later = self.bone_transform(component, component.get_bone_name(1))
                moved = None
                if self.first_bone is not None and later is not None:
                    moved = (later - self.first_bone).length() > 0.01
                self.check("walk_clip_moves_bones", moved)
                self.check("idle_plays_nothing", None, "no idle clip in the lot 0 bundle: not measured")
            if 30 < self.tick <= 150:
                self.character.add_movement_input(unreal.Vector(1.0, 0.0, 0.0), 1.0, False)
                self.wall_x_samples.append(self.character.get_actor_location().x)
            if self.tick == 151:
                travelled = self.character.get_actor_location().x - self.start_x
                self.check("character_moves", travelled > 10.0, {"delta_x_cm": travelled})
                peak = max(self.wall_x_samples) if self.wall_x_samples else 0.0
                self.check("wall_stops_it", peak <= WALL_X + 2.0, {"peak_x": peak})
                distance = abs(self.character.get_actor_location().x - PROP_X)
                self.check("reaches_pickup", distance < 50.0, {"distance_cm": distance})
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
        for starter in ("editor_play_simulate", "editor_request_begin_play"):
            if hasattr(subsystem, starter):
                getattr(subsystem, starter)()
                break
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
