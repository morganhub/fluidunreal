"""game.screenshot: one rendered frame of the test bed, and the share of it the character covers.

The same bed as `game.smoke_test`, rendered off-screen. The character walks until it is mid-path,
is frozen mid-stride, and is shot from the side. Then it is hidden and the same camera shoots
again. The share of pixels that differ is the character (and its shadow); the frame without it is
the negative control, rendered in the same run from the same camera.

What lot 0 got wrong, and what this therefore does:

- the first frame and the second showed different scenes, and the share read a green,
  repeatable, meaningless 69 %. It happened again in 0.3.2 with nothing destroyed: the second
  `take_high_res_screenshot` rendered the editor's world, with its own lighting and its own
  reference-pose character, instead of the PIE world. That call shoots whichever viewport it
  finds. So neither frame goes through a viewport: a `SceneCapture2D` placed in the PIE world
  renders both into one render target, which is exported to PNG;
- exposure is fixed on the capture, or eye adaptation alone changes every pixel between frames;
- a share above `CEILING`, or a difference that spans the whole frame, is refused rather than
  reported: a character is one region, a changed view is everywhere.

It is the only visual evidence this kit produces, and a number is not a look: the result asks for
`ue-frame.png` to be opened and described.
"""

import os
import shutil

import unreal

from fluidunreal_runtime import png
from fluidunreal_runtime.errors import OpError
from fluidunreal_runtime.report import write_json_atomic
from fluidunreal_runtime.testbed import DEFERRED, Bed, _published, game_world, play_single_animation

MIN_SHARE = 0.01
# A character seen whole from 3.2 m cannot cover this much of the frame: above it, the two frames
# do not show the same scene, and the share measures the view changing.
CEILING = 0.40
# A difference box wider than this share of the frame is not one character.
MAX_BOX_WIDTH = 0.6
# Braking from full speed takes 88 cm. The prop's near face is at 180 cm and the capsule's radius
# 34: stopping input any later ran the capsule into the prop, and it slid off sideways toward the
# camera. The character stops at about 128 cm, in the open.
# Braking from full speed takes about 88 cm: input stops here so the character halts in the open,
# short of the prop's near face at 180 cm.
STOP_AT_X = 40.0
WALK_MAX_STEPS = 400
SETTLE_STEPS = 20
# Captures rendered and thrown away before each kept frame, so temporal effects have settled.
WARM_CAPTURES = 8
# From 4.5 m the character covered 1.19 % of the frame, a hair above the threshold: closer, so a
# pass does not depend on which frame of the stride the character stops on.
CAMERA_AT = unreal.Vector(130.0, -320.0, 100.0)
CAMERA_FACING = unreal.Rotator(roll=0.0, pitch=-5.0, yaw=90.0)


