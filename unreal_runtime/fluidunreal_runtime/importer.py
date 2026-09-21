"""asset.import: bring the bundle's GLB in, read back what the editor really wrote, then publish.

Everything here is what lot 0 measured on 5.8.2, not what the documentation promises:

- Interchange is the import path; the legacy `GLTFImporter` plugin does not exist on this series.
- Bone names lose their dots: `DEF-big_toe.02.L` arrives as `DEF-big_toe_02_L`.
- The importer adds a proxy root joint, so the engine reports one bone more than the bundle.
- `SkeletalMeshComponent.get_bone_location` does not exist; bones are read as sockets.
- The animation arrives one frame short of the bundle: glTF sampling, tolerated and stated.
- A material instance and a physics asset are created even when the pipeline asks for neither. The
  knob has not been found, so they are reported rather than claimed away.

Nothing is published until every check against the bundle has passed. A failure cleans the staging
area and publishes nothing at all.
"""

import os
import shutil
import time

import unreal

from fluidunreal_runtime.errors import OpError
from fluidunreal_runtime.report import sha256_file

STAGING = "_staging"
PROXY_SUFFIX = "proxytruerootjoint"


def unreal_bone_name(blender_name):
    """Unreal cannot hold a dot in a bone name. Measured on 5.8.2, not assumed."""
    return blender_name.replace(".", "_")


def _pipeline(builder):
    """The import options, and an honest note about the ones that do not take."""
    try:
        pipeline = unreal.InterchangeGenericAssetsPipeline()
    except AttributeError as error:
        raise OpError(
            "MISSING_DEPENDENCY",
            "InterchangeGenericAssetsPipeline is not available: %s" % error,
            recovery="check that the Interchange plugins are enabled on this engine",
        ) from error
    for section, prop, value in (
        ("mesh_pipeline", "import_skeletal_meshes", True),
        ("mesh_pipeline", "import_static_meshes", False),
        ("mesh_pipeline", "create_physics_asset", False),
        ("animation_pipeline", "import_animations", True),
        ("material_pipeline", "import_materials", False),
    ):
        try:
            holder = pipeline.get_editor_property(section)
            holder.set_editor_property(prop, value)
        except Exception as error:  # noqa: BLE001 - a probe reports, it does not fail
            builder.warn("%s.%s could not be set: %s" % (section, prop, error))
    return pipeline


def _import(source, destination, builder):
    task = unreal.AssetImportTask()
    task.filename = source
    task.destination_path = destination
    task.automated = True
    task.save = True
    task.replace_existing = True
    try:
        task.set_editor_property("options", _pipeline(builder))
    except Exception as error:  # noqa: BLE001
        builder.warn("the Interchange pipeline could not be attached: %s" % error)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    created = [str(p) for p in (unreal.EditorAssetLibrary.list_assets(destination, recursive=True) or [])]
    if not created:
        raise OpError(
            "VALIDATION_FAILED",
            "the importer created nothing from %s" % os.path.basename(source),
            recovery="read unreal.log: Interchange logs why it refused the file",
        )
    return created


def _by_class(paths):
    found = {}
    for path in paths:
        asset = unreal.EditorAssetLibrary.load_asset(path)
        if asset is None:
            continue
        found.setdefault(type(asset).__name__, []).append((path, asset))
    return found


def _bones(mesh, builder):
    """Bone names, read through a spawned component: the skeleton's own API is not exposed."""
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SkeletalMeshActor, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0)
    )
    component = actor.skeletal_mesh_component
    for setter in ("set_skeletal_mesh_asset", "set_skeletal_mesh"):
        if hasattr(component, setter):
            getattr(component, setter)(mesh)
            break
    else:
        actor.destroy_actor()
        raise OpError("INTERNAL_ERROR", "no setter for the skeletal mesh on this series")
    try:
        names = [str(component.get_bone_name(i)) for i in range(component.get_num_bones())]
    except Exception as error:  # noqa: BLE001
        names = []
        builder.warn("the bones could not be enumerated: %s" % error)
    actor.destroy_actor()
    return names


