"""A plan: fluidblend's, plus the estimate broken down, where each number came from, and a verdict.

Subclassed rather than copied, so a reader of fluidblend's plans reads these too. The additions are
the reason for having a plan here at all: an estimate nobody can trace is a number to argue with,
not one to act on.
"""

from __future__ import annotations

from typing import Literal

from fluidblend.contracts import tasks as fb
from fluidblend.contracts.common import StrictModel
from pydantic import Field


class Estimate(StrictModel):
    """What a run is expected to cost before it starts."""

    seconds: float = Field(ge=0, description="run_seconds + startup_seconds")
    minutes: float = Field(ge=0)
    run_seconds: float = Field(ge=0)
    startup_seconds: float = Field(ge=0, description="Opening the project, before any Python runs")
    new_disk_bytes: int = Field(ge=0)
    free_disk_bytes: int | None = Field(default=None, ge=0, description="None when it was not measured")
    checked_before_execution: bool = Field(
        description="False for a host operation: nothing is refused on this estimate"
    )
    sources: dict[str, str] = Field(description="For each number above, where it came from")


class Plan(fb.Plan):
    estimate: Estimate
    verdict: Literal["within_budget", "over_budget", "blocked"]
