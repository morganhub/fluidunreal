"""Task status, cancel and reconcile: what happens after a run stopped without saying how.

The editor is a fake that writes what the runtime writes, or leaves what a killed import leaves, so
the runner, the envelope and reconcile are the real code. U12 kills a real editor mid-import on top
of this; these tests prove the host side without one.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fluidblend.contracts.common import Artifact, OperationResult, OperationStatus
from fluidblend.contracts.tasks import TaskRecord, WorkerInfo
from fluidblend.core import exit_codes
from fluidblend.core.atomic import atomic_write_json
from fluidblend.core.budgets import load_metrics
from fluidblend.core.hashing import new_id, now_iso, sha256_file
from fluidblend.core.locks import ProjectLocks
from fluidblend.core.paths import relpath_posix

from fluidunreal.adapters import unreal_batch, unreal_discovery
from fluidunreal.cli import main
from fluidunreal.contracts.operations import validate_request
from fluidunreal.core import tasks as tasks_module
from fluidunreal.core.budgets import metric_key
from fluidunreal.core.tasks import TaskRunner
from fluidunreal.core.ue_content import CONTENT_INDEX, task_leftovers, write_content_index
from tests.conftest import make_request

# Taken before the autouse guard in tests/unit/conftest.py replaces it.
REAL_EXECUTE_UNREAL = TaskRunner._execute_unreal
BUNDLE = "fx-export-unreal"
ASSET = "vitruvian"


def write_asset(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xc1\x83\x2a\x9e not a real package")
    return path


class FakeEditor:
    """Stands in for `unreal_batch.run_operation`, which is the only thing that starts an editor."""

    def __init__(self):
        self.mode = "crash"
        self.pid = 424242
        self.task_id: str | None = None
        self.envelopes: list[dict] = []
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, *, editor, uproject, kit_root, task_dir, envelope, task_id, timeout_s, **kwargs):
        # The real adapter writes the envelope before it launches anything.
        atomic_write_json(task_dir / "request.json", envelope)
        self.envelopes.append(envelope)
        self.task_id = task_id
        kwargs["on_worker_started"](
            {
                "pid": self.pid,
                "executable": str(editor),
                "started_at": now_iso(),
                "task_marker": f"{unreal_batch.TASK_MARKER}{task_id}",
            }
        )
        context = envelope["context"]
        content = Path(context["content_root"])
        version = content / ASSET / f"v{context['next_version']:03d}"
        log = task_dir / "unreal.log"
        if self.mode == "succeed":
            return self._succeed(envelope, task_dir, version, log)
        # What a killed import leaves: a staging folder, and a version renamed into place but never
        # indexed by the engine.
        write_asset(content / "_staging" / task_id / "SK_vitruvian.uasset")
        write_asset(version / "SK_vitruvian.uasset")
        self.started.set()
        if self.mode == "hang":
            assert self.release.wait(10), "the test never released the fake editor"
            return unreal_batch.BatchOutcome(1, 3.0, False, None, log)
        return unreal_batch.BatchOutcome(None, float(timeout_s), True, None, log)

    def _succeed(self, envelope, task_dir, version, log):
        write_asset(version / "SK_vitruvian.uasset")
        report = Path(envelope["context"]["out_dir"]) / "import-report.json"
        atomic_write_json(report, {"asset_id": ASSET, "version": envelope["context"]["next_version"]})
        result = OperationResult(
            operation_id=envelope["request"]["operation_id"],
            operation=envelope["request"]["operation"],
            task_id=envelope["task_id"],
            status=OperationStatus.succeeded,
            artifacts=[
                Artifact(
                    kind="report",
                    path="import-report.json",
                    sha256=sha256_file(report),
                    bytes=report.stat().st_size,
                )
            ],
            metrics={"asset_id": ASSET, "version": envelope["context"]["next_version"]},
        ).model_dump(mode="json")
        atomic_write_json(task_dir / "result.json", result)
        return unreal_batch.BatchOutcome(0, 12.5, False, result, log)


class LiveWorker:
    """A pid whose command line carries a task's marker until something kills it."""

    def __init__(self, monkeypatch, pid: int, task_id):
        self.pid = pid
        self.task_id = task_id
        self.alive = True
        self.killed: list[tuple[int, str]] = []
        monkeypatch.setattr(unreal_batch, "worker_command_line", self.command_line)
        monkeypatch.setattr(unreal_batch, "kill_worker", self.kill)

    def command_line(self, pid: int) -> str:
        if not self.alive or pid != self.pid:
            return ""
        return (
            r'"X:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" "C:\p\Bed.uproject" '
            f"-nullrhi {unreal_batch.TASK_MARKER}{self.task_id()}"
        )

    def kill(self, pid: int, task_id: str) -> bool:
        self.killed.append((pid, task_id))
        self.alive = False
        return True


