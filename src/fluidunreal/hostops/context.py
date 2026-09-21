"""What a host operation is handed, and what it may hand back."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any

from fluidblend.contracts.common import (
    Artifact,
    ChangedEntity,
    ErrorCode,
    ErrorRecord,
    OperationResult,
    OperationStatus,
    StrictModel,
)
from fluidblend.core.hashing import sha256_file

from fluidunreal.contracts.operations import OperationRequest
from fluidunreal.core.project import Project


class HostOpError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        recovery: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.recovery = recovery
        self.details = details or {}


@dataclass
class HostContext:
    project: Project
    request: OperationRequest
    params: StrictModel
    task_id: str
    task_dir: Path
    out_dir: Path
    artifacts: list[Artifact] = field(default_factory=list)
    changed: list[ChangedEntity] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    next_safe_actions: list[str] = field(default_factory=list)
    checkpoint_id: str | None = None
    started_monotonic: float = field(default_factory=monotonic)

    def add_file(self, kind: str, path: Path, **metrics: Any) -> Artifact:
        artifact = Artifact(
            kind=kind,
            path=path.relative_to(self.out_dir).as_posix(),
            sha256=sha256_file(path),
            bytes=path.stat().st_size,
            metrics=metrics,
        )
        self.artifacts.append(artifact)
        return artifact

    def write_report(self, name: str, data: dict[str, Any], kind: str = "report") -> Artifact:
        from fluidblend.core.atomic import atomic_write_json

        path = self.out_dir / name
        atomic_write_json(path, data)
        return self.add_file(kind, path)

    def limit(self, text: str) -> None:
        """Something this run does not prove. Stated, never left for the reader to assume."""
        if text not in self.limits:
            self.limits.append(text)

    def result(
        self,
        status: OperationStatus = OperationStatus.succeeded,
        errors: list[ErrorRecord] | None = None,
    ) -> OperationResult:
        metrics = dict(self.metrics)
        if self.limits:
            metrics["limits"] = self.limits
        metrics.setdefault("wall_time_ms", int((monotonic() - self.started_monotonic) * 1000))
        return OperationResult(
            operation_id=self.request.operation_id,
            operation=self.request.operation,
            task_id=self.task_id,
            status=status,
            changed_entities=self.changed,
            artifacts=self.artifacts,
            warnings=self.warnings,
            errors=errors or [],
            metrics=metrics,
            checkpoint_id=self.checkpoint_id,
            next_safe_actions=self.next_safe_actions,
        )
