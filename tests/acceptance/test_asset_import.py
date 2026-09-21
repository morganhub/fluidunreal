"""U05: a bundle imported into Unreal, and what the kit checks before it publishes anything.

Marked `unreal`: without the locked engine these are skipped as `not_run`, never counted as passed.
"""

from __future__ import annotations

import json

import pytest
from fluidblend.contracts.common import ErrorCode
from fluidblend.core import exit_codes
from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.revisions import RevisionStore

from fluidunreal.core.tasks import TaskRunner
from fluidunreal.core.ue_content import CONTENT_INDEX, verify_content
from tests.conftest import make_request, note

pytestmark = pytest.mark.unreal


@pytest.fixture
def imported(project, fixture_bundle):
    runner = TaskRunner(project)
    accepted = runner.run(
        make_request("bundle.accept", "acc-001", parameters={"source_path": str(fixture_bundle)})
    )
    assert accepted.exit_code == exit_codes.OK, accepted.result.model_dump()
    return runner


@pytest.mark.acceptance("U05", title="Import a bundle into Unreal and publish it as a version")
def test_U05_import_publishes_a_version_it_checked_first(imported, project):
    outcome = imported.run(make_request("asset.import", "imp-001", target={"bundle_id": "fx-export-unreal"}))
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    metrics = outcome.result.metrics

    # What the bundle said, measured against what the engine wrote.
    assert metrics["asset_id"] == "vitruvian" and metrics["version"] == 1
    assert metrics["bone_count"] == 188, "the bundle's count, with the proxy root excluded"
    assert metrics["animations"] == 1
    assert metrics["content_path"] == "/Game/Fluid/vitruvian/v001"
    assert outcome.result.new_revision == 1

    version_dir = project.asset_dir("vitruvian") / "v001"
    assert (version_dir / CONTENT_INDEX).is_file()
    assert verify_content(version_dir) == []

    names = {p.stem for p in version_dir.rglob("*.uasset")}
    assert {"SK_vitruvian", "SKEL_vitruvian", "A_vitruvian_walk-baked"} <= names

    # The revision points at the index, so an edit in the editor is caught later.
    record = RevisionStore(project.root).get("asset:vitruvian")
    assert record and record.revision == 1
    assert sha256_file(project.root / record.path) == record.sha256

    # Nothing half-imported is left behind.
    assert not (project.content_root / "_staging").exists()

    report = read_json(project.root / outcome.result.artifacts[0].path)
    assert report["bones_added_by_importer"] == ["CustomRig_Vitruvian_ProxyTrueRootJoint"]
    limits = metrics["limits"]
    assert any("47 frames against the bundle's 48" in limit for limit in limits)
    assert any("MaterialInstanceConstant" in limit for limit in limits)
    note(
        "U05",
        f"188 deform bones, one animation, published as v001 in {metrics['unreal_elapsed_s']}s; "
        "the importer's proxy root and its extra assets are reported, not claimed away",
    )


def test_a_second_import_makes_the_next_version_and_keeps_the_first(imported, project):
    first = imported.run(make_request("asset.import", "imp-001", target={"bundle_id": "fx-export-unreal"}))
    assert first.exit_code == exit_codes.OK
    second = imported.run(
        make_request(
            "asset.import",
            "imp-002",
            target={"bundle_id": "fx-export-unreal"},
            parameters={"replace_existing": True},
        )
    )
    assert second.exit_code == exit_codes.OK, second.result.model_dump()
    assert second.result.metrics["version"] == 2 and second.result.new_revision == 2

    versions = sorted(p.name for p in project.asset_dir("vitruvian").iterdir() if p.is_dir())
    assert versions == ["v001", "v002"], "a published version is never overwritten"
    assert verify_content(project.asset_dir("vitruvian") / "v001") == []


def test_replaying_the_same_import_creates_no_new_version(imported, project):
    first = imported.run(make_request("asset.import", "imp-001", target={"bundle_id": "fx-export-unreal"}))
    assert first.exit_code == exit_codes.OK
    again = imported.run(make_request("asset.import", "imp-001", target={"bundle_id": "fx-export-unreal"}))
    assert again.exit_code == exit_codes.OK and again.replayed
    versions = sorted(p.name for p in project.asset_dir("vitruvian").iterdir() if p.is_dir())
    assert versions == ["v001"]


def test_a_bundle_whose_bone_count_is_wrong_publishes_nothing(imported, project):
    """The negative control: the check has to bite, or passing it means nothing."""
    manifest = project.bundle_dir("fx-export-unreal") / "handoff-bundle.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["instances"][0]["bone_count"] = 42
    manifest.write_text(json.dumps(data), encoding="utf-8")

    outcome = imported.run(make_request("asset.import", "imp-bad", target={"bundle_id": "fx-export-unreal"}))
    assert outcome.exit_code != exit_codes.OK
    assert outcome.result.errors[0].code == ErrorCode.VALIDATION_FAILED
    assert "42 bones" in outcome.result.errors[0].message
    assert not project.asset_dir("vitruvian").exists(), "nothing is published on a failed check"
    assert not (project.content_root / "_staging").exists(), "the staging area is cleaned"


def test_an_import_needs_an_accepted_bundle(project):
    outcome = TaskRunner(project).run(
        make_request("asset.import", "imp-404", target={"bundle_id": "never-accepted"})
    )
    assert outcome.exit_code == exit_codes.FAILED
    assert "no accepted bundle" in outcome.result.errors[0].message
