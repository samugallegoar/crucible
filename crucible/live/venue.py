"""A local simulated venue (ADR-0043).

The venue is what a real adapter would be at the I/O boundary: it accepts
orders, keeps its own order state and account, and reports fills. Its
*pricing* delegates to the backtest fill models through a private
``LadderExecutionSimulator`` bound to the venue's own mirror order manager,
so a live run can be compared byte for byte with a backtest. Limits, stated
plainly: it is not an independent matching engine, it is single-currency,
single-order (no bracket/OCO/OTO, mirroring ``Broker``), and Level 0 (instant
fill from the current bar) is refused.

The venue's virtual clock only moves when ``place`` or ``on_bar`` is called
with a timestamp; it never reads wall-clock time. The RNG and ``MarketStats``
belong to the engine (the checkpoint saves them there), so the venue shares
them and does not snapshot them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from crucible.accounting.ledger import price_to_decimal
from crucible.core import checkpoint as ckpt
from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.core.types import (
    Currency,
    OrderId,
    OrderSide,
    OrderState,
    RealismLevel,
    Symbol,
    TimestampNs,
)
from crucible.execution.ladder import LadderExecutionSimulator
from crucible.orders.manager import InMemoryOrderManager
from crucible.orders.state import TERMINAL_STATES

if TYPE_CHECKING:
    from collections.abc import Mapping

    import numpy as np

    from crucible.core.events import BarEvent
    from crucible.execution.ladder import (
        CommissionModelLike,
        ExecutedFill,
        LatencyModelLike,
        OrderClosed,
        ParticipationLimits,
        PriceAdjusterLike,
        SpreadModelLike,
    )
    from crucible.execution.models import MarketStats
    from crucible.orders.interfaces import OrderSpec


class SimulatedVenue:
    """Satisfies ``crucible.live.interfaces.Broker`` and ``Snapshottable``."""

    def __init__(
        self,
        *,
        level: RealismLevel,
        spread: SpreadModelLike,
        latency: LatencyModelLike,
        slippage: PriceAdjusterLike,
        commission: CommissionModelLike,
        participation: ParticipationLimits | None,
        stats: MarketStats,
        rng: np.random.Generator,
        initial_cash: Decimal,
        base_currency: Currency,
    ) -> None:
        if level < RealismLevel.BASIC_FRICTION:
            msg = (
                "SimulatedVenue needs realism Level 1 or higher (BASIC_FRICTION): Level 0 "
                f"fills instantly from the current bar, which a venue cannot; got {level.name}"
            )
            raise ConfigurationError(msg)
        self._orders = InMemoryOrderManager()
        self._sim = LadderExecutionSimulator(
            level=level,
            order_manager=self._orders,
            spread=spread,
            latency=latency,
            slippage=slippage,
            commission=commission,
            participation=participation,
            stats=stats,
            rng=rng,
        )
        self._base = base_currency
        self._cash: dict[Currency, Decimal] = {base_currency: initial_cash}
        self._positions: dict[Symbol, Decimal] = {}
        self._now = TimestampNs(0)
        self._emitted = 0
        self._next_client = 0

    # ------------------------------------------------------------ order path

    def place(self, spec: OrderSpec, order_id: OrderId, ts: TimestampNs) -> None:
        """Accepts an order under the caller's id (a client order id)."""
        self._now = TimestampNs(max(int(self._now), int(ts)))
        order = self._orders.create(
            symbol=spec.symbol,
            side=spec.side,
            qty=spec.qty,
            type=spec.type,
            limit_price=spec.limit_price,
            stop_price=spec.stop_price,
            tif=spec.tif,
            ts=ts,
            trail_bps=spec.trail_bps,
            algo_bars=spec.algo_bars,
            algo_rate=spec.algo_rate,
            strategy_id=spec.strategy_id,
            order_id=order_id,
        )
        self._orders.transition(order.id, OrderState.SUBMITTED, ts)
        self._orders.transition(order.id, OrderState.ACCEPTED, ts)
        self._sim.on_order_submitted(order, None)  # Level >= 1: activates, no sync fills

    def cancel(self, order_id: OrderId) -> None:
        try:
            order = self._orders.get(order_id)
        except CrucibleError:
            return
        if order.state in TERMINAL_STATES:
            return
        self._orders.transition(order_id, OrderState.CANCELLED, self._now)
        self._sim.remove_pending(order_id)

    def on_bar(self, bar: BarEvent) -> tuple[list[ExecutedFill], list[OrderClosed]]:
        """Advances the virtual clock to ``bar`` and returns what happened.
        ``bar`` may carry a provisional id/seq: the venue reads only its data."""
        self._now = TimestampNs(max(int(self._now), int(bar.ts)))
        fills, closed = self._sim.on_bar(bar)
        for fill in fills:
            signed = fill.qty if fill.side is OrderSide.BUY else -fill.qty
            self._positions[fill.symbol] = self._positions.get(fill.symbol, Decimal(0)) + signed
            self._cash[self._base] -= signed * price_to_decimal(fill.price) + fill.commission
        self._emitted += len(fills) + len(closed)
        return fills, closed

    # -------------------------------------------------------- Broker surface

    def submit(self, spec: OrderSpec) -> OrderId:
        order_id = OrderId(f"V-{self._next_client:08d}")
        self._next_client += 1
        self.place(spec, order_id, self._now)
        return order_id

    def order_state(self, order_id: OrderId) -> OrderState:
        try:
            return self._orders.get(order_id).state
        except CrucibleError as exc:
            msg = f"{exc} (venue time {self._now}); order ids come from submit/place"
            raise CrucibleError(msg) from None

    def positions(self) -> dict[Symbol, Decimal]:
        return {symbol: qty for symbol, qty in self._positions.items() if qty != 0}

    def cash(self) -> dict[Currency, Decimal]:
        return dict(self._cash)

    def why_not_filled(self, order_id: OrderId) -> list[tuple[int, str]]:
        return self._sim.why_not_filled(order_id)

    # -------------------------------------------------- reconciliation, resume

    def summary(self) -> dict[str, object]:
        """What a resume compares against a checkpoint: how many fills and
        closures the venue has published, and its open orders."""
        return {
            "emitted": self._emitted,
            "open_orders": {str(o.id): str(o.filled_qty) for o in self._orders.open_orders()},
        }

    def snapshot(self) -> dict[str, object]:
        return {
            "orders": self._orders.snapshot(),
            "execution": self._sim.snapshot(),
            "cash": dict(self._cash),
            "positions": {str(symbol): qty for symbol, qty in self._positions.items()},
            "now": int(self._now),
            "emitted": self._emitted,
            "next_client": self._next_client,
        }

    def restore(self, state: Mapping[str, object]) -> None:
        self._orders.restore(ckpt.field_dict(state, "orders"))
        self._sim.restore(ckpt.field_dict(state, "execution"))
        self._cash = {
            Currency(key): ckpt.expect(value, Decimal, f"cash[{key}]")
            for key, value in ckpt.field_dict(state, "cash").items()
        }
        self._positions = {
            Symbol(key): ckpt.expect(value, Decimal, f"positions[{key}]")
            for key, value in ckpt.field_dict(state, "positions").items()
        }
        self._now = TimestampNs(ckpt.field(state, "now", int))
        self._emitted = ckpt.field(state, "emitted", int)
        self._next_client = ckpt.field(state, "next_client", int)
