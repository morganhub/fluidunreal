"""U11 and `plan`: a run that does not fit is refused before a task folder or an editor exists.

Every estimate carries where its numbers came from. Nothing here starts an editor: the refusals
happen before one could be, and tests/unit/conftest.py fails any test that reaches one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fluidblend.contracts.common import ErrorCode
from fluidblend.contracts.tasks import Plan as FluidblendPlan
from fluidblend.core import exit_codes
from fluidblend.core.atomic import atomic_write_json
from fluidblend.core.budgets import dir_size_bytes

from fluidunreal.cli import main
from fluidunreal.contracts.operations import validate_request
from fluidunreal.core.budgets import (
    DEFAULT_RUN_SECONDS,
    GIB,
    IMPORT_DISK_FACTOR,
    budget_errors,
    estimate_for,
    record_run,
)
from fluidunreal.core.project import load_project
from fluidunreal.core.tasks import TaskRunner
from tests.conftest import make_request, note
from tests.unit.conftest import BUNDLE, task_dirs


def set_budgets(project, **values):
    """Through project.json and a reload, the way a user changes a budget."""
    path = project.root / "project.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["budgets"].update(values)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return load_project(project.root)


def task_events(project, operation_id: str) -> list[dict]:
    return [
        e
        for e in project.journal().events()
        if e["event"] == "task_updated" and e["task"]["operation_id"] == operation_id
    ]


def importing(operation_id: str) -> dict:
    return make_request("asset.import", operation_id, target={"bundle_id": BUNDLE})


@pytest.mark.acceptance("U11", title="Refuse a run over its time or disk budget before anything starts")
def test_U11_a_run_over_budget_is_refused_before_anything_exists(accepted):
    before = task_dirs(accepted)

    slow = set_budgets(accepted, max_task_minutes=1)
    outcome = TaskRunner(slow).run(importing("imp-slow"))
    assert outcome.exit_code == exit_codes.BUDGET_EXCEEDED, outcome.result.model_dump()
    error = outcome.result.errors[0]
    assert error.code == ErrorCode.BUDGET_EXCEEDED and "max_task_minutes=1" in error.message
    sources = error.details["estimate"]["sources"]
    assert "stated default" in sources["run_seconds"]
    assert "unreal_startup_timeout_s" in sources["startup_seconds"]
    assert "user decision" in error.recovery and "doctor" in error.recovery
    assert outcome.result.task_id == "none" and task_events(slow, "imp-slow") == []

    # A full drive. Only the question to the operating system is replaced: the need, the comparison
    # and the refusal are the code a real run goes through.
    fits = set_budgets(slow, max_task_minutes=45)
    full = TaskRunner(fits, disk_free=lambda path: 5 * 1024**2).run(importing("imp-full"))
    assert full.exit_code == exit_codes.BUDGET_EXCEEDED
    assert "5 MiB free" in full.result.errors[0].message
    assert "deletes nothing" in full.result.errors[0].recovery

    # A need beyond max_new_disk_gib, on the real drive.
    small = set_budgets(fits, max_new_disk_gib=0.01)
    greedy = TaskRunner(small).run(importing("imp-big"))
    assert greedy.exit_code == exit_codes.BUDGET_EXCEEDED
    assert "max_new_disk_gib=0.01" in greedy.result.errors[0].message

    assert task_dirs(small) == before, "no refused run created a task folder"
    for operation_id in ("imp-full", "imp-big"):
        assert task_events(small, operation_id) == []
    estimate = error.details["estimate"]
    need = estimate["new_disk_bytes"] / 1024**2
    note(
        "U11",
        f"{estimate['seconds']:.0f} s estimated (nothing measured: stated defaults) over "
        f"max_task_minutes=1 -> exit 6; {need:.0f} MiB needed on a drive with 5 MiB free -> exit 6; "
        f"{need:.0f} MiB over max_new_disk_gib=0.01 -> exit 6; no task folder, no task event, no editor",
    )


def test_the_estimate_says_where_every_number_came_from(accepted, tmp_path):
    project = accepted
    request, _params, spec = validate_request(importing("imp-x"))

    first = estimate_for(project, request, spec, disk_free=lambda path: 10 * GIB)
    bundle = dir_size_bytes(project.bundle_dir(BUNDLE))
    assert first.run_seconds == DEFAULT_RUN_SECONDS and first.startup_seconds == 600
    assert first.seconds == 720 and first.minutes == 12
    assert first.new_disk_bytes == int(bundle * IMPORT_DISK_FACTOR) and first.free_disk_bytes == 10 * GIB
    assert set(first.sources) == {"run_seconds", "startup_seconds", "new_disk_bytes", "free_disk_bytes"}
    assert f"({bundle} bytes)" in first.sources["new_disk_bytes"]

    record_run(project.root, "asset.import", 30.0)
    record_run(project.root, "asset.import", 50.0)
    measured = estimate_for(project, request, spec, disk_free=lambda path: 10 * GIB)
    assert measured.run_seconds == 40.0 and measured.startup_seconds == 0.0
    assert "last 2 measured asset.import run(s)" in measured.sources["run_seconds"]
    assert "included in the measured runs" in measured.sources["startup_seconds"]

    atomic_write_json(
        project.root / "state" / "diagnostics" / "capabilities.json",
        {
            "capabilities": [
                {"capability_id": "unreal.editor", "evidence": {}},
                {
                    "capability_id": "unreal.python",
                    "verified_at": "2026-09-21T10:00:00.000Z",
                    "evidence": {"warmup_seconds": 15.5},
                },
            ]
        },
    )
    warm = estimate_for(project, request, spec, disk_free=lambda path: 10 * GIB)
    assert warm.startup_seconds == 15.5 and warm.seconds == 55.5
    assert "measured by `doctor` (unreal.python" in warm.sources["startup_seconds"]


def test_a_host_operation_is_never_refused_on_its_estimate(accepted):
    project = set_budgets(accepted, max_task_minutes=1, max_new_disk_gib=0.01)
    outcome = TaskRunner(project, disk_free=lambda path: 0).run(
        make_request("bundle.inspect", "ins-001", target={"bundle_id": BUNDLE})
    )
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    request, _params, spec = validate_request(
        make_request("bundle.inspect", "ins-002", target={"bundle_id": BUNDLE})
    )
    estimate = estimate_for(project, request, spec)
    assert estimate.checked_before_execution is False and budget_errors(project, spec, estimate) == []


def test_a_dry_run_is_held_to_the_same_budget(accepted):
    slow = set_budgets(accepted, max_task_minutes=1)
    before = task_dirs(slow)
    refused = TaskRunner(slow).run(importing("imp-dry"), force_dry_run=True)
    assert refused.exit_code == exit_codes.BUDGET_EXCEEDED and task_dirs(slow) == before

    fits = set_budgets(slow, max_task_minutes=45)
    planned = TaskRunner(fits).run(importing("imp-dry"), force_dry_run=True)
    assert planned.exit_code == exit_codes.OK and planned.result.status == "planned"
    assert planned.result.metrics["estimate"]["seconds"] == 720.0


def test_plan_prints_the_estimate_and_the_verdict_without_executing(accepted, tmp_path, capsys):
    project = accepted
    request = tmp_path / "import.json"
    request.write_text(json.dumps(importing("imp-plan")), encoding="utf-8")
    root = str(project.root)
    before = task_dirs(project)

    assert main(["plan", "--project", root, "--operation", str(request), "--json"]) == exit_codes.OK
    plan = json.loads(capsys.readouterr().out)
    assert set(FluidblendPlan.model_fields) <= set(plan), "fluidblend's plan shape, extended"
    assert plan["verdict"] == "within_budget" and plan["blocking_errors"] == []
    assert plan["estimated_seconds"] == 720.0 and plan["estimate"]["checked_before_execution"] is True
    assert "unreal_startup_timeout_s" in plan["estimate"]["sources"]["startup_seconds"]
    assert plan["warnings"] and "stated default" in plan["warnings"][0]
    assert (project.root / "state" / "plans" / "imp-plan.json").is_file()

    set_budgets(project, max_task_minutes=5)
    assert main(["plan", "--project", root, "--operation", str(request)]) == exit_codes.BUDGET_EXCEEDED
    human = capsys.readouterr().out
    assert "verdict: over_budget" in human and "BLOCKING BUDGET_EXCEEDED" in human
    assert "startup_seconds: nothing measured yet" in human
    assert task_dirs(project) == before, "a plan executes nothing"


def test_plan_says_blocked_for_what_the_runner_would_refuse_first(project, tmp_path, capsys):
    root = str(project.root)
    unavailable = tmp_path / "screenshot.json"
    unavailable.write_text(
        json.dumps(
            make_request("game.screenshot", "shot-001", target={"bundle_id": BUNDLE, "asset_id": "hero"})
        ),
        encoding="utf-8",
    )
    assert main(["plan", "--project", root, "--operation", str(unavailable), "--json"]) == exit_codes.BLOCKED
    plan = json.loads(capsys.readouterr().out)
    assert plan["verdict"] == "blocked"
    assert plan["blocking_errors"][0]["code"] == ErrorCode.UNSUPPORTED_CAPABILITY

    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(make_request("asset.teleport", "x-001")), encoding="utf-8")
    assert main(["plan", "--project", root, "--operation", str(broken)]) == exit_codes.INVALID
    assert main(["plan", "--project", root, "--operation", str(Path(tmp_path, "missing.json"))]) == (
        exit_codes.INVALID
    )
