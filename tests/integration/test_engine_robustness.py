"""Engine hardening (batch 1, ADR-0048): failed starts, setup-time refusals,
state held outside the checkpoint."""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from pathlib import Path

import pytest
from checkpoint_support import DAY, DIVCO, USD, build_dividend_store, make_engine

from crucible.core import checkpoint as ckpt
from crucible.core.errors import CheckpointError, ConfigurationError, CrucibleError
from crucible.core.events import BarEvent
from crucible.core.instruments import FuturesSpec
from crucible.core.types import StrategyId
from crucible.risk.engine import CompositeRiskEngine
from crucible.risk.interfaces import RiskAction, RiskDecision
from crucible.risk.limits import DrawdownHaltLimit, MarginCallLimit, MarginRequirementLimit
from crucible.strategy.context import BacktestContext
from crucible.strategy.multi import MultiStrategy


class _Hooks:
    """The strategy hooks a test strategy does not care about."""

    def on_start(self, ctx: BacktestContext) -> None: ...

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None: ...

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_order_update(self, ctx: object, event: object) -> None: ...

    def on_fill(self, ctx: object, event: object) -> None: ...

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: object) -> None: ...


class FailsOnStart(_Hooks):
    def on_start(self, ctx: BacktestContext) -> None:
        msg = "boom"
        raise RuntimeError(msg)


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    build_dividend_store(root)
    return root


def test_an_engine_whose_on_start_failed_is_unusable(store: Path) -> None:
    engine = make_engine(store, strategy=FailsOnStart())
    with pytest.raises(RuntimeError, match="boom"):
        engine.run()
    with pytest.raises(CrucibleError, match="failed during on_start"):
        engine.run()
    with pytest.raises(CrucibleError, match="failed during on_start"):
        engine.run_until(DAY)


_FUTURES = {DIVCO: FuturesSpec(multiplier=Decimal("50"))}


@pytest.mark.parametrize("kind", ["pre_trade", "mark"])
def test_margin_limits_with_futures_are_refused_at_setup(store: Path, kind: str) -> None:
    risk = (
        CompositeRiskEngine(USD, pre_trade_limits=[MarginRequirementLimit()])
        if kind == "pre_trade"
        else CompositeRiskEngine(USD, mark_limits=[MarginCallLimit()])
    )
    with pytest.raises(ConfigurationError, match=r"initial_margin.*DIVCO"):
        make_engine(store, risk_engine=risk, futures_specs=_FUTURES)


def test_margin_limits_without_futures_are_accepted(store: Path) -> None:
    risk = CompositeRiskEngine(
        USD, pre_trade_limits=[MarginRequirementLimit()], mark_limits=[MarginCallLimit()]
    )
    make_engine(store, risk_engine=risk)


class CountsOnSelf(_Hooks):
    """Violates the state contract: mutable state lives on ``self``."""

    def __init__(self) -> None:
        self.calls = 0

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        self.calls += 1


class StatefulCounter(CountsOnSelf):
    """The same counter, declared properly as a StatefulStrategy."""

    STATE_VERSION = 1

    def checkpoint_state(self) -> dict[str, object]:
        return {"calls": self.calls}

    def restore_state(self, ctx: object, state: dict[str, object]) -> None:
        self.calls = ckpt.field(state, "calls", int)


class CountingLimit:
    """A mark limit that keeps state but is not Snapshottable."""

    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def check(self, portfolio: object, ts: object, base_currency: object) -> RiskDecision:
        self.calls += 1
        return RiskDecision(RiskAction.ALLOW, "ok")


def test_a_strategy_that_keeps_state_on_self_cannot_be_checkpointed(
    store: Path, tmp_path: Path
) -> None:
    engine = make_engine(store, strategy=CountsOnSelf())
    engine.run_until(DAY * 3)  # type: ignore[arg-type]
    with pytest.raises(CheckpointError, match=r"strategy.*calls"):
        engine.checkpoint(tmp_path / "c.json")


