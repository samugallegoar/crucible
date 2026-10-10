"""Paper broker: a facade over the backtest engine (ADR-0040).

It is NOT in the strategy's order path in this piece: strategies still submit
through ``ctx.orders`` -> ``engine.submit_spec`` -> risk -> simulator. This
facade gives external code the ``Broker`` surface over the same engine, so
orders submitted here go through ``engine.submit_spec`` and therefore risk,
exactly as a strategy's do. A real adapter in the order path is not part of this runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from crucible.core.errors import CrucibleError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from decimal import Decimal

    from crucible.core.engine import BacktestEngine
    from crucible.core.types import Currency, OrderId, OrderState, Symbol
    from crucible.orders.interfaces import OrderSpec


class PaperBroker:
    """Satisfies ``crucible.live.interfaces.Broker`` over a ``BacktestEngine``."""

    def __init__(self, engine: BacktestEngine) -> None:
        self._engine = engine

    def submit(self, spec: OrderSpec) -> OrderId:
        return self._engine.submit_spec(spec)

    def cancel(self, order_id: OrderId) -> None:
        self._engine.cancel_order(order_id)

    def order_state(self, order_id: OrderId) -> OrderState:
        try:
            return self._engine.order_manager.get(order_id).state
        except CrucibleError as exc:
            msg = f"{exc} (ts={self._engine.balances().ts}); order ids come from Broker.submit"
            raise CrucibleError(msg) from None

    def positions(self) -> Mapping[Symbol, Decimal]:
        return {
            symbol: position.qty
            for symbol, position in self._engine.balances().positions.items()
            if position.qty != 0
        }

    def cash(self) -> Mapping[Currency, Decimal]:
        return dict(self._engine.balances().cash)
