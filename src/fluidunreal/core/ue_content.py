"""Versions of imported Unreal content, and the hash that makes one a revision.

`RevisionStore` records one file per target, which is exactly right for a `.blend` and wrong for a
folder of `.uasset`. So a published version writes `FLUID_CONTENT.json`, listing every file it holds
with its sha256, and the revision points at that. External change detection then works unchanged,
and a `.uasset` edited by hand in the editor is caught the next time the kit looks.

The runtime's own tree is hashed too, and the hash travels in the envelope: what runs inside the
editor is only ever the code the engine approved.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import now_iso, sha256_file
from fluidblend.core.paths import is_reparse_point

CONTENT_INDEX = "FLUID_CONTENT.json"
VERSION_DIR = re.compile(r"^v(\d{3,})$")
ASSET_EXTENSIONS = (".uasset", ".umap")
# The importer stages every import under `<content root>/_staging/<task_id>` before renaming it to
# its version (unreal_runtime/fluidunreal_runtime/importer.py). The name is shared, not configurable.
STAGING_DIR = "_staging"


def version_dirs(asset_dir: Path) -> list[tuple[int, Path]]:
    if not asset_dir.is_dir():
        return []
    found = []
    for entry in sorted(asset_dir.iterdir()):
        match = VERSION_DIR.fullmatch(entry.name)
        if entry.is_dir() and match:
            found.append((int(match.group(1)), entry))
    return sorted(found)


def next_version(asset_dir: Path) -> int:
    existing = version_dirs(asset_dir)
    return (existing[-1][0] + 1) if existing else 1


def tree_hash(folder: Path, *, suffixes: tuple[str, ...] = ASSET_EXTENSIONS) -> tuple[str, dict[str, str]]:
    """One digest for a folder, plus the per-file hashes it was made from."""
    files: dict[str, str] = {}
    if folder.is_dir():
        for path in sorted(folder.rglob("*")):
            if path.is_file() and (not suffixes or path.suffix.lower() in suffixes):
                files[path.relative_to(folder).as_posix()] = sha256_file(path)
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(files[relative].encode("ascii"))
    return digest.hexdigest(), files


def write_content_index(version_dir: Path, *, asset_id: str, version: int, bundle_id: str) -> Path:
    """The file a revision points at. Written last, so a half-import leaves none."""
    digest, files = tree_hash(version_dir)
    index = version_dir / CONTENT_INDEX
    atomic_write_json(
        index,
        {
            "schema_version": "1.0",
            "asset_id": asset_id,
            "version": version,
            "bundle_id": bundle_id,
            "written_at": now_iso(),
            "tree_sha256": digest,
            "files": files,
        },
    )
    return index


def verify_content(version_dir: Path) -> list[str]:
    """Files that no longer hash to what the index recorded, or have gone missing."""
    index = version_dir / CONTENT_INDEX
    if not index.is_file():
        return [f"no {CONTENT_INDEX} in {version_dir.name}"]
    try:
        recorded = read_json(index).get("files") or {}
    except (ValueError, OSError) as exc:
        return [f"{CONTENT_INDEX} is unreadable: {exc}"]
    problems = []
    for relative, digest in sorted(recorded.items()):
        path = version_dir / relative
        if not path.is_file():
            problems.append(f"missing: {relative}")
        elif sha256_file(path) != digest:
            problems.append(f"changed since the import: {relative}")
    return problems


@dataclass
class Leftovers:
    """What an interrupted task may have left under the content root, split by what may go."""

    removable: list[Path] = field(default_factory=list)
    kept: list[tuple[Path, str]] = field(default_factory=list)


def _holds_only_engine_files(folder: Path) -> bool:
    return all(p.is_dir() or p.suffix.lower() in ASSET_EXTENSIONS for p in folder.rglob("*"))


def _why_not_removable(path: Path) -> str | None:
    if is_reparse_point(path):
        return "a link or junction: never followed, never removed"
    if path.is_dir() and not _holds_only_engine_files(path):
        return "holds files that are not Unreal assets"
    return None


def task_leftovers(
    content_root: Path, *, task_id: str, asset_id: str | None, next_version: int | None
) -> Leftovers:
    """Sort what is under the content root into what this task provably wrote, and the rest.

    Two things are provably a task's own. Its staging folder, because the name is its task id. And
    the version folder it was told to create, when that folder has no index: `next_version` is one
    past every version folder that existed when the task started, so nothing older can carry that
    number, and a folder without `FLUID_CONTENT.json` was never published. Everything else found on
    the way is reported and left alone, whatever it looks like.
    """
    found = Leftovers()
    staging = content_root / STAGING_DIR
    if staging.is_dir():
        for entry in sorted(staging.iterdir()):
            mine = entry.name == task_id or (
                entry.stem == task_id and entry.suffix.lower() in ASSET_EXTENSIONS
            )
            if not mine:
                found.kept.append((entry, "another task's staging: not this task's to remove"))
            elif reason := _why_not_removable(entry):
                found.kept.append((entry, reason))
            else:
                found.removable.append(entry)
    if not asset_id or not next_version:
        return found
    for number, folder in version_dirs(content_root / asset_id):
        indexed = (folder / CONTENT_INDEX).is_file()
        if number != next_version:
            if not indexed:
                found.kept.append(
                    (folder, f"unindexed, but not v{next_version:03d}, the version this task was given")
                )
        elif indexed:
            found.kept.append((folder, "indexed: a published version, never removed by a reconcile"))
        elif reason := _why_not_removable(folder):
            found.kept.append((folder, reason))
        else:
            found.removable.append(folder)
    return found


def remove_leftovers(content_root: Path, paths: list[Path]) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Remove what `task_leftovers` proved removable, then the folders that held only that."""
    removed: list[Path] = []
    failed: list[tuple[Path, str]] = []
    for path in paths:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as exc:
            failed.append((path, str(exc)))
            continue
        removed.append(path)
        # An empty `_staging` or asset folder is what the removal itself left; anything still
        # holding an entry is not, and rmdir refuses it.
        parent = path.parent
        if parent != content_root and parent.is_dir() and not any(parent.iterdir()):
            with contextlib.suppress(OSError):
                parent.rmdir()
    return removed, failed


