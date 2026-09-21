"""An Unreal project the user brought: what the kit checks before it writes a single file there."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fluidblend.core import exit_codes

from fluidunreal.core.project import load_project, scaffold_project, user_project_problems
from fluidunreal.core.tasks import TaskRunner
from fluidunreal.core.ue_content import write_content_index
from tests.conftest import make_request

PYTHON = {"Name": "PythonScriptPlugin", "Enabled": True}


def their_game(tmp_path: Path, *, association: str = "5.8", plugins: list | None = None) -> Path:
    uproject = tmp_path / "TheirGame" / "TheirGame.uproject"
    uproject.parent.mkdir(parents=True)
    uproject.write_text(
        json.dumps(
            {
                "FileVersion": 3,
                "EngineAssociation": association,
                "Plugins": [PYTHON] if plugins is None else plugins,
            }
        ),
        encoding="utf-8",
    )
    return uproject


def project_on(tmp_path: Path, uproject: Path):
    root = tmp_path / "kit-project"
    scaffold_project(root, project_id="my-game", ue_project=str(uproject))
    return load_project(root)


def test_a_clean_project_on_the_locked_series_has_nothing_to_report(tmp_path: Path):
    project = project_on(tmp_path, their_game(tmp_path))
    assert user_project_problems(project) == []
    assert not project.content_root.exists(), "checking writes nothing"


def test_another_engine_series_and_a_missing_python_plugin_are_named(tmp_path: Path):
    project = project_on(tmp_path, their_game(tmp_path, association="5.7", plugins=[]))
    problems = user_project_problems(project)
    assert any("for Unreal Engine 5.7" in p for p in problems)
    # The exact line to add, and the promise not to add it.
    assert any(
        '{"Name": "PythonScriptPlugin", "Enabled": true}' in p and "never edits" in p for p in problems
    )
    assert json.loads(project.uproject.read_text(encoding="utf-8"))["Plugins"] == []


def test_content_the_kit_did_not_write_stops_it(tmp_path: Path):
    project = project_on(tmp_path, their_game(tmp_path))
    theirs = project.content_root / "Hero" / "SK_Hero.uasset"
    theirs.parent.mkdir(parents=True)
    theirs.write_bytes(b"their asset")
    assert user_project_problems(project) == ["not written by this kit: Fluid/Hero/SK_Hero.uasset"]


def test_an_indexed_version_passes_and_an_unindexed_file_in_it_does_not(tmp_path: Path):
    project = project_on(tmp_path, their_game(tmp_path))
    version = project.content_root / "vitruvian" / "v001"
    version.mkdir(parents=True)
    (version / "SK_vitruvian.uasset").write_bytes(b"imported")
    write_content_index(version, asset_id="vitruvian", version=1, bundle_id="fx-export-unreal")
    assert user_project_problems(project) == []
    (version / "Extra.uasset").write_bytes(b"added later")
    assert user_project_problems(project) == ["unindexed version content: Fluid/vitruvian/v001/Extra.uasset"]


def test_a_staging_folder_left_behind_asks_for_a_reconcile(tmp_path: Path):
    project = project_on(tmp_path, their_game(tmp_path))
    left = project.content_root / "_staging" / "task-1" / "SK.uasset"
    left.parent.mkdir(parents=True)
    left.write_bytes(b"half an import")
    (problem,) = user_project_problems(project)
    assert "staging folder was left" in problem and "reconcile" in problem


def test_a_linked_content_folder_is_refused(tmp_path: Path):
    project = project_on(tmp_path, their_game(tmp_path))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    project.content_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        project.content_root.symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip("not_run: this account cannot create a symbolic link")
    assert any("is a link" in p for p in user_project_problems(project))


def test_the_runner_refuses_before_it_looks_for_an_editor(tmp_path: Path, fixture_bundle: Path):
    project = project_on(tmp_path, their_game(tmp_path, plugins=[]))
    runner = TaskRunner(project)
    accepted = runner.run(
        make_request(
            "bundle.accept", "acc-001", project_id="my-game", parameters={"source_path": str(fixture_bundle)}
        )
    )
    assert accepted.exit_code == exit_codes.OK, accepted.result.model_dump()
    outcome = runner.run(
        make_request(
            "asset.import", "imp-001", project_id="my-game", target={"bundle_id": "fx-export-unreal"}
        )
    )
    assert outcome.exit_code == exit_codes.CONFLICT
    assert "PythonScriptPlugin" in outcome.result.errors[0].message
    assert not project.content_root.exists()
    assert outcome.task is None, "refused before a task existed"
    assert outcome.result.errors[0].details["problems"]
