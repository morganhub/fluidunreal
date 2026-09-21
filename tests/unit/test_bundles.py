"""U03 and U04: what comes in, and what is refused at the door.

The refusals are the point. A bundle is the only thing this kit lets in from outside, so each test
below is a way of getting something past it that must not work.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fluidblend.contracts.common import ErrorCode, OperationStatus
from fluidblend.core import exit_codes
from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import sha256_file

from fluidunreal.core.tasks import TaskRunner
from tests.conftest import make_request


def accept(runner, source: Path, operation_id="acc-001"):
    return runner.run(make_request("bundle.accept", operation_id, parameters={"source_path": str(source)}))


def altered(tmp_path: Path, fixture: Path, mutate) -> Path:
    """A copy of the reference bundle with one thing changed."""
    folder = tmp_path / "tampered"
    shutil.copytree(fixture, folder)
    mutate(folder)
    return folder


@pytest.fixture
def runner(project):
    return TaskRunner(project)


@pytest.mark.acceptance("U03", title="Accept a bundle published by fluidblend")
def test_U03_accept_verifies_everything_it_claims(runner, project, fixture_bundle):
    outcome = accept(runner, fixture_bundle)
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    metrics = outcome.result.metrics
    assert metrics["files_verified"] == 4 and metrics["producer"].startswith("fluidblend")
    assert metrics["khronos"] == "passed" and metrics["instances"] == 1

    copied = project.bundle_dir("fx-export-unreal")
    manifest = read_json(copied / "handoff-bundle.json")
    for entry in manifest["files"]:
        assert sha256_file(copied / entry["path"]) == entry["sha256"], entry["path"]
    assert (copied / "licenses").is_dir(), "the licence travels with the bundle"

    report = read_json(project.root / outcome.result.artifacts[0].path)
    assert report["licences"] and report["producer_version"] == "0.6.0"
    assert report["instances"] == ["hero-01"] and report["clips"] == ["walk-baked"]

    # Replaying the same operation_id returns the same result and creates nothing new.
    again = accept(runner, fixture_bundle)
    assert again.exit_code == exit_codes.OK and again.replayed
    assert again.result.artifacts[0].path == outcome.result.artifacts[0].path


def test_a_tampered_file_is_refused(runner, tmp_path, fixture_bundle):
    def flip(folder: Path):
        model = next(folder.glob("*.glb"))
        data = bytearray(model.read_bytes())
        data[-1] ^= 0xFF
        model.write_bytes(bytes(data))

    outcome = accept(runner, altered(tmp_path, fixture_bundle, flip))
    assert outcome.exit_code == exit_codes.FAILED
    assert outcome.result.errors[0].code == ErrorCode.VALIDATION_FAILED
    assert "sha256" in outcome.result.errors[0].message


def test_a_missing_file_is_refused(runner, tmp_path, fixture_bundle):
    outcome = accept(runner, altered(tmp_path, fixture_bundle, lambda f: next(f.glob("*.glb")).unlink()))
    assert outcome.exit_code == exit_codes.FAILED
    assert "does not carry" in outcome.result.errors[0].message


def test_an_empty_licence_is_refused(runner, tmp_path, fixture_bundle):
    def empty(folder: Path):
        licence = next((folder / "licenses").glob("*"))
        licence.write_text("", encoding="utf-8")
        manifest = json.loads((folder / "handoff-bundle.json").read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            if entry["role"] == "license":
                entry["sha256"] = sha256_file(licence)
                entry["bytes"] = 0
        (folder / "handoff-bundle.json").write_text(json.dumps(manifest), encoding="utf-8")

    outcome = accept(runner, altered(tmp_path, fixture_bundle, empty))
    assert outcome.exit_code == exit_codes.BLOCKED
    assert outcome.result.errors[0].code == ErrorCode.PERMISSION_REQUIRED


def test_a_bundle_from_an_older_producer_is_refused(runner, tmp_path, fixture_bundle):
    def downgrade(folder: Path):
        manifest = json.loads((folder / "handoff-bundle.json").read_text(encoding="utf-8"))
        manifest["producer"]["version"] = "0.5.1"
        (folder / "handoff-bundle.json").write_text(json.dumps(manifest), encoding="utf-8")

    outcome = accept(runner, altered(tmp_path, fixture_bundle, downgrade))
    assert outcome.exit_code == exit_codes.FAILED
    assert "0.6.0" in (outcome.result.errors[0].recovery or "")


def test_the_same_bundle_id_with_different_contents_is_a_conflict(runner, tmp_path, fixture_bundle):
    assert accept(runner, fixture_bundle).exit_code == exit_codes.OK

    def touch(folder: Path):
        manifest = json.loads((folder / "handoff-bundle.json").read_text(encoding="utf-8"))
        manifest["warnings"] = ["something else entirely"]
        (folder / "handoff-bundle.json").write_text(json.dumps(manifest), encoding="utf-8")

    outcome = accept(runner, altered(tmp_path, fixture_bundle, touch), operation_id="acc-002")
    assert outcome.exit_code == exit_codes.CONFLICT
    assert outcome.result.errors[0].code == ErrorCode.SCENE_CONFLICT


def test_a_folder_without_a_manifest_and_a_unc_path_are_refused(runner, tmp_path):
    empty = tmp_path / "not-a-bundle"
    empty.mkdir()
    outcome = accept(runner, empty)
    assert outcome.exit_code == exit_codes.FAILED and "handoff-bundle.json" in str(
        outcome.result.errors[0].message
    )

    unc = runner.run(
        make_request("bundle.accept", "acc-unc", parameters={"source_path": r"\\server\share\bundle"})
    )
    assert unc.exit_code == exit_codes.BLOCKED
    assert unc.result.errors[0].code == ErrorCode.PERMISSION_REQUIRED


def test_reusing_an_operation_id_with_other_parameters_is_a_conflict(runner, tmp_path, fixture_bundle):
    assert accept(runner, fixture_bundle).exit_code == exit_codes.OK
    other = tmp_path / "elsewhere"
    shutil.copytree(fixture_bundle, other)
    outcome = accept(runner, other)  # same operation_id, different source_path
    assert outcome.exit_code == exit_codes.CONFLICT
    assert "different parameters" in outcome.result.errors[0].message


def test_a_dry_run_executes_nothing_but_says_what_it_would_need(runner, project, fixture_bundle):
    outcome = runner.run(
        make_request("bundle.accept", "acc-dry", parameters={"source_path": str(fixture_bundle)}),
        force_dry_run=True,
    )
    assert outcome.exit_code == exit_codes.OK
    assert outcome.result.status == OperationStatus.planned
    assert outcome.result.metrics["dry_run"] is True
    assert outcome.result.metrics["input_paths"] == ["source_path"]
    assert not project.bundle_dir("fx-export-unreal").exists()


@pytest.mark.acceptance("U04", title="Wrap a third-party GLB into a bundle")
def test_U04_wrap_describes_only_what_the_file_says(runner, project, fixture_bundle, tmp_path):
    # Stand in for a downloaded model: the same GLB, with a licence the user supplies.
    shutil.copy2(next(fixture_bundle.glob("*.glb")), project.root / "incoming.glb")
    (project.root / "licenses" / "third-party.md").write_text(
        "# Quaternius-style CC0 asset\n\nCC0-1.0.\n", encoding="utf-8"
    )
    outcome = runner.run(
        make_request(
            "bundle.wrap",
            "wrap-001",
            parameters={
                "model_path": "incoming.glb",
                "license_path": "licenses/third-party.md",
                "license": "CC0-1.0",
                "bundle_id": "third-party-01",
                "fps_numerator": 24,
            },
        )
    )
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    assert outcome.result.metrics["skinned"] is True
    # 188 joints in the GLB. Unreal reports 189 after import because it adds a proxy root: the
    # bundle describes the file, the audit reconciles the difference.
    assert outcome.result.metrics["bone_count"] == 188

    manifest = read_json(project.bundle_dir("third-party-01") / "handoff-bundle.json")
    assert manifest["producer"]["kit"] == "external"
    assert manifest["instances"][0]["license"] == "CC0-1.0"
    # Nothing is invented: a wrapped GLB has no reference pose, and the kit says what that costs.
    assert manifest["instances"][0]["reference_pose"] == []
    limits = outcome.result.metrics["limits"]
    assert any("no reference pose" in limit for limit in limits)


def test_wrap_refuses_a_format_it_cannot_read(runner, project):
    (project.root / "model.fbx").write_bytes(b"not a glb")
    (project.root / "licenses" / "x.md").write_text("CC0\n", encoding="utf-8")
    outcome = runner.run(
        make_request(
            "bundle.wrap",
            "wrap-fbx",
            parameters={
                "model_path": "model.fbx",
                "license_path": "licenses/x.md",
                "license": "CC0-1.0",
                "bundle_id": "fbx-01",
            },
        )
    )
    assert outcome.exit_code == exit_codes.BLOCKED
    assert outcome.result.errors[0].code == ErrorCode.UNSUPPORTED_CAPABILITY


def test_wrap_refuses_a_file_that_is_not_a_glb(runner, project):
    (project.root / "fake.glb").write_bytes(b"NOPE" + b"\x00" * 64)
    (project.root / "licenses" / "x.md").write_text("CC0\n", encoding="utf-8")
    outcome = runner.run(
        make_request(
            "bundle.wrap",
            "wrap-fake",
            parameters={
                "model_path": "fake.glb",
                "license_path": "licenses/x.md",
                "license": "CC0-1.0",
                "bundle_id": "fake-01",
            },
        )
    )
    assert outcome.exit_code == exit_codes.FAILED
    assert "glTF magic" in outcome.result.errors[0].message


def test_inspect_reverifies_an_accepted_bundle(runner, project, fixture_bundle):
    assert accept(runner, fixture_bundle).exit_code == exit_codes.OK
    outcome = runner.run(make_request("bundle.inspect", "ins-001", target={"bundle_id": "fx-export-unreal"}))
    assert outcome.exit_code == exit_codes.OK
    report = read_json(project.root / outcome.result.artifacts[0].path)
    assert set(report["files"].values()) == {"verified"}
    assert report["imported_assets_in_project"] == []


def test_inspect_refuses_a_bundle_that_was_never_accepted(runner):
    outcome = runner.run(make_request("bundle.inspect", "ins-404", target={"bundle_id": "ghost-01"}))
    assert outcome.exit_code == exit_codes.FAILED
    assert "no accepted bundle" in outcome.result.errors[0].message


def test_an_operation_that_is_not_implemented_yet_says_so_rather_than_pretending(runner):
    outcome = runner.run(
        make_request(
            "asset.audit", "aud-001", target={"bundle_id": "fx-export-unreal", "asset_id": "vitruvian"}
        )
    )
    assert outcome.exit_code == exit_codes.BLOCKED
    assert outcome.result.errors[0].code == ErrorCode.UNSUPPORTED_CAPABILITY
    assert "not available in this lot" in outcome.result.errors[0].message
    assert "ops --all" in (outcome.result.errors[0].recovery or "")
