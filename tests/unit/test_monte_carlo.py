"""Monte Carlo resampling tests (ADR-0017).

Reference values were computed independently (a standalone script, not
this module) with the exact same seed/algorithm, then hardcoded."""

from __future__ import annotations

import numpy as np
import pytest

from crucible.core.errors import ConfigurationError
from crucible.validation.monte_carlo import (
    BlockBootstrapTest,
    ReturnOrderShuffleTest,
    StartDateShiftTest,
)

_RETURNS = [0.02, -0.01, 0.03, -0.05, 0.01, 0.02, -0.03, 0.04, -0.02, 0.01]
_THRESHOLD = -0.03


def test_return_order_shuffle_matches_hand_computed_reference() -> None:
    test = ReturnOrderShuffleTest(drawdown_threshold=_THRESHOLD)
    assert test.name == "return_order_shuffle"
    result = test.run(_RETURNS, np.random.default_rng(7), n_iterations=5)
    assert result["p_drawdown_worse_than_threshold"] == pytest.approx(1.0)
    assert result["median_max_drawdown"] == pytest.approx(-0.07896071314000012)
    assert result["worst_max_drawdown"] == pytest.approx(-0.08771500000000013)
    assert result["sharpe_invariant_to_permutation"] == pytest.approx(0.06993786061802351)


def test_start_date_shift_matches_hand_computed_reference() -> None:
    test = StartDateShiftTest(drawdown_threshold=_THRESHOLD)
    assert test.name == "start_date_shift"
    result = test.run(_RETURNS, np.random.default_rng(7), n_iterations=5)
    assert result["p_drawdown_worse_than_threshold"] == pytest.approx(1.0)
    assert result["median_max_drawdown"] == pytest.approx(-0.05000000000000009)
    assert result["worst_max_drawdown"] == pytest.approx(-0.050670700000000075)
    assert result["sharpe_invariant_to_permutation"] == pytest.approx(0.06993786061802351)


def test_block_bootstrap_matches_hand_computed_reference() -> None:
    test = BlockBootstrapTest(drawdown_threshold=_THRESHOLD)
    assert test.name == "block_bootstrap"
    result = test.run(_RETURNS, np.random.default_rng(7), n_iterations=5)
    assert result["p_drawdown_worse_than_threshold"] == pytest.approx(1.0)
    assert result["median_max_drawdown"] == pytest.approx(-0.05174843354260486)
    assert result["worst_max_drawdown"] == pytest.approx(-0.059690000000000014)
    assert result["median_sharpe"] == pytest.approx(-0.032949132854301705)
    assert result["p_sharpe_lt_0"] == pytest.approx(0.6)


@pytest.mark.parametrize("cls", [ReturnOrderShuffleTest, StartDateShiftTest, BlockBootstrapTest])
def test_rejects_too_few_return_observations(cls: type) -> None:
    test = cls()
    with pytest.raises(ConfigurationError, match="need >= 3"):
        test.run([0.01, 0.02], np.random.default_rng(0), n_iterations=5)


@pytest.mark.parametrize("cls", [ReturnOrderShuffleTest, StartDateShiftTest, BlockBootstrapTest])
def test_rejects_zero_iterations(cls: type) -> None:
    test = cls()
    with pytest.raises(ConfigurationError, match="n_iterations"):
        test.run(_RETURNS, np.random.default_rng(0), n_iterations=0)


def test_shuffle_and_shift_report_a_single_invariant_sharpe_not_a_distribution() -> None:
    # Both are permutations of the same multiset of returns, so
    # mean/std -- and therefore per-period Sharpe -- can't vary between
    # iterations; only the drawdown path does. This is a mathematical
    # property, not a coincidence of the reference data above.
    shuffle_result = ReturnOrderShuffleTest().run(_RETURNS, np.random.default_rng(1), 10)
    shift_result = StartDateShiftTest().run(_RETURNS, np.random.default_rng(1), 10)
    expected_sharpe = np.array(_RETURNS).mean() / np.array(_RETURNS).std(ddof=1)
    assert shuffle_result["sharpe_invariant_to_permutation"] == pytest.approx(expected_sharpe)
    assert shift_result["sharpe_invariant_to_permutation"] == pytest.approx(expected_sharpe)


def test_block_bootstrap_sharpe_genuinely_varies_across_seeds() -> None:
    # Unlike shuffle/shift, block bootstrap resamples WITH replacement, so
    # different seeds should (almost certainly) produce different median
    # Sharpe values -- confirming it isn't silently invariant too.
    test = BlockBootstrapTest()
    a = test.run(_RETURNS, np.random.default_rng(1), 20)
    b = test.run(_RETURNS, np.random.default_rng(2), 20)
    assert a["median_sharpe"] != b["median_sharpe"]
