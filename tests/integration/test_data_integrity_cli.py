"""``crucible data integrity`` end to end on a small synthetic dataset (ADR-0088)."""

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING

import polars as pl
import pytest

from crucible.cli.main import main
from crucible.core.types import DatasetId
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import build_dataset

if TYPE_CHECKING:
    from pathlib import Path

_NS = 1_000_000_000


def _rows(minutes: list[int]) -> list[dict[str, object]]:
    """One Monday session (2024-01-08) with 1-minute bars closing at 15:01 UTC + each minute."""
    start = int(dt.datetime(2024, 1, 8, 15, 1, tzinfo=dt.UTC).timestamp())
    return [
        {
            "symbol": "ES",
            "event_time": (start + m * 60) * _NS,
            "available_at": (start + m * 60) * _NS,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10.0,
        }
        for m in minutes
    ]


def _store(tmp_path: Path, minutes: list[int]) -> Path:
    root = tmp_path / "store"
    build_dataset(
        root,
        DatasetId("es_1m"),
        pl.DataFrame(_rows(minutes), schema=BAR_SCHEMA),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )
    return root


def test_the_json_report_counts_the_missing_minutes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _store(tmp_path, [0, 1, 2, 6, 7])
    assert main(["data", "integrity", "--store", str(store), "--dataset", "es_1m", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["dataset"] == "es_1m"
    assert doc["ok"] is True
    assert doc["session_rule"] == "cme"
    (sym,) = doc["symbols"]
    assert (sym["rows"], sym["missing_minutes"], sym["largest_gap_minutes"]) == (5, 3, 3)


def test_the_text_report_names_the_symbol_and_the_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _store(tmp_path, [0, 1, 2])
    assert main(["data", "integrity", "--store", str(store), "--dataset", "es_1m"]) == 0
    out = capsys.readouterr().out
    assert "es_1m: OK" in out
    assert "ES: 3 bars, 1 sessions, 0 missing minutes" in out


def test_a_calendar_adds_the_session_date_comparison(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _store(tmp_path, [0, 1])
    argv = ["data", "integrity", "--store", str(store), "--dataset", "es_1m", "--json"]
    assert main([*argv, "--calendar", "CMES"]) == 0
    cal = json.loads(capsys.readouterr().out)["calendar"]
    assert cal["name"] == "CMES"
    assert cal["data_sessions"] == 1


def test_an_unknown_dataset_is_a_structured_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _store(tmp_path, [0])
    code = main(["data", "integrity", "--store", str(store), "--dataset", "missing", "--json"])
    assert code != 0
    error = json.loads(capsys.readouterr().out)["error"]
    assert "dataset 'missing' not found" in error["message"]


def test_a_contract_violation_exits_1_and_still_prints_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store refuses to write a defective dataset, so the violation is injected at the read."""
    store = _store(tmp_path, [0, 1])
    from crucible.data import integrity

    real = integrity.integrity_report

    def with_a_duplicate(frame: pl.LazyFrame, **kwargs: object) -> dict[str, object]:
        return real(pl.concat([frame, frame.head(1)]), **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(integrity, "integrity_report", with_a_duplicate)
    argv = ["data", "integrity", "--store", str(store), "--dataset", "es_1m", "--json"]
    assert main(argv) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is False
    assert doc["errors"]["duplicate_bars"] == 1
