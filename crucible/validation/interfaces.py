"""Validation Protocols (gate 4).

Everything here consumes *finished run results*; validation never re-touches
raw data except through the same PIT-disciplined engine paths.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True, slots=True)
class Split:
    """Index ranges into a time-ordered sample, half-open ``[start, end)``.

    ``train``/``test`` may each hold more than one disjoint range: purged
    K-fold and CPCV place the test fold mid-timeline, so train data can sit
    on both sides of it after purging (docs/GLOSSARY.md: purge, embargo).
    ``validate`` is empty for splitters that don't produce a validate
    window — only ``WalkForwardSplitter`` does (three-way
    windows).
    """

    train: tuple[tuple[int, int], ...]
    test: tuple[tuple[int, int], ...]
    validate: tuple[tuple[int, int], ...] = ()


class Splitter(Protocol):
    """Walk-forward / purged K-fold / CPCV split generation."""

    def splits(self, n_samples: int) -> Iterator[Split]:
        """Deterministic for a given configuration; no RNG unless injected."""
        ...


class TrialRegistry(Protocol):
    """Counts every parameter evaluation per experiment family (R4.3).
    Conservative scoping per ADR-0008: all trials in a family count."""

    def record_trial(
        self,
        family: str,
        experiment_id: str,
        sharpe: float | None = None,
        mode: str | None = None,
        start_ns: int | None = None,
        end_ns: int | None = None,
    ) -> int:
        """Registers a trial; returns the family's running trial count.
        ``sharpe`` (per-period, not annualized) is stored for DSR's
        cross-trial dispersion estimate (ADR-0015) if given. ``mode``
        (``RunMode.value``) and ``start_ns``/``end_ns`` (the run's data
        window) are stored for contamination flagging (R4.9, ADR-0021) if
        given."""
        ...

    def trial_count(self, family: str) -> int: ...

    def trial_sharpes(self, family: str) -> Sequence[float]:
        """Per-period Sharpe of every distinct trial recorded for
        ``family`` that supplied one."""
        ...

    def overlapping_optimization_trials(
        self, family: str, start_ns: int, end_ns: int
    ) -> Sequence[str]:
        """``experiment_id``s of every ``mode="optimization"`` trial in
        ``family`` whose recorded data window overlaps
        ``[start_ns, end_ns)`` (R4.9, ADR-0021)."""
        ...


class ResamplingTest(Protocol):
    """Monte Carlo / bootstrap / null test over a realized return series."""

    @property
    def name(self) -> str: ...

    def run(
        self,
        returns: Sequence[float],
        rng: np.random.Generator,
        n_iterations: int,
    ) -> dict[str, float]:
        """Named statistics of the resampled distribution (e.g. p_drawdown_gt_30)."""
        ...
