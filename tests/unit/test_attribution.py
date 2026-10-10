"""Per-strategy attribution against hand-computed values (ADR-0030)."""

from __future__ import annotations

import math

import pytest

from crucible.analytics.attribution import (
    UNATTRIBUTED,
    marginal_risk_contribution,
    per_strategy_pnl_deltas,
    strategy_correlation,
)
from crucible.core.errors import CrucibleError


def _fill(
    ts: int,
    side: str,
    qty: str,
    price: float,
    commission: str,
    strategy_id: str | None,
    multiplier: str = "1",
    fx_to_base: str = "1",
):
    return {
        "ts": ts,
        "side": side,
        "qty": qty,
        "price": price,
        "commission": commission,
        "strategy_id": strategy_id,
        "currency": "USD",
        "multiplier": multiplier,
        "fx_to_base": fx_to_base,
    }


# --------------------------------------------------------- per_strategy_pnl_deltas


def test_per_strategy_pnl_deltas_buckets_by_period_and_strategy() -> None:
    # period 0 (ts<=1): A buys 10@100 (comm 1) -> -1001; B buys 5@50 (comm 0.5) -> -250.5
    # period 1 (1<ts<=2): A sells 10@110 (comm 1) -> +1099; B sells 5@40 (comm 0.5) -> +199.5;
    #   an untagged fill buys 1@10 (comm 0) -> -10
    fills = [
        _fill(1, "buy", "10", 100.0, "1", "A"),
        _fill(1, "buy", "5", 50.0, "0.5", "B"),
        _fill(2, "sell", "10", 110.0, "1", "A"),
        _fill(2, "sell", "5", 40.0, "0.5", "B"),
        _fill(2, "buy", "1", 10.0, "0", None),
    ]
    result = per_strategy_pnl_deltas(fills, period_ts=[1, 2])

    assert result.columns == ["ts", "A", "B", UNATTRIBUTED]
    row0 = result.row(0, named=True)
    assert row0["ts"] == 1
    assert row0["A"] == pytest.approx(-1001.0)
    assert row0["B"] == pytest.approx(-250.5)
    assert row0[UNATTRIBUTED] == pytest.approx(0.0)
    row1 = result.row(1, named=True)
    assert row1["ts"] == 2
    assert row1["A"] == pytest.approx(1099.0)
    assert row1["B"] == pytest.approx(199.5)
    assert row1[UNATTRIBUTED] == pytest.approx(-10.0)


def test_per_strategy_pnl_deltas_fills_untraded_periods_with_zero() -> None:
    fills = [_fill(1, "buy", "1", 100.0, "0", "A")]
    result = per_strategy_pnl_deltas(fills, period_ts=[1, 2, 3])
    assert result.get_column("A").to_list() == [pytest.approx(-100.0), 0.0, 0.0]


def test_per_strategy_pnl_deltas_empty_fills_returns_ts_only() -> None:
    result = per_strategy_pnl_deltas([], period_ts=[1, 2])
    assert result.columns == ["ts"]
    assert result.get_column("ts").to_list() == [1, 2]


def test_per_strategy_pnl_deltas_rejects_fill_beyond_last_period() -> None:
    fills = [_fill(5, "buy", "1", 100.0, "0", "A")]
    with pytest.raises(CrucibleError, match="after the last period_ts"):
        per_strategy_pnl_deltas(fills, period_ts=[1, 2])


def test_per_strategy_pnl_deltas_rejects_empty_period_ts() -> None:
    with pytest.raises(CrucibleError, match="non-empty"):
        per_strategy_pnl_deltas([_fill(1, "buy", "1", 1.0, "0", "A")], period_ts=[])


# ------------------------------------------------------------- strategy_correlation


def test_strategy_correlation_perfectly_correlated() -> None:
    fills = [
        _fill(1, "sell", "1", 1.0, "0", "A"),
        _fill(1, "sell", "2", 1.0, "0", "B"),
        _fill(2, "sell", "2", 1.0, "0", "A"),
        _fill(2, "sell", "4", 1.0, "0", "B"),
        _fill(3, "sell", "3", 1.0, "0", "A"),
        _fill(3, "sell", "6", 1.0, "0", "B"),
    ]
    deltas = per_strategy_pnl_deltas(fills, period_ts=[1, 2, 3])
    corr = strategy_correlation(deltas)
    ab = corr.filter((corr["strategy_id"] == "A") & (corr["other_id"] == "B")).row(0, named=True)
    assert ab["correlation"] == pytest.approx(1.0)


