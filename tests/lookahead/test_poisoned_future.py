"""Poisoned-future test (R2.2a) on the momentum example.

Inject absurd prices into every bar with ``available_at`` after a cutoff T,
rerun, and require every output up to T to be byte-for-byte unchanged. If
poisoning the future changes the past, information is flowing backward.

The example strategy is part of the harness matrix (AGENTS.md §7).
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
from examples.momentum.build_data import BARS_DATASET, build_all

POISON_FACTOR = 1_000.0


def _config(store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    return ExperimentConfig.model_validate(raw)


@pytest.mark.lookahead
def test_poisoning_the_future_does_not_change_the_past(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    clean_store = tmp_path_factory.mktemp("clean")
    build_all(clean_store)

    bars = pl.read_parquet(clean_store / str(BARS_DATASET) / "data.parquet")
    cutoff = int(bars.get_column("available_at").median())  # type: ignore[arg-type]

    poisoned_store = tmp_path_factory.mktemp("poisoned")
    build_all(poisoned_store)  # identical universe/corporate actions
    poison = pl.col("available_at") > cutoff
    poisoned_bars = bars.with_columns(
        open=pl.when(poison).then(pl.col("open") * POISON_FACTOR).otherwise(pl.col("open")),
        high=pl.when(poison).then(pl.col("high") * POISON_FACTOR).otherwise(pl.col("high")),
        low=pl.when(poison).then(pl.col("low") * POISON_FACTOR).otherwise(pl.col("low")),
        close=pl.when(poison).then(pl.col("close") * POISON_FACTOR).otherwise(pl.col("close")),
    )
    build_dataset(
        poisoned_store,
        DatasetId(str(BARS_DATASET)),
        poisoned_bars,
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

    # sanity: the poison had teeth — the futures do diverge
    clean_equity = pl.read_parquet(clean_run.path / "equity.parquet")
    poisoned_equity = pl.read_parquet(poisoned_run.path / "equity.parquet")
    assert not clean_equity.equals(poisoned_equity)
