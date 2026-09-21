"""Generate the reference hand-off bundle lot 0 imports, from fluidblend's CC0 Vitruvian fixture.

Runs the real chain against the real Blender: install the character, build the shot, make it walk,
bake it with rigid limbs, export with the Unreal preset. The bundle fluidblend publishes is copied
into fixtures/vitruvian-walk-unreal/.

Nothing here is part of the kit: it is a recipe, kept so the fixture can be regenerated rather than
trusted. Run it from the fluidblend checkout's environment:

    uv run --project ..\\fluidblend python scripts\\lot0\\make_fixture_bundle.py

Options:
    --work <dir>   where to build the scratch project (default: a temp folder, kept on success)
    --force        replace an existing fixture folder
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.project import kit_root, load_project, scaffold_project
from fluidblend.core.tasks import TaskRunner

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FIXTURE = REPO / "fixtures" / "vitruvian-walk-unreal"
SPAN = {"start": 1, "end_exclusive": 49}


def request(operation: str, operation_id: str, *, target=None, parameters=None, project_id="demo-studio"):
    return {
        "schema_version": "1.0",
        "operation": operation,
        "operation_id": operation_id,
        "project_id": project_id,
        "target": target or {},
        "parameters": parameters or {},
        "dry_run": False,
    }


def install_character(project) -> str:
    """Copy fluidblend's pinned CC0 fixture into the scratch project, with its licence."""
    fixture = kit_root() / "fixtures/vitruvian/character.blend"
    if not fixture.exists():
        raise SystemExit(
            f"not_run: {fixture} is missing. Run `git lfs pull` in the fluidblend checkout first."
        )
    metadata = read_json(fixture.with_name("asset.json"))
    if sha256_file(fixture) != metadata["sha256"]:
        raise SystemExit("the Vitruvian fixture does not match its pinned sha256: refusing to use it")
    folder = project.root / "assets/characters/vitruvian/v001"
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fixture, folder / "character.blend")
    (project.root / "licenses").mkdir(exist_ok=True)
    shutil.copy2(kit_root() / "licenses/vitruvian.md", project.root / "licenses/vitruvian.md")
    manifest = {
        key: metadata[key]
        for key in ("asset_id", "version", "sha256", "license", "objects", "armature", "rig_profile")
    }
    manifest.update(
        blend_path="assets/characters/vitruvian/v001/character.blend",
        license_path="licenses/vitruvian.md",
    )
    atomic_write_json(folder / "asset.json", manifest)
    return "assets/characters/vitruvian/v001/asset.json"


def run_chain(project) -> Path:
    runner = TaskRunner(project)
    manifest = install_character(project)
    shot = {"shot_id": "shot010"}
    hero = {**shot, "instance_id": "hero-01"}
    steps = (
        ("shot.build", "fx-build", shot, {"assets": [{"manifest_path": manifest, "instance_id": "hero-01"}]}),
        ("animation.create", "fx-walk", hero, {"preset": "walk", "output_clip": "walk"}),
        ("animation.apply", "fx-apply", hero, {"clip_id": "walk"}),
        (
            "animation.bake",
            "fx-bake",
            hero,
            {"output_clip": "walk-baked", "frame_range": SPAN, "rigid_limbs": True},
        ),
        (
            "game.export",
            "fx-export-unreal",
            shot,
            {
                "output_name": "vitruvian-walk",
                "instance_ids": ["hero-01"],
                "export_def_bones": True,
                "export_preset": "unreal",
            },
        ),
    )
    outcome = None
    for operation, operation_id, target, parameters in steps:
        print(f"-- {operation} ({operation_id})", flush=True)
        outcome = runner.run(request(operation, operation_id, target=target, parameters=parameters))
        if outcome.exit_code != 0:
            print(json.dumps(outcome.result.model_dump(mode="json"), indent=2)[:4000])
            raise SystemExit(f"{operation} failed with exit {outcome.exit_code}")
    bundle = next((a for a in outcome.result.artifacts if a.kind == "bundle"), None)
    if bundle is None:
        raise SystemExit(
            "no bundle was published: "
            + "; ".join(outcome.result.warnings or ["no reason given, which is itself a bug"])
        )
    return project.root / bundle.path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if FIXTURE.exists() and not args.force:
        raise SystemExit(f"{FIXTURE} already exists (pass --force to replace it)")

    work = args.work or Path(tempfile.mkdtemp(prefix="fluidunreal-fixture-"))
    root = work / "studio"
    print(f"scratch project: {root}")
    scaffold_project(root, profile="game", project_id="demo-studio", game_engine="unreal")
    project = load_project(root)

    bundle_path = run_chain(project)
    source = bundle_path.parent
    print(f"bundle published: {bundle_path}")

    # A bundle is its manifest plus the files the manifest names. Anything else the export folder
    # happens to carry is not part of the contract and does not belong in the fixture.
    if FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    FIXTURE.mkdir(parents=True)
    shutil.copy2(bundle_path, FIXTURE / "handoff-bundle.json")
    for entry in read_json(bundle_path)["files"]:
        destination = FIXTURE / entry["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / entry["path"], destination)

    manifest = read_json(FIXTURE / "handoff-bundle.json")
    for entry in manifest["files"]:
        carried = FIXTURE / entry["path"]
        if not carried.is_file() or sha256_file(carried) != entry["sha256"]:
            raise SystemExit(f"the copied bundle does not match its own manifest: {entry['path']}")
    instance = (manifest.get("instances") or [{}])[0]
    print(
        json.dumps(
            {
                "bundle_id": manifest["bundle_id"],
                "producer": manifest["producer"]["version"],
                "khronos": manifest["validation"]["khronos"],
                "bone_count": instance.get("bone_count"),
                "reference_pose": len(instance.get("reference_pose", [])),
                "clips": [c["clip_id"] for c in manifest.get("clips", [])],
                "files": [f["role"] for f in manifest["files"]],
                "limits": manifest.get("limits", []),
            },
            indent=2,
        )
    )
    print(f"\nfixture written: {FIXTURE}")
    print("Record its source, licence and sha256 in fixtures/README.md before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
