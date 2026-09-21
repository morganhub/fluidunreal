"""asset.audit: measure what the engine wrote, against what the bundle said.

Every measurement carries its space, its unit and its tolerance, and `passed` is three-valued. A
measurement that could not be taken is `None`: never a pass, and never a defect in the asset either.

What lot 0 settled, and what this file therefore does:

- bone names lose their dots on import, so every lookup maps `.` to `_`;
- `get_bone_location` does not exist on this series, so bones are read as sockets;
- the root is bone 0 of the skeleton, not the first animation track. Reading the track gave a thigh
  that swings 57.5 cm in a walk, which would have called an in-place clip a travelling one.

The scale check was proven real by a negative control: falsifying the reference pose by ten
centimetres fails all five bones. The audit re-runs that logic, it does not re-assert the result.
"""

import unreal

from fluidunreal_runtime.errors import OpError

CM_PER_M = 100.0
SCALE_TOLERANCE_CM = 1.0
TRAVEL_TOLERANCE_CM = 2.0
IN_PLACE_LIMIT_CM = 1.0
PROXY_SUFFIX = "proxytruerootjoint"


def unreal_bone_name(blender_name):
    return blender_name.replace(".", "_")


def _measurement(kind, name, **kwargs):
    row = {
        "kind": kind,
        "name": name,
        "space": kwargs.get("space", "world"),
        "unit": kwargs.get("unit", "cm"),
        "expected": kwargs.get("expected"),
        "observed": kwargs.get("observed"),
        "tolerance": kwargs.get("tolerance"),
        "passed": kwargs.get("passed"),
        "detail": kwargs.get("detail") or {},
    }
    return row


def _find(content_path, class_name, builder):
    """One asset of a class under the published version."""
    found = []
    for path in unreal.EditorAssetLibrary.list_assets(content_path, recursive=True) or []:
        asset = unreal.EditorAssetLibrary.load_asset(str(path))
        if asset is not None and type(asset).__name__ == class_name:
            found.append((str(path), asset))
    if not found:
        builder.warn("no %s under %s" % (class_name, content_path))
    return found


def _spawn(mesh):
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SkeletalMeshActor, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0)
    )
    component = actor.skeletal_mesh_component
    for setter in ("set_skeletal_mesh_asset", "set_skeletal_mesh"):
        if hasattr(component, setter):
            getattr(component, setter)(mesh)
            return actor, component
    actor.destroy_actor()
    raise OpError("INTERNAL_ERROR", "no setter for the skeletal mesh on this series")


def _scale_and_axis(component, bones, instance, builder):
    """Each reference bone's height in centimetres, against the bundle's metres."""
    rows = []
    reference = instance.get("reference_pose") or []
    if not reference:
        builder.limit(
            "the bundle carries no reference pose: the scale and axis checks are not_run, and "
            "nothing here says the import is the right size"
        )
        return rows, None

    heights = {}
    for entry in reference:
        blender_bone = entry["bone"]
        bone = unreal_bone_name(blender_bone)
        expected = float(entry["head_m"][2]) * CM_PER_M
        observed = None
        if bone in bones:
            try:
                observed = float(component.get_socket_location(bone).z)
                heights[blender_bone] = observed
            except Exception as error:  # noqa: BLE001
                builder.warn("the socket location of %s is unreadable: %s" % (bone, error))
        else:
            builder.warn("reference bone %s (as %s) is not in the imported skeleton" % (blender_bone, bone))
        rows.append(
            _measurement(
                "scale_check",
                blender_bone,
                expected=round(expected, 3),
                observed=None if observed is None else round(observed, 3),
                tolerance=SCALE_TOLERANCE_CM,
                passed=None if observed is None else abs(observed - expected) <= SCALE_TOLERANCE_CM,
                detail={"unreal_bone": bone, "read_with": "get_socket_location"},
            )
        )

    axis = None
    if len(heights) >= 2:
        # The bone the bundle puts highest must be the one Unreal puts highest: Z is up in both.
        by_bundle = sorted(reference, key=lambda e: float(e["head_m"][2]))
        highest = by_bundle[-1]["bone"]
        observed_highest = max(heights, key=lambda name: heights[name])
        axis = _measurement(
            "axis_check",
            "highest reference bone",
            space="world",
            unit="count",
            expected=None,
            observed=None,
            passed=observed_highest == highest,
            detail={"bundle_says": highest, "engine_says": observed_highest},
        )
        rows.append(axis)
    return rows, axis


