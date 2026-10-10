"""Daily cross-sectional momentum (example strategy).

Timing discipline: rebalances fire on the *first* bar event of a session and
use only rows with ``event_time`` strictly before that session, so every
symbol is ranked on the same information set (no symbol gets an intra-session
edge). Orders are market GTC and fill at the next bar per Level 1 semantics
(ADR-0010).

Params (all required, from config):
- ``bars_dataset``: dataset id to rank.
- ``symbols``: the tradeable list (the synthetic universe).
- ``lookback``: momentum window in sessions.
- ``top_k``: number of names held, equal-weighted.
- ``rebalance_every``: sessions between rebalances.
- ``base_currency``: ISO code for equity sizing.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING

import polars as pl

from crucible.core.types import Currency, DatasetId, OrderSide, Symbol

if TYPE_CHECKING:
    from crucible.core.events import BarEvent
    from crucible.strategy.context import BacktestContext


class Momentum:
    """Long-only top-k momentum, equal weight, periodic rebalance."""

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

        lookback = int(str(ctx.params["lookback"]))
        every = int(str(ctx.params["rebalance_every"]))
        if sessions <= lookback or sessions % every != 0:
            return
        self._rebalance(ctx, current_event_time=int(event.event_time))

    def _rebalance(self, ctx: BacktestContext, current_event_time: int) -> None:
        dataset = DatasetId(str(ctx.params["bars_dataset"]))
        raw_symbols = ctx.params["symbols"]
        assert isinstance(raw_symbols, list)  # config-validated YAML list
        symbols = [Symbol(str(s)) for s in raw_symbols]
        lookback = int(str(ctx.params["lookback"]))
        top_k = int(str(ctx.params["top_k"]))
        base = Currency(str(ctx.params["base_currency"]))

        history = ctx.data.history(
            dataset, ["close"], symbols, as_of=ctx.clock.now, lookback=lookback + 1
        ).filter(pl.col("event_time") < current_event_time)
        if history.height == 0:
            return

        freshest = int(history.get_column("event_time").max())  # type: ignore[arg-type]
        stats = (
            history.group_by("symbol")
            .agg(
                first_close=pl.col("close").sort_by("event_time").first(),
                last_close=pl.col("close").sort_by("event_time").last(),
                last_event_time=pl.col("event_time").max(),
                n=pl.len(),
            )
            # a symbol with stale or short history is not rankable today;
            # delisted names drop out here instead of being force-ranked
            .filter((pl.col("last_event_time") == freshest) & (pl.col("n") >= lookback))
            .with_columns(momentum=pl.col("last_close") / pl.col("first_close") - 1.0)
            .sort(["momentum", "symbol"], descending=[True, False])
        )
        if stats.height == 0:
            return

        winners = set(stats.head(top_k).get_column("symbol").to_list())
        equity = ctx.portfolio.equity(base)
        weight = Decimal(1) / Decimal(top_k)

        for row in stats.iter_rows(named=True):
            symbol = Symbol(row["symbol"])
            price = Decimal(repr(row["last_close"]))
            target_qty = (
                (equity * weight / price).quantize(Decimal("1"), rounding=ROUND_DOWN)
                if row["symbol"] in winners
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
            "momentum run finished",
            sessions=int(str(ctx.state["sessions"])),
        )
