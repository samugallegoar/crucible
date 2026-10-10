"""Multiple strategies sharing one portfolio (ADR-0030).

``MultiStrategy`` itself satisfies ``Strategy`` -- the engine still runs
exactly one top-level strategy, exactly as before; this composite is how
several *independent* ``Strategy`` implementations (their own params,
their own ``ctx.state``) run inside that one engine call, all trading
through the same ledger/positions/cash. Nothing about ``BacktestEngine``'s
loop, the risk engine, or execution changes -- a sub-strategy's order is
indistinguishable from a single-strategy run's order except for the
``strategy_id`` tag that flows through for attribution
(``crucible.analytics.attribution``).

Every event is broadcast to every sub-strategy, unfiltered (a
documented simplification, ADR-0030): sub-strategies already see the
full shared portfolio via ``ctx.portfolio``, so seeing every fill/order
update too is consistent, not a new leak. A sub-strategy that only cares
about its own activity can filter by ``event.strategy_id``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from crucible.core import checkpoint as ckpt
from crucible.core.errors import CheckpointError, ConfigurationError
from crucible.strategy.context import BacktestContext
from crucible.strategy.interfaces import StatefulStrategy

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crucible.accounting.interfaces import PortfolioView
    from crucible.core.interfaces import (
        ClockEvent,
        DataEvent,
        FillEvent,
        MarketEvent,
        OrderUpdateEvent,
    )
    from crucible.core.types import StrategyId
    from crucible.strategy.interfaces import Context, Strategy


class MultiStrategy:
    """Satisfies ``Strategy``. ``strategies`` order is dispatch order
    (deterministic -- a plain ``dict`` preserves insertion order); every
    sub-strategy sees the same shared portfolio and market data, its own
    ``ctx.state``, and (if given) its own ``params``."""

    def __init__(
        self,
        strategies: Mapping[StrategyId, Strategy],
        params: Mapping[StrategyId, Mapping[str, object]] | None = None,
    ) -> None:
        if not strategies:
            msg = "MultiStrategy needs at least one strategy"
            raise ConfigurationError(msg)
        self._strategies = dict(strategies)
        self._params = dict(params or {})
        self._contexts: dict[StrategyId, BacktestContext] = {}

    @property
    def child_strategies(self) -> Mapping[StrategyId, Strategy]:
        """The composed strategies (read-only): the engine's state check looks at
        each child that is not itself a ``StatefulStrategy`` (ADR-0048)."""
        return dict(self._strategies)

    def _build_contexts(self, ctx: Context) -> None:
        def _portfolio_provider() -> PortfolioView:
            return ctx.portfolio

        for strategy_id in self._strategies:
            self._contexts[strategy_id] = BacktestContext(
                clock=ctx.clock,
                data=ctx.data,
                portfolio_provider=_portfolio_provider,
                orders=ctx.orders.with_strategy_id(strategy_id),
                targets=ctx.targets.with_strategy_id(strategy_id),
                log=ctx.log,
                params=self._params.get(strategy_id, ctx.params),
            )

    def on_start(self, ctx: Context) -> None:
        self._build_contexts(ctx)
        for strategy_id, strategy in self._strategies.items():
            strategy.on_start(self._contexts[strategy_id])

    def checkpoint_state(self) -> Mapping[str, object]:
        """Each sub-strategy's own ``ctx.state`` plus the state its
        ``StatefulStrategy`` hook exports (ADR-0042)."""
        children: dict[str, object] = {}
        for strategy_id, strategy in self._strategies.items():
            if isinstance(strategy, StatefulStrategy):
                children[str(strategy_id)] = dict(strategy.checkpoint_state())
        return {
            "contexts": {str(sid): dict(c.state) for sid, c in self._contexts.items()},
            "children": children,
        }

    def restore_state(self, ctx: Context, state: Mapping[str, object]) -> None:
        """Rebuilds the sub-contexts (``on_start`` is not called on resume)
        and restores each sub-strategy's state."""
        saved = ckpt.field_dict(state, "contexts")
        expected = {str(strategy_id) for strategy_id in self._strategies}
        if set(saved) != expected:
            msg = (
                f"checkpoint has sub-strategies {sorted(saved)} but this MultiStrategy has "
                f"{sorted(expected)}; resume with the same strategies"
            )
            raise CheckpointError(msg)
        self._build_contexts(ctx)
        children = ckpt.field_dict(state, "children")
        for strategy_id, strategy in self._strategies.items():
            sub_context = self._contexts[strategy_id]
            sub_context.state.update(ckpt.expect(saved[str(strategy_id)], dict, "context state"))
            if isinstance(strategy, StatefulStrategy):
                strategy.restore_state(
                    sub_context, ckpt.expect(children.get(str(strategy_id)), dict, "child state")
                )

    def on_market(self, ctx: Context, event: MarketEvent) -> None:
        for strategy_id, strategy in self._strategies.items():
            strategy.on_market(self._contexts[strategy_id], event)

    def on_data(self, ctx: Context, event: DataEvent) -> None:
        for strategy_id, strategy in self._strategies.items():
            strategy.on_data(self._contexts[strategy_id], event)

    def on_order_update(self, ctx: Context, event: OrderUpdateEvent) -> None:
        for strategy_id, strategy in self._strategies.items():
            strategy.on_order_update(self._contexts[strategy_id], event)

    def on_fill(self, ctx: Context, event: FillEvent) -> None:
        for strategy_id, strategy in self._strategies.items():
            strategy.on_fill(self._contexts[strategy_id], event)

    def on_session(self, ctx: Context, event: ClockEvent) -> None:
        for strategy_id, strategy in self._strategies.items():
            strategy.on_session(self._contexts[strategy_id], event)

    def on_end(self, ctx: Context) -> None:
        for strategy_id, strategy in self._strategies.items():
            strategy.on_end(self._contexts[strategy_id])
