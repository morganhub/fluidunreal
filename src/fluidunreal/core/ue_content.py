"""Versions of imported Unreal content, and the hash that makes one a revision.

`RevisionStore` records one file per target, which is exactly right for a `.blend` and wrong for a
folder of `.uasset`. So a published version writes `FLUID_CONTENT.json`, listing every file it holds
with its sha256, and the revision points at that. External change detection then works unchanged,
and a `.uasset` edited by hand in the editor is caught the next time the kit looks.

The runtime's own tree is hashed too, and the hash travels in the envelope: what runs inside the
editor is only ever the code the engine approved.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any

from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import now_iso, sha256_file

CONTENT_INDEX = "FLUID_CONTENT.json"
VERSION_DIR = re.compile(r"^v(\d{3,})$")
ASSET_EXTENSIONS = (".uasset", ".umap")


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