def test_strategy_correlation_perfectly_anticorrelated() -> None:
    fills = [
        _fill(1, "sell", "1", 1.0, "0", "A"),
        _fill(1, "sell", "3", 1.0, "0", "B"),
        _fill(2, "sell", "2", 1.0, "0", "A"),
        _fill(2, "sell", "2", 1.0, "0", "B"),
        _fill(3, "sell", "3", 1.0, "0", "A"),
        _fill(3, "sell", "1", 1.0, "0", "B"),
    ]
    deltas = per_strategy_pnl_deltas(fills, period_ts=[1, 2, 3])
    corr = strategy_correlation(deltas)
    ab = corr.filter((corr["strategy_id"] == "A") & (corr["other_id"] == "B")).row(0, named=True)
    assert ab["correlation"] == pytest.approx(-1.0)
    aa = corr.filter((corr["strategy_id"] == "A") & (corr["other_id"] == "A")).row(0, named=True)
    assert aa["correlation"] == pytest.approx(1.0)


def test_strategy_correlation_rejects_fewer_than_two_strategies() -> None:
    fills = [_fill(1, "sell", "1", 1.0, "0", "A"), _fill(2, "sell", "1", 1.0, "0", "A")]
    deltas = per_strategy_pnl_deltas(fills, period_ts=[1, 2])
    with pytest.raises(CrucibleError, match="need >= 2 strategies"):
        strategy_correlation(deltas)


# ------------------------------------------------------ marginal_risk_contribution


def test_marginal_risk_contribution_hand_computed() -> None:
    # A pnl deltas [1,2,3] (mean 2), B pnl deltas [1,1,4] (mean 2)
    # portfolio = [2,3,7] (mean 4); var(portfolio, ddof=1) = 7, sd = sqrt(7)
    # cov(A,portfolio)=2.5 -> MRC_A = 2.5/sqrt(7)
    # cov(B,portfolio)=4.5 -> MRC_B = 4.5/sqrt(7)
    fills = [
        _fill(1, "sell", "1", 1.0, "0", "A"),
        _fill(1, "sell", "1", 1.0, "0", "B"),
        _fill(2, "sell", "2", 1.0, "0", "A"),
        _fill(2, "sell", "1", 1.0, "0", "B"),
        _fill(3, "sell", "3", 1.0, "0", "A"),
        _fill(3, "sell", "4", 1.0, "0", "B"),
    ]
    deltas = per_strategy_pnl_deltas(fills, period_ts=[1, 2, 3])
    mrc = marginal_risk_contribution(deltas)

    sqrt7 = math.sqrt(7)
    assert mrc["A"] == pytest.approx(2.5 / sqrt7)
    assert mrc["B"] == pytest.approx(4.5 / sqrt7)
    # sum-to-portfolio-SD identity (covariance decomposition of a sum)
    assert sum(mrc.values()) == pytest.approx(sqrt7)


def test_marginal_risk_contribution_zero_when_portfolio_has_no_variance() -> None:
    # A=[4,2,0], B=[0,2,4] individually vary but sum to a constant 4 each period
    fills = [
        _fill(1, "sell", "4", 1.0, "0", "A"),
        _fill(2, "sell", "2", 1.0, "0", "A"),
        _fill(3, "sell", "0", 1.0, "0", "A"),
        _fill(1, "sell", "0", 1.0, "0", "B"),
        _fill(2, "sell", "2", 1.0, "0", "B"),
        _fill(3, "sell", "4", 1.0, "0", "B"),
    ]
    deltas = per_strategy_pnl_deltas(fills, period_ts=[1, 2, 3])
    mrc = marginal_risk_contribution(deltas)
    assert mrc == {"A": 0.0, "B": 0.0}


def test_marginal_risk_contribution_rejects_single_period() -> None:
    fills = [_fill(1, "sell", "1", 1.0, "0", "A"), _fill(1, "sell", "1", 1.0, "0", "B")]
    deltas = per_strategy_pnl_deltas(fills, period_ts=[1])
    with pytest.raises(CrucibleError, match="need >= 2 periods"):
        marginal_risk_contribution(deltas)


def test_a_foreign_currency_fill_is_converted_to_base() -> None:
    # BUY 10 @ 50 EUR, commission 2 EUR, mid 1.10: (-10 * 50 - 2) * 1.10 = -552.2 USD
    fills = [_fill(1, "buy", "10", 50.0, "2", "A", fx_to_base="1.1")]
    frame = per_strategy_pnl_deltas(fills, [1])
    assert frame["A"].to_list() == pytest.approx([-552.2])


def test_a_futures_round_trip_realizes_price_move_times_multiplier() -> None:
    # BUY 2 @ 4000 x50 = -400000; SELL 2 @ 4010 x50 = +401000; net +1000 =
    # (4010 - 4000) * 2 * 50
    fills = [
        _fill(1, "buy", "2", 4000.0, "0", "A", multiplier="50"),
        _fill(2, "sell", "2", 4010.0, "0", "A", multiplier="50"),
    ]
    frame = per_strategy_pnl_deltas(fills, [1, 2])
    assert frame["A"].to_list() == pytest.approx([-400000.0, 401000.0])


def test_old_schema_fill_rows_are_refused_with_a_clear_message() -> None:
    old = {"ts": 1, "side": "buy", "qty": "1", "price": 10.0, "commission": "0", "strategy_id": "A"}
    with pytest.raises(CrucibleError, match="multiplier"):
        per_strategy_pnl_deltas([old], [1])