def _check_against_bundle(ctx, instance, created, builder):
    """What the engine wrote, compared to what the bundle said. A mismatch publishes nothing."""
    meshes = created.get("SkeletalMesh") or []
    if len(meshes) != 1:
        raise OpError(
            "VALIDATION_FAILED",
            "expected one skeletal mesh, the importer made %d" % len(meshes),
            details={"created": sorted(created)},
        )
    mesh_path, mesh = meshes[0]
    bones = _bones(mesh, builder)
    added = [name for name in bones if name.lower().endswith(PROXY_SUFFIX)]
    expected = int(instance.get("bone_count") or 0)
    if expected and len(bones) - len(added) != expected:
        raise OpError(
            "VALIDATION_FAILED",
            "the bundle declares %d bones, the import has %d (%d added by the importer)"
            % (expected, len(bones), len(added)),
            details={"added_by_importer": added, "sample": bones[:10]},
        )

    clips = ctx.clips_for(instance["instance_id"])
    sequences = created.get("AnimSequence") or []
    if clips and len(sequences) != len(clips):
        raise OpError(
            "VALIDATION_FAILED",
            "the bundle declares %d clip(s), the import has %d animation(s)" % (len(clips), len(sequences)),
        )
    for index, (_path, sequence) in enumerate(sequences):
        if index >= len(clips):
            break
        clip = clips[index]
        span = clip.get("frame_range") or {}
        declared = int(span.get("end_exclusive", 0)) - int(span.get("start", 0))
        try:
            frames = int(sequence.get_editor_property("number_of_sampled_frames"))
        except Exception as error:  # noqa: BLE001
            builder.warn("the frame count of %s is unreadable: %s" % (clip.get("clip_id"), error))
            continue
        if declared and abs(frames - declared) > 1:
            raise OpError(
                "VALIDATION_FAILED",
                "clip %s declares %d frames, the import has %d" % (clip.get("clip_id"), declared, frames),
            )
        if declared and frames != declared:
            builder.limit(
                "clip %s arrived at %d frames against the bundle's %d: glTF sampling, within the "
                "one-frame tolerance" % (clip.get("clip_id"), frames, declared)
            )
    return mesh_path, bones, added


def _rename(created, asset_id, clips, builder):
    """Deterministic names, so the rest of the kit and the test bed can find things."""
    renamed = {}
    plan = []
    for path, _asset in created.get("Skeleton") or []:
        plan.append((path, "SKEL_%s" % asset_id))
    for path, _asset in created.get("SkeletalMesh") or []:
        plan.append((path, "SK_%s" % asset_id))
    for path, _asset in created.get("PhysicsAsset") or []:
        plan.append((path, "PA_%s" % asset_id))
    for index, (path, _asset) in enumerate(created.get("AnimSequence") or []):
        clip_id = clips[index].get("clip_id") if index < len(clips) else "clip%02d" % index
        plan.append((path, "A_%s_%s" % (asset_id, clip_id)))

    for path, new_name in plan:
        folder = path.rsplit("/", 1)[0].split(".")[0]
        target = "%s/%s" % (folder, new_name)
        try:
            if unreal.EditorAssetLibrary.rename_asset(path, target):
                renamed[path] = target
            else:
                builder.warn("could not rename %s to %s" % (path, new_name))
        except Exception as error:  # noqa: BLE001
            builder.warn("could not rename %s: %s" % (path, error))
    return renamed


def _mark(created, ctx, instance, builder):
    """Identity tags, so a later run can tell where a piece of content came from."""
    bundle_id = ctx.bundle.get("bundle_id", "")
    model = None
    for entry in ctx.bundle.get("files") or []:
        if entry.get("role") == "model":
            model = entry.get("sha256")
    for assets in created.values():
        for path, asset in assets:
            for key, value in (
                ("fluid_instance_id", instance.get("instance_id", "")),
                ("fluid_asset_id", instance.get("asset_id", "")),
                ("fluid_bundle_id", bundle_id),
                ("fluid_bundle_sha256", model or ""),
            ):
                try:
                    unreal.EditorAssetLibrary.set_metadata_tag(asset, key, str(value))
                except Exception as error:  # noqa: BLE001
                    builder.warn("could not tag %s: %s" % (path, error))
                    return


def _root_motion(created, clips, builder):
    for index, (_path, sequence) in enumerate(created.get("AnimSequence") or []):
        if index >= len(clips):
            break
        wanted = clips[index].get("root_motion") != "in_place"
        try:
            sequence.set_editor_property("enable_root_motion", wanted)
        except Exception as error:  # noqa: BLE001
            builder.warn("enable_root_motion could not be set: %s" % error)


def _publish(ctx, asset_id, staging, builder):
    """Move the staging folder to its version. A version that exists is never overwritten."""
    destination = "%s/%s/v%03d" % (ctx.destination_root, asset_id, ctx.next_version)
    if unreal.EditorAssetLibrary.does_directory_exist(destination):
        raise OpError(
            "SCENE_CONFLICT",
            "%s already exists" % destination,
            recovery="a published version is never overwritten; import again to make the next one",
        )
    if not unreal.EditorAssetLibrary.rename_directory(staging, destination):
        raise OpError("INTERNAL_ERROR", "could not publish %s to %s" % (staging, destination))
    unreal.EditorAssetLibrary.save_directory(destination, only_if_is_dirty=False, recursive=True)
    return destination


