"""The contracts: what a request must carry, and what the catalogue refuses to pretend."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fluidblend.contracts.handoff import HandoffBundle
from fluidblend.contracts.operations import OperationRequest as FluidblendRequest
from pydantic import ValidationError

from fluidunreal.contracts.operations import (
    OPERATIONS,
    OperationRequest,
    RequestValidationError,
    Target,
    validate_request,
)
from fluidunreal.contracts.reports import AuditReport, Measurement
from fluidunreal.contracts.schema_export import (
    VENDORED,
    build_schemas,
    check_up_to_date,
    dumps_canonical,
)

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def request(operation, operation_id="op-001", target=None, parameters=None):
    return {
        "schema_version": "1.0",
        "operation": operation,
        "operation_id": operation_id,
        "project_id": "my-game",
        "target": target or {},
        "parameters": parameters or {},
        "dry_run": False,
    }


def test_the_target_extends_fluidblends_rather_than_copying_it():
    """Subclassing keeps one definition of the envelope; a copy would drift on the first change."""
    assert issubclass(Target, FluidblendRequest.model_fields["target"].annotation)
    assert issubclass(OperationRequest, FluidblendRequest)
    target = Target(bundle_id="shot010-hero-001", shot_id="shot010", asset_id="vitruvian")
    assert target.bundle_id == "shot010-hero-001" and target.shot_id == "shot010"
    # The parent's strictness is inherited: an unknown key is still refused.
    with pytest.raises(ValidationError):
        Target(surprise=1)


def test_a_bundle_id_is_not_accepted_by_the_sibling_kit():
    """The extension is local on purpose: fluidblend must never be handed a target it cannot read."""
    with pytest.raises(ValidationError):
        FluidblendRequest.model_validate(request("game.export", target={"bundle_id": "b-001"}))


def test_an_operation_that_addresses_a_bundle_requires_one():
    with pytest.raises(RequestValidationError, match="requires target.bundle_id"):
        validate_request(request("bundle.inspect"))
    parsed, _params, spec = validate_request(request("bundle.inspect", target={"bundle_id": "b-001"}))
    assert parsed.target.bundle_id == "b-001" and spec.backend == "host"


def test_an_operation_that_addresses_an_asset_requires_one():
    with pytest.raises(RequestValidationError, match="requires target.asset_id"):
        validate_request(request("asset.audit", target={"bundle_id": "b-001"}))


def test_unknown_operations_and_bad_parameters_are_refused():
    with pytest.raises(RequestValidationError, match="unknown operation"):
        validate_request(request("asset.teleport"))
    with pytest.raises(RequestValidationError, match="invalid parameters"):
        validate_request(request("bundle.accept", parameters={"source_path": ""}))
    with pytest.raises(RequestValidationError, match="invalid request"):
        validate_request({**request("bundle.accept"), "schema_version": "2.0"})


def test_the_catalogue_says_what_is_not_implemented_instead_of_hiding_it():
    """What is left is the P2 lot, by name: packaging and retargeting."""
    unavailable = {name for name, spec in OPERATIONS.items() if not spec.available}
    assert unavailable == {"game.package", "retarget.mannequin"}
    assert OPERATIONS["asset.import"].available, "proven against the real engine by U05"
    assert OPERATIONS["asset.audit"].available, "proven against the real engine by U06"
    assert OPERATIONS["handoff.request"].available, "validated by fluidblend itself in U13"
    assert OPERATIONS["game.smoke_test"].available, "played in the real engine by U07, and failed on cue"
    assert OPERATIONS["game.screenshot"].available, "rendered and looked at by U08, with its control"
    # Nothing claims a live mode: an open editor is a conflict, not a session to write into.
    assert all("live" not in spec.execution_contract()["modes"] for spec in OPERATIONS.values())


def test_engine_operations_declare_the_engine_they_need():
    contract = OPERATIONS["asset.import"].execution_contract()
    assert "unreal.editor" in contract["required_dependencies"]
    assert contract["required_targets"] == ["bundle_id"]
    assert contract["publication"] == "asset_revision_and_reports"
    assert OPERATIONS["bundle.accept"].execution_contract()["input_paths"] == ["source_path"]


def test_a_measurement_that_could_not_be_taken_is_neither_a_pass_nor_a_failure():
    report = AuditReport(
        bundle_id="b-001",
        asset_id="vitruvian",
        engine="5.8.2",
        measurements=[
            Measurement(
                kind="scale_check", name="DEF-spine", expected=90.0, observed=90.0, tolerance=1.0, passed=True
            ),
            Measurement(kind="root_motion_travel", name="root", passed=None),
        ],
    )
    assert report.technical_pass is True
    assert report.not_run == ["root"]
    # A report with nothing measurable does not pass by default.
    empty = AuditReport(
        bundle_id="b-001",
        asset_id="vitruvian",
        engine="5.8.2",
        measurements=[Measurement(kind="bone_count", name="bones", passed=None)],
    )
    assert empty.technical_pass is False


def test_repo_schemas_are_up_to_date():
    stale = check_up_to_date(SCHEMAS)
    assert stale == [], f"run `fluidunreal schema export --out schemas`: {stale}"


def test_the_vendored_bundle_schema_matches_the_installed_dependency():
    """The contract belongs to fluidblend. A drifted copy would accept bundles it cannot read."""
    on_disk = (SCHEMAS / "handoff-bundle.json").read_text(encoding="utf-8")
    assert json.loads(on_disk)["$id"].endswith("handoff-bundle.json")
    assert on_disk == dumps_canonical(build_schemas()["handoff-bundle"])
    assert VENDORED["handoff-bundle"] is HandoffBundle
