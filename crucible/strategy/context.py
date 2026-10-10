"""The concrete Context handed to strategies by the backtest runtime.

Everything here is a *view* or a *request channel*: data access is PIT-only,
the portfolio is read-only, and orders are requests routed through the
engine. There is no object on this surface that can mutate ledger state.
"""

from __future__ import annotations

from dataclasses import replace as _replace
from typing import TYPE_CHECKING, Protocol

from crucible.core.types import OrderType, TimeInForce
from crucible.orders.interfaces import OrderSpec

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, MutableMapping
    from decimal import Decimal

    from crucible.accounting.interfaces import PortfolioView
    from crucible.core.interfaces import Clock
    from crucible.core.types import OrderId, OrderSide, StrategyId, Symbol
    from crucible.data.interfaces import PITAccessor
    from crucible.orders.interfaces import OrderSubmitter
    from crucible.portfolio.interfaces import TargetSetter
    from crucible.strategy.interfaces import StrategyLogger


class OrderRouting(Protocol):
    """What the engine exposes to the submitter facade."""

    def submit_spec(self, spec: OrderSpec) -> OrderId: ...

    def submit_bracket(
        self, entry: OrderSpec, take_profit: float, stop_loss: float
    ) -> tuple[OrderId, OrderId, OrderId]: ...

    def submit_oco(self, first: OrderSpec, second: OrderSpec) -> tuple[OrderId, OrderId]: ...

    def submit_oto(self, first: OrderSpec, then: OrderSpec) -> tuple[OrderId, OrderId]: ...

    def cancel_order(self, order_id: OrderId) -> None: ...


class EngineOrderSubmitter:
    """Satisfies ``OrderSubmitter``; forwards to the engine's routing hooks.
    ``strategy_id`` (ADR-0030), when set, is stamped onto every
    spec this instance submits -- ``with_strategy_id`` produces a tagged
    clone sharing the same routing, one per sub-strategy in a
    multi-strategy run (``strategy.multi.MultiStrategy``)."""

    def __init__(self, routing: OrderRouting, strategy_id: StrategyId | None = None) -> None:
        self._routing = routing
        self._strategy_id = strategy_id

    def with_strategy_id(self, strategy_id: StrategyId) -> EngineOrderSubmitter:
        return EngineOrderSubmitter(self._routing, strategy_id)

    def _tag(self, spec: OrderSpec) -> OrderSpec:
        return spec if self._strategy_id is None else _replace(spec, strategy_id=self._strategy_id)

    def submit(
        self,
        symbol: Symbol,
        side: OrderSide,
        qty: Decimal,
        type: OrderType | None = None,
        limit_price: float | None = None,
        stop_price: float | None = None,
        tif: TimeInForce | None = None,
    ) -> OrderId:
        return self._routing.submit_spec(
            self._tag(
                OrderSpec(
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    type=type if type is not None else OrderType.MARKET,
                    limit_price=limit_price,
                    stop_price=stop_price,
                    tif=tif if tif is not None else TimeInForce.GTC,
                )
            )
        )

    def place(self, spec: OrderSpec) -> OrderId:
        return self._routing.submit_spec(self._tag(spec))

    def submit_bracket(
        self, entry: OrderSpec, take_profit: float, stop_loss: float
    ) -> tuple[OrderId, OrderId, OrderId]:
        return self._routing.submit_bracket(self._tag(entry), take_profit, stop_loss)

    def submit_oco(self, first: OrderSpec, second: OrderSpec) -> tuple[OrderId, OrderId]:
        return self._routing.submit_oco(self._tag(first), self._tag(second))

    def submit_oto(self, first: OrderSpec, then: OrderSpec) -> tuple[OrderId, OrderId]:
        return self._routing.submit_oto(self._tag(first), self._tag(then))

    def cancel(self, order_id: OrderId) -> None:
        self._routing.cancel_order(order_id)


class TargetRouting(Protocol):
    """What the engine exposes to the target-setter facade (ADR-0029): turning declared weights
    into orders needs engine-internal
    state (current marks, positions, FX rates) a strategy never sees
    directly. ``strategy_id`` (ADR-0030) attributes the
    resulting order the same way ``EngineOrderSubmitter`` does."""

    def resolve_target(
        self, symbol: Symbol, weight: float, strategy_id: StrategyId | None = None
    ) -> None: ...

    def resolve_targets(
        self, weights: Mapping[Symbol, float], strategy_id: StrategyId | None = None
    ) -> None: ...


class EngineTargetSetter:
    """Satisfies ``TargetSetter``; forwards to the engine's resolution
    hooks, exactly mirroring ``EngineOrderSubmitter`` (including
    ``with_strategy_id``, ADR-0030)."""

    def __init__(self, routing: TargetRouting, strategy_id: StrategyId | None = None) -> None:
        self._routing = routing
        self._strategy_id = strategy_id

    def with_strategy_id(self, strategy_id: StrategyId) -> EngineTargetSetter:
        return EngineTargetSetter(self._routing, strategy_id)

    def set(self, symbol: Symbol, weight: float) -> None:
        self._routing.resolve_target(symbol, weight, self._strategy_id)

    def set_all(self, weights: Mapping[Symbol, float]) -> None:
        self._routing.resolve_targets(weights, self._strategy_id)


class BacktestContext:
    """Satisfies ``crucible.strategy.interfaces.Context``."""

    def __init__(
        self,
        *,
        clock: Clock,
        data: PITAccessor,
        portfolio_provider: Callable[[], PortfolioView],
        orders: OrderSubmitter,
        targets: TargetSetter,
        log: StrategyLogger,
        params: Mapping[str, object],
    ) -> None:
        self._clock = clock
        self._data = data
        self._portfolio_provider = portfolio_provider
        self._orders = orders
        self._targets = targets
        self._log = log
        self._params = dict(params)
        self._state: dict[str, object] = {}

    @property
    def clock(self) -> Clock:
        return self._clock

    @property
    def data(self) -> PITAccessor:
        return self._data

    @property
    def portfolio(self) -> PortfolioView:
        return self._portfolio_provider()

    @property
    def orders(self) -> OrderSubmitter:
        return self._orders

    @property
    def targets(self) -> TargetSetter:
        return self._targets

    @property
    def log(self) -> StrategyLogger:
        return self._log

    @property
    def state(self) -> MutableMapping[str, object]:
        return self._state

    @property
    def params(self) -> Mapping[str, object]:
        return self._params