def test_a_stateful_strategy_may_be_checkpointed(store: Path, tmp_path: Path) -> None:
    engine = make_engine(store, strategy=StatefulCounter())
    engine.run_until(DAY * 3)  # type: ignore[arg-type]
    engine.checkpoint(tmp_path / "c.json")
    assert (tmp_path / "c.json").exists()


def test_a_stateful_limit_that_is_not_snapshottable_cannot_be_checkpointed(
    store: Path, tmp_path: Path
) -> None:
    risk = CompositeRiskEngine(USD, mark_limits=[CountingLimit()])
    engine = make_engine(store, risk_engine=risk)
    engine.run_until(DAY * 3)  # type: ignore[arg-type]
    with pytest.raises(CheckpointError, match="CountingLimit"):
        engine.checkpoint(tmp_path / "c.json")


def test_a_snapshottable_limit_may_be_checkpointed(store: Path, tmp_path: Path) -> None:
    risk = CompositeRiskEngine(USD, mark_limits=[DrawdownHaltLimit(0.5)])
    engine = make_engine(store, risk_engine=risk)
    engine.run_until(DAY * 3)  # type: ignore[arg-type]
    engine.checkpoint(tmp_path / "c.json")
    assert (tmp_path / "c.json").exists()


class AppendsToDeque(_Hooks):
    """A rolling window kept on ``self``: the commonest way to break the contract."""

    def __init__(self) -> None:
        self.window: deque[float] = deque(maxlen=3)

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        self.window.append(float(event.close))


class SwitchableRestore(StatefulCounter):
    """Same class for writing and resuming (the setup check compares classes);
    ``fail`` makes ``restore_state`` refuse."""

    fail = False

    def restore_state(self, ctx: object, state: dict[str, object]) -> None:
        if SwitchableRestore.fail:
            msg = "cannot restore"
            raise CheckpointError(msg)
        super().restore_state(ctx, state)


def test_a_deque_kept_on_self_cannot_be_checkpointed(store: Path, tmp_path: Path) -> None:
    engine = make_engine(store, strategy=AppendsToDeque())
    engine.run_until(DAY * 3)  # type: ignore[arg-type]
    with pytest.raises(CheckpointError, match=r"strategy.*window"):
        engine.checkpoint(tmp_path / "c.json")


def test_a_child_of_a_multi_strategy_that_keeps_state_on_self_cannot_be_checkpointed(
    store: Path, tmp_path: Path
) -> None:
    multi = MultiStrategy({StrategyId("a"): CountsOnSelf()})
    engine = make_engine(store, strategy=multi)
    engine.run_until(DAY * 3)  # type: ignore[arg-type]
    with pytest.raises(CheckpointError, match=r"calls"):
        engine.checkpoint(tmp_path / "c.json")


def test_a_failed_resume_leaves_the_engine_unusable(store: Path, tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    good = make_engine(store, strategy=SwitchableRestore())
    good.run_until(DAY * 3)  # type: ignore[arg-type]
    good.checkpoint(path)
    bad = make_engine(store, strategy=SwitchableRestore())
    SwitchableRestore.fail = True
    try:
        with pytest.raises(CheckpointError, match="cannot restore"):
            bad.resume_from(path)
    finally:
        SwitchableRestore.fail = False
    with pytest.raises(CrucibleError, match="failed during"):
        bad.run()


def test_margin_limits_with_futures_that_have_margins_are_accepted(store: Path) -> None:
    risk = CompositeRiskEngine(
        USD, pre_trade_limits=[MarginRequirementLimit()], mark_limits=[MarginCallLimit()]
    )
    spec = FuturesSpec(
        multiplier=Decimal("50"), initial_margin=Decimal("5000"), maintenance_margin=Decimal("4000")
    )
    make_engine(store, risk_engine=risk, futures_specs={DIVCO: spec})
