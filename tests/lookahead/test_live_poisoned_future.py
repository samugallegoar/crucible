"""Poisoned-future test through LiveRuntime (AGENTS.md section 7 harness matrix).

Poison every bar with available_at after a cutoff; every output up to the
cutoff must be unchanged. The venue steps the first poisoned bar while the
last clean event is processed (the feed's one-event lookahead), so this also
proves the venue's run-ahead leaks nothing into earlier results.
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
from crucible.live.runtime import LiveRuntime
from examples.momentum.build_data import BARS_DATASET, build_all

POISON_FACTOR = 1_000.0


def _config(store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["live"] = {"enabled": True}
    return ExperimentConfig.model_validate(raw)


def _upto(rows: list[dict[str, object]], cutoff: int) -> list[dict[str, object]]:
    return [row for row in rows if int(str(row["ts"])) <= cutoff]


@pytest.mark.lookahead
def test_poisoning_the_future_does_not_change_the_past_under_live_runtime(
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

    clean = LiveRuntime(_config(clean_store)).run()
    poisoned = LiveRuntime(_config(poisoned_store)).run()

    for name in ("equity_rows", "fill_rows", "ledger_rows"):
        clean_rows = _upto(getattr(clean, name), cutoff)
        poisoned_rows = _upto(getattr(poisoned, name), cutoff)
        assert clean_rows == poisoned_rows, f"{name}: outputs before the cutoff changed"
        assert clean_rows, f"{name}: nothing before the cutoff, the test proves nothing"

    # sanity: the poison had teeth after the cutoff
    assert clean.equity_rows != poisoned.equity_rows
