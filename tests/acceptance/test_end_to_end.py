"""U14: Blender to Unreal and back, every step the real tool, nothing copied from a fixture.

fluidblend bakes and exports a walking character with the Unreal preset; this kit accepts the
bundle, imports, audits, plays and shoots it; then asks for a re-export with `handoff.request`,
which fluidblend runs, and the new bundle is accepted in turn.

`not_run` without Unreal Engine 5.8, without a fluidblend checkout at 0.6.1 or later (the bake
declares its root motion from that version on), or without the Blender that checkout drives.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from fluidblend.core import exit_codes
from fluidblend.core.atomic import read_json

from fluidunreal.core.project import kit_root, load_project, scaffold_project
from fluidunreal.core.tasks import TaskRunner
from tests.conftest import make_request, note

pytestmark = pytest.mark.unreal

MINIMUM_FLUIDBLEND = (0, 6, 1)
TARGET = {"bundle_id": "fx-export-unreal", "asset_id": "vitruvian"}


def fluidblend_checkout() -> Path:
    """The sibling kit's checkout: FLUIDBLEND_KIT, else next to this one. Its version is read, not assumed."""
    candidate = Path(os.environ.get("FLUIDBLEND_KIT") or kit_root().parent / "fluidblend")
    pyproject = candidate / "pyproject.toml"
    if not pyproject.is_file():
        pytest.skip(f"not_run: no fluidblend checkout at {candidate}")
    match = re.search(r'^version = "(\d+)\.(\d+)\.(\d+)"', pyproject.read_text(encoding="utf-8"), re.M)
    if not match or tuple(int(g) for g in match.groups()) < MINIMUM_FLUIDBLEND:
        pytest.skip(f"not_run: fluidblend at {candidate} is older than 0.6.1")
    return candidate


def fluidblend(checkout: Path, *arguments: str, timeout: int = 1800) -> subprocess.CompletedProcess:
    """Run in the sibling kit's own environment, never this one's: it drives its own Blender."""
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV", "UV_"))}
    return subprocess.run(  # noqa: S603 - argument list, no shell
        ["uv", "run", "--project", str(checkout), *arguments],
        cwd=checkout,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def published(stdout: str, key: str) -> Path:
    lines = [line.split("=", 1)[1] for line in stdout.splitlines() if line.startswith(key + "=")]
    assert lines, f"no {key} in the output:\n{stdout[-3000:]}"
    return Path(lines[-1].strip())


@pytest.mark.acceptance(
    "U14", title="Blender to Unreal and back: export, import, audit, play, shoot, re-export"
)
def test_U14_the_whole_loop_with_both_kits(tmp_path):
    checkout = fluidblend_checkout()
    built = fluidblend(
        checkout,
        "python",
        str(kit_root() / "scripts" / "lot0" / "make_fixture_bundle.py"),
        "--build-only",
        "--work",
        str(tmp_path / "blender"),
    )
    if built.returncode != 0 and "not_run" in (built.stdout + built.stderr):
        pytest.skip("not_run: " + (built.stdout + built.stderr).strip().splitlines()[-1])
    assert built.returncode == 0, (built.stdout[-3000:], built.stderr[-3000:])
    studio = published(built.stdout, "FLUIDBLEND_STUDIO")
    bundle = published(built.stdout, "FLUIDBLEND_BUNDLE")

    manifest = read_json(bundle)
    assert manifest["producer"]["kit"] == "fluidblend"
    assert manifest["clips"][0]["root_motion"] == "root_bone", "fluidblend 0.6.1 says the walk travels"

    # Its own root: the shared fixture scaffolds one without the link to the Blender project.
    root = tmp_path / "unreal-side"
    scaffold_project(root, project_id="demo-game", fluidblend_project=str(studio))
    project = load_project(root)
    runner = TaskRunner(project)
    for request in (
        make_request("bundle.accept", "acc-001", parameters={"source_path": str(bundle.parent)}),
        make_request("asset.import", "imp-001", target={"bundle_id": "fx-export-unreal"}),
        make_request("asset.audit", "aud-001", target=TARGET),
        make_request("game.smoke_test", "smoke-001", target=TARGET),
        make_request("game.screenshot", "shot-001", target=TARGET),
    ):
        outcome = runner.run(request)
        assert outcome.exit_code == exit_codes.OK, (request["operation"], outcome.result.model_dump())
        if request["operation"] == "asset.audit":
            # The same walk the fixture declared in place, now declared as it is, passes.
            assert outcome.result.metrics["technical_pass"] is True, outcome.result.model_dump()

    # Back to Blender: the request this kit writes is one fluidblend runs as it is.
    handed = runner.run(
        make_request(
            "handoff.request",
            "handoff-001",
            target={"bundle_id": "fx-export-unreal"},
            parameters={"kind": "reexport_unreal", "output_name": "vitruvian-walk-again"},
        )
    )
    assert handed.exit_code == exit_codes.OK, handed.result.model_dump()
    written = project.root / "requests" / "fluidblend" / "handoff-001.json"
    assert written.is_file()
    rerun = fluidblend(
        checkout, "fluidblend", "run", "--project", str(studio), "--operation", str(written), "--json"
    )
    assert rerun.returncode == 0, (rerun.stdout[-3000:], rerun.stderr[-3000:])
    result = json.loads(rerun.stdout)
    again = next(a for a in result["artifacts"] if a["kind"] == "bundle")
    second = studio / again["path"]

    accepted = runner.run(
        make_request("bundle.accept", "acc-002", parameters={"source_path": str(second.parent)})
    )
    assert accepted.exit_code == exit_codes.OK, accepted.result.model_dump()
    assert read_json(second)["bundle_id"] != "fx-export-unreal"
    note(
        "U14",
        "fluidblend baked and exported; accepted, imported, audited (technical pass), played (14 checks) "
        "and shot; the reexport_unreal request ran in fluidblend as written and its bundle was accepted",
    )
