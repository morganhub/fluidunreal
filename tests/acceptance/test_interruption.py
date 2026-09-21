"""U12: the editor killed in the middle of an import, and what the kit does about it.

Marked `unreal`: without the locked engine these are skipped as `not_run`, never counted as passed.
The kill is real: the worker is taken down with the kit's own `kill_worker`, marker check included,
while the importer holds a staging folder on disk and has published nothing.
"""

from __future__ import annotations

import threading
import time

import pytest
from fluidblend.contracts.common import OperationStatus
from fluidblend.core import exit_codes
from fluidblend.core.revisions import RevisionStore

from fluidunreal.adapters import unreal_batch
from fluidunreal.cli import main
from fluidunreal.core.tasks import TaskRunner
from tests.conftest import make_request, note

pytestmark = pytest.mark.unreal

IMPORT = make_request("asset.import", "imp-001", target={"bundle_id": "fx-export-unreal"})


def running_import(project, runner):
    """The import's task once its editor is up and its staging folder holds assets."""
    staging = project.content_root / "_staging"
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        tasks = [t for t in runner.state.tasks() if t.operation == "asset.import"]
        if tasks and tasks[-1].worker and staging.is_dir() and list(staging.rglob("*.uasset")):
            return tasks[-1]
        time.sleep(1)
    raise AssertionError("the import never reached its staging folder")


@pytest.mark.acceptance(
    "U12", title="Kill the editor mid-import: unknown, refused, reconciled, nothing published"
)
def test_U12_an_interrupted_import_is_concluded_not_guessed(project, fixture_bundle):
    runner = TaskRunner(project)
    accepted = runner.run(
        make_request("bundle.accept", "acc-001", parameters={"source_path": str(fixture_bundle)})
    )
    assert accepted.exit_code == exit_codes.OK, accepted.result.model_dump()

    paused = TaskRunner(project, test_hooks={"pause_before_publish_s": 600})
    finished = {}
    worker = threading.Thread(target=lambda: finished.update(outcome=paused.run(IMPORT)))
    worker.start()
    task = running_import(project, paused)
    assert unreal_batch.kill_worker(task.worker.pid, task.task_id), "the kit's own kill refused its worker"
    worker.join(600)
    outcome = finished["outcome"]

    # The editor wrote no result: unknown, not failed, and certainly not succeeded.
    assert outcome.exit_code == exit_codes.UNKNOWN_STATE, outcome.result.model_dump()
    assert outcome.result.status == OperationStatus.unknown
    assert "task reconcile" in (outcome.result.errors[0].recovery or "")
    staging = project.content_root / "_staging" / task.task_id
    assert list(staging.rglob("*.uasset")), "the kill happened mid-import: the staging is still there"
    assert not (project.asset_dir("vitruvian") / "v001").exists()

    # Retrying before anyone concluded what happened is refused.
    retry = runner.run(IMPORT)
    assert retry.exit_code == exit_codes.UNKNOWN_STATE and "reconcile" in retry.result.errors[0].recovery

    assert main(["task", "reconcile", "--project", str(project.root), "--id", task.task_id]) == exit_codes.OK
    concluded = runner.state.task(task.task_id)
    assert concluded.status == OperationStatus.failed
    assert not staging.exists(), "reconcile removed what this task left"
    assert RevisionStore(project.root).get("asset:vitruvian") is None, "nothing was published"

    # Concluded, the same request runs again and publishes the first version.
    again = TaskRunner(project).run(IMPORT)
    assert again.exit_code == exit_codes.OK, again.result.model_dump()
    assert (project.asset_dir("vitruvian") / "v001").is_dir()
    note(
        "U12",
        "editor killed with a staging folder on disk: exit 5, retry refused, reconcile removed the "
        "staging and published nothing, the retry then imported v001",
    )