@pytest.fixture
def editor(monkeypatch):
    fake = FakeEditor()
    engine = unreal_discovery.EngineInfo(
        path=r"X:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe", version="5.8.2", series="5.8"
    )
    monkeypatch.setattr(TaskRunner, "_execute_unreal", REAL_EXECUTE_UNREAL)
    monkeypatch.setattr(unreal_discovery, "select", lambda configured=None: (engine, []))
    monkeypatch.setattr(unreal_batch, "gui_editor_on", lambda uproject: None)
    monkeypatch.setattr(unreal_batch, "run_operation", fake)
    monkeypatch.setattr(tasks_module, "write_runtime_manifest", lambda runtime_dir: {"hash": "fake"})
    return fake


@pytest.fixture
def accepted(project, fixture_bundle):
    outcome = TaskRunner(project).run(
        make_request("bundle.accept", "acc-001", parameters={"source_path": str(fixture_bundle)})
    )
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    return project


def fabricate(project, status, *, pid=None, operation_id="imp-crash", parameters=None) -> TaskRecord:
    """A task left the way a host that died leaves one: recorded, enveloped, never concluded."""
    runner = TaskRunner(project)
    request, params, spec = validate_request(
        make_request("asset.import", operation_id, target={"bundle_id": BUNDLE}, parameters=parameters)
    )
    task = TaskRecord(
        task_id=new_id("task"),
        operation_id=operation_id,
        operation=spec.name,
        project_id=request.project_id,
        status=status,
        fingerprint=runner._fingerprint(request),
        target=request.target.model_dump(exclude_none=True),
        created_at=now_iso(),
        updated_at=now_iso(),
    )
    if pid:
        task.worker = WorkerInfo(
            pid=pid,
            executable=r"X:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
            started_at=now_iso(),
            task_marker=f"{unreal_batch.TASK_MARKER}{task.task_id}",
        )
    out = project.root / "state" / "tasks" / task.task_id / "out"
    out.mkdir(parents=True)
    envelope = runner._envelope(request, params, spec, task, out, {"hash": "fake"})
    atomic_write_json(out.parent / "request.json", envelope)
    runner.state.upsert_task(task)
    return task


def shown(project, path: Path) -> str:
    return relpath_posix(project.root, path)


def task_dirs(project) -> list[str]:
    return sorted(p.name for p in (project.root / "state" / "tasks").iterdir())


