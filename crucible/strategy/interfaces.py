"""Strategy-facing Protocols: ``Strategy`` and ``Context``.

The same strategy object runs under backtest, paper, and live runtimes; only
the runtime differs, and the strategy cannot tell which one it is in.
Strategies emit orders/targets through the context and never mutate portfolio
or ledger state — there is no mutating handle to leak.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Protocol, runtime_checkable

from crucible.accounting.interfaces import PortfolioView
from crucible.core.interfaces import (
    Clock,
    ClockEvent,
    DataEvent,
    FillEvent,
    MarketEvent,
    OrderUpdateEvent,
)
from crucible.data.interfaces import PITAccessor
from crucible.orders.interfaces import OrderSubmitter
from crucible.portfolio.interfaces import TargetSetter


class StrategyLogger(Protocol):
    """Structured logger handed to strategies; entries carry event/order ids."""

    def info(self, msg: str, /, **fields: object) -> None: ...

    def warning(self, msg: str, /, **fields: object) -> None: ...


class Context(Protocol):
    """Everything a strategy may touch. Data access is PIT-only via ``data``;
    ``portfolio`` is read-only; ``state`` is serializable for checkpoint/resume."""

    @property
    def clock(self) -> Clock: ...

    @property
    def data(self) -> PITAccessor: ...

    @property
    def portfolio(self) -> PortfolioView: ...

    @property
    def orders(self) -> OrderSubmitter: ...

    @property
    def targets(self) -> TargetSetter: ...

    @property
    def log(self) -> StrategyLogger: ...

    @property
    def state(self) -> MutableMapping[str, object]: ...

    @property
    def params(self) -> Mapping[str, object]: ...


class Strategy(Protocol):
    """Event handlers a strategy implements. All handlers are optional in
    spirit but explicit in type: implement them all, empty where unused."""

    def on_start(self, ctx: Context) -> None: ...

    def on_market(self, ctx: Context, event: MarketEvent) -> None: ...

    def on_data(self, ctx: Context, event: DataEvent) -> None: ...

    def on_order_update(self, ctx: Context, event: OrderUpdateEvent) -> None: ...

    def on_fill(self, ctx: Context, event: FillEvent) -> None: ...

    def on_session(self, ctx: Context, event: ClockEvent) -> None: ...

    def on_end(self, ctx: Context) -> None: ...


@runtime_checkable
class StatefulStrategy(Protocol):
    """Optional: a strategy whose resumable state does not live entirely in
    ``ctx.state`` (E7, ADR-0042).

    ``checkpoint_state()`` returns a mapping of codec-supported values, stored
    in the checkpoint. On resume the engine calls ``restore_state`` **instead
    of** ``on_start`` (re-running ``on_start`` would clobber restored state).
    ``MultiStrategy`` implements this because its sub-strategies' contexts are
    built in ``on_start``. A class attribute ``STATE_VERSION: int`` (default 1)
    is recorded in the checkpoint; a mismatch refuses the resume.
    """

    def checkpoint_state(self) -> Mapping[str, object]: ...

    def restore_state(self, ctx: Context, state: Mapping[str, object]) -> None: ...
