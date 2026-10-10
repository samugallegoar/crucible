"""Poisoned-future test (R2.2a) on the trend_demo example (TrendFollower).

Same harness as ``test_poisoned_future.py``'s momentum coverage: inject
absurd prices into every bar with ``available_at`` after a cutoff T,
rerun, and require every output up to T to be byte-for-byte unchanged.
TrendFollower reads its own trailing return history via
``ctx.data.history``, so it is squarely subject to PIT discipline and
belongs in the harness matrix (AGENTS.md §7: every strategy/example added
must be covered here) -- doubly so since this example (ADR-0024) exists
specifically to demonstrate a genuine, data-dependent edge; if it could
see the future, the acceptance demonstration would be worthless.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

from crucible.core.types import DatasetId
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import build_dataset
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import run_experiment
from examples.trend_demo.build_data import BARS_DATASET, build_all

POISON_FACTOR = 1_000.0


def _config(store: Path, config_name: str = "config.yaml") -> ExperimentConfig:
    raw = yaml.safe_load(Path(f"examples/trend_demo/{config_name}").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    return ExperimentConfig.model_validate(raw)


def _poisoned_bars(clean_root: Path, cutoff: int) -> pl.DataFrame:
    bars = pl.read_parquet(clean_root / str(BARS_DATASET) / "data.parquet")
    poison = pl.col("available_at") > cutoff
    return bars.with_columns(
        open=pl.when(poison).then(pl.col("open") * POISON_FACTOR).otherwise(pl.col("open")),
        high=pl.when(poison).then(pl.col("high") * POISON_FACTOR).otherwise(pl.col("high")),
        low=pl.when(poison).then(pl.col("low") * POISON_FACTOR).otherwise(pl.col("low")),
        close=pl.when(poison).then(pl.col("close") * POISON_FACTOR).otherwise(pl.col("close")),
    )


@pytest.mark.lookahead
def test_poisoning_the_future_does_not_change_the_past(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    clean_store = tmp_path_factory.mktemp("clean")
    build_all(clean_store)
    bars = pl.read_parquet(clean_store / str(BARS_DATASET) / "data.parquet")
    cutoff = int(bars.get_column("available_at").median())  # type: ignore[arg-type]

    poisoned_store = tmp_path_factory.mktemp("poisoned")
    build_all(poisoned_store)  # identical bars before the cutoff
    build_dataset(
        poisoned_store,
        DatasetId(str(BARS_DATASET)),
        _poisoned_bars(clean_store, cutoff),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="poisoned",
    )

    clean_run = run_experiment(_config(clean_store), tmp_path_factory.mktemp("out_clean"))
    poisoned_run = run_experiment(_config(poisoned_store), tmp_path_factory.mktemp("out_poisoned"))

    for name in ["ledger.parquet", "fills.parquet", "equity.parquet"]:
        clean_frame = pl.read_parquet(clean_run.path / name).filter(pl.col("ts") <= cutoff)
        poisoned_frame = pl.read_parquet(poisoned_run.path / name).filter(pl.col("ts") <= cutoff)
        assert clean_frame.equals(poisoned_frame), (
            f"{name}: outputs before the poison cutoff changed — lookahead leak"
        )

    # sanity: the poison had teeth -- TrendFollower's signal reacts to
    # price, unlike RandomSignal's/RandomDirection's, so the futures must
    # actually diverge
    clean_equity = pl.read_parquet(clean_run.path / "equity.parquet")
    poisoned_equity = pl.read_parquet(poisoned_run.path / "equity.parquet")
    assert not clean_equity.equals(poisoned_equity)


@pytest.mark.lookahead
def test_poisoning_the_future_does_not_change_the_past_for_random_direction(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """RandomDirection (ADR-0024) also reads ``ctx.data.history`` for
    position sizing, even though its long/flat call ignores price -- same
    harness coverage requirement (AGENTS.md §7) as any other strategy."""
    clean_store = tmp_path_factory.mktemp("clean")
    build_all(clean_store)
    bars = pl.read_parquet(clean_store / str(BARS_DATASET) / "data.parquet")
    cutoff = int(bars.get_column("available_at").median())  # type: ignore[arg-type]

    poisoned_store = tmp_path_factory.mktemp("poisoned")
    build_all(poisoned_store)
    build_dataset(
        poisoned_store,
        DatasetId(str(BARS_DATASET)),
        _poisoned_bars(clean_store, cutoff),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="poisoned",
    )

    clean_run = run_experiment(
        _config(clean_store, "config_random.yaml"), tmp_path_factory.mktemp("out_clean_rd")
    )
    poisoned_run = run_experiment(
        _config(poisoned_store, "config_random.yaml"), tmp_path_factory.mktemp("out_poisoned_rd")
    )

    for name in ["ledger.parquet", "fills.parquet", "equity.parquet"]:
        clean_frame = pl.read_parquet(clean_run.path / name).filter(pl.col("ts") <= cutoff)
        poisoned_frame = pl.read_parquet(poisoned_run.path / name).filter(pl.col("ts") <= cutoff)
        assert clean_frame.equals(poisoned_frame), (
            f"{name}: outputs before the poison cutoff changed — lookahead leak"
        )
