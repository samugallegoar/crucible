"""Buys the UP side of a Polymarket five-minute contract when it is cheap and holds it to the
outcome (example strategy, ADR-0054).

Timing: it reacts to the bar it is given (a closed one-second or two-second mid), so it uses no
data from after that bar. The order is a market GTC order that fills at the next bar (Level 1,
ADR-0010). Positions are never closed by the strategy: at the window end the settlement bar
prices the contract at 1.0 or 0.001 and the ``delisting`` action liquidates it (ADR-0052).

Params (from config): ``threshold`` (buy when the bar's close is below it) and ``quantity``
(contracts per window).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from crucible.core.types import OrderSide

if TYPE_CHECKING:
    from crucible.core.events import BarEvent
    from crucible.strategy.context import BacktestContext


class BuyCheapUp:
    """One buy per UP contract, the first time its price is below the threshold."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["bought"] = []

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        symbol = str(event.symbol)
        if not symbol.endswith("-UP"):
            return
        bought = ctx.state["bought"]
        assert isinstance(bought, list)
        if symbol in bought:
            return
        if event.close >= float(str(ctx.params["threshold"])):
            return
        bought.append(symbol)
        ctx.orders.submit(event.symbol, OrderSide.BUY, Decimal(str(ctx.params["quantity"])))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...
