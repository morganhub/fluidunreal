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
DIFFERENCE_THRESHOLD = 12
# Above this the two frames cannot be the same scene: the measurement is refused, not reported.
PLAUSIBLE_CEILING = 0.40  # 8-bit levels: below this, two pixels are the same picture


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
    anim = unreal.EditorAssetLibrary.load_asset(anim_path)
    # P3 measured it: 5.8.2 has no `anim_to_play` property on the component.
    try:
        component.play_animation(anim, True)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"play_animation unavailable: {exc}")
    return actor, camera


def shot_path(name):
    """`project_saved_dir()` is engine-relative: make it absolute before touching the filesystem."""
    folder = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
    return os.path.join(folder, "Screenshots", name + ".png")


def request_shot(name, notes, controller=None, camera=None):
    """Ask for a frame. It is latent: only ticks make the engine render and write it.

    The first run slept in a loop waiting for the file and got nothing, because sleeping on the main
    thread is exactly what stops the engine from ticking. The waiting is done by the tick callback.
    """
    target = shot_path(name)
    try:
        if controller is not None and camera is not None:
            controller.set_view_target_with_blend(camera, 0.0)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.isfile(target):
            os.remove(target)
        unreal.AutomationLibrary.take_high_res_screenshot(WIDTH, HEIGHT, target)
        return target
    except Exception as exc:  # noqa: BLE001
        notes.append(f"take_high_res_screenshot({name}) raised: {exc}")
        return None


def written(path):
    return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 0


class Shooter:
    """Two frames, one run: with the character and without it, the negative control."""

    WAIT_TICKS = 180

    def __init__(self, notes, report_path):
        self.notes = notes
        self.report_path = report_path
        self.report = {"proof": "P4", "engine": unreal.SystemLibrary.get_engine_version(), "notes": notes}
        self.actor = None
        self.stage = "warmup"
        self.waited = 0
        self.with_character = None
        self.without_character = None
        self.handle = None
        self.pie_actor = None
        self.camera = None
        self.controller = None

    def finish(self):
        if self.handle is not None:
            unreal.unregister_slate_post_tick_callback(self.handle)
            self.handle = None
        frames = {"with_character": self.with_character, "without_character": self.without_character}
        self.report["frames"] = frames
        if written(self.with_character) and written(self.without_character):
            try:
                share = differing_share(self.with_character, self.without_character)
                self.report["rendered_share"] = round(share, 5)
                self.report["threshold"] = 0.01
                self.report["ceiling"] = PLAUSIBLE_CEILING
                if share > PLAUSIBLE_CEILING:
                    # A character cannot cover most of the frame here. A share this high means the
                    # two frames do not show the same scene, so the number measures the view
                    # changing, not the character. Looked at: it was a different scene entirely.
                    self.report["passed"] = None
                    self.notes.append(
                        f"not_run: {share:.1%} of the frame differs, above the {PLAUSIBLE_CEILING:.0%} "
                        "ceiling. The two frames do not show the same scene, so the share measures "
                        "nothing about the character. Open both PNGs before believing any number here"
                    )
                else:
                    self.report["passed"] = share >= 0.01
            except Exception as exc:  # noqa: BLE001
                self.report["passed"] = None
                self.notes.append(f"the two frames could not be compared: {exc}")
        else:
            self.report["rendered_share"] = None
            self.report["passed"] = None
            self.notes.append("not_run: the engine wrote no usable frame, so nothing is claimed")
        with open(self.report_path, "w", encoding="utf-8") as handle:
            json.dump(self.report, handle, indent=2, sort_keys=True)
        print("FLUIDUNREAL_PROBE=" + json.dumps({"proof": "P4", "share": self.report["rendered_share"]}))
        unreal.SystemLibrary.quit_editor()

    def step(self, _delta):
        self.waited += 1
        try:
            if self.stage == "warmup" and self.waited == 20:
                self.aim_camera()
            if self.stage == "warmup" and self.waited > 60:
                self.with_character = request_shot(
                    "p4-with-character", self.notes, self.controller, self.camera
                )
                self.stage, self.waited = "first", 0
            elif self.stage == "first" and (written(self.with_character) or self.waited > self.WAIT_TICKS):
                if not written(self.with_character):
                    self.notes.append("the first frame never appeared")
                target = self.pie_actor or self.actor
                target.set_actor_hidden_in_game(True)
                self.notes.append(f"hidden for the negative control: {target.get_name()}")
                self.stage, self.waited = "hidden", 0
            elif self.stage == "hidden" and self.waited > 30:
                self.without_character = request_shot(
                    "p4-without-character", self.notes, self.controller, self.camera
                )
                self.stage, self.waited = "second", 0
            elif self.stage == "second" and (
                written(self.without_character) or self.waited > self.WAIT_TICKS
            ):
                self.finish()
        except Exception as exc:  # noqa: BLE001
            self.notes.append(f"P4 step raised: {exc}")
            self.finish()

    def aim_camera(self):
        """Point the game view at the bed's camera, and freeze everything else.

        The first run compared two frames that showed entirely different scenes and reported a
        meaningless 69 %: the capture takes the game viewport, which was not looking at the bed.
        Nothing but the character's presence may differ between the two frames.
        """
        world = None
        for call in (
            lambda: unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world(),
            lambda: unreal.EditorLevelLibrary.get_game_world(),
        ):
            try:
                world = call()
            except Exception:  # noqa: BLE001
                continue
            if world is not None:
                break
        if world is None:
            self.notes.append("no game world: the capture cannot be aimed")
            return
        try:
            controller = unreal.GameplayStatics.get_player_controller(world, 0)
            cameras = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.CameraActor)
            if controller is None or not cameras:
                self.notes.append(f"controller={controller is not None}, cameras={len(cameras or [])}")
                return
            # The auto-spawned default pawn is a sphere that both occludes the bed and takes the
            # view back: measured, the second frame showed its interior instead of the scene.
            self.camera = cameras[0]
            self.controller = controller
            pawn = controller.get_controlled_pawn()
            if pawn is not None and not isinstance(pawn, unreal.SkeletalMeshActor):
                self.notes.append(f"the default pawn {pawn.get_name()} is removed from the bed")
                controller.un_possess()
                pawn.destroy_actor()
            controller.set_view_target_with_blend(cameras[0], 0.0)
            self.notes.append(f"the view is aimed at {cameras[0].get_name()}")
            self.pie_actor = next(
                iter(unreal.GameplayStatics.get_all_actors_of_class(world, unreal.SkeletalMeshActor)), None
            )
            if self.pie_actor is None:
                self.notes.append("no SkeletalMeshActor in the PIE world: the character cannot be hidden")
            else:
                # A moving clip would change the picture on its own: only presence may differ.
                self.pie_actor.skeletal_mesh_component.stop()
        except Exception as exc:  # noqa: BLE001
            self.notes.append(f"aiming the capture failed: {exc}")

    def run(self):
        self.actor, _camera = build_bed(
            os.environ["FLUIDUNREAL_LOT0_MESH"], os.environ["FLUIDUNREAL_LOT0_ANIM"], self.notes
        )
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        # P3 measured it: only `editor_request_begin_play` actually simulates and renders.
        subsystem.editor_request_begin_play()
        self.handle = unreal.register_slate_post_tick_callback(self.step)


def main():
    notes = []
    shooter = Shooter(notes, os.environ["FLUIDUNREAL_LOT0_OUT"])
    try:
        shooter.run()
    except Exception as exc:  # noqa: BLE001
        notes.append(f"P4 could not start: {exc}")
        shooter.finish()


main()
