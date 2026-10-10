"""Config -> models: registry level gating and slot exclusivity."""

from __future__ import annotations

import pydantic
import pytest

from crucible.core.errors import ConfigurationError
from crucible.core.types import RealismLevel
from crucible.execution.models import (
    DynamicSpread,
    NormalLatency,
    PerShareCommission,
    SqrtImpact,
)
from crucible.experiments.config import ExecutionConfig
from crucible.experiments.runner import build_execution_setup


def _config(**kwargs: object) -> ExecutionConfig:
    return ExecutionConfig.model_validate(kwargs)


def test_full_level4_stack_builds() -> None:
    setup = build_execution_setup(
        _config(
            spread={"type": "dynamic", "base_bps": 2.0, "vol_mult": 1.5},
            latency={"type": "normal", "mean_ms": 50.0, "std_ms": 10.0},
            slippage={"type": "sqrt_impact", "coef": 0.1},
            commission={"type": "per_share", "rate": "0.005", "minimum": "1.00"},
            participation={"max_bar_vol": 0.1, "max_adv": 0.02},
        ),
        RealismLevel.IMPACT,
    )
    assert isinstance(setup.spread, DynamicSpread)
    assert isinstance(setup.latency, NormalLatency)
    assert isinstance(setup.slippage, SqrtImpact)
    assert isinstance(setup.commission, PerShareCommission)
    assert setup.participation is not None
    assert setup.latency.mean_ns == 50.0 * 1_000_000  # ms -> ns


def test_spread_below_level2_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="realism level >= 2"):
        build_execution_setup(
            _config(spread={"type": "static", "half_spread_bps": 1.0}),
            RealismLevel.BASIC_FRICTION,
        )


def test_impact_below_level4_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="realism level >= 4"):
        build_execution_setup(
            _config(slippage={"type": "sqrt_impact", "coef": 0.1}),
            RealismLevel.LIQUIDITY,
        )


def test_shorthand_and_model_slot_are_mutually_exclusive() -> None:
    with pytest.raises((pydantic.ValidationError, ConfigurationError)):
        _config(slippage_bps=5.0, slippage={"type": "fixed_bps", "bps": 5.0})


def test_scenario_name_base_is_reserved() -> None:
    with pytest.raises((pydantic.ValidationError, ConfigurationError)):
        _config(scenarios={"base": {}})


def test_shorthand_builds_level1_models() -> None:
    setup = build_execution_setup(
        _config(slippage_bps=5.0, commission_bps=2.0), RealismLevel.BASIC_FRICTION
    )
    assert setup.participation is None
    assert type(setup.spread).__name__ == "NoSpread"
