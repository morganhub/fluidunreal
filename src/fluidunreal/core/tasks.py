"""The task runner: validate, lock, execute, verify, publish.

The flow is fluidblend's, trimmed to what this kit does. Its `core.tasks` is not importable here by
design (it binds the Blender adapters at import time), so the shape is reproduced rather than
inherited. The file formats are not: journal, tasks and revisions stay byte-compatible with the
sibling kit, so one reader understands both projects.

The engine backend lands in lot 2. Until then `_execute` refuses it by name rather than pretending.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fluidblend.contracts.common import (
    ErrorCode,
    ErrorRecord,
    OperationResult,
    OperationStatus,
    StrictModel,
)
from fluidblend.contracts.tasks import TaskRecord, WorkerInfo
from fluidblend.core import exit_codes
from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import fingerprint, new_id, now_iso, sha256_file
from fluidblend.core.locks import LockBusy, ProjectLocks
from fluidblend.core.paths import PathRejected, relpath_posix
from fluidblend.core.revisions import RevisionStore
from fluidblend.core.state import StateStore
from pydantic import ValidationError

from fluidunreal.adapters import unreal_batch, unreal_discovery
from fluidunreal.contracts.operations import (
    OperationRequest,
    OperationSpec,
    RequestValidationError,
    validate_request,
)
from fluidunreal.contracts.project import LOCKED_UNREAL_SERIES
from fluidunreal.core.permissions import operation_allowed
from fluidunreal.core.project import (
    Project,
    is_test_bed,
    kit_root,
    outside_changes,
    outside_content,
    user_project_problems,
)
from fluidunreal.core.ue_content import next_version as ue_next_version
from fluidunreal.core.ue_content import write_content_index, write_runtime_manifest
from fluidunreal.hostops import HOST_HANDLERS, HostContext, HostOpError

BLOCKED_EXIT = {
    ErrorCode.PERMISSION_REQUIRED: exit_codes.BLOCKED,
    ErrorCode.UNSUPPORTED_CAPABILITY: exit_codes.BLOCKED,
    ErrorCode.MISSING_DEPENDENCY: exit_codes.BLOCKED,
    ErrorCode.BUDGET_EXCEEDED: exit_codes.BUDGET_EXCEEDED,
    ErrorCode.SCENE_CONFLICT: exit_codes.CONFLICT,
    ErrorCode.TIMEOUT_UNKNOWN_STATE: exit_codes.UNKNOWN_STATE,
    ErrorCode.VALIDATION_FAILED: exit_codes.INVALID,
    ErrorCode.INTERNAL_ERROR: exit_codes.FAILED,
}

# Where each operation's outputs end up. A destination that already holds something is a conflict,
# never an overwrite.
RUNTIME_VERSION = "0.3.1"

PUBLICATION = {
    "bundle.accept": "reviews/bundles",
    "bundle.wrap": "reviews/bundles",
    "bundle.inspect": "reviews/bundles",
    "asset.import": "imports",
    "asset.audit": "reviews/assets",
    "game.smoke_test": "reviews/game",
    "game.screenshot": "reviews/game",
    "handoff.request": "reviews/handoff",
}


class TaskAbort(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        recovery: str | None = None,
        details: dict[str, Any] | None = None,
        status: OperationStatus = OperationStatus.blocked,
    ):
        super().__init__(message)
        self.error = ErrorRecord(code=code, message=message, recovery=recovery, details=details or {})
        self.status = status


@dataclass
class RunOutcome:
    result: OperationResult
    exit_code: int
    task: TaskRecord | None = None
    replayed: bool = False


class TaskRunner:
    def __init__(self, project: Project, *, test_hooks: dict[str, Any] | None = None):
        self.project = project
        self.state = StateStore(project.root)
        self.revisions = RevisionStore(project.root)
        self.locks = ProjectLocks(project.root)
        self.test_hooks = test_hooks or {}

    # --- Public API ---------------------------------------------------------------------

    def run(self, payload: dict[str, Any], *, force_dry_run: bool = False) -> RunOutcome:
        try:
            request, params, spec = validate_request(payload)
        except RequestValidationError as exc:
            result = self._rejected(
                payload, ErrorCode.VALIDATION_FAILED, str(exc), details={"errors": exc.details}
            )
            return RunOutcome(result, exit_codes.INVALID)
        if force_dry_run:
            request = request.model_copy(update={"dry_run": True})
        task: TaskRecord | None = None
        try:
            self._preflight(request, spec)
            replay = self._idempotency(request)
            if replay is not None:
                return RunOutcome(replay, exit_codes.OK, replayed=True)
            with self.locks.hold("project", purpose=f"{spec.name} {request.operation_id}"):
                # Another writer may have committed while we waited for the lock.
                replay = self._idempotency(request)
                if replay is not None:
                    return RunOutcome(replay, exit_codes.OK, replayed=True)
                task = self._create_task(request, spec)
                if request.dry_run:
                    result = self._dry_run_result(request, spec, task)
                    task.status = OperationStatus.planned
                    task.result_path = self._save_result(task, result)
                    self.state.upsert_task(task)
                    return RunOutcome(result, exit_codes.OK, task)
                task.status = OperationStatus.running
                task.attempts += 1
                self.state.upsert_task(task)
                result = self._execute(request, params, spec, task)
                if result.status != OperationStatus.succeeded:
                    return self._finish_failed(task, result)
                task.status = OperationStatus.validating
                self.state.upsert_task(task)
                self._verify_artifacts(task, result)
                result = self._publish(request, spec, task, result)
                task.status = OperationStatus.succeeded
                task.artifacts = result.artifacts
                task.new_revision = result.new_revision
                task.result_path = self._save_result(task, result)
                self.state.upsert_task(task)
                return RunOutcome(result, exit_codes.OK, task)
        except LockBusy as exc:
            abort = TaskAbort(
                ErrorCode.SCENE_CONFLICT,
                str(exc),
                recovery="wait for the other writer, or read state/locks/*.owner.json",
            )
            return self._aborted(request, spec, task, abort)
        except TaskAbort as abort:
            return self._aborted(request, spec, task, abort)
        except PathRejected as exc:
            return self._aborted(request, spec, task, TaskAbort(ErrorCode.PERMISSION_REQUIRED, str(exc)))
        except (OSError, ValueError) as exc:
            return self._aborted(
                request,
                spec,
                task,
                TaskAbort(ErrorCode.VALIDATION_FAILED, str(exc), status=OperationStatus.failed),
            )

    # --- Steps --------------------------------------------------------------------------

    def _preflight(self, request: OperationRequest, spec: OperationSpec) -> None:
        if request.project_id != self.project.project_id:
            raise TaskAbort(
                ErrorCode.VALIDATION_FAILED,
                f"the request is for project {request.project_id}, this one is {self.project.project_id}",
                status=OperationStatus.failed,
            )
        if not spec.available:
            raise TaskAbort(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                f"{spec.name} is not available in this lot",
                recovery="`fluidunreal ops --all --json` lists what is available and what is not",
            )
        verdict = operation_allowed(self.project.permissions, spec)
        if not verdict.allowed:
            raise TaskAbort(ErrorCode.PERMISSION_REQUIRED, verdict.reason or "not permitted")
        if spec.requires_bundle and request.target.bundle_id:
            folder = self.project.bundle_dir(request.target.bundle_id)
            if spec.name != "bundle.accept" and not folder.is_dir():
                raise TaskAbort(
                    ErrorCode.VALIDATION_FAILED,
                    f"no accepted bundle {request.target.bundle_id}",
                    recovery="run bundle.accept first",
                    status=OperationStatus.failed,
                )

    def _idempotency(self, request: OperationRequest) -> OperationResult | None:
        entry = self.state.ledger_entry(request.operation_id)
        if entry is None:
            return None
        fp = self._fingerprint(request)
        status = entry["status"]
        if status == OperationStatus.succeeded:
            if entry["fingerprint"] != fp:
                raise TaskAbort(
                    ErrorCode.SCENE_CONFLICT,
                    f"operation_id {request.operation_id} already ran with different parameters",
                    recovery="use a new operation_id",
                    details={"previous_task": entry["task_id"]},
                )
            path = self.project.root / entry["result_path"] if entry.get("result_path") else None
            if path and path.exists():
                self.project.journal().append(
                    "replayed", operation_id=request.operation_id, task_id=entry["task_id"]
                )
                return OperationResult.model_validate(read_json(path))
            raise TaskAbort(
                ErrorCode.TIMEOUT_UNKNOWN_STATE,
                "the published result of that operation_id is gone",
                recovery=f"fluidunreal task reconcile --id {entry['task_id']}",
            )
        if status in (
            OperationStatus.running,
            OperationStatus.validating,
            OperationStatus.unknown,
            OperationStatus.queued,
        ):
            raise TaskAbort(
                ErrorCode.TIMEOUT_UNKNOWN_STATE,
                f"operation_id {request.operation_id} has a task in state {status}",
                recovery=f"fluidunreal task reconcile --id {entry['task_id']} before any new attempt",
                details={"previous_task": entry["task_id"]},
            )
        return None

    def _create_task(self, request: OperationRequest, spec: OperationSpec) -> TaskRecord:
        previous = self.state.ledger_entry(request.operation_id)
        attempts = 0
        if previous:
            prior = self.state.task(previous["task_id"])
            attempts = prior.attempts if prior else 0
        task = TaskRecord(
            task_id=new_id("task"),
            operation_id=request.operation_id,
            operation=spec.name,
            project_id=request.project_id,
            status=OperationStatus.queued,
            fingerprint=self._fingerprint(request),
            expected_revision=request.target.expected_revision,
            target=request.target.model_dump(exclude_none=True),
            budget=self.project.manifest.budgets.model_dump(),
            attempts=attempts,
            created_at=now_iso(),
            updated_at=now_iso(),
            mode="batch",
        )
        task_dir = self._task_dir(task.task_id)
        task_dir.mkdir(parents=True, exist_ok=False)
        (task_dir / "out").mkdir()
        self.state.upsert_task(task)
        return task

    def _execute(
        self,
        request: OperationRequest,
        params: StrictModel,
        spec: OperationSpec,
        task: TaskRecord,
    ) -> OperationResult:
        task_dir = self._task_dir(task.task_id)
        out_dir = task_dir / "out"
        if spec.backend == "unreal":
            return self._execute_unreal(request, params, spec, task, task_dir, out_dir)
        handler = HOST_HANDLERS.get(spec.name)
        if handler is None:
            raise TaskAbort(ErrorCode.UNSUPPORTED_CAPABILITY, f"no host handler for {spec.name}")
        ctx = HostContext(
            project=self.project,
            request=request,
            params=params,
            task_id=task.task_id,
            task_dir=task_dir,
            out_dir=out_dir,
        )
        try:
            handler(ctx)
        except HostOpError as exc:
            status = (
                OperationStatus.failed
                if exc.code in (ErrorCode.VALIDATION_FAILED, ErrorCode.INTERNAL_ERROR)
                else OperationStatus.blocked
            )
            return ctx.result(
                status,
                [ErrorRecord(code=exc.code, message=str(exc), recovery=exc.recovery, details=exc.details)],
            )
        return ctx.result()

    def _execute_unreal(
        self,
        request: OperationRequest,
        params: StrictModel,
        spec: OperationSpec,
        task: TaskRecord,
        task_dir: Path,
        out_dir: Path,
    ) -> OperationResult:
        """One dedicated editor, one operation. Never the session someone has open."""
        # Before the editor is even looked for: what is wrong with someone else's project does not
        # depend on which engine is installed.
        if not is_test_bed(self.project):
            problems = user_project_problems(self.project)
            if problems:
                raise TaskAbort(
                    ErrorCode.SCENE_CONFLICT,
                    "the Unreal project cannot be written safely: " + problems[0],
                    recovery="fix what is listed in details; the kit changes nothing outside Content/Fluid",
                    details={"problems": problems},
                )
        editor, notes = unreal_discovery.select(self.project.local.unreal_editor_executable)
        if editor is None:
            raise TaskAbort(
                ErrorCode.MISSING_DEPENDENCY,
                f"no Unreal Engine {LOCKED_UNREAL_SERIES} on this machine",
                recovery="`fluidunreal doctor --project .` says what was found",
                details={"notes": notes},
            )
        uproject = self.project.uproject
        if not uproject.is_file():
            raise TaskAbort(
                ErrorCode.VALIDATION_FAILED,
                f"the project points at a .uproject that does not exist: {uproject}",
                status=OperationStatus.failed,
            )
        open_editor = unreal_batch.gui_editor_on(uproject)
        if open_editor:
            raise TaskAbort(
                ErrorCode.SCENE_CONFLICT,
                "an Unreal editor is already open on this project",
                recovery="close it first; the kit never closes, saves or reloads it for you",
                details={"process": open_editor[:400]},
            )

        kit = kit_root()
        manifest = write_runtime_manifest(kit / "unreal_runtime")
        envelope = self._envelope(request, params, spec, task, out_dir, manifest)
        self.project.journal().append(
            "unreal_worker_started",
            task_id=task.task_id,
            operation=spec.name,
            editor=editor.path,
            engine=editor.version,
            runtime_hash=manifest["hash"],
        )

        def remember(info: dict[str, Any]) -> None:
            task.worker = WorkerInfo(**info)
            self.state.upsert_task(task)

        # In someone else's project, whatever changes outside Content/Fluid is said, by name. The kit
        # writes nothing there; the engine sometimes does (it added Config/DefaultInput.ini to a
        # project that had none), and the user is told rather than left to find it.
        watched = None if is_test_bed(self.project) else outside_content(self.project)
        with self.locks.hold("unreal-instance", purpose=f"{spec.name} {request.operation_id}"):
            outcome = unreal_batch.run_operation(
                editor=Path(editor.path),
                uproject=uproject,
                kit_root=kit,
                task_dir=task_dir,
                envelope=envelope,
                task_id=task.task_id,
                timeout_s=int(self.project.manifest.budgets.max_task_minutes * 60),
                render=spec.op_class == "render",
                on_worker_started=remember,
            )

        if outcome.result is None:
            # The editor left no result: what it wrote is unknown, and calling that a failure
            # would be a guess in the direction that loses work.
            raise TaskAbort(
                ErrorCode.TIMEOUT_UNKNOWN_STATE,
                "the editor wrote no result"
                + (f" and was killed after {outcome.elapsed_s}s" if outcome.timed_out else ""),
                recovery=f"fluidunreal task reconcile --project . --id {task.task_id}",
                details={
                    "exit_code": outcome.exit_code,
                    "timed_out": outcome.timed_out,
                    "log_tail": unreal_batch.log_tail(outcome.log_path),
                },
                status=OperationStatus.unknown,
            )
        try:
            result = OperationResult.model_validate(outcome.result)
        except ValidationError as exc:
            raise TaskAbort(
                ErrorCode.VALIDATION_FAILED,
                f"the editor wrote a result the engine cannot read: {exc}",
                status=OperationStatus.failed,
            ) from exc
        if watched is not None:
            for change in outside_changes(watched, outside_content(self.project)):
                result.warnings.append(f"outside Content/Fluid, while the editor ran: {change}")
        result.metrics.setdefault("unreal_elapsed_s", outcome.elapsed_s)
        result.metrics.setdefault("unreal_exit_code", outcome.exit_code)
        if result.status != OperationStatus.succeeded and not result.errors:
            result.errors.append(
                ErrorRecord(
                    code=ErrorCode.INTERNAL_ERROR,
                    message="the editor reported a failure without saying why",
                    details={"log_tail": unreal_batch.log_tail(outcome.log_path)},
                )
            )
        return result

    def _envelope(
        self,
        request: OperationRequest,
        params: StrictModel,
        spec: OperationSpec,
        task: TaskRecord,
        out_dir: Path,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Everything the runtime may touch. It opens no path that is not in here."""
        bundle_dir = None
        bundle: dict[str, Any] = {}
        next_version = 1
        if request.target.bundle_id:
            bundle_dir = self.project.bundle_dir(request.target.bundle_id)
            bundle = read_json(bundle_dir / "handoff-bundle.json")
            asset_id = request.target.asset_id or (bundle.get("instances") or [{}])[0].get("asset_id")
            if asset_id:
                next_version = ue_next_version(self.project.asset_dir(asset_id))
        return {
            "schema_version": "1.0",
            "task_id": task.task_id,
            "runtime_version": RUNTIME_VERSION,
            "runtime_hash": manifest["hash"],
            "request": {
                "operation": spec.name,
                "operation_id": request.operation_id,
                "project_id": request.project_id,
                "target": request.target.model_dump(exclude_none=True),
                "parameters": params.model_dump(mode="json"),
            },
            "context": {
                "project_root": str(self.project.root),
                "task_dir": str(self._task_dir(task.task_id)),
                "out_dir": str(out_dir),
                "engine_series": self.project.manifest.ue.engine_series,
                "bundle_dir": str(bundle_dir) if bundle_dir else None,
                "bundle": bundle,
                "destination_root": getattr(params, "destination_root", "/Game/Fluid"),
                "content_root": str(self.project.content_root),
                "next_version": next_version,
                "budgets": self.project.manifest.budgets.model_dump(),
                "test_hooks": self.test_hooks,
            },
        }

    def _verify_artifacts(self, task: TaskRecord, result: OperationResult) -> None:
        """An artifact that is not there, or no longer hashes to what was recorded, is not evidence."""
        out_dir = self._task_dir(task.task_id) / "out"
        for artifact in result.artifacts:
            path = out_dir / artifact.path
            if not path.is_file():
                raise TaskAbort(
                    ErrorCode.INTERNAL_ERROR,
                    f"the operation reported an artifact it did not write: {artifact.path}",
                    status=OperationStatus.failed,
                )
            if sha256_file(path) != artifact.sha256:
                raise TaskAbort(
                    ErrorCode.INTERNAL_ERROR,
                    f"{artifact.path} changed after it was reported",
                    status=OperationStatus.failed,
                )

    def _publish(
        self,
        request: OperationRequest,
        spec: OperationSpec,
        task: TaskRecord,
        result: OperationResult,
    ) -> OperationResult:
        out_dir = self._task_dir(task.task_id) / "out"
        base = self.project.root / PUBLICATION.get(spec.name, "reviews") / request.operation_id
        if base.exists() and any(base.iterdir()):
            raise TaskAbort(
                ErrorCode.SCENE_CONFLICT,
                f"{relpath_posix(self.project.root, base)} already holds something",
                recovery="use a new operation_id",
            )
        base.mkdir(parents=True, exist_ok=True)
        journal = self.project.journal()
        for entry in sorted(out_dir.iterdir()):
            shutil.move(str(entry), str(base / entry.name))
        for artifact in result.artifacts:
            published = base / artifact.path
            artifact.path = relpath_posix(self.project.root, published)
            journal.append(
                "artifact_published",
                task_id=task.task_id,
                kind=artifact.kind,
                path=artifact.path,
                sha256=artifact.sha256,
            )
        if spec.creates_version:
            result = self._record_asset_version(request, task, result)
        result.next_safe_actions.append(
            f"read {relpath_posix(self.project.root, base)} for what this run proved"
        )
        return result

    def _record_asset_version(
        self, request: OperationRequest, task: TaskRecord, result: OperationResult
    ) -> OperationResult:
        """Make the published content a revision the kit can check against later.

        `RevisionStore` records one file per target, which is right for a .blend and wrong for a
        folder of .uasset. So the version writes an index of every file it holds with its hash, and
        the revision points at that: external change detection then works unchanged, and a .uasset
        edited by hand in the editor is caught the next time the kit looks.
        """
        asset_id = result.metrics.get("asset_id") or request.target.asset_id
        version = result.metrics.get("version")
        if not asset_id or not version:
            result.warnings.append("no asset version was recorded: the run reported neither")
            return result
        version_dir = self.project.asset_dir(str(asset_id)) / f"v{int(version):03d}"
        if not version_dir.is_dir():
            raise TaskAbort(
                ErrorCode.INTERNAL_ERROR,
                f"the editor reported {version_dir} but nothing is there",
                status=OperationStatus.failed,
            )
        index = write_content_index(
            version_dir,
            asset_id=str(asset_id),
            version=int(version),
            bundle_id=str(request.target.bundle_id or ""),
        )
        record = self.revisions.record(f"asset:{asset_id}", index, origin="kit")
        result.new_revision = record.revision
        result.metrics["content_index"] = relpath_posix(self.project.root, index)
        self.project.journal().append(
            "asset_version_published",
            task_id=task.task_id,
            asset_id=str(asset_id),
            version=int(version),
            revision=record.revision,
            sha256=record.sha256,
        )
        return result

    # --- Results ------------------------------------------------------------------------

    def _dry_run_result(
        self, request: OperationRequest, spec: OperationSpec, task: TaskRecord
    ) -> OperationResult:
        contract = spec.execution_contract()
        return OperationResult(
            operation_id=request.operation_id,
            operation=spec.name,
            task_id=task.task_id,
            status=OperationStatus.planned,
            metrics={"dry_run": True, **contract},
            next_safe_actions=[f"run the same request without --dry-run to execute {spec.name}"],
        )

    def _rejected(
        self,
        payload: dict[str, Any],
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> OperationResult:
        return OperationResult(
            operation_id=str(payload.get("operation_id") or "unknown"),
            operation=str(payload.get("operation") or "unknown"),
            task_id="none",
            status=OperationStatus.failed,
            errors=[ErrorRecord(code=code, message=message, details=details or {})],
        )

    def _aborted(
        self,
        request: OperationRequest,
        spec: OperationSpec | None,
        task: TaskRecord | None,
        abort: TaskAbort,
    ) -> RunOutcome:
        result = OperationResult(
            operation_id=request.operation_id,
            operation=request.operation,
            task_id=task.task_id if task else "none",
            status=abort.status,
            errors=[abort.error],
        )
        if task is not None:
            task.status = abort.status
            task.updated_at = now_iso()
            task.result_path = self._save_result(task, result)
            self.state.upsert_task(task)
        code = BLOCKED_EXIT.get(abort.error.code, exit_codes.FAILED)
        if abort.status == OperationStatus.failed and abort.error.code == ErrorCode.VALIDATION_FAILED:
            code = exit_codes.FAILED
        return RunOutcome(result, code, task)

    def _finish_failed(self, task: TaskRecord, result: OperationResult) -> RunOutcome:
        task.status = result.status
        task.updated_at = now_iso()
        task.result_path = self._save_result(task, result)
        self.state.upsert_task(task)
        code = exit_codes.FAILED
        if result.errors:
            code = BLOCKED_EXIT.get(result.errors[0].code, exit_codes.FAILED)
            if result.status == OperationStatus.failed and result.errors[0].code in (
                ErrorCode.VALIDATION_FAILED,
                ErrorCode.INTERNAL_ERROR,
            ):
                code = exit_codes.FAILED
        return RunOutcome(result, code, task)

    # --- Plumbing -----------------------------------------------------------------------

    def _task_dir(self, task_id: str) -> Path:
        return self.project.root / "state" / "tasks" / task_id

    def _fingerprint(self, request: OperationRequest) -> str:
        return fingerprint(
            {
                "operation": request.operation,
                "target": request.target.model_dump(exclude_none=True),
                "parameters": request.parameters,
                "dry_run": request.dry_run,
            }
        )

    def _save_result(self, task: TaskRecord, result: OperationResult) -> str:
        path = self._task_dir(task.task_id) / "result.published.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, result.model_dump(mode="json"))
        return relpath_posix(self.project.root, path)
