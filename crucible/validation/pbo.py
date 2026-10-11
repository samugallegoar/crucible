"""Probability of Backtest Overfitting via Combinatorial Symmetric
Cross-Validation (Bailey, Borwein, López de Prado & Zhu 2015). Answers a different question than
DSR: DSR asks "is this one
trial's Sharpe distinguishable from search noise?"; PBO asks "if I picked
the best-looking trial in-sample, out of a panel of N trials evaluated
over the same periods, how often would that pick actually be
out-of-sample median-or-worse?" -- ADR-0015.

Rank convention (ADR-0070): within each split the selected trial's out-of-sample
rank runs from 1 (worst) to N (best), its relative rank is ``omega = rank / (N + 1)``
and the logit ``lambda = log(omega / (1 - omega))``; a split counts as overfit when
``lambda <= 0``, i.e. ``2 * rank <= N + 1`` (the paper integrates the logit density
up to and including 0). The comparison is done on the integer rank, so no logarithm
is ever taken and ``omega`` is never 0 or 1.

Ties are resolved by expectation, not by array position: when several trials share
the best in-sample score the selection is a uniformly random pick among them, and
when the selected trial's out-of-sample score ties others its rank is uniform over
the tied block. Each split contributes the probability that it is overfit under that
random tie-breaking, a number in [0, 1]. A panel of identical trials therefore gets a
PBO of about 0.5 (selection is a coin flip), not 1.0, which a strict ``<`` count gave.

Requires a full trials x periods returns panel, not a single run's
returns. `crucible optimize` assembles the panel;
no report can show PBO for a single ``crucible run`` invocation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from crucible.core.errors import ConfigurationError

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from crucible.validation.splits import CombinatorialPurgedCVSplitter

MIN_OBSERVATIONS_PER_PARTITION = 2
"""A per-period Sharpe needs a sample standard deviation (``ddof=1``), so two observations."""


@dataclass(frozen=True, slots=True)
class PboResult:
    """``pbo`` is a probability in [0, 1]: the fraction of combinatorial
    splits in which the trial that looked best in-sample performed at or
    below the out-of-sample median. Near 0: the in-sample winner tends to
    keep winning out-of-sample -- a genuine edge. Near 1 (above 0.5
    flags an overfit strategy): picking the
    in-sample winner is no better than a coin flip or worse -- selection,
    not skill.

    ``n_tied_splits`` counts the splits whose outcome depended on a tie (several
    in-sample winners, or the winner's out-of-sample score shared with another
    trial); those splits contribute their expected value under random tie-breaking.
    When every split is tied the panel cannot tell its trials apart and ``pbo``
    describes a random pick, not the strategies."""

    pbo: float
    n_combinations: int
    n_trials: int
    n_tied_splits: int = 0


def _per_period_sharpe(returns: NDArray[np.float64]) -> NDArray[np.float64]:
    """Row-wise per-period Sharpe. A row with zero variance and a zero mean (a trial
    that held nothing in this partition) scores 0.0, the same convention as
    analytics.metrics; zero variance with a non-zero mean has no finite Sharpe and is
    refused by the caller."""
    constant = _constant_rows(returns)
    std = np.where(constant, 0.0, returns.std(axis=1, ddof=1))
    mean = np.where(constant, returns[:, 0], returns.mean(axis=1))
    return np.divide(mean, std, out=np.zeros_like(mean), where=std != 0.0)


def _constant_rows(returns: NDArray[np.float64]) -> NDArray[np.bool_]:
    """Rows whose values are all identical. Tested exactly: the float standard deviation of a
    constant row is ~1e-19, not 0, and would give a Sharpe ratio of ~1e16."""
    return np.all(returns == returns[:, :1], axis=1)


def _flat_indices(ranges: tuple[tuple[int, int], ...]) -> NDArray[np.int64]:
    return np.concatenate([np.arange(start, end) for start, end in ranges])


def _check_partition(returns: NDArray[np.float64], label: str) -> None:
    n_obs = returns.shape[1]
    if n_obs < MIN_OBSERVATIONS_PER_PARTITION:
        msg = (
            f"a CSCV {label} partition has {n_obs} observation(s); a Sharpe needs >= "
            f"{MIN_OBSERVATIONS_PER_PARTITION}. Use fewer groups or a longer panel"
        )
        raise ConfigurationError(msg)
    undefined = np.flatnonzero(_constant_rows(returns) & (returns[:, 0] != 0.0))
    if undefined.size:
        msg = (
            f"trial(s) {undefined.tolist()} have constant non-zero returns in a CSCV {label} "
            "partition: their Sharpe ratio is undefined (zero variance), so they cannot be "
            "ranked. Remove them from the panel or lengthen the partitions"
        )
        raise ConfigurationError(msg)


def overfit_probability(is_scores: NDArray[np.float64], oos_scores: NDArray[np.float64]) -> float:
    """Probability, under uniform random tie-breaking, that the in-sample winner
    ranks at or below the out-of-sample median (``2 * rank <= N + 1``)."""
    n_trials = len(is_scores)
    winners = np.flatnonzero(is_scores == is_scores.max())
    total = 0.0
    for winner in winners:
        score = oos_scores[winner]
        below = int(np.sum(oos_scores < score))
        tied = int(np.sum(oos_scores == score))  # includes the winner itself
        ranks = np.arange(below + 1, below + tied + 1)
        total += float(np.mean(2 * ranks <= n_trials + 1))
    return total / len(winners)


def _is_tied(is_scores: NDArray[np.float64], oos_scores: NDArray[np.float64]) -> bool:
    winners = np.flatnonzero(is_scores == is_scores.max())
    if winners.size > 1:
        return True
    return int(np.sum(oos_scores == oos_scores[winners[0]])) > 1


def probability_of_backtest_overfitting(
    returns: NDArray[np.float64], splitter: CombinatorialPurgedCVSplitter
) -> PboResult:
    """``returns``: shape ``(n_trials, n_periods)``, the SAME periods for
    every trial (aligned in time). ``splitter`` partitions the period axis
    into combinatorial in-sample/out-of-sample splits; CSCV requires a
    *symmetric* split (``n_test_groups == n_groups // 2``) so every split
    has a complementary partner elsewhere in the combination set. Selection uses
    only each split's in-sample columns. Non-finite returns, partitions shorter than
    two observations and constant non-zero rows are refused (ADR-0070)."""
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
    if not np.all(np.isfinite(returns)):
        bad = sorted({int(i) for i in np.argwhere(~np.isfinite(returns))[:, 0]})
        msg = (
            f"PBO panel has NaN or infinite returns in trial(s) {bad}; a Sharpe ratio of a "
            "series with missing values is undefined. Align the trials on periods where every "
            "trial has a finite return"
        )
        raise ConfigurationError(msg)

    overfit: list[float] = []
    n_tied = 0
    for split in splitter.splits(n_periods):
        train = returns[:, _flat_indices(split.train)]
        test = returns[:, _flat_indices(split.test)]
        _check_partition(train, "in-sample")
        _check_partition(test, "out-of-sample")
        is_sharpe = _per_period_sharpe(train)
        oos_sharpe = _per_period_sharpe(test)
        overfit.append(overfit_probability(is_sharpe, oos_sharpe))
        n_tied += int(_is_tied(is_sharpe, oos_sharpe))

    return PboResult(
        pbo=float(sum(overfit) / len(overfit)),
        n_combinations=len(overfit),
        n_trials=n_trials,
        n_tied_splits=n_tied,
    )
