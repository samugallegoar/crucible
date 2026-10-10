"""Intraday ex-date: fills inside the ex-date's own session are not before the
ex-date (ADR-0046 amendment).

Convention: a timestamp exactly at a 24/7 midnight is the START of that day, like
a midnight-stamped ex-date on an exchange calendar; the holder of record is the
position strictly before the ex session opens.

Hand computation. Sessions are days [D, D+1) (a test calendar); DIVCO is flat at 50
with a 2.00 dividend whose ex event is stamped 3D+12H (inside the session that
opens at 3D), pay-date 4D. Bars: a=2D+6H, b=2D+12H, o=3D (the open), c=3D+3H,
d=3D+9H, e=3D+12H, f=4D, g=5D. At Level 1 an order submitted on a bar fills on
the next bar.
  A: BUY 100 submitted on c fills on d, inside the ex session: no dividend.
  B: BUY 100 submitted on a fills on b (before the open); SELL 100 submitted on c
     fills on d (inside the session). Holder of record with 100: +200 on the pay-date.
  C: BUY 100 submitted on b fills on o, exactly at the open. A buyer on the ex-date
     session is not entitled: no dividend.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.core.engine import BacktestEngine
from crucible.core.events import BarEvent
from crucible.core.types import Currency, DatasetId, OrderSide, RealismLevel, Symbol, TimestampNs
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CORPORATE_ACTION_SCHEMA,
    CORPORATE_ACTION_SORT_KEYS,
)
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
HOUR = 3_600 * 10**9
BARS = DatasetId("intraday_bars")
ACTIONS = DatasetId("intraday_actions")
DIVCO = Symbol("DIVCO")
USD = Currency("USD")
A, B, OPEN, C, D, E, F, G = (
    2 * DAY + 6 * HOUR,
    2 * DAY + 12 * HOUR,
    3 * DAY,
    3 * DAY + 3 * HOUR,
    3 * DAY + 9 * HOUR,
    3 * DAY + 12 * HOUR,
    4 * DAY,
    5 * DAY,
)


class DailySessions:
    """A calendar whose sessions are whole days [D, D+1); no true-open overrides."""

    name = "test-daily-sessions"

    def session_open_by_close(self, start: TimestampNs, end: TimestampNs) -> dict[int, int]:
        return {}

    def session_open_at(self, ts: TimestampNs) -> TimestampNs | None:
        return TimestampNs(int(ts) // DAY * DAY)


class ScriptedByTs:
    """Submits DIVCO orders on chosen bar timestamps: ``{ts: [(side, qty)]}``."""

    def __init__(self, script: dict[int, list[tuple[OrderSide, str]]]) -> None:
        self._script = script

    def on_start(self, ctx: BacktestContext) -> None: ...

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        for side, qty in self._script.get(int(event.ts), []):
            ctx.orders.submit(DIVCO, side, Decimal(qty))

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_order_update(self, ctx: object, event: object) -> None: ...

    def on_fill(self, ctx: object, event: object) -> None: ...

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: object) -> None: ...


def _store(root: Path) -> None:
    times = [A, B, OPEN, C, D, E, F, G]
    n = len(times)
    bars = pl.DataFrame(
        {
            "symbol": ["DIVCO"] * n,
            "event_time": times,
            "available_at": times,
            "open": [50.0] * n,
            "high": [50.5] * n,
            "low": [49.5] * n,
            "close": [50.0] * n,
            "volume": [1e6] * n,
        }
    )
    build_dataset(root, BARS, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")
    actions = pl.DataFrame(
        {
            "symbol": ["DIVCO"],
            "action": ["cash_dividend"],
            "effective_at": [E],
            "event_time": [E],
            "available_at": [E],
            "value": [2.0],
            "pay_at": [F],
        },
        schema_overrides={"value": pl.Float64, "pay_at": pl.Int64},
    )
    build_dataset(
        root,
        ACTIONS,
        actions,
        schema=CORPORATE_ACTION_SCHEMA,
        sort_keys=CORPORATE_ACTION_SORT_KEYS,
        source="test",
    )


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    _store(root)
    return root


def _dividends(store: Path, script: dict[int, list[tuple[OrderSide, str]]]) -> list[Decimal]:
    result = BacktestEngine(
        store=ParquetDataStore(store),
        bars_dataset=BARS,
        corporate_actions_dataset=ACTIONS,
        strategy=ScriptedByTs(script),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
        calendar=DailySessions(),
    ).run()
    return [Decimal(str(row["amount"])) for row in result.ledger_rows if row["type"] == "dividend"]


def test_a_buy_inside_the_ex_session_is_not_entitled(store: Path) -> None:
    assert _dividends(store, {C: [(OrderSide.BUY, "100")]}) == []


def test_a_sell_inside_the_ex_session_is_still_entitled(store: Path) -> None:
    dividends = _dividends(store, {A: [(OrderSide.BUY, "100")], C: [(OrderSide.SELL, "100")]})
    assert dividends == [Decimal("200")]


def test_a_buy_that_fills_exactly_at_the_session_open_is_not_entitled(store: Path) -> None:
    assert _dividends(store, {B: [(OrderSide.BUY, "100")]}) == []
