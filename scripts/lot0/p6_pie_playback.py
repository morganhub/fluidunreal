"""Lot 0 follow-up, proof P6: in a headless PIE session, does the clip's time advance at all?

P3 and the kit's test bed read a bone that never moves. A human has since watched the same clip play
in the animation editor, so the data is good. This separates the two remaining explanations:

- the playback position does not advance (nothing is playing), or
- it advances but the pose read from the component is never refreshed.

It spawns the same clip on a `Character` and on a plain `SkeletalMeshActor`, forces pose ticking on
both, and records every tick: the component's playback position, whether it says it is playing, and
the world location of two distal bones while nothing translates the actor. Rotation-only animation
leaves a bone's *local* translation unchanged, so world locations of a hand and a foot are what can
reveal a pose that moves.

Environment:
  FLUIDUNREAL_LOT0_OUT   absolute path of the JSON report to write
"""

import json
import os

import unreal

MESH = "/Game/Fluid/vitruvian/v001/vitruvian-walk/SkeletalMeshes/SK_vitruvian"
ANIM = "/Game/Fluid/vitruvian/v001/vitruvian-walk/SkeletalMeshes/A_vitruvian_walk-baked"
BONES = ("DEF-foot_L", "DEF-hand_L")
TICKS = 90


def force_ticking(component, notes, label):
    try:
        component.set_editor_property(
            "visibility_based_anim_tick_option",
            unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES,
        )
    except Exception as error:  # noqa: BLE001
        notes.append("%s: tick option refused: %s" % (label, error))
    for prop in ("enable_update_rate_optimizations", "no_skeleton_update"):
        try:
            component.set_editor_property(prop, False)
        except Exception as error:  # noqa: BLE001
            notes.append("%s: %s refused: %s" % (label, prop, error))


def arm(component, anim, notes, label):
    force_ticking(component, notes, label)
    try:
        component.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
        component.play_animation(anim, True)
    except Exception as error:  # noqa: BLE001
        notes.append("%s: play_animation failed: %s" % (label, error))


def read(component, label, notes):
    row = {}
    for name in ("get_position", "is_playing", "get_play_rate"):
        call = getattr(component, name, None)
        if call is None:
            row[name] = "absent"
            continue
        try:
            value = call()
            row[name] = round(value, 4) if isinstance(value, float) else value
        except Exception as error:  # noqa: BLE001
            row[name] = "raised: %s" % error
    for bone in BONES:
        try:
            location = component.get_socket_location(bone)
            row[bone] = [round(location.x, 3), round(location.y, 3), round(location.z, 3)]
        except Exception as error:  # noqa: BLE001
            row[bone] = "raised: %s" % error
    return row


class Probe(object):
    def __init__(self, report_path):
        self.report_path = report_path
        self.notes = []
        self.tick = 0
        self.handle = None
        self.anim = unreal.EditorAssetLibrary.load_asset(ANIM)
        self.mesh = unreal.EditorAssetLibrary.load_asset(MESH)
        self.subjects = None
        self.samples = {"Character": [], "SkeletalMeshActor": []}

    def build(self):
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        subsystem.new_level("/Game/Fluid/_probe/P6")
        cube = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube.Cube")
        floor = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.StaticMeshActor, unreal.Vector(0.0, 0.0, -50.0), unreal.Rotator(0.0, 0.0, 0.0)
        )
        floor.static_mesh_component.set_static_mesh(cube)
        floor.set_actor_scale3d(unreal.Vector(20.0, 20.0, 1.0))

        character = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.Character, unreal.Vector(0.0, -200.0, 100.0), unreal.Rotator(0.0, 0.0, 0.0)
        )
        character.set_actor_label("ProbeCharacter")
        character.mesh.set_skeletal_mesh_asset(self.mesh)
        arm(character.mesh, self.anim, self.notes, "editor Character")

        plain = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.SkeletalMeshActor, unreal.Vector(0.0, 200.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0)
        )
        plain.set_actor_label("ProbeSkeletalMeshActor")
        plain.skeletal_mesh_component.set_skeletal_mesh_asset(self.mesh)
        arm(plain.skeletal_mesh_component, self.anim, self.notes, "editor SkeletalMeshActor")

    def resolve(self):
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            return None
        found = {}
        for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
            label = actor.get_actor_label() if hasattr(actor, "get_actor_label") else actor.get_name()
            if "ProbeCharacter" in label or (
                isinstance(actor, unreal.Character) and "Character" not in found
            ):
                if isinstance(actor, unreal.Character):
                    found["Character"] = actor.mesh
            if isinstance(actor, unreal.SkeletalMeshActor):
                found["SkeletalMeshActor"] = actor.skeletal_mesh_component
        if len(found) < 2:
            return None
        for label, component in found.items():
            arm(component, self.anim, self.notes, "PIE " + label)
        return found

    def step(self, _delta):
        self.tick += 1
        if self.subjects is None:
            if self.tick > 120:
                self.finish("the PIE world never held both subjects")
                return
            self.subjects = self.resolve()
            if self.subjects is None:
                return
            self.ready = self.tick
        for label, component in self.subjects.items():
            row = read(component, label, self.notes)
            row["tick"] = self.tick - self.ready
            self.samples[label].append(row)
        if self.tick - self.ready >= TICKS:
            self.finish(None)

    def summarise(self):
        summary = {}
        for label, rows in self.samples.items():
            if not rows:
                summary[label] = "no samples"
                continue
            positions = [r.get("get_position") for r in rows if isinstance(r.get("get_position"), float)]
            travel = {}
            for bone in BONES:
                points = [r[bone] for r in rows if isinstance(r.get(bone), list)]
                if len(points) >= 2:
                    first = points[0]
                    travel[bone] = round(
                        max(sum((p[i] - first[i]) ** 2 for i in range(3)) ** 0.5 for p in points), 3
                    )
            summary[label] = {
                "position_first": positions[0] if positions else None,
                "position_last": positions[-1] if positions else None,
                "playback_advanced": (positions[-1] != positions[0]) if len(positions) >= 2 else None,
                "is_playing_last": rows[-1].get("is_playing"),
                "max_bone_travel_cm": travel,
            }
        return summary

    def finish(self, aborted):
        if self.handle is not None:
            unreal.unregister_slate_post_tick_callback(self.handle)
            self.handle = None
        report = {
            "proof": "P6",
            "engine": unreal.SystemLibrary.get_engine_version(),
            "aborted": aborted,
            "summary": self.summarise(),
            "notes": self.notes,
            "first_rows": {k: v[:3] for k, v in self.samples.items()},
            "last_rows": {k: v[-3:] for k, v in self.samples.items()},
        }
        with open(self.report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
        print("FLUIDUNREAL_PROBE=" + json.dumps({"proof": "P6", "summary": report["summary"]}))
        unreal.SystemLibrary.quit_editor()

    def run(self):
        self.build()
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_begin_play()
        self.handle = unreal.register_slate_post_tick_callback(self.step)


probe = Probe(os.environ["FLUIDUNREAL_LOT0_OUT"])
try:
    probe.run()
except Exception as error:  # noqa: BLE001 - a probe that cannot start must still say so
    probe.notes.append("could not start: %s" % error)
    probe.finish(str(error))
