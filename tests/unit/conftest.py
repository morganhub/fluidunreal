"""Unit tests never start, query or kill a real Unreal process.

Someone may have an editor open on this machine while they run. Every process the kit touches goes
through `unreal_batch`, so that is what is replaced here: anything that would launch or kill fails
the test loudly, and liveness reads as "nothing is running". A test that needs a live editor
supplies its own fake on top.

`_execute_unreal` is replaced too, because the real one rewrites the tracked
`unreal_runtime/RUNTIME_MANIFEST.json` before it launches anything. Tests that drive a fake editor
through the real runner restore it and replace what lies beneath.
"""

from __future__ import annotations

import pytest

from fluidunreal.adapters import unreal_batch
from fluidunreal.core.tasks import TaskRunner


def _no_real_editor(*_args, **_kwargs):
    raise AssertionError("a unit test reached a real Unreal process")


@pytest.fixture(autouse=True)
def no_real_editor(monkeypatch):
    monkeypatch.setattr(TaskRunner, "_execute_unreal", _no_real_editor)
    monkeypatch.setattr(unreal_batch, "run_operation", _no_real_editor)
    monkeypatch.setattr(unreal_batch, "kill_worker", _no_real_editor)
    monkeypatch.setattr(unreal_batch, "worker_command_line", lambda pid: "")
    monkeypatch.setattr(unreal_batch, "surviving_children", lambda pid: [])
