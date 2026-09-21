"""fluidunreal runtime, executed inside the Unreal editor (standard library + `unreal` only).

Entry point: `main(envelope_path)`. The result is written atomically **before** the editor is asked
to quit, whatever happened. A run that leaves no result is an unknown write state, and the engine
treats it as one: lot 0 watched the editor exit cleanly having run nothing, so the file on disk is
the only thing that says what happened.

The editor embeds Python 3.11. Nothing here may use syntax newer than that.
"""

import os
import traceback

from fluidunreal_runtime.envelope import Context, load_envelope
from fluidunreal_runtime.errors import OpError
from fluidunreal_runtime.report import ResultBuilder, write_json_atomic

RUNTIME_VERSION = "0.3.1"

# A handler returns this when it finishes on the editor's tick rather than on this call. Waiting
# for it here would be the very thing that breaks: a blocking wait stops the editor ticking, so
# nothing it was waiting for ever happens. The handler writes the result and quits itself.
DEFERRED = "deferred"
SUPPORTED_UNREAL_SERIES = "5.8"


def _handlers():
    """Imported lazily so a broken handler cannot stop the result from being written."""
    from fluidunreal_runtime import audit, importer, screenshot, testbed

    return {
        "asset.import": importer.run,
        "asset.audit": audit.run,
        "game.smoke_test": testbed.run,
        "game.screenshot": screenshot.run,
    }


def _check_engine(ctx):
    import unreal

    version = unreal.SystemLibrary.get_engine_version()
    series = ".".join(version.split("-")[0].split(".")[:2])
    if series != SUPPORTED_UNREAL_SERIES:
        raise OpError(
            "UNSUPPORTED_CAPABILITY",
            "this runtime is validated for Unreal Engine %s, the editor is %s"
            % (SUPPORTED_UNREAL_SERIES, version),
            recovery="run the kit against the locked series, or re-do lot 0 on this one",
        )
    if ctx.engine_series != SUPPORTED_UNREAL_SERIES:
        raise OpError(
            "VALIDATION_FAILED",
            "the project declares engine series %s, this runtime is %s"
            % (ctx.engine_series, SUPPORTED_UNREAL_SERIES),
        )
    return version


def _check_runtime_version(ctx):
    if ctx.runtime_expected_version and ctx.runtime_expected_version != RUNTIME_VERSION:
        raise OpError(
            "VALIDATION_FAILED",
            "the engine expects runtime %s, this one is %s" % (ctx.runtime_expected_version, RUNTIME_VERSION),
            recovery="reinstall the kit; the runtime must be the version the engine approved",
        )


def run_envelope(envelope):
    """Execute one operation and return the result the engine will read back."""
    request = envelope["request"]
    ctx = Context.from_envelope(envelope)
    builder = ResultBuilder(request, ctx)
    try:
        _check_runtime_version(ctx)
        builder.metrics["engine"] = _check_engine(ctx)
        builder.metrics["runtime_version"] = RUNTIME_VERSION
        handler = _handlers().get(request["operation"])
        if handler is None:
            raise OpError(
                "UNSUPPORTED_CAPABILITY",
                "this runtime does not implement %s" % request["operation"],
            )
        outcome = handler(ctx, request, builder)
        if outcome is DEFERRED:
            return DEFERRED
        return builder.result()
    except OpError as error:
        return builder.result(
            "blocked" if error.code != "VALIDATION_FAILED" else "failed", [error.as_record()]
        )
    except BaseException as error:  # noqa: BLE001 - the result must exist whatever happened
        return builder.result(
            "failed",
            [
                {
                    "code": "INTERNAL_ERROR",
                    "message": "%s: %s" % (type(error).__name__, error),
                    "recovery": "read unreal.log in the task folder",
                    "details": {"traceback": traceback.format_exc()[-4000:]},
                }
            ],
        )


def main(envelope_path):
    import unreal

    result = None
    try:
        envelope = load_envelope(envelope_path)
        result = run_envelope(envelope)
        destination = os.path.join(envelope["context"]["task_dir"], "result.json")
        if result is DEFERRED:
            # The handler is driving the editor and will write the result and quit itself.
            unreal.log("fluidunreal: %s runs on the tick" % envelope["request"]["operation"])
            return
    except BaseException as error:  # noqa: BLE001
        unreal.log_error("fluidunreal: the envelope could not be read: %s" % error)
        unreal.SystemLibrary.quit_editor()
        return
    write_json_atomic(destination, result)
    unreal.log("fluidunreal: %s -> %s" % (result["operation"], result["status"]))
    unreal.SystemLibrary.quit_editor()
