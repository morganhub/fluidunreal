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
def test_U07_the_bed_plays_the_character_and_says_what_it_did(imported, project):
    outcome = smoke(imported, "smoke-001")
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    bed = report(project, "smoke-001")
    checks = bed["checks"]

    assert len(checks) == 14 and bed["passed"] is True
    assert bed["failed_checks"] == [] and bed["not_run_checks"] == []
    assert bed["started_with"] == "editor_request_begin_play" and bed["headless"] is True
    assert bed["wall_time_ms"] > 0 and "platform" in bed["machine"]

    # Standing: no clip is assigned and the pose holds. is_playing is not trusted for this.
    idle = checks["idle_plays_nothing"]["detail"]
    assert idle["assigned_clip"] == ["None"] and idle["feet_distance_range_cm"] <= 0.05

    # Walking: the clip wraps at least once, and the feet move relative to each other.
    looping = checks["walk_plays_looping"]["detail"]
    assert looping["wraps"] >= 1 and looping["always_playing"] is True
    moves = checks["walk_clip_moves_bones"]["detail"]
    assert moves["distance_range_cm_by_pair"]["DEF-foot_L~DEF-foot_R"] > moves["threshold_cm"]
    # Lot 4, first human review: the arms held out in their rest pose were seen, then measured.
    assert any("leaves the arms still" in warning for warning in outcome.result.warnings)
    walked = checks["character_moves"]["detail"]
    assert walked["delta_x_cm"] > 10.0 and abs(walked["lateral_cm"]) <= 5.0
    # Nothing moved the character before the walk: the default pawn once threw it 2.7 m.
    assert walked["positions_cm"]["ready"][:2] == walked["positions_cm"]["walk_start"][:2]
    assert abs(walked["facing_error_deg"]) < 10.0, "the mesh faces the way the character walks"
    assert checks["wall_stops_it"]["detail"]["peak_x"] <= 402.0

    # The feet are on the floor, not the capsule: the mesh once floated 88 cm above it.
    floor = checks["stands_on_floor"]["detail"]
    assert abs(floor["bone_height_cm"] - floor["bundle_height_cm"]) <= floor["tolerance_cm"]
    assert floor["mesh_offset"]["z_cm"] == -88.0 and floor["mesh_offset"]["yaw_deg"] == -90.0

    # Stopping: no speed, the clip stopped, the pose holds again.
    idle_again = checks["back_to_idle"]["detail"]
    assert idle_again["speed_cm_s"] < 1.0 and idle_again["clip_stopped_at_step"] is not None

    # The prop is on the hand after the hand carried it, and its old place is empty.
    held = checks["holds_prop"]["detail"]
    assert held["held_at"]["socket"] == "DEF-hand_R" and held["distance_to_hand_cm"] <= 5.0
    assert held["hand_moved_since_pickup_cm"] > 10.0
    assert checks["pickup_empty"]["detail"]["occupants"] == []
    assert any("right hand bone" in limit for limit in outcome.result.metrics["limits"])

    feet = moves["distance_range_cm_by_pair"]["DEF-foot_L~DEF-foot_R"]
    note(
        "U07",
        f"14 checks measured and passed; the clip wrapped {looping['wraps']} time(s), the distance "
        f"between the feet varied by {feet:.1f} cm, the prop stayed on the hand over "
        f"{held['hand_moved_since_pickup_cm']:.0f} cm",
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
    assert set(bed["failed_checks"]) == {"walk_clip_found", "walk_plays_looping", "walk_clip_moves_bones"}
    # What does not depend on the clip still passes: the failure is where it belongs.
    for name in ("character_moves", "idle_plays_nothing", "back_to_idle", "holds_prop"):
        assert bed["checks"][name]["passed"] is True, name
    assert (
        bed["checks"]["walk_clip_moves_bones"]["detail"]["distance_range_cm_by_pair"]["DEF-foot_L~DEF-foot_R"]
        <= bed["checks"]["walk_clip_moves_bones"]["detail"]["threshold_cm"]
    )
    assert outcome.result.errors[0].code == "VALIDATION_FAILED"
    assert "walk_clip_found" in outcome.result.errors[0].message
