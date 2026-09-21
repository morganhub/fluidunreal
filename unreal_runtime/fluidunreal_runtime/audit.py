"""asset.audit: measure what the engine wrote, against what the bundle said.

Every measurement carries its space, its unit and its tolerance, and `passed` is three-valued. A
measurement that could not be taken is `None`: never a pass, and never a defect in the asset either.

What lot 0 settled, and what this file therefore does:

- bone names lose their dots on import, so every lookup maps `.` to `_`;
- `get_bone_location` does not exist on this series, so bones are read as sockets;
- root motion is read on the bones that carry the body, never on bone 0 alone. See `_body_bones`:
  bone 0 is a joint the importer invents, and reading it passed an in-place claim that was false.

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


def _animations(content_path, ctx, instance, body, builder):
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
        rows.extend(_root_motion(sequence, clip, name, frames, declared, body, builder))
    return rows


def _body_bones(component, bones):
    """The bones that carry the body through space: the top of what the bundle exported.

    Lot 0 read bone 0 and called it the root. On this series bone 0 is the joint the importer adds,
    `<node>_ProxyTrueRootJoint`, which no clip animates. It read 0.0 cm on a walk whose every bone
    travels 0.59 m, and the audit passed an in-place claim that was false. The "control" meant to
    catch a wrong bone did not: its thigh read 57.5 cm, taken for a swing, and that 57.5 cm was the
    travel itself. A deform-only export has no single root bone at all. The reference fixture's 188
    bones hang from the proxy in 75 separate chains, and the travel is carried by every one of them.

    So: every bone whose parent is the proxy. Without a proxy, bone 0 is a real root and is used.
    """
    added = [name for name in bones if name.lower().endswith(PROXY_SUFFIX)]
    if not added:
        return (bones[:1], None, None) if bones else ([], None, "the skeleton has no bones")
    proxy = added[0]
    top = []
    for name in bones:
        if name == proxy:
            continue
        try:
            parent = str(component.get_parent_bone(name))
        except Exception as error:  # noqa: BLE001
            return [], proxy, "the parent of %s is unreadable: %s" % (name, error)
        if parent == proxy:
            top.append(name)
    if not top:
        return [], proxy, "no bone hangs from %s" % proxy
    return top, proxy, None


def _horizontal(sequence, bone, frames, builder):
    """Component-space position of a top bone at each frame, in centimetres, X and Y only.

    A top bone's parent is the proxy, which sits at the origin, so its local translation is its
    position in the component. That is only true of top bones, which is why only they are read.
    """
    points = []
    for frame in frames:
        try:
            transform = unreal.AnimationLibrary.get_bone_pose_for_frame(sequence, bone, frame, True)
        except Exception as error:  # noqa: BLE001
            builder.warn("the pose of %s at frame %d is unreadable: %s" % (bone, frame, error))
            return None
        points.append((float(transform.translation.x), float(transform.translation.y)))
    return points


def _distance(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _root_motion(sequence, clip, name, frames, declared_frames, body, builder):
    """How far the body travels between the first and the last frame, and a control on the reader.

    Travel is the median over the top bones: a clip moves them together, and one odd chain cannot
    swing the result. The control is the largest excursion of any top bone from its first-frame
    position anywhere in the clip. A walk always has some; a reader that returns constants has none,
    and then a travel of zero means nothing.

    A declared stride covers the whole clip; the travel is read from its first frame to its last,
    which is one frame short of a loop, and Unreal samples one frame fewer than the bundle declares.
    So the stride is scaled to the span actually read: on the reference walk, 46 frames of 48.
    Comparing the full stride instead fails a correct 0.6 m walk by 2.5 cm.
    """
    bones, proxy, problem = body
    if clip is None or frames is None or not bones:
        builder.limit("root motion of %s is not_run: %s" % (name, problem or "no clip or no frame count"))
        return [_measurement("root_motion_travel", name, space="component", passed=None)]
    last = max(int(frames) - 1, 0)
    sampled = sorted({last * k // 4 for k in range(5)})
    travels, excursion = [], 0.0
    for bone in bones:
        points = _horizontal(sequence, bone, sampled, builder)
        if points is None:
            continue
        travels.append((_distance(points[0], points[-1]), bone))
        excursion = max(excursion, max(_distance(points[0], p) for p in points))
    if not travels:
        builder.limit("root motion of %s is not_run: no top bone could be read" % name)
        return [_measurement("root_motion_travel", name, space="component", passed=None)]
    travels.sort()
    observed = travels[len(travels) // 2][0]
    reader_moves = excursion > IN_PLACE_LIMIT_CM
    control = _measurement(
        "root_motion_travel",
        "control: %s" % name,
        space="component",
        observed=round(excursion, 3),
        passed=reader_moves,
        detail={
            "why": "largest excursion of a top bone within the clip; a reader that returns "
            "constants reads zero here, and then no travel below means anything",
            "frames": sampled,
        },
    )

    declared = clip.get("root_motion")
    stride = clip.get("stride_m")
    repetitions = clip.get("repetitions") or 1
    detail = {
        "declared": declared,
        "read_on": "median of %d bones hanging from %s" % (len(travels), proxy) if proxy else travels[0][1],
        "least_cm": [travels[0][1], round(travels[0][0], 3)],
        "most_cm": [travels[-1][1], round(travels[-1][0], 3)],
        "frames": [sampled[0], sampled[-1]],
    }
    if declared == "in_place":
        expected, tolerance = 0.0, IN_PLACE_LIMIT_CM
        passed = observed < IN_PLACE_LIMIT_CM
        if not passed:
            detail["why"] = (
                "declared in place, but the whole body travels: played on a Character it slides "
                "ahead of its capsule and snaps back every loop"
            )
    elif stride is None:
        detail["why"] = "the bundle declares no stride to compare against"
        return [
            _measurement(
                "root_motion_travel", name, space="component", observed=round(observed, 3), detail=detail
            ),
            control,
        ]
    else:
        span = float(last) / declared_frames if declared_frames else 1.0
        expected = float(stride) * int(repetitions) * CM_PER_M * span
        detail["span_of_clip_read"] = "%d of %d frames" % (last, declared_frames or last)
        tolerance = TRAVEL_TOLERANCE_CM
        passed = abs(observed - expected) <= TRAVEL_TOLERANCE_CM
    travel = _measurement(
        "root_motion_travel",
        name,
        space="component",
        expected=round(expected, 3),
        observed=round(observed, 3),
        tolerance=tolerance,
        passed=passed if reader_moves else None,
        detail=detail,
    )
    if not reader_moves:
        builder.limit(
            "root motion of %s is not_run: no top bone moves at all within the clip, so a travel "
            "of %.3f cm proves nothing about the reader" % (name, observed)
        )
    return [travel, control]


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
        body = _body_bones(component, bones)
    finally:
        actor.destroy_actor()

    rows.extend(_animations(content_path, ctx, instance, body, builder))
    for row in rows:
        if row["kind"] == "root_motion_travel" and row["passed"] is False and "why" in row["detail"]:
            builder.next_safe_actions.append(
                "%s: %s. The declaration comes from the bundle; fix it where the clip is made"
                % (row["name"], row["detail"]["why"])
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
        "root_motion_read_on": body[0][:3] + (["..."] if len(body[0]) > 3 else []),
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
