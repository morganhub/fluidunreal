"""What this machine can actually do, probed rather than assumed.

Every capability is one of: `available` (seen working), `not_installed`, `not_configured`,
`unverified` (found, but the probe was not run) or `incompatible`. `available` is never claimed from
an exit code alone. Lot 0 watched the editor start, return zero and run nothing at all, so a clean
exit proves only that the process ended.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fluidblend.adapters import gltf_validator as gltfv
from fluidblend.contracts.capabilities import CapabilitiesReport, Capability
from fluidblend.core.atomic import atomic_write_json
from fluidblend.core.hashing import now_iso

import fluidunreal
from fluidunreal.adapters import unreal_discovery as discovery
from fluidunreal.contracts.project import LOCKED_UNREAL_SERIES
from fluidunreal.core.project import Project, kit_root

PROBE_SCRIPT = "scripts/lot0/p1_probe.py"


def _capability(capability_id: str, **kwargs: Any) -> Capability:
    kwargs.setdefault("verified_at", now_iso())
    kwargs.setdefault("provider", "fluidunreal")
    return Capability(capability_id=capability_id, **kwargs)


def _editor(project: Project, notes: list[str]) -> tuple[Capability, discovery.EngineInfo | None]:
    chosen, discovery_notes = discovery.select(project.local.unreal_editor_executable)
    notes.extend(discovery_notes)
    every = discovery.discover(project.local.unreal_editor_executable)
    evidence: dict[str, Any] = {
        "locked_series": LOCKED_UNREAL_SERIES,
        "candidates": [
            {"path": info.path, "version": info.version, "series": info.series, "source": info.source}
            for info in every
        ],
    }
    if chosen is None:
        status = "incompatible" if every else "not_installed"
        return (
            _capability(
                "unreal.editor",
                provider="Epic Games",
                status=status,
                evidence=evidence,
                restrictions=discovery_notes,
                error=None
                if every
                else f"no {discovery.EDITOR} found; install Unreal Engine {LOCKED_UNREAL_SERIES}",
                fallback="nothing in this kit runs without the editor except the bundle operations",
            ),
            None,
        )
    evidence.update({"build_version": chosen.version, "branch": chosen.branch, "source": chosen.source})
    return (
        _capability(
            "unreal.editor",
            provider="Epic Games",
            version=chosen.version,
            executable=chosen.path,
            transport="process",
            status="available",
            evidence={**evidence, "sha256": chosen.sha256},
        ),
        chosen,
    )


def _python(project: Project, engine: discovery.EngineInfo | None, *, probe: bool) -> Capability:
    if engine is None:
        return _capability("unreal.python", status="not_installed", error="no editor to probe")
    uproject = project.uproject
    script = kit_root() / PROBE_SCRIPT
    if not uproject.is_file():
        return _capability(
            "unreal.python",
            status="not_configured",
            error=f"the project's .uproject does not exist: {uproject}",
            fallback="`init` lays down the test bed, or point ue.uproject at a real project",
        )
    if not script.is_file():
        return _capability("unreal.python", status="unverified", error=f"no probe script at {script}")
    if not probe:
        return _capability(
            "unreal.python",
            status="unverified",
            executable=engine.path,
            error="not probed (--no-probe): the editor was found but nothing was run",
        )
    answer, failure = discovery.probe(
        Path(engine.path), uproject, script, project.local.unreal_startup_timeout_s
    )
    if answer is None:
        return _capability(
            "unreal.python",
            status="unverified",
            executable=engine.path,
            error=failure,
            fallback="a first open compiles shaders; raise unreal_startup_timeout_s and try again",
        )
    classes = answer.get("unreal_classes") or {}
    missing = sorted(name for name, present in classes.items() if not present)
    return _capability(
        "unreal.python",
        provider="PythonScriptPlugin",
        version=str(answer.get("python", "")).split()[0] or None,
        executable=engine.path,
        transport="process",
        status="available",
        tools=sorted(name for name, present in classes.items() if present),
        restrictions=[f"absent on this series: {name}" for name in missing],
        evidence={
            "engine_version": (answer.get("engine") or {}).get("engine_version"),
            "python": answer.get("python"),
            "probe_seconds": answer.get("probe_seconds"),
        },
    )


def _project(project: Project) -> Capability:
    uproject = project.uproject
    if not uproject.is_file():
        return _capability(
            "unreal.project",
            status="not_configured",
            error=f"no .uproject at {uproject}",
            fallback="`fluidunreal init` lays down the test bed",
        )
    plugins, fatal = discovery.project_plugins(uproject)
    restrictions = []
    if fatal:
        restrictions.append(
            f"these plugins do not exist on {LOCKED_UNREAL_SERIES} and abort the editor at "
            f"startup: {', '.join(fatal)}"
        )
    return _capability(
        "unreal.project",
        provider="fluidunreal",
        executable=str(uproject),
        status="incompatible" if fatal else "available",
        tools=plugins,
        restrictions=restrictions,
        evidence={"content_root": str(project.content_root), "plugins": plugins},
        error=None if not fatal else "the project requests a plugin this engine does not have",
    )


def _validator(project: Project) -> Capability:
    """Shared with fluidblend: the tools folder is the same, so it is installed once."""
    found = gltfv.find_validator(project.local.gltf_validator_executable)
    if not found:
        return _capability(
            "gltf.khronos_validator",
            status="not_installed",
            error="no validator: a wrapped GLB's validity stays not_run, never passed",
            fallback="it is optional; bundle.wrap records not_run rather than guessing",
        )
    return _capability(
        "gltf.khronos_validator",
        provider="Khronos",
        executable=str(found),
        status="available",
        transport="process",
    )


def _uv() -> Capability:
    binary = shutil.which("uv")
    if not binary:
        return _capability("python.uv", status="not_installed", error="uv is not in PATH")
    try:
        done = subprocess.run(  # noqa: S603 - argument list
            [binary, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
        version = (done.stdout or "").strip() or None
    except (OSError, subprocess.SubprocessError) as exc:
        return _capability("python.uv", status="unverified", executable=binary, error=str(exc))
    return _capability("python.uv", provider="Astral", version=version, executable=binary, status="available")


def _fluidblend(project: Project) -> Capability:
    """Optional, and only needed to hand a fix back to the sibling kit."""
    import fluidblend

    linked = project.manifest.sources.fluidblend_project
    return _capability(
        "fluidblend.kit",
        provider="fluidblend",
        version=fluidblend.__version__,
        status="available" if linked else "not_configured",
        error=None
        if linked
        else "sources.fluidblend_project is not set: handoff.request cannot phrase a command",
        evidence={"library": fluidblend.__version__, "project": linked},
    )


def run_doctor(project: Project, *, probe: bool = True) -> CapabilitiesReport:
    notes: list[str] = []
    editor, engine = _editor(project, notes)
    capabilities = [
        editor,
        _project(project),
        _python(project, engine, probe=probe),
        _validator(project),
        _uv(),
        _fluidblend(project),
    ]
    report = CapabilitiesReport(
        generated_at=now_iso(),
        host={
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "fluidunreal": fluidunreal.__version__,
            "locked_unreal_series": LOCKED_UNREAL_SERIES,
            # Kept with the report rather than dropped: a note about which engines were passed over
            # is what makes a later "why did it pick that one" answerable.
            "discovery_notes": notes,
        },
        capabilities=capabilities,
    )
    destination = project.root / "state" / "diagnostics" / "capabilities.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, report.model_dump(mode="json"))
    return report


def write_lock(project: Project, report: CapabilitiesReport, path: Path) -> dict[str, Any]:
    """The lock records what was observed. It is only ever written on an explicit request."""
    lock = {
        "schema_version": fluidunreal.SCHEMA_VERSION,
        "dependencies": {
            capability.capability_id: {
                "name": capability.provider or capability.capability_id,
                "version": capability.version,
                # Machine paths stay in capabilities.json; the lock is meant to be committed.
                "path": None,
                "sha256": (capability.evidence or {}).get("sha256"),
                "source": (capability.evidence or {}).get("source"),
                "verified_at": report.generated_at,
                "status": capability.status,
            }
            for capability in report.capabilities
        },
        "extra": {
            "generated_at": report.generated_at,
            "fluidunreal": fluidunreal.__version__,
            "unreal_locked_series": LOCKED_UNREAL_SERIES,
            **{k: v for k, v in report.host.items() if k != "discovery_notes"},
        },
    }
    atomic_write_json(path, lock)
    return lock


def compare_lock(report: CapabilitiesReport, lock: dict[str, Any]) -> list[str]:
    """What drifted since the lock was written. Reported; the lock is never silently replaced."""
    drift: list[str] = []
    recorded = lock.get("dependencies") or {}
    for capability in report.capabilities:
        entry = recorded.get(capability.capability_id)
        if entry is None:
            drift.append(f"{capability.capability_id}: not in the lock")
            continue
        if entry.get("version") != capability.version:
            drift.append(
                f"{capability.capability_id}: version {entry.get('version')} locked, "
                f"{capability.version} observed"
            )
        if entry.get("status") != capability.status:
            drift.append(
                f"{capability.capability_id}: status {entry.get('status')} locked, "
                f"{capability.status} observed"
            )
    return drift
