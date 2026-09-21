"""Host operations: everything that happens without starting the editor."""

from __future__ import annotations

from collections.abc import Callable

from fluidunreal.hostops import bundle, handoff
from fluidunreal.hostops.context import HostContext, HostOpError

HOST_HANDLERS: dict[str, Callable[[HostContext], None]] = {
    "bundle.accept": bundle.accept,
    "bundle.wrap": bundle.wrap,
    "bundle.inspect": bundle.inspect,
    "handoff.request": handoff.request,
}

__all__ = ["HOST_HANDLERS", "HostContext", "HostOpError"]
