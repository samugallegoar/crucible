"""Bracket order through the whole engine: entry fill activates children;
when take-profit and stop-loss both trigger in one bar, the stop executes.

Hand computation (zero slippage/commission, initial cash 100,000):
  day 1: strategy submits bracket (BUY 10 MARKET, TP 110, SL 92)
  day 2: entry fills at open 100 -> cash 99,000; children activate
  day 3: bar spans 91..111 -> both children trigger -> stop executes at 92
         realized pnl = (92 - 100) * 10 = -80 ; cash = 99,000 + 920 = 99,920
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

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
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.orders.interfaces import OrderSpec
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
USD = Currency("USD")
BARS = DatasetId("bars_bracket")
AAA = Symbol("AAA")


def _build(root: Path) -> None:
    frame = pl.DataFrame(
        {
            "symbol": ["AAA"] * 3,
            "event_time": [DAY, 2 * DAY, 3 * DAY],
            "available_at": [DAY, 2 * DAY, 3 * DAY],
            "open": [100.0, 100.0, 100.0],
            "high": [101.0, 101.0, 111.0],
            "low": [99.0, 99.0, 91.0],
            "close": [100.0, 100.0, 95.0],
            "volume": [1e6] * 3,
        }
    )
    build_dataset(root, BARS, frame, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")


class BracketOnce:
    def __init__(self) -> None:
        self.ids: tuple[str, str, str] | None = None

    def on_start(self, ctx: BacktestContext) -> None: ...

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:  # type: ignore[override]
        if self.ids is None:
            entry, tp, sl = ctx.orders.submit_bracket(
                OrderSpec(symbol=AAA, side=OrderSide.BUY, qty=Decimal("10")),
                take_profit=110.0,
                stop_loss=92.0,
            )
            self.ids = (str(entry), str(tp), str(sl))

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_order_update(self, ctx: object, event: object) -> None: ...

    def on_fill(self, ctx: object, event: object) -> None: ...

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: object) -> None: ...


def _run(root: Path, strategy: BracketOnce) -> BacktestResult:
    return BacktestEngine(
        store=ParquetDataStore(root),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=strategy,
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        start=TimestampNs(0),
        end=TimestampNs(4 * DAY),
    ).run()


def test_bracket_lifecycle_with_adverse_intrabar_resolution(tmp_path: Path) -> None:
    _build(tmp_path)
    strategy = BracketOnce()
    result = _run(tmp_path, strategy)
    assert strategy.ids is not None
    entry_id, tp_id, sl_id = strategy.ids

    states = {row["order_id"]: row["state"] for row in result.order_rows}
    assert states[entry_id] == "filled"
    assert states[sl_id] == "filled"  # the adverse leg won the ambiguous bar
    assert states[tp_id] == "cancelled"

    prices = {row["order_id"]: row["price"] for row in result.fill_rows}
    assert prices[entry_id] == 100.0
    assert prices[sl_id] == 92.0

    final = result.final_snapshot
    assert final.cash(USD) == Decimal("99920")
    assert final.realized_pnl == Decimal("-80")
    assert final.position(AAA) is None

    # the dropped take-profit leg carries its why-not-filled explanation
    assert any("OCO ambiguity" in reason for _, reason in result.order_reasons.get(tp_id, []))


def test_an_opposite_side_oco_pair_is_refused(tmp_path: Path) -> None:
    """Regression (2026-10 audit, LOW): an OCO pair with one buy and one sell leg was accepted,
    and the adverse-leg rule (a signed cash-flow comparison) always executed the buy. The pair
    is meaningless, so it is refused with the fix instead of being resolved arbitrarily."""
    from crucible.core.errors import ConfigurationError

    _build(tmp_path)
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=BracketOnce(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        start=TimestampNs(0),
        end=TimestampNs(4 * DAY),
    )
    with pytest.raises(ConfigurationError, match="same side"):
        engine.submit_oco(
            OrderSpec(symbol=AAA, side=OrderSide.BUY, qty=Decimal("10")),
            OrderSpec(symbol=AAA, side=OrderSide.SELL, qty=Decimal("10")),
        )