def test_reconcile_removes_exactly_what_the_interrupted_import_wrote(accepted, editor, capsys):
    project = accepted
    content = project.content_root
    published = content / ASSET / "v001"
    write_asset(published / "SK_vitruvian.uasset")
    write_content_index(published, asset_id=ASSET, version=1, bundle_id=BUNDLE)
    older = content / ASSET / "v002"  # an earlier task's leftover, never indexed
    write_asset(older / "SK_vitruvian.uasset")
    stranger = write_asset(content / "_staging" / "task-someone-else" / "X.uasset")

    request = make_request("asset.import", "imp-001", target={"bundle_id": BUNDLE})
    crashed = TaskRunner(project).run(request)
    assert crashed.exit_code == exit_codes.UNKNOWN_STATE, crashed.result.model_dump()
    task_id = crashed.result.task_id
    assert editor.envelopes[0]["context"]["next_version"] == 3
    staging, version = content / "_staging" / task_id, content / ASSET / "v003"
    assert staging.is_dir() and version.is_dir()
    assert "task reconcile --project" in crashed.result.errors[0].recovery
    # A killed run measures its timeout, not the import: it must not feed the next estimate.
    assert metric_key("asset.import") not in load_metrics(project.root)

    before = task_dirs(project)
    refused = TaskRunner(project).run(request)
    assert refused.exit_code == exit_codes.UNKNOWN_STATE
    assert task_dirs(project) == before, "a refused retry creates nothing"

    assert main(["task", "reconcile", "--project", str(project.root), "--id", task_id]) == exit_codes.OK
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed" and report["action"] == "marked_failed"
    assert sorted(report["removed"]) == sorted([shown(project, staging), shown(project, version)])
    kept = {item["path"] for item in report["kept"]}
    assert kept == {shown(project, older), shown(project, stranger.parent)}
    assert not staging.exists() and not version.exists()
    assert (published / CONTENT_INDEX).is_file() and older.is_dir() and stranger.is_file()

    task = TaskRunner(project).state.task(task_id)
    assert task.status == OperationStatus.failed
    assert "removed" in task.errors[-1].message and "the operation_id is free" in task.errors[-1].recovery
    assert any(e["event"] == "reconciled" and e["task_id"] == task_id for e in project.journal().events())
    assert (project.root / "state" / "tasks" / task_id / "reconcile.json").is_file()

    # The same operation_id now runs, and publishes the version the crash never finished.
    editor.mode = "succeed"
    retry = TaskRunner(project).run(request)
    assert retry.exit_code == exit_codes.OK, retry.result.model_dump()
    assert retry.result.metrics["version"] == 3 and (version / CONTENT_INDEX).is_file()
    assert retry.result.new_revision == 1
    assert load_metrics(project.root)[metric_key("asset.import")]["history"] == [12.5]


def test_reconcile_kills_the_editor_it_recorded_and_spares_a_decoy(accepted, monkeypatch):
    project = accepted
    content = project.content_root
    decoy = write_asset(content / ASSET / "v001" / "SK_vitruvian.uasset").parent
    task = fabricate(project, OperationStatus.running, pid=515151)
    # The envelope was computed with v001 already there: this task was told to make v002.
    staging = write_asset(content / "_staging" / task.task_id / "SK_vitruvian.uasset").parent
    mine = write_asset(content / ASSET / "v002" / "SK_vitruvian.uasset").parent
    worker = LiveWorker(monkeypatch, 515151, lambda: task.task_id)

    report = TaskRunner(project).reconcile(task.task_id)
    assert worker.killed == [(515151, task.task_id)]
    assert report["worker"]["killed"] is True and "was killed" in report["summary"]
    assert report["status"] == "failed"
    assert sorted(report["removed"]) == sorted([shown(project, staging), shown(project, mine)])
    assert decoy.is_dir(), "an unindexed folder with another number is not this task's"
    assert {item["path"] for item in report["kept"]} == {shown(project, decoy)}


def test_a_recycled_pid_is_never_killed(accepted, monkeypatch):
    project = accepted
    task = fabricate(project, OperationStatus.unknown, pid=616161)
    # The pid now belongs to someone's own editor, open on their own project, without the marker.
    monkeypatch.setattr(
        unreal_batch,
        "worker_command_line",
        lambda pid: r'"C:\Epic\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" "D:\Their Game\Their.uproject"',
    )
    report = TaskRunner(project).reconcile(task.task_id)  # the autouse guard fails on any kill
    assert report["worker"] == {"recorded": True, "pid": 616161, "alive": False, "killed": False}
    assert report["status"] == "failed" and "already stopped" in report["summary"]


