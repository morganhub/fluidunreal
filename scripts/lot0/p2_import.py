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


def unreal_bone_name(blender_name):
    """Unreal cannot hold a dot in a bone name: `DEF-big_toe.02.L` arrives as `DEF-big_toe_02_L`.

    Measured on 5.8.2, not assumed. The kit must map names, not compare them raw, or every
    reference-pose lookup silently misses and the scale check reports `not_run` forever.
    """
    return blender_name.replace(".", "_")


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
    # The assets must survive this editor: P3 opens a fresh one and loads them by path.
    task.save = True
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
        # Two ways to hand a pipeline over. The first run showed materials and a PhysicsAsset being
        # created anyway, so whether either actually takes is exactly what this proof must settle.
        attached = []
        try:
            task.set_editor_property("options", pipeline)
            attached.append("task.options")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"task.options rejected the pipeline: {exc}")
        for holder in ("pipelines", "override_pipelines"):
            try:
                task.set_editor_property(holder, [pipeline])
                attached.append(f"task.{holder}")
            except Exception as exc:  # noqa: BLE001
                notes.append(f"task.{holder} unavailable: {exc}")
        notes.append(f"pipeline attached through: {attached or 'nothing'}")
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
    try:
        bone_count = component.get_num_bones()
        bones = [str(component.get_bone_name(i)) for i in range(bone_count)]
    except Exception as exc:  # noqa: BLE001
        notes.append(f"bone enumeration unavailable: {exc}")
        bone_count, bones = None, []

    def bone_world_z(name):
        """5.8.2 has no `get_bone_location`; bones are exposed as sockets, so read them that way."""
        for getter, label in (
            ("get_socket_location", "socket"),
            ("get_bone_transform", "transform"),
        ):
            call = getattr(component, getter, None)
            if call is None:
                continue
            try:
                value = call(name)
                return (value.translation.z if label == "transform" else value.z), getter
            except Exception as exc:  # noqa: BLE001
                notes.append(f"{getter}({name}) failed: {exc}")
        return None, None

    checks = []
    instance = (bundle.get("instances") or [{}])[0]
    for reference in instance.get("reference_pose", []):
        blender_bone = reference["bone"]
        bone = unreal_bone_name(blender_bone)
        expected_cm = reference["head_m"][2] * CM_PER_M
        observed, via = None, None
        if bone in bones:
            observed, via = bone_world_z(bone)
        else:
            notes.append(f"reference bone {blender_bone} (as {bone}) is not in the imported skeleton")
        checks.append(
            {
                "kind": "scale_check",
                "bone": blender_bone,
                "unreal_bone": bone,
                "read_with": via,
                "space": "world",
                "unit": "cm",
                "expected": round(expected_cm, 3),
                "observed": None if observed is None else round(observed, 3),
                "tolerance": 1.0,
                "passed": None if observed is None else abs(observed - expected_cm) <= 1.0,
            }
        )
    expected_count = instance.get("bone_count")
    extra = [b for b in bones if b.lower().endswith("proxytruerootjoint")]
    if expected_count is not None and bone_count == expected_count + len(extra) and extra:
        notes.append(
            f"the importer added {extra} on top of the bundle's {expected_count} bones: "
            "the audit must count the bundle's bones, not the engine's total"
        )
    actor.destroy_actor()
    return {
        "bone_count": bone_count,
        "added_by_importer": extra,
        "bones_sampled": bones[:10],
        "scale_checks": checks,
    }


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
        # The importer names the sequence after the file, not after the glTF animation, so match on
        # the file stem rather than on the animation name. Recorded because it decides how
        # `asset.import` renames things: `A_<asset_id>_<clip_id>` cannot be derived from the
        # imported name alone when a GLB carries several clips.
        clip = next((c for name, c in clips.items() if entry["name"].startswith(name.split(".")[0])), None)
        if clip is None and len(clips) == 1:
            clip = next(iter(clips.values()))
            facts["matched_by"] = "the GLB carries a single clip"
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
    saved = unreal.EditorAssetLibrary.save_directory(STAGING, only_if_is_dirty=False, recursive=True)
    if not saved:
        notes.append("save_directory reported nothing saved: the next proof may find no assets")
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
