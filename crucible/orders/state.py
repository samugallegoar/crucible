"""The order state machine (invariant I7).

The allowed-transition table is the enforcement, not documentation: every
state change funnels through ``validate_transition``.
"""

from __future__ import annotations

from crucible.core.errors import IllegalOrderTransition
from crucible.core.types import OrderId, OrderState, TimestampNs

ALLOWED_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    # CREATED -> CANCELLED: composite children (OTO/bracket) wait in CREATED
    # until the parent fills; if the parent dies first, they are cancelled
    # without ever being submitted.
    OrderState.CREATED: frozenset({OrderState.SUBMITTED, OrderState.CANCELLED}),
    OrderState.SUBMITTED: frozenset(
        {OrderState.ACCEPTED, OrderState.REJECTED, OrderState.CANCELLED}
    ),
    OrderState.ACCEPTED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.EXPIRED,
        }
    ),
    OrderState.PARTIALLY_FILLED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,  # successive partial fills
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.EXPIRED,
        }
    ),
    OrderState.FILLED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.REJECTED: frozenset(),
    OrderState.EXPIRED: frozenset(),
}

TERMINAL_STATES: frozenset[OrderState] = frozenset(
    state for state, allowed in ALLOWED_TRANSITIONS.items() if not allowed
)


def validate_transition(
    order_id: OrderId, current: OrderState, to_state: OrderState, ts: TimestampNs
) -> None:
    """Raises ``IllegalOrderTransition`` unless ``current -> to_state`` is allowed."""
    if to_state not in ALLOWED_TRANSITIONS[current]:
        msg = (
            f"illegal order transition {current.name} -> {to_state.name} "
            f"(order_id={order_id}, ts={ts}). Allowed from {current.name}: "
            f"{sorted(s.name for s in ALLOWED_TRANSITIONS[current]) or 'none (terminal)'}."
        )
        raise IllegalOrderTransition(msg)
