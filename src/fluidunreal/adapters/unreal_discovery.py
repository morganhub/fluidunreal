"""Find the Unreal editor, and say which one was found and how.

Everything here was measured in lot 0 on 5.8.2, not remembered. The version comes from
`Engine/Build/Build.version`, which is a JSON file: unlike Blender, no process has to be launched to
learn what series an install is.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from fluidblend.core.hashing import sha256_file

from fluidunreal.contracts.project import LOCKED_UNREAL_SERIES

EDITOR = "UnrealEditor-Cmd.exe"
RELATIVE_BINARY = Path("Engine") / "Binaries" / "Win64" / EDITOR
REGISTRY_KEYS = (
    r"SOFTWARE\EpicGames\Unreal Engine",
    r"SOFTWARE\WOW6432Node\EpicGames\Unreal Engine",
)
PROBE_MARKER = "FLUIDUNREAL_PROBE="
# Lot 0, P1: requesting a plugin that does not exist aborts the editor at startup before any script
# runs. `GLTFImporter` is gone in 5.8, so a project asking for it never starts.
KNOWN_MISSING_PLUGINS = ("GLTFImporter",)


@dataclass
class EngineInfo:
    path: str
    version: str | None = None
    series: str | None = None
    branch: str | None = None
    source: str = "unknown"
    sha256: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def is_locked_series(self) -> bool:
        return self.series == LOCKED_UNREAL_SERIES


def read_build_version(engine_dir: Path) -> dict[str, object] | None:
    """`Engine/Build/Build.version`. Cheap, exact, and needs no process."""
    path = engine_dir / "Engine" / "Build" / "Build.version"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _from_registry() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    try:
        import winreg
    except ImportError:  # pragma: no cover - Windows only, as the kit is
        return found
    for key_path in REGISTRY_KEYS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(key, name) as entry:
                            directory, _kind = winreg.QueryValueEx(entry, "InstalledDirectory")
                    except OSError:
                        continue
                    if directory:
                        found.append((f"registry:{key_path}\\{name}", Path(directory)))
        except OSError:
            continue
    return found


def _from_default_install() -> list[tuple[str, Path]]:
    base = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Epic Games"
    if not base.is_dir():
        return []
    return [("default-install", entry) for entry in sorted(base.glob("UE_*")) if entry.is_dir()]


def _describe(source: str, engine_dir: Path) -> EngineInfo | None:
    binary = engine_dir / RELATIVE_BINARY
    if not binary.is_file():
        return None
    info = EngineInfo(path=str(binary), source=source)
    build = read_build_version(engine_dir)
    if build:
        major, minor = build.get("MajorVersion"), build.get("MinorVersion")
        patch = build.get("PatchVersion")
        if isinstance(major, int) and isinstance(minor, int):
            info.series = f"{major}.{minor}"
            info.version = f"{major}.{minor}.{patch if isinstance(patch, int) else 0}"
        branch = build.get("BranchName")
        info.branch = str(branch) if branch else None
    else:
        info.notes.append("Build.version is missing or unreadable: the series could not be read")
    return info


def discover(configured: str | None = None) -> list[EngineInfo]:
    """Every editor this machine has, in the order the kit prefers them."""
    candidates: list[tuple[str, Path]] = []
    if configured:
        binary = Path(configured)
        if binary.is_file():
            candidates.append(("config/local.json", binary.parents[3]))
    env = os.environ.get("FLUIDUNREAL_EDITOR")
    if env and Path(env).is_file():
        candidates.append(("FLUIDUNREAL_EDITOR", Path(env).parents[3]))
    candidates.extend(_from_registry())
    candidates.extend(_from_default_install())

    seen: set[str] = set()
    found: list[EngineInfo] = []
    for source, engine_dir in candidates:
        info = _describe(source, engine_dir)
        if info is None or info.path.lower() in seen:
            continue
        seen.add(info.path.lower())
        found.append(info)
    return found


def select(
    configured: str | None = None, *, allow_unlocked: bool = False
) -> tuple[EngineInfo | None, list[str]]:
    """The editor the kit will use, or nothing with the reason."""
    notes: list[str] = []
    found = discover(configured)
    if not found:
        return None, [f"no {EDITOR} found in the registry or under Program Files\\Epic Games"]
    locked = [info for info in found if info.is_locked_series]
    others = [info for info in found if not info.is_locked_series]
    for info in others:
        notes.append(f"{info.path}: series {info.series or 'unknown'}, not the locked {LOCKED_UNREAL_SERIES}")
    if locked:
        chosen = locked[0]
        chosen.sha256 = sha256_file(Path(chosen.path))
        return chosen, notes
    if allow_unlocked and found:
        chosen = found[0]
        chosen.sha256 = sha256_file(Path(chosen.path))
        notes.append("using an unlocked series because it was explicitly allowed")
        return chosen, notes
    return None, notes


def project_plugins(uproject: Path) -> tuple[list[str], list[str]]:
    """Plugins the .uproject enables, and the ones known to abort the editor on this series."""
    try:
        data = json.loads(uproject.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return [], []
    names = [
        str(entry.get("Name"))
        for entry in (data.get("Plugins") or [])
        if isinstance(entry, dict) and entry.get("Enabled") and entry.get("Name")
    ]
    fatal = [name for name in names if name in KNOWN_MISSING_PLUGINS]
    return names, fatal


def probe(binary: Path, uproject: Path, script: Path, timeout_s: int) -> tuple[dict | None, str]:
    """Run a probe script in the editor and read back the line it prints.

    `available` is only ever claimed when that line was really read. A zero exit code on its own
    says nothing: lot 0 watched the editor idle for fifteen minutes and exit cleanly having run
    nothing at all.
    """
    command = [
        str(binary),
        str(uproject),
        "-run=pythonscript",
        f"-script={script}",
        "-unattended",
        "-nopause",
        "-nosplash",
        "-NoSound",
        "-stdout",
        "-FullStdOutLogOutput",
    ]
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    try:
        done = subprocess.run(  # noqa: S603 - argument list, never a shell string
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return None, f"the editor did not answer within {timeout_s}s (first open compiles shaders)"
    except OSError as exc:
        return None, f"the editor could not be started: {exc}"
    for line in (done.stdout or "").splitlines() + (done.stderr or "").splitlines():
        if PROBE_MARKER in line:
            try:
                return json.loads(line.split(PROBE_MARKER, 1)[1]), ""
            except ValueError:
                return None, "the probe line could not be parsed"
    return None, f"the editor printed no probe line (exit {done.returncode})"
