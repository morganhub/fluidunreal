"""An Unreal project the user already has: the kit writes under Content/Fluid and nowhere else.

Marked `unreal`: without the locked engine these are skipped as `not_run`, never counted as passed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fluidblend.core import exit_codes
from fluidblend.core.hashing import sha256_file

from fluidunreal.core.project import load_project, scaffold_project, templates_dir
from fluidunreal.core.tasks import TaskRunner
from fluidunreal.core.ue_content import CONTENT_INDEX, verify_content
from tests.conftest import make_request

pytestmark = pytest.mark.unreal

# The engine's own working folders: it writes there whatever the kit does, and they are reported by
# `inspect`, never versioned.
ENGINE_DIRS = {"Saved", "Intermediate", "DerivedDataCache"}


def their_game(tmp_path: Path) -> Path:
    """A project that is not the kit's: its own name, its own files, a Python plugin enabled."""
    source = templates_dir() / "game-unreal"
    game = tmp_path / "TheirGame"
    shutil.copytree(source / "Config", game / "Config")
    shutil.copyfile(source / "FluidUnrealTestBed.uproject", game / "TheirGame.uproject")
    (game / "Content" / "Their").mkdir(parents=True)
    (game / "Content" / "Their" / "notes.txt").write_text("the user's own content", encoding="utf-8")
    (game / "Source.txt").write_text("the user's own file", encoding="utf-8")
    return game / "TheirGame.uproject"


def outside_the_kit(game: Path) -> dict[str, str]:
    """Every file the kit must not touch, with its hash."""
    found = {}
    for path in sorted(game.rglob("*")):
        relative = path.relative_to(game)
        if not path.is_file() or relative.parts[0] in ENGINE_DIRS:
            continue
        if relative.parts[:2] == ("Content", "Fluid"):
            continue
        found[relative.as_posix()] = sha256_file(path)
    return found


def test_the_whole_chain_writes_only_under_content_fluid(tmp_path, fixture_bundle):
    uproject = their_game(tmp_path)
    game = uproject.parent
    before = outside_the_kit(game)
    root = tmp_path / "kit-project"
    scaffold_project(root, project_id="demo-game", ue_project=str(uproject))
    project = load_project(root)
    assert not list(root.rglob("*.uproject")), "no test bed is laid down beside someone else's project"
    runner = TaskRunner(project)

    warnings = []
    for request in (
        make_request("bundle.accept", "acc-001", parameters={"source_path": str(fixture_bundle)}),
        make_request("asset.import", "imp-001", target={"bundle_id": "fx-export-unreal"}),
        make_request(
            "game.smoke_test", "smoke-001", target={"bundle_id": "fx-export-unreal", "asset_id": "vitruvian"}
        ),
        make_request(
            "game.screenshot", "shot-001", target={"bundle_id": "fx-export-unreal", "asset_id": "vitruvian"}
        ),
    ):
        outcome = runner.run(request)
        assert outcome.exit_code == exit_codes.OK, (request["operation"], outcome.result.model_dump())
        warnings += outcome.result.warnings

    # The user's files are exactly as they were: none changed, none removed.
    after = outside_the_kit(game)
    assert {name: after.get(name) for name in before} == before
    # Anything added outside Content/Fluid was added by the engine, and the kit said so by name.
    for name in sorted(set(after) - set(before)):
        assert any(w.endswith(f"added {name}") for w in warnings), (name, warnings)
    # Under Content/Fluid: the imported version, indexed, and nothing else. No bed map, no staging.
    fluid = game / "Content" / "Fluid"
    assert sorted(p.name for p in fluid.iterdir()) == ["vitruvian"]
    assert (fluid / "vitruvian" / "v001" / CONTENT_INDEX).is_file()
    assert verify_content(fluid / "vitruvian" / "v001") == []
    assert not list(fluid.rglob("*.umap"))
    # The frames were written under Saved/ by the engine, copied out, and removed.
    assert not (game / "Saved" / "Screenshots" / "fluidunreal").exists()
    assert (root / "reviews" / "game" / "shot-001" / "ue-frame.png").is_file()
