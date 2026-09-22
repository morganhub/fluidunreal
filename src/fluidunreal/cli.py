"""The CLI: the only way anything happens. The skill drives this, it computes nothing itself.

Exit codes are fluidblend's, unchanged, so one reader understands both kits.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

from fluidblend.core import exit_codes
from fluidblend.core.atomic import read_json

import fluidunreal
from fluidunreal.contracts.operations import OPERATIONS, RequestValidationError, validate_request
from fluidunreal.contracts.schema_export import check_up_to_date, export_all
from fluidunreal.core.planner import make_plan
from fluidunreal.core.plugins import APPROVALS, approve
from fluidunreal.core.project import ProjectError, inspect_project, load_project, scaffold_project
from fluidunreal.core.tasks import BLOCKED_EXIT, UNSETTLED, TaskRunner
from fluidunreal.doctor import compare_lock, run_doctor, write_lock


def _print(data: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(data)


def _refuse(message: str, as_json: bool, details: object = None) -> None:
    if as_json:
        _print({"error": message, "details": details}, True)
    else:
        print(f"error: {message}", file=sys.stderr)


def _load_request(path_text: str, project_root: Path) -> object:
    """A relative request path is read from the project root, as fluidblend does.

    It used to be read from the working directory: an agent at the root of a workspace holding both
    kits' projects ran `--project unreal --operation requests/x.json` and got a traceback.
    """
    path = Path(path_text)
    if not path.is_absolute():
        path = project_root / path
    return json.loads(path.read_text(encoding="utf-8"))


def _utf8_output() -> None:
    """Redirected, Windows writes the ANSI code page: `Démo` reached an agent reading the pipe as
    UTF-8 as `D�mo`, and the fluidblend command a hand-off prints named a folder that does not
    exist. The output is UTF-8 whatever it is written to."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")


def cmd_ops(args: argparse.Namespace) -> int:
    rows = [
        {
            "name": spec.name,
            "backend": spec.backend,
            "class": spec.op_class,
            "lot": spec.lot,
            "available": spec.available,
            "description": spec.description,
            **spec.execution_contract(),
        }
        for spec in OPERATIONS.values()
        if args.all or spec.available
    ]
    if args.json:
        _print(rows, True)
    else:
        for row in rows:
            mark = " " if row["available"] else "-"
            print(f"{mark} {row['name']:<22} {row['backend']:<7} {row['lot']}  {row['description']}")
        if not args.all:
            hidden = sum(1 for s in OPERATIONS.values() if not s.available)
            print(f"\n{hidden} operation(s) not available yet; `ops --all` lists them and says why.")
    return exit_codes.OK


def cmd_init(args: argparse.Namespace) -> int:
    report = scaffold_project(
        Path(args.path),
        project_id=args.project_id,
        name=args.name,
        ue_project=args.ue_project,
        fluidblend_project=args.fluidblend_project,
        dry_run=args.dry_run,
    )
    _print(report, args.json)
    if args.strict and report["conflicts"]:
        return exit_codes.CONFLICT
    return exit_codes.OK


def cmd_inspect(args: argparse.Namespace) -> int:
    project = load_project(Path(args.project))
    _print(inspect_project(project), args.json)
    return exit_codes.OK


def cmd_doctor(args: argparse.Namespace) -> int:
    project = load_project(Path(args.project))
    report = run_doctor(project, probe=not args.no_probe)
    lock_path = Path(args.write_lock) if args.write_lock else None
    drift: list[str] = []
    existing = project.root / project.manifest.dependency_lock
    if existing.is_file():
        drift = compare_lock(report, read_json(existing))
    if lock_path:
        write_lock(project, report, lock_path)
    payload = report.model_dump(mode="json")
    payload["drift_from_lock"] = drift
    if args.json:
        _print(payload, True)
    else:
        for capability in report.capabilities:
            line = f"{capability.capability_id:<26} {capability.status:<16} {capability.version or ''}"
            print(line.rstrip())
            for restriction in capability.restrictions:
                print(f"    - {restriction}")
            if capability.error:
                print(f"    ! {capability.error}")
        for entry in drift:
            print(f"drift: {entry}")
    # A diagnostic never fails a run: it reports. Only a missing project is a blocked exit.
    return exit_codes.OK


