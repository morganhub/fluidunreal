"""The CLI: the only way anything happens. The skill drives this, it computes nothing itself.

Exit codes are fluidblend's, unchanged, so one reader understands both kits.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fluidblend.core import exit_codes

import fluidunreal
from fluidunreal.contracts.operations import OPERATIONS
from fluidunreal.contracts.schema_export import check_up_to_date, export_all
from fluidunreal.core.project import ProjectError, inspect_project, load_project, scaffold_project


def _print(data: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(data)


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

    p = sub.add_parser("schema", help="export or check the JSON Schemas")
    p.add_argument("action", choices=["export", "check"])
    p.add_argument("--out", default="schemas")
    p.set_defaults(func=cmd_schema)
    return parser


def main(argv: list[str] | None = None) -> int:
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
