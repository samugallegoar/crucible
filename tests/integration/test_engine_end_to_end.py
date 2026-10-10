"""Engine end-to-end on a tiny hand-computed scenario with a delisting.

Scenario (Level 1, slippage 0 bps, commission 10 bps, initial cash 100,000):
- AAA bars on days 1..5, BBB bars on days 1..3, BBB delists effective day 4.
- Strategy buys 10 shares (market, GTC) the first time it sees each symbol.

Hand computation:
  day 1: both orders submitted; no fills yet.
  day 2: AAA fills 10 @ open 100.5 (fee 1.005); BBB fills 10 @ open 50.5
         (fee 0.505). cash = 100000 - 1005 - 1.005 - 505 - 0.505 = 98488.49
         equity(day2) = 98488.49 + 10*101 + 10*51 = 100008.49
  day 4: BBB delists; liquidated at last mark 52 -> cash += 520 = 99008.49
         realized BBB pnl = (52 - 50.5) * 10 = 15
  day 5: equity = 99008.49 + 10*104 = 100048.49 ; fees = 1.51
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl

from crucible.core.engine import BacktestEngine, BacktestResult
from crucible.core.events import BarEvent
from crucible.core.types import (
    Currency,
    DatasetId,
    OrderSide,
    RealismLevel,
    Symbol,
    TimestampNs,
)
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CORPORATE_ACTION_SCHEMA,
    CORPORATE_ACTION_SORT_KEYS,
)
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
USD = Currency("USD")
BARS = DatasetId("bars_e2e")
ACTIONS = DatasetId("ca_e2e")


def _build_datasets(root: Path) -> None:
    def bars(symbol: str, closes: list[float], opens: list[float]) -> pl.DataFrame:
        days = list(range(1, len(closes) + 1))
        return pl.DataFrame(
            {
                "symbol": [symbol] * len(days),
                "event_time": [d * DAY for d in days],
                "available_at": [d * DAY for d in days],
                "open": opens,
                "high": [max(o, c) * 1.01 for o, c in zip(opens, closes, strict=True)],
                "low": [min(o, c) * 0.99 for o, c in zip(opens, closes, strict=True)],
                "close": closes,
                "volume": [1e6] * len(days),
            }
        )

    frame = pl.concat(
        [
            bars("AAA", [100.0, 101.0, 102.0, 103.0, 104.0], [99.5, 100.5, 101.5, 102.5, 103.5]),
            bars("BBB", [50.0, 51.0, 52.0], [49.5, 50.5, 51.5]),
        ]
    )
    build_dataset(root, BARS, frame, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")
    actions = pl.DataFrame(
        {
            "symbol": ["BBB"],
            "action": ["delisting"],
            "effective_at": [4 * DAY],
            "event_time": [4 * DAY],
            "available_at": [4 * DAY],
            "value": [None],
            "pay_at": [None],
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


class BuyOnFirstSight:
    """Buys 10 shares of every symbol the first time it sees a bar for it."""

    def __init__(self) -> None:
        self.fills: list[object] = []
        self.updates: list[object] = []

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["seen"] = set()

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:  # type: ignore[override]
        seen = ctx.state["seen"]
        assert isinstance(seen, set)
        if event.symbol not in seen:
            seen.add(event.symbol)
            ctx.orders.submit(event.symbol, OrderSide.BUY, Decimal("10"))

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_order_update(self, ctx: object, event: object) -> None:
        self.updates.append(event)

    def on_fill(self, ctx: object, event: object) -> None:
        self.fills.append(event)

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: object) -> None: ...


def _run(root: Path) -> BacktestResult:
    engine = BacktestEngine(
        store=ParquetDataStore(root),
        bars_dataset=BARS,
        corporate_actions_dataset=ACTIONS,
        strategy=BuyOnFirstSight(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=10.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
    )
    return engine.run()


def test_end_to_end_matches_hand_computation(tmp_path: Path) -> None:
    _build_datasets(tmp_path)
    result = _run(tmp_path)

    prices = {row["symbol"]: row["price"] for row in result.fill_rows}
    assert prices == {"AAA": 100.5, "BBB": 50.5}

    equity = {row["ts"]: row["equity"] for row in result.equity_rows}
    assert equity[2 * DAY] == 100008.49
    assert equity[5 * DAY] == 100048.49

    final = result.final_snapshot
    assert final.cash(USD) == Decimal("99008.49")
    assert final.fees_paid == Decimal("1.51")
    assert final.realized_pnl == Decimal("15")
    assert final.position(Symbol("BBB")) is None
    aaa = final.position(Symbol("AAA"))
    assert aaa is not None
    assert aaa.qty == Decimal("10")

    types = [row["type"] for row in result.ledger_rows]
    assert "corporate_action" in types


def test_identical_inputs_produce_identical_outputs(tmp_path: Path) -> None:
    _build_datasets(tmp_path)
    a, b = _run(tmp_path), _run(tmp_path)
    assert a.equity_rows == b.equity_rows
    assert a.fill_rows == b.fill_rows
    assert a.order_rows == b.order_rows
    assert a.ledger_rows == b.ledger_rows
    assert a.log.entries == b.log.entries
