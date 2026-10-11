"""Order Protocols: the order object, submission API, and state machine.

State machine:
``CREATED -> SUBMITTED -> ACCEPTED -> {PARTIALLY_FILLED -> FILLED | CANCELLED |
REJECTED | EXPIRED}``. Illegal transitions raise ``IllegalOrderTransition``;
the allowed-transition table is code in ``crucible.orders``, not a
convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

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

MOC_CUTOFF_NS = 10 * 60 * 10**9
"""Market-on-close orders must reach the market this long before the session close: NYSE and
Nasdaq stop accepting them at 15:50 ET for a 16:00 close. Crucible applies the same ten minutes on
every exchange calendar (ADR-0074); a later order is rejected, never filled at the close."""


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderSpec:
    """A complete order request. ``trail_bps`` is for TRAILING_STOP,
    ``algo_bars`` for TWAP/VWAP slicing, ``algo_rate`` for PARTICIPATION.
    ``strategy_id`` (ADR-0030) attributes the order to one
    strategy in a multi-strategy run; ``None`` for a single-strategy run
    or an engine-generated order (e.g. a risk-engine FLATTEN)."""

    symbol: Symbol
    side: OrderSide
    qty: Decimal
    type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    tif: TimeInForce = TimeInForce.GTC
    trail_bps: float | None = None
    algo_bars: int | None = None
    algo_rate: float | None = None
    strategy_id: StrategyId | None = None
    close_at: TimestampNs | None = None
    """MARKET_ON_CLOSE only: the session close (UTC ns) whose closing price the order takes."""


class Order(Protocol):
    """Read-only view of an order. State changes only via the OrderManager."""

    id: OrderId
    symbol: Symbol
    side: OrderSide
    type: OrderType
    qty: Decimal
    limit_price: float | None
    stop_price: float | None
    tif: TimeInForce
    created_at: TimestampNs
    strategy_id: StrategyId | None

    @property
    def state(self) -> OrderState: ...

    @property
    def filled_qty(self) -> Decimal: ...

    @property
    def remaining_qty(self) -> Decimal: ...


class OrderSubmitter(Protocol):
    """The strategy-facing order API (``ctx.orders``). Submission is a request;
    acceptance arrives later as an ``OrderUpdateEvent`` after modeled latency."""

    def with_strategy_id(self, strategy_id: StrategyId) -> OrderSubmitter:
        """A submitter that stamps every order it places with
        ``strategy_id`` (ADR-0030) -- how a multi-strategy run
        (``strategy.multi.MultiStrategy``) attributes each sub-strategy's
        orders for post-hoc PnL attribution."""
        ...

    def submit(
        self,
        symbol: Symbol,
        side: OrderSide,
        qty: Decimal,
        type: OrderType = ...,
        limit_price: float | None = None,
        stop_price: float | None = None,
        tif: TimeInForce = ...,
    ) -> OrderId: ...

    def place(self, spec: OrderSpec) -> OrderId:
        """Full-featured single-order submission (stops, trailing, algos)."""
        ...

    def submit_bracket(
        self, entry: OrderSpec, take_profit: float, stop_loss: float
    ) -> tuple[OrderId, OrderId, OrderId]:
        """Entry + opposite-side take-profit LIMIT and stop-loss STOP children,
        OCO-linked, activated when the entry fills. Returns
        (entry_id, take_profit_id, stop_loss_id)."""
        ...

    def submit_oco(self, first: OrderSpec, second: OrderSpec) -> tuple[OrderId, OrderId]:
        """Two live orders where a full fill of one cancels the other."""
        ...

    def submit_oto(self, first: OrderSpec, then: OrderSpec) -> tuple[OrderId, OrderId]:
        """``then`` stays dormant until ``first`` fully fills."""
        ...

    def cancel(self, order_id: OrderId) -> None:
        """Requests cancellation; it may lose the race against a fill."""
        ...


class OrderManager(Protocol):
    """Owns order state. The only component allowed to transition orders."""

    def get(self, order_id: OrderId) -> Order: ...

    def transition(self, order_id: OrderId, to_state: OrderState, ts: TimestampNs) -> None:
        """Applies a state transition. Raises ``IllegalOrderTransition`` with
        order id, current state, attempted state, and timestamp otherwise."""
        ...

    def resize(self, order_id: OrderId, new_qty: Decimal, ts: TimestampNs) -> None:
        """Shrinks an order's quantity before acceptance (risk engine
        RESIZE, ADR-0027). Raises if the order is already
        ``ACCEPTED`` or later, or if ``new_qty`` isn't positive."""
        ...

    def open_orders(self) -> list[Order]: ...
