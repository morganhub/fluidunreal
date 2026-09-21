"""Running one operation inside a dedicated Unreal editor process.

The command line is built as an argument list, never a shell string. Two things lot 0 measured are
encoded here and must not be "simplified":

- `-ExecCmds=py <path>` has to reach the engine as **one quoted token**. `Start-Process` and
  `subprocess` both split on the space otherwise, and the editor then runs a bare `py`, does
  nothing, and idles until the timeout without a single error line.
- Every `PYTHON*` variable is removed from the child environment. The editor embeds its own 3.11;
  a `PYTHONPATH` from the 3.13 the kit runs on breaks it in ways that look like kit bugs.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import now_iso

ENVELOPE_VARIABLE = "FLUIDUNREAL_ENVELOPE"
TASK_VARIABLE = "FLUIDUNREAL_TASK_ID"
TASK_MARKER = "-fluidunreal-task="
KILL_GRACE_SECONDS = 30


@dataclass
class BatchOutcome:
    exit_code: int | None
    elapsed_s: float
    timed_out: bool
    result: dict[str, Any] | None
    log_path: Path
    command: list[str] = field(default_factory=list)


def entrypoint_path(kit_root: Path) -> Path:
    return kit_root / "unreal_runtime" / "entrypoint.py"


def build_command(
    editor: Path,
    uproject: Path,
    entrypoint: Path,
    log_path: Path,
    task_id: str,
    *,
    render: bool = False,
    commandlet: bool = False,
) -> list[str]:
    """The exact line lot 0 validated. `render` swaps -nullrhi for off-screen rendering."""
    command = [str(editor), str(uproject)]
    if commandlet:
        command += ["-run=pythonscript", f"-script={entrypoint}"]
    else:
        # One token. The engine parses the value after `-ExecCmds=`, spaces included.
        command += [f"-ExecCmds=py {entrypoint}"]
    command += [
        "-unattended",
        "-nopause",
        "-nosplash",
        "-NoSound",
        "-stdout",
        "-FullStdOutLogOutput",
        f"-abslog={log_path}",
        "-RenderOffScreen" if render else "-nullrhi",
        f"{TASK_MARKER}{task_id}",
    ]
    return command


def child_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}


def gui_editor_on(uproject: Path) -> str | None:
    """An editor already open on this project. Reported; never killed on someone's behalf."""
    query = (
        "Get-CimInstance Win32_Process -Filter \"Name='UnrealEditor.exe'\" | "
        "Select-Object -ExpandProperty CommandLine"
    )
    try:
        done = subprocess.run(  # noqa: S603 - argument list
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    needle = str(uproject).lower()
    for line in (done.stdout or "").splitlines():
        if needle in line.lower():
            return line.strip()
    return None


def worker_command_line(pid: int) -> str:
    query = (
        f"Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' | "
        "Select-Object -ExpandProperty CommandLine"
    )
    try:
        done = subprocess.run(  # noqa: S603 - argument list
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (done.stdout or "").strip()


def is_task_worker(pid: int, task_id: str) -> bool:
    """True only when that pid is alive, is an editor, and carries this task's marker.

    A pid alone is not an identity: Windows recycles them, and the process that owns a recorded pid
    an hour later may be someone's open editor.
    """
    line = worker_command_line(pid).lower()
    return "unrealeditor" in line and f"{TASK_MARKER}{task_id}".lower() in line


def kill_worker(pid: int, task_id: str) -> bool:
    """Kill only a process that is really this task's editor, and its children with it.

    The marker check is what makes this safe: without it, a recycled pid would take down whatever
    now owns it. `taskkill /T` takes the ShaderCompileWorker children too.
    """
    if not is_task_worker(pid, task_id):
        return False
    try:
        subprocess.run(  # noqa: S603 - argument list
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def surviving_children(pid: int) -> list[str]:
    """Editor children still around after a kill. Reported, never killed blind."""
    query = (
        f"Get-CimInstance Win32_Process -Filter 'ParentProcessId={int(pid)}' | "
        "Select-Object -ExpandProperty Name"
    )
    try:
        done = subprocess.run(  # noqa: S603 - argument list
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in (done.stdout or "").splitlines() if line.strip()]


def _kill_tree(process: subprocess.Popen) -> None:
    """Kill the editor and the children it spawned. Never leave one behind."""
    try:
        subprocess.run(  # noqa: S603 - argument list
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        process.kill()
    try:
        process.wait(timeout=KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def run_operation(
    *,
    editor: Path,
    uproject: Path,
    kit_root: Path,
    task_dir: Path,
    envelope: dict[str, Any],
    task_id: str,
    timeout_s: int,
    render: bool = False,
    on_worker_started=None,
) -> BatchOutcome:
    """Write the envelope, run one editor, read the result it left."""
    task_dir.mkdir(parents=True, exist_ok=True)
    envelope_path = task_dir / "request.json"
    result_path = task_dir / "result.json"
    log_path = task_dir / "unreal.log"
    if result_path.exists():
        result_path.unlink()
    atomic_write_json(envelope_path, envelope)

    command = build_command(editor, uproject, entrypoint_path(kit_root), log_path, task_id, render=render)
    environment = child_environment()
    environment[ENVELOPE_VARIABLE] = str(envelope_path)
    environment[TASK_VARIABLE] = task_id

    started = time.monotonic()
    timed_out = False
    with (task_dir / "unreal.stdout.txt").open("w", encoding="utf-8") as out:
        process = subprocess.Popen(  # noqa: S603 - argument list, never a shell string
            command, stdout=out, stderr=subprocess.STDOUT, env=environment
        )
        try:
            if on_worker_started is not None:
                on_worker_started(
                    {
                        "pid": process.pid,
                        "executable": str(editor),
                        "started_at": now_iso(),
                        "task_marker": f"{TASK_MARKER}{task_id}",
                    }
                )
            process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(process)
        except BaseException:
            # Anything that goes wrong on this side still owns the editor it started. Leaving it
            # running orphans a process that holds the project and its logs until someone notices.
            _kill_tree(process)
            raise

    elapsed = round(time.monotonic() - started, 2)
    result = None
    if result_path.exists():
        try:
            result = read_json(result_path)
        except (ValueError, OSError):
            result = None
    return BatchOutcome(
        exit_code=process.returncode,
        elapsed_s=elapsed,
        timed_out=timed_out,
        result=result,
        log_path=log_path,
        command=command,
    )


def log_tail(path: Path, characters: int = 1500) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-characters:]
    except OSError:
        return ""