def snapshot(asset_dir: Path, checkpoints: Path, *, task_id: str, label: str) -> dict[str, Any] | None:
    """Copy what is there before writing, so a failed import can be undone by hand.

    `create_file_checkpoint` snapshots a single file; imported content is a folder, so this does the
    same job in the same place, with the same manifest shape.
    """
    if not asset_dir.is_dir() or not any(asset_dir.iterdir()):
        return None
    checkpoint_id = f"{label}-{task_id}"
    destination = checkpoints / checkpoint_id / asset_dir.name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(asset_dir, destination)
    digest, files = tree_hash(destination)
    manifest = {
        "checkpoint_id": checkpoint_id,
        "source": asset_dir.as_posix(),
        "sha256": digest,
        "files": len(files),
        "created_at": now_iso(),
        "task_id": task_id,
    }
    atomic_write_json(checkpoints / checkpoint_id / "checkpoint.json", manifest)
    return manifest


def runtime_hash(runtime_dir: Path) -> tuple[str, dict[str, str]]:
    """The runtime tree, hashed before every launch. Only approved code enters the editor."""
    return tree_hash(runtime_dir, suffixes=(".py",))


def write_runtime_manifest(runtime_dir: Path) -> dict[str, Any]:
    digest, files = runtime_hash(runtime_dir)
    manifest = {"schema_version": "1.0", "hash": digest, "files": files, "written_at": now_iso()}
    atomic_write_json(runtime_dir / "RUNTIME_MANIFEST.json", manifest)
    return manifest
