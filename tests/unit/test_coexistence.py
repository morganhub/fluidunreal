"""Both skills installed in one agent project: each where it belongs, each answering for itself.

`not_run` without PowerShell 7 or without a fluidblend checkout beside this one (FLUIDBLEND_KIT).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from fluidunreal.core.project import kit_root

KITS = ("fluidblend", "fluidunreal")


def checkout(kit: str) -> Path:
    if kit == "fluidunreal":
        return kit_root()
    path = Path(os.environ.get("FLUIDBLEND_KIT") or kit_root().parent / "fluidblend")
    if not (path / "skills" / "fluidblend" / "SKILL.md").is_file():
        pytest.skip(f"not_run: no fluidblend checkout at {path}")
    return path


def pwsh(*arguments: str, cwd: Path) -> subprocess.CompletedProcess:
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("not_run: PowerShell 7 is not installed")
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV"))}
    return subprocess.run(  # noqa: S603 - argument list, no shell
        [executable, "-NoProfile", "-File", *arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )


def description(skill: Path) -> str:
    front = skill.read_text(encoding="utf-8").split("---")[1]
    match = re.search(r"^description: >-\n((?:  .*\n)+)", front, re.M)
    assert match, skill
    return " ".join(line.strip() for line in match.group(1).splitlines())


def test_both_skills_install_side_by_side_and_each_answers_for_itself(tmp_path: Path):
    agent = tmp_path / "agent-project"
    agent.mkdir()
    for kit in KITS:
        home = checkout(kit)
        installed = pwsh(
            str(home / "scripts" / "install-skill.ps1"), "-Target", str(agent), "-Client", "both", cwd=home
        )
        assert installed.returncode == 0, (kit, installed.stdout[-2000:], installed.stderr[-2000:])

    for kit in KITS:
        for client in (".claude", ".agents"):
            folder = agent / client / "skills" / kit
            assert (folder / "SKILL.md").is_file(), folder
            # Each copy points at its own kit, so each wrapper runs its own CLI.
            assert Path((folder / "kit-path.txt").read_text(encoding="utf-8").strip()) == checkout(kit)

    # Each answers from its own catalogue through the installed wrapper.
    for kit, own, other in (
        ("fluidunreal", "game.screenshot", "animation.bake"),
        ("fluidblend", "animation.bake", "game.screenshot"),
    ):
        wrapper = agent / ".claude" / "skills" / kit / "scripts" / f"{kit}.ps1"
        answered = pwsh(str(wrapper), "ops", "--all", "--json", cwd=agent)
        assert answered.returncode == 0, (kit, answered.stdout[-2000:], answered.stderr[-2000:])
        names = json.dumps(json.loads(answered.stdout))
        assert own in names and other not in names, kit

    # Each description claims its own tool, so a request lands on the kit that can do it.
    unreal = description(agent / ".claude" / "skills" / "fluidunreal" / "SKILL.md")
    blender = description(agent / ".claude" / "skills" / "fluidblend" / "SKILL.md")
    assert "Unreal Engine" in unreal and "fluidblend" in unreal
    assert "Blender" in blender
