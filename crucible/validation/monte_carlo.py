"""Monte Carlo resampling tests over a realized return series (ADR-0017): return-order shuffle,
start-date (circular) shift, and
block bootstrap -- implementing ``validation.interfaces.ResamplingTest``.

Execution-assumption and strategy-parameter perturbation Monte Carlo need
re-simulation (the return series a finished run already has isn't enough
to answer "what if latency had been higher"), so they don't fit this
return-only Protocol and aren't implemented here -- see ADR-0017 and
docs/modules/validation.md known gaps.

Reports "P(drawdown worse than a threshold)".
Return-order shuffle and start-date shift are BOTH permutations of the
same fixed multiset of returns, so mean/std -- and therefore per-period
Sharpe -- are mathematically invariant across their iterations (only the
PATH, and so drawdown, varies); their Sharpe output is a single constant,
not a distribution, and is named accordingly rather than reported as a
median/probability like the genuinely-varying block bootstrap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from crucible.core.drawdown import max_drawdown_from_returns as _max_drawdown_from_returns
from crucible.core.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_DRAWDOWN_THRESHOLD = -0.30


def _per_period_sharpe(returns: np.ndarray) -> float:
    std = returns.std(ddof=1)
    return float(returns.mean() / std) if std else 0.0


def _validated_array(returns: Sequence[float], n_iterations: int) -> np.ndarray:
    arr = np.asarray(returns, dtype=np.float64)
    if len(arr) < 3:
        msg = (
            f"cannot run a Monte Carlo resampling test on {len(arr)} return observations; need >= 3"
        )
        raise ConfigurationError(msg)
    if n_iterations < 1:
        msg = f"n_iterations must be >= 1, got {n_iterations}"
        raise ConfigurationError(msg)
    if not np.all(np.isfinite(arr)) or np.any(arr <= -1.0):
        msg = (
            "cannot run a Monte Carlo resampling test: the returns contain NaN/infinite values "
            "or a return of -100% or worse (ruin)"
        )
        raise ConfigurationError(msg)
    return arr


@dataclass(frozen=True, slots=True)
class ReturnOrderShuffleTest:
    """Randomly permutes the return series' order (a "trade-order
    reshuffle", implemented at the return-series level -- ADR-0017).
    Isolates sequencing risk from return-generating-process risk: total
    return and Sharpe can't move, only the drawdown path can."""

    drawdown_threshold: float = DEFAULT_DRAWDOWN_THRESHOLD

    @property
    def name(self) -> str:
        return "return_order_shuffle"

    def run(
        self, returns: Sequence[float], rng: np.random.Generator, n_iterations: int
    ) -> dict[str, float]:
        arr = _validated_array(returns, n_iterations)
        drawdowns = np.array(
            [_max_drawdown_from_returns(rng.permutation(arr)) for _ in range(n_iterations)]
        )
        return {
            "p_drawdown_worse_than_threshold": float((drawdowns <= self.drawdown_threshold).mean()),
            "drawdown_threshold": self.drawdown_threshold,
            "median_max_drawdown": float(np.median(drawdowns)),
            "worst_max_drawdown": float(drawdowns.min()),
            "sharpe_invariant_to_permutation": _per_period_sharpe(arr),
        }


@dataclass(frozen=True, slots=True)
class StartDateShiftTest:
    """Circularly rotates the return series to a randomly chosen start
    point (a "start-date shift", implemented as a rotation of the
    already-computed series rather than a re-simulation from a different
    calendar date -- ADR-0017). Same Sharpe-invariance property as the
    shuffle test, for the same reason: a rotation is a permutation."""

    drawdown_threshold: float = DEFAULT_DRAWDOWN_THRESHOLD

    @property
    def name(self) -> str:
        return "start_date_shift"

    def run(
        self, returns: Sequence[float], rng: np.random.Generator, n_iterations: int
    ) -> dict[str, float]:
        arr = _validated_array(returns, n_iterations)
        n = len(arr)
        shifts = rng.integers(0, n, size=n_iterations)
        drawdowns = np.array([_max_drawdown_from_returns(np.roll(arr, int(s))) for s in shifts])
        return {
            "p_drawdown_worse_than_threshold": float((drawdowns <= self.drawdown_threshold).mean()),
            "drawdown_threshold": self.drawdown_threshold,
            "median_max_drawdown": float(np.median(drawdowns)),
            "worst_max_drawdown": float(drawdowns.min()),
            "sharpe_invariant_to_permutation": _per_period_sharpe(arr),
        }


@dataclass(frozen=True, slots=True)
class BlockBootstrapTest:
    """Circular block bootstrap (same block-length convention as
    ``analytics.metrics._block_bootstrap_ci``: block ~ sqrt(n)), resampling
    WITH replacement -- unlike the two tests above, this changes the
    return series' composition, so both drawdown and Sharpe are genuine
    distributions here, not a single invariant value."""

    drawdown_threshold: float = DEFAULT_DRAWDOWN_THRESHOLD

    @property
    def name(self) -> str:
        return "block_bootstrap"

    def run(
        self, returns: Sequence[float], rng: np.random.Generator, n_iterations: int
    ) -> dict[str, float]:
        arr = _validated_array(returns, n_iterations)
        n = len(arr)
        block = max(1, int(np.sqrt(n)))
        n_blocks = -(-n // block)
        drawdowns = np.empty(n_iterations)
        sharpes = np.empty(n_iterations)
        for i in range(n_iterations):
            starts = rng.integers(0, n, size=n_blocks)
            idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n] % n
            sample = arr[idx]
            drawdowns[i] = _max_drawdown_from_returns(sample)
            sharpes[i] = _per_period_sharpe(sample)
        return {
            "p_drawdown_worse_than_threshold": float((drawdowns <= self.drawdown_threshold).mean()),
            "drawdown_threshold": self.drawdown_threshold,
            "median_max_drawdown": float(np.median(drawdowns)),
            "worst_max_drawdown": float(drawdowns.min()),
            "median_sharpe": float(np.median(sharpes)),
            "p_sharpe_lt_0": float((sharpes < 0).mean()),
        }
