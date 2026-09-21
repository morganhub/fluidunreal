"""U01: what the machine can actually do, and what the kit refuses to claim about it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fluidblend.core import exit_codes
from fluidblend.core.atomic import read_json

from fluidunreal.adapters import unreal_discovery as discovery
from fluidunreal.cli import main
from fluidunreal.contracts.project import LOCKED_UNREAL_SERIES
from fluidunreal.core.project import kit_root, template_problems
from fluidunreal.doctor import compare_lock, run_doctor, write_lock

TEMPLATE = kit_root() / "templates" / "game-unreal"


def statuses(report) -> dict[str, str]:
    return {c.capability_id: c.status for c in report.capabilities}


@pytest.mark.acceptance("U01", title="Diagnose the machine and lock the engine series")
def test_U01_doctor_reports_what_it_saw(project):
    report = run_doctor(project, probe=False)
    found = statuses(report)
    assert set(found) == {
        "unreal.editor",
        "unreal.project",
        "unreal.python",
        "gltf.khronos_validator",
        "python.uv",
        "fluidblend.kit",
    }
    # Whatever this machine has, nothing is claimed available without having been seen working.
    python = next(c for c in report.capabilities if c.capability_id == "unreal.python")
    assert python.status != "available", "the probe was not run: available must not be claimed"
    assert "not probed" in (python.error or "")

    editor = next(c for c in report.capabilities if c.capability_id == "unreal.editor")
    if editor.status == "available":
        assert editor.evidence["locked_series"] == LOCKED_UNREAL_SERIES
        assert editor.evidence["sha256"] and editor.version
    else:
        assert editor.status in ("not_installed", "incompatible") and editor.error

    written = read_json(project.root / "state" / "diagnostics" / "capabilities.json")
    assert written["host"]["locked_unreal_series"] == LOCKED_UNREAL_SERIES


def test_the_test_bed_is_laid_down_and_pinned(project):
    assert project.uproject.is_file(), "init lays down the test bed"
    assert template_problems(TEMPLATE) == []
    manifest = read_json(TEMPLATE / "template-manifest.json")
    assert manifest["engine_series"] == LOCKED_UNREAL_SERIES
    assert set(manifest["files"]) == {
        "Config/DefaultEngine.ini",
        "Config/DefaultGame.ini",
        "FluidUnrealTestBed.uproject",
    }


def test_a_modified_test_bed_is_reported_not_repaired(tmp_path: Path):
    import shutil

    copy = tmp_path / "game-unreal"
    shutil.copytree(TEMPLATE, copy)
    (copy / "Config" / "DefaultEngine.ini").write_text("; tampered\n", encoding="utf-8")
    problems = template_problems(copy)
    assert problems == ["differs from its pinned hash: Config/DefaultEngine.ini"]

    (copy / "FluidUnrealTestBed.uproject").unlink()
    assert any("missing from the template" in p for p in template_problems(copy))


def test_the_test_bed_asks_for_no_plugin_that_would_abort_the_editor(project):
    """Lot 0: requesting GLTFImporter on 5.8 kills the editor before any script runs."""
    plugins, fatal = discovery.project_plugins(project.uproject)
    assert fatal == [], f"these plugins do not exist on {LOCKED_UNREAL_SERIES}: {fatal}"
    assert "PythonScriptPlugin" in plugins
    # Interchange carries glTF import and the engine enables it: asking for it is not this kit's job.
    assert not any(name.startswith("Interchange") for name in plugins)


def test_a_project_requesting_a_missing_plugin_is_incompatible(project):
    data = json.loads(project.uproject.read_text(encoding="utf-8"))
    data["Plugins"].append({"Name": "GLTFImporter", "Enabled": True})
    project.uproject.write_text(json.dumps(data), encoding="utf-8")
    report = run_doctor(project, probe=False)
    entry = next(c for c in report.capabilities if c.capability_id == "unreal.project")
    assert entry.status == "incompatible"
    assert any("abort the editor" in r for r in entry.restrictions)


def test_the_lock_records_no_machine_paths_and_drift_is_reported(project, tmp_path: Path):
    report = run_doctor(project, probe=False)
    lock_path = tmp_path / "dependencies.lock.json"
    lock = write_lock(project, report, lock_path)
    assert all(entry["path"] is None for entry in lock["dependencies"].values())
    assert lock["extra"]["unreal_locked_series"] == LOCKED_UNREAL_SERIES
    assert compare_lock(report, lock) == []

    lock["dependencies"]["unreal.editor"]["version"] = "5.7.0"
    drift = compare_lock(report, lock)
    assert any("unreal.editor" in entry and "5.7.0" in entry for entry in drift)


def test_capabilities_needs_a_diagnostic_before_it_can_answer(project, capsys):
    assert main(["capabilities", "--project", str(project.root)]) == exit_codes.BLOCKED
    assert "run `fluidunreal doctor" in capsys.readouterr().err

    assert main(["doctor", "--project", str(project.root), "--no-probe"]) == exit_codes.OK
    capsys.readouterr()
    assert main(["capabilities", "--project", str(project.root)]) == exit_codes.OK
    assert "unreal.editor" in capsys.readouterr().out


def test_a_foreign_series_is_never_selected(monkeypatch):
    info = discovery.EngineInfo(path="X:/UE_9.9/UnrealEditor-Cmd.exe", version="9.9.0", series="9.9")
    monkeypatch.setattr(discovery, "discover", lambda configured=None: [info])
    chosen, notes = discovery.select(None)
    assert chosen is None
    assert any("not the locked" in note for note in notes)


def test_the_pinned_hashes_match_what_git_stores():
    """A pin over the working copy is worth nothing if git hands a checkout different bytes.

    The template was pinned over CRLF that Windows wrote, while git stored LF, so every checkout on
    CI failed to match. The template is marked `-text` now, and this compares the pin to the bytes
    git actually keeps rather than to the ones on this disk.
    """
    import hashlib
    import subprocess

    root = kit_root()
    pinned = read_json(TEMPLATE / "template-manifest.json")["files"]
    for relative, digest in sorted(pinned.items()):
        tracked = f"templates/game-unreal/{relative}"
        stored = subprocess.run(  # noqa: S603 - argument list
            ["git", "-C", str(root), "cat-file", "blob", f":{tracked}"],
            capture_output=True,
            check=False,
        )
        if stored.returncode != 0:
            pytest.skip(f"not_run: {tracked} is not in the index")
        assert hashlib.sha256(stored.stdout).hexdigest() == digest, (
            f"{tracked}: git stores different bytes than the pin records"
        )
