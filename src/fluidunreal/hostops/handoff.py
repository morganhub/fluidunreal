"""handoff.request: hand a fix back to fluidblend, as a request that kit will actually accept.

When the import or the audit shows something wrong that lives in Blender, this kit does not touch
it. It writes a complete, typed fluidblend request and prints the exact command to run it. The
agent then hands over to the `fluidblend` skill and comes back with `bundle.accept` on the export.

Two rules make this safe. The catalogue of templates is closed: a `kind` outside it is refused
rather than improvised. And every request is validated with fluidblend's own `validate_request`
before it is written, so what is handed over is something that kit accepts rather than something
this one believes it should.

`bundle_id` is this kit's own extension to the target. It never leaves here: the sibling kit's
models forbid unknown fields and would reject the whole request.
"""

from __future__ import annotations

from typing import Any

from fluidblend.contracts.common import ErrorCode
from fluidblend.contracts.operations import RequestValidationError
from fluidblend.contracts.operations import validate_request as validate_fluidblend_request
from fluidblend.core.atomic import atomic_write_json, read_json

from fluidunreal.hostops.context import HostContext, HostOpError

TEMPLATES = ("reexport_unreal", "bake_rigid_limbs", "create_clip", "look_at_glb")


def _bundle(ctx: HostContext) -> dict[str, Any]:
    path = ctx.project.bundle_dir(ctx.request.target.bundle_id) / "handoff-bundle.json"
    if not path.is_file():
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            f"no accepted bundle {ctx.request.target.bundle_id}",
            recovery="run bundle.accept first",
        )
    return read_json(path)


def _producer(ctx: HostContext, bundle: dict[str, Any]) -> dict[str, Any]:
    producer = bundle.get("producer") or {}
    if producer.get("kit") != "fluidblend":
        raise HostOpError(
            ErrorCode.UNSUPPORTED_CAPABILITY,
            "this bundle was wrapped from a third-party GLB, not produced by fluidblend",
            recovery="there is no Blender project behind it; fix the source where it came from",
        )
    if not ctx.project.manifest.sources.fluidblend_project:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            "sources.fluidblend_project is not set",
            recovery="set it in project.json: the kit cannot phrase a command it cannot point anywhere",
        )
    return producer


def _instance(bundle: dict[str, Any], instance_id: str | None) -> dict[str, Any]:
    instances = bundle.get("instances") or []
    if instance_id:
        for entry in instances:
            if entry.get("instance_id") == instance_id:
                return entry
        raise HostOpError(ErrorCode.VALIDATION_FAILED, f"the bundle describes no instance {instance_id}")
    if not instances:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, "the bundle describes no instance")
    return instances[0]


def _clip(bundle: dict[str, Any], clip_id: str | None) -> dict[str, Any]:
    clips = bundle.get("clips") or []
    if clip_id:
        for entry in clips:
            if entry.get("clip_id") == clip_id:
                return entry
        raise HostOpError(ErrorCode.VALIDATION_FAILED, f"the bundle describes no clip {clip_id}")
    if not clips:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            "the bundle describes no clip to work on",
            recovery="name one with clip_id, or ask for a different kind of fix",
        )
    return clips[0]


def _reexport(ctx: HostContext, bundle: dict[str, Any], producer: dict[str, Any]) -> dict[str, Any]:
    instances = [i["instance_id"] for i in bundle.get("instances") or []]
    if ctx.params.instance_id:
        instances = [_instance(bundle, ctx.params.instance_id)["instance_id"]]
    name = ctx.params.output_name or f"{producer.get('shot_id') or 'shot'}-unreal"
    return {
        "operation": "game.export",
        "parameters": {
            "output_name": name,
            "instance_ids": instances,
            "export_def_bones": True,
            "export_preset": "unreal",
        },
    }


def _bake(ctx: HostContext, bundle: dict[str, Any], _producer: dict[str, Any]) -> dict[str, Any]:
    instance = _instance(bundle, ctx.params.instance_id)
    clip = _clip(bundle, ctx.params.clip_id)
    # The Blender range, not the GLB's: `frame_range` starts at 0 after slide_to_zero, and a bake
    # built from it baked the walk over frames 0-47 instead of 1-48. Bundles name the Blender range
    # from schema 1.1 on; without it the offset is unknown, and guessing it would bake the wrong
    # frames without anyone seeing.
    span = clip.get("source_frame_range")
    if not span:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            f"bundle {bundle.get('bundle_id')} (schema {bundle.get('schema_version')}) does not name "
            f"the Blender range of {clip['clip_id']}: its frame_range is the GLB's, shifted to start at 0",
            recovery="ask for reexport_unreal first: fluidblend 0.6.2 and later name the range to bake",
        )
    return {
        "operation": "animation.bake",
        "instance_id": instance["instance_id"],
        "parameters": {
            "output_clip": f"{clip['clip_id']}-baked",
            "frame_range": {
                "start": int(span.get("start", 0)),
                "end_exclusive": int(span.get("end_exclusive", 2)),
            },
            "rigid_limbs": True,
        },
    }


