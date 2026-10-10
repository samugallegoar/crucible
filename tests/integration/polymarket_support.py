"""Shared Polymarket fixtures for the quoted-spread tests (ADR-0060): a three-contract CSV
store whose bars carry quotes, and the example config pointed at it. Importable from
``tests/integration`` only, like ``checkpoint_support``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from crucible.data.importers.build import build_from_spec
from crucible.experiments.config import ExperimentConfig

HEADER = (
    "slug,start_time,elapsed,ask_YES,bid_YES,ask_NO,bid_NO,btc_strike,btc_current,btc_gap,"
    "timestamp_log,resolved,winner"
)
QUOTES = {1000: ("0.38", "0.42"), 1300: ("0.0", "0.10"), 1600: ("0.43", "0.45")}
DATASET = "polymarket_btc5m_csv_v1"


def build_polymarket_store(tmp_path: Path, *, spot: bool = True) -> Path:
    btc = "100.0" if spot else ""  # an empty btc_current drops the spot bars
    rows = [
        f"btc-updown-5m-{start},{start},{ts - start},{ask},{bid},0.60,0.55,100.0,{btc},0.0,{ts},"
        "True,Up"
        for start, (bid, ask) in QUOTES.items()
        for ts in (start + 100, start + 102, start + 104, start + 106)
    ]
    (tmp_path / "pm.csv").write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        f"kind: polymarket_csv\ndataset: {DATASET}\ninput: '{tmp_path / 'pm.csv'}'\n"
        "bar_seconds: 2\n",
        encoding="utf-8",
    )
    store = tmp_path / "store"
    build_from_spec(spec, store)
    return store


def polymarket_config(name: str, store: Path, *, live: bool = False) -> ExperimentConfig:
    raw: dict[str, Any] = yaml.safe_load(
        Path(f"examples/real_data/{name}").read_text(encoding="utf-8")
    )
    raw["data"]["store"] = str(store)
    if live:
        raw["live"] = {"enabled": True}
    raw["start"], raw["end"] = "1970-01-01", "1970-01-01T01:00:00+00:00"
    return ExperimentConfig.model_validate(raw)
