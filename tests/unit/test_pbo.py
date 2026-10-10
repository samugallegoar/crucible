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
