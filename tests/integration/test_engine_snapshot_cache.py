"""The engine reuses the portfolio snapshot while nothing it depends on changed (ADR-0054).

A strategy that reads ``ctx.portfolio`` once per symbol (the momentum example does, 569 times per
rebalance) used to rebuild the snapshot every time. The snapshot is a pure function of
(clock, ledger, marks), so it is rebuilt only when one of them changes.

Scenario (Level 1, zero costs, initial cash 100,000, AAA bars on days 1..4, closes 100..103,
opens 99.5..102.5): the strategy buys 10 on day 1. The order fills at the day-2 open 100.5:
cash 100000 - 1005 = 98995. Marks move every day.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl

from crucible.core.engine import BacktestEngine
from crucible.core.events import BarEvent
from crucible.core.types import Currency, DatasetId, OrderSide, RealismLevel, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
USD = Currency("USD")
BARS = DatasetId("bars_snapshot_cache")


class Recorder:
    def __init__(self) -> None:
        self.rows: list[tuple[bool, Decimal, Decimal]] = []
        self.objects: list[object] = []

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["bought"] = False

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:  # type: ignore[override]
        first = ctx.portfolio
        second = ctx.portfolio
        self.rows.append((first is second, first.cash(USD), first.equity(USD)))
        self.objects.append(first)
        if not ctx.state["bought"]:
            ctx.state["bought"] = True
            ctx.orders.submit(event.symbol, OrderSide.BUY, Decimal("10"))

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_order_update(self, ctx: object, event: object) -> None: ...

    def on_fill(self, ctx: object, event: object) -> None: ...

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: object) -> None: ...


def test_the_snapshot_is_reused_within_an_instant_and_rebuilt_when_state_changes(
    tmp_path: Path,
) -> None:
    closes = [100.0, 101.0, 102.0, 103.0]
    opens = [99.5, 100.5, 101.5, 102.5]
    frame = pl.DataFrame(
        {
            "symbol": ["AAA"] * 4,
            "event_time": [d * DAY for d in range(1, 5)],
            "available_at": [d * DAY for d in range(1, 5)],
            "open": opens,
            "high": [c * 1.01 for c in closes],
            "low": [o * 0.99 for o in opens],
            "close": closes,
            "volume": [1e6] * 4,
        }
    )
    build_dataset(tmp_path, BARS, frame, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")
    strategy = Recorder()
    BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=strategy,
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
    ).run()

    same_within_instant = [row[0] for row in strategy.rows]
    cash = [row[1] for row in strategy.rows]
    equity = [row[2] for row in strategy.rows]
    assert same_within_instant == [True, True, True, True]
    # day 1: no position yet; day 2 onwards: 10 shares filled at 100.5 (cash 98995)
    assert cash == [Decimal("100000"), Decimal("98995"), Decimal("98995"), Decimal("98995")]
    # equity = cash + 10 * close: 100000, 98995 + 1010, 98995 + 1020, 98995 + 1030
    assert equity == [
        Decimal("100000"),
        Decimal("100005"),
        Decimal("100015"),
        Decimal("100025"),
    ]
    # marks or the ledger changed between instants, so a new snapshot is built each time
    assert len({id(obj) for obj in strategy.objects}) == 4