def test_cancel_stops_a_running_import_and_leaves_it_for_reconcile(accepted, editor, monkeypatch, capsys):
    project = accepted
    editor.mode = "hang"
    worker = LiveWorker(monkeypatch, editor.pid, lambda: editor.task_id)
    request = make_request("asset.import", "imp-cancel", target={"bundle_id": BUNDLE})
    outcomes = []
    thread = threading.Thread(target=lambda: outcomes.append(TaskRunner(project).run(request)))
    thread.start()
    try:
        assert editor.started.wait(10), "the fake editor never started"
        task_id = editor.task_id
        code = main(["task", "cancel", "--project", str(project.root), "--id", task_id])
    finally:
        editor.release.set()
        thread.join(10)
    assert code == exit_codes.UNKNOWN_STATE, "a cancelled task still needs reconcile"
    data = json.loads(capsys.readouterr().out)
    assert data["cancelled"] is True and data["worker"]["killed"] is True
    assert data["next_action"].startswith("fluidunreal task reconcile --project")
    assert worker.killed == [(editor.pid, task_id)]
    assert outcomes[0].exit_code == exit_codes.UNKNOWN_STATE

    assert TaskRunner(project).run(request).exit_code == exit_codes.UNKNOWN_STATE
    assert main(["task", "reconcile", "--project", str(project.root), "--id", task_id]) == exit_codes.OK
    report = json.loads(capsys.readouterr().out)
    assert shown(project, project.content_root / "_staging" / task_id) in report["removed"]
    assert not (project.content_root / "_staging").exists(), "an emptied staging area goes with it"


def test_cancel_and_reconcile_leave_a_finished_task_alone(accepted, capsys):
    project = accepted
    task = fabricate(project, OperationStatus.failed)
    root = str(project.root)
    assert main(["task", "cancel", "--project", root, "--id", task.task_id]) == exit_codes.OK
    assert json.loads(capsys.readouterr().out)["cancelled"] is False
    assert main(["task", "reconcile", "--project", root, "--id", task.task_id]) == exit_codes.OK
    assert json.loads(capsys.readouterr().out)["action"] == "none"


def test_status_says_whether_the_editor_still_runs_and_what_to_do(accepted, monkeypatch, capsys):
    project = accepted
    task = fabricate(project, OperationStatus.unknown, pid=717171)
    (project.root / "state" / "tasks" / task.task_id / "unreal.log").write_text(
        "LogPython: fluidunreal: asset.import started\n", encoding="utf-8"
    )
    LiveWorker(monkeypatch, 717171, lambda: task.task_id)
    assert main(["task", "status", "--project", str(project.root), "--id", task.task_id]) == exit_codes.OK
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "unknown" and data["worker_alive"] is True
    assert data["next_action"] == (
        f'fluidunreal task reconcile --project "{project.root}" --id {task.task_id}'
    )
    assert "asset.import started" in data["log_tail"]


def test_an_unknown_task_is_an_invalid_argument_and_a_missing_project_is_blocked(project, tmp_path, capsys):
    assert main(["task", "status", "--project", str(project.root), "--id", "task-nope"]) == exit_codes.INVALID
    assert "unknown task" in capsys.readouterr().err
    assert (
        main(["task", "reconcile", "--project", str(tmp_path / "nowhere"), "--id", "x"]) == exit_codes.BLOCKED
    )


def test_a_leftover_that_cannot_be_removed_keeps_the_task_unsettled(accepted, capsys):
    project = accepted
    task = fabricate(project, OperationStatus.unknown)
    held = write_asset(project.content_root / "_staging" / task.task_id / "SK_vitruvian.uasset")
    root = str(project.root)
    # Windows refuses to delete a file something holds open: what a lingering shader worker does.
    with held.open("rb"):
        assert (
            main(["task", "reconcile", "--project", root, "--id", task.task_id]) == exit_codes.UNKNOWN_STATE
        )
    data = json.loads(capsys.readouterr().out)
    assert data["action"] == "retry_reconcile" and data["failed"]
    assert TaskRunner(project).state.task(task.task_id).status == OperationStatus.unknown

    assert main(["task", "reconcile", "--project", root, "--id", task.task_id]) == exit_codes.OK
    assert not held.exists()


def test_reconcile_waits_while_another_process_holds_the_project(accepted, capsys):
    project = accepted
    task = fabricate(project, OperationStatus.running)
    with ProjectLocks(project.root).hold("project", purpose="a run in another process"):
        code = main(["task", "reconcile", "--project", str(project.root), "--id", task.task_id])
    assert code == exit_codes.UNKNOWN_STATE
    data = json.loads(capsys.readouterr().out)
    assert data["action"] == "wait" and "task cancel" in data["next_action"]
    assert TaskRunner(project).state.task(task.task_id).status == OperationStatus.running


