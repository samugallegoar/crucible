"""PaperBroker: an external facade over the engine (ADR-0040). Orders go
through engine.submit_spec (so risk applies) and state comes from the
engine's order manager and ledger fold."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from crucible.core.engine import BacktestEngine
from crucible.core.errors import CrucibleError
from crucible.core.events import BarEvent
from crucible.core.types import (
    Currency,
    DatasetId,
    OrderId,
    OrderSide,
    OrderState,
    OrderType,
    RealismLevel,
    Symbol,
    TimestampNs,
)
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.live.paper import PaperBroker
from crucible.orders.interfaces import OrderSpec
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
BARS = DatasetId("broker_bars")
DIVCO = Symbol("DIVCO")


class BrokerDrivenStrategy:
    """Trades only through the PaperBroker held in ``holder``; records what the
    broker reports on each bar."""

    def __init__(self, holder: dict[str, PaperBroker]) -> None:
        self._holder = holder
        self.bar_no = 0
        self.buy_id: OrderId | None = None
        self.limit_id: OrderId | None = None
        self.log: list[dict[str, object]] = []

    def on_start(self, ctx: BacktestContext) -> None: ...

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        broker = self._holder["broker"]
        self.bar_no += 1
        if self.bar_no == 1:
            self.buy_id = broker.submit(
                OrderSpec(symbol=DIVCO, side=OrderSide.BUY, qty=Decimal("100"))
            )
            self.limit_id = broker.submit(
                OrderSpec(
                    symbol=DIVCO,
                    side=OrderSide.BUY,
                    qty=Decimal("10"),
                    type=OrderType.LIMIT,
                    limit_price=1.0,
                )
            )
        elif self.bar_no == 2:
            assert self.buy_id is not None
            assert self.limit_id is not None
            self.log.append(
                {
                    "buy_state": broker.order_state(self.buy_id),
                    "positions": dict(broker.positions()),
                    "cash": dict(broker.cash()),
                }
            )
            broker.cancel(self.limit_id)
            self.log.append({"limit_state": broker.order_state(self.limit_id)})

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


def _run(
    tmp_path: Path,
    make_strategy: Callable[[dict[str, PaperBroker]], Any] = BrokerDrivenStrategy,
) -> tuple[Any, PaperBroker]:
    # Any: the helper returns whichever strategy class it was asked to build
    bars = pl.DataFrame(
        {
            "symbol": ["DIVCO"] * 4,
            "event_time": [d * DAY for d in range(1, 5)],
            "available_at": [d * DAY for d in range(1, 5)],
            "open": [50.0] * 4,
            "high": [50.5] * 4,
            "low": [49.5] * 4,
            "close": [50.0] * 4,
            "volume": [1e6] * 4,
        }
    )
    build_dataset(tmp_path, BARS, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="t")
    holder: dict[str, PaperBroker] = {}
    strategy = make_strategy(holder)
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=strategy,
        params={},
        initial_cash=Decimal("100000"),
        base_currency=Currency("USD"),
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(5 * DAY),
    )
    holder["broker"] = PaperBroker(engine)
    engine.run()
    return strategy, holder["broker"]


def test_submit_fill_state_positions_and_cash(tmp_path: Path) -> None:
    strategy, _ = _run(tmp_path)
    snapshot = strategy.log[0]
    assert snapshot["buy_state"] is OrderState.FILLED
    assert snapshot["positions"] == {DIVCO: Decimal("100")}
    # 100000 - 100 * 50 at Level 1, zero slippage/commission (flat bars at 50)
    assert snapshot["cash"] == {Currency("USD"): Decimal("95000")}


def test_cancel_moves_the_order_to_cancelled(tmp_path: Path) -> None:
    strategy, _ = _run(tmp_path)
    assert strategy.log[1]["limit_state"] is OrderState.CANCELLED


def test_unknown_order_id_names_the_id_and_the_time(tmp_path: Path) -> None:
    _, broker = _run(tmp_path)
    with pytest.raises(CrucibleError, match=r"O-99999999.*ts="):
        broker.order_state(OrderId("O-99999999"))


class RoundTripThroughBroker:
    """BUY 100 on bar 1, SELL 100 on bar 2 (both through the broker); reads
    ``positions()`` on bar 4, when the position is flat."""

    def __init__(self, holder: dict[str, PaperBroker]) -> None:
        self._holder = holder
        self.bar_no = 0
        self.final_positions: dict[Symbol, Decimal] | None = None

    def on_start(self, ctx: BacktestContext) -> None: ...

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        broker = self._holder["broker"]
        self.bar_no += 1
        if self.bar_no == 1:
            broker.submit(OrderSpec(symbol=DIVCO, side=OrderSide.BUY, qty=Decimal("100")))
        elif self.bar_no == 2:
            broker.submit(OrderSpec(symbol=DIVCO, side=OrderSide.SELL, qty=Decimal("100")))
        elif self.bar_no == 4:
            self.final_positions = dict(broker.positions())

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


def test_positions_drops_a_flat_position(tmp_path: Path) -> None:
    """Long 100 then flat: the ledger fold keeps DIVCO with quantity 0, which
    the broker must not report."""
    strategy, _ = _run(tmp_path, RoundTripThroughBroker)
    assert strategy.final_positions == {}
