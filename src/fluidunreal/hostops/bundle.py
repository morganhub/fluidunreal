"""Accepting a bundle, wrapping a GLB into one, and re-checking one that was accepted.

A bundle is the only thing this kit lets in from outside. Everything it claims is verified against
the bytes on disk before it is copied in: every sha256, the licence, the producer's version. After
that the folder is protected, and the rest of the kit works from the copy rather than from wherever
it came from.

A bundle without a readable licence is refused. It is a redistribution format, and the kit will not
carry an asset whose terms it cannot show.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from fluidblend.adapters import gltf_validator as gltfv
from fluidblend.contracts.common import ChangedEntity, ErrorCode
from fluidblend.contracts.handoff import HandoffBundle
from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import now_iso, sha256_file
from fluidblend.core.paths import resolve_inside
from pydantic import ValidationError

from fluidunreal.contracts.reports import AcceptedBundle
from fluidunreal.hostops.context import HostContext, HostOpError
from fluidunreal.hostops.glb_reader import GlbError, describe

MANIFEST = "handoff-bundle.json"
MINIMUM_PRODUCER = (0, 6, 0)


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in version.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts[:3]) or (0,)


def _read_outside(ctx: HostContext, raw: str) -> Path:
    """The one path this kit reads from outside its root: a bundle folder, read-only.

    It is still checked: it must be a real absolute directory, not a link, not a UNC share, and it
    must hold a manifest. Everything the kit does afterwards works on its own copy.
    """
    if not raw or not raw.strip():
        raise HostOpError(ErrorCode.VALIDATION_FAILED, "source_path is empty")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (ctx.project.root / candidate).resolve()
    text = str(candidate)
    if text.startswith("\\\\") or text.startswith("//"):
        raise HostOpError(
            ErrorCode.PERMISSION_REQUIRED,
            f"a UNC path is refused: {text}",
            recovery="copy the bundle to a local folder first",
        )
    if not candidate.is_dir():
        raise HostOpError(ErrorCode.VALIDATION_FAILED, f"not a folder: {candidate}")
    if candidate.is_symlink() or os.path.realpath(candidate) != text:
        raise HostOpError(
            ErrorCode.PERMISSION_REQUIRED,
            "the bundle folder must be a real path, not a link",
        )
    if not (candidate / MANIFEST).is_file():
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            f"no {MANIFEST} in {candidate}",
            recovery="point at the folder fluidblend published, the one holding the GLB",
        )
    return candidate


def _parse_manifest(folder: Path) -> HandoffBundle:
    try:
        return HandoffBundle.model_validate(read_json(folder / MANIFEST))
    except (ValidationError, ValueError) as exc:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            f"{MANIFEST} does not match the contract: {exc}",
            recovery="re-export with fluidblend 0.6.0 or later",
        ) from exc


def _verify_files(folder: Path, bundle: HandoffBundle) -> list[str]:
    """Every declared file must be there and hash to what the manifest says."""
    licences: list[str] = []
    for entry in bundle.files:
        path = folder / entry.path
        if not path.is_file():
            raise HostOpError(
                ErrorCode.VALIDATION_FAILED,
                f"the bundle names a file it does not carry: {entry.path}",
            )
        observed = sha256_file(path)
        if observed != entry.sha256:
            raise HostOpError(
                ErrorCode.VALIDATION_FAILED,
                f"{entry.path} does not match its recorded sha256",
                details={"declared": entry.sha256, "observed": observed},
                recovery="the bundle was altered or copied badly; re-export it",
            )
        if entry.role == "license":
            if path.stat().st_size == 0:
                raise HostOpError(
                    ErrorCode.PERMISSION_REQUIRED,
                    f"the licence file is empty: {entry.path}",
                )
            licences.append(entry.path)
    return licences


def _check_producer(bundle: HandoffBundle) -> None:
    if bundle.producer.kit == "external":
        return
    if _version_tuple(bundle.producer.version) < MINIMUM_PRODUCER:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            f"this bundle was produced by fluidblend {bundle.producer.version}",
            recovery="re-export with fluidblend >= 0.6.0",
        )


def _copy_in(ctx: HostContext, folder: Path, bundle: HandoffBundle) -> Path:
    """Copy the manifest and the files it names. Nothing else the folder happens to hold."""
    destination = ctx.project.bundle_dir(bundle.bundle_id)
    if destination.exists() and any(destination.iterdir()):
        existing = destination / MANIFEST
        if existing.is_file() and sha256_file(existing) == sha256_file(folder / MANIFEST):
            return destination
        raise HostOpError(
            ErrorCode.SCENE_CONFLICT,
            f"bundle {bundle.bundle_id} is already here with different contents",
            recovery="accept it under a different bundle_id, or remove the existing one deliberately",
        )
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(folder / MANIFEST, destination / MANIFEST)
    for entry in bundle.files:
        target = destination / entry.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(folder / entry.path, target)
    return destination


def _budget_fits(ctx: HostContext, bundle: HandoffBundle) -> None:
    declared = sum(f.bytes or 0 for f in bundle.files)
    allowed = ctx.project.manifest.budgets.max_new_disk_gib * 1024**3
    if declared > allowed:
        raise HostOpError(
            ErrorCode.BUDGET_EXCEEDED,
            f"the bundle is {declared / 1024**3:.2f} GiB, over the project's "
            f"{ctx.project.manifest.budgets.max_new_disk_gib} GiB",
            recovery="raise budgets.max_new_disk_gib deliberately, or accept a smaller bundle",
        )


def _report(
    ctx: HostContext, folder: Path, destination: Path, bundle: HandoffBundle, licences: list[str]
) -> AcceptedBundle:
    return AcceptedBundle(
        bundle_id=bundle.bundle_id,
        accepted_at=now_iso(),
        source_path=str(folder),
        manifest_sha256=sha256_file(destination / MANIFEST),
        producer_kit=bundle.producer.kit,
        producer_version=bundle.producer.version,
        files_verified=len(bundle.files),
        licences=licences,
        khronos=bundle.validation.khronos,
        instances=[i.instance_id for i in bundle.instances],
        clips=[c.clip_id for c in bundle.clips],
        warnings=list(bundle.warnings),
        limits=list(bundle.limits),
    )


def _state_the_limits(ctx: HostContext, bundle: HandoffBundle) -> None:
    if bundle.validation.khronos != "passed":
        ctx.limit(f"the GLB's Khronos validation is {bundle.validation.khronos}, not passed")
    if bundle.validation.reimport_passed is not True:
        ctx.limit("the producer ran no control re-import: the glTF node names are unverified")
    if not bundle.instances:
        ctx.limit("the bundle describes no instance: only the GLB itself can be imported")
    for instance in bundle.instances:
        if not instance.reference_pose:
            ctx.limit(
                f"instance {instance.instance_id} carries no reference pose: "
                "the scale check after import will be not_run"
            )
        if not instance.baked:
            ctx.limit(f"instance {instance.instance_id} is not baked")
    for limit in bundle.limits:
        ctx.limit(f"stated by the producer: {limit}")


def accept(ctx: HostContext) -> None:
    """U03. Verify everything the bundle claims, then copy it in."""
    folder = _read_outside(ctx, ctx.params.source_path)
    bundle = _parse_manifest(folder)
    _check_producer(bundle)
    _budget_fits(ctx, bundle)
    licences = _verify_files(folder, bundle)
    if bundle.producer.kit == "fluidblend" and not licences:
        raise HostOpError(
            ErrorCode.PERMISSION_REQUIRED,
            "the bundle carries no licence file",
            recovery="a bundle never redistributes an asset without its licence",
        )
    destination = _copy_in(ctx, folder, bundle)

    report = _report(ctx, folder, destination, bundle, licences)
    ctx.write_report("bundle-accept.json", report.model_dump(mode="json"))
    ctx.changed.append(ChangedEntity(kind="bundle", id=bundle.bundle_id, change="created"))
    ctx.metrics.update(
        {
            "bundle_id": bundle.bundle_id,
            "files_verified": len(bundle.files),
            "instances": len(bundle.instances),
            "clips": len(bundle.clips),
            "khronos": bundle.validation.khronos,
            "producer": f"{bundle.producer.kit} {bundle.producer.version}",
        }
    )
    ctx.warnings.extend(bundle.warnings)
    _state_the_limits(ctx, bundle)
    ctx.next_safe_actions.append(
        f'fluidunreal run --project "{ctx.project.root}" --operation <an asset.import request whose '
        f'target.bundle_id is "{bundle.bundle_id}">, then asset.audit on the same bundle'
    )


def wrap(ctx: HostContext) -> None:
    """U04. Turn a third-party GLB into a bundle, describing only what the file really says."""
    model = resolve_inside(ctx.project.root, ctx.params.model_path, allow_missing=False)
    if model.suffix.lower() != ".glb":
        raise HostOpError(
            ErrorCode.UNSUPPORTED_CAPABILITY,
            f"only .glb is supported in P0/P1, not {model.suffix or 'a folder'}",
            recovery="convert to GLB, or wait for the FBX path if lot 0 ever asks for it",
        )
    licence = resolve_inside(ctx.project.root, ctx.params.license_path, allow_missing=False)
    if licence.stat().st_size == 0:
        raise HostOpError(ErrorCode.PERMISSION_REQUIRED, "the licence file is empty")

    try:
        facts = describe(model)
    except GlbError as exc:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, str(exc)) from exc

    destination = ctx.project.bundle_dir(ctx.params.bundle_id)
    if destination.exists() and any(destination.iterdir()):
        raise HostOpError(
            ErrorCode.SCENE_CONFLICT,
            f"bundle {ctx.params.bundle_id} already exists",
            recovery="use a different bundle_id",
        )
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(model, destination / model.name)
    (destination / "licenses").mkdir(exist_ok=True)
    shutil.copy2(licence, destination / "licenses" / licence.name)

    khronos = "not_run"
    validator = gltfv.find_validator(ctx.project.local.gltf_validator_executable)
    if validator:
        try:
            summary = gltfv.validate(validator, destination / model.name, ctx.out_dir / "gltf-validator.json")
            khronos = "passed" if summary["passed"] else "failed"
        except (RuntimeError, ValueError, OSError) as exc:
            ctx.warnings.append(f"the Khronos validator could not run: {exc}")
    else:
        ctx.limit("no Khronos validator on this machine: the GLB's validity is not_run, not passed")

    fps = {"numerator": ctx.params.fps_numerator, "denominator": ctx.params.fps_denominator}
    rate = ctx.params.fps_numerator / ctx.params.fps_denominator
    clips = []
    for index, animation in enumerate(facts["animations"]):
        seconds = animation["seconds"]
        if seconds is None or seconds <= 0:
            ctx.warnings.append(f"animation {animation['name']!r} declares no duration: left out")
            continue
        clips.append(
            {
                "clip_id": _clip_id(animation["name"], index),
                "instance_id": "wrapped-01",
                "gltf_animation_name": animation["name"],
                "frame_range": {"start": 0, "end_exclusive": max(2, round(seconds * rate))},
                "loop": False,
                "root_motion": "in_place",
            }
        )

    instances: list[dict[str, Any]] = []
    if facts["skinned"]:
        instances.append(
            {
                "instance_id": "wrapped-01",
                "kind": "character",
                "asset_id": _asset_id(ctx.params.bundle_id),
                "asset_version": 1,
                "license": ctx.params.license,
                "license_file": f"licenses/{licence.name}",
                "skinned": True,
                "baked": False,
                "export_def_bones": False,
                "bone_count": facts["bone_count"],
                "gltf_node_name": (facts["skinned_node_names"] or ["wrapped-01"])[0],
                "reference_pose": [],
            }
        )
        # Without a reference pose there is nothing to measure the import against, and the kit says
        # so now rather than reporting a scale check that silently never runs.
        ctx.limit("a wrapped GLB carries no reference pose: the scale check after import is not_run")
    else:
        ctx.limit("this GLB has no skin: it is a prop or a static mesh, not a character")
        clips = []

    payload = {
        "bundle_id": ctx.params.bundle_id,
        "producer": {
            "kit": "external",
            "version": facts["generator"] or "unknown",
            "operation": "bundle.wrap",
            "operation_id": ctx.request.operation_id,
            "project_id": ctx.project.project_id,
            "source_revision": 0,
            "created_at": now_iso(),
        },
        "fps": fps,
        "axis_convention": {
            "blender": {"up": "+Z", "forward": "-Y"},
            "gltf": {"up": "+Y", "forward": "+Z"},
        },
        "files": [
            _file_entry(destination, model.name, "model", "glb"),
            _file_entry(destination, f"licenses/{licence.name}", "license", None),
        ],
        "validation": {"khronos": khronos, "reimport_passed": None},
        "instances": instances,
        "clips": clips,
        "warnings": list(ctx.warnings),
        "limits": list(ctx.limits),
    }
    try:
        bundle = HandoffBundle.model_validate(payload)
    except ValidationError as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED, f"the wrapped bundle does not satisfy the contract: {exc}"
        ) from exc

    atomic_write_json(destination / MANIFEST, bundle.model_dump(mode="json"))
    licences = [f"licenses/{licence.name}"]
    ctx.write_report(
        "bundle-accept.json",
        _report(ctx, model.parent, destination, bundle, licences).model_dump(mode="json"),
    )
    ctx.metrics.update(
        {
            "bundle_id": bundle.bundle_id,
            "khronos": khronos,
            "bone_count": facts["bone_count"],
            "animations": len(facts["animations"]),
            "clips": len(clips),
            "skinned": facts["skinned"],
        }
    )


def inspect(ctx: HostContext) -> None:
    """Re-verify an accepted bundle against its own manifest, and say what came of it."""
    folder = ctx.project.bundle_dir(ctx.request.target.bundle_id)
    if not (folder / MANIFEST).is_file():
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            f"no accepted bundle {ctx.request.target.bundle_id}",
            recovery="run bundle.accept first",
        )
    bundle = _parse_manifest(folder)
    verified: dict[str, str] = {}
    if ctx.params.verify_hashes:
        _verify_files(folder, bundle)
        verified = {e.path: "verified" for e in bundle.files}

    imported = sorted(p.name for p in ctx.project.content_root.glob("*") if p.is_dir())
    ctx.write_report(
        "bundle-inspect.json",
        {
            "bundle_id": bundle.bundle_id,
            "producer": bundle.producer.model_dump(mode="json"),
            "files": verified or {e.path: "not_checked" for e in bundle.files},
            "instances": [i.instance_id for i in bundle.instances],
            "clips": [c.clip_id for c in bundle.clips],
            "validation": bundle.validation.model_dump(mode="json"),
            "imported_assets_in_project": imported,
        },
    )
    _state_the_limits(ctx, bundle)
    ctx.metrics.update({"bundle_id": bundle.bundle_id, "files_checked": len(verified)})


def _file_entry(folder: Path, relative: str, role: str, fmt: str | None) -> dict[str, Any]:
    path = folder / relative
    entry: dict[str, Any] = {
        "role": role,
        "path": relative.replace("\\", "/"),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }
    if fmt:
        entry["format"] = fmt
    return entry


def _clip_id(name: str, index: int) -> str:
    cleaned = "".join(c if c.isalnum() or c in "._-" else "-" for c in name.lower()).strip("-.")
    return cleaned or f"clip-{index:02d}"


def _asset_id(bundle_id: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "._-" else "-" for c in bundle_id.lower()).strip("-.")
    return cleaned or "wrapped"
