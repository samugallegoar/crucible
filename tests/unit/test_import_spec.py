"""Import spec models (ADR-0052): explicit, validated, no defaults for the risky choices."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from crucible.core.errors import ConfigurationError
from crucible.data.importers.spec import OhlcvSpec, PolymarketSpec, load_spec


def _ohlcv() -> dict[str, Any]:
    return {
        "kind": "ohlcv_csv",
        "dataset": "equities_daily_v1",
        "input": "data/*.csv",
        "price_basis": "adjusted",
        "columns": {
            "timestamp": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        },
        "symbol": {"column": "Symbol"},
        "timestamp": {"format": "%Y-%m-%d", "meaning": "session_close", "calendar": "XNYS"},
    }


def _write(tmp_path: Path, raw: object) -> Path:
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_a_valid_ohlcv_spec_parses_with_safe_defaults(tmp_path: Path) -> None:
    spec = load_spec(_write(tmp_path, _ohlcv()))
    assert isinstance(spec, OhlcvSpec)
    assert spec.price_basis == "adjusted"
    assert spec.delimiter == ","
    assert spec.rows.on_incomplete == "drop"
    assert spec.rows.ohlc_repair == "refuse"  # repairing data is always an explicit opt-in
    assert spec.feed_latency_s == 0


def test_a_valid_polymarket_spec_parses(tmp_path: Path) -> None:
    raw = {"kind": "polymarket_csv", "dataset": "pm_v1", "input": "data/*.csv"}
    spec = load_spec(_write(tmp_path, raw))
    assert isinstance(spec, PolymarketSpec)
    assert spec.bar_seconds == 1
    assert spec.window_seconds == 300
    assert spec.settlement_floor == 0.001
    assert spec.spot_source == "binance"


def test_price_basis_has_no_default(tmp_path: Path) -> None:
    raw = _ohlcv()
    del raw["price_basis"]
    with pytest.raises(ConfigurationError, match="price_basis"):
        load_spec(_write(tmp_path, raw))


def test_an_unknown_kind_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="unknown kind"):
        load_spec(_write(tmp_path, {**_ohlcv(), "kind": "excel"}))


def test_the_symbol_needs_exactly_one_source_none(tmp_path: Path) -> None:
    raw = {**_ohlcv(), "symbol": {}}
    with pytest.raises(ConfigurationError, match="exactly one"):
        load_spec(_write(tmp_path, raw))


def test_the_symbol_needs_exactly_one_source_two(tmp_path: Path) -> None:
    raw = {**_ohlcv(), "symbol": {"column": "Symbol", "fixed": "XAUUSD"}}
    with pytest.raises(ConfigurationError, match="exactly one"):
        load_spec(_write(tmp_path, raw))


def test_bar_open_needs_an_interval(tmp_path: Path) -> None:
    raw = {**_ohlcv(), "timestamp": {"format": "%Y-%m-%d", "meaning": "bar_open"}}
    with pytest.raises(ConfigurationError, match="interval"):
        load_spec(_write(tmp_path, raw))


def test_session_close_needs_a_calendar(tmp_path: Path) -> None:
    raw = {**_ohlcv(), "timestamp": {"format": "%Y-%m-%d", "meaning": "session_close"}}
    with pytest.raises(ConfigurationError, match="calendar"):
        load_spec(_write(tmp_path, raw))


def test_session_close_refuses_the_24_7_calendar(tmp_path: Path) -> None:
    raw = {
        **_ohlcv(),
        "timestamp": {"format": "%Y-%m-%d", "meaning": "session_close", "calendar": "24/7"},
    }
    with pytest.raises(ConfigurationError, match="bar_open"):
        load_spec(_write(tmp_path, raw))


def test_an_unknown_key_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="bogus"):
        load_spec(_write(tmp_path, {**_ohlcv(), "bogus": 1}))


def test_a_parquet_polymarket_spec_needs_an_outcomes_file(tmp_path: Path) -> None:
    raw = {"kind": "polymarket_parquet", "dataset": "pm_v1", "input": "ticks.parquet"}
    with pytest.raises(ConfigurationError, match="outcomes"):
        load_spec(_write(tmp_path, raw))


def test_a_missing_spec_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_spec(tmp_path / "nope.yaml")


def test_a_spec_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="mapping"):
        load_spec(_write(tmp_path, ["a", "b"]))


def test_a_malformed_interval_is_refused(tmp_path: Path) -> None:
    raw = {**_ohlcv(), "timestamp": {"format": "%Y-%m-%d", "meaning": "bar_open", "interval": "2x"}}
    with pytest.raises(ConfigurationError, match="interval"):
        load_spec(_write(tmp_path, raw))


def test_an_offset_in_the_format_needs_a_utc_timezone(tmp_path: Path) -> None:
    """%z parses to an absolute instant; re-labelling it with another zone would shift it."""
    timestamp = {
        "format": "%Y-%m-%dT%H:%M:%S%z",
        "timezone": "America/New_York",
        "meaning": "bar_close",
    }
    with pytest.raises(ConfigurationError, match="%z"):
        load_spec(_write(tmp_path, {**_ohlcv(), "timestamp": timestamp}))
    ok = {**timestamp, "timezone": "UTC"}
    assert isinstance(load_spec(_write(tmp_path, {**_ohlcv(), "timestamp": ok})), OhlcvSpec)
