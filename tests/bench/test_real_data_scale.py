"""Opt-in scale benchmarks on the imported real datasets (ADR-0054).

Run: uv run pytest -m bench tests/bench -s
They skip when ``data/processed`` lacks the dataset, write nothing into the repo, and record
wall time and peak working set. Targets (spec 2026-09-27): equities 569 symbols 2015-2026 in
under 300 s and 2 GB.
"""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path
from typing import Any

import polars as pl
import psutil
import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import run_experiment

STORE = Path("data/processed")
pytestmark = pytest.mark.bench


def _need(dataset: str) -> None:
    if not (STORE / dataset / "data.parquet").exists():
        pytest.skip(f"{dataset} not built in {STORE}; see docs/data/README.md")


def _run(config: dict[str, Any], tmp: Path) -> tuple[float, float]:
    """Wall seconds and the process's peak working set in MB (Windows) or RSS (elsewhere)."""
    cfg = ExperimentConfig.model_validate(config)
    t0 = time.perf_counter()
    run_experiment(cfg, tmp, record_trial=False)
    seconds = time.perf_counter() - t0
    info = psutil.Process().memory_info()
    return seconds, getattr(info, "peak_wset", info.rss) / 1e6


def _report(name: str, seconds: float, megabytes: float) -> None:
    print(f"\nBENCH {name}: seconds={seconds:.1f} peak_mb={megabytes:.0f}")


def _iso(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / 1e9, dt.UTC).date().isoformat()


def test_equities_momentum_569_symbols_full_range(tmp_path: Path) -> None:
    _need("equities_daily_v1")
    raw = yaml.safe_load(Path("examples/real_data/equities_momentum.yaml").read_text("utf-8"))
    symbols = (
        pl.scan_parquet(STORE / "equities_daily_v1" / "data.parquet")
        .select("symbol")
        .unique()
        .sort("symbol")
        .collect()["symbol"]
        .to_list()
    )
    raw["strategy"]["params"]["symbols"] = symbols
    seconds, megabytes = _run(raw, tmp_path)
    _report("equities_momentum_569", seconds, megabytes)
    assert seconds < 300, f"target is 300 s, took {seconds:.0f}"
    assert megabytes < 2000, f"target is 2000 MB, peaked at {megabytes:.0f}"


def test_gold_trend_15m_full_history(tmp_path: Path) -> None:
    _need("xauusd_15m_v1")
    raw = yaml.safe_load(Path("examples/real_data/gold_trend.yaml").read_text("utf-8"))
    seconds, megabytes = _run(raw, tmp_path)
    _report("gold_trend_15m", seconds, megabytes)


def test_polymarket_csv_all_contracts(tmp_path: Path) -> None:
    _need("polymarket_btc5m_csv_v1")
    raw = yaml.safe_load(Path("examples/real_data/polymarket_up.yaml").read_text("utf-8"))
    bars = pl.scan_parquet(STORE / "polymarket_btc5m_csv_v1" / "data.parquet")
    lo, hi = (
        bars.select(first=pl.col("event_time").min(), last=pl.col("event_time").max())
        .collect()
        .row(0)
    )
    raw["start"] = _iso(int(lo))
    raw["end"] = _iso(int(hi) + 86_400 * 10**9)
    seconds, megabytes = _run(raw, tmp_path)
    _report("polymarket_csv", seconds, megabytes)
