"""U07: the imported character played in the kit's test bed, and the bed proven able to fail.

Marked `unreal`: without the locked engine these are skipped as `not_run`, never counted as passed.
"""

from __future__ import annotations

import pytest
from fluidblend.core import exit_codes
from fluidblend.core.atomic import read_json

from fluidunreal.core.tasks import TaskRunner
from tests.conftest import make_request, note

pytestmark = pytest.mark.unreal

NOT_BUILT = {"idle_plays_nothing", "back_to_idle", "holds_prop", "pickup_empty"}


@pytest.fixture
def imported(project, fixture_bundle):
    runner = TaskRunner(project)
    accepted = runner.run(
        make_request("bundle.accept", "acc-001", parameters={"source_path": str(fixture_bundle)})
    )
    assert accepted.exit_code == exit_codes.OK, accepted.result.model_dump()
    outcome = runner.run(make_request("asset.import", "imp-001", target={"bundle_id": "fx-export-unreal"}))
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    return runner


def smoke(runner, operation_id, **parameters):
    return runner.run(
        make_request(
            operation_id=operation_id,
            operation="game.smoke_test",
            target={"bundle_id": "fx-export-unreal", "asset_id": "vitruvian"},
            parameters=parameters,
        )
    )


def report(project, operation_id):
    return read_json(project.root / "reviews" / "game" / operation_id / "smoke-report.json")


@pytest.mark.acceptance("U07", title="Play the character headless in the test bed and report 14 checks")
def test_U07_the_bed_plays_the_character_and_says_what_it_did_not_measure(imported, project):
    outcome = smoke(imported, "smoke-001")
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    bed = report(project, "smoke-001")
    checks = bed["checks"]

    assert len(checks) == 14 and bed["passed"] is True and bed["failed_checks"] == []
    # Not measured is listed, never counted as a pass.
    assert set(bed["not_run_checks"]) == NOT_BUILT
    assert all(checks[name]["passed"] is True for name in set(checks) - NOT_BUILT)
    assert bed["started_with"] == "editor_request_begin_play" and bed["headless"] is True

    # The clip advances in PIE: its position moves and the player says it is playing.
    playing = checks["walk_plays_looping"]["detail"]
    assert playing["is_playing"] is True and playing["position_to_s"] > playing["position_from_s"]

    # The skeleton deforms: the distance between the feet changes while the actor stands still.
    moves = checks["walk_clip_moves_bones"]["detail"]
    assert moves["actor_moved_cm"] < 0.01
    assert moves["distance_range_cm_by_pair"]["DEF-foot_L~DEF-foot_R"] > moves["threshold_cm"]

    assert checks["character_moves"]["detail"]["delta_x_cm"] > 10.0
    assert checks["wall_stops_it"]["detail"]["peak_x"] <= 402.0
    feet = moves["distance_range_cm_by_pair"]["DEF-foot_L~DEF-foot_R"]
    note(
        "U07",
        f"10 checks measured and passed, 4 not measured by this bed; the distance between the feet "
        f"changes by {feet:.1f} cm with the actor still",
    )


def test_without_the_clip_the_bed_fails_by_name(imported, project):
    """The negative control: the same bed, no clip. The animation checks must fail, and say so."""
    outcome = smoke(imported, "smoke-noclip", clip_id="no-such-clip")
    assert outcome.exit_code == exit_codes.FAILED, outcome.result.model_dump()
    # A failed run publishes nothing: the report is where the error says it is.
    assert not (project.root / "reviews" / "game" / "smoke-noclip").exists()
    written = project.root / "state" / "tasks" / outcome.task.task_id / "out" / "smoke-report.json"
    assert str(written) in outcome.result.errors[0].recovery
    bed = read_json(written)

    assert bed["passed"] is False
    assert {"walk_clip_found", "walk_plays_looping", "walk_clip_moves_bones"} <= set(bed["failed_checks"])
    # What does not depend on the clip still passes: the failure is where it belongs.
    assert bed["checks"]["character_moves"]["passed"] is True
    assert (
        bed["checks"]["walk_clip_moves_bones"]["detail"]["distance_range_cm_by_pair"]["DEF-foot_L~DEF-foot_R"]
        <= bed["checks"]["walk_clip_moves_bones"]["detail"]["threshold_cm"]
    )
    assert outcome.result.errors[0].code == "VALIDATION_FAILED"
    assert "walk_clip_found" in outcome.result.errors[0].message
