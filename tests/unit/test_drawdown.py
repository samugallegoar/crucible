"""Maximum drawdown: one definition, starting value included (ADR-0071). Expected values are
hand-computed."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from crucible.analytics import metrics
from crucible.core.drawdown import max_drawdown, max_drawdown_from_returns
from crucible.core.errors import CrucibleError
from crucible.validation.monte_carlo import StartDateShiftTest


def test_a_first_period_loss_counts() -> None:
    # regression: cumprod(1 + r) without the starting 1.0 gave [0.9, 0.99], peak 0.9 -> 0 %
    assert max_drawdown_from_returns([-0.10, 0.10]) == pytest.approx(-0.10)


def test_a_gain_then_a_drawdown() -> None:
    # 1.0 -> 1.2 -> 0.9 -> 1.08: peak 1.2, trough 0.9 -> -25 %
    assert max_drawdown_from_returns([0.20, -0.25, 0.20]) == pytest.approx(-0.25)


def test_the_maximum_at_the_initial_capital() -> None:
    # 1.0 -> 0.95 -> 0.855 -> 0.9405: never back above 1.0, trough 0.855 -> -14.5 %
    assert max_drawdown_from_returns([-0.05, -0.10, 0.10]) == pytest.approx(-0.145)


def test_a_monotonic_increasing_path_has_no_drawdown() -> None:
    assert max_drawdown_from_returns([0.01, 0.02, 0.0, 0.03]) == 0.0


def test_empty_and_single_element_series() -> None:
    assert max_drawdown_from_returns([]) == 0.0  # the path [1.0]
    assert max_drawdown_from_returns([-0.3]) == pytest.approx(-0.3)
    assert max_drawdown_from_returns([0.3]) == 0.0
    assert max_drawdown([100.0]) == 0.0


@pytest.mark.parametrize(
    "returns",
    [[0.1, float("nan")], [float("inf")], [-1.0, 0.1], [0.2, -1.5]],
    ids=["nan", "inf", "minus-100pct", "beyond-ruin"],
)
def test_invalid_returns_are_refused(returns: list[float]) -> None:
    with pytest.raises(CrucibleError):
        max_drawdown_from_returns(returns)


@pytest.mark.parametrize("equity", [[], [100.0, float("nan")], [100.0, 0.0], [100.0, -5.0]])
def test_invalid_equity_is_refused(equity: list[float]) -> None:
    with pytest.raises(CrucibleError):
        max_drawdown(equity)


def test_the_point_estimate_and_the_resample_statistic_agree_on_the_same_path() -> None:
    rng = np.random.default_rng(3)
    for _ in range(50):
        returns = rng.normal(0.0, 0.02, 40)
        equity = 1000.0 * np.concatenate(([1.0], np.cumprod(1.0 + returns)))
        assert max_drawdown(equity) == pytest.approx(max_drawdown_from_returns(returns))


def test_compute_metrics_brackets_its_own_point_estimate_with_a_first_period_loss() -> None:
    # a curve whose deepest point is the first period's loss: the old bootstrap statistic could
    # not see it, so the interval sat above the point estimate it was printed next to
    values = [100.0, 80.0, 84.0, 88.2, 92.6, 97.2, 98.0, 99.0, 99.5, 99.9]
    equity = pl.DataFrame({"ts": list(range(len(values))), "equity": values})
    trades = pl.DataFrame({"pnl": [1.0]})
    out = metrics.compute_metrics(
        equity, trades, rng=np.random.default_rng(0), periods_per_year=252.0
    )
    dd = out["max_drawdown"]
    assert dd.value == pytest.approx(-0.20)
    assert dd.ci_low is not None
    assert dd.ci_low <= dd.value  # some resamples are at least as deep as the real path


def test_monte_carlo_shift_sees_the_first_period_loss() -> None:
    # a rotation that starts on the -50 % return must report -50 %, not 0 %
    result = StartDateShiftTest(drawdown_threshold=-0.40).run(
        [-0.5, 0.01, 0.01], np.random.default_rng(0), 50
    )
    assert result["worst_max_drawdown"] == pytest.approx(-0.5)
