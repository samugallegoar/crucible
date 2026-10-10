"""The multi-currency equity loop of the vectorized engine (ADR-0062).

Hand computation, USD base, one EUR symbol B, initial cash 1000, no costs, four aligned bars:
close (EUR)   100    110    99     99
fx (EURUSD)   1.00   1.10   1.10   1.21
weight         0      1      1      0      (lagged: the weight in force over the bar)
Positions are funded in EUR (the event-driven convention): local pnl U accumulates q * dP and
equity = 1000 + fx * U.
t0: U=0, E=1000; set q = w[1]*E/(P*fx) = 1*1000/(100*1.0) = 10
t1: U = 10*(110-100) = 100; E = 1000 + 1.1*100 = 1110; q = 1110/(110*1.1) = 1110/121
t2: U = 100 + (1110/121)*(99-110) = 100 - 1110/11 = -10/11; E = 1000 + 1.1*(-10/11) = 999.0; q = 0
t3: U unchanged; E = 1000 + 1.21*(-10/11) = 998.9   (FX moves only the accumulated pnl)
Per-bar gross pnl: t1 = 10*10*1.1 + 0*0.1 = 110; t2 = (1110/121)*(-11)*1.1 + 100*0 = -111;
t3 = 0 + (-10/11)*(1.21-1.10) = -0.1 (they sum to E[t]-E[t-1]).
"""

from __future__ import annotations

import numpy as np
import pytest

from crucible.vectorized.fx import run_fx_equity


def _column(values: list[float]) -> np.ndarray:
    return np.array(values, dtype=np.float64).reshape(-1, 1)


def test_hand_computed_eur_symbol_funded_in_euros() -> None:
    equity, pnl = run_fx_equity(
        close=_column([100, 110, 99, 99]),
        weight=_column([0, 1, 1, 0]),
        fx=_column([1.0, 1.1, 1.1, 1.21]),
        initial_cash=1000.0,
        cost_rate=0.0,
    )
    assert equity == pytest.approx([1000.0, 1110.0, 999.0, 998.9])
    assert pnl[:, 0] == pytest.approx([0.0, 110.0, -111.0, -0.1])


def test_a_flat_position_is_not_exposed_to_the_rate() -> None:
    equity, pnl = run_fx_equity(
        close=_column([100, 101, 102, 103]),
        weight=_column([0, 0, 0, 0]),
        fx=_column([1.0, 2.0, 0.5, 3.0]),
        initial_cash=1000.0,
        cost_rate=0.0,
    )
    assert equity == pytest.approx([1000.0] * 4)
    assert not pnl.any()


def test_a_new_position_has_no_principal_exposure_to_the_rate() -> None:
    # open at t0 (q = 1*1000/(100*1.0) = 10), the rate doubles at t1 with the price flat: no pnl
    equity, _ = run_fx_equity(
        close=_column([100, 100]),
        weight=_column([0, 1]),
        fx=_column([1.0, 2.0]),
        initial_cash=1000.0,
        cost_rate=0.0,
    )
    assert equity == pytest.approx([1000.0, 1000.0])


def test_costs_are_the_turnover_rate_on_prior_equity_taken_from_base_cash() -> None:
    # weights 0, 1, 0 and a 10 bps rate: cost at t1 = 0.001*|1-0|*1000 = 1.0 (equity 999.0); at t2
    # the weight goes back to 0: cost = 0.001*|0-1|*999 = 0.999, so equity = 999 - 0.999
    equity, _ = run_fx_equity(
        close=_column([100, 100, 100]),
        weight=_column([0, 1, 0]),
        fx=_column([1.0, 1.0, 1.0]),
        initial_cash=1000.0,
        cost_rate=0.001,
    )
    assert equity == pytest.approx([1000.0, 999.0, 999.0 - 0.001 * 999.0])


def test_with_every_rate_one_the_loop_equals_the_single_currency_compounding() -> None:
    # two symbols, base currency only: E[t] = E[t-1] * (1 + sum(w * r) - turnover * rate)
    close = np.array([[100, 50], [110, 49], [99, 51.45], [101, 50]], dtype=np.float64)
    weight = np.array([[0, 0], [0.5, -0.25], [0.5, -0.25], [0.2, 0.0]], dtype=np.float64)
    fx = np.ones_like(close)
    rate = 0.0005
    equity, _ = run_fx_equity(
        close=close, weight=weight, fx=fx, initial_cash=1000.0, cost_rate=rate
    )
    expected = [1000.0]
    ret = close[1:] / close[:-1] - 1.0
    for t in range(1, 4):
        turnover = np.abs(weight[t] - weight[t - 1]).sum()
        expected.append(expected[-1] * (1.0 + (weight[t] * ret[t - 1]).sum() - turnover * rate))
    assert equity == pytest.approx(expected, rel=1e-12)


# ---------------------------------------------------------------- the engine's FX path

import dataclasses  # noqa: E402
from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402

import polars as pl  # noqa: E402

