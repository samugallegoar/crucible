"""Venue-backed execution backend (ADR-0043).

The engine's ``ExecutionBackend`` for live runs: orders go to a venue and the
fills come back later as events through the feed, so this backend never
returns a synchronous fill. It is single-order only (``Broker`` has no
bracket/OCO/OTO), and the engine refuses composite orders while
``supports_composite_orders`` is False.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from crucible.core import checkpoint as ckpt
from crucible.core.errors import CheckpointError, ConfigurationError
from crucible.orders.interfaces import OrderSpec

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crucible.core.events import BarEvent
    from crucible.core.types import OrderId, TimestampNs
    from crucible.execution.ladder import ExecutedFill, OrderClosed
    from crucible.live.venue import SimulatedVenue
    from crucible.orders.manager import ManagedOrder


class VenueExecution:
    """Satisfies ``crucible.execution.backend.ExecutionBackend``."""

    supports_composite_orders = False
    # the venue has priced the next bar before a mark runs (ADR-0044): the engine
    # refuses a risk FLATTEN, whose orders would fill one bar late
    supports_mid_mark_orders = False

    def __init__(self, venue: SimulatedVenue) -> None:
        self._venue = venue
        self.restore_mode: Literal["restore", "external"] = "restore"

    @property
    def venue(self) -> SimulatedVenue:
        return self._venue

    def on_order_submitted(
        self, order: ManagedOrder, current_bar: BarEvent | None
    ) -> list[ExecutedFill]:
        if order.parent_id is not None or order.oco_with is not None:
            msg = (
                f"order {order.id} is part of a composite order; the venue backend accepts "
                "single orders only"
            )
            raise ConfigurationError(msg)
        self._venue.place(
            OrderSpec(
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                type=order.type,
                limit_price=order.limit_price,
                stop_price=order.stop_price,
                tif=order.tif,
                trail_bps=order.trail_bps,
                algo_bars=order.algo_bars,
                algo_rate=order.algo_rate,
                strategy_id=order.strategy_id,
            ),
            order.id,
            order.created_at,
        )
        return []

    def on_bar(self, bar: BarEvent) -> tuple[list[ExecutedFill], list[OrderClosed]]:
        return [], []

    def remove_pending(self, order_id: OrderId) -> None:
        self._venue.cancel(order_id)

    def parent_died(self, parent_id: OrderId, ts: TimestampNs) -> list[OrderClosed]:
        return []

    def why_not_filled(self, order_id: OrderId) -> list[tuple[int, str]]:
        return self._venue.why_not_filled(order_id)

    def snapshot(self) -> dict[str, object]:
        return {"venue": self._venue.snapshot(), "summary": self._venue.summary()}

    def restore(self, state: Mapping[str, object]) -> None:
        """``restore`` mode rebuilds the in-process venue from the checkpoint;
        ``external`` models a venue that kept running (its state is not
        restored) and any difference from the checkpoint is refused."""
        if self.restore_mode == "restore":
            self._venue.restore(ckpt.field_dict(state, "venue"))
            return
        self._reconcile(ckpt.field_dict(state, "summary"))

    def _reconcile(self, saved: Mapping[str, object]) -> None:
        now = self._venue.summary()
        differences: list[str] = []
        saved_position = ckpt.field(saved, "emitted", int)
        if saved_position != now["emitted"]:
            differences.append(
                f"stream position: checkpoint={saved_position}, venue={now['emitted']}"
            )
        saved_open = {
            key: str(value) for key, value in ckpt.field_dict(saved, "open_orders").items()
        }
        now_open = now["open_orders"]
        assert isinstance(now_open, dict)
        for order_id in sorted(set(saved_open) | set(now_open)):
            if saved_open.get(order_id) != now_open.get(order_id):
                differences.append(
                    f"order {order_id}: checkpoint filled={saved_open.get(order_id)}, "
                    f"venue filled={now_open.get(order_id)}"
                )
        if differences:
            msg = (
                "the venue does not match the checkpoint ("
                + "; ".join(differences)
                + "); resume with venue_state='restore' or reconcile the venue first"
            )
            raise CheckpointError(msg)
