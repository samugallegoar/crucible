"""Round-trip builder: FIFO matching, hand-computed PnL."""

from __future__ import annotations

import pytest

from crucible.analytics.trades import build_trades
from crucible.core.errors import CrucibleError


def _fill(
    ts: int,
    symbol: str,
    side: str,
    qty: str,
    price: float,
    multiplier: str = "1",
    fx_to_base: str = "1",
    currency: str = "USD",
) -> dict[str, object]:
    return {
        "ts": ts,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
        "currency": currency,
        "multiplier": multiplier,
        "fx_to_base": fx_to_base,
    }


def test_simple_round_trip() -> None:
    trades = build_trades(
        [_fill(1, "AAA", "buy", "10", 100.0), _fill(5, "AAA", "sell", "10", 110.0)]
    )
    assert trades.height == 1
    row = trades.row(0, named=True)
    assert row["pnl"] == 100.0  # (110-100)*10
    assert row["side"] == "long"
    assert row["holding_ns"] == 4


def test_fifo_partial_exits() -> None:
    trades = build_trades(
        [
            _fill(1, "AAA", "buy", "10", 100.0),
            _fill(2, "AAA", "buy", "10", 102.0),
            _fill(3, "AAA", "sell", "15", 105.0),
        ]
    )
    # FIFO: 10 from the first lot (+50), 5 from the second (+15)
    assert trades.height == 2
    assert sorted(trades.get_column("pnl").to_list()) == [15.0, 50.0]


def test_short_round_trip() -> None:
    trades = build_trades([_fill(1, "AAA", "sell", "5", 100.0), _fill(9, "AAA", "buy", "5", 90.0)])
    row = trades.row(0, named=True)
    assert row["side"] == "short"
    assert row["pnl"] == 50.0  # (100-90)*5


def test_open_positions_produce_no_trades() -> None:
    trades = build_trades([_fill(1, "AAA", "buy", "10", 100.0)])
    assert trades.height == 0


def test_empty_input_yields_typed_empty_frame() -> None:
    trades = build_trades([])
    assert trades.height == 0
    assert "pnl" in trades.columns


def test_a_base_currency_trade_has_no_fx_component() -> None:
    trades = build_trades(
        [_fill(1, "AAA", "buy", "10", 100.0), _fill(5, "AAA", "sell", "10", 110.0)]
    )
    row = trades.row(0, named=True)
    assert row["pnl_fx"] == 0.0
    assert row["pnl_price"] == row["pnl"] == 100.0
    assert row["currency"] == "USD"
    assert row["multiplier"] == 1.0


def test_a_foreign_currency_long_splits_into_price_and_fx() -> None:
    """BUY 10 EEE @ 50 EUR at fx 1.10, SELL 10 @ 60 at fx 1.20:
    pnl = 10 * (60 * 1.20 - 50 * 1.10) = 10 * (72 - 55) = 170;
    pnl_price = 10 * (60 - 50) * 1.10 = 110; pnl_fx = 10 * 60 * (1.20 - 1.10) = 60."""
    trades = build_trades(
        [
            _fill(1, "EEE", "buy", "10", 50.0, fx_to_base="1.1", currency="EUR"),
            _fill(5, "EEE", "sell", "10", 60.0, fx_to_base="1.2", currency="EUR"),
        ]
    )
    row = trades.row(0, named=True)
    assert row["pnl"] == pytest.approx(170.0)
    assert row["pnl_price"] == pytest.approx(110.0)
    assert row["pnl_fx"] == pytest.approx(60.0)
    assert row["pnl_price"] + row["pnl_fx"] == pytest.approx(row["pnl"])
    assert row["currency"] == "EUR"


def test_a_short_in_a_foreign_currency_splits_with_the_short_sign() -> None:
    """SELL 5 @ 100 at fx 1.0, BUY 5 @ 90 at fx 1.1 (direction -1):
    pnl = -5 * (90 * 1.1 - 100 * 1.0) = -5 * (99 - 100) = 5;
    pnl_price = -5 * (90 - 100) * 1.0 = 50; pnl_fx = -5 * 90 * (1.1 - 1.0) = -45."""
    trades = build_trades(
        [
            _fill(1, "EEE", "sell", "5", 100.0, fx_to_base="1", currency="EUR"),
            _fill(9, "EEE", "buy", "5", 90.0, fx_to_base="1.1", currency="EUR"),
        ]
    )
    row = trades.row(0, named=True)
    assert row["pnl"] == pytest.approx(5.0)
    assert row["pnl_price"] == pytest.approx(50.0)
    assert row["pnl_fx"] == pytest.approx(-45.0)


def test_a_futures_round_trip_is_scaled_by_the_multiplier() -> None:
    # 2 contracts, +10 points, multiplier 50: 2 * 50 * 10 = 1000
    trades = build_trades(
        [
            _fill(1, "ES", "buy", "2", 4000.0, multiplier="50"),
            _fill(5, "ES", "sell", "2", 4010.0, multiplier="50"),
        ]
    )
    row = trades.row(0, named=True)
    assert row["pnl"] == pytest.approx(1000.0)
    assert row["multiplier"] == 50.0
    assert row["pnl_fx"] == 0.0


def test_old_schema_fill_rows_are_refused_with_the_missing_columns() -> None:
    old = {"ts": 1, "symbol": "AAA", "side": "buy", "qty": "1", "price": 10.0}
    with pytest.raises(CrucibleError, match=r"currency.*fx_to_base.*multiplier"):
        build_trades([old])


def test_the_split_matches_pnl_to_float_precision_on_awkward_rates() -> None:
    """Each component is derived in Decimal (pnl_fx = pnl - pnl_price), so the float
    columns differ from pnl by at most float rounding, never by Decimal rounding."""
    import math

    trades = build_trades(
        [
            _fill(1, "EEE", "buy", "7", 75.84, fx_to_base="1.26377", currency="EUR"),
            _fill(9, "EEE", "sell", "7", 425.24, fx_to_base="0.75507", currency="EUR"),
        ]
    )
    row = trades.row(0, named=True)
    assert math.isclose(row["pnl_price"] + row["pnl_fx"], row["pnl"], rel_tol=1e-15)
