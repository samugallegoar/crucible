"""Live-parity Protocols: ``Broker`` and ``DataFeed``.

Live parity is achieved by interface design: the backtest execution simulator,
the paper broker, and any real broker adapter all stand behind ``Broker``, and
the strategy cannot tell them apart.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from decimal import Decimal
from typing import Literal, Protocol

from crucible.core.interfaces import Event
from crucible.core.types import Currency, OrderId, OrderState, Symbol
from crucible.orders.interfaces import OrderSpec


class Broker(Protocol):
    """Order routing plus account state, identical across backtest/paper/live.

    Defined in ADR-0040. ``submit`` takes an ``OrderSpec`` (what
    strategies emit), never the internal ``Order``. Single orders only:
    bracket/OCO/OTO have no ``Broker`` counterpart yet (known gap).
    """

    def submit(self, spec: OrderSpec) -> OrderId:
        """Route one order. Acceptance and fills arrive later, after modeled
        latency; observe them via ``order_state``."""
        ...

    def cancel(self, order_id: OrderId) -> None:
        """Request cancellation; it may lose the race against a fill."""
        ...

    def order_state(self, order_id: OrderId) -> OrderState:
        """Current state of an order. Raises ``CrucibleError`` (naming the
        order id and the simulation time) for an id the broker never issued."""
        ...

    def positions(self) -> Mapping[Symbol, Decimal]:
        """Signed non-zero quantities per symbol, as of the current time."""
        ...

    def cash(self) -> Mapping[Currency, Decimal]:
        """Total ledger cash per currency as of the current time (not
        settled-only: settlement lag, ADR-0028, does not reduce this)."""
        ...


class DataFeed(Protocol):
    """A time-ordered event source. In backtests it replays stored data through
    the PIT store; in paper/live it wraps a vendor stream at the I/O boundary."""

    stamping: Literal["eager", "lazy"]

    def subscribe(self, symbols: frozenset[Symbol]) -> None: ...

    def events(self) -> Iterator[Event]:
        """Events in non-decreasing ``ts`` order; ties broken by ``seq``.

        Stamping: an ``"eager"`` feed stamps every event (calling
        ``next_event_id``/``next_seq``) inside ``events()`` before the run
        starts; a ``"lazy"`` feed stamps each event when the engine pulls it
        (ADR-0044). A feed must declare which it is in ``stamping``.
        """
        ...


class LazyDataFeed(DataFeed, Protocol):
    """A lazily stamping feed must save and restore its own position, because
    at a session boundary it has already pulled ahead of the engine."""

    def snapshot(self) -> dict[str, object]: ...

    def restore(self, state: Mapping[str, object]) -> None: ...
