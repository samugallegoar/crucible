"""Crucible error hierarchy.

Prime directive: refuse, don't warn. Suspicious states raise one of these with
an actionable message saying what happened, where (timestamp, symbol, order id),
and how to fix it. No engine code path silently produces numbers after a
sanity-check failure.
"""

from __future__ import annotations


class CrucibleError(Exception):
    """Base class for every error raised by the engine."""


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


class CheckpointError(CrucibleError):
    """A checkpoint could not be written, read, or safely resumed (E7)."""
