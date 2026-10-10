"""Poisoned-future test (R2.2a) on the Polymarket example (BuyCheapUp), AGENTS.md section 7.

Absurd prices are injected into every bar with ``available_at`` after a cutoff; every output up to
the cutoff must be byte-for-byte unchanged.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

from crucible.core.types import DatasetId
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS, QUOTED_BAR_SCHEMA
from crucible.data.importers.build import build_from_spec
from crucible.data.store import build_dataset
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import run_experiment

CSV_HEADER = (
    "slug,start_time,elapsed,ask_YES,bid_YES,ask_NO,bid_NO,btc_strike,btc_current,btc_gap,"
    "timestamp_log,resolved,winner"
)
DATASET = "polymarket_btc5m_csv_v1"


def _config(store: Path, example: str = "polymarket_up.yaml") -> ExperimentConfig:
    raw = yaml.safe_load(Path(f"examples/real_data/{example}").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(store)
    raw["start"], raw["end"] = "1970-01-01", "1970-01-01T01:00:00+00:00"
    return ExperimentConfig.model_validate(raw)


def _build(root: Path, tmp: Path) -> None:
    rows = [
        f"btc-updown-5m-{start},{start},{ts - start},0.42,0.38,0.62,0.58,100.0,100.0,0.0,{ts},"
        "True,Up"
        for start in (1000, 1300)
        for ts in (start + 100, start + 102, start + 104, start + 106)
    ]
    (tmp / "pm.csv").write_text("\n".join([CSV_HEADER, *rows]) + "\n", encoding="utf-8")
    spec = tmp / "spec.yaml"
    spec.write_text(
        f"kind: polymarket_csv\ndataset: {DATASET}\ninput: '{tmp / 'pm.csv'}'\nbar_seconds: 2\n",
        encoding="utf-8",
    )
    build_from_spec(spec, root)


_PRICES = ("open", "high", "low", "close")
_QUOTES = ("bid_open", "ask_open", "bid_close", "ask_close")


def _check_poisoned_future(
    tmp_path_factory: pytest.TempPathFactory,
    example: str,
    schema: dict[str, pl.DataType],
    poisoned_columns: tuple[str, ...],
) -> None:
    clean = tmp_path_factory.mktemp("clean")
    _build(clean, tmp_path_factory.mktemp("clean_src"))
    bars = pl.read_parquet(clean / DATASET / "data.parquet")
    cutoff = int(bars.get_column("available_at").median())  # type: ignore[arg-type]

    poisoned = tmp_path_factory.mktemp("poisoned")
    _build(poisoned, tmp_path_factory.mktemp("poisoned_src"))
    poison = pl.col("available_at") > cutoff
    poisoned_bars = bars.with_columns(
        [
            pl.when(poison).then(pl.col(c) * 1000.0).otherwise(pl.col(c)).alias(c)
            for c in poisoned_columns
        ]
    )
    build_dataset(
        poisoned,
        DatasetId(DATASET),
        poisoned_bars,
        schema=schema,
        sort_keys=BAR_SORT_KEYS,
        source="poisoned",
    )

    clean_run = run_experiment(
        _config(clean, example), tmp_path_factory.mktemp("o1"), record_trial=False
    )
    poisoned_run = run_experiment(
        _config(poisoned, example), tmp_path_factory.mktemp("o2"), record_trial=False
    )
    for name in ["ledger.parquet", "fills.parquet", "equity.parquet"]:
        a = pl.read_parquet(clean_run.path / name).filter(pl.col("ts") <= cutoff)
        b = pl.read_parquet(poisoned_run.path / name).filter(pl.col("ts") <= cutoff)
        assert a.equals(b), f"{name}: outputs before the poison cutoff changed — lookahead leak"
    # sanity: the poison had teeth (the second contract's price is no longer "cheap")
    clean_fills = pl.read_parquet(clean_run.path / "fills.parquet")
    poisoned_fills = pl.read_parquet(poisoned_run.path / "fills.parquet")
    assert not clean_fills.equals(poisoned_fills)


@pytest.mark.lookahead
def test_poisoning_the_future_does_not_change_the_past(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    _check_poisoned_future(tmp_path_factory, "polymarket_up.yaml", BAR_SCHEMA, _PRICES)


@pytest.mark.lookahead
def test_poisoning_future_prices_and_quotes_does_not_change_the_past_under_a_quoted_spread(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """The quote columns are part of a bar: a quoted run must not read the quotes of a later bar
    (ADR-0060)."""
    _check_poisoned_future(
        tmp_path_factory, "polymarket_up_quoted.yaml", QUOTED_BAR_SCHEMA, _PRICES + _QUOTES
    )
