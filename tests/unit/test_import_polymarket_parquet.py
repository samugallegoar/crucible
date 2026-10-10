"""Polymarket Parquet input (ADR-0052): same bars as the CSV path on equivalent data."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.data.importers.build import build_from_spec
from crucible.data.importers.polymarket import import_polymarket
from crucible.data.importers.spec import PolymarketSpec

HEADER = (
    "slug,start_time,elapsed,ask_YES,bid_YES,ask_NO,bid_NO,btc_strike,btc_current,btc_gap,"
    "timestamp_log,resolved,winner"
)
TICKS = [  # ts, up_bid, up_ask, down_bid, down_ask, btc
    (1100.0, 0.40, 0.44, 0.56, 0.60, 100.0),
    (1101.0, 0.48, 0.52, 0.48, 0.52, 101.0),
    (1103.0, 0.60, 0.64, 0.36, 0.40, 102.0),
]


def _csv_spec(folder: Path) -> PolymarketSpec:
    folder.mkdir()
    lines = [
        f"btc-updown-5m-1000,1000,{int(ts) - 1000},{ua},{ub},{da},{db},100.0,{btc},0.0,"
        f"{int(ts)},True,Up"
        for ts, ub, ua, db, da, btc in TICKS
    ]
    (folder / "pm.csv").write_text("\n".join([HEADER, *lines]) + "\n", encoding="utf-8")
    return PolymarketSpec.model_validate(
        {
            "kind": "polymarket_csv",
            "dataset": "pm",
            "input": str(folder / "pm.csv"),
            "bar_seconds": 2,
        }
    )


def _parquet_spec(
    tmp_path: Path, ticks: Sequence[tuple[float, ...]] | None = None, **over: Any
) -> PolymarketSpec:
    rows = ticks if ticks is not None else TICKS
    pl.DataFrame(
        {
            "event_slug": ["btc-updown-5m-1000"] * len(rows),
            "ts": [r[0] for r in rows],
            "poly_up_bid": [r[1] for r in rows],
            "poly_up_ask": [r[2] for r in rows],
            "poly_down_bid": [r[3] for r in rows],
            "poly_down_ask": [r[4] for r in rows],
            "binance_price": [r[5] for r in rows],
            "coinbase_price": [r[5] + 1 for r in rows],
            "kraken_price": [r[5] + 2 for r in rows],
        }
    ).write_parquet(tmp_path / "ticks.parquet")
    pl.DataFrame(
        {
            "event_slug": ["btc-updown-5m-1000"],
            "window_start_ts": [1000],
            "window_end_ts": [1300],
            "winner_side": ["UP"],
            "target": [1],
        }
    ).write_parquet(tmp_path / "outcomes.parquet")
    raw: dict[str, Any] = {
        "kind": "polymarket_parquet",
        "dataset": "pm",
        "input": str(tmp_path / "ticks.parquet"),
        "outcomes": str(tmp_path / "outcomes.parquet"),
        "bar_seconds": 2,
    }
    raw.update(over)
    return PolymarketSpec.model_validate(raw)


def _run(spec: PolymarketSpec) -> Any:
    return import_polymarket(spec, start=None, end=None, max_contracts=None)


def test_the_parquet_path_matches_the_csv_path_on_equivalent_data(tmp_path: Path) -> None:
    csv = _run(_csv_spec(tmp_path / "csv"))
    parquet = _run(_parquet_spec(tmp_path))
    cols = ["symbol", "event_time"]
    assert csv.datasets[0].frame.sort(cols).equals(parquet.datasets[0].frame.sort(cols))
    assert csv.datasets[1].frame.sort("symbol").equals(parquet.datasets[1].frame.sort("symbol"))


def test_a_contract_in_the_ticks_without_an_outcome_is_unresolved(tmp_path: Path) -> None:
    spec = _parquet_spec(tmp_path)
    ticks = pl.read_parquet(tmp_path / "ticks.parquet")
    extra = ticks.head(1).with_columns(event_slug=pl.lit("btc-updown-5m-1300"))
    pl.concat([ticks, extra]).write_parquet(tmp_path / "ticks.parquet")
    result = _run(spec)
    assert "BTC5M-1300-UP" not in set(result.datasets[0].frame["symbol"].to_list())
    assert result.report.extra["contracts_unresolved"] == 1


def test_the_spot_source_selects_the_exchange_price(tmp_path: Path) -> None:
    result = _run(_parquet_spec(tmp_path, spot_source="kraken"))
    frame = result.datasets[0].frame
    spot = frame.filter(frame["symbol"] == "BTCUSD").sort("event_time")
    assert spot["close"].to_list()[:2] == [103.0, 104.0]  # kraken = binance + 2


def test_fractional_second_ticks_bucket_by_the_floor_second(tmp_path: Path) -> None:
    ticks = [(1100.4, 0.40, 0.44, 0.56, 0.60, 100.0), (1101.9, 0.48, 0.52, 0.48, 0.52, 101.0)]
    result = _run(_parquet_spec(tmp_path, ticks))
    frame = result.datasets[0].frame
    up = frame.filter(frame["symbol"] == "BTC5M-1000-UP").sort("event_time").to_dicts()
    assert up[0]["event_time"] == 1102 * 10**9
    assert (up[0]["open"], up[0]["close"]) == pytest.approx((0.42, 0.50))


def test_a_missing_outcomes_file_is_refused(tmp_path: Path) -> None:
    spec = _parquet_spec(tmp_path, outcomes=str(tmp_path / "gone.parquet"))
    with pytest.raises(ConfigurationError, match=r"gone\.parquet"):
        _run(spec)


def test_an_outcome_window_that_disagrees_with_window_seconds_is_refused(tmp_path: Path) -> None:
    spec = _parquet_spec(tmp_path, window_seconds=600)
    with pytest.raises(ConfigurationError, match="window_seconds"):
        _run(spec)


def test_the_size_guard_refuses_before_writing_a_polymarket_dataset(tmp_path: Path) -> None:
    _parquet_spec(tmp_path)
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(
        f"kind: polymarket_parquet\ndataset: pm\ninput: '{tmp_path / 'ticks.parquet'}'\n"
        f"outcomes: '{tmp_path / 'outcomes.parquet'}'\nbar_seconds: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="max-rows"):
        build_from_spec(spec_file, tmp_path / "store", max_rows=1)
    assert not (tmp_path / "store" / "pm").exists()


def test_the_ticks_importer_carries_the_first_and_last_quote_of_each_bucket(
    tmp_path: Path,
) -> None:
    result = _run(_parquet_spec(tmp_path))
    frame = result.datasets[0].frame.filter(pl.col("symbol") == "BTC5M-1000-UP").sort("event_time")
    first = frame.row(0, named=True)
    # bucket (1100, 1102] holds ticks 1100 (0.40/0.44) and 1101 (0.48/0.52)
    assert (first["bid_open"], first["ask_open"], first["bid_close"], first["ask_close"]) == (
        pytest.approx(0.40),
        pytest.approx(0.44),
        pytest.approx(0.48),
        pytest.approx(0.52),
    )
