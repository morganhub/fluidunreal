"""Enforcement of `config/permissions.json`. The kit reads it and never writes it."""

from __future__ import annotations

from dataclasses import dataclass

from fluidblend.contracts.project import Permissions

from fluidunreal.contracts.operations import OperationSpec


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str | None = None


def operation_allowed(permissions: Permissions, spec: OperationSpec) -> Verdict:
    """`inspect` may only read; anything that writes needs a profile that allows writing."""
    if permissions.profile == "inspect" and spec.op_class != "read":
        return Verdict(
            False,
            f"the permissions profile is 'inspect': {spec.name} writes, so it is refused. "
            "Change config/permissions.json deliberately; the kit never edits it.",
        )
    if spec.backend == "unreal" and not permissions.allowed_roots:
        return Verdict(False, "no allowed root: the kit will not start the editor")
    return Verdict(True)
