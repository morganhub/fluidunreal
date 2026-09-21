"""U08: one rendered frame of the test bed, the share the character covers, and its control.

Marked `unreal`: without the locked engine these are skipped as `not_run`, never counted as passed.
Without a usable GPU the operation answers MISSING_DEPENDENCY, and the scenario is `not_run` too.
"""

from __future__ import annotations

import pytest
from fluidblend.core import exit_codes
from fluidblend.core.atomic import read_json

from fluidunreal.core.tasks import TaskRunner
from tests.conftest import make_request, note

pytestmark = pytest.mark.unreal


def imported(project, fixture_bundle, **hooks):
    runner = TaskRunner(project, test_hooks=hooks)
    accepted = runner.run(
        make_request("bundle.accept", "acc-001", parameters={"source_path": str(fixture_bundle)})
    )
    assert accepted.exit_code == exit_codes.OK, accepted.result.model_dump()
    outcome = runner.run(make_request("asset.import", "imp-001", target={"bundle_id": "fx-export-unreal"}))
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    return runner


def shoot(runner, operation_id):
    outcome = runner.run(
        make_request(
            operation_id=operation_id,
            operation="game.screenshot",
            target={"bundle_id": "fx-export-unreal", "asset_id": "vitruvian"},
        )
    )
    if outcome.result.errors and outcome.result.errors[0].code == "MISSING_DEPENDENCY":
        pytest.skip("not_run: no usable GPU, the engine wrote no frame")
    return outcome


@pytest.mark.acceptance("U08", title="Render one frame off-screen and measure the share the character covers")
def test_U08_the_frame_shows_the_character_and_only_the_character_differs(project, fixture_bundle):
    runner = imported(project, fixture_bundle)
    outcome = shoot(runner, "shot-001")
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    folder = project.root / "reviews" / "game" / "shot-001"
    report = read_json(folder / "screenshot-report.json")

    for name in ("ue-frame.png", "ue-frame-empty.png"):
        data = (folder / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 10_000, name
    assert {a.path.rsplit("/", 1)[-1] for a in outcome.result.artifacts if a.kind == "image"} == {
        "ue-frame.png",
        "ue-frame-empty.png",
    }

    comparison = report["comparison"]
    assert report["passed"] is True and report["refused_because"] is None
    assert report["threshold"] <= report["rendered_share"] <= report["ceiling"]
    # One region, not the whole frame: lot 0's 69 % differed everywhere, and that is the tell.
    box = comparison["box"]
    assert (box[2] - box[0] + 1) < 0.6 * comparison["width"]
    assert report["camera"]["through"].startswith("SceneCapture2D")
    assert report["mesh_offset"]["yaw_deg"] == -90.0 and report["looked_at"] is False
    # Where the character was when shot: on the line it walked, facing the way it walked.
    assert abs(report["character"]["actor_cm"][1]) <= 5.0
    assert abs(report["character"]["facing_error_deg"]) < 10.0
    assert any("open ue-frame.png" in action for action in outcome.result.next_safe_actions)
    note(
        "U08",
        f"the character and its shadow cover {report['rendered_share']:.2%} of a "
        f"{comparison['width']}x{comparison['height']} frame, in one region {box}; the frames were "
        "opened and looked at when this scenario was written (docs/reviews)",
    )


def test_without_the_character_in_either_frame_nothing_differs(project, fixture_bundle):
    """The negative control of U08: the same run with the character hidden from both frames."""
    runner = imported(project, fixture_bundle, frame_without_character=True)
    outcome = shoot(runner, "shot-empty")
    assert outcome.exit_code == exit_codes.FAILED, outcome.result.model_dump()
    written = project.root / "state" / "tasks" / outcome.task.task_id / "out" / "screenshot-report.json"
    report = read_json(written)
    assert report["rendered_share"] < 0.001 and report["passed"] is False
    assert outcome.result.errors[0].code == "VALIDATION_FAILED"
    assert "under 1%" in outcome.result.errors[0].message