from crucible.core.errors import ConfigurationError, DataQualityError  # noqa: E402
from crucible.core.types import DatasetId, RealismLevel, TimestampNs  # noqa: E402
from crucible.data.contracts import (  # noqa: E402
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    FX_RATE_SCHEMA,
    FX_RATE_SORT_KEYS,
)
from crucible.data.store import ParquetDataStore, build_dataset  # noqa: E402
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig  # noqa: E402

BARS = DatasetId("fx_bars")
FX = DatasetId("fx_rates")
# B (EUR) closes 100, 110, 99, 99 and the rates of the hand computation above; A (USD) is flat
# at 100 and held at weight 0.5 throughout, so it adds a base-currency symbol to the grid without
# moving equity (its local pnl is zero at every bar): equity must still be 1000, 1110, 999, 998.9.
B_CLOSES = {1: 100.0, 2: 110.0, 3: 99.0, 4: 99.0}
RATES = [(1, 1, 1.0), (2, 2, 1.1), (3, 3, 1.1), (4, 4, 1.21)]  # (event_time, available_at, mid)


def _bar_row(symbol: str, ts: int, close: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "event_time": ts,
        "available_at": ts,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1.0,
    }


def _fx_row(pair: str, event: int, available: int, mid: float) -> dict[str, object]:
    return {
        "symbol": pair,
        "event_time": event,
        "available_at": available,
        "mid": mid,
        "bid": mid,
        "ask": mid,
    }


def _fx_store(
    root: Path,
    *,
    rates: list[tuple[int, int, float]] | None = None,
    pair: str = "EURUSD",
    drop_b_ts: int | None = None,
) -> ParquetDataStore:
    rows = [_bar_row("A", ts, 100.0) for ts in B_CLOSES]
    rows += [_bar_row("B", ts, px) for ts, px in B_CLOSES.items() if ts != drop_b_ts]
    build_dataset(
        root,
        BARS,
        pl.from_dicts(rows, schema=BAR_SCHEMA),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )
    fx_rows = [_fx_row(pair, e, a, m) for e, a, m in (RATES if rates is None else rates)]
    build_dataset(
        root,
        FX,
        pl.from_dicts(fx_rows, schema=FX_RATE_SCHEMA),
        schema=FX_RATE_SCHEMA,
        sort_keys=FX_RATE_SORT_KEYS,
        source="test",
    )
    return ParquetDataStore(root)


