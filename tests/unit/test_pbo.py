"""Probability of Backtest Overfitting via CSCV (Bailey, Borwein, López de
Prado, Zhu 2015; ADR-0015).

Reference values below were computed independently (a standalone script,
not this module) against the same formulas, then hardcoded."""

from __future__ import annotations

import numpy as np
import pytest

from crucible.core.errors import ConfigurationError
from crucible.validation.pbo import PboResult, probability_of_backtest_overfitting
from crucible.validation.splits import CombinatorialPurgedCVSplitter

_RETURNS = np.array(
    [
        [0.01, 0.02, -0.01, 0.03, 0.02, -0.02, 0.01, 0.04],
        [0.00, -0.01, 0.02, -0.03, 0.01, 0.03, -0.02, -0.01],
        [-0.02, 0.01, -0.03, 0.02, -0.01, -0.02, 0.03, 0.02],
    ]
)


def test_matches_hand_computed_pbo() -> None:
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2)
    result = probability_of_backtest_overfitting(_RETURNS, splitter)
    assert result.n_combinations == 6
    assert result.n_trials == 3
    assert result.pbo == pytest.approx(0.6666666666666666)


def test_result_type() -> None:
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2)
    result = probability_of_backtest_overfitting(_RETURNS, splitter)
    assert isinstance(result, PboResult)


def test_rejects_fewer_than_two_trials() -> None:
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2)
    with pytest.raises(ConfigurationError, match="n_trials"):
        probability_of_backtest_overfitting(_RETURNS[:1], splitter)


def test_rejects_an_asymmetric_splitter() -> None:
    # CSCV requires n_test_groups == n_groups // 2 (a symmetric split); a
    # 5-group / 2-test-group splitter is a valid CombinatorialPurgedCVSplitter
    # on its own but not a valid CSCV panel splitter.
    splitter = CombinatorialPurgedCVSplitter(n_groups=5, n_test_groups=2)
    with pytest.raises(ConfigurationError, match="symmetric"):
        probability_of_backtest_overfitting(_RETURNS, splitter)


def test_a_strategy_that_wins_every_split_both_ways_has_pbo_zero() -> None:
    # trial 0 dominates every period; picking it in-sample always wins
    # out-of-sample too, so no split ever counts as overfit.
    returns = np.array(
        [
            [0.05, 0.06, 0.05, 0.06, 0.05, 0.06, 0.05, 0.06],
            [0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
            [-0.05, -0.06, -0.05, -0.06, -0.05, -0.06, -0.05, -0.06],
        ]
    )
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2)
    result = probability_of_backtest_overfitting(returns, splitter)
    assert result.pbo == 0.0


# --- ties and degenerate panels (ADR-0070) -------------------------------------------------


def _reference_pbo(returns: np.ndarray, splitter: CombinatorialPurgedCVSplitter) -> float:
    """Independent reference: average the paper's logit rule over every pair of explicit
    tie-breaking orders (one for the in-sample pick, one for the out-of-sample ranking)."""
    import itertools
    import math

    n_trials = returns.shape[0]
    orders = list(itertools.permutations(range(n_trials)))
    per_split: list[float] = []
    for split in splitter.splits(returns.shape[1]):
        train = np.concatenate([np.arange(a, b) for a, b in split.train])
        test = np.concatenate([np.arange(a, b) for a, b in split.test])

        def sharpe(block: np.ndarray) -> list[float]:
            out = []
            for row in block:
                std = float(np.std(row, ddof=1))
                out.append(float(np.mean(row)) / std if std else 0.0)
            return out

        is_s, oos_s = sharpe(returns[:, train]), sharpe(returns[:, test])
        hits = 0
        for is_order in orders:
            # the pick: highest in-sample score, ties to the earlier trial in is_order
            pick = max(range(n_trials), key=lambda t: (is_s[t], -is_order.index(t)))
            for oos_order in orders:
                # strict total order on (score, tie-break position); rank 1 = worst
                key = {t: (oos_s[t], -oos_order.index(t)) for t in range(n_trials)}
                rank = 1 + sum(1 for t in range(n_trials) if key[t] < key[pick])
                omega = rank / (n_trials + 1)
                hits += int(math.log(omega / (1.0 - omega)) <= 0.0)
        per_split.append(hits / len(orders) ** 2)
    return sum(per_split) / len(per_split)


