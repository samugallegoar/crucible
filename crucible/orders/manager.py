"""In-memory order manager: the only component that transitions orders."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from crucible.core import checkpoint as ckpt
from crucible.core.errors import CrucibleError, IllegalOrderTransition
from crucible.core.types import (
    OrderId,
    OrderSide,
    OrderState,
    OrderType,
    StrategyId,
    Symbol,
    TimeInForce,
    TimestampNs,
)
from crucible.orders.state import TERMINAL_STATES, validate_transition

if TYPE_CHECKING:
    from collections.abc import Mapping


class ManagedOrder:
    """An order whose state only the :class:`InMemoryOrderManager` mutates.

    Satisfies ``crucible.orders.interfaces.Order``. Strategies receive this
    object but have no mutation API — state changes go through the manager.
    """

    def __init__(
        self,
        *,
        id: OrderId,
        symbol: Symbol,
        side: OrderSide,
        type: OrderType,
        qty: Decimal,
        limit_price: float | None,
        stop_price: float | None,
        tif: TimeInForce,
        created_at: TimestampNs,
        trail_bps: float | None = None,
        algo_bars: int | None = None,
        algo_rate: float | None = None,
        parent_id: OrderId | None = None,
        oco_with: OrderId | None = None,
        strategy_id: StrategyId | None = None,
    ) -> None:
        if qty <= 0:
            msg = f"order qty must be positive, got {qty} (order_id={id}, ts={created_at})"
            raise CrucibleError(msg)
        if type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and limit_price is None:
            msg = f"{type.name} order requires limit_price (order_id={id}, ts={created_at})"
            raise CrucibleError(msg)
        if type in (OrderType.STOP, OrderType.STOP_LIMIT) and stop_price is None:
            msg = f"{type.name} order requires stop_price (order_id={id}, ts={created_at})"
            raise CrucibleError(msg)
        if type is OrderType.TRAILING_STOP and trail_bps is None and stop_price is None:
            msg = (
                f"TRAILING_STOP requires trail_bps (and optionally an initial "
                f"stop_price) (order_id={id}, ts={created_at})"
            )
            raise CrucibleError(msg)
        if type in (OrderType.TWAP, OrderType.VWAP) and (algo_bars is None or algo_bars < 1):
            msg = f"{type.name} requires algo_bars >= 1 (order_id={id}, ts={created_at})"
            raise CrucibleError(msg)
        if type is OrderType.PARTICIPATION and (algo_rate is None or not 0 < algo_rate <= 1):
            msg = f"PARTICIPATION requires 0 < algo_rate <= 1 (order_id={id}, ts={created_at})"
            raise CrucibleError(msg)
        self.id = id
        self.symbol = symbol
        self.side = side
        self.type = type
        self.qty = qty
        self.limit_price = limit_price
        self.stop_price = stop_price
        self.tif = tif
        self.created_at = created_at
        self.trail_bps = trail_bps
        self.algo_bars = algo_bars
        self.algo_rate = algo_rate
        self.parent_id = parent_id
        self.oco_with = oco_with
        self.strategy_id = strategy_id
        self._state = OrderState.CREATED
        self._filled_qty = Decimal("0")

    @property
    def state(self) -> OrderState:
        return self._state

    @property
    def filled_qty(self) -> Decimal:
        return self._filled_qty

    @property
    def remaining_qty(self) -> Decimal:
        return self.qty - self._filled_qty


class InMemoryOrderManager:
    """Owns all orders of a run; satisfies ``OrderManager``."""

    def __init__(self) -> None:
        self._orders: dict[OrderId, ManagedOrder] = {}
        self._next_id = 0

    def create(
        self,
        *,
        symbol: Symbol,
        side: OrderSide,
        qty: Decimal,
        type: OrderType,
        limit_price: float | None,
        stop_price: float | None,
        tif: TimeInForce,
        ts: TimestampNs,
        trail_bps: float | None = None,
        algo_bars: int | None = None,
        algo_rate: float | None = None,
        parent_id: OrderId | None = None,
        oco_with: OrderId | None = None,
        strategy_id: StrategyId | None = None,
        order_id: OrderId | None = None,
    ) -> ManagedOrder:
        if order_id is None:
            order_id = OrderId(f"O-{self._next_id:08d}")
            self._next_id += 1
        elif order_id in self._orders:
            msg = f"order_id={order_id} already exists; explicit order ids must be unique"
            raise CrucibleError(msg)
        order = ManagedOrder(
            id=order_id,
            symbol=symbol,
            side=side,
            type=type,
            qty=qty,
            limit_price=limit_price,
            stop_price=stop_price,
            tif=tif,
            created_at=ts,
            trail_bps=trail_bps,
            algo_bars=algo_bars,
            algo_rate=algo_rate,
            parent_id=parent_id,
            oco_with=oco_with,
            strategy_id=strategy_id,
        )
        self._orders[order_id] = order
        return order

    def link_oco(self, a: OrderId, b: OrderId) -> None:
        """Marks two orders as one-cancels-other (used by bracket/OCO)."""
        self.get(a).oco_with = b
        self.get(b).oco_with = a

    def get(self, order_id: OrderId) -> ManagedOrder:
        try:
            return self._orders[order_id]
        except KeyError:
            msg = f"unknown order_id={order_id}; it was never created in this run"
            raise CrucibleError(msg) from None

    def transition(self, order_id: OrderId, to_state: OrderState, ts: TimestampNs) -> None:
        order = self.get(order_id)
        validate_transition(order_id, order.state, to_state, ts)
        order._state = to_state

    def resize(self, order_id: OrderId, new_qty: Decimal, ts: TimestampNs) -> None:
        """Shrinks an order's quantity before it has started filling (the
        risk engine's RESIZE action, ADR-0027). Only legal
        before ``ACCEPTED`` -- an order already live at the execution
        simulator has no well-defined "resize a fill in progress"
        semantics, and none is needed: pre-trade risk checks run before
        acceptance."""
        order = self.get(order_id)
        if order.state not in (OrderState.CREATED, OrderState.SUBMITTED):
            msg = (
                f"cannot resize order {order_id} in state {order.state.name} "
                f"(ts={ts}); resize is only legal before ACCEPTED"
            )
            raise CrucibleError(msg)
        if new_qty <= 0:
            msg = f"resize qty must be positive, got {new_qty} (order_id={order_id}, ts={ts})"
            raise CrucibleError(msg)
        order.qty = new_qty

    def apply_fill(self, order_id: OrderId, qty: Decimal, ts: TimestampNs) -> None:
        """Records executed quantity and moves state accordingly. Overfills
        raise: the simulator must never fill more than was ordered."""
        order = self.get(order_id)
        if qty <= 0:
            msg = f"fill qty must be positive, got {qty} (order_id={order_id}, ts={ts})"
            raise CrucibleError(msg)
        if qty > order.remaining_qty:
            msg = (
                f"overfill: qty={qty} > remaining={order.remaining_qty} "
                f"(order_id={order_id}, ts={ts})"
            )
            raise IllegalOrderTransition(msg)
        new_filled = order._filled_qty + qty
        to_state = OrderState.FILLED if new_filled == order.qty else OrderState.PARTIALLY_FILLED
        validate_transition(order_id, order.state, to_state, ts)
        order._filled_qty = new_filled
        order._state = to_state

    def open_orders(self) -> list[ManagedOrder]:
        """Orders that can still fill, in creation order (deterministic)."""
        return [o for o in self._orders.values() if o.state not in TERMINAL_STATES]

    def all_orders(self) -> list[ManagedOrder]:
        return list(self._orders.values())

    def snapshot(self) -> dict[str, object]:
        """The id counter and every order's fields, state and fill, in insertion order."""
        return {
            "next_id": self._next_id,
            "orders": [
                {
                    "id": o.id,
                    "symbol": o.symbol,
                    "side": o.side,
                    "type": o.type,
                    "qty": o.qty,
                    "limit_price": o.limit_price,
                    "stop_price": o.stop_price,
                    "tif": o.tif,
                    "created_at": int(o.created_at),
                    "trail_bps": o.trail_bps,
                    "algo_bars": o.algo_bars,
                    "algo_rate": o.algo_rate,
                    "parent_id": o.parent_id,
                    "oco_with": o.oco_with,
                    "strategy_id": o.strategy_id,
                    "state": o.state,
                    "filled_qty": o.filled_qty,
                }
                for o in self._orders.values()
            ],
        }

    def restore(self, state: Mapping[str, object]) -> None:
        """Rebuilds every order through the constructor (its validation still
        applies), then sets ``_state``/``_filled_qty`` directly. That direct
        assignment is the one restore-only path that bypasses the transition
        table: the saved state was reached legally in the original run
        (ADR-0041)."""
        orders: dict[OrderId, ManagedOrder] = {}
        for entry in ckpt.field_list(state, "orders"):
            raw = ckpt.expect(entry, dict, "order entry")
            parent = ckpt.optional_field(raw, "parent_id", str)
            oco = ckpt.optional_field(raw, "oco_with", str)
            strategy = ckpt.optional_field(raw, "strategy_id", str)
            order = ManagedOrder(
                id=OrderId(ckpt.field(raw, "id", str)),
                symbol=Symbol(ckpt.field(raw, "symbol", str)),
                side=ckpt.field(raw, "side", OrderSide),
                type=ckpt.field(raw, "type", OrderType),
                qty=ckpt.field(raw, "qty", Decimal),
                limit_price=ckpt.optional_number(raw, "limit_price"),
                stop_price=ckpt.optional_number(raw, "stop_price"),
                tif=ckpt.field(raw, "tif", TimeInForce),
                created_at=TimestampNs(ckpt.field(raw, "created_at", int)),
                trail_bps=ckpt.optional_number(raw, "trail_bps"),
                algo_bars=ckpt.optional_field(raw, "algo_bars", int),
                algo_rate=ckpt.optional_number(raw, "algo_rate"),
                parent_id=OrderId(parent) if parent is not None else None,
                oco_with=OrderId(oco) if oco is not None else None,
                strategy_id=StrategyId(strategy) if strategy is not None else None,
            )
            order._state = ckpt.field(raw, "state", OrderState)
            order._filled_qty = ckpt.field(raw, "filled_qty", Decimal)
            orders[order.id] = order
        self._orders = orders
        self._next_id = ckpt.field(state, "next_id", int)
