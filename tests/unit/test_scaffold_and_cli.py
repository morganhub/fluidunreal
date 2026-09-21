"""U02: creating a project, twice, and what the CLI refuses."""

from __future__ import annotations

from pathlib import Path

import pytest
from fluidblend.core import exit_codes
from fluidblend.core.state import StateStore

from fluidunreal.cli import main
from fluidunreal.core.project import ProjectError, inspect_project, load_project, scaffold_project


@pytest.mark.acceptance("U02", title="Initialize a project, and re-run the initialization")
def test_U02_init_is_idempotent_and_keeps_manual_edits(tmp_path: Path):
    root = tmp_path / "Mon Jeu é"
    report = scaffold_project(root, project_id="my-game", name="Mon Jeu")
    assert (root / "project.json").exists() and (root / "config" / "permissions.json").exists()
    # Seven scaffold files plus the three of the pinned test bed.
    assert len(report["created_files"]) == 10 and report["conflicts"] == []
    assert (root / "ue" / "FluidUnrealTestBed" / "FluidUnrealTestBed.uproject").is_file()
    outside = [p for p in tmp_path.rglob("*") if root not in p.parents and p != root]
    assert outside == [], f"writes outside the scope: {outside}"

    project = load_project(root)
    assert project.project_id == "my-game" and project.manifest.ue.engine_series == "5.8"
    assert project.manifest.name == "Mon Jeu"

    # A re-run creates nothing and does not rewrite the creation date.
    again = scaffold_project(root, project_id="my-game", name="Mon Jeu")
    assert again["created_files"] == [] and again["conflicts"] == []
    assert len(again["identical"]) == 7

    agents = root / "AGENTS.md"
    agents.write_text("# My own rules\n", encoding="utf-8")
    third = scaffold_project(root, project_id="my-game", name="Mon Jeu")
    assert [c["path"] for c in third["conflicts"]] == ["AGENTS.md"]
    assert agents.read_text(encoding="utf-8") == "# My own rules\n"

    events = StateStore(root).rebuild(save=False)
    assert events["initialized_at"] is not None


def test_a_dry_run_writes_nothing(tmp_path: Path):
    root = tmp_path / "dry"
    report = scaffold_project(root, project_id="my-game", dry_run=True)
    assert report["dry_run"] and report["created_files"] and not root.exists()


def test_strict_reports_a_conflict_as_exit_3(tmp_path: Path):
    root = tmp_path / "strict"
    assert main(["init", "--path", str(root), "--project-id", "my-game"]) == exit_codes.OK
    (root / "AGENTS.md").write_text("mine\n", encoding="utf-8")
    assert main(["init", "--path", str(root), "--project-id", "my-game", "--strict"]) == exit_codes.CONFLICT
    assert main(["init", "--path", str(root), "--project-id", "my-game"]) == exit_codes.OK


def test_an_existing_unreal_project_must_be_a_real_absolute_uproject(tmp_path: Path):
    root = tmp_path / "existing"
    with pytest.raises(ProjectError, match="absolute path"):
        scaffold_project(root, project_id="my-game", ue_project="ue/Some.uproject")
    with pytest.raises(ProjectError, match="not a .uproject"):
        scaffold_project(root, project_id="my-game", ue_project=str(tmp_path / "nope.uproject"))

    real = tmp_path / "TheirGame" / "TheirGame.uproject"
    real.parent.mkdir(parents=True)
    real.write_text('{"FileVersion": 3}', encoding="utf-8")
    report = scaffold_project(root, project_id="my-game", ue_project=str(real))
    assert report["uproject"] == str(real)
    project = load_project(root)
    assert project.uproject == real
    # The kit writes under Content/Fluid and nowhere else in someone else's project.
    assert project.content_root == real.parent / "Content" / "Fluid"


def test_the_test_bed_is_the_default_and_lives_inside_the_project(tmp_path: Path):
    root = tmp_path / "bed"
    scaffold_project(root, project_id="my-game")
    project = load_project(root)
    assert not Path(project.manifest.ue.uproject).is_absolute()
    assert project.root in project.uproject.parents


def test_inspect_reports_the_engine_working_dirs_without_counting_them(tmp_path: Path):
    root = tmp_path / "sizes"
    scaffold_project(root, project_id="my-game")
    project = load_project(root)
    saved = project.uproject.parent / "Saved"
    saved.mkdir(parents=True)
    (saved / "big.bin").write_bytes(b"x" * 4096)

    facts = inspect_project(project)
    assert facts["engine_working_dirs_bytes"]["Saved"] == 4096
    assert facts["bundles"] == [] and facts["imported_assets"] == []
    assert facts["uproject_exists"] is True, "init laid the test bed down"
    assert facts["engine_series"] == "5.8"


def test_an_invalid_project_id_is_refused(tmp_path: Path):
    with pytest.raises(ProjectError, match="invalid project_id"):
        scaffold_project(tmp_path / "bad", project_id="My Game")


def test_cli_ops_lists_what_is_not_available_only_on_request(capsys):
    assert main(["ops"]) == exit_codes.OK
    visible = capsys.readouterr().out
    assert "bundle.accept" in visible and "asset.import" in visible
    assert "game.package" not in visible, "packaging is P2 and must not look runnable"
    assert "not available yet" in visible

    assert main(["ops", "--all", "--json"]) == exit_codes.OK
    every = capsys.readouterr().out
    assert "game.package" in every and "retarget.mannequin" in every


def test_cli_reports_a_missing_project_as_blocked(tmp_path: Path, capsys):
    assert main(["inspect", "--project", str(tmp_path / "nowhere")]) == exit_codes.BLOCKED
    assert "no project.json" in capsys.readouterr().err