def cmd_capabilities(args: argparse.Namespace) -> int:
    project = load_project(Path(args.project))
    path = project.root / "state" / "diagnostics" / "capabilities.json"
    if not path.is_file():
        print("no capabilities.json yet: run `fluidunreal doctor --project .`", file=sys.stderr)
        return exit_codes.BLOCKED
    _print(read_json(path), True)
    return exit_codes.OK


def cmd_run(args: argparse.Namespace) -> int:
    project = load_project(Path(args.project))
    try:
        payload = _load_request(args.operation, project.root)
    except (OSError, ValueError) as exc:
        _refuse(f"cannot read {args.operation}: {exc}", args.json)
        return exit_codes.INVALID
    runner = TaskRunner(project)
    outcome = runner.run(payload, force_dry_run=args.dry_run)
    _print(outcome.result.model_dump(mode="json"), args.json or True)
    return outcome.exit_code


def cmd_plan(args: argparse.Namespace) -> int:
    project = load_project(Path(args.project))
    try:
        payload = _load_request(args.operation, project.root)
        request, params, spec = validate_request(payload)
    except RequestValidationError as exc:
        _refuse(str(exc), args.json, exc.details)
        return exit_codes.INVALID
    except (OSError, ValueError) as exc:
        _refuse(f"cannot read {args.operation}: {exc}", args.json)
        return exit_codes.INVALID
    plan = make_plan(project, request, params, spec)
    if args.json:
        _print(plan.model_dump(mode="json"), True)
    else:
        estimate = plan.estimate
        free = (
            f"{estimate.free_disk_bytes / 1024**3:.1f} GiB free"
            if estimate.free_disk_bytes is not None
            else "free space not measured"
        )
        lines = [
            f"plan {plan.operation_id} - {plan.operation} ({plan.backend}, {plan.op_class}, {plan.lot})",
            f"  estimate: {estimate.minutes} min ({estimate.run_seconds:.0f} s run + "
            f"{estimate.startup_seconds:.0f} s start), {plan.estimated_new_disk_mib:.0f} MiB new, {free}",
            *(f"    {name}: {source}" for name, source in estimate.sources.items()),
            f"  budget: {plan.budget['max_task_minutes']} min, {plan.budget['max_new_disk_gib']} GiB",
            f"  verdict: {plan.verdict}",
            *(f"  - {step}" for step in plan.steps),
            *(f"  ! {warning}" for warning in plan.warnings),
            *(f"  BLOCKING {error.code}: {error.message}" for error in plan.blocking_errors),
        ]
        print("\n".join(lines))
    if not plan.blocking_errors:
        return exit_codes.OK
    return BLOCKED_EXIT.get(plan.blocking_errors[0].code, exit_codes.FAILED)


def cmd_task(args: argparse.Namespace) -> int:
    runner = TaskRunner(load_project(Path(args.project)))
    action = {"status": runner.status, "cancel": runner.cancel, "reconcile": runner.reconcile}
    try:
        data = action[args.task_command](args.id)
    except ProjectError as exc:
        # The project loaded; only the task id is wrong. That is an invalid argument, not a block.
        _refuse(str(exc), args.json)
        return exit_codes.INVALID
    _print(data, True)
    # A cancel always leaves the task for reconcile, and a reconcile that could not conclude says
    # so: both are an uncertain write state until reconcile has marked the task concluded.
    if args.task_command in ("cancel", "reconcile") and data.get("status") in UNSETTLED:
        return exit_codes.UNKNOWN_STATE
    return exit_codes.OK


def cmd_resume(args: argparse.Namespace) -> int:
    report = TaskRunner(load_project(Path(args.project))).resume()
    unfinished = report["unfinished_tasks"]
    if args.json:
        _print(report, True)
    else:
        print(
            f"resume {report['project_id']}: {report['events']} events, "
            f"{len(unfinished)} task(s) to reconcile"
        )
        if report["corrupt_lines"]:
            print(f"  ! {len(report['corrupt_lines'])} journal line(s) could not be read")
        for task in unfinished:
            running = ", its editor is still running" if task.get("worker_alive") else ""
            print(
                f"  {task['task_id']} {task['operation']} [{task['operation_id']}] {task['status']}{running}"
            )
            print(f"    -> {task['reconcile_command']}")
    return exit_codes.UNKNOWN_STATE if unfinished else exit_codes.OK


