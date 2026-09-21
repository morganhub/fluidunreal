"""What the code may never do, checked on the code itself rather than promised in a document.

- The runtime runs inside the editor's own Python 3.11, with the standard library and `unreal`
  only: anything else would be code the kit did not ship, and newer syntax would not even parse.
- The runtime starts no process: whatever the editor launches is the editor's, never the kit's.
- Nothing in the repository builds a command through a shell.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
RUNTIME = sorted((KIT / "unreal_runtime").rglob("*.py"))
PYTHON_SOURCES = sorted(
    path
    for folder in ("src", "unreal_runtime", "scripts", "tests")
    for path in (KIT / folder).rglob("*.py")
    if "__pycache__" not in path.parts
)
ALLOWED = set(sys.stdlib_module_names) | {"unreal", "fluidunreal_runtime", "__future__"}


def imported(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_there_is_a_runtime_to_check():
    assert len(RUNTIME) >= 8 and len(PYTHON_SOURCES) > len(RUNTIME)


@pytest.mark.parametrize("path", RUNTIME, ids=lambda p: p.name)
def test_the_runtime_parses_as_python_311_and_imports_only_the_stdlib_and_unreal(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 11))
    assert imported(tree) <= ALLOWED, sorted(imported(tree) - ALLOWED)
    assert "subprocess" not in imported(tree), "the runtime starts no process"
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not calls & {"exec", "eval", "compile", "__import__"}


def shell_calls(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "shell" and not (
                isinstance(keyword.value, ast.Constant) and keyword.value.value is False
            ):
                lines.append(node.lineno)
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "system"
            and getattr(func.value, "id", None) == "os"
        ):
            lines.append(node.lineno)
    return lines


def test_the_guards_catch_what_they_look_for():
    """A guard that never fires proves nothing: each one is shown a planted offence."""
    sources = ["import numpy", "from subprocess import run", "from . import sibling"]
    assert imported(ast.parse("\n".join(sources))) == {"numpy", "subprocess"}
    planted = [
        "import os, subprocess",
        "subprocess.run('x', shell=True)",
        "os.system('x')",
        "subprocess.run(['x'], shell=False)",
    ]
    assert shell_calls(ast.parse("\n".join(planted))) == [2, 3]


def test_no_command_anywhere_goes_through_a_shell():
    offenders = []
    for path in PYTHON_SOURCES:
        if path.name == "test_code_guards.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders += [f"{path.relative_to(KIT)}:{line}" for line in shell_calls(tree)]
    assert offenders == []
