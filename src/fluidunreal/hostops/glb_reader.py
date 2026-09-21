"""Read a GLB's structure with the standard library alone.

`bundle.wrap` has to describe a GLB nobody documented: what nodes it has, which are skinned, what
animations it carries and how long they are. Only the JSON chunk is parsed; the binary chunk is
never decoded, so a hostile file cannot make this do work proportional to its contents.

What it reports is what is in the file. It infers nothing: a GLB with no skin says `skinned: false`,
and a bundle wrapped from it says so too rather than guessing that a character is in there.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
# A glTF JSON chunk describing a scene is kilobytes to a few megabytes. Beyond this the file is not
# something this kit should be parsing in memory.
MAX_JSON_BYTES = 64 * 1024 * 1024


class GlbError(ValueError):
    pass


def read_json_chunk(path: Path) -> dict[str, Any]:
    """The glTF JSON of a binary .glb. Raises `GlbError` on anything that is not one."""
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) < 12 or header[:4] != MAGIC:
            raise GlbError(f"not a GLB (no glTF magic): {path.name}")
        _magic, version, total = struct.unpack("<4sII", header)
        if version != 2:
            raise GlbError(f"unsupported GLB container version {version}; this kit reads version 2")
        actual = path.stat().st_size
        if total != actual:
            raise GlbError(f"the GLB header declares {total} bytes but the file holds {actual}")
        while True:
            chunk_header = handle.read(8)
            if len(chunk_header) < 8:
                raise GlbError("no JSON chunk found in the GLB")
            length, kind = struct.unpack("<II", chunk_header)
            if kind == JSON_CHUNK:
                if length > MAX_JSON_BYTES:
                    raise GlbError(f"the GLB's JSON chunk is {length} bytes: refused")
                payload = handle.read(length)
                if len(payload) != length:
                    raise GlbError("the GLB's JSON chunk is truncated")
                try:
                    return json.loads(payload.decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as exc:
                    raise GlbError(f"the GLB's JSON chunk is not valid JSON: {exc}") from exc
            if kind != BIN_CHUNK:
                # An unknown chunk is skipped, as the specification requires.
                pass
            handle.seek(length, 1)


def _animation_seconds(gltf: dict[str, Any], animation: dict[str, Any]) -> float | None:
    """Longest input accessor of the animation's samplers: its duration in seconds."""
    accessors = gltf.get("accessors") or []
    longest = None
    for sampler in animation.get("samplers") or []:
        index = sampler.get("input")
        if not isinstance(index, int) or not 0 <= index < len(accessors):
            continue
        maximum = accessors[index].get("max")
        if isinstance(maximum, list) and maximum and isinstance(maximum[0], int | float):
            value = float(maximum[0])
            longest = value if longest is None else max(longest, value)
    return longest


def describe(path: Path) -> dict[str, Any]:
    """Everything `bundle.wrap` needs, read rather than assumed."""
    gltf = read_json_chunk(path)
    nodes = gltf.get("nodes") or []
    skins = gltf.get("skins") or []
    meshes = gltf.get("meshes") or []

    skinned_nodes = [n for n in nodes if isinstance(n.get("skin"), int)]
    skeleton_roots = []
    for skin in skins:
        root = skin.get("skeleton")
        if isinstance(root, int) and 0 <= root < len(nodes):
            skeleton_roots.append(str(nodes[root].get("name") or f"node{root}"))

    joints: set[int] = set()
    for skin in skins:
        joints.update(j for j in (skin.get("joints") or []) if isinstance(j, int))

    animations = []
    for index, animation in enumerate(gltf.get("animations") or []):
        animations.append(
            {
                "name": str(animation.get("name") or f"animation{index}"),
                "seconds": _animation_seconds(gltf, animation),
                "channels": len(animation.get("channels") or []),
            }
        )

    extras = {}
    for node in nodes:
        for key, value in (node.get("extras") or {}).items():
            if key.startswith("fluidblend_"):
                extras.setdefault(key, str(value))

    return {
        "generator": str((gltf.get("asset") or {}).get("generator") or ""),
        "gltf_version": str((gltf.get("asset") or {}).get("version") or ""),
        "node_count": len(nodes),
        "mesh_count": len(meshes),
        "skin_count": len(skins),
        "bone_count": len(joints),
        "skinned": bool(skins and skinned_nodes),
        "skinned_node_names": [str(n.get("name") or "") for n in skinned_nodes],
        "skeleton_roots": skeleton_roots,
        "animations": animations,
        "extras": extras,
    }
