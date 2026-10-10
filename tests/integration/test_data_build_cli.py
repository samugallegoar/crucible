"""crucible data build through main(argv) (ADR-0052)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from crucible.cli.main import main


def _csv(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _spec(tmp_path: Path, **over: Any) -> Path:
    raw: dict[str, Any] = {
        "kind": "ohlcv_csv",
        "dataset": "eq_v1",
        "input": str(tmp_path / "raw" / "*.csv"),
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
    raw.update(over)
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    folder = tmp_path / "raw"
    folder.mkdir()
    _csv(
        folder / "eq.csv",
        [
            "Date,Open,High,Low,Close,Volume,Symbol",
            "2020-01-02,10,12,9,11,100,aapl",
            "2020-01-03,11,13,10,12,200,aapl",
        ],
    )
    return folder


def test_build_writes_a_labelled_deterministic_dataset(
    tmp_path: Path, raw: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec(tmp_path)
    assert main(["data", "build", str(spec), "--store", str(tmp_path / "a")]) == 0
    assert main(["data", "build", str(spec), "--store", str(tmp_path / "b")]) == 0
    out = capsys.readouterr().out
    assert "eq_v1" in out
    assert "price_basis=adjusted" in out
    a, b = tmp_path / "a" / "eq_v1", tmp_path / "b" / "eq_v1"
    assert (
        hashlib.sha256((a / "data.parquet").read_bytes()).digest()
        == hashlib.sha256((b / "data.parquet").read_bytes()).digest()
    )
    assert (a / "import_report.json").read_bytes() == (b / "import_report.json").read_bytes()
    report = json.loads((a / "import_report.json").read_text(encoding="utf-8"))
    assert report["rows_written"] == {"eq_v1": 2}
    manifest = json.loads((a / "manifest.json").read_text(encoding="utf-8"))
    assert "price_basis=adjusted" in manifest["source"]


def test_a_built_dataset_passes_data_check(tmp_path: Path, raw: Path) -> None:
    assert main(["data", "build", str(_spec(tmp_path)), "--store", str(tmp_path / "s")]) == 0
    code = main(
        [
            "data",
            "check",
            "--store",
            str(tmp_path / "s"),
            "--dataset",
            "eq_v1",
            "--calendar",
            "XNYS",
        ]
    )
    assert code == 0


def test_a_quality_refusal_writes_nothing(
    tmp_path: Path, raw: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _csv(
        raw / "eq.csv",
        ["Date,Open,High,Low,Close,Volume,Symbol", "2020-01-02,10,10.5,10.2,11,100,aapl"],
    )
    code = main(["data", "build", str(_spec(tmp_path)), "--store", str(tmp_path / "s")])
    assert code == 1
    assert "ohlc_bounds" in capsys.readouterr().err
    assert not (tmp_path / "s" / "eq_v1").exists()


def test_coverage_needs_a_calendar_or_an_explicit_skip(
    tmp_path: Path, raw: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    timestamp = {"format": "%Y-%m-%d", "meaning": "bar_open", "interval": "1d"}
    spec = _spec(tmp_path, symbol={"fixed": "XAUUSD"}, timestamp=timestamp)
    assert main(["data", "build", str(spec), "--store", str(tmp_path / "s")]) == 1
    assert "calendar_coverage" in capsys.readouterr().err
    skipped = _spec(
        tmp_path,
        symbol={"fixed": "XAUUSD"},
        timestamp=timestamp,
        quality_skip=["calendar_coverage"],
        quality_skip_reason="24/5 market: weekends have no bars",
    )
    assert main(["data", "build", str(skipped), "--store", str(tmp_path / "s")]) == 0


def test_polymarket_only_options_are_refused_for_ohlcv(
    tmp_path: Path, raw: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [
        "data",
        "build",
        str(_spec(tmp_path)),
        "--store",
        str(tmp_path / "s"),
        "--start",
        "2020-01-01",
    ]
    assert main(argv) == 1
    assert "polymarket" in capsys.readouterr().err


def test_the_row_guard_refuses_before_writing(
    tmp_path: Path, raw: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [
        "data",
        "build",
        str(_spec(tmp_path)),
        "--store",
        str(tmp_path / "s"),
        "--max-rows",
        "1",
    ]
    assert main(argv) == 1
    assert "max-rows" in capsys.readouterr().err
    assert not (tmp_path / "s" / "eq_v1").exists()


def test_data_check_can_repeat_a_recorded_skip(tmp_path: Path, raw: Path) -> None:
    timestamp = {"format": "%Y-%m-%d", "meaning": "bar_open", "interval": "1d"}
    spec = _spec(
        tmp_path,
        symbol={"fixed": "XAUUSD"},
        timestamp=timestamp,
        quality_skip=["calendar_coverage"],
        quality_skip_reason="24/5 market: weekends have no bars",
    )
    store = str(tmp_path / "s")
    assert main(["data", "build", str(spec), "--store", store]) == 0
    base = ["data", "check", "--store", store, "--dataset", "eq_v1", "--calendar", "24/7"]
    assert main([*base, "--skip", "calendar_coverage"]) == 1  # a skip needs a reason
    code = main([*base, "--skip", "calendar_coverage", "--skip-reason", "24/5 market"])
    assert code == 0