def _create(ctx: HostContext, bundle: dict[str, Any], _producer: dict[str, Any]) -> dict[str, Any]:
    instance = _instance(bundle, ctx.params.instance_id)
    recipe = ctx.params.recipe or "walk"
    return {
        "operation": "animation.create",
        "instance_id": instance["instance_id"],
        "parameters": {"preset": recipe, "output_clip": ctx.params.clip_id or recipe},
    }


def _look(ctx: HostContext, bundle: dict[str, Any], producer: dict[str, Any]) -> dict[str, Any]:
    """The eyes. fluidblend renders the GLB in a browser so a human can actually see it."""
    model = next((f for f in bundle.get("files") or [] if f.get("role") == "model"), None)
    if model is None:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, "the bundle carries no model file")
    shot = producer.get("shot_id") or "shot010"
    export_path = f"exports/{shot}/{producer.get('operation_id')}/{model['path']}"
    return {
        "operation": "game.import_test",
        "parameters": {"export_path": export_path, "template": "web"},
        # game.smoke_test needs the folder game.import_test publishes, which does not exist yet.
        # Chaining it here would be inventing a path; it goes in next_safe_actions as text.
        "follow_up": "then run game.smoke_test on the published game folder to look at web-frame.png",
    }


BUILDERS = {
    "reexport_unreal": _reexport,
    "bake_rigid_limbs": _bake,
    "create_clip": _create,
    "look_at_glb": _look,
}


def request(ctx: HostContext) -> None:
    kind = ctx.params.kind
    if kind not in TEMPLATES:
        raise HostOpError(
            ErrorCode.UNSUPPORTED_CAPABILITY,
            f"there is no template for {kind!r}",
            recovery=f"the catalogue is closed: {', '.join(TEMPLATES)}",
        )
    bundle = _bundle(ctx)
    producer = _producer(ctx, bundle)
    draft = BUILDERS[kind](ctx, bundle, producer)
    follow_up = draft.pop("follow_up", None)

    # Only keys the sibling kit understands. Its models forbid unknown fields, so a bundle_id here
    # would make it reject the whole request rather than ignore it.
    instance_id = draft.pop("instance_id", None)
    payload = {
        "schema_version": "1.0",
        "operation": draft["operation"],
        "operation_id": ctx.request.operation_id,
        "project_id": producer.get("project_id"),
        "target": {
            key: value
            for key, value in {
                "shot_id": producer.get("shot_id"),
                "instance_id": instance_id,
                "expected_revision": producer.get("source_revision"),
            }.items()
            if value is not None
        },
        "parameters": draft["parameters"],
        "dry_run": False,
    }
    try:
        validate_fluidblend_request(payload)
    except RequestValidationError as exc:
        raise HostOpError(
            ErrorCode.INTERNAL_ERROR,
            f"the kit built a request fluidblend refuses: {exc}",
            details={"errors": exc.details, "payload": payload},
            recovery="this is a defect in the template, not in your project",
        ) from exc

    destination = ctx.project.root / "requests" / "fluidblend" / f"{ctx.request.operation_id}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, payload)

    command = (
        f'fluidblend run --project "{ctx.project.manifest.sources.fluidblend_project}" '
        f'--operation "{destination}"'
    )
    ctx.write_report(
        "handoff-report.json",
        {
            "kind": kind,
            "bundle_id": ctx.request.target.bundle_id,
            "wrote": str(destination),
            "fluidblend_operation": payload["operation"],
            "command": command,
            "follow_up": follow_up,
        },
    )
    ctx.metrics.update(
        {"kind": kind, "fluidblend_operation": payload["operation"], "request": str(destination)}
    )
    ctx.limit("this kit does not run fluidblend: the command has to be handed to that skill")
    ctx.next_safe_actions.append(command)
    if follow_up:
        ctx.next_safe_actions.append(follow_up)
    ctx.next_safe_actions.append("then bundle.accept the new export here, and import it again")
