"""Plugins a project enables: reviewed ones pass, others wait for a person's approval."""

from __future__ import annotations

import json
from pathlib import Path

from fluidblend.core import exit_codes

from fluidunreal.cli import main
from fluidunreal.core.plugins import APPROVALS, REVIEWED_PLUGINS, unreviewed_plugins
from fluidunreal.core.project import load_project, scaffold_project, templates_dir
from fluidunreal.core.tasks import TaskRunner
from tests.conftest import make_request


def their_game(tmp_path: Path, extra: list[dict]) -> Path:
    uproject = tmp_path / "TheirGame" / "TheirGame.uproject"
    uproject.parent.mkdir(parents=True)
    plugins = [{"Name": "PythonScriptPlugin", "Enabled": True}, *extra]
    uproject.write_text(json.dumps({"FileVersion": 3, "EngineAssociation": "5.8", "Plugins": plugins}))
    return uproject


def test_the_test_bed_enables_only_reviewed_plugins():
    bed = json.loads(
        (templates_dir() / "game-unreal" / "FluidUnrealTestBed.uproject").read_text(encoding="utf-8")
    )
    enabled = {p["Name"] for p in bed["Plugins"] if p.get("Enabled")}
    assert enabled <= REVIEWED_PLUGINS


def test_an_unknown_plugin_stops_the_run_until_a_person_approves_it(tmp_path: Path, fixture_bundle: Path):
    uproject = their_game(
        tmp_path,
        [{"Name": "SomeoneElsesPlugin", "Enabled": True}, {"Name": "DisabledOne", "Enabled": False}],
    )
    root = tmp_path / "kit-project"
    scaffold_project(root, project_id="demo-game", ue_project=str(uproject))
    project = load_project(root)
    assert unreviewed_plugins(root, uproject) == ["SomeoneElsesPlugin"], "a disabled plugin loads nothing"

    runner = TaskRunner(project)
    accepted = runner.run(
        make_request("bundle.accept", "acc-001", parameters={"source_path": str(fixture_bundle)})
    )
    assert accepted.exit_code == exit_codes.OK
    importing = make_request(
        "asset.import", "imp-001", target={"bundle_id": "fx-export-unreal"}, dry_run=True
    )
    refused = runner.run(importing)
    assert refused.exit_code == exit_codes.BLOCKED and refused.task is None
    error = refused.result.errors[0]
    assert error.code == "PERMISSION_REQUIRED" and "SomeoneElsesPlugin" in error.message
    assert "approve-plugins" in error.recovery and error.details["plugins"] == ["SomeoneElsesPlugin"]
    assert not (root / APPROVALS).exists(), "the kit never approves on its own"

    # A name the project does not enable cannot be approved: a typo approves nothing.
    assert (
        main(["approve-plugins", "--project", str(root), "--plugins", "SomeoneElsesPluginn"])
        == exit_codes.INVALID
    )
    assert (
        main(["approve-plugins", "--project", str(root), "--plugins", "SomeoneElsesPlugin"]) == exit_codes.OK
    )
    assert unreviewed_plugins(root, uproject) == []
    planned = TaskRunner(project).run(
        make_request("asset.import", "imp-002", target={"bundle_id": "fx-export-unreal"}, dry_run=True)
    )
    assert planned.exit_code == exit_codes.OK, planned.result.model_dump()
