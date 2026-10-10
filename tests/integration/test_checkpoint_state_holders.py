"""State a checkpoint would silently lose is refused by name (ADR-0048, ADR-0056)."""

from __future__ import annotations

from pathlib import Path

import pytest
from checkpoint_support import (
    DAY,
    BuyEveryDivcoBar,
    RollingSlippage,
    assert_same_result,
    build_dividend_store,
    execution_setup,
    make_engine,
)

from crucible.core.errors import CheckpointError
from crucible.core.types import TimestampNs
from crucible.risk.interfaces import RiskAction, RiskDecision


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    build_dividend_store(root)
    return root


class CountingRisk:
    """A hand-written RiskEngine (not CompositeRiskEngine, not Snapshottable)."""

    def __init__(self, *, mutate: bool) -> None:
        self.mutate = mutate
        self.checked = 0

    def pre_trade(self, order: object, portfolio: object) -> RiskDecision:
        if self.mutate:
            self.checked += 1
        return RiskDecision(RiskAction.ALLOW, "ok")

    def on_mark(self, portfolio: object, ts: object) -> RiskDecision:
        return RiskDecision(RiskAction.ALLOW, "ok")


def test_a_custom_risk_engine_that_changes_state_is_refused_by_name(
    store: Path, tmp_path: Path
) -> None:
    engine = make_engine(store, risk_engine=CountingRisk(mutate=True))
    engine.run_until(TimestampNs(3 * DAY))
    with pytest.raises(
        CheckpointError,
        match=r"risk_engine CountingRisk changed during the run \(attributes: checked\)",
    ):
        engine.checkpoint(tmp_path / "c.json")


def test_a_custom_risk_engine_without_state_changes_checkpoints_and_resumes(
    store: Path, tmp_path: Path
) -> None:
    baseline = make_engine(store, risk_engine=CountingRisk(mutate=False)).run()
    path = tmp_path / "c.json"
    first = make_engine(store, risk_engine=CountingRisk(mutate=False))
    first.run_until(TimestampNs(3 * DAY))
    first.checkpoint(path)
    resumed = make_engine(store, risk_engine=CountingRisk(mutate=False))
    resumed.resume_from(path)
    assert_same_result(resumed.run(), baseline)


def test_a_stateful_execution_model_that_is_not_snapshottable_is_refused_by_name(
    store: Path, tmp_path: Path
) -> None:
    engine = make_engine(
        store, strategy=BuyEveryDivcoBar(), execution=execution_setup(RollingSlippage())
    )
    engine.run_until(TimestampNs(3 * DAY))
    with pytest.raises(
        CheckpointError,
        match=r"execution\.slippage RollingSlippage changed during the run \(attributes: fills\)",
    ):
        engine.checkpoint(tmp_path / "c.json")


class _Instrument:
    def __init__(self, n: int) -> None:
        self.name = f"S{n}"


class BigUniverseStrategy(BuyEveryDivcoBar):
    """A large read-only universe (sorts first) next to a small counter it changes each bar."""

    def __init__(self) -> None:
        self.instruments = [_Instrument(i) for i in range(200)]
        self.seen = {"bars": 0}

    def on_market(self, ctx: object, event: object) -> None:
        self.seen["bars"] += 1
        super().on_market(ctx, event)  # type: ignore[arg-type]


def test_a_big_read_only_attribute_does_not_hide_a_changing_sibling(
    store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from crucible.core import setup_fingerprint

    monkeypatch.setattr(setup_fingerprint, "_MAX_NODES", 50)
    engine = make_engine(store, strategy=BigUniverseStrategy())
    engine.run_until(TimestampNs(3 * DAY))
    with pytest.raises(CheckpointError, match=r"\(attributes: seen\)"):
        engine.checkpoint(tmp_path / "c.json")
