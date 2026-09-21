"""Lot 0, proof P1: what Unreal Engine really is on this machine.

Run inside the editor. Prints one JSON line prefixed with FLUIDUNREAL_PROBE= so the caller can read
it out of a log that also carries the engine's own output. Nothing is asserted here: the point is to
record what is there, and the series it fixes.
"""

import json
import os
import platform
import sys
import time

import unreal

OUT_ENV = "FLUIDUNREAL_LOT0_OUT"


def plugin_names():
    """Enabled plugins, through whichever API the locked series exposes."""
    try:
        return sorted(p.get_name() for p in unreal.PluginBlueprintLibrary.get_enabled_plugins())
    except AttributeError:
        pass
    try:
        registry = unreal.PluginBlueprintLibrary
        return sorted(registry.get_plugin_names()) if hasattr(registry, "get_plugin_names") else []
    except Exception as exc:  # noqa: BLE001 - a probe reports, it does not fail
        return [f"unavailable: {exc}"]


def engine_facts():
    facts = {}
    for name, call in (
        ("engine_version", lambda: unreal.SystemLibrary.get_engine_version()),
        ("project_directory", lambda: unreal.Paths.project_dir()),
        ("engine_directory", lambda: unreal.Paths.engine_dir()),
        ("project_file", lambda: unreal.Paths.get_project_file_path()),
        ("is_editor", lambda: unreal.SystemLibrary.is_valid_class(unreal.EditorUtilityWidget)),
    ):
        try:
            facts[name] = call()
        except Exception as exc:  # noqa: BLE001
            facts[name] = f"unavailable: {exc}"
    return facts


def interchange_surface():
    """Which import classes this series actually exposes to Python (decides P2's approach)."""
    wanted = (
        "AssetImportTask",
        "AssetToolsHelpers",
        "InterchangeManager",
        "InterchangeGenericAssetsPipeline",
        "InterchangeGenericMeshPipeline",
        "InterchangeGenericAnimationPipeline",
        "InterchangeSourceData",
        "InterchangeAssetImportData",
        "GLTFImportOptions",
        "EditorAssetLibrary",
        "AnimationLibrary",
        "AutomationLibrary",
        "LevelEditorSubsystem",
        "EditorLevelLibrary",
        "SkeletalMeshSocket",
        "DataAssetFactory",
    )
    return {name: hasattr(unreal, name) for name in wanted}


def module_surface():
    """Free functions the test bed and the screenshot depend on."""
    wanted = (
        "register_slate_post_tick_callback",
        "unregister_slate_post_tick_callback",
        "log",
        "log_error",
    )
    return {name: hasattr(unreal, name) for name in wanted}


def main():
    started = time.monotonic()
    report = {
        "proof": "P1",
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "engine": engine_facts(),
        "plugins": plugin_names(),
        "unreal_classes": interchange_surface(),
        "unreal_functions": module_surface(),
        "argv": sys.argv,
        "probe_seconds": round(time.monotonic() - started, 3),
    }
    print("FLUIDUNREAL_PROBE=" + json.dumps(report))
    destination = os.environ.get(OUT_ENV)
    if destination:
        with open(destination, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
    unreal.log("fluidunreal lot0 P1 probe finished")


main()