class FrameBed(Bed):
    """The smoke bed, lit, with a camera, and a capture sequence instead of fourteen checks."""

    def __init__(self, ctx, request, builder, mesh, anim, instance, width, height):
        Bed.__init__(self, ctx, request, builder, mesh, anim, instance)
        self.width = width
        self.height = height
        self.stage = "settle"
        self.stage_step = 0
        self.capture = None
        self.target = None
        self.shots = {}
        self.stopped_x = None
        self.stopped_at = None

    def build(self):
        Bed.build(self)
        unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.DirectionalLight,
            unreal.Vector(0.0, 0.0, 500.0),
            unreal.Rotator(roll=0.0, pitch=-45.0, yaw=45.0),
        )
        unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.SkyLight, unreal.Vector(0.0, 0.0, 400.0), unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0)
        )
        capture = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.SceneCapture2D, CAMERA_AT, CAMERA_FACING
        )
        capture.set_actor_label("FrameCapture")

    def resolve(self):
        chosen = Bed.resolve(self)
        if chosen is None:
            return None
        world = game_world(self.builder)
        for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.SceneCapture2D):
            if actor.get_actor_label() == "FrameCapture":
                self.capture = actor.capture_component2d
        if self.capture is None:
            raise OpError("INTERNAL_ERROR", "the bed's capture is not in the PIE world")
        self.target = unreal.RenderingLibrary.create_render_target2d(
            world, self.width, self.height, unreal.TextureRenderTargetFormat.RTF_RGBA8
        )
        self.capture.set_editor_property("texture_target", self.target)
        self.capture.set_editor_property("capture_every_frame", False)
        self.capture.set_editor_property("capture_on_movement", False)
        self.capture.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
        settings = self.capture.get_editor_property("post_process_settings")
        for name, value in (
            ("override_auto_exposure_method", True),
            ("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL),
            ("override_auto_exposure_bias", True),
            ("auto_exposure_bias", 10.0),
        ):
            try:
                settings.set_editor_property(name, value)
            except Exception as error:  # noqa: BLE001
                self.builder.warn("exposure setting %s refused: %s" % (name, error))
        self.capture.set_editor_property("post_process_settings", settings)
        self.capture.set_editor_property("post_process_blend_weight", 1.0)
        return chosen

    def shot_path(self, name):
        """`project_saved_dir()` is engine-relative: absolute before the filesystem sees it."""
        folder = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
        return os.path.join(folder, "Screenshots", "fluidunreal", self.ctx.task_id, name + ".png")

    def shoot(self, name):
        """Render the capture and write it. Reading the pixels back waits for the GPU."""
        target = self.shot_path(name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.isfile(target):
            os.remove(target)
        self.capture.capture_scene()
        world = game_world(self.builder)
        unreal.RenderingLibrary.export_render_target(
            world, self.target, os.path.dirname(target), os.path.basename(target)
        )
        self.shots[name] = target

    @staticmethod
    def written(path):
        return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 0

    def next_stage(self, stage):
        self.stage = stage
        self.stage_step = 0

    def measure(self, actor, component, step):
        self.stage_step += 1
        if self.stage == "settle" and self.stage_step >= SETTLE_STEPS:
            if self.anim is not None:
                self.play_via = play_single_animation(component, self.anim, self.builder)
            self.next_stage("walk")
        elif self.stage == "walk":
            actor.add_movement_input(unreal.Vector(1.0, 0.0, 0.0), 1.0, True)
            if actor.get_actor_location().x >= STOP_AT_X or self.stage_step >= WALK_MAX_STEPS:
                self.next_stage("brake")
        elif self.stage == "brake":
            # Frozen mid-stride: between the two frames, only the character's presence may change.
            if actor.get_velocity().length() < 1.0:
                component.stop()
                where = actor.get_actor_location()
                facing = component.get_world_rotation()
                self.stopped_x = round(where.x, 2)
                self.stopped_at = {
                    "actor_cm": [round(where.x, 2), round(where.y, 2), round(where.z, 2)],
                    "mesh_yaw_deg": round(facing.yaw, 2),
                    "facing_error_deg": self.facing_error_deg(actor, component),
                }
                self.next_stage("aim")
        elif self.stage == "aim":
            # Throw-away captures first: the kept frame must not be the first the capture renders.
            if self.stage_step <= WARM_CAPTURES:
                self.capture.capture_scene()
            elif self.stage_step >= SETTLE_STEPS:
                if self.ctx.test_hooks.get("frame_without_character"):
                    # The negative control of U08: no character in either frame must read ~0.
                    actor.set_actor_hidden_in_game(True)
                self.shoot("with-character")
                actor.set_actor_hidden_in_game(True)
                self.next_stage("hidden")
        elif self.stage == "hidden":
            if self.stage_step <= WARM_CAPTURES:
                self.capture.capture_scene()
            elif self.stage_step >= SETTLE_STEPS:
                self.shoot("without-character")
                self.finish()


def _judge(frames, builder):
    """The share, its box, and a verdict that refuses what cannot be the character."""
    with_path, without_path = frames.get("with-character"), frames.get("without-character")
    if not with_path or not without_path:
        return None, None, "the engine wrote no usable frame"
    try:
        comparison = png.compare(with_path, without_path)
    except Exception as error:  # noqa: BLE001
        return None, None, "the two frames could not be compared: %s" % error
    share = comparison["share"]
    box = comparison.get("box")
    if box and (box[2] - box[0] + 1) > MAX_BOX_WIDTH * comparison["width"]:
        return (
            comparison,
            None,
            "the difference spans %d of %d pixels across: a character is one region, so the two "
            "frames do not show the same scene" % (box[2] - box[0] + 1, comparison["width"]),
        )
    if share > CEILING:
        return (
            comparison,
            None,
            (
                "%.1f%% of the frame differs, above the %.0f%% ceiling: the two frames do not show the "
                "same scene, so the share says nothing about the character" % (share * 100, CEILING * 100)
            ),
        )
    return comparison, share >= MIN_SHARE, None


def run(ctx, request, builder):
    asset_id = request["target"].get("asset_id")
    instance = ctx.instance(asset_id)
    parameters = request.get("parameters") or {}
    content_path, version, mesh, anim, anim_name = _published(ctx, asset_id, None, builder)
    bed = FrameBed(
        ctx,
        request,
        builder,
        mesh,
        anim,
        instance,
        int(parameters.get("width") or 640),
        int(parameters.get("height") or 360),
    )
    bed.anim_name = anim_name

    def publish(_report):
        frames = {}
        for name, source in bed.shots.items():
            if bed.written(source):
                destination = ctx.out("ue-frame.png" if name == "with-character" else "ue-frame-empty.png")
                shutil.copyfile(source, destination)
                frames[name] = destination
        comparison, passed, refusal = _judge(frames, builder)
        report = {
            "schema_version": "1.0",
            "engine": unreal.SystemLibrary.get_engine_version(),
            "headless": False,
            "asset_id": asset_id,
            "content_path": content_path,
            "version": version,
            "clip": anim_name,
            "frames": {name: os.path.basename(path) for name, path in frames.items()},
            "camera": {
                "location_cm": [CAMERA_AT.x, CAMERA_AT.y, CAMERA_AT.z],
                "yaw_deg": 90.0,
                "through": "SceneCapture2D in the PIE world, exported render target",
            },
            "character_stopped_at_x": bed.stopped_x,
            "character": bed.stopped_at,
            "mesh_offset": bed.mesh_offset,
            "rendered_share": None if comparison is None else round(comparison["share"], 5),
            "comparison": comparison,
            "threshold": MIN_SHARE,
            "ceiling": CEILING,
            "passed": passed,
            "refused_because": refusal,
            "looked_at": False,
            "aborted": bed.report.get("aborted") if bed.report else None,
            "notes": bed.notes,
            "wall_time_ms": bed.build_report()["wall_time_ms"],
            "machine": bed.build_report()["machine"],
        }
        builder.write_report("screenshot-report.json", report)
        for name, path in frames.items():
            builder.add_file("image", path, role=name)
        builder.metrics.update(
            {
                "asset_id": asset_id,
                "version": version,
                "rendered_share": report["rendered_share"],
                "passed": passed,
            }
        )
        builder.limit("the share counts the character and its shadow: both differ between the frames")
        builder.limit("one frame, one camera, one pose: this is not how the game looks, it is proof it draws")
        builder.next_safe_actions.append(
            "open ue-frame.png and say you looked at it before judging how the character looks"
        )
        errors, status = [], "succeeded"
        aborted = bed.report.get("aborted") if bed.report else None
        if aborted:
            status = "failed"
            errors.append(
                {
                    "code": "INTERNAL_ERROR",
                    "message": "the bed stopped before its frames: %s" % aborted,
                    "recovery": "read unreal.log in the task folder",
                }
            )
        elif not frames:
            status = "blocked"
            errors.append(
                {
                    "code": "MISSING_DEPENDENCY",
                    "message": "the engine wrote no frame: rendering off-screen needs a usable GPU",
                    "recovery": "`fluidunreal doctor --project .` reports unreal.gpu",
                }
            )
        elif passed is not True:
            status = "failed"
            errors.append(
                {
                    "code": "VALIDATION_FAILED",
                    "message": refusal
                    or "the character covers %.2f%% of the frame, under %.0f%%"
                    % ((comparison or {}).get("share", 0.0) * 100, MIN_SHARE * 100),
                    "recovery": "open both frames in %s before anything else" % ctx.out_dir,
                }
            )
        write_json_atomic(os.path.join(ctx.task_dir, "result.json"), builder.result(status, errors))
        unreal.SystemLibrary.quit_editor()

    bed.on_finished = publish
    bed.run()
    return DEFERRED
