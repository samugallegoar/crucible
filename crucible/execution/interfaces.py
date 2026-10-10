"""Execution Protocols: the realism ladder's pluggable pieces.

Pessimism assumptions (cross-cutting, enforced in code once implemented):
- Fills never occur outside the bar's ``[low, high]``; violations raise.
- Intrabar ambiguity resolves against the strategy; configurable only toward
  *more* pessimism.
- Nothing fills before the order could have reached the market (latency).

Every stochastic component takes an explicit ``numpy.random.Generator``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import numpy as np

from crucible.core.interfaces import MarketEvent
from crucible.core.types import FillId, OrderId, TimestampNs
from crucible.orders.interfaces import Order


@dataclass(frozen=True, slots=True)
class ProposedFill:
    """A fill a model proposes; the simulator validates it against bar bounds
    and participation caps before it becomes a ``FillEvent``.

    ``passive`` marks a resting limit executed at its own limit price
    (maker); aggressive fills (market, or limits filled at a better opening
    price) are takers. Commission schedules may price the two differently.
    """

    order_id: OrderId
    fill_id: FillId
    ts: TimestampNs
    qty: Decimal
    price: float
    passive: bool = False


class FillModel(Protocol):
    """Decides whether/how an order fills against a market event."""

    def propose(
        self,
        order: Order,
        market: MarketEvent,
        rng: np.random.Generator,
    ) -> list[ProposedFill]:
        """Zero or more fills, each within the event's price bounds.

        Timing: proposed ``ts`` must be >= the time the order reached the
        market (submission + latency).
        """
        ...


class SpreadModel(Protocol):
    """Half-spread in price terms at a moment (static or vol/time-of-day dynamic)."""

    def half_spread(self, market: MarketEvent, rng: np.random.Generator) -> float: ...


class SlippageModel(Protocol):
    """Adverse price adjustment applied to a reference price."""

    def adjusted_price(
        self,
        reference_price: float,
        order: Order,
        market: MarketEvent,
        rng: np.random.Generator,
    ) -> float:
        """Always weakly worse for the order's side than ``reference_price``."""
        ...


class LatencyModel(Protocol):
    """Delay between a component emitting an event and it taking effect."""

    def latency_ns(self, rng: np.random.Generator) -> int:
        """Non-negative delay in nanoseconds; seeded, never wall-clock derived."""
        ...


class CommissionModel(Protocol):
    """Commission on a fill; ``Decimal`` because it lands on the ledger."""

    def commission(self, fill: ProposedFill) -> Decimal: ...
