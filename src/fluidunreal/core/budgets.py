"""Budgets: what a run is expected to cost, checked before a task folder or an editor exists.

The storage and the time comparison are fluidblend's (`record_metric`, `load_metrics`,
`check_budget`), so `state/metrics.json` reads the same in both kits. What is estimated differs: an
editor start and an import rather than frames. The disk check also asks the drive, because an import
that fills it fails inside the editor, half-written, and that is exactly what reconcile exists for.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from fluidblend.contracts.common import ErrorCode, ErrorRecord
from fluidblend.core.atomic import read_json
from fluidblend.core.budgets import check_budget, dir_size_bytes, load_metrics, record_metric

from fluidunreal.contracts.operations import OperationRequest, OperationSpec
from fluidunreal.contracts.plans import Estimate
from fluidunreal.core.project import Project

# Stated, not measured. Lot 3 measured asset.import at 25-28 s, asset.audit at 36-41 s and
# game.smoke_test at 19 s on the reference machine, with a warm cache (docs/acceptance-reports/).
# Three times the longest leaves room for a slower machine without passing a guess off as a figure.
DEFAULT_RUN_SECONDS = 120.0
HOST_RUN_SECONDS = 5.0
# Interchange writes a skeletal mesh, a skeleton, a physics asset, a material instance and one
# sequence per clip, and a package keeps source data the GLB does not. No import has been weighed
# yet, so four times the bundle is a stated ceiling. The staging folder is renamed into its version,
# not copied, so it is not counted twice.
IMPORT_DISK_FACTOR = 4.0
REPORT_DISK_BYTES = 64 * 1024**2
MIB = 1024**2
GIB = 1024**3

DiskFree = Callable[[Path], int]


def metric_key(operation: str) -> str:
    return f"unreal.elapsed_s.{operation}"


def record_run(root: Path, operation: str, elapsed_s: float) -> None:
    record_metric(root, metric_key(operation), elapsed_s)


def free_bytes(path: Path) -> int:
    """Free space on the drive that holds `path`, or will hold it once it is created."""
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def doctor_warmup(root: Path) -> tuple[float, str] | None:
    """The editor's start as `doctor` last measured it, with where the number came from."""
    try:
        report = read_json(root / "state" / "diagnostics" / "capabilities.json")
    except (OSError, ValueError):
        return None
    for capability in report.get("capabilities") or []:
        value = (capability.get("evidence") or {}).get("warmup_seconds")
        if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
            return (
                float(value),
                f"warmup_seconds measured by `doctor` ({capability.get('capability_id')}, "
                f"{capability.get('verified_at')})",
            )
    return None


