"""Lot 0, proof P4: an off-screen frame, and the share of it the character covers.

Renders the same bed twice in one run, with and without the character, and compares the two PNGs.
The frame without the character is the negative control: a share near zero there is what makes the
share above 1 % mean anything. A green number nobody looked at is not evidence.

Environment:
  FLUIDUNREAL_LOT0_OUT     absolute path of the JSON report to write
  FLUIDUNREAL_LOT0_MESH    content path of the SkeletalMesh imported by P2
  FLUIDUNREAL_LOT0_ANIM    content path of the AnimSequence imported by P2
  FLUIDUNREAL_LOT0_SHOTS   folder the PNGs are copied into
"""

import json
import os
import struct
import time
import zlib

import unreal

CUBE = "/Engine/BasicShapes/Cube.Cube"
WIDTH, HEIGHT = 640, 360
DIFFERENCE_THRESHOLD = 12  # 8-bit levels: below this, two pixels are the same picture


def read_png(path):
    """Minimal PNG reader: 8-bit RGB/RGBA, the only formats the engine writes here."""
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    offset, header, pixels = 8, None, bytearray()
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
            header = (width, height, depth, colour)
        elif kind == b"IDAT":
            pixels += body
        elif kind == b"IEND":
            break
        offset += 12 + length
    if header is None:
        raise ValueError(f"no IHDR: {path}")
    width, height, depth, colour = header
    if depth != 8 or colour not in (2, 6):
        raise ValueError(f"unsupported PNG ({depth}-bit, colour {colour}): {path}")
    channels = 3 if colour == 2 else 4
    raw = zlib.decompress(bytes(pixels))
    stride = width * channels
    out, previous = [], bytearray(stride)
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        line = bytearray(raw[position + 1 : position + 1 + stride])
        position += 1 + stride
        for index in range(stride):
            left = line[index - channels] if index >= channels else 0
            up = previous[index]
            corner = previous[index - channels] if index >= channels else 0
            value = line[index]
            if filter_type == 1:
                value += left
            elif filter_type == 2:
                value += up
            elif filter_type == 3:
                value += (left + up) // 2
            elif filter_type == 4:
                delta = left + up - corner
                candidates = (abs(delta - left), abs(delta - up), abs(delta - corner))
                value += (left, up, corner)[candidates.index(min(candidates))]
            line[index] = value & 0xFF
        out.append(bytes(line))
        previous = line
    return width, height, channels, out


def differing_share(first, second):
    w1, h1, c1, rows1 = read_png(first)
    w2, h2, c2, rows2 = read_png(second)
    if (w1, h1) != (w2, h2):
        raise ValueError("the two frames differ in size: they cannot be compared")
    differing = 0
    for row1, row2 in zip(rows1, rows2, strict=True):
        for x in range(w1):
            a, b = x * c1, x * c2
            if (
                abs(row1[a] - row2[b]) > DIFFERENCE_THRESHOLD
                or abs(row1[a + 1] - row2[b + 1]) > DIFFERENCE_THRESHOLD
                or abs(row1[a + 2] - row2[b + 2]) > DIFFERENCE_THRESHOLD
            ):
                differing += 1
    return differing / float(w1 * h1)


def build_bed(mesh_path, anim_path, notes):
    subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    subsystem.new_level("/Game/Lot0/P4Bed")
    cube = unreal.EditorAssetLibrary.load_asset(CUBE)
    floor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.StaticMeshActor, unreal.Vector(0.0, 0.0, -50.0), unreal.Rotator(0.0, 0.0, 0.0)
    )
    floor.static_mesh_component.set_static_mesh(cube)
    floor.set_actor_scale3d(unreal.Vector(20.0, 20.0, 1.0))

    unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.DirectionalLight, unreal.Vector(0.0, 0.0, 500.0), unreal.Rotator(-45.0, 45.0, 0.0)
    )
    unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SkyLight, unreal.Vector(0.0, 0.0, 400.0), unreal.Rotator(0.0, 0.0, 0.0)
    )
    camera = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.CameraActor, unreal.Vector(-350.0, 0.0, 120.0), unreal.Rotator(0.0, 0.0, 0.0)
    )

    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SkeletalMeshActor, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0)
    )
    component = actor.skeletal_mesh_component
    mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
    for setter in ("set_skeletal_mesh_asset", "set_skeletal_mesh"):
        if hasattr(component, setter):
            getattr(component, setter)(mesh)
            break
    else:
        notes.append("no setter found for the skeletal mesh")
    component.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
    component.set_editor_property("anim_to_play", unreal.EditorAssetLibrary.load_asset(anim_path))
    component.set_editor_property("looping", True)
    return actor, camera


def shoot(name, notes):
    """Returns the PNG path the engine wrote, or None with a note saying why not."""
    target = os.path.join(unreal.Paths.project_saved_dir(), "Screenshots", name + ".png")
    try:
        unreal.AutomationLibrary.take_high_res_screenshot(WIDTH, HEIGHT, target)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"take_high_res_screenshot({name}) raised: {exc}")
        return None
    for _ in range(200):
        if os.path.isfile(target) and os.path.getsize(target) > 0:
            return target
        time.sleep(0.05)
    notes.append(f"no PNG appeared for {name} at {target}")
    return None


def main():
    notes = []
    report = {"proof": "P4", "engine": unreal.SystemLibrary.get_engine_version(), "notes": notes}
    try:
        actor, _camera = build_bed(
            os.environ["FLUIDUNREAL_LOT0_MESH"], os.environ["FLUIDUNREAL_LOT0_ANIM"], notes
        )
        with_character = shoot("p4-with-character", notes)
        actor.set_actor_hidden_in_game(True)
        if hasattr(actor, "set_is_temporarily_hidden_in_editor"):
            actor.set_is_temporarily_hidden_in_editor(True)
        without_character = shoot("p4-without-character", notes)
        report["frames"] = {"with_character": with_character, "without_character": without_character}
        if with_character and without_character:
            share = differing_share(with_character, without_character)
            report["rendered_share"] = round(share, 5)
            report["threshold"] = 0.01
            report["passed"] = share >= 0.01
        else:
            report["rendered_share"] = None
            report["passed"] = None
            notes.append("not_run: the engine wrote no usable frame, so nothing is claimed")
    except Exception as exc:  # noqa: BLE001
        report["passed"] = None
        notes.append(f"P4 raised: {exc}")
    with open(os.environ["FLUIDUNREAL_LOT0_OUT"], "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    print("FLUIDUNREAL_PROBE=" + json.dumps({"proof": "P4", "share": report.get("rendered_share")}))
    unreal.SystemLibrary.quit_editor()


main()
