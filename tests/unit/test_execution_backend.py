"""ExecutionBackend: the seam the engine calls into (ADR-0043)."""

from __future__ import annotations

import numpy as np

from crucible.core.types import RealismLevel
from crucible.execution.backend import ExecutionBackend
from crucible.execution.ladder import ExecutionSetup, LadderExecutionSimulator
from crucible.orders.manager import InMemoryOrderManager


def _ladder() -> LadderExecutionSimulator:
    setup = ExecutionSetup.legacy(RealismLevel.BASIC_FRICTION, 0.0, 0.0)
    return LadderExecutionSimulator(
        level=RealismLevel.BASIC_FRICTION,
        order_manager=InMemoryOrderManager(),
        spread=setup.spread,
        latency=setup.latency,
        slippage=setup.slippage,
        commission=setup.commission,
        participation=setup.participation,
        stats=setup.stats,
        rng=np.random.default_rng(0),
    )


def test_the_ladder_simulator_satisfies_the_backend_protocol() -> None:
    sim = _ladder()
    assert isinstance(sim, ExecutionBackend)
    assert sim.supports_composite_orders is True


def test_an_object_missing_a_method_is_not_a_backend() -> None:
    class Partial:
        supports_composite_orders = True

        def on_bar(self, bar: object) -> None: ...

    assert not isinstance(Partial(), ExecutionBackend)
