"""TrendFollower: absolute (time-series) trend following on a single
symbol's own recent return sign (ADR-0024).

Exploits genuine serial autocorrelation (AR(1),
``examples.trend_demo.build_data``), unlike
``examples.overfit_demo.strategy.RandomSignal`` (no data dependence at
all) or ``examples.momentum.strategy.Momentum`` (cross-sectional
ranking on a *static* per-symbol drift -- an effect ADR-0023 found
survives every implemented null test trivially). Return-order shuffling
destroys THIS strategy's edge specifically, because shuffling destroys
the lag-1 dependency its signal reads.

Params: ``bars_dataset``, ``symbol``, ``lookback`` (bars averaged for the
trend signal), ``rebalance_every``, ``base_currency``.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from crucible.core.types import Currency, DatasetId, OrderSide, Symbol

if TYPE_CHECKING:
    from crucible.core.events import BarEvent
    from crucible.strategy.context import BacktestContext


class TrendFollower:
    """Long 100% of equity when the trailing mean return is positive,
    flat otherwise."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["sessions"] = 0
        ctx.state["last_event_time"] = 0

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        last_et = ctx.state["last_event_time"]
        assert isinstance(last_et, int)
        if int(event.event_time) <= last_et:
            return  # not the first bar of a new session
        ctx.state["last_event_time"] = int(event.event_time)
        sessions = ctx.state["sessions"]
        assert isinstance(sessions, int)
        sessions += 1
        ctx.state["sessions"] = sessions

        every = int(str(ctx.params["rebalance_every"]))
        if sessions % every != 0:
            return
        self._rebalance(ctx, current_event_time=int(event.event_time))

    def _rebalance(self, ctx: BacktestContext, current_event_time: int) -> None:
        dataset = DatasetId(str(ctx.params["bars_dataset"]))
        symbol = Symbol(str(ctx.params["symbol"]))
        lookback = int(str(ctx.params["lookback"]))
        base = Currency(str(ctx.params["base_currency"]))

        history = (
            ctx.data.history(
                dataset, ["close"], [symbol], as_of=ctx.clock.now, lookback=lookback + 2
            )
            .filter(pl.col("event_time") < current_event_time)
            .sort("event_time")
        )
        if history.height < lookback + 1:
            return

        closes = history.get_column("close").to_list()[-(lookback + 1) :]
        trailing_returns = [closes[i + 1] / closes[i] - 1.0 for i in range(len(closes) - 1)]
        signal = sum(trailing_returns) / len(trailing_returns)

        price = Decimal(repr(closes[-1]))
        equity = ctx.portfolio.equity(base)
        target_qty = (
            (equity / price).quantize(Decimal("1"), rounding=ROUND_DOWN)
            if signal > 0
            else Decimal("0")
        )
        position = ctx.portfolio.position(symbol)
        current_qty = position.qty if position is not None else Decimal("0")
        delta = target_qty - current_qty
        if delta == 0:
            return
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        ctx.orders.submit(symbol, side, abs(delta))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None:
        ctx.log.info(
            "trend-follower run finished",
            sessions=int(str(ctx.state["sessions"])),
        )


class RandomDirection:
    """Same mechanics as ``TrendFollower`` (session counting,
    ``rebalance_every`` gating, long-100%-or-flat sizing) but the
    long/flat decision comes from ``rng.choice([-1, 1])`` seeded by
    ``params["seed"]``, never the data (ADR-0024). The "no genuine
    edge" half of the trend-demo acceptance pair: apples-to-apples with
    ``TrendFollower`` except for where the signal comes from, so a null
    test comparing the two isolates exactly that difference."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["sessions"] = 0
        ctx.state["last_event_time"] = 0
        ctx.state["rng"] = np.random.default_rng(int(str(ctx.params["seed"])))

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        last_et = ctx.state["last_event_time"]
        assert isinstance(last_et, int)
        if int(event.event_time) <= last_et:
            return
        ctx.state["last_event_time"] = int(event.event_time)
        sessions = ctx.state["sessions"]
        assert isinstance(sessions, int)
        sessions += 1
        ctx.state["sessions"] = sessions

        every = int(str(ctx.params["rebalance_every"]))
        if sessions % every != 0:
            return
        self._rebalance(ctx, current_event_time=int(event.event_time))

    def _rebalance(self, ctx: BacktestContext, current_event_time: int) -> None:
        dataset = DatasetId(str(ctx.params["bars_dataset"]))
        symbol = Symbol(str(ctx.params["symbol"]))
        base = Currency(str(ctx.params["base_currency"]))
        rng = ctx.state["rng"]
        assert isinstance(rng, np.random.Generator)

        history = (
            ctx.data.history(dataset, ["close"], [symbol], as_of=ctx.clock.now, lookback=2)
            .filter(pl.col("event_time") < current_event_time)
            .sort("event_time")
        )
        if history.height == 0:
            return

        signal = int(rng.choice([-1, 1]))
        price = Decimal(repr(history.get_column("close").to_list()[-1]))
        equity = ctx.portfolio.equity(base)
        target_qty = (
            (equity / price).quantize(Decimal("1"), rounding=ROUND_DOWN)
            if signal > 0
            else Decimal("0")
        )
        position = ctx.portfolio.position(symbol)
        current_qty = position.qty if position is not None else Decimal("0")
        delta = target_qty - current_qty
        if delta == 0:
            return
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        ctx.orders.submit(symbol, side, abs(delta))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None:
        ctx.log.info(
            "random-direction run finished",
            sessions=int(str(ctx.state["sessions"])),
        )
