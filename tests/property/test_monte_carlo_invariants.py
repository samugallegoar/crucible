"""Property: shuffle/shift Sharpe is exactly the returns' own per-period
Sharpe regardless of seed (a mathematical consequence of permutation
invariance, ADR-0017), and every reported drawdown is <= 0 for all three
Monte Carlo tests."""

from __future__ import annotations

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from crucible.validation.monte_carlo import (
    BlockBootstrapTest,
    ReturnOrderShuffleTest,
    StartDateShiftTest,
)

_returns_strategy = st.lists(
    st.floats(min_value=-0.2, max_value=0.2, allow_nan=False, allow_infinity=False),
    min_size=3,
    max_size=30,
).filter(lambda rs: np.std(rs, ddof=1) > 1e-9)  # avoid the degenerate zero-variance case


@given(returns=_returns_strategy, seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_shuffle_sharpe_matches_the_returns_own_sharpe_for_any_seed(
    returns: list[float], seed: int
) -> None:
    arr = np.array(returns)
    expected = float(arr.mean() / arr.std(ddof=1))
    result = ReturnOrderShuffleTest().run(returns, np.random.default_rng(seed), n_iterations=5)
    assert result["sharpe_invariant_to_permutation"] == expected


@given(returns=_returns_strategy, seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_shift_sharpe_matches_the_returns_own_sharpe_for_any_seed(
    returns: list[float], seed: int
) -> None:
    arr = np.array(returns)
    expected = float(arr.mean() / arr.std(ddof=1))
    result = StartDateShiftTest().run(returns, np.random.default_rng(seed), n_iterations=5)
    assert result["sharpe_invariant_to_permutation"] == expected


@given(returns=_returns_strategy, seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_every_drawdown_stat_is_non_positive(returns: list[float], seed: int) -> None:
    for cls in (ReturnOrderShuffleTest, StartDateShiftTest, BlockBootstrapTest):
        result = cls().run(returns, np.random.default_rng(seed), n_iterations=5)
        assert result["median_max_drawdown"] <= 0.0
        assert result["worst_max_drawdown"] <= 0.0
        assert result["worst_max_drawdown"] <= result["median_max_drawdown"]