def cmd_approve_plugins(args: argparse.Namespace) -> int:
    """A person's decision, recorded. The skill runs this only when the user said so."""
    project = load_project(Path(args.project))
    names = [name.strip() for name in args.plugins.split(",") if name.strip()]
    try:
        record = approve(project.root, project.uproject, names)
    except ValueError as exc:
        _refuse(str(exc), args.json)
        return exit_codes.INVALID
    _print(
        {"approved": names, "record": str(project.root / APPROVALS), "all": sorted(record["plugins"])}
        if args.json
        else f"approved {', '.join(names)}; recorded in {project.root / APPROVALS}",
        args.json,
    )
    return exit_codes.OK


def cmd_schema(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if args.action == "export":
        count = export_all(out)
        print(f"{count} schemas written to {out}")
        return exit_codes.OK
    stale = check_up_to_date(out)
    if stale:
        print("stale schemas: " + ", ".join(stale))
        return exit_codes.INVALID
    print("schemas up to date")
    return exit_codes.OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fluidunreal",
        description="Import a hand-off bundle into Unreal Engine 5 and prove what arrived.",
    )
    parser.add_argument("--version", action="version", version=fluidunreal.__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ops", help="list the operation catalogue")
    p.add_argument("--all", action="store_true", help="include what is not available yet")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ops)

    p = sub.add_parser("init", help="create or complete a project")
    p.add_argument("--path", required=True)
    p.add_argument("--project-id", required=True)
    p.add_argument("--name")
    p.add_argument(
        "--ue-project",
        default="template",
        help="'template' lays down the kit's test bed; otherwise an absolute path to a .uproject",
    )
    p.add_argument("--fluidblend-project", help="absolute path, recorded to phrase exact commands")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--strict", action="store_true", help="exit 3 when a file on disk differs")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("inspect", help="read the project state")
    p.add_argument("--project", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("doctor", help="probe the engine and write capabilities.json")
    p.add_argument("--project", required=True)
    p.add_argument("--no-probe", action="store_true", help="find the editor without starting it")
    p.add_argument("--write-lock", metavar="PATH", help="record what was observed; never implicit")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("capabilities", help="read the last diagnostic without probing again")
    p.add_argument("--project", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_capabilities)

    p = sub.add_parser("plan", help="estimate a request and say whether it fits, without executing it")
    p.add_argument("--project", required=True)
    p.add_argument("--operation", required=True, help="path to the request JSON")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("run", help="execute a typed request")
    p.add_argument("--project", required=True)
    p.add_argument("--operation", required=True, help="path to the request JSON")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("task", help="state, cancellation and reconciliation of a task")
    task_sub = p.add_subparsers(dest="task_command", required=True)
    for name, text in (
        ("status", "what the task recorded, and whether its editor still runs"),
        ("cancel", "kill the task's editor and leave the task for reconcile"),
        ("reconcile", "conclude a task left unsettled: stop its editor, clean what it provably wrote"),
    ):
        tp = task_sub.add_parser(name, help=text)
        tp.add_argument("--project", required=True)
        tp.add_argument("--id", required=True, help="the task_id that `run` or `resume` printed")
        tp.add_argument("--json", action="store_true", help="accepted for symmetry: the output is JSON")
    p.set_defaults(func=cmd_task)

    p = sub.add_parser("resume", help="rebuild the state from the journal and list what to reconcile")
    p.add_argument("--project", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("approve-plugins", help="record a person's approval of plugins the .uproject enables")
    p.add_argument("--project", required=True)
    p.add_argument(
        "--plugins", required=True, help="comma-separated plugin names, as the refusal listed them"
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_approve_plugins)

    p = sub.add_parser("schema", help="export or check the JSON Schemas")
    p.add_argument("action", choices=["export", "check"])
    p.add_argument("--out", default="schemas")
    p.set_defaults(func=cmd_schema)
    return parser


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ProjectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exit_codes.BLOCKED
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return exit_codes.FAILED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