def _signal(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
    """A held 0.5 in A; B held at weight 1 over the bars at ts 2 and 3 (scores 1, 1, 0, 0)."""
    return bars.select(
        symbol="symbol",
        ts=pl.col("event_time"),
        score=pl.when(pl.col("symbol") == "A")
        .then(pl.lit(0.5))
        .otherwise(pl.when(pl.col("event_time") <= 2).then(pl.lit(1.0)).otherwise(pl.lit(0.0))),
    )


def _config(
    store: ParquetDataStore,
    *,
    symbol_currency: dict[str, str] | None = None,
    fx_dataset: DatasetId | None = FX,
) -> VectorizedConfig:
    return VectorizedConfig(
        store=store,
        bars_dataset=BARS,
        signal=_signal,
        params={},
        initial_cash=Decimal("1000"),
        realism_level=RealismLevel.FRICTIONLESS,
        start=TimestampNs(1),
        end=TimestampNs(4),
        base_currency="USD",
        symbol_currency={"B": "EUR"} if symbol_currency is None else symbol_currency,
        fx_dataset=fx_dataset,
    )


def test_the_engine_runs_the_fx_path_and_matches_the_hand_computation(tmp_path: Path) -> None:
    result = VectorizedBacktestEngine().run(_config(_fx_store(tmp_path)))
    assert result.equity["ts"].to_list() == [1, 2, 3, 4]
    assert result.equity["equity"].to_list() == pytest.approx([1000.0, 1110.0, 999.0, 998.9])
    b = result.pnl.filter(pl.col("symbol") == "B").sort("ts")
    assert b["pnl"].to_list() == pytest.approx([0.0, 110.0, -111.0, -0.1])
    assert not result.pnl.filter(pl.col("symbol") == "A")["pnl"].abs().gt(1e-12).any()
    per_ts = result.pnl.group_by("ts").agg(pl.col("pnl").sum()).sort("ts")["pnl"].to_list()
    assert per_ts == pytest.approx([0.0, 110.0, -111.0, -0.1])


def test_a_symbol_map_without_a_foreign_currency_uses_the_single_currency_path(
    tmp_path: Path,
) -> None:
    store = _fx_store(tmp_path)
    plain = VectorizedBacktestEngine().run(_config(store, symbol_currency={}, fx_dataset=None))
    explicit = VectorizedBacktestEngine().run(_config(store, symbol_currency={"B": "USD"}))
    assert plain.equity.equals(explicit.equity)
    assert plain.pnl.equals(explicit.pnl)


def test_the_rate_used_at_a_bar_is_the_latest_known_at_its_ts(tmp_path: Path) -> None:
    # the ts-4 rate is published at ts 5 (after the last bar): the bar at ts 4 still uses 1.10,
    # so the final equity is 1000 + 1.10 * (-10/11) = 999.0, not 998.9
    late = [(1, 1, 1.0), (2, 2, 1.1), (3, 3, 1.1), (4, 5, 1.21)]
    result = VectorizedBacktestEngine().run(_config(_fx_store(tmp_path, rates=late)))
    assert result.equity["equity"].to_list()[-1] == pytest.approx(999.0)


@pytest.mark.parametrize(
    ("kwargs", "config_kwargs", "error", "match"),
    [
        ({"pair": "USDEUR"}, {}, DataQualityError, "EURUSD"),
        ({"rates": [(2, 2, 1.1), (3, 3, 1.1), (4, 4, 1.21)]}, {}, DataQualityError, "no FX rate"),
        (
            {"rates": [(1, 1, 1.0), (2, 2, 0.0), (3, 3, 1.1), (4, 4, 1.21)]},
            {},
            DataQualityError,
            "positive",
        ),
        ({}, {"fx_dataset": None}, ConfigurationError, "fx_rates"),
        ({"drop_b_ts": 3}, {}, DataQualityError, "common calendar"),
    ],
)
def test_refuses_what_it_cannot_price(
    tmp_path: Path,
    kwargs: dict[str, object],
    config_kwargs: dict[str, object],
    error: type[Exception],
    match: str,
) -> None:
    store = _fx_store(tmp_path, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(error, match=match):
        VectorizedBacktestEngine().run(_config(store, **config_kwargs))  # type: ignore[arg-type]


def test_entering_a_position_from_flat_is_charged_the_turnover_cost() -> None:
    # the run starts flat: a weight of 1 from row 1 enters a full position, costing 0.001*1*1000 = 1
    equity, _ = run_fx_equity(
        close=_column([100, 100, 100]),
        weight=_column([1, 1, 1]),
        fx=_column([1.0, 1.0, 1.0]),
        initial_cash=1000.0,
        cost_rate=0.001,
    )
    assert equity == pytest.approx([1000.0, 999.0, 999.0])


def test_a_weight_at_the_first_row_that_is_never_held_is_not_charged_as_an_exit() -> None:
    # weight[0] = 1 is not held (the run starts flat) and weight[1] = 0: no trade happens, no cost
    equity, _ = run_fx_equity(
        close=_column([100, 100, 100]),
        weight=_column([1, 0, 0]),
        fx=_column([1.0, 1.0, 1.0]),
        initial_cash=1000.0,
        cost_rate=0.001,
    )
    assert equity == pytest.approx([1000.0, 1000.0, 1000.0])


def test_the_rate_is_the_latest_event_time_among_the_rows_available_at_the_bar(
    tmp_path: Path,
) -> None:
    """The event engine's PIT read takes, among rows with available_at <= ts, the one with the
    latest event_time (ties: the later available_at). Rows: (event 1, avail 1, 1.0), (2, 2, 1.1),
    (event 5, avail 3, 1.2), (event 3, avail 4, 9.0): at ts 3 the best is event 5 (1.2); at ts 4 the
    row with event 3 is also available but 5 > 3, so it is still 1.2 (taking the latest
    available_at would give 9.0). Rates by ts: 1.0, 1.1, 1.2, 1.2. With the hand case's closes and
    weights: E1 = 1110 (rate 1.1), U after t2 = -10/11, E2 = 1000 + 1.2*(-10/11), E3 the same."""
    rates = [(1, 1, 1.0), (2, 2, 1.1), (5, 3, 1.2), (3, 4, 9.0)]
    result = VectorizedBacktestEngine().run(_config(_fx_store(tmp_path, rates=rates)))
    expected = 1000.0 + 1.2 * (-10.0 / 11.0)
    assert result.equity["equity"].to_list() == pytest.approx([1000.0, 1110.0, expected, expected])


def test_an_empty_window_is_refused_with_a_clear_message(tmp_path: Path) -> None:
    config = dataclasses.replace(
        _config(_fx_store(tmp_path)), start=TimestampNs(100), end=TimestampNs(200)
    )
    with pytest.raises(DataQualityError, match="no bars between"):
        VectorizedBacktestEngine().run(config)


def test_the_weight_at_the_first_window_row_is_not_reported_as_held(tmp_path: Path) -> None:
    """The run starts flat (the row-0 weight is never held), so the weights frame must not claim a
    position there: episodes built from it would start a phantom zero-pnl episode. With the window
    starting at ts 2, B's lagged weight there is 1 (from the score at ts 1) and must read 0."""
    config = dataclasses.replace(_config(_fx_store(tmp_path)), start=TimestampNs(2))
    result = VectorizedBacktestEngine().run(config)
    b = result.weights.filter(pl.col("symbol") == "B").sort("ts")
    assert b.filter(pl.col("ts") == 2)["weight"].to_list() == [0.0]
    assert b.filter(pl.col("ts") == 3)["weight"].to_list() == [1.0]  # held from the next row on
