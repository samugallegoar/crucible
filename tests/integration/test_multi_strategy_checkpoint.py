"""MultiStrategy resumes with every sub-strategy's own ctx.state (ADR-0042)."""

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

from crucible.core.checkpoint import read_checkpoint
from crucible.core.errors import CheckpointError
from crucible.core.events import BarEvent
from crucible.core.types import OrderSide, StrategyId, TimestampNs
from crucible.strategy.context import BacktestContext
from crucible.strategy.interfaces import StatefulStrategy
from crucible.strategy.multi import MultiStrategy


class Sub:
    """Counts bars in its own ctx.state and buys ``symbol`` once."""

    def __init__(self, symbol: str, sink: dict[str, int]) -> None:
        self._symbol = symbol
        self._sink = sink

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["n"] = 0
        ctx.state["bought"] = False

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        n = ctx.state["n"]
        assert isinstance(n, int)
        ctx.state["n"] = n + 1
        if not ctx.state["bought"] and str(event.symbol) == self._symbol:
            ctx.state["bought"] = True
            ctx.orders.submit(event.symbol, OrderSide.BUY, Decimal("10"))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None:
        n = ctx.state["n"]
        assert isinstance(n, int)
        self._sink[self._symbol] = n


def _multi(sink: dict[str, int]) -> MultiStrategy:
    return MultiStrategy(
        {
            StrategyId("a"): Sub("DIVCO", sink),
            StrategyId("b"): Sub("SHORTCO", sink),
        }
    )


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    build_dividend_store(root)
    return root


def test_multi_strategy_is_stateful() -> None:
    assert isinstance(_multi({}), StatefulStrategy)


def test_resume_carries_each_sub_strategys_state(store: Path, tmp_path: Path) -> None:
    baseline_sink: dict[str, int] = {}
    baseline = make_engine(store, strategy=_multi(baseline_sink)).run()

    path = tmp_path / "c.json"
    engine = make_engine(store, strategy=_multi({}))
    engine.run_until(TimestampNs(3 * DAY))
    engine.checkpoint(path)
    _, payload = read_checkpoint(path)
    assert isinstance(payload, dict)
    contexts = payload["strategy_state"]["contexts"]  # type: ignore[index]
    assert set(contexts) == {"a", "b"}
    assert contexts["a"]["n"] > 0  # non-vacuous: sub-state was really captured

    resumed_sink: dict[str, int] = {}
    resumed = make_engine(store, strategy=_multi(resumed_sink))
    resumed.resume_from(path)
    assert_same_result(resumed.run(), baseline)
    assert resumed_sink == baseline_sink  # each sub-strategy's counter continued, not restarted


def test_different_sub_strategy_set_is_refused_by_the_setup_fingerprint(
    store: Path, tmp_path: Path
) -> None:
    path = tmp_path / "c.json"
    engine = make_engine(store, strategy=_multi({}))
    engine.run_until(TimestampNs(3 * DAY))
    engine.checkpoint(path)
    other = MultiStrategy({StrategyId("a"): Sub("DIVCO", {})})
    # the strategy's own attributes are part of the setup description, so the
    # engine refuses before MultiStrategy.restore_state is reached
    with pytest.raises(CheckpointError, match="setup differs"):
        make_engine(store, strategy=other).resume_from(path)


def test_restore_state_itself_refuses_a_different_sub_strategy_set() -> None:
    """Defense in depth: the hook checks the ids too, for a caller that bypasses
    the engine's fingerprint."""
    other = MultiStrategy({StrategyId("a"): Sub("DIVCO", {})})
    saved = {"contexts": {"a": {}, "b": {}}, "children": {}}
    with pytest.raises(CheckpointError, match="sub-strategies"):
        other.restore_state(None, saved)  # type: ignore[arg-type]  # refuses before using ctx
