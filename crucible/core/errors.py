"""Crucible error hierarchy.

Prime directive: refuse, don't warn. Suspicious states raise one of these with
an actionable message saying what happened, where (timestamp, symbol, order id),
and how to fix it. No engine code path silently produces numbers after a
sanity-check failure.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Mapping

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class CrucibleError(Exception):
    """Base class for every error raised by the engine.

    ``code`` is the machine-readable name of the error class (``ExperimentError`` ->
    ``experiment_error``): stable, never reused for another meaning, safe to branch on. ``location``
    is an optional mapping saying where the error arose (a path, symbol, timestamp, order id);
    attach it with ``raise SomeError(message).at(path=...)``. The message stays the human and LLM
    readable explanation of what happened and how to fix it (ADR-0084).
    """

    location: Mapping[str, object] | None = None

    @property
    def code(self) -> str:
        """The stable snake_case name of this error's class."""
        return _CAMEL_BOUNDARY.sub("_", type(self).__name__).lower()

    def at(self, **location: object) -> Self:
        """Records where the error arose and returns it, so it can be raised in one expression."""
        self.location = {**(self.location or {}), **location}
        return self


class LookaheadError(CrucibleError):
    """Data with ``available_at > as_of`` was requested or would be exposed."""


class InvariantViolation(CrucibleError):
    """An identity from docs/INVARIANTS.md failed at a mark."""


class DataQualityError(CrucibleError):
    """A dataset failed a pre-run quality check."""


class IllegalOrderTransition(CrucibleError):
    """An order state transition outside the allowed set was attempted."""


class ConfigurationError(CrucibleError):
    """Invalid or ambiguous experiment configuration."""


class ExperimentError(CrucibleError):
    """Artifact-store or run-registry failure (missing run, hash mismatch...)."""


class VaultLockedError(CrucibleError):
    """The futures holdout vault refused the attempt: an access, a run or a whole file reaches
    the declared protected period without an authorized evaluation (C6c, ADR-0105).

    It subclasses ``CrucibleError`` (not ``LookaheadError``): it is not the point-in-time rule,
    it is the holdout lock — the data exists, is knowable, and is deliberately withheld from the
    research path until a human authorizes ONE registered evaluation.
    """


class CheckpointError(CrucibleError):
    """A checkpoint could not be written, read, or safely resumed (E7)."""
