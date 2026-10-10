"""Snapshottable execution models are saved and restored atomically (ADR-0056)."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import numpy as np
import pytest

from crucible.core import checkpoint as ckpt
from crucible.core.errors import CheckpointError
from crucible.core.types import RealismLevel
from crucible.execution.ladder import LadderExecutionSimulator
from crucible.execution.models import MarketStats, NoCommission, NoSlippage, NoSpread, ZeroLatency
from crucible.orders.manager import InMemoryOrderManager


class _CountingSlippage(NoSlippage):
    def __init__(self, calls: int = 0) -> None:
        self.calls = calls

    def snapshot(self) -> dict[str, object]:
        return {"calls": self.calls}

    def restore(self, state: Mapping[str, object]) -> None:
        self.calls = ckpt.field(state, "calls", int)


class _TotalCommission(NoCommission):
    def __init__(self, total: int = 0) -> None:
        self.total = total

    def commission(self, fill: object) -> Decimal:
        return Decimal("0")

    def snapshot(self) -> dict[str, object]:
        return {"total": self.total}

    def restore(self, state: Mapping[str, object]) -> None:
        self.total = ckpt.field(state, "total", int)


def _ladder(
    slippage: object | None = None, commission: object | None = None
) -> LadderExecutionSimulator:
    return LadderExecutionSimulator(
        level=RealismLevel.BASIC_FRICTION,
        order_manager=InMemoryOrderManager(),
        spread=NoSpread(),
        latency=ZeroLatency(),
        slippage=slippage if slippage is not None else NoSlippage(),  # type: ignore[arg-type]
        commission=commission if commission is not None else NoCommission(),  # type: ignore[arg-type]
        participation=None,
        stats=MarketStats(),
        rng=np.random.default_rng(0),
    )


def test_snapshot_has_a_models_entry_with_state_only_for_snapshottable_models() -> None:
    models = _ladder(slippage=_CountingSlippage(3)).snapshot()["models"]
    assert models == {"spread": None, "latency": None, "slippage": {"calls": 3}, "commission": None}


def test_a_snapshot_round_trips_model_state_in_place() -> None:
    source = _ladder(slippage=_CountingSlippage(7), commission=_TotalCommission(4))
    target = _ladder(slippage=_CountingSlippage(0), commission=_TotalCommission(0))
    target.restore(source.snapshot())
    assert target.snapshot()["models"] == source.snapshot()["models"]


def test_state_for_a_stateless_model_is_refused() -> None:
    state = _ladder().snapshot()
    state["models"] = {"spread": {"x": 1}, "latency": None, "slippage": None, "commission": None}
    with pytest.raises(CheckpointError, match=r"stateless execution model .*spread"):
        _ladder().restore(state)


def test_a_different_model_set_is_refused() -> None:
    state = _ladder().snapshot()
    del state["models"]["slippage"]  # type: ignore[attr-defined,index]
    with pytest.raises(CheckpointError, match="same execution configuration"):
        _ladder().restore(state)


def test_a_failed_restore_rolls_every_model_back() -> None:
    ladder = _ladder(slippage=_CountingSlippage(9), commission=_TotalCommission(11))
    before = ladder.snapshot()
    bad = {
        "pending": {},
        "reasons": {},
        "models": {
            "spread": None,
            "latency": None,
            "slippage": {"calls": 1},  # restores fine...
            "commission": {"total": "not-an-int"},  # ...then this one refuses
        },
    }
    with pytest.raises(CheckpointError):
        ladder.restore(bad)
    assert ladder.snapshot() == before  # slippage is back at 9, commission untouched


class _BrittleCommission(_TotalCommission):
    def restore(self, state: Mapping[str, object]) -> None:
        msg = "boom"
        raise ValueError(msg)


def test_any_exception_while_restoring_a_model_rolls_the_others_back() -> None:
    """Not only CheckpointError: a model's restore may raise anything (review finding)."""
    ladder = _ladder(slippage=_CountingSlippage(9), commission=_BrittleCommission(11))
    before = ladder.snapshot()
    state = ladder.snapshot()
    state["models"] = {
        "spread": None,
        "latency": None,
        "slippage": {"calls": 1},
        "commission": {"total": 5},
    }
    with pytest.raises(ValueError, match="boom"):
        ladder.restore(state)
    assert ladder.snapshot() == before


class _AliasedSlippage(NoSlippage):
    """snapshot() hands out its live list and restore() rewrites that list in place."""

    def __init__(self, log: list[int]) -> None:
        self.log = log

    def snapshot(self) -> dict[str, object]:
        return {"log": self.log}

    def restore(self, state: Mapping[str, object]) -> None:
        self.log.clear()
        self.log.extend(ckpt.expect(state["log"], list, "log"))


def test_a_snapshot_that_aliases_live_state_still_rolls_back_correctly() -> None:
    ladder = _ladder(slippage=_AliasedSlippage([1, 2]), commission=_TotalCommission(11))
    bad = {
        "pending": {},
        "reasons": {},
        "models": {
            "spread": None,
            "latency": None,
            "slippage": {"log": [9]},
            "commission": {"total": "not-an-int"},
        },
    }
    with pytest.raises(CheckpointError):
        ladder.restore(bad)
    assert ladder.snapshot()["models"]["slippage"] == {"log": [1, 2]}  # type: ignore[index]


def test_a_malformed_pending_entry_is_refused_before_any_model_is_touched() -> None:
    ladder = _ladder(slippage=_CountingSlippage(9))
    before = ladder.snapshot()
    bad = {
        "pending": {"O-1": {"effective_at": "not-an-int"}},
        "reasons": {},
        "models": {
            "spread": None,
            "latency": None,
            "slippage": {"calls": 1},
            "commission": None,
        },
    }
    with pytest.raises(CheckpointError):
        ladder.restore(bad)
    assert ladder.snapshot() == before  # slippage still 9: models restore only after parsing
