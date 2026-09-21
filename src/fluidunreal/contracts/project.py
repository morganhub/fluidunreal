"""`project.json` and `config/*.json` for a fluidunreal project.

Budgets, autonomy, permissions and revisions come from fluidblend unchanged: a third-party tool must
be able to read both kits' projects with one reader. What is new here is the Unreal section and the
link back to the fluidblend project, which is informative only — this kit never writes into it.
"""

from __future__ import annotations

from typing import Literal

from fluidblend.contracts.common import SCHEMA_VERSION, StrictModel
from fluidblend.contracts.project import (
    IDENT_PATTERN,
    Autonomy,
    Budgets,
    DependencyLock,
    Permissions,
    RevisionsFile,
)
from pydantic import Field, model_validator

__all__ = [
    "Autonomy",
    "Budgets",
    "DependencyLock",
    "LocalConfig",
    "Permissions",
    "ProjectManifest",
    "RevisionsFile",
    "Sources",
    "UnrealSection",
]

# Fixed by lot 0 on the reference machine: observed 5.8.2, and 5.8 is the last planned major 5.x.
LOCKED_UNREAL_SERIES = "5.8"


class UnrealSection(StrictModel):
    uproject: str = Field(
        min_length=1,
        description="Project-relative path to the .uproject, or an absolute one for an existing "
        "project the user already has",
    )
    engine_series: str = Field(default=LOCKED_UNREAL_SERIES, pattern=r"^\d+\.\d+$")
    content_root: str = Field(
        default="Content/Fluid",
        description="The only place under Content/ this kit ever writes",
    )


class Sources(StrictModel):
    """Where the bundles come from. Read to phrase exact commands, never written to."""

    fluidblend_project: str | None = Field(
        default=None, description="Absolute path to the sibling project, for next_safe_actions only"
    )


class UnrealBudgets(Budgets):
    """Same shape as fluidblend's, with defaults sized for an engine that compiles shaders."""

    max_task_minutes: int = Field(default=45, ge=1, le=24 * 60)
    max_new_disk_gib: float = Field(default=20.0, ge=0.01, le=10_000)


class ProjectManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    project_id: str = Field(pattern=IDENT_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    profile: Literal["unreal"] = "unreal"
    ue: UnrealSection
    sources: Sources = Field(default_factory=Sources)
    autonomy: Autonomy = Field(default_factory=Autonomy)
    budgets: UnrealBudgets = Field(default_factory=UnrealBudgets)
    dependency_lock: str = "dependencies.lock.json"
    created_at: str = Field(min_length=1, max_length=40)
    fluidunreal_version: str = Field(min_length=1, max_length=40)


class LocalConfig(StrictModel):
    """Machine paths. Never committed, never part of a revision."""

    unreal_editor_executable: str | None = None
    gltf_validator_executable: str | None = None
    unreal_startup_timeout_s: int = Field(
        default=600,
        ge=30,
        le=7200,
        description="The first open of a project compiles shaders: minutes, once per DDC",
    )
    ddc_path: str | None = Field(
        default=None,
        description="Absolute path outside the root. A junction inside it is refused by the path guard",
    )

    @model_validator(mode="after")
    def _no_relative_ddc(self) -> LocalConfig:
        if self.ddc_path and not self.ddc_path.strip():
            raise ValueError("ddc_path must be an absolute path or absent")
        return self
