"""U13: the hand-off back to fluidblend, validated by that kit rather than by this one."""

from __future__ import annotations

import json

import pytest
from fluidblend.contracts.common import ErrorCode
from fluidblend.contracts.operations import validate_request as validate_fluidblend_request
from fluidblend.core import exit_codes
from fluidblend.core.atomic import read_json

from fluidunreal.core.project import load_project, scaffold_project
from fluidunreal.core.tasks import TaskRunner
from fluidunreal.hostops.handoff import TEMPLATES
from tests.conftest import make_request, note


@pytest.fixture
def linked(tmp_path, fixture_bundle):
    """A project that knows where the fluidblend project is, with a bundle accepted."""
    root = tmp_path / "linked"
    scaffold_project(
        root,
        project_id="demo-game",
        fluidblend_project=str(tmp_path / "studio"),
    )
    project = load_project(root)
    runner = TaskRunner(project)
    accepted = runner.run(
        make_request("bundle.accept", "acc-001", parameters={"source_path": str(fixture_bundle)})
    )
    assert accepted.exit_code == exit_codes.OK, accepted.result.model_dump()
    return runner, project


def hand_off(runner, kind, operation_id=None, **parameters):
    return runner.run(
        make_request(
            "handoff.request",
            operation_id or f"handoff-{kind}",
            target={"bundle_id": "fx-export-unreal"},
            parameters={"kind": kind, **parameters},
        )
    )


@pytest.mark.acceptance("U13", title="Hand a fix back to fluidblend as a request it accepts")
@pytest.mark.parametrize("kind", TEMPLATES)
def test_U13_every_template_builds_a_request_fluidblend_accepts(linked, kind):
    runner, project = linked
    outcome = hand_off(runner, kind)
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()

    written = project.root / "requests" / "fluidblend" / f"handoff-{kind}.json"
    assert written.is_file()
    payload = json.loads(written.read_text(encoding="utf-8"))

    # The sibling kit is the judge, not this one.
    request, _params, spec = validate_fluidblend_request(payload)
    assert spec.available
    # It targets the project that produced the bundle, not the one running this kit.
    producer = read_json(project.bundle_dir("fx-export-unreal") / "handoff-bundle.json")["producer"]
    assert request.project_id == producer["project_id"]
    assert request.target.shot_id == producer["shot_id"]
    assert request.target.expected_revision == producer["source_revision"]

    # bundle_id is this kit's extension: it must never reach a kit whose models forbid it.
    assert "bundle_id" not in payload["target"]

    command = outcome.result.next_safe_actions[0]
    assert command.startswith("fluidblend run --project ")
    assert str(written) in command
    assert any("does not run fluidblend" in limit for limit in outcome.result.metrics["limits"])


def test_the_reexport_template_asks_for_what_unreal_needs(linked):
    runner, _project = linked
    outcome = hand_off(runner, "reexport_unreal", output_name="shot010-hero")
    parameters = read_json(_project_request(_project_of(linked), "handoff-reexport_unreal"))["parameters"]
    assert parameters["export_preset"] == "unreal" and parameters["export_def_bones"] is True
    assert parameters["output_name"] == "shot010-hero"
    assert parameters["instance_ids"] == ["hero-01"]
    assert outcome.result.metrics["fluidblend_operation"] == "game.export"


def test_the_bake_template_names_the_clip_and_its_range(linked):
    runner, project = linked
    outcome = hand_off(runner, "bake_rigid_limbs", clip_id="walk-baked", instance_id="hero-01")
    assert outcome.exit_code == exit_codes.OK
    payload = read_json(project.root / "requests" / "fluidblend" / "handoff-bake_rigid_limbs.json")
    assert payload["parameters"]["rigid_limbs"] is True
    assert payload["parameters"]["frame_range"] == {"start": 0, "end_exclusive": 48}
    assert payload["target"]["instance_id"] == "hero-01"


def test_the_look_template_asks_for_the_browser_and_says_what_comes_next(linked):
    runner, project = linked
    outcome = hand_off(runner, "look_at_glb")
    payload = read_json(project.root / "requests" / "fluidblend" / "handoff-look_at_glb.json")
    assert payload["parameters"]["template"] == "web"
    assert payload["parameters"]["export_path"].endswith(".glb")
    # The smoke test needs a folder that does not exist yet: it is described, never invented.
    assert any("game.smoke_test" in action for action in outcome.result.next_safe_actions)
    note("U13", "four templates, each validated by fluidblend's own validate_request")


def test_a_kind_outside_the_catalogue_is_refused(linked):
    runner, _project = linked
    outcome = runner.run(
        make_request(
            "handoff.request",
            "handoff-bad",
            target={"bundle_id": "fx-export-unreal"},
            parameters={"kind": "retarget_everything"},
        )
    )
    # The contract rejects it before the handler is even reached.
    assert outcome.exit_code == exit_codes.INVALID
    assert "invalid parameters" in outcome.result.errors[0].message


def test_a_wrapped_bundle_has_no_blender_project_behind_it(tmp_path, fixture_bundle):
    root = tmp_path / "wrapped"
    scaffold_project(root, project_id="demo-game", fluidblend_project=str(tmp_path / "studio"))
    project = load_project(root)
    runner = TaskRunner(project)
    import shutil

    shutil.copy2(next(fixture_bundle.glob("*.glb")), project.root / "incoming.glb")
    (project.root / "licenses" / "x.md").write_text("CC0-1.0\n", encoding="utf-8")
    assert (
        runner.run(
            make_request(
                "bundle.wrap",
                "wrap-001",
                parameters={
                    "model_path": "incoming.glb",
                    "license_path": "licenses/x.md",
                    "license": "CC0-1.0",
                    "bundle_id": "wrapped-01",
                },
            )
        ).exit_code
        == exit_codes.OK
    )
    outcome = runner.run(
        make_request(
            "handoff.request",
            "handoff-wrapped",
            target={"bundle_id": "wrapped-01"},
            parameters={"kind": "reexport_unreal"},
        )
    )
    assert outcome.exit_code == exit_codes.BLOCKED
    assert outcome.result.errors[0].code == ErrorCode.UNSUPPORTED_CAPABILITY
    assert "third-party GLB" in outcome.result.errors[0].message


def test_without_the_link_the_kit_cannot_phrase_a_command(tmp_path, fixture_bundle):
    root = tmp_path / "unlinked"
    scaffold_project(root, project_id="demo-game")
    project = load_project(root)
    runner = TaskRunner(project)
    assert (
        runner.run(
            make_request("bundle.accept", "acc-001", parameters={"source_path": str(fixture_bundle)})
        ).exit_code
        == exit_codes.OK
    )
    outcome = runner.run(
        make_request(
            "handoff.request",
            "handoff-nolink",
            target={"bundle_id": "fx-export-unreal"},
            parameters={"kind": "reexport_unreal"},
        )
    )
    assert outcome.exit_code == exit_codes.FAILED
    assert "sources.fluidblend_project" in outcome.result.errors[0].message


def _project_of(linked):
    return linked[1]


def _project_request(project, operation_id):
    return project.root / "requests" / "fluidblend" / f"{operation_id}.json"
