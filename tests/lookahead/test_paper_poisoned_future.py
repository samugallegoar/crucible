"""Poisoned-future test through PaperRuntime (AGENTS.md §7 harness matrix).

Poison every bar with available_at after a cutoff; every output up to the
cutoff must be unchanged. The first poisoned bar is the feed's one-event
lookahead while the last clean event is processed, so this also proves the
peek leaks nothing.
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
from crucible.live.runtime import PaperRuntime
from examples.momentum.build_data import BARS_DATASET, build_all

POISON_FACTOR = 1_000.0


def _config(store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    return ExperimentConfig.model_validate(raw)


@pytest.mark.lookahead
def test_poisoning_the_future_does_not_change_the_past_under_paper_runtime(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    clean_store = tmp_path_factory.mktemp("clean")
    build_all(clean_store)
    bars = pl.read_parquet(clean_store / str(BARS_DATASET) / "data.parquet")
    cutoff = int(bars.get_column("available_at").median())  # type: ignore[arg-type]

    poisoned_store = tmp_path_factory.mktemp("poisoned")
    build_all(poisoned_store)
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

    clean = PaperRuntime(_config(clean_store)).run()
    poisoned = PaperRuntime(_config(poisoned_store)).run()

    for name in ("ledger_rows", "fill_rows", "equity_rows"):
        clean_frame = pl.DataFrame(getattr(clean, name)).filter(pl.col("ts") <= cutoff)
        poisoned_frame = pl.DataFrame(getattr(poisoned, name)).filter(pl.col("ts") <= cutoff)
        assert clean_frame.equals(poisoned_frame), (
            f"{name}: outputs before the poison cutoff changed under PaperRuntime; lookahead leak"
        )

    # sanity: the poison had teeth
    assert not pl.DataFrame(clean.equity_rows).equals(pl.DataFrame(poisoned.equity_rows))
