"""Planning a request without executing it: the runner's own gates, and the estimate.

The shape is fluidblend's planner, whose module is not importable here. The gates are not
reproduced: they are the runner's, called the same way, so a plan that says a run will be refused is
right about it, and one that says it will go ahead has checked what the run checks first.
"""

from __future__ import annotations

from fluidblend.contracts.common import ErrorCode, ErrorRecord, StrictModel
from fluidblend.core.atomic import atomic_write_json

from fluidunreal.contracts.operations import OperationRequest, OperationSpec
from fluidunreal.contracts.plans import Plan
from fluidunreal.core.budgets import DiskFree, budget_errors, estimate_for
from fluidunreal.core.permissions import operation_allowed
from fluidunreal.core.project import Project
from fluidunreal.core.tasks import TaskAbort, TaskRunner


def make_plan(
    project: Project,
    request: OperationRequest,
    params: StrictModel,
    spec: OperationSpec,
    *,
    disk_free: DiskFree | None = None,
    save: bool = True,
) -> Plan:
    runner = TaskRunner(project, disk_free=disk_free)
    blocking: list[ErrorRecord] = []
    try:
        runner._preflight(request, params, spec)
    except TaskAbort as abort:
        blocking.append(abort.error)
    estimate = estimate_for(project, request, spec, disk_free=runner.disk_free)
    over = budget_errors(project, spec, estimate)
    blocking.extend(over)
    verdict = "within_budget"
    if blocking:
        verdict = "blocked" if blocking[0].code != ErrorCode.BUDGET_EXCEEDED else "over_budget"

    warnings: list[str] = []
    if estimate.checked_before_execution and "stated default" in estimate.sources["run_seconds"]:
        warnings.append(
            f"no {spec.name} run has been measured on this project: the time is a stated default, "
            "and `fluidunreal doctor` measures the editor's start"
        )
    if estimate.checked_before_execution and estimate.free_disk_bytes is None:
        warnings.append("free disk space could not be measured: that check was not run")

    resources: list[str] = []
    steps = ["validate the request, its paths and the permissions"]
    if spec.backend == "unreal":
        resources += [
            f"unreal:{project.local.unreal_editor_executable or 'auto-discovery'}",
            f"uproject:{project.uproject}",
            f"content_root:{project.content_root}",
        ]
        steps.append("estimate the time and the disk, and refuse over budget before anything is created")
    steps.append("lock the project and create the task folder")
    if spec.backend == "unreal":
        steps.append(f"run {spec.name} in one dedicated editor, never one that is already open")
    else:
        steps.append(f"run {spec.name} on the host")
    steps.append("verify every artifact against its hash, then publish and journal")
    if spec.creates_version:
        steps.append("index the new Content/Fluid/<asset_id>/vNNN and record it as a revision")

    plan = Plan(
        operation_id=request.operation_id,
        operation=spec.name,
        backend=spec.backend,
        op_class=spec.op_class,
        lot=spec.lot,
        available=spec.available,
        permission_ok=operation_allowed(project.permissions, spec).allowed,
        estimated_seconds=estimate.seconds,
        estimated_new_disk_mib=round(estimate.new_disk_bytes / 1024**2, 1),
        resources=resources,
        budget=project.manifest.budgets.model_dump(),
        stop_conditions=[
            "time or disk budget exceeded",
            "an Unreal editor already open on the project",
            "a path outside the root, or a missing permission",
            "a task of the same operation_id left unsettled: reconcile it first",
            f"{project.manifest.autonomy.max_repair_attempts} repair attempts without improvement",
        ],
        steps=steps,
        warnings=warnings,
        blocking_errors=blocking,
        estimate=estimate,
        verdict=verdict,
    )
    if save:
        path = project.root / "state" / "plans" / f"{request.operation_id}.json"
        atomic_write_json(path, plan.model_dump(mode="json"))
        project.journal().append(
            "plan_created",
            operation_id=request.operation_id,
            path=path.relative_to(project.root).as_posix(),
        )
    return plan
