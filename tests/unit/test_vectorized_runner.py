"""Unit tests for the config -> vectorized-engine glue:
every ExperimentConfig field the vectorized path can't honor must be
refused, not silently dropped (AGENTS.md §5)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from crucible.core.errors import ConfigurationError
from crucible.core.types import RealismLevel
from crucible.data.store import ParquetDataStore
from crucible.experiments.config import (
    ExperimentConfig,
    ExperimentHeader,
    FuturesMarginConfig,
    MarginCallLimitConfig,
    QuotedSpreadConfig,
    RiskConfig,
    StaticSpreadConfig,
    StrategyConfig,
)
from crucible.experiments.vectorized_runner import assemble_vectorized_engine
from examples.trend_demo.build_data import build_all


def _base_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "store": "examples/trend_demo/data",
        "bars": "trend_demo_bars_v1",
        "calendar": "XNYS",
    }
    data.update(overrides)
    return data


def _config(**overrides: object) -> ExperimentConfig:
    kwargs: dict[str, object] = {
        "experiment": ExperimentHeader(
            name="t",
            family="t",
            mode="evaluation",
            seed=1,
            realism_level=RealismLevel.BASIC_FRICTION,
        ),
        "data": _base_data(),
        "strategy": StrategyConfig(
            entrypoint="examples.trend_demo.vectorized_signal:trend_follower_signal",
            params={"lookback": 3},
        ),
        "initial_cash": Decimal("1000000"),
        "start": "2020-01-01",
        "end": "2022-01-01",
    }
    kwargs.update(overrides)
    return ExperimentConfig.model_validate(kwargs)


def test_assembles_a_runnable_engine_for_an_in_scope_config(tmp_path: Path) -> None:
    build_all(tmp_path)
    engine, vec_config = assemble_vectorized_engine(_config(), store=ParquetDataStore(tmp_path))
    assert vec_config.realism_level is RealismLevel.BASIC_FRICTION
    result = engine.run(vec_config)
    assert result.equity.height > 0


def test_refuses_corporate_actions() -> None:
    with pytest.raises(ConfigurationError, match="corporate_actions"):
        assemble_vectorized_engine(_config(data=_base_data(corporate_actions="some_ca_dataset")))


def test_refuses_universe() -> None:
    with pytest.raises(ConfigurationError, match="universe"):
        assemble_vectorized_engine(_config(data=_base_data(universe="some_universe_dataset")))


def test_refuses_a_foreign_symbol_currency_without_an_fx_dataset() -> None:
    data = _base_data(symbol_currency={"EURSTOCK": "EUR"})
    with pytest.raises(ConfigurationError, match="fx_rates"):
        assemble_vectorized_engine(_config(data=data))


def test_accepts_futures_multipliers(tmp_path: Path) -> None:
    """The multiplier cancels in a vectorized return (ADR-0065), so the config is in scope."""
    build_all(tmp_path)
    data = _base_data(futures_multipliers={"ES": Decimal("50")})
    engine, vec_config = assemble_vectorized_engine(
        _config(data=data), store=ParquetDataStore(tmp_path)
    )
    assert engine.run(vec_config).equity.height > 0


def test_refuses_futures_margins() -> None:
    data = _base_data(
        futures_multipliers={"ES": Decimal("50")},
        futures_margins={
            "ES": FuturesMarginConfig(initial=Decimal("100"), maintenance=Decimal("80"))
        },
    )
    with pytest.raises(ConfigurationError, match="futures_margins"):
        assemble_vectorized_engine(_config(data=data))


def test_refuses_a_risk_config() -> None:
    risk = RiskConfig(mark=(MarginCallLimitConfig(type="margin_call"),))
    with pytest.raises(ConfigurationError, match="risk engine"):
        assemble_vectorized_engine(_config(risk=risk))


def test_refuses_settlement_lag() -> None:
    with pytest.raises(ConfigurationError, match="settlement"):
        assemble_vectorized_engine(_config(settlement_lag_days=1))


def test_refuses_borrow_and_financing_rates() -> None:
    with pytest.raises(ConfigurationError, match="borrow"):
        assemble_vectorized_engine(_config(short_borrow_rate=0.05))


def test_refuses_scenario_fanout() -> None:
    execution = {
        "slippage_bps": 0.0,
        "commission_bps": 0.0,
        "scenarios": {"stress": {"spread": StaticSpreadConfig(type="static", half_spread_bps=5.0)}},
    }
    with pytest.raises(ConfigurationError, match="scenario"):
        assemble_vectorized_engine(_config(execution=execution))


def test_refuses_a_level_2_execution_model_slot() -> None:
    execution = {
        "slippage_bps": 0.0,
        "commission_bps": 0.0,
        "spread": StaticSpreadConfig(type="static", half_spread_bps=5.0),
    }
    with pytest.raises(ConfigurationError, match="Level 2"):
        assemble_vectorized_engine(_config(execution=execution))


def test_refuses_a_quoted_spread() -> None:
    execution = {
        "slippage_bps": 0.0,
        "commission_bps": 0.0,
        "spread": QuotedSpreadConfig(type="quoted"),
    }
    with pytest.raises(ConfigurationError, match="Level 2"):
        assemble_vectorized_engine(_config(execution=execution))


def test_refuses_realism_level_two_or_higher() -> None:
    header = ExperimentHeader(
        name="t", family="t", mode="evaluation", seed=1, realism_level=RealismLevel.SPREAD_LATENCY
    )
    with pytest.raises(ConfigurationError, match="FRICTIONLESS"):
        assemble_vectorized_engine(_config(experiment=header))


def test_refuses_a_live_block() -> None:
    with pytest.raises(ConfigurationError, match="live"):
        assemble_vectorized_engine(_config(live={"enabled": True}))
