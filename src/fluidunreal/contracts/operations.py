"""The operation catalogue: what this kit will do, and what it refuses by name.

`Target` and `OperationRequest` subclass fluidblend's so the envelope, its patterns and its
`schema_version` check stay one definition. Subclassing rather than copying matters: the models are
`extra="forbid"`, so a request carrying `bundle_id` would be rejected outright by the parent, and a
copy would drift the first time the envelope changes.

`OperationSpec` itself is copied, deliberately: it is thirty lines, and its `execution_contract`
describes *this* kit's dependencies, not Blender's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from fluidblend.contracts import operations as fb
from fluidblend.contracts.common import StrictModel
from fluidblend.contracts.project import IDENT_PATTERN
from pydantic import Field, ValidationError

Backend = Literal["host", "unreal"]
OpClass = Literal["read", "write", "render", "export"]
Lot = Literal["P0", "P1", "P2"]

BUNDLE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{2,99}$"


class Target(fb.Target):
    """fluidblend's target plus the one thing this kit addresses: a bundle it has accepted."""

    bundle_id: str | None = Field(default=None, pattern=BUNDLE_ID_PATTERN)


class OperationRequest(fb.OperationRequest):
    target: Target = Field(default_factory=Target)


# --- Per-operation parameters --------------------------------------------------------------


class NoParams(StrictModel):
    pass


class BundleAcceptParams(StrictModel):
    source_path: str = Field(
        min_length=1,
        description="Folder holding handoff-bundle.json. The one path this kit reads from outside "
        "its root, read-only, and only for this operation",
    )


class BundleWrapParams(StrictModel):
    model_path: str = Field(min_length=1, description="A .glb; FBX is not supported in P0/P1")
    license_path: str = Field(min_length=1)
    license: str = Field(min_length=1, max_length=120)
    bundle_id: str = Field(pattern=BUNDLE_ID_PATTERN)
    fps_numerator: int = Field(default=30, ge=1, le=1_000_000)
    fps_denominator: int = Field(default=1, ge=1, le=1_000_000)


class BundleInspectParams(StrictModel):
    verify_hashes: bool = True


class AssetImportParams(StrictModel):
    asset_id: str | None = Field(default=None, pattern=IDENT_PATTERN)
    destination_root: str = Field(default="/Game/Fluid", pattern=r"^/Game(/[A-Za-z0-9_]+)+$")
    replace_existing: bool = Field(
        default=False,
        description="Creates the next version; it never overwrites a published one",
    )


class AssetAuditParams(StrictModel):
    render_reference_poses: bool = Field(
        default=False, description="Needs a usable GPU; without one the images are not_run"
    )


class GameSmokeTestParams(StrictModel):
    clip_id: str | None = Field(default=None, pattern=IDENT_PATTERN)


class GameScreenshotParams(StrictModel):
    width: int = Field(default=640, ge=64, le=4096)
    height: int = Field(default=360, ge=64, le=4096)


HandoffKind = Literal["reexport_unreal", "bake_rigid_limbs", "create_clip", "look_at_glb"]


class HandoffRequestParams(StrictModel):
    kind: HandoffKind
    instance_id: str | None = Field(default=None, pattern=IDENT_PATTERN)
    clip_id: str | None = Field(default=None, pattern=IDENT_PATTERN)
    output_name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,80}$")
    recipe: str | None = Field(default=None, pattern=IDENT_PATTERN)


class ProjectPlanParams(StrictModel):
    request_path: str


# --- Catalogue -----------------------------------------------------------------------------

# Everything an operation needs from the outside, per operation. An operation that needs the editor
# says so here, so `doctor` and `plan` can refuse before anything is launched.
REQUIRED_DEPENDENCIES: dict[str, list[str]] = {
    "asset.import": ["unreal.editor", "unreal.python", "unreal.project"],
    "asset.audit": ["unreal.editor", "unreal.python", "unreal.project"],
    "game.smoke_test": ["unreal.editor", "unreal.python", "unreal.project"],
    "game.screenshot": ["unreal.editor", "unreal.python", "unreal.project"],
    "handoff.request": ["fluidblend.kit"],
}
OPTIONAL_DEPENDENCIES: dict[str, list[str]] = {
    "bundle.accept": ["gltf.khronos_validator"],
    "bundle.wrap": ["gltf.khronos_validator"],
    "game.screenshot": ["unreal.gpu"],
    "asset.audit": ["unreal.gpu"],
}


@dataclass(frozen=True)
class OperationSpec:
    name: str
    params_model: type[StrictModel]
    backend: Backend
    op_class: OpClass
    lot: Lot
    available: bool
    description: str
    requires_bundle: bool = False
    requires_asset: bool = False
    creates_version: bool = False
    cli_command: str | None = None
    """Dedicated CLI subcommand when the operation does not go through `fluidunreal run`."""

    def execution_contract(self) -> dict[str, Any]:
        """Machine-readable execution scope shared by CLI help and generated schemas."""
        targets = []
        if self.requires_bundle:
            targets.append("bundle_id")
        if self.requires_asset:
            targets.append("asset_id")
        paths = [name for name in self.params_model.model_fields if name.endswith("_path")]
        return {
            # There is no live mode: an editor already open on the project is a conflict, not a
            # session to write into.
            "modes": ["batch"] if self.available and not self.cli_command else [],
            "required_dependencies": REQUIRED_DEPENDENCIES.get(self.name, []),
            "optional_dependencies": OPTIONAL_DEPENDENCIES.get(self.name, []),
            "required_targets": targets,
            "input_paths": paths,
            "publication": "asset_revision_and_reports" if self.creates_version else "reports_and_artifacts",
            "cli_command": self.cli_command,
        }


