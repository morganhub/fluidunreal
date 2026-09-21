"""The skill is part of the kit: it is checked like the rest of it."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fluidunreal.contracts.operations import OPERATIONS, validate_request
from fluidunreal.core.project import kit_root

SKILL = kit_root() / "skills" / "fluidunreal"
BODY_MIN, BODY_MAX = 120, 320


def frontmatter_and_body() -> tuple[dict[str, str], list[str]]:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md needs a frontmatter block"
    _, raw, body = text.split("---\n", 2)
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if line and not line.startswith((" ", "\t")) and ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields, body.splitlines()


def test_the_frontmatter_says_what_this_kit_is():
    fields, _body = frontmatter_and_body()
    assert fields["name"] == "fluidunreal" and fields["license"] == "MIT"
    description = (SKILL / "SKILL.md").read_text(encoding="utf-8").split("license:")[0]
    assert 1 <= len(description) <= 2048
    for expected in ("Unreal Engine", "handoff bundle", "import", "audit"):
        assert expected in description, expected


def test_the_description_captures_no_fluidblend_request():
    """Two skills live side by side: this one must not answer a Blender question."""
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    description = text.split("license:")[0]
    for blender_operation in ("scene.build", "animation.retime", "shot.preview", "game.export"):
        assert blender_operation not in description, blender_operation
    body = text.split("---\n", 2)[2]
    assert "fluidblend" in body, "the body must say where Blender work goes"


def test_the_body_stays_readable():
    _fields, body = frontmatter_and_body()
    assert BODY_MIN <= len(body) <= BODY_MAX, f"{len(body)} lines"


def test_every_reference_exists_and_is_linked():
    _fields, body = frontmatter_and_body()
    text = "\n".join(body)
    on_disk = {p.name for p in (SKILL / "references").glob("*.md")}
    assert on_disk == {
        "environment.md",
        "project.md",
        "bundles.md",
        "import.md",
        "test-bed.md",
        "handoff.md",
        "recovery.md",
    }
    for name in on_disk:
        assert name in text, f"{name} is not mentioned in SKILL.md"


def test_no_link_points_at_something_missing():
    for markdown in [SKILL / "SKILL.md", *(SKILL / "references").glob("*.md")]:
        text = markdown.read_text(encoding="utf-8")
        for target in re.findall(r"\]\((\.\./)?((?:references|assets|scripts)/[^)]+)\)", text):
            path = (SKILL / target[1]).resolve()
            assert path.is_file(), f"{markdown.name} links to a missing {target[1]}"


@pytest.mark.parametrize("example", sorted((SKILL / "assets").glob("request-*.json")))
def test_every_example_request_validates(example: Path):
    payload = json.loads(example.read_text(encoding="utf-8"))
    request, _params, spec = validate_request(payload)
    assert spec.name in OPERATIONS and request.operation_id


def test_the_examples_cover_everything_the_kit_intends_to_do():
    """P2 operations are named in the catalogue to be refused, so they carry no example."""
    named = {
        json.loads(p.read_text(encoding="utf-8"))["operation"]
        for p in (SKILL / "assets").glob("request-*.json")
    }
    runnable = {name for name, spec in OPERATIONS.items() if spec.cli_command is None and spec.lot != "P2"}
    assert named == runnable, f"missing examples: {sorted(runnable - named)}"
    p2 = {name for name, spec in OPERATIONS.items() if spec.lot == "P2"}
    assert p2 == {"game.package", "retarget.mannequin"}
    assert not (named & p2), "a P2 operation must not look runnable"


def test_the_bundle_example_is_the_real_one():
    example = json.loads((SKILL / "assets" / "handoff-bundle-example.json").read_text(encoding="utf-8"))
    fixture = kit_root() / "fixtures" / "vitruvian-walk-unreal" / "handoff-bundle.json"
    if not fixture.is_file():
        pytest.skip("not_run: the reference bundle is missing (git lfs pull)")
    assert example == json.loads(fixture.read_text(encoding="utf-8"))


def test_the_wrapper_is_shipped_with_the_skill():
    wrapper = (SKILL / "scripts" / "fluidunreal.ps1").read_text(encoding="utf-8")
    assert "FLUIDUNREAL_HOME" in wrapper and "unreal_runtime" in wrapper
    assert "kit-path.txt" in wrapper