def _animations(content_path, ctx, instance, root_bone, builder):
    rows = []
    clips = ctx.clips_for(instance["instance_id"])
    fps = ctx.bundle.get("fps") or {"numerator": 24, "denominator": 1}
    rate = float(fps["numerator"]) / float(fps.get("denominator", 1))
    sequences = _find(content_path, "AnimSequence", builder)
    for index, (path, sequence) in enumerate(sequences):
        clip = clips[index] if index < len(clips) else None
        name = path.rsplit("/", 1)[-1].split(".")[0]
        span = (clip or {}).get("frame_range") or {}
        declared = int(span.get("end_exclusive", 0)) - int(span.get("start", 0))
        frames = None
        try:
            frames = int(sequence.get_editor_property("number_of_sampled_frames"))
        except Exception as error:  # noqa: BLE001
            builder.warn("the frame count of %s is unreadable: %s" % (name, error))
        rows.append(
            _measurement(
                "anim_length",
                name,
                space="frame",
                unit="frames",
                expected=declared or None,
                observed=frames,
                tolerance=1.0,
                passed=None if (frames is None or not declared) else abs(frames - declared) <= 1,
                detail={"fps": rate, "clip_id": (clip or {}).get("clip_id")},
            )
        )
        rows.append(_root_motion(sequence, clip, name, root_bone, builder))
    return rows


def _root_bone(component, bones):
    """Bone 0, not the first animation track. Lot 0 read a thigh and would have believed it."""
    if bones:
        return bones[0]
    try:
        return str(component.get_bone_name(0))
    except Exception:  # noqa: BLE001
        return None


def _travel(sequence, bone, frames, builder):
    positions = []
    for frame in (0, max(int(frames) - 1, 0)):
        try:
            transform = unreal.AnimationLibrary.get_bone_pose_for_frame(sequence, bone, frame, True)
            positions.append(transform.translation)
        except Exception as error:  # noqa: BLE001
            builder.warn("the pose of %s at frame %d is unreadable: %s" % (bone, frame, error))
            return None
    delta = positions[-1] - positions[0]
    return float((delta.x**2 + delta.y**2) ** 0.5)


def _root_motion(sequence, clip, name, root_bone, builder):
    """`root_bone` is bone 0 of the skeleton, handed in. Never the first animation track.

    Lot 0 read that track and got a thigh swinging 57.5 cm, which would have reported an in-place
    clip as travelling half a metre. The control measurement below is what exposes that mistake:
    if the root and the control read the same number, the root is not the root.
    """
    if clip is None or root_bone is None:
        return _measurement("root_motion_travel", name, space="component", passed=None)
    bone = root_bone
    try:
        frames = int(sequence.get_editor_property("number_of_sampled_frames"))
    except Exception as error:  # noqa: BLE001
        builder.warn("the root motion of %s could not be measured: %s" % (name, error))
        return _measurement("root_motion_travel", name, space="component", passed=None)

    stride = clip.get("stride_m")
    repetitions = clip.get("repetitions") or 1
    in_place = clip.get("root_motion") == "in_place"
    observed = _travel(sequence, bone, frames, builder)
    if in_place:
        expected = 0.0
        passed = None if observed is None else observed < IN_PLACE_LIMIT_CM
        tolerance = IN_PLACE_LIMIT_CM
    elif stride is None:
        return _measurement(
            "root_motion_travel",
            name,
            space="component",
            passed=None,
            detail={"why": "the bundle declares no stride to compare against"},
        )
    else:
        expected = float(stride) * int(repetitions) * CM_PER_M
        passed = None if observed is None else abs(observed - expected) <= TRAVEL_TOLERANCE_CM
        tolerance = TRAVEL_TOLERANCE_CM
    return _measurement(
        "root_motion_travel",
        name,
        space="component",
        expected=round(expected, 3),
        observed=None if observed is None else round(observed, 3),
        tolerance=tolerance,
        passed=passed,
        detail={"bone": bone, "declared": clip.get("root_motion")},
    )


