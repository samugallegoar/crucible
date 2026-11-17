"""``crucible data catalog`` end to end on a small store (ADR-0089)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import polars as pl

from crucible.cli.main import main
from crucible.core.types import DatasetId
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import build_dataset

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_NS = 1_000_000_000


def _store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    frame = pl.DataFrame(
        [
            {
                "symbol": "ES",
                "event_time": (1_704_067_260 + 60 * i) * _NS,
                "available_at": (1_704_067_260 + 60 * i) * _NS,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 10.0,
            }
            for i in range(3)
        ],
        schema=BAR_SCHEMA,
    )
    raw = build_dataset(
        root,
        DatasetId("es_raw"),
        frame,
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="import:databento_dbn;price_basis=raw",
    )
    build_dataset(
        root,
        DatasetId("es_cont"),
        frame,
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source=f"continuous:v1;from=es_raw@{raw.content_hash[:16]}",
    )
    return root


def test_the_json_catalog_lists_lineage_and_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _store(tmp_path)
    assert main(["data", "catalog", "--store", str(store), "--json", "--verify"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is True
    assert doc["verified"] is True
    cont, raw = doc["datasets"]
    assert (cont["dataset"], raw["dataset"]) == ("es_cont", "es_raw")
    assert cont["lineage"] == ["es_raw"]
    assert cont["root_origin"] == "import:databento_dbn"
    assert raw["checksum_verified"] is True
    assert len(cont["findings"]) == 1  # continuous:v1 is superseded


def test_the_text_catalog_shows_one_line_per_dataset_and_its_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _store(tmp_path)
    assert main(["data", "catalog", "--store", str(store), "--dataset", "es_cont"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("es_cont  OK  bars  rows=3")
    assert "origin=import:databento_dbn" in out
    assert "a newer version of this series supersedes it" in out
    assert "es_raw  OK" not in out


def test_a_tampered_manifest_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = _store(tmp_path)
    path = store / "es_raw" / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["row_count"] = 7
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert main(["data", "catalog", "--store", str(store), "--json"]) == 1
    entry = json.loads(capsys.readouterr().out)["datasets"][1]
    assert entry["errors"] == ["the data file has 3 rows, the manifest says 7"]


def test_an_unknown_dataset_is_a_structured_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _store(tmp_path)
    code = main(["data", "catalog", "--store", str(store), "--dataset", "nope", "--json"])
    assert code != 0
    assert "not found in the store" in json.loads(capsys.readouterr().out)["error"]["message"]