def test_identical_trials_are_a_coin_flip_not_certain_overfitting() -> None:
    # regression: a strict "<" rank put the in-sample winner last on every tie, so N identical
    # trials scored PBO = 1.0 ("always overfit") instead of describing a random pick
    row = _RETURNS[0]
    returns = np.vstack([row, row, row, row])
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2)
    result = probability_of_backtest_overfitting(returns, splitter)
    assert result.pbo == pytest.approx(0.5)  # ranks 1..4 equally likely; 1 and 2 are <= median
    assert result.n_tied_splits == result.n_combinations
    assert result.pbo == pytest.approx(_reference_pbo(returns, splitter))


def test_odd_panel_of_identical_trials_counts_the_median_as_overfit() -> None:
    # lambda <= 0 includes the median rank (the paper integrates up to and including 0)
    row = _RETURNS[0]
    returns = np.vstack([row, row, row])
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2)
    assert probability_of_backtest_overfitting(returns, splitter).pbo == pytest.approx(2 / 3)


def test_all_flat_trials_tie_everywhere() -> None:
    returns = np.zeros((3, 8))
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2)
    result = probability_of_backtest_overfitting(returns, splitter)
    assert result.pbo == pytest.approx(2 / 3)
    assert result.n_tied_splits == result.n_combinations


@pytest.mark.parametrize(
    "returns",
    [
        np.vstack([_RETURNS[0], _RETURNS[0], _RETURNS[1], _RETURNS[2]]),  # tied winners
        np.vstack([_RETURNS, _RETURNS[1:2]]),  # a duplicate of a non-winner
        _RETURNS,  # no ties
        np.vstack([_RETURNS[:2], np.zeros((2, 8))]),  # two flat trials tie at Sharpe 0
    ],
)
def test_matches_the_exhaustive_tie_break_reference(returns: np.ndarray) -> None:
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2)
    result = probability_of_backtest_overfitting(returns, splitter)
    assert result.pbo == pytest.approx(_reference_pbo(returns, splitter))


def test_duplicating_the_dominant_trial_does_not_manufacture_overfitting() -> None:
    returns = np.array(
        [
            [0.05, 0.06, 0.05, 0.06, 0.05, 0.06, 0.05, 0.06],
            [0.05, 0.06, 0.05, 0.06, 0.05, 0.06, 0.05, 0.06],
            [0.00, 0.01, -0.01, 0.00, 0.01, -0.01, 0.00, 0.01],
            [-0.05, -0.06, -0.05, -0.06, -0.05, -0.06, -0.05, -0.06],
        ]
    )
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2)
    # the two copies rank 3 and 4 out of 4 in either order: never at or below the median
    assert probability_of_backtest_overfitting(returns, splitter).pbo == 0.0


def test_in_sample_winners_that_collapse_out_of_sample_are_overfit() -> None:
    # trial i earns only in group i and loses a little elsewhere: whichever two groups are
    # in-sample, the picked trial owns one of them and has nothing left out-of-sample, where
    # the two trials that own the test groups beat it. Every split is overfit.
    good, bad = [0.04, 0.05], [-0.01, -0.012]
    returns = np.array([[r for g in range(4) for r in (good if g == i else bad)] for i in range(4)])
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2)
    result = probability_of_backtest_overfitting(returns, splitter)
    assert result.pbo == 1.0
    assert result.pbo == pytest.approx(_reference_pbo(returns, splitter))


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_rejects_non_finite_returns(bad: float) -> None:
    returns = _RETURNS.copy()
    returns[1, 3] = bad
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2)
    with pytest.raises(ConfigurationError, match=r"trial\(s\) \[1\]"):
        probability_of_backtest_overfitting(returns, splitter)


def test_rejects_constant_non_zero_returns() -> None:
    returns = np.vstack([_RETURNS, np.full(8, 0.001)])
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2)
    with pytest.raises(ConfigurationError, match="undefined"):
        probability_of_backtest_overfitting(returns, splitter)


def test_rejects_partitions_too_short_for_a_sharpe() -> None:
    # with test groups {1, 3}, a purge of 1 leaves a single in-sample observation
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2, purge=1)
    with pytest.raises(ConfigurationError, match="observation"):
        probability_of_backtest_overfitting(_RETURNS, splitter)


def test_is_deterministic() -> None:
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2)
    first = probability_of_backtest_overfitting(_RETURNS, splitter)
    assert first == probability_of_backtest_overfitting(_RETURNS.copy(), splitter)
