"""The shared Sharpe estimator and its degenerate-series guard (2026-10 audit)."""

from __future__ import annotations

import numpy as np
import pytest

from crucible.core.stats import is_degenerate_returns, per_period_sharpe


def test_a_series_with_dispersion_is_scored_normally() -> None:
    returns = np.array([0.01, -0.005, 0.02, 0.0, -0.01, 0.015])
    assert not is_degenerate_returns(returns)
    assert per_period_sharpe(returns) == pytest.approx(returns.mean() / returns.std(ddof=1))


@pytest.mark.parametrize(
    "returns",
    [
        np.zeros(10),
        np.full(10, 0.001),  # exact constant
        np.array([0.001] * 10) * (1.0 + np.linspace(-1e-16, 1e-16, 10)),  # float dust only
        np.array([]),
        np.array([0.01, np.nan, 0.02]),
        np.array([0.01, np.inf]),
    ],
)
def test_a_series_without_dispersion_has_no_sharpe(returns: np.ndarray) -> None:
    assert is_degenerate_returns(returns)
    assert per_period_sharpe(returns) == 0.0


def test_compounded_constant_returns_are_degenerate() -> None:
    """What the engine actually produces: equity * 1.001 every bar, so each simple return is
    exactly 0.001 in decimal but not bit-identical after the division."""
    equity = np.array([100.0 * 1.001**i for i in range(500)])
    returns = equity[1:] / equity[:-1] - 1.0
    assert returns.std(ddof=1) < 1e-15
    assert is_degenerate_returns(returns)
