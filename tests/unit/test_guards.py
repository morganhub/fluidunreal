"""U09 and U10: what the runner does with a request it has seen before, or should never run.

U09 replays through a fake editor, so the operation that creates a version and a revision is the
one being replayed; the runner, the ledger and the publication are the real code. U10 needs no
editor at all: every refusal happens before a task folder exists.
"""

from __future__ import annotations

import shutil

import pytest
from fluidblend.core import exit_codes

from fluidunreal.core.tasks import TaskRunner
from tests.conftest import make_request, note
from tests.unit.conftest import ASSET, BUNDLE, task_dirs


def task_updates(project) -> int:
    return sum(1 for e in project.journal().events() if e["event"] == "task_updated")


@pytest.mark.acceptance("U09", title="Replay an operation_id, and refuse it with other parameters")
def test_U09_the_same_request_replays_and_other_parameters_conflict(
    accepted, editor, fixture_bundle, tmp_path
):
    project = accepted
    editor.mode = "succeed"
    request = make_request("asset.import", "imp-u09", target={"bundle_id": BUNDLE})
    first = TaskRunner(project).run(request)
    assert first.exit_code == exit_codes.OK, first.result.model_dump()
    assert first.result.new_revision == 1

    tasks = task_dirs(project)
    revisions = (project.root / "state" / "revisions.json").read_bytes()
    versions = sorted(p.name for p in project.asset_dir(ASSET).iterdir())
    updates = task_updates(project)

    again = TaskRunner(project).run(request)
    assert again.exit_code == exit_codes.OK and again.replayed
    assert again.result.model_dump() == first.result.model_dump(), "the same result, not a new one"
    assert len(editor.envelopes) == 1, "a replay starts no editor"
    assert task_dirs(project) == tasks, "no new task folder"
    assert (project.root / "state" / "revisions.json").read_bytes() == revisions, "no new revision"
    assert sorted(p.name for p in project.asset_dir(ASSET).iterdir()) == versions == ["v001"]
    assert task_updates(project) == updates
    last = project.journal().events()[-1]
    assert last["event"] == "replayed"
    assert last["operation_id"] == "imp-u09" and last["task_id"] == first.result.task_id

    other = make_request(
        "asset.import", "imp-u09", target={"bundle_id": BUNDLE}, parameters={"replace_existing": True}
    )
    conflict = TaskRunner(project).run(other)
    assert conflict.exit_code == exit_codes.CONFLICT
    assert "different parameters" in conflict.result.errors[0].message
    assert len(editor.envelopes) == 1 and task_dirs(project) == tasks

    # A host operation behaves the same: the bundle accepted by the fixture, accepted again.
    accepting = make_request("bundle.accept", "acc-001", parameters={"source_path": str(fixture_bundle)})
    assert TaskRunner(project).run(accepting).replayed
    elsewhere = tmp_path / "elsewhere"
    shutil.copytree(fixture_bundle, elsewhere)
    moved = make_request("bundle.accept", "acc-001", parameters={"source_path": str(elsewhere)})
    assert TaskRunner(project).run(moved).exit_code == exit_codes.CONFLICT
    assert task_dirs(project) == tasks
    note(
        "U09",
        "asset.import replayed: same result, no editor, no task folder, no revision, no version; "
        "journal `replayed`. replace_existing under the same id -> exit 3; bundle.accept likewise",
    )


def wrap(operation_id: str, **overrides) -> dict:
    parameters = {
        "model_path": "incoming.glb",
        "license_path": "licenses/third-party.md",
        "license": "CC0-1.0",
        "bundle_id": "wrapped-01",
    }
    return make_request("bundle.wrap", operation_id, parameters={**parameters, **overrides})


@pytest.mark.acceptance("U10", title="Supply an escaping path or a command as a parameter")
def test_U10_escaping_paths_and_commands_are_refused_before_anything_runs(project, tmp_path):
    victim = tmp_path / "outside.glb"
    victim.write_bytes(b"glTF outside the root")
    importing = {"bundle_id": BUNDLE}
    cases = {
        "a parent segment": wrap("u10-parent", model_path="..\\x.glb"),
        "an absolute path outside the root": wrap("u10-absolute", model_path=str(victim)),
        "a UNC share": wrap("u10-unc", model_path="\\\\server\\share\\x.glb"),
        "a licence outside the root": wrap("u10-licence", license_path="..\\..\\secret.md"),
        "a command in a path": wrap("u10-path-command", model_path="incoming.glb;calc.exe"),
        "an expansion in a path": wrap("u10-path-expansion", license_path="licenses/$env:USERNAME.md"),
        "a command in an identifier": wrap("u10-identifier", bundle_id="wrapped;calc"),
        "a command in a target": make_request(
            "bundle.inspect", "u10-target", target={"bundle_id": "b-01;calc"}
        ),
        "a command in an asset id": make_request(
            "asset.import", "u10-asset", target=importing, parameters={"asset_id": "hero;calc"}
        ),
        "a command in a content path": make_request(
            "asset.import",
            "u10-content",
            target=importing,
            parameters={"destination_root": "/Game/Fluid;calc"},
        ),
        "a UNC bundle source": make_request(
            "bundle.accept", "u10-source-unc", parameters={"source_path": "\\\\server\\share\\bundle"}
        ),
        "a parent segment in a bundle source": make_request(
            "bundle.accept", "u10-source-parent", parameters={"source_path": "..\\..\\bundle"}
        ),
        "a command in a bundle source": make_request(
            "bundle.accept", "u10-source-command", parameters={"source_path": f"{tmp_path};calc"}
        ),
    }
    codes = {}
    for label, payload in cases.items():
        outcome = TaskRunner(project).run(payload)
        codes[label] = outcome.exit_code
        assert outcome.exit_code in (exit_codes.BLOCKED, exit_codes.INVALID), (
            label,
            outcome.result.model_dump(),
        )
        assert outcome.result.task_id == "none", label

    assert task_dirs(project) == [], "no refusal created a task folder"
    assert task_updates(project) == 0, "no refusal journalled a task"
    assert not any((project.root / "bundles").iterdir())
    assert victim.read_bytes() == b"glTF outside the root"
    paths = sum(1 for code in codes.values() if code == exit_codes.BLOCKED)
    identifiers = sum(1 for code in codes.values() if code == exit_codes.INVALID)
    note(
        "U10",
        f"{len(cases)} requests refused before execution: {paths} paths -> PERMISSION_REQUIRED (exit 2), "
        f"{identifiers} identifiers -> VALIDATION_FAILED (exit 4); no task folder, no task event",
    )
