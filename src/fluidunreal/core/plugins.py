"""Which plugins a .uproject loads, and which of them a human has agreed to.

A plugin is code the editor runs as soon as the project opens, before the kit's runtime has any say.
The kit therefore opens a project only when every plugin it enables is either one it was proven
with, or one a person approved by name. An approval is a file a human writes through the CLI; the
kit never writes one on its own, and the skill never runs the command without being told to.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import now_iso

from fluidunreal.adapters.unreal_discovery import project_plugins

# The plugins the kit was proven with on the locked series: the test bed's own two, and the three
# Interchange plugins proof P1 found the engine enabling by itself. Everything else is somebody
# else's code, however common.
REVIEWED_PLUGINS = frozenset(
    {"PythonScriptPlugin", "PythonAutomationTest", "Interchange", "InterchangeEditor", "InterchangeAssets"}
)
APPROVALS = Path("state") / "approvals" / "plugins.json"


def approved_plugins(root: Path) -> dict[str, Any]:
    path = root / APPROVALS
    if not path.is_file():
        return {}
    try:
        return dict(read_json(path).get("plugins") or {})
    except (ValueError, OSError):
        return {}


def unreviewed_plugins(root: Path, uproject: Path) -> list[str]:
    """Enabled plugins that are neither reviewed nor approved, in the order the .uproject lists them."""
    enabled, _fatal = project_plugins(uproject)
    approved = approved_plugins(root)
    return [name for name in enabled if name not in REVIEWED_PLUGINS and name not in approved]


def approve(root: Path, uproject: Path, names: list[str]) -> dict[str, Any]:
    """Record a person's approval of plugins the project enables. Only names it enables are taken."""
    enabled, _fatal = project_plugins(uproject)
    unknown = [name for name in names if name not in enabled]
    if unknown:
        raise ValueError(f"{uproject.name} does not enable: {', '.join(unknown)}")
    record = {"schema_version": "1.0", "plugins": approved_plugins(root)}
    for name in names:
        record["plugins"][name] = {"approved_at": now_iso(), "uproject": str(uproject), "by": "cli"}
    path = root / APPROVALS
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, record)
    return record
