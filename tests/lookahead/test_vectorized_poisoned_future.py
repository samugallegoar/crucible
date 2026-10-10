"""Poisoned-future test (R2.2a/R2.3) for the vectorized engine.

Mirrors ``test_poisoned_future.py``'s method for the event-driven engine:
inject absurd prices into every bar after a cutoff and require every
vectorized output at-or-before the cutoff to be unchanged. Uses
``examples.trend_demo``'s vectorized signal (ADR-0035) -- the
example strategy is part of the harness matrix (AGENTS.md §7).
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl
import pytest

from crucible.analytics.trades import build_episodes
from crucible.core.types import RealismLevel, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig
from examples.trend_demo.build_data import BARS_DATASET, build_all
from examples.trend_demo.vectorized_signal import trend_follower_signal

POISON_FACTOR = 1_000.0


def _config(store: ParquetDataStore, end: TimestampNs) -> VectorizedConfig:
    return VectorizedConfig(
        store=store,
        bars_dataset=BARS_DATASET,
        signal=trend_follower_signal,
        params={"lookback": 3},
        initial_cash=Decimal("1000000"),
        realism_level=RealismLevel.FRICTIONLESS,
        start=TimestampNs(0),
        end=end,
    )


@pytest.mark.lookahead
def test_poisoning_the_future_does_not_change_vectorized_outputs_at_or_before_the_cutoff(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    clean_store_path = tmp_path_factory.mktemp("clean")
    build_all(clean_store_path)

    bars = pl.read_parquet(clean_store_path / str(BARS_DATASET) / "data.parquet")
    cutoff = int(bars.get_column("available_at").median())  # type: ignore[arg-type]
    end = TimestampNs(int(bars.get_column("available_at").max()))  # type: ignore[arg-type]

    poisoned_store_path = tmp_path_factory.mktemp("poisoned")
    build_all(poisoned_store_path)
    poison = pl.col("available_at") > cutoff
    poisoned_bars = bars.with_columns(
        open=pl.when(poison).then(pl.col("open") * POISON_FACTOR).otherwise(pl.col("open")),
        high=pl.when(poison).then(pl.col("high") * POISON_FACTOR).otherwise(pl.col("high")),
        low=pl.when(poison).then(pl.col("low") * POISON_FACTOR).otherwise(pl.col("low")),
        close=pl.when(poison).then(pl.col("close") * POISON_FACTOR).otherwise(pl.col("close")),
    )
    build_dataset(
        poisoned_store_path,
        BARS_DATASET,
        poisoned_bars,
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="poisoned",
    )

    engine = VectorizedBacktestEngine()
    clean = engine.run(_config(ParquetDataStore(clean_store_path), end))
    poisoned = engine.run(_config(ParquetDataStore(poisoned_store_path), end))

    for name, clean_frame, poisoned_frame in (
        ("equity", clean.equity, poisoned.equity),
        ("weights", clean.weights, poisoned.weights),
        ("scores", clean.scores, poisoned.scores),
    ):
        before = clean_frame.filter(pl.col("ts") <= cutoff)
        after = poisoned_frame.filter(pl.col("ts") <= cutoff)
        assert before.equals(after), (
            f"{name}: outputs at-or-before the poison cutoff changed — lookahead leak"
        )

    # episodes that closed at or before the cutoff are derived from the lagged weights only
    clean_episodes = build_episodes(clean.weights, clean.pnl).filter(pl.col("exit_ts") <= cutoff)
    poisoned_episodes = build_episodes(poisoned.weights, poisoned.pnl).filter(
        pl.col("exit_ts") <= cutoff
    )
    assert clean_episodes.height > 0, "the cutoff must leave closed episodes to compare"
    assert clean_episodes.equals(poisoned_episodes), "episodes before the cutoff changed"

    # sanity: the poison had teeth downstream of the cutoff
    clean_tail = clean.equity.filter(pl.col("ts") > cutoff)
    poisoned_tail = poisoned.equity.filter(pl.col("ts") > cutoff)
    assert not clean_tail.equals(poisoned_tail)
