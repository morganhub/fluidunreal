"""U06: measuring what the engine wrote, and proving the measurements can fail."""

from __future__ import annotations

import json

import pytest
from fluidblend.core import exit_codes
from fluidblend.core.atomic import read_json

from fluidunreal.core.tasks import TaskRunner
from tests.conftest import make_request, note

pytestmark = pytest.mark.unreal


@pytest.fixture
def audited(project, fixture_bundle):
    runner = TaskRunner(project)
    accepted = runner.run(
        make_request("bundle.accept", "acc-001", parameters={"source_path": str(fixture_bundle)})
    )
    assert accepted.exit_code == exit_codes.OK, accepted.result.model_dump()
    return runner


def audit(runner, operation_id="aud-001"):
    return runner.run(
        make_request(
            operation_id=operation_id,
            operation="asset.audit",
            target={"bundle_id": "fx-export-unreal", "asset_id": "vitruvian"},
        )
    )


def imported(runner):
    outcome = runner.run(make_request("asset.import", "imp-001", target={"bundle_id": "fx-export-unreal"}))
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    return outcome


def rows(project, operation_id="aud-001"):
    """Indexed by kind and name: an animation carries both a length and a root motion row."""
    report = read_json(project.root / "reviews" / "assets" / operation_id / "audit-report.json")
    return report, {(m["kind"], m["name"]): m for m in report["measurements"]}


@pytest.mark.acceptance("U06", title="Audit the imported asset: scale, axes, length, root motion")
def test_U06_the_audit_measures_rather_than_assumes(audited, project):
    imported(audited)
    outcome = audit(audited)
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    report, by_name = rows(project)

    # The scale is measured in centimetres against the bundle's metres, not assumed to be x100.
    for bone in ("DEF-spine", "DEF-forehead.R", "DEF-big_toe.02.L"):
        measurement = by_name[("scale_check", bone)]
        assert measurement["kind"] == "scale_check" and measurement["passed"] is True
        assert measurement["unit"] == "cm" and measurement["tolerance"] == 1.0
        assert abs(measurement["observed"] - measurement["expected"]) <= 1.0
    assert by_name[("scale_check", "DEF-forehead.R")]["expected"] == pytest.approx(169.285, abs=0.01)

    assert by_name[("axis_check", "highest reference bone")]["passed"] is True
    assert by_name[("bone_count", "deform bones")]["observed"] == 188
    assert by_name[("bone_count", "deform bones")]["detail"]["added_by_importer"] == [
        "CustomRig_Vitruvian_ProxyTrueRootJoint"
    ]

    length = by_name[("anim_length", "A_vitruvian_walk-baked")]
    assert length["observed"] == 47 and length["expected"] == 48
    assert length["passed"] is True, "one frame of glTF sampling, inside the tolerance"

    # The reference walk is declared in place and travels: the audit says so, on the bones that
    # carry the body. Lot 0 read the importer's proxy joint, got 0.0 cm, and passed it.
    travel = by_name[("root_motion_travel", "A_vitruvian_walk-baked")]
    control = by_name[("root_motion_travel", "control: A_vitruvian_walk-baked")]
    assert travel["detail"]["declared"] == "in_place"
    assert "ProxyTrueRootJoint" in travel["detail"]["read_on"] and "75 bones" in travel["detail"]["read_on"]
    assert report["root_motion_read_on"][0] != "CustomRig_Vitruvian_ProxyTrueRootJoint"
    assert travel["observed"] == pytest.approx(57.5, abs=1.5) and travel["passed"] is False
    assert "slides ahead of its capsule" in travel["detail"]["why"]
    assert control["passed"] is True and control["observed"] > 1.0, "the reader reads moving data"

    assert outcome.result.metrics["technical_pass"] is False, "a false declaration is a real defect"
    assert outcome.result.metrics["not_run"] == []
    assert any("declared in place" in action for action in outcome.result.next_safe_actions)
    note(
        "U06",
        "five reference bones within a millimetre, 188 deform bones, 47 frames against 48; the walk "
        "declared in place travels 57.5 cm over 75 top bones, and the audit fails it for that",
    )


def test_a_clip_declared_with_its_real_travel_passes(audited, project):
    """The positive control: the same clip, declared as the walk it was made from, passes.

    Without it, a root motion check that fails could be a check that always fails. The stride is
    the recipe's, not the number observed: fluidblend's walk defaults to amplitude 0.3, and its
    stride per cycle is twice that. Read over 46 frames of 48, 0.6 m is 57.5 cm.
    """
    imported(audited)
    manifest = project.bundle_dir("fx-export-unreal") / "handoff-bundle.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["clips"][0].update({"root_motion": "root_bone", "stride_m": 0.6})
    manifest.write_text(json.dumps(data), encoding="utf-8")

    outcome = audit(audited, "aud-travel")
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    _report, by_name = rows(project, "aud-travel")
    travel = by_name[("root_motion_travel", "A_vitruvian_walk-baked")]
    assert travel["detail"]["span_of_clip_read"] == "46 of 48 frames"
    assert travel["expected"] == pytest.approx(57.5) and travel["passed"] is True
    assert outcome.result.metrics["technical_pass"] is True

    # And a stride that is wrong by more than the tolerance fails: 0.5 m is 47.9 cm over that span.
    data["clips"][0]["stride_m"] = 0.5
    manifest.write_text(json.dumps(data), encoding="utf-8")
    wrong = audit(audited, "aud-short")
    _report, by_name = rows(project, "aud-short")
    assert by_name[("root_motion_travel", "A_vitruvian_walk-baked")]["passed"] is False
    assert wrong.result.metrics["technical_pass"] is False


def test_a_falsified_reference_pose_fails_every_scale_check(audited, project):
    """The negative control. Without it, five green measurements prove only that nothing ran."""
    imported(audited)
    manifest = project.bundle_dir("fx-export-unreal") / "handoff-bundle.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for entry in data["instances"][0]["reference_pose"]:
        entry["head_m"][2] += 0.10
    manifest.write_text(json.dumps(data), encoding="utf-8")

    outcome = audit(audited, "aud-bad")
    assert outcome.exit_code == exit_codes.OK, "the audit reads, it does not fail on a bad asset"
    _report, by_name = rows(project, "aud-bad")
    scale = [m for m in by_name.values() if m["kind"] == "scale_check"]
    assert len(scale) == 5 and all(m["passed"] is False for m in scale)
    assert outcome.result.metrics["technical_pass"] is False


def test_a_bundle_without_a_reference_pose_reports_not_run_rather_than_a_pass(audited, project):
    imported(audited)
    manifest = project.bundle_dir("fx-export-unreal") / "handoff-bundle.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["instances"][0]["reference_pose"] = []
    manifest.write_text(json.dumps(data), encoding="utf-8")

    outcome = audit(audited, "aud-nopose")
    assert outcome.exit_code == exit_codes.OK
    report, by_name = rows(project, "aud-nopose")
    assert not any(m["kind"] == "scale_check" for m in report["measurements"])
    assert any("no reference pose" in limit for limit in report["limits"])
    assert by_name[("bone_count", "deform bones")]["passed"] is True, "what could still be measured, was"


def test_the_audit_refuses_an_asset_that_was_never_imported(audited):
    outcome = audit(audited, "aud-early")
    assert outcome.exit_code != exit_codes.OK
    assert "has not been imported" in outcome.result.errors[0].message
