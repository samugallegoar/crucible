"""Snapshots for the stateful risk limits and the composite risk engine."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from crucible.core.checkpoint import canonical_json, decode, encode
from crucible.core.errors import CheckpointError
from crucible.core.interfaces import Snapshottable
from crucible.core.types import Currency, TimestampNs
from crucible.risk.engine import CompositeRiskEngine
from crucible.risk.interfaces import RiskAction
from crucible.risk.limits import DailyLossFlattenLimit, DrawdownHaltLimit, MaxOrderNotionalLimit

USD = Currency("USD")
DAY_NS = 86_400 * 10**9


class _Portfolio:
    """The two-line PortfolioView the mark limits actually read."""

    def __init__(self, equity: str) -> None:
        self._equity = Decimal(equity)

    def equity(self, base: Currency) -> Decimal:
        return self._equity


def _through_json(state: dict[str, object]) -> dict[str, object]:
    out = decode(json.loads(canonical_json(encode(state))))
    assert isinstance(out, dict)
    return out


def test_drawdown_peak_survives_a_restore_and_still_halts() -> None:
    limit = DrawdownHaltLimit(0.10)
    limit.check(_Portfolio("1000"), TimestampNs(1), USD)  # peak 1000
    limit.check(_Portfolio("950"), TimestampNs(2), USD)
    state = _through_json(limit.snapshot())
    assert state == {"peak": Decimal("1000")}

    fresh = DrawdownHaltLimit(0.10)
    fresh.restore(state)
    decision = fresh.check(_Portfolio("850"), TimestampNs(3), USD)  # 15% below the restored peak
    assert decision.action is RiskAction.HALT


def test_daily_loss_day_and_start_equity_survive_a_restore() -> None:
    limit = DailyLossFlattenLimit(0.05)
    limit.check(_Portfolio("1000"), TimestampNs(DAY_NS + 5), USD)  # day 1 starts at 1000
    state = _through_json(limit.snapshot())
    assert state == {"day": 1, "day_start_equity": Decimal("1000")}

    fresh = DailyLossFlattenLimit(0.05)
    fresh.restore(state)
    same_day = fresh.check(_Portfolio("900"), TimestampNs(DAY_NS + 50), USD)
    assert same_day.action is RiskAction.FLATTEN  # measured against the restored day-start equity


def test_unset_state_roundtrips_as_none() -> None:
    limit = DrawdownHaltLimit(0.2)
    state = _through_json(limit.snapshot())
    assert state == {"peak": None}
    DrawdownHaltLimit(0.2).restore(state)


def test_composite_snapshot_is_index_aligned_and_restores_in_place() -> None:
    def build() -> tuple[CompositeRiskEngine, DrawdownHaltLimit]:
        drawdown = DrawdownHaltLimit(0.10)
        engine = CompositeRiskEngine(
            USD,
            pre_trade_limits=[MaxOrderNotionalLimit(Decimal("100000"))],
            mark_limits=[drawdown, DailyLossFlattenLimit(0.5)],
        )
        return engine, drawdown

    engine, drawdown = build()
    assert isinstance(engine, Snapshottable)
    engine.on_mark(_Portfolio("1000"), TimestampNs(DAY_NS))
    state = _through_json(engine.snapshot())
    assert state["pre_trade"] == [None]  # stateless limit
    assert isinstance(state["mark"], list)
    assert len(state["mark"]) == 2

    fresh, fresh_drawdown = build()
    fresh.restore(state)
    assert fresh_drawdown.snapshot() == drawdown.snapshot()


def test_composite_restore_refuses_a_different_limit_set() -> None:
    engine = CompositeRiskEngine(USD, mark_limits=[DrawdownHaltLimit(0.1)])
    state = _through_json(engine.snapshot())
    other = CompositeRiskEngine(
        USD, mark_limits=[DrawdownHaltLimit(0.1), DailyLossFlattenLimit(0.1)]
    )
    with pytest.raises(CheckpointError, match="mark"):
        other.restore(state)