def test_only_what_is_provably_the_tasks_is_removable(tmp_path):
    content = tmp_path / "Content" / "Fluid"
    write_asset(content / "_staging" / "task-a" / "X.uasset")
    write_asset(content / "_staging" / "task-a.uasset")
    write_asset(content / "_staging" / "task-b" / "Y.uasset")
    indexed = write_asset(content / "hero" / "v003" / "A.uasset").parent
    (indexed / CONTENT_INDEX).write_text("{}", encoding="utf-8")

    found = task_leftovers(content, task_id="task-a", asset_id="hero", next_version=3)
    assert set(found.removable) == {content / "_staging" / "task-a", content / "_staging" / "task-a.uasset"}
    reasons = {path.name: reason for path, reason in found.kept}
    assert "published version" in reasons["v003"] and "another task" in reasons["task-b"]

    foreign = write_asset(content / "hero" / "v004" / "A.uasset").parent
    (foreign / "notes.txt").write_text("someone's notes", encoding="utf-8")
    found = task_leftovers(content, task_id="task-z", asset_id="hero", next_version=4)
    assert found.removable == []
    assert dict(found.kept)[foreign] == "holds files that are not Unreal assets"


def test_the_envelope_counts_versions_for_the_asset_the_runtime_will_import(accepted):
    """The runtime takes parameters.asset_id first. The number has to be computed for that asset."""
    project = accepted
    manifest = project.bundle_dir(BUNDLE) / "handoff-bundle.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["instances"].append({**data["instances"][0], "instance_id": "crate-01", "asset_id": "crate"})
    manifest.write_text(json.dumps(data), encoding="utf-8")
    existing = write_asset(project.content_root / "crate" / "v001" / "SM_crate.uasset").parent
    write_content_index(existing, asset_id="crate", version=1, bundle_id=BUNDLE)

    task = fabricate(project, OperationStatus.unknown, parameters={"asset_id": "crate"})
    envelope = json.loads(
        (project.root / "state" / "tasks" / task.task_id / "request.json").read_text(encoding="utf-8")
    )
    assert envelope["context"]["next_version"] == 2


def test_resume_rebuilds_from_the_journal_and_names_every_task_to_reconcile(accepted, monkeypatch, capsys):
    project = accepted
    stuck = fabricate(project, OperationStatus.unknown, pid=818181, operation_id="imp-stuck")
    fabricate(project, OperationStatus.failed, operation_id="imp-failed")
    fabricate(project, OperationStatus.planned, operation_id="imp-dry")
    LiveWorker(monkeypatch, 818181, lambda: stuck.task_id)
    # The snapshot is a projection; the journal is what resume trusts.
    (project.root / "state" / "state.json").unlink()
    root = str(project.root)

    assert main(["resume", "--project", root, "--json"]) == exit_codes.UNKNOWN_STATE
    report = json.loads(capsys.readouterr().out)
    assert [t["task_id"] for t in report["unfinished_tasks"]] == [stuck.task_id]
    command = f'fluidunreal task reconcile --project "{project.root}" --id {stuck.task_id}'
    assert report["next_actions"] == [command]
    assert report["unfinished_tasks"][0]["worker_alive"] is True
    assert report["inspect"]["bundles"] == [BUNDLE]
    assert (project.root / "state" / "state.json").is_file()
    assert (project.root / "state" / "resume-report.json").is_file()

    assert main(["resume", "--project", root]) == exit_codes.UNKNOWN_STATE
    human = capsys.readouterr().out
    assert "1 task(s) to reconcile" in human and "its editor is still running" in human
    assert command in human

    assert main(["task", "reconcile", "--project", root, "--id", stuck.task_id]) == exit_codes.OK
    capsys.readouterr()
    assert main(["resume", "--project", root]) == exit_codes.OK
    assert "0 task(s) to reconcile" in capsys.readouterr().out