def estimate_for(
    project: Project, request: OperationRequest, spec: OperationSpec, *, disk_free: DiskFree = free_bytes
) -> Estimate:
    if spec.backend != "unreal":
        return Estimate(
            seconds=HOST_RUN_SECONDS,
            minutes=round(HOST_RUN_SECONDS / 60, 1),
            run_seconds=HOST_RUN_SECONDS,
            startup_seconds=0.0,
            new_disk_bytes=0,
            checked_before_execution=False,
            sources={
                "run_seconds": "a host operation starts no editor: the kit's stated default",
                "startup_seconds": "no editor is started",
                "new_disk_bytes": "not estimated for a host operation; bundle.accept checks the "
                "bundle's declared size against max_new_disk_gib itself",
                "free_disk_bytes": "not measured for a host operation",
            },
        )

    sources: dict[str, str] = {}
    measured = load_metrics(project.root).get(metric_key(spec.name)) or {}
    history = measured.get("history") or []
    if history:
        run = float(measured["mean"])
        sources["run_seconds"] = (
            f"mean of the last {len(history)} measured {spec.name} run(s) on this project (state/metrics.json)"
        )
    else:
        run = DEFAULT_RUN_SECONDS
        sources["run_seconds"] = (
            f"no {spec.name} run measured on this project yet: the kit's stated default of "
            f"{DEFAULT_RUN_SECONDS:.0f} s, three times the longest run lot 3 measured"
        )

    warmup = doctor_warmup(project.root)
    if warmup is not None:
        startup, origin = warmup
        sources["startup_seconds"] = origin
        if history:
            sources["startup_seconds"] += (
                "; added on top of measured runs that already include a start, because a cleared "
                "derived-data cache makes the next start a first one"
            )
    elif history:
        startup = 0.0
        sources["startup_seconds"] = "included in the measured runs; `doctor` has recorded no warmup"
    else:
        startup = float(project.local.unreal_startup_timeout_s)
        sources["startup_seconds"] = (
            "nothing measured yet: config/local.json unreal_startup_timeout_s, the time a first open "
            "is allowed for compiling shaders"
        )

    if spec.name == "asset.import" and request.target.bundle_id:
        folder = project.bundle_dir(request.target.bundle_id)
        size = dir_size_bytes(folder) if folder.is_dir() else 0
        need = int(size * IMPORT_DISK_FACTOR)
        sources["new_disk_bytes"] = (
            f"the accepted bundle ({size} bytes) times {IMPORT_DISK_FACTOR:g}, a stated factor: "
            "no import has been weighed yet"
        )
    else:
        need = REPORT_DISK_BYTES
        sources["new_disk_bytes"] = (
            f"{spec.name} writes reports, not content: the kit's stated allowance of "
            f"{REPORT_DISK_BYTES // MIB} MiB"
        )

    free: int | None
    try:
        free = int(disk_free(project.content_root))
        sources["free_disk_bytes"] = (
            f"free space on the drive holding the content root, {project.content_root}"
        )
    except OSError as exc:
        free = None
        sources["free_disk_bytes"] = f"could not be measured ({exc}): the free-space check was not run"

    seconds = run + startup
    return Estimate(
        seconds=round(seconds, 1),
        minutes=round(seconds / 60, 1),
        run_seconds=round(run, 1),
        startup_seconds=round(startup, 1),
        new_disk_bytes=need,
        free_disk_bytes=free,
        checked_before_execution=True,
        sources=sources,
    )


def budget_errors(project: Project, spec: OperationSpec, estimate: Estimate) -> list[ErrorRecord]:
    """What refuses the run. Always empty for a host operation: its estimate is informative."""
    if not estimate.checked_before_execution:
        return []
    budgets = project.manifest.budgets
    evidence = {"estimate": estimate.model_dump(mode="json")}
    errors = [
        error.model_copy(
            update={
                "details": {**error.details, **evidence},
                # fluidblend's wording is about renders; this says what can be done about a start.
                "recovery": "raise budgets.max_task_minutes in project.json (a user decision), or run "
                "`fluidunreal doctor` so the editor's start is measured rather than assumed",
            }
        )
        for error in check_budget(budgets, {"frames": 0, "seconds": estimate.seconds, "disk_mib": 0})
    ]
    if estimate.new_disk_bytes > budgets.max_new_disk_gib * GIB:
        errors.append(
            ErrorRecord(
                code=ErrorCode.BUDGET_EXCEEDED,
                message=f"{spec.name} needs an estimated {estimate.new_disk_bytes / GIB:.2f} GiB "
                f"> max_new_disk_gib={budgets.max_new_disk_gib}",
                recovery="import a smaller bundle, or raise budgets.max_new_disk_gib in project.json "
                "(a user decision)",
                details=evidence,
            )
        )
    if estimate.free_disk_bytes is not None and estimate.free_disk_bytes < estimate.new_disk_bytes:
        errors.append(
            ErrorRecord(
                code=ErrorCode.BUDGET_EXCEEDED,
                message=f"{spec.name} needs an estimated {estimate.new_disk_bytes / MIB:.0f} MiB and the "
                f"drive holding {project.content_root} has {estimate.free_disk_bytes / MIB:.0f} MiB free",
                recovery="free space on that drive; the kit deletes nothing to make room",
                details=evidence,
            )
        )
    return errors
