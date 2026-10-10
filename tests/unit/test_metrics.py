"""Metrics: hand-checkable values, deterministic CIs, refusals."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from crucible.analytics.metrics import compute_metrics
from crucible.analytics.trades import build_trades
from crucible.core.errors import CrucibleError

DAY = 86_400 * 10**9


def _equity(values: list[float]) -> pl.DataFrame:
    return pl.DataFrame({"ts": [i * DAY for i in range(len(values))], "equity": values})


def _no_trades() -> pl.DataFrame:
    return build_trades([])


def test_flat_equity_has_zero_sharpe_and_drawdown() -> None:
    metrics = compute_metrics(
        _equity([100.0] * 10),
        _no_trades(),
        rng=np.random.default_rng(1),
        periods_per_year=252,
    )
    assert metrics["sharpe"].value == 0.0
    assert metrics["max_drawdown"].value == 0.0
    assert metrics["volatility"].value == 0.0


def test_max_drawdown_matches_hand_value() -> None:
    # peak 120 -> trough 90: drawdown = -25%
    metrics = compute_metrics(
        _equity([100.0, 120.0, 90.0, 110.0]),
        _no_trades(),
        rng=np.random.default_rng(1),
        periods_per_year=252,
    )
    assert metrics["max_drawdown"].value == pytest.approx(-0.25)


def test_cis_are_deterministic_given_seed() -> None:
    values = list(100.0 * np.cumprod(1 + np.random.default_rng(7).normal(0, 0.01, 100)))
    a = compute_metrics(
        _equity(values), _no_trades(), rng=np.random.default_rng(42), periods_per_year=252
    )
    b = compute_metrics(
        _equity(values), _no_trades(), rng=np.random.default_rng(42), periods_per_year=252
    )
    assert (a["sharpe"].ci_low, a["sharpe"].ci_high) == (b["sharpe"].ci_low, b["sharpe"].ci_high)
    assert a["sharpe"].ci_low is not None
    assert a["sharpe"].ci_high is not None
    assert a["sharpe"].ci_low <= a["sharpe"].value <= a["sharpe"].ci_high
    # max_drawdown's bootstrap CI (R4.8, ADR-0020) -- same determinism and
    # bracketing checks as sharpe's, above.
    assert (a["max_drawdown"].ci_low, a["max_drawdown"].ci_high) == (
        b["max_drawdown"].ci_low,
        b["max_drawdown"].ci_high,
    )
    assert a["max_drawdown"].ci_low is not None
    assert a["max_drawdown"].ci_high is not None
    assert a["max_drawdown"].ci_low <= a["max_drawdown"].value <= a["max_drawdown"].ci_high


def test_too_short_series_is_refused() -> None:
    with pytest.raises(CrucibleError, match="need >= 3"):
        compute_metrics(
            _equity([100.0, 101.0]),
            _no_trades(),
            rng=np.random.default_rng(1),
            periods_per_year=252,
        )


def test_ruin_is_refused() -> None:
    with pytest.raises(CrucibleError, match="ruin"):
        compute_metrics(
            _equity([100.0, 50.0, -10.0, 20.0]),
            _no_trades(),
            rng=np.random.default_rng(1),
            periods_per_year=252,
        )
