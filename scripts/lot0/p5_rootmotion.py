"""Lot 0, proof P5: root motion, measured rather than assumed.

Enables root motion on the imported clip and measures how far the root bone actually travels over
it, against the bundle's `stride_m * repetitions`. Also qualifies the `object` case (an animated
node with no bone): either it converts, or the kit refuses it and says so.

Environment:
  FLUIDUNREAL_LOT0_BUNDLE  bundle folder
  FLUIDUNREAL_LOT0_OUT     absolute path of the JSON report to write
  FLUIDUNREAL_LOT0_ANIM    content path of the AnimSequence imported by P2
"""

import json
import os

import unreal

CM_PER_M = 100.0
TOLERANCE_CM = 2.0


def root_bone_name(anim, notes):
    """Bone 0 of the skeleton, not the first animation track.

    Measured: the first track was `def-thigh_l`, a thigh that swings 57.5 cm during a walk. Reading
    it as root travel would have reported an in-place clip as travelling half a metre.
    """
    mesh_path = os.environ.get("FLUIDUNREAL_LOT0_MESH")
    if mesh_path:
        try:
            mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
            actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                unreal.SkeletalMeshActor, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0)
            )
            component = actor.skeletal_mesh_component
            for setter in ("set_skeletal_mesh_asset", "set_skeletal_mesh"):
                if hasattr(component, setter):
                    getattr(component, setter)(mesh)
                    break
            name = str(component.get_bone_name(0))
            actor.destroy_actor()
            notes.append(f"the root bone is {name} (bone 0 of the imported skeleton)")
            return name
        except Exception as exc:  # noqa: BLE001
            notes.append(f"the skeleton root could not be read: {exc}")
    try:
        names = unreal.AnimationLibrary.get_animation_track_names(anim)
        if names:
            notes.append(f"falling back to the first animation track: {names[0]}")
            return str(names[0])
    except Exception as exc:  # noqa: BLE001
        notes.append(f"track names unavailable: {exc}")
    return "root"


def travel_over_clip(anim, bone, frames, notes):
    """Horizontal distance the bone covers between the first and last frame of the clip."""
    positions = []
    for frame in (0, max(frames - 1, 0)):
        try:
            transform = unreal.AnimationLibrary.get_bone_pose_for_frame(anim, bone, frame, True)
            positions.append(transform.translation)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"get_bone_pose_for_frame({bone}, {frame}) unavailable: {exc}")
            return None
    delta = positions[-1] - positions[0]
    return (delta.x**2 + delta.y**2) ** 0.5


def main():
    notes = []
    folder = os.environ["FLUIDUNREAL_LOT0_BUNDLE"]
    with open(os.path.join(folder, "handoff-bundle.json"), encoding="utf-8") as handle:
        bundle = json.load(handle)
    anim = unreal.EditorAssetLibrary.load_asset(os.environ["FLUIDUNREAL_LOT0_ANIM"])
    clip = (bundle.get("clips") or [{}])[0]

    report = {
        "proof": "P5",
        "engine": unreal.SystemLibrary.get_engine_version(),
        "clip_id": clip.get("clip_id"),
        "declared_root_motion": clip.get("root_motion"),
        "notes": notes,
    }

    enabled = None
    try:
        anim.set_editor_property("enable_root_motion", clip.get("root_motion") != "in_place")
        unreal.EditorAssetLibrary.save_loaded_asset(anim)
        enabled = anim.get_editor_property("enable_root_motion")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"enable_root_motion unavailable: {exc}")
    report["enable_root_motion"] = enabled

    frames = None
    try:
        frames = anim.get_editor_property("number_of_sampled_frames")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"number_of_sampled_frames unavailable: {exc}")
    bone = root_bone_name(anim, notes)
    observed = travel_over_clip(anim, bone, frames or 0, notes) if frames else None

    stride = clip.get("stride_m")
    repetitions = clip.get("repetitions") or 1
    expected = None if stride is None else stride * repetitions * CM_PER_M
    if clip.get("root_motion") == "in_place":
        # An in-place clip must stay put: more than a centimetre of travel means it is not in place.
        passed = None if observed is None else observed < 1.0
        expected = 0.0
    else:
        passed = None if (observed is None or expected is None) else abs(observed - expected) <= TOLERANCE_CM

    report["measurement"] = {
        "kind": "root_motion_travel",
        "bone": bone,
        "space": "component",
        "unit": "cm",
        "expected": None if expected is None else round(expected, 3),
        "observed": None if observed is None else round(observed, 3),
        "tolerance": TOLERANCE_CM,
        "passed": passed,
    }
    # A zero that nobody cross-checked is not evidence: read a bone that must move, with the same
    # API. A walk cycle swings the thigh, so a large number there proves the reader works and that
    # the root's zero is a real zero rather than a broken call.
    control_bone, control_travel = None, None
    try:
        tracks = [str(n) for n in unreal.AnimationLibrary.get_animation_track_names(anim)]
        control_bone = next((n for n in tracks if "thigh" in n.lower()), tracks[0] if tracks else None)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"no control bone could be chosen: {exc}")
    if control_bone and frames:
        control_travel = travel_over_clip(anim, control_bone, frames, notes)
    report["negative_control"] = {
        "bone": control_bone,
        "travel_cm": None if control_travel is None else round(control_travel, 3),
        "reader_works": None if control_travel is None else control_travel > 1.0,
        "why": "the same call on a bone that must move; without it the root's zero proves nothing",
    }

    # The `object` case (an animated node with no bone) is qualified, never guessed at.
    report["object_case"] = {
        "present_in_bundle": any(c.get("root_motion") == "object" for c in bundle.get("clips", [])),
        "verdict": "not_qualified_by_this_run",
        "note": "if it appears, the kit either converts it or refuses it with a handoff.request",
    }
    with open(os.environ["FLUIDUNREAL_LOT0_OUT"], "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    print("FLUIDUNREAL_PROBE=" + json.dumps({"proof": "P5", "passed": passed}))
    unreal.SystemLibrary.quit_editor()


main()
