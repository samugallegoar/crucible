"""Unit tests for promote_config (ADR-0037): the
config-rewriting half of promotion, independent of running an engine."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from crucible.core.errors import ConfigurationError
from crucible.core.types import RealismLevel, Symbol
from crucible.experiments.config import (
    ConstantLatencyConfig,
    ExecutionConfig,
    ExperimentConfig,
    FixedBpsSlippageConfig,
    StaticSpreadConfig,
)
from crucible.experiments.promotion import PromotedSignalStrategy, promote_config
from examples.trend_demo.build_data import build_all

LEVEL2_EXECUTION = ExecutionConfig(
    spread=StaticSpreadConfig(type="static", half_spread_bps=5.0),
    latency=ConstantLatencyConfig(type="constant", ms=50.0),
    slippage=FixedBpsSlippageConfig(type="fixed_bps", bps=2.0),
)


def _vectorized_config(store_path: Path) -> ExperimentConfig:
    import yaml

    raw = yaml.safe_load(
        Path("examples/trend_demo/config_vectorized.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store_path)
    return ExperimentConfig.model_validate(raw)


def test_promote_config_rewrites_strategy_and_realism_level(tmp_path: Path) -> None:
    build_all(tmp_path)
    config = _vectorized_config(tmp_path)

    promoted = promote_config(
        config,
        target_realism_level=RealismLevel.SPREAD_LATENCY,
        execution=LEVEL2_EXECUTION,
        promotion_lookback=10,
    )

    assert promoted.experiment.realism_level is RealismLevel.SPREAD_LATENCY
    assert promoted.strategy.entrypoint == "crucible.experiments.promotion:PromotedSignalStrategy"
    assert promoted.strategy.params["signal_entrypoint"] == config.strategy.entrypoint
    assert promoted.strategy.params["signal_params"] == config.strategy.params
    assert promoted.strategy.params["symbols"] == ["TRENDY"]
    assert promoted.strategy.params["lookback"] == 10
    assert promoted.execution is LEVEL2_EXECUTION
    # everything else about the run (dataset, dates, cash) is untouched
    assert promoted.data.bars == config.data.bars
    assert promoted.initial_cash == config.initial_cash
    assert promoted.start == config.start
    assert promoted.end == config.end


def test_promote_config_refuses_level_0_or_1(tmp_path: Path) -> None:
    build_all(tmp_path)
    config = _vectorized_config(tmp_path)
    with pytest.raises(ConfigurationError, match="Level 2"):
        promote_config(
            config,
            target_realism_level=RealismLevel.BASIC_FRICTION,
            execution=LEVEL2_EXECUTION,
            promotion_lookback=10,
        )


def test_promote_config_refuses_a_nonpositive_lookback(tmp_path: Path) -> None:
    build_all(tmp_path)
    config = _vectorized_config(tmp_path)
    with pytest.raises(ConfigurationError, match="promotion_lookback"):
        promote_config(
            config,
            target_realism_level=RealismLevel.SPREAD_LATENCY,
            execution=LEVEL2_EXECUTION,
            promotion_lookback=0,
        )


class _Event:
    def __init__(self, symbol: str, event_time: int) -> None:
        self.symbol = symbol
        self.event_time = event_time


class _Ctx:
    def __init__(self, bars_at: dict[int, int]) -> None:
        self.state: dict[str, object] = {}
        self.bars_at = bars_at


def _strategy(rebalances: list[int], ctx: _Ctx) -> PromotedSignalStrategy:
    strategy = PromotedSignalStrategy.__new__(PromotedSignalStrategy)
    strategy._cfg = lambda c: SimpleNamespace(symbols=[Symbol("A"), Symbol("B")])  # type: ignore[method-assign]
    strategy._bars_at = lambda c, cfg, ts: ctx.bars_at[ts]  # type: ignore[method-assign]
    strategy._rebalance = lambda c, cfg: rebalances.append(len(rebalances))  # type: ignore[method-assign]
    return strategy


def test_it_rebalances_once_per_timestamp_on_the_last_bar() -> None:
    rebalances: list[int] = []
    ctx = _Ctx({1: 2, 2: 2})
    strategy = _strategy(rebalances, ctx)
    for symbol, ts in (("A", 1), ("B", 1), ("A", 2), ("B", 2)):
        strategy.on_market(ctx, _Event(symbol, ts))  # type: ignore[arg-type]
    assert len(rebalances) == 2


def test_a_late_arriving_bar_of_an_older_timestamp_does_not_rebalance_again() -> None:
    """B's bar for t=1 reaches the engine after A's bar for t=2 (a slower feed): the decision for
    t=1 was already taken on A's bar (only A was there), so B@1 must not rebalance again."""
    rebalances: list[int] = []
    ctx = _Ctx({1: 1, 2: 1})
    strategy = _strategy(rebalances, ctx)
    for symbol, ts in (("A", 1), ("A", 2), ("B", 1)):
        strategy.on_market(ctx, _Event(symbol, ts))  # type: ignore[arg-type]
    assert len(rebalances) == 2