def _control(sequence, bones, builder):
    """A bone that must move, read the same way. Without it a root travel of zero proves nothing."""
    moving = [name for name in bones if "thigh" in name.lower()]
    if not sequence or not moving:
        return None
    try:
        frames = int(sequence.get_editor_property("number_of_sampled_frames"))
    except Exception:  # noqa: BLE001
        return None
    travel = _travel(sequence, moving[0], frames, builder)
    return _measurement(
        "root_motion_travel",
        "control: %s" % moving[0],
        space="component",
        observed=None if travel is None else round(travel, 3),
        passed=None if travel is None else travel > 1.0,
        detail={"why": "the same call on a bone that must move; without it a zero proves nothing"},
    )


def run(ctx, request, builder):
    parameters = request.get("parameters") or {}
    asset_id = request["target"].get("asset_id")
    instance = ctx.instance(asset_id)
    version = ctx.next_version - 1
    if version < 1:
        raise OpError(
            "VALIDATION_FAILED",
            "asset %s has not been imported yet" % asset_id,
            recovery="run asset.import first",
        )
    content_path = "%s/%s/v%03d" % (ctx.destination_root, asset_id, version)
    if not unreal.EditorAssetLibrary.does_directory_exist(content_path):
        raise OpError("VALIDATION_FAILED", "nothing published at %s" % content_path)

    meshes = _find(content_path, "SkeletalMesh", builder)
    if len(meshes) != 1:
        raise OpError("VALIDATION_FAILED", "expected one skeletal mesh at %s" % content_path)
    _mesh_path, mesh = meshes[0]
    actor, component = _spawn(mesh)
    try:
        bones = [str(component.get_bone_name(i)) for i in range(component.get_num_bones())]
        added = [name for name in bones if name.lower().endswith(PROXY_SUFFIX)]
        rows, _axis = _scale_and_axis(component, bones, instance, builder)
        rows.append(
            _measurement(
                "bone_count",
                "deform bones",
                space="none",
                unit="count",
                expected=int(instance.get("bone_count") or 0) or None,
                observed=len(bones) - len(added),
                tolerance=0.0,
                passed=(len(bones) - len(added)) == int(instance.get("bone_count") or 0)
                if instance.get("bone_count")
                else None,
                detail={"added_by_importer": added},
            )
        )
        root = _root_bone(component, bones)
    finally:
        actor.destroy_actor()

    rows.extend(_animations(content_path, ctx, instance, root, builder))
    sequences = _find(content_path, "AnimSequence", builder)
    control = _control(sequences[0][1] if sequences else None, bones, builder)
    if control is not None:
        rows.append(control)
        for row in rows:
            if (
                row["kind"] == "root_motion_travel"
                and not row["name"].startswith("control:")
                and row["observed"] is not None
                and control["observed"] is not None
                and abs(row["observed"] - control["observed"]) < 0.001
            ):
                row["passed"] = None
                row["detail"]["why"] = (
                    "the root and the moving control read the same travel: the bone being read is "
                    "not the root, so this measures nothing"
                )
                builder.limit(
                    "root motion is not_run for %s: it read the same travel as the control bone" % row["name"]
                )
    elif any(r["kind"] == "root_motion_travel" and r["observed"] == 0 for r in rows):
        builder.limit(
            "a root travel of zero was measured with no moving bone to check the reader against: "
            "it is reported, not believed"
        )

    if parameters.get("render_reference_poses"):
        builder.limit("reference pose images need a GPU and a render pass: not_run in this lot")

    taken = [row for row in rows if row["passed"] is not None]
    report = {
        "schema_version": "1.0",
        "bundle_id": ctx.bundle.get("bundle_id"),
        "asset_id": asset_id,
        "engine": unreal.SystemLibrary.get_engine_version(),
        "content_path": content_path,
        "root_bone": root,
        "measurements": rows,
        "images": [],
        "limits": list(builder.limits),
    }
    builder.write_report("audit-report.json", report)
    builder.metrics.update(
        {
            "asset_id": asset_id,
            "version": version,
            "measurements": len(rows),
            "measured": len(taken),
            "not_run": [row["name"] for row in rows if row["passed"] is None],
            # Every measurement that could be taken passed. This is not artistic approval.
            "technical_pass": bool(taken) and all(row["passed"] for row in taken),
        }
    )
    if not taken:
        builder.limit("nothing could be measured: technical_pass is false, not unknown")
    builder.next_safe_actions.append(
        "read audit-report.json: a measurement with passed null was not taken, and proves nothing"
    )
