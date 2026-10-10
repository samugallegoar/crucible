"""RandomSignal: a strategy whose signal is pure noise, seeded by
``params["seed"]``, with zero relationship to any market data (ADR-0023).

The "known-overfit" half of the acceptance demonstration: sweeping many
seeds via ``crucible optimize`` and picking the best in-sample Sharpe is
exactly what a trial-counting parameter search does, on a strategy that
by construction has zero genuine skill -- DSR and PBO exist to catch
precisely this pattern.

Rebalance/order-submission mechanics mirror ``examples.momentum.strategy
.Momentum`` (session counting, ``rebalance_every`` gating, equal weight);
the only difference is *which* symbols get picked: pure ``rng.choice``,
never a momentum ranking or any other data-derived statistic. The rng is
seeded once in ``on_start`` from ``params["seed"]`` -- CLAUDE.md's
explicit-rng rule, never global RNG.
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


class RandomSignal:
    """Long-only, equal-weight, periodic rebalance into a random subset of
    the universe -- no genuine edge by construction."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["sessions"] = 0
        ctx.state["last_event_time"] = 0
        ctx.state["rng"] = np.random.default_rng(int(str(ctx.params["seed"])))

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
        raw_symbols = ctx.params["symbols"]
        assert isinstance(raw_symbols, list)  # config-validated YAML list
        symbols = [Symbol(str(s)) for s in raw_symbols]
        top_k = int(str(ctx.params["top_k"]))
        base = Currency(str(ctx.params["base_currency"]))
        rng = ctx.state["rng"]
        assert isinstance(rng, np.random.Generator)

        history = ctx.data.history(
            dataset, ["close"], symbols, as_of=ctx.clock.now, lookback=2
        ).filter(pl.col("event_time") < current_event_time)
        if history.height == 0:
            return
        freshest = int(history.get_column("event_time").max())  # type: ignore[arg-type]
        latest = history.filter(pl.col("event_time") == freshest)
        tradeable = latest.get_column("symbol").to_list()
        if not tradeable:
            return

        k = min(top_k, len(tradeable))
        winners = set(rng.choice(tradeable, size=k, replace=False).tolist())
        equity = ctx.portfolio.equity(base)
        weight = Decimal(1) / Decimal(k)
        prices = dict(
            zip(
                latest.get_column("symbol").to_list(),
                latest.get_column("close").to_list(),
                strict=True,
            )
        )

        for symbol_str, price_val in prices.items():
            symbol = Symbol(symbol_str)
            price = Decimal(repr(price_val))
            target_qty = (
                (equity * weight / price).quantize(Decimal("1"), rounding=ROUND_DOWN)
                if symbol_str in winners
                else Decimal("0")
            )
            position = ctx.portfolio.position(symbol)
            current_qty = position.qty if position is not None else Decimal("0")
            delta = target_qty - current_qty
            if delta == 0:
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            ctx.orders.submit(symbol, side, abs(delta))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None:
        ctx.log.info(
            "random-signal run finished",
            sessions=int(str(ctx.state["sessions"])),
        )
