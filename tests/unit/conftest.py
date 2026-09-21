"""Unit tests never start, query or kill a real Unreal process, and can still drive the real runner.

Someone may have an editor open on this machine while they run. Every process the kit touches goes
through `unreal_batch`, so that is what is replaced here: anything that would launch or kill fails
the test loudly, and liveness reads as "nothing is running". A test that needs a live editor
supplies its own fake on top.

`_execute_unreal` is replaced too, because the real one rewrites the tracked
`unreal_runtime/RUNTIME_MANIFEST.json` before it launches anything. The `editor` fixture restores it
and replaces what lies beneath instead, so the runner, the envelope and the publication are the real
code around a fake editor.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fluidblend.contracts.common import Artifact, OperationResult, OperationStatus
from fluidblend.core import exit_codes
from fluidblend.core.atomic import atomic_write_json
from fluidblend.core.hashing import now_iso, sha256_file

from fluidunreal.adapters import unreal_batch, unreal_discovery
from fluidunreal.core import tasks as tasks_module
from fluidunreal.core.tasks import TaskRunner
from tests.conftest import make_request

REAL_EXECUTE_UNREAL = TaskRunner._execute_unreal
BUNDLE = "fx-export-unreal"
ASSET = "vitruvian"


def _no_real_editor(*_args, **_kwargs):
    raise AssertionError("a unit test reached a real Unreal process")


@pytest.fixture(autouse=True)
def no_real_editor(monkeypatch):
    monkeypatch.setattr(TaskRunner, "_execute_unreal", _no_real_editor)
    monkeypatch.setattr(unreal_batch, "run_operation", _no_real_editor)
    monkeypatch.setattr(unreal_batch, "kill_worker", _no_real_editor)
    monkeypatch.setattr(unreal_batch, "worker_command_line", lambda pid: "")
    monkeypatch.setattr(unreal_batch, "surviving_children", lambda pid: [])


def write_asset(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xc1\x83\x2a\x9e not a real package")
    return path


def task_dirs(project) -> list[str]:
    return sorted(p.name for p in (project.root / "state" / "tasks").iterdir())


class FakeEditor:
    """Stands in for `unreal_batch.run_operation`, the only thing that starts an editor.

    `succeed` writes what the runtime writes for an import. `crash` leaves what a killed import
    leaves and never answers. `hang` does the same, then waits until the test releases it.
    """

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
        # A staging folder, and a version renamed into place but never indexed by the engine.
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
