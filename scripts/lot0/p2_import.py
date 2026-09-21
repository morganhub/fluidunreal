"""Lot 0, proof P2: does Interchange import a skinned, animated GLB, and at what scale?

Reads a hand-off bundle (produced by fluidblend), imports its GLB, then *measures* what the engine
wrote: bone count, animation length, and the world height of a reference bone against the bundle's
reference pose. A measurement that cannot be taken is recorded as null, never as a pass.

Environment:
  FLUIDUNREAL_LOT0_BUNDLE  absolute path to the bundle folder (containing handoff-bundle.json)
  FLUIDUNREAL_LOT0_OUT     absolute path of the JSON report to write
"""

import json
import os
import time

import unreal

STAGING = "/Game/Lot0/P2"
CM_PER_M = 100.0


def read_bundle():
    folder = os.environ["FLUIDUNREAL_LOT0_BUNDLE"]
    with open(os.path.join(folder, "handoff-bundle.json"), encoding="utf-8") as handle:
        bundle = json.load(handle)
    model = next(f for f in bundle["files"] if f["role"] == "model")
    return bundle, os.path.join(folder, model["path"].replace("/", os.sep))


def build_task(source):
    """Interchange through AssetImportTask. Every option here is what P2 exists to confirm."""
    task = unreal.AssetImportTask()
    task.filename = source
    task.destination_path = STAGING
    task.automated = True
    task.save = False
    task.replace_existing = True
    notes = []
    try:
        pipeline = unreal.InterchangeGenericAssetsPipeline()
        for holder, prop, value in (
            ("mesh_pipeline", "import_skeletal_meshes", True),
            ("mesh_pipeline", "import_static_meshes", False),
            ("mesh_pipeline", "create_physics_asset", False),
            ("animation_pipeline", "import_animations", True),
            ("material_pipeline", "import_materials", False),
        ):
            try:
                section = pipeline.get_editor_property(holder)
                section.set_editor_property(prop, value)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"{holder}.{prop} not settable: {exc}")
        try:
            task.set_editor_property("options", pipeline)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"task.options rejected the pipeline: {exc}")
    except AttributeError as exc:
        notes.append(f"InterchangeGenericAssetsPipeline unavailable: {exc}")
    return task, notes


def created_assets(task):
    paths = []
    for attribute in ("imported_object_paths", "result"):
        try:
            value = task.get_editor_property(attribute)
        except Exception:  # noqa: BLE001
            continue
        if value:
            paths = [str(p) for p in value]
            break
    if not paths:
        paths = [str(p) for p in unreal.EditorAssetLibrary.list_assets(STAGING, recursive=True)]
    out = []
    for path in paths:
        asset = unreal.EditorAssetLibrary.load_asset(path)
        out.append(
            {
                "path": path,
                "class": type(asset).__name__ if asset else None,
                "name": asset.get_name() if asset else None,
            }
        )
    return out


def measure_skeleton(assets, bundle, notes):
    """Bone count and the world height of one reference bone, in centimetres.

    Reading a reference pose straight off the Skeleton is not reliably exposed to Python, so the
    mesh is spawned in the level and the bone is read through the component. That is the fallback
    the kit will use if the direct API turns out to be unavailable.
    """
    entry = next((a for a in assets if a["class"] == "SkeletalMesh"), None)
    if entry is None:
        notes.append("no SkeletalMesh was created: nothing to measure")
        return {"bone_count": None, "bones_sampled": [], "scale_checks": []}
    mesh = unreal.EditorAssetLibrary.load_asset(entry["path"])
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SkeletalMeshActor, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0)
    )
    component = actor.skeletal_mesh_component
    for setter in ("set_skeletal_mesh_asset", "set_skeletal_mesh"):
        if hasattr(component, setter):
            getattr(component, setter)(mesh)
            break
    else:
        notes.append("no setter found for the skeletal mesh on the component")
    names = [str(n) for n in component.get_all_socket_names()] if hasattr(component, "get_all_socket_names") else []
    try:
        bone_count = component.get_num_bones()
        bones = [str(component.get_bone_name(i)) for i in range(bone_count)]
    except Exception as exc:  # noqa: BLE001
        notes.append(f"bone enumeration unavailable: {exc}")
        bone_count, bones = None, []

    checks = []
    instance = (bundle.get("instances") or [{}])[0]
    for reference in instance.get("reference_pose", []):
        bone = reference["bone"]
        expected_cm = reference["head_m"][2] * CM_PER_M
        observed = None
        if bone in bones:
            try:
                observed = component.get_bone_location(bone).z
            except Exception as exc:  # noqa: BLE001
                notes.append(f"bone location unavailable for {bone}: {exc}")
        else:
            notes.append(f"reference bone {bone} is not in the imported skeleton")
        checks.append(
            {
                "kind": "scale_check",
                "bone": bone,
                "space": "world",
                "unit": "cm",
                "expected": round(expected_cm, 3),
                "observed": None if observed is None else round(observed, 3),
                "tolerance": 1.0,
                "passed": None if observed is None else abs(observed - expected_cm) <= 1.0,
            }
        )
    actor.destroy_actor()
    return {"bone_count": bone_count, "bones_sampled": bones[:10], "sockets": names, "scale_checks": checks}


def measure_animations(assets, bundle, notes):
    out = []
    clips = {c["gltf_animation_name"]: c for c in bundle.get("clips", [])}
    fps = bundle["fps"]["numerator"] / bundle["fps"]["denominator"]
    for entry in [a for a in assets if a["class"] == "AnimSequence"]:
        anim = unreal.EditorAssetLibrary.load_asset(entry["path"])
        facts = {"path": entry["path"], "name": entry["name"]}
        for label, prop in (("frames", "number_of_sampled_frames"), ("seconds", "sequence_length")):
            try:
                facts[label] = anim.get_editor_property(prop)
            except Exception as exc:  # noqa: BLE001
                facts[label] = None
                notes.append(f"{entry['name']}.{prop} unavailable: {exc}")
        clip = next((c for name, c in clips.items() if name.endswith(entry["name"])), None)
        if clip:
            expected = clip["frame_range"]["end_exclusive"] - clip["frame_range"]["start"]
            facts["expected_frames"] = expected
            facts["expected_seconds"] = round(expected / fps, 4)
            facts["frames_within_one"] = (
                None if facts.get("frames") is None else abs(facts["frames"] - expected) <= 1
            )
        out.append(facts)
    return out


def main():
    started = time.monotonic()
    notes = []
    bundle, source = read_bundle()
    task, build_notes = build_task(source)
    notes.extend(build_notes)
    import_started = time.monotonic()
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    import_seconds = round(time.monotonic() - import_started, 3)

    assets = created_assets(task)
    report = {
        "proof": "P2",
        "source": source,
        "bundle_id": bundle["bundle_id"],
        "engine_version": unreal.SystemLibrary.get_engine_version(),
        "import_seconds": import_seconds,
        "assets": assets,
        "skeleton": measure_skeleton(assets, bundle, notes),
        "animations": measure_animations(assets, bundle, notes),
        "expected_bone_count": (bundle.get("instances") or [{}])[0].get("bone_count"),
        "notes": notes,
        "total_seconds": round(time.monotonic() - started, 3),
    }
    with open(os.environ["FLUIDUNREAL_LOT0_OUT"], "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    print("FLUIDUNREAL_PROBE=" + json.dumps({"proof": "P2", "assets": len(assets), "notes": len(notes)}))
    unreal.log("fluidunreal lot0 P2 import finished")


main()
