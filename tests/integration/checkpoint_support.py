"""Shared scaffolding for the checkpoint/resume tests (E7, ADR-0041).

A small two-symbol dataset with a dividend (ex-date day 3, pay date
configurable), a strategy that keeps its working state in ``ctx.state``
(including a ``set``), an engine factory, and whole-result comparison.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from crucible.core import checkpoint as ckpt
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
from crucible.execution.ladder import ExecutionSetup
from crucible.execution.models import MarketStats, NoCommission, NoSpread, ZeroLatency
from crucible.strategy.context import BacktestContext

if TYPE_CHECKING:
    import numpy as np

    from crucible.orders.interfaces import Order

DAY = 86_400 * 10**9
BARS = DatasetId("ckpt_bars")
ACTIONS = DatasetId("ckpt_actions")
DIVCO = Symbol("DIVCO")
SHORTCO = Symbol("SHORTCO")
USD = Currency("USD")


def build_dividend_store(root: Path, *, pay_day: int = 5, n_days: int = 5) -> None:
    """``n_days`` daily bars per symbol; a 2.00 dividend on both, ex-date day 3."""
    days = list(range(1, n_days + 1))
    bars = pl.DataFrame(
        {
            "symbol": ["DIVCO"] * n_days + ["SHORTCO"] * n_days,
            "event_time": [d * DAY for d in days] * 2,
            "available_at": [d * DAY for d in days] * 2,
            "open": [50.0] * n_days + [20.0] * n_days,
            "high": [50.5] * n_days + [20.5] * n_days,
            "low": [49.5] * n_days + [19.5] * n_days,
            "close": [50.0] * n_days + [20.0] * n_days,
            "volume": [1e6] * (2 * n_days),
        }
    )
    build_dataset(root, BARS, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="t")
    actions = pl.DataFrame(
        {
            "symbol": ["DIVCO", "SHORTCO"],
            "action": ["cash_dividend", "cash_dividend"],
            "effective_at": [3 * DAY, 3 * DAY],
            "event_time": [3 * DAY, 3 * DAY],
            "available_at": [3 * DAY, 3 * DAY],
            "value": [2.0, 2.0],
            "pay_at": [pay_day * DAY, pay_day * DAY],
        },
        schema_overrides={"value": pl.Float64, "pay_at": pl.Int64},
    )
    build_dataset(
        root,
        ACTIONS,
        actions,
        schema=CORPORATE_ACTION_SCHEMA,
        sort_keys=CORPORATE_ACTION_SORT_KEYS,
        source="t",
    )


class TradingStrategy:
    """First bar of each symbol: buy 100 DIVCO / short 50 SHORTCO. Working
    state lives in ``ctx.state`` (a counter and a ``set``), as the resumable
    strategy contract requires."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["done"] = set()
        ctx.state["bars"] = 0

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        bars = ctx.state["bars"]
        assert isinstance(bars, int)
        ctx.state["bars"] = bars + 1
        done = ctx.state["done"]
        assert isinstance(done, set)
        if event.symbol in done:
            return
        done.add(str(event.symbol))
        if event.symbol == DIVCO:
            ctx.orders.submit(DIVCO, OrderSide.BUY, Decimal("100"))
        elif event.symbol == SHORTCO:
            ctx.orders.submit(SHORTCO, OrderSide.SELL, Decimal("50"))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


def make_engine(
    root: Path,
    *,
    strategy: object | None = None,
    seed: int = 0,
    end_day: int = 9,
    **overrides: object,
) -> BacktestEngine:
    """A fresh engine over the dividend store. ``overrides`` replace any
    ``BacktestEngine`` keyword (for example ``observer=`` or ``feed_factory=``)."""
    kwargs: dict[str, object] = {
        "store": ParquetDataStore(root),
        "bars_dataset": BARS,
        "corporate_actions_dataset": ACTIONS,
        "strategy": strategy if strategy is not None else TradingStrategy(),
        "params": {},
        "initial_cash": Decimal("100000"),
        "base_currency": USD,
        "realism_level": RealismLevel.BASIC_FRICTION,
        "slippage_bps": 0.0,
        "commission_bps": 0.0,
        "start": TimestampNs(0),
        "end": TimestampNs(end_day * DAY),
        "seed": seed,
    }
    kwargs.update(overrides)
    return BacktestEngine(**kwargs)  # type: ignore[arg-type]  # test factory: kwargs are BacktestEngine's own


def result_parts(result: BacktestResult) -> dict[str, object]:
    """Every part of a result that must survive a stop/resume unchanged."""
    snapshot = result.final_snapshot
    return {
        "equity": result.equity_rows,
        "orders": result.order_rows,
        "fills": result.fill_rows,
        "ledger": result.ledger_rows,
        "log": result.log.entries,
        "reasons": result.order_reasons,
        "final_equity": str(snapshot.equity(USD)),
        "final_cash": str(snapshot.cash(USD)),
        "final_positions": {
            str(symbol): str(position.qty) for symbol, position in snapshot.positions().items()
        },
    }


def assert_same_result(actual: BacktestResult, expected: BacktestResult) -> None:
    a, e = result_parts(actual), result_parts(expected)
    assert a.keys() == e.keys()
    for key in e:
        assert a[key] == e[key], f"result part {key!r} differs (resumed vs uninterrupted)"


class BuyEveryDivcoBar:
    """Buys 1 DIVCO on every DIVCO bar: a steady stream of fills across any boundary."""

    def on_start(self, ctx: BacktestContext) -> None: ...

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        if event.symbol == DIVCO:
            ctx.orders.submit(DIVCO, OrderSide.BUY, Decimal("1"))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


class RollingSlippage:
    """Adverse slippage that grows by one basis point per fill: run state living on a model."""

    def __init__(self) -> None:
        self.fills = 0

    def adjusted_price(
        self, reference_price: float, order: Order, market: BarEvent, rng: np.random.Generator
    ) -> float:
        self.fills += 1
        fraction = self.fills / 10_000.0
        if order.side is OrderSide.BUY:
            return reference_price * (1.0 + fraction)
        return reference_price * (1.0 - fraction)


class SnapshottableRollingSlippage(RollingSlippage):
    def snapshot(self) -> dict[str, object]:
        return {"fills": self.fills}

    def restore(self, state: Mapping[str, object]) -> None:
        self.fills = ckpt.field(state, "fills", int)


def execution_setup(slippage: RollingSlippage) -> ExecutionSetup:
    return ExecutionSetup(
        spread=NoSpread(),
        latency=ZeroLatency(),
        slippage=slippage,
        commission=NoCommission(),
        participation=None,
        stats=MarketStats(),
    )
