"""The execution backend seam (ADR-0043).

The engine drives one ``ExecutionBackend``: the in-process ladder simulator
(backtest, paper) or a venue-backed implementation (live). The Protocol is
exactly the surface the engine called on ``LadderExecutionSimulator`` before
the seam existed, so introducing it changes no behavior.

A backend is built by a factory that receives an ``ExecutionContext``: the
engine creates the RNG, ``MarketStats`` and order manager in ``__init__``, and
a backend that must draw from the same stream (the simulated venue, for
byte-identical parity) needs those objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

    import numpy as np

    from crucible.core.events import BarEvent
    from crucible.core.types import OrderId, RealismLevel, TimestampNs
    from crucible.execution.ladder import ExecutedFill, ExecutionSetup, OrderClosed
    from crucible.execution.models import MarketStats
    from crucible.orders.manager import InMemoryOrderManager, ManagedOrder


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """What the engine hands a backend factory. ``rng`` and ``stats`` are the
    engine's own objects (the checkpoint saves them there), so a backend must
    share them, never copy them."""

    level: RealismLevel
    order_manager: InMemoryOrderManager
    setup: ExecutionSetup
    stats: MarketStats
    rng: np.random.Generator


@runtime_checkable
class ExecutionBackend(Protocol):
    """Order execution as the engine sees it.

    ``supports_composite_orders`` is False for backends whose order path is
    single-order only (the venue); the engine then refuses bracket/OCO/OTO.
    A backend may also set ``supports_mid_mark_orders = False`` (optional,
    read with a default of True) when it cannot fill orders placed during a
    mark on the bar already pulled; the engine then refuses a risk FLATTEN.
    """

    supports_composite_orders: bool

    def on_order_submitted(
        self, order: ManagedOrder, current_bar: BarEvent | None
    ) -> list[ExecutedFill]:
        """Called right after the engine accepted ``order``. Returns fills that
        are known synchronously (Level 0 only); everything else arrives later."""
        ...

    def on_bar(self, bar: BarEvent) -> tuple[list[ExecutedFill], list[OrderClosed]]:
        """Called when the engine handles ``bar`` (before ``on_market``)."""
        ...

    def remove_pending(self, order_id: OrderId) -> None:
        """The engine cancelled or closed ``order_id``; stop working it."""
        ...

    def parent_died(self, parent_id: OrderId, ts: TimestampNs) -> list[OrderClosed]:
        """Cancels dormant children of a parent that ended unfilled."""
        ...

    def why_not_filled(self, order_id: OrderId) -> list[tuple[int, str]]:
        """Structured ``(ts, reason)`` trail for an order."""
        ...

    def snapshot(self) -> dict[str, object]:
        """Resumable state (see ``Snapshottable``)."""
        ...

    def restore(self, state: Mapping[str, object]) -> None:
        """Restores ``snapshot`` output in place."""
        ...