def _spec(
    name: str,
    params: type[StrictModel],
    backend: Backend,
    op_class: OpClass,
    lot: Lot,
    description: str,
    *,
    available: bool = True,
    requires_bundle: bool = False,
    requires_asset: bool = False,
    creates_version: bool = False,
    cli: str | None = None,
) -> OperationSpec:
    return OperationSpec(
        name,
        params,
        backend,
        op_class,
        lot,
        available,
        description,
        requires_bundle,
        requires_asset,
        creates_version,
        cli,
    )


OPERATIONS: dict[str, OperationSpec] = {
    s.name: s
    for s in [
        _spec(
            "environment.doctor",
            NoParams,
            "host",
            "read",
            "P0",
            "Probe the engine, its Python and the project's plugins; write capabilities.json",
            cli="doctor",
        ),
        _spec(
            "capabilities.list",
            NoParams,
            "host",
            "read",
            "P0",
            "List the capabilities last observed, without probing again",
            cli="capabilities",
        ),
        _spec("project.init", NoParams, "host", "write", "P0", "Create a project", cli="init"),
        _spec("project.inspect", NoParams, "host", "read", "P0", "Read the project state", cli="inspect"),
        _spec(
            "project.plan",
            ProjectPlanParams,
            "host",
            "read",
            "P0",
            "Estimate a request without executing it",
            cli="plan",
        ),
        _spec(
            "project.resume",
            NoParams,
            "host",
            "read",
            "P0",
            "Rebuild the state from the journal and list what to reconcile",
            cli="resume",
        ),
        _spec("task.status", NoParams, "host", "read", "P0", "State of a task", cli="task status"),
        _spec("task.cancel", NoParams, "host", "write", "P0", "Cancel a running task", cli="task cancel"),
        _spec(
            "task.reconcile",
            NoParams,
            "host",
            "write",
            "P0",
            "Conclude a task left in an unknown write state",
            cli="task reconcile",
        ),
        _spec(
            "bundle.accept",
            BundleAcceptParams,
            "host",
            "write",
            "P0",
            "Accept a hand-off bundle published by fluidblend, verifying every hash and its licence",
        ),
        _spec(
            "bundle.wrap",
            BundleWrapParams,
            "host",
            "write",
            "P0",
            "Wrap a third-party GLB into a bundle; a readable licence is required",
        ),
        _spec(
            "bundle.inspect",
            BundleInspectParams,
            "host",
            "read",
            "P0",
            "Re-verify an accepted bundle and list what was imported from it",
            requires_bundle=True,
        ),
        _spec(
            "asset.import",
            AssetImportParams,
            "unreal",
            "write",
            "P0",
            "Import a bundle into the Unreal project and publish it as a new version",
            requires_bundle=True,
            creates_version=True,
        ),
        _spec(
            "asset.audit",
            AssetAuditParams,
            "unreal",
            "read",
            "P0",
            "Measure what the engine wrote: scale, axes, animation length, root motion, sockets",
            requires_bundle=True,
            requires_asset=True,
        ),
        _spec(
            "game.smoke_test",
            GameSmokeTestParams,
            "unreal",
            "read",
            "P1",
            "Play the kit's test bed headless and report its checks",
            requires_bundle=True,
            requires_asset=True,
        ),
        _spec(
            "game.screenshot",
            GameScreenshotParams,
            "unreal",
            "render",
            "P1",
            "Render one off-screen frame and the share of it the character covers",
            available=False,
            requires_bundle=True,
            requires_asset=True,
        ),
        _spec(
            "handoff.request",
            HandoffRequestParams,
            "host",
            "write",
            "P1",
            "Write a typed fluidblend request when the fix belongs in Blender",
            requires_bundle=True,
        ),
        _spec(
            "game.package",
            NoParams,
            "unreal",
            "export",
            "P2",
            "Cook and package the project (not implemented: this kit does not build your game)",
            available=False,
        ),
        _spec(
            "retarget.mannequin",
            NoParams,
            "unreal",
            "write",
            "P2",
            "Retarget onto the UE5 Mannequin (not implemented)",
            available=False,
        ),
    ]
}


class RequestValidationError(ValueError):
    def __init__(self, message: str, details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.details = details or []


def validate_request(payload: dict[str, Any]) -> tuple[OperationRequest, StrictModel, OperationSpec]:
    """Validate the envelope, then the parameters against the operation's own model."""
    try:
        request = OperationRequest.model_validate(payload)
    except ValidationError as exc:
        raise RequestValidationError("invalid request", exc.errors(include_url=False)) from exc
    spec = OPERATIONS.get(request.operation)
    if spec is None:
        raise RequestValidationError(f"unknown operation: {request.operation}")
    try:
        params = spec.params_model.model_validate(request.parameters)
    except ValidationError as exc:
        raise RequestValidationError(
            f"invalid parameters for {request.operation}", exc.errors(include_url=False)
        ) from exc
    if spec.requires_bundle and not request.target.bundle_id:
        raise RequestValidationError(f"{request.operation} requires target.bundle_id")
    if spec.requires_asset and not request.target.asset_id:
        raise RequestValidationError(f"{request.operation} requires target.asset_id")
    return request, params, spec
