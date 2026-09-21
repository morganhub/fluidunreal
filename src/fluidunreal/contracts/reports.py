"""What this kit publishes: an accepted bundle, an import, an audit measurement.

A `Measurement` carries its space, its unit and its tolerance, and `passed` is `None` when the
measurement could not be taken. Lot 0 is why that field is three-valued rather than a boolean: an
unmeasurable check that defaults to `False` reads as a defect in the asset, and one that defaults to
`True` is a lie.
"""

from __future__ import annotations

from typing import Any, Literal

from fluidblend.contracts.common import SCHEMA_VERSION, StrictModel
from fluidblend.contracts.project import IDENT_PATTERN
from pydantic import Field

MeasurementKind = Literal[
    "scale_check",
    "axis_check",
    "anim_length",
    "root_motion_travel",
    "socket_position",
    "bone_count",
    "rendered_share",
]


class Measurement(StrictModel):
    kind: MeasurementKind
    name: str = Field(min_length=1, max_length=200, description="What was measured, e.g. the bone")
    space: Literal["world", "component", "local", "frame", "none"] = "world"
    unit: Literal["cm", "m", "frames", "seconds", "count", "share"] = "cm"
    expected: float | None = None
    observed: float | None = None
    tolerance: float | None = Field(default=None, ge=0)
    passed: bool | None = Field(
        default=None, description="None means it could not be measured: never a pass, never a failure"
    )
    detail: dict[str, Any] = Field(default_factory=dict)


class AcceptedBundle(StrictModel):
    """`bundles/<bundle_id>/accepted.json`: what was checked when the bundle came in."""

    schema_version: str = SCHEMA_VERSION
    bundle_id: str = Field(min_length=3, max_length=100)
    accepted_at: str = Field(min_length=1, max_length=40)
    source_path: str = Field(min_length=1, description="Where it came from, for traceability only")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    producer_kit: Literal["fluidblend", "external"]
    producer_version: str = Field(min_length=1, max_length=40)
    files_verified: int = Field(ge=1)
    licences: list[str] = Field(min_length=1, description="A bundle without one is never accepted")
    khronos: Literal["passed", "failed", "not_run"] = "not_run"
    instances: list[str] = Field(default_factory=list)
    clips: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)


class ImportedAsset(StrictModel):
    """One asset the editor really wrote, as read back from the content it created."""

    asset_id: str = Field(pattern=IDENT_PATTERN)
    version: int = Field(ge=1)
    content_path: str = Field(min_length=1)
    skeleton: str | None = None
    skeletal_mesh: str | None = None
    animations: list[str] = Field(default_factory=list)
    bone_count: int = Field(default=0, ge=0)
    bones_added_by_importer: list[str] = Field(
        default_factory=list,
        description="The importer adds a proxy root: counted apart, never against the bundle",
    )
    sockets: list[str] = Field(default_factory=list)
    uassets: dict[str, str] = Field(
        default_factory=dict, description="Published path to sha256, verified before publication"
    )


class AuditReport(StrictModel):
    schema_version: str = SCHEMA_VERSION
    bundle_id: str = Field(min_length=3, max_length=100)
    asset_id: str = Field(pattern=IDENT_PATTERN)
    engine: str = Field(min_length=1, max_length=120)
    measurements: list[Measurement] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)

    @property
    def technical_pass(self) -> bool:
        """Every measurement that could be taken passed. This is not artistic approval."""
        taken = [m for m in self.measurements if m.passed is not None]
        return bool(taken) and all(m.passed for m in taken)

    @property
    def not_run(self) -> list[str]:
        return [m.name for m in self.measurements if m.passed is None]
