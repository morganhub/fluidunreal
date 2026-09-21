"""Load, create and inspect a fluidunreal project.

A project is a folder this kit is the only writer of. It holds the bundles it accepted, the reports
it produced, and an Unreal project it writes into under `Content/Fluid/**` and nowhere else.

The Unreal project can be the test bed the kit lays down, or one the user already has. Either way
the kit refuses to touch anything outside its content root.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fluidblend.contracts.project import Permissions
from fluidblend.core.atomic import atomic_write_text, read_json
from fluidblend.core.hashing import now_iso, sha256_bytes
from fluidblend.core.journal import Journal
from fluidblend.core.paths import normalize_root
from pydantic import ValidationError

import fluidunreal
from fluidunreal.contracts.project import LOCKED_UNREAL_SERIES, LocalConfig, ProjectManifest

TEST_BED = "ue/FluidUnrealTestBed/FluidUnrealTestBed.uproject"
# Reported by `inspect`, never versioned and never counted against the disk budget: a first shader
# compile is gigabytes, and it is not something the kit produced.
UNCOUNTED_DIRS = ("Saved", "Intermediate", "DerivedDataCache", "Binaries", "Build")


class ProjectError(RuntimeError):
    pass


def kit_root() -> Path:
    """Root of the kit repository (holds `pyproject.toml`, `templates/`, `unreal_runtime/`)."""
    env = os.environ.get("FLUIDUNREAL_HOME")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and (parent / "templates").exists():
            return parent
    raise ProjectError("kit root not found; set FLUIDUNREAL_HOME")


def templates_dir() -> Path:
    return kit_root() / "templates"


@dataclass
class Project:
    root: Path
    manifest: ProjectManifest
    local: LocalConfig
    permissions: Permissions

    @property
    def project_id(self) -> str:
        return self.manifest.project_id

    @property
    def uproject(self) -> Path:
        """Absolute path of the .uproject, whether it is the kit's test bed or the user's own."""
        declared = Path(self.manifest.ue.uproject)
        return declared if declared.is_absolute() else self.root / declared

    @property
    def content_root(self) -> Path:
        """The only place under `Content/` this kit writes."""
        return self.uproject.parent / self.manifest.ue.content_root

    def asset_dir(self, asset_id: str) -> Path:
        return self.content_root / asset_id

    def bundle_dir(self, bundle_id: str) -> Path:
        return self.root / "bundles" / bundle_id

    def journal(self) -> Journal:
        return Journal(self.root / "state" / "journal.jsonl")


def _load_model(path: Path, model: type, *, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise ProjectError(f"missing {path.name}")
    try:
        return model.model_validate(read_json(path))
    except (ValidationError, ValueError) as exc:
        raise ProjectError(f"{path.name} is invalid: {exc}") from exc


def load_project(root: Path) -> Project:
    root = normalize_root(root)
    manifest_path = root / "project.json"
    if not manifest_path.exists():
        raise ProjectError(f"no project.json in {root}")
    manifest = _load_model(manifest_path, ProjectManifest)
    if manifest.schema_version != fluidunreal.SCHEMA_VERSION:
        raise ProjectError(
            f"schema_version {manifest.schema_version} is not supported "
            f"(kit {fluidunreal.SCHEMA_VERSION}); explicit migration required"
        )
    local = _load_model(root / "config" / "local.json", LocalConfig, default=LocalConfig())
    permissions = _load_model(root / "config" / "permissions.json", Permissions, default=Permissions())
    return Project(root=root, manifest=manifest, local=local, permissions=permissions)


# --- Scaffold -----------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def _render(text: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ProjectError(f"unknown placeholder in a template: {key}")
        return values[key]

    return _PLACEHOLDER.sub(replace, text)


def _same_content(existing: bytes, proposed: str, suffix: str) -> bool:
    if suffix == ".json":
        try:
            import json

            return json.loads(existing.decode("utf-8")) == json.loads(proposed)
        except (ValueError, UnicodeDecodeError):
            return False
    return existing.decode("utf-8", "replace").replace("\r\n", "\n") == proposed.replace("\r\n", "\n")


def scaffold_project(
    path: Path,
    *,
    project_id: str,
    name: str | None = None,
    ue_project: str | None = None,
    fluidblend_project: str | None = None,
    engine_series: str = LOCKED_UNREAL_SERIES,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create or complete a project, never overwriting a file that differs (U02)."""
    import json as _json

    root = Path(os.path.abspath(path))
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", project_id):
        raise ProjectError("invalid project_id (lowercase letters, digits, . _ -)")

    uproject = TEST_BED
    if ue_project and ue_project != "template":
        candidate = Path(ue_project)
        if not candidate.is_absolute():
            raise ProjectError("an existing Unreal project must be given as an absolute path")
        if candidate.suffix != ".uproject" or not candidate.is_file():
            raise ProjectError(f"not a .uproject file: {candidate}")
        # A symlink or junction would let a write escape the recorded root.
        if candidate.is_symlink() or os.path.realpath(candidate) != str(candidate):
            raise ProjectError("the .uproject path must be a real path, not a link")
        uproject = str(candidate)

    # A re-init must not rewrite the creation date: comparing a freshly stamped project.json to the
    # one on disk would report a conflict on every run that crosses a second boundary.
    created_at = now_iso()
    existing_manifest = root / "project.json"
    if existing_manifest.is_file():
        try:
            created_at = str(read_json(existing_manifest).get("created_at") or created_at)
        except (ValueError, OSError):
            pass

    structure = read_json(templates_dir() / "project" / "folder_structure.json")
    values = {
        "project_id": project_id,
        "project_name": name or project_id,
        "uproject": uproject.replace("\\", "\\\\"),
        "engine_series": engine_series,
        "fluidblend_project": _json.dumps(fluidblend_project),
        "created_at": created_at,
        "fluidunreal_version": fluidunreal.__version__,
        "schema_version": fluidunreal.SCHEMA_VERSION,
    }
    report: dict[str, Any] = {
        "root": str(root),
        "dry_run": dry_run,
        "created_dirs": [],
        "created_files": [],
        "identical": [],
        "conflicts": [],
        "first_init": not (root / "project.json").exists(),
        "uproject": uproject,
    }

    template_root = templates_dir() / "project" / "files"
    planned = [
        (root / rel, _render((template_root / source).read_text(encoding="utf-8"), values))
        for rel, source in structure["files"].items()
    ]

    for rel in structure["directories"]:
        target = root / rel
        if not target.exists():
            report["created_dirs"].append(rel)
            if not dry_run:
                target.mkdir(parents=True, exist_ok=True)

    for target, content in planned:
        rel = target.relative_to(root).as_posix()
        if target.exists():
            existing = target.read_bytes()
            if _same_content(existing, content, target.suffix):
                report["identical"].append(rel)
            else:
                report["conflicts"].append(
                    {
                        "path": rel,
                        "existing_sha256": sha256_bytes(existing),
                        "proposed_sha256": sha256_bytes(content.encode("utf-8")),
                        "action": "kept_existing",
                    }
                )
            continue
        report["created_files"].append(rel)
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target, content)

    if not dry_run:
        journal = Journal(root / "state" / "journal.jsonl")
        if report["first_init"]:
            journal.append(
                "project_initialized",
                project_id=project_id,
                uproject=uproject,
                engine_series=engine_series,
                fluidunreal_version=fluidunreal.__version__,
            )
        else:
            journal.append(
                "project_init_rerun",
                created=len(report["created_files"]),
                identical=len(report["identical"]),
                conflicts=[c["path"] for c in report["conflicts"]],
            )
    return report


def dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                continue
    return total


def inspect_project(project: Project) -> dict[str, Any]:
    """What is in the project right now, including what the engine left behind."""
    bundles = sorted(p.name for p in (project.root / "bundles").glob("*") if p.is_dir())
    imported = sorted(p.name for p in project.content_root.glob("*") if p.is_dir())
    uncounted = {
        name: dir_size_bytes(project.uproject.parent / name)
        for name in UNCOUNTED_DIRS
        if (project.uproject.parent / name).exists()
    }
    return {
        "project_id": project.project_id,
        "root": str(project.root),
        "uproject": str(project.uproject),
        "uproject_exists": project.uproject.is_file(),
        "engine_series": project.manifest.ue.engine_series,
        "content_root": str(project.content_root),
        "bundles": bundles,
        "imported_assets": imported,
        "fluidblend_project": project.manifest.sources.fluidblend_project,
        # Reported, never counted against the budget and never versioned.
        "engine_working_dirs_bytes": uncounted,
        "engine_working_dirs_gib": round(sum(uncounted.values()) / 1024**3, 3),
    }
