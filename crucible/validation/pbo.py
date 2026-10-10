"""Probability of Backtest Overfitting via Combinatorial Symmetric
Cross-Validation (Bailey, Borwein, López de Prado & Zhu 2015). Answers a different question than
DSR: DSR asks "is this one
trial's Sharpe distinguishable from search noise?"; PBO asks "if I picked
the best-looking trial in-sample, out of a panel of N trials evaluated
over the same periods, how often would that pick actually be
out-of-sample median-or-worse?" -- ADR-0015.

Requires a full trials x periods returns panel, not a single run's
returns. `crucible optimize` assembles the panel;
no report can show PBO for a single ``crucible run`` invocation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from crucible.core.errors import ConfigurationError

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from crucible.validation.splits import CombinatorialPurgedCVSplitter


@dataclass(frozen=True, slots=True)
class PboResult:
    """``pbo`` is a probability in [0, 1]: the fraction of combinatorial
    splits in which the trial that looked best in-sample performed at or
    below the out-of-sample median. Near 0: the in-sample winner tends to
    keep winning out-of-sample -- a genuine edge. Near 1 (above 0.5
    flags an overfit strategy): picking the
    in-sample winner is no better than a coin flip or worse -- selection,
    not skill."""

    pbo: float
    n_combinations: int
    n_trials: int


def _per_period_sharpe(returns: NDArray[np.float64]) -> NDArray[np.float64]:
    """Row-wise per-period Sharpe; rows with zero variance get 0.0 (same
    convention as analytics.metrics)."""
    std = returns.std(axis=1, ddof=1)
    mean = returns.mean(axis=1)
    return np.divide(mean, std, out=np.zeros_like(mean), where=std != 0.0)


def _flat_indices(ranges: tuple[tuple[int, int], ...]) -> NDArray[np.int64]:
    return np.concatenate([np.arange(start, end) for start, end in ranges])


def probability_of_backtest_overfitting(
    returns: NDArray[np.float64], splitter: CombinatorialPurgedCVSplitter
) -> PboResult:
    """``returns``: shape ``(n_trials, n_periods)``, the SAME periods for
    every trial (aligned in time). ``splitter`` partitions the period axis
    into combinatorial in-sample/out-of-sample splits; CSCV requires a
    *symmetric* split (``n_test_groups == n_groups // 2``) so every split
    has a complementary partner elsewhere in the combination set."""
    n_trials, n_periods = returns.shape
    if n_trials < 2:
        msg = f"PBO needs a panel of >= 2 trials to compare, got n_trials={n_trials}"
        raise ConfigurationError(msg)
    if splitter.n_groups % 2 != 0 or splitter.n_test_groups != splitter.n_groups // 2:
        msg = (
            "CSCV requires a symmetric splitter (n_test_groups == n_groups // 2, "
            f"n_groups even), got n_groups={splitter.n_groups}, "
            f"n_test_groups={splitter.n_test_groups}"
        )
        raise ConfigurationError(msg)

    lambdas: list[float] = []
    for split in splitter.splits(n_periods):
        train_idx = _flat_indices(split.train)
        test_idx = _flat_indices(split.test)
        is_sharpe = _per_period_sharpe(returns[:, train_idx])
        oos_sharpe = _per_period_sharpe(returns[:, test_idx])
        n_star = int(np.argmax(is_sharpe))
        rank = 1 + int(np.sum(oos_sharpe < oos_sharpe[n_star]))  # 1 (worst) .. n_trials (best)
        omega = rank / (n_trials + 1)
        lambdas.append(math.log(omega / (1.0 - omega)))

    overfit = sum(1 for lam in lambdas if lam <= 0.0)
    return PboResult(
        pbo=overfit / len(lambdas),
        n_combinations=len(lambdas),
        n_trials=n_trials,
    )
