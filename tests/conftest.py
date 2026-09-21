"""Shared fixtures: a temporary project, the locked engine, and the acceptance report.

Without the real Unreal Engine, every test marked `unreal` is skipped as `not_run`. It is never
counted as validated, and the report shows it as its own status rather than folding it into a pass.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

KIT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT_ROOT / "src"))

from fluidunreal.contracts.project import LOCKED_UNREAL_SERIES  # noqa: E402
from fluidunreal.core.project import load_project, scaffold_project  # noqa: E402

PROJECT_DIR_NAME = "Démo Jeu é"
FIXTURE_BUNDLE = KIT_ROOT / "fixtures" / "vitruvian-walk-unreal"
_ACCEPTANCE: dict[str, dict[str, Any]] = {}
_NOTES: dict[str, list[str]] = {}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--acceptance-report",
        default=None,
        help="path (without extension) of the acceptance report to write",
    )


def _unreal_editor() -> str | None:
    env = os.environ.get("FLUIDUNREAL_EDITOR")
    if env and Path(env).exists():
        return env
    default = Path(
        rf"C:\Program Files\Epic Games\UE_{LOCKED_UNREAL_SERIES}"
        r"\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
    )
    return str(default) if default.exists() else None


UNREAL_EXE = _unreal_editor()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if UNREAL_EXE:
        return
    skip = pytest.mark.skip(reason=f"not_run: no Unreal Engine {LOCKED_UNREAL_SERIES} detected")
    for item in items:
        if "unreal" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def unreal_exe() -> str:
    if not UNREAL_EXE:
        pytest.skip("not_run: Unreal Engine missing")
    return UNREAL_EXE


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / PROJECT_DIR_NAME
    scaffold_project(root, project_id="demo-game", name="Démo Jeu")
    return root


@pytest.fixture
def project(project_root: Path):
    return load_project(project_root)


@pytest.fixture(scope="session")
def fixture_bundle() -> Path:
    if not (FIXTURE_BUNDLE / "handoff-bundle.json").is_file():
        pytest.skip("not_run: the reference bundle is missing (git lfs pull)")
    return FIXTURE_BUNDLE


def make_request(
    operation: str,
    operation_id: str,
    *,
    target: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
    project_id: str = "demo-game",
    dry_run: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": operation,
        "operation_id": operation_id,
        "project_id": project_id,
        "target": target or {},
        "parameters": parameters or {},
        "dry_run": dry_run,
    }


def note(scenario: str, text: str) -> None:
    _NOTES.setdefault(scenario, []).append(text)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    outcome = yield
    report = outcome.get_result()
    marker = item.get_closest_marker("acceptance")
    if marker is None or report.when != "call" and not (report.when == "setup" and report.skipped):
        return
    scenario = marker.args[0] if marker.args else item.name
    status = "passed" if report.passed else ("not_run" if report.skipped else "failed")
    detail = ""
    if report.skipped and report.longrepr:
        detail = str(report.longrepr[-1]) if isinstance(report.longrepr, tuple) else str(report.longrepr)
    elif report.failed:
        detail = str(report.longreprtext)[-800:]
    _ACCEPTANCE[scenario] = {
        "scenario": scenario,
        "test": item.nodeid,
        "status": status,
        "duration_s": round(report.duration, 2),
        "detail": detail,
        "title": marker.kwargs.get("title", ""),
    }


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    target = session.config.getoption("--acceptance-report")
    if not target or not _ACCEPTANCE:
        return
    rows = [dict(v, notes=_NOTES.get(k, [])) for k, v in sorted(_ACCEPTANCE.items())]
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    payload = {"generated_at": generated, "unreal": UNREAL_EXE, "scenarios": rows}
    base = Path(target)
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# fluidunreal acceptance report - generated automatically",
        "",
        f"Generated on {generated} by `pytest --acceptance-report`. "
        f"Unreal Engine: `{UNREAL_EXE or 'missing'}`.",
        "",
        "Statuses: `passed` = real test passed; `failed` = failure; "
        "`not_run` = missing dependency, not counted as validated.",
        "",
        "| Scenario | Title | Status | Duration | Notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        notes = "<br>".join(row["notes"]) if row["notes"] else ""
        if row["status"] != "passed" and row["detail"]:
            notes = (notes + "<br>" if notes else "") + row["detail"].splitlines()[-1][:160]
        lines.append(
            f"| {row['scenario']} | {row['title']} | {row['status']} | {row['duration_s']} s | {notes} |"
        )
    base.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