def _written_files(ctx, asset_id, builder):
    """The .uasset files on disk, with their hashes: what the engine verifies before publication."""
    if not ctx.content_root:
        return {}
    folder = os.path.join(ctx.content_root, asset_id, "v%03d" % ctx.next_version)
    written = {}
    for base, _dirs, names in os.walk(folder):
        for name in sorted(names):
            if name.endswith(".uasset") or name.endswith(".umap"):
                path = os.path.join(base, name)
                written[os.path.relpath(path, ctx.content_root).replace(os.sep, "/")] = sha256_file(path)
    if not written:
        builder.warn("no .uasset was found on disk under %s" % folder)
    return written


def _clean_staging(ctx, staging, builder):
    """Remove the staging area from the asset registry and from disk.

    `delete_directory` empties the registry but leaves the folder behind, so a later inspect finds
    a stray `_staging` under the content root and the kit looks like it does not clean up. Only an
    empty folder is removed: real content is never deleted by a cleanup path.
    """
    try:
        if unreal.EditorAssetLibrary.does_directory_exist(staging):
            unreal.EditorAssetLibrary.delete_directory(staging)
    except Exception as error:  # noqa: BLE001
        builder.warn("the staging registry entry could not be removed: %s" % error)
    if not ctx.content_root:
        return
    relative = staging[len(ctx.destination_root) :].lstrip("/").replace("/", os.sep)
    folder = os.path.join(ctx.content_root, relative)
    for base in (folder, os.path.dirname(folder)):
        if not base or not os.path.isdir(base):
            continue
        remaining = [
            name
            for _root, _dirs, names in os.walk(base)
            for name in names
            if name.endswith(".uasset") or name.endswith(".umap")
        ]
        if remaining:
            builder.warn("%s still holds %d asset(s): left alone" % (base, len(remaining)))
            return
        try:
            shutil.rmtree(base)
        except OSError as error:
            builder.warn("the staging folder could not be removed: %s" % error)
            return


def run(ctx, request, builder):
    parameters = request.get("parameters") or {}
    instance = ctx.instance(parameters.get("asset_id") or request["target"].get("asset_id"))
    asset_id = instance["asset_id"]
    source = ctx.bundle_file("model")
    staging = "%s/%s/%s" % (ctx.destination_root, STAGING, ctx.task_id)

    try:
        created_paths = _import(source, staging, builder)
        created = _by_class(created_paths)
        _mesh_path, bones, added = _check_against_bundle(ctx, instance, created, builder)

        clips = ctx.clips_for(instance["instance_id"])
        _root_motion(created, clips, builder)
        renamed = _rename(created, asset_id, clips, builder)
        _mark(created, ctx, instance, builder)
        unreal.EditorAssetLibrary.save_directory(staging, only_if_is_dirty=False, recursive=True)
        pause = float(ctx.test_hooks.get("pause_before_publish_s") or 0)
        if pause:
            # Test only (U12): the staging is on disk and nothing is published. An editor killed
            # here is the interruption the kit must conclude without guessing.
            time.sleep(pause)
        published = _publish(ctx, asset_id, staging, builder)
        _clean_staging(ctx, staging, builder)
    except BaseException:
        # Nothing half-imported is left behind for the next run to trip over.
        _clean_staging(ctx, staging, builder)
        raise

    extras = sorted(k for k in created if k in ("MaterialInstanceConstant", "PhysicsAsset"))
    if extras:
        builder.limit(
            "the importer also created %s: the pipeline option that suppresses them has not been "
            "found on this series, so they are reported rather than claimed away" % ", ".join(extras)
        )
    if added:
        builder.limit(
            "the importer added %s on top of the bundle's bones: counted apart, never against it"
            % ", ".join(added)
        )

    report = {
        "bundle_id": ctx.bundle.get("bundle_id"),
        "asset_id": asset_id,
        "instance_id": instance.get("instance_id"),
        "version": ctx.next_version,
        "content_path": published,
        "bone_count": len(bones) - len(added),
        "bones_added_by_importer": added,
        "animations": [name for name in renamed.values() if "/A_" in name],
        "created": {kind: [p for p, _a in assets] for kind, assets in created.items()},
        "renamed": renamed,
        "uassets": _written_files(ctx, asset_id, builder),
    }
    builder.write_report("import-report.json", report)
    builder.changed_entity("asset", asset_id, "created")
    builder.metrics.update(
        {
            "asset_id": asset_id,
            "version": ctx.next_version,
            "content_path": published,
            "bone_count": report["bone_count"],
            "animations": len(created.get("AnimSequence") or []),
            "uassets": len(report["uassets"]),
        }
    )
    builder.next_safe_actions.append(
        "run asset.audit on %s to measure the scale and the animation lengths" % asset_id
    )
