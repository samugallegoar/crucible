"""``crucible data continuous`` end to end on a small synthetic raw dataset (ADR-0086)."""

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING

import polars as pl
import pytest

from crucible.cli.main import main
from crucible.core.types import DatasetId
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset

if TYPE_CHECKING:
    from pathlib import Path

_NS = 1_000_000_000
A, B = "ESH2024", "ESM2024"


def _bars(contract: str, session: int, price: float, volume: float) -> list[dict[str, object]]:
    day = dt.date(2024, 1, 2) + dt.timedelta(days=session)
    rows: list[dict[str, object]] = []
    for minute in range(3):
        opened = dt.datetime(day.year, day.month, day.day, 15, minute, tzinfo=dt.UTC)
        close = (int(opened.timestamp()) + 60) * _NS
        p = price + 0.25 * minute
        rows.append(
            {
                "symbol": contract,
                "event_time": close,
                "available_at": close,
                "open": p,
                "high": p + 0.5,
                "low": p - 0.25,
                "close": p + 0.25,
                "volume": volume,
            }
        )
    return rows


@pytest.fixture
def store(tmp_path: Path) -> Path:
    rows = [r for i in range(10) for r in _bars(A, i, 4700.0, 100.0)]
    rows += [r for i in range(13) for r in _bars(B, i, 4710.0, 150.0 if i >= 6 else 10.0)]
    root = tmp_path / "store"
    build_dataset(
        root,
        DatasetId("es_1m_raw"),
        pl.DataFrame(rows, schema=BAR_SCHEMA),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="import:databento_dbn;price_basis=raw",
    )
    return root


def test_the_command_builds_three_datasets_per_root(
    store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["data", "continuous", "--store", str(store), "--roots", "es", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert "threshold=1.0;backstop_sessions=1" in doc["parameters"]
    (report,) = doc["roots"]
    assert report["root"] == "ES"
    assert report["rolls"] == 1
    assert report["rolls_by_reason"] == {"volume": 1}
    assert [d["dataset"] for d in report["datasets"]] == [
        "es_1m_cont_v3",
        "es_1m_cont_ratio_v3",
        "es_1m_rolls_v3",
    ]
    names = {str(d) for d in ParquetDataStore(store).list_datasets()}
    assert {"es_1m_cont_v3", "es_1m_cont_ratio_v3", "es_1m_rolls_v3"} <= names


def test_the_text_output_names_each_dataset(
    store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["data", "continuous", "--store", str(store), "--roots", "ES"]) == 0
    out = capsys.readouterr().out
    assert "ES: 1 rolls" in out
    assert "es_1m_cont_ratio_v3" in out


def test_a_missing_raw_dataset_is_a_structured_error(
    store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["data", "continuous", "--store", str(store), "--roots", "nq", "--json"])
    assert code == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "experiment_error"
    assert "nq_1m_raw" in error["message"]
    assert error["location"]["command"] == "data"


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (["--roots", ","], "--roots is empty"),
        (["--roots", "es", "--raw", "es_1m_raw"], "must contain {root}"),
        (["--roots", "es", "--threshold", "0"], "threshold must be > 0"),
        (["--roots", "es", "--backstop-sessions", "-1"], "backstop_sessions must be >= 0"),
    ],
)
def test_bad_arguments_are_refused_with_a_code(
    store: Path, capsys: pytest.CaptureFixture[str], extra: list[str], expected: str
) -> None:
    assert main(["data", "continuous", "--store", str(store), "--json", *extra]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "configuration_error"
    assert expected in error["message"]


def test_a_rebuild_reproduces_the_hashes(store: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["data", "continuous", "--store", str(store), "--roots", "es", "--json"]
    assert main(argv) == 0
    first = json.loads(capsys.readouterr().out)["roots"][0]["datasets"]
    assert main(argv) == 0
    second = json.loads(capsys.readouterr().out)["roots"][0]["datasets"]
    assert [d["content_hash"] for d in first] == [d["content_hash"] for d in second]
