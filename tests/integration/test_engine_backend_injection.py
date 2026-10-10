"""The engine drives whatever backend the factory builds (ADR-0043)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from checkpoint_support import (
    DAY,
    assert_same_result,
    build_dividend_store,
    make_engine,
)

from crucible.core.errors import ConfigurationError
from crucible.core.events import BarEvent
from crucible.core.types import OrderSide, Symbol
from crucible.execution.backend import ExecutionBackend, ExecutionContext
from crucible.execution.ladder import LadderExecutionSimulator
from crucible.orders.interfaces import OrderSpec
from crucible.strategy.context import BacktestContext


class Recording:
    """Delegates to a real ladder simulator and records the calls."""

    supports_composite_orders = True

    def __init__(self, inner: LadderExecutionSimulator) -> None:
        self.inner = inner
        self.calls: list[tuple[str, object]] = []

    def on_order_submitted(self, order: object, current_bar: object) -> list:  # type: ignore[type-arg]
        self.calls.append(("submitted", str(order.id)))  # type: ignore[attr-defined]
        return self.inner.on_order_submitted(order, current_bar)  # type: ignore[arg-type]

    def on_bar(self, bar: BarEvent) -> tuple[list, list]:  # type: ignore[type-arg]
        self.calls.append(("bar", int(bar.ts)))
        return self.inner.on_bar(bar)

    def remove_pending(self, order_id: object) -> None:
        self.inner.remove_pending(order_id)  # type: ignore[arg-type]

    def parent_died(self, parent_id: object, ts: object) -> list:  # type: ignore[type-arg]
        return self.inner.parent_died(parent_id, ts)  # type: ignore[arg-type]

    def why_not_filled(self, order_id: object) -> list[tuple[int, str]]:
        return self.inner.why_not_filled(order_id)  # type: ignore[arg-type]

    def snapshot(self) -> dict[str, object]:
        return self.inner.snapshot()

    def restore(self, state: object) -> None:
        self.inner.restore(state)  # type: ignore[arg-type]


def _ladder_for(ctx: ExecutionContext) -> LadderExecutionSimulator:
    return LadderExecutionSimulator(
        level=ctx.level,
        order_manager=ctx.order_manager,
        spread=ctx.setup.spread,
        latency=ctx.setup.latency,
        slippage=ctx.setup.slippage,
        commission=ctx.setup.commission,
        participation=ctx.setup.participation,
        stats=ctx.setup.stats,
        rng=ctx.rng,
    )


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    build_dividend_store(root)
    return root


def test_an_injected_backend_is_driven_and_changes_nothing(store: Path) -> None:
    built: list[Recording] = []

    def factory(ctx: ExecutionContext) -> ExecutionBackend:
        backend = Recording(_ladder_for(ctx))
        built.append(backend)
        return backend

    baseline = make_engine(store).run()
    injected = make_engine(store, execution_backend_factory=factory).run()
    assert_same_result(injected, baseline)
    kinds = [kind for kind, _ in built[0].calls]
    assert "submitted" in kinds
    assert "bar" in kinds


def test_the_default_backend_is_the_ladder_simulator(store: Path) -> None:
    engine = make_engine(store)
    assert isinstance(engine.execution, LadderExecutionSimulator)


class BracketOnce:
    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["done"] = False

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        if ctx.state["done"] or event.symbol != Symbol("DIVCO"):
            return
        ctx.state["done"] = True
        ctx.orders.submit_bracket(
            OrderSpec(symbol=Symbol("DIVCO"), side=OrderSide.BUY, qty=Decimal("10")),
            take_profit=60.0,
            stop_loss=40.0,
        )

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_order_update(self, ctx: object, event: object) -> None: ...

    def on_fill(self, ctx: object, event: object) -> None: ...

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: object) -> None: ...


def test_a_backend_without_composite_support_refuses_a_bracket(store: Path) -> None:
    class SingleOnly(Recording):
        supports_composite_orders = False

    def factory(ctx: ExecutionContext) -> ExecutionBackend:
        return SingleOnly(_ladder_for(ctx))

    engine = make_engine(store, strategy=BracketOnce(), execution_backend_factory=factory)
    with pytest.raises(ConfigurationError, match="single orders"):
        engine.run_until(DAY * 3)  # type: ignore[arg-type]
