"""The dataset catalog (ADR-0089): identity, origin, lineage, contract, range and its checks."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.core.types import DatasetId
from crucible.data.catalog import dataset_catalog, parse_source
from crucible.data.continuous import DATASET_VERSION
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset

if TYPE_CHECKING:
    from pathlib import Path

_NS = 1_000_000_000
_T0 = 1_704_067_200  # 2024-01-01T00:00:00Z


def _bars(symbols: list[str], n: int = 3) -> pl.DataFrame:
    rows = [
        {
            "symbol": s,
            "event_time": (_T0 + 60 * (i + 1)) * _NS,
            "available_at": (_T0 + 60 * (i + 1)) * _NS,
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 1.0,
        }
        for s in symbols
        for i in range(n)
    ]
    return pl.DataFrame(rows, schema=BAR_SCHEMA)


def _build(root: Path, name: str, source: str, symbols: list[str] | None = None) -> str:
    manifest = build_dataset(
        root,
        DatasetId(name),
        _bars(symbols or ["ESH4"]),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source=source,
    )
    return manifest.content_hash


def _edit_manifest(root: Path, name: str, **changes: object) -> None:
    path = root / name / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.update(changes)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _entry(catalog: dict[str, object], name: str) -> dict[str, object]:
    entries = catalog["datasets"]
    assert isinstance(entries, list)
    (found,) = [e for e in entries if e["dataset"] == name]
    assert isinstance(found, dict)
    return found


def test_parse_source_splits_origin_fields_and_flags() -> None:
    parsed = parse_source("continuous:v2;rolls;root=ES;from=es_1m_raw@abcd;dropped=a:1,b:2")
    assert parsed == {
        "origin": "continuous:v2",
        "fields": {"root": "ES", "from": "es_1m_raw@abcd", "dropped": "a:1,b:2"},
        "flags": ["rolls"],
    }


def test_free_text_source_is_kept_whole_as_the_origin() -> None:
    assert parse_source("null-test shuffle") == {
        "origin": "null-test shuffle",
        "fields": {},
        "flags": [],
    }


def test_an_entry_reports_identity_contract_and_range(tmp_path: Path) -> None:
    content_hash = _build(
        tmp_path, "es_raw", "import:databento_dbn;price_basis=raw", ["ESM4", "ESH4"]
    )
    entry = _entry(dataset_catalog(ParquetDataStore(tmp_path)), "es_raw")
    assert entry["contract"] == "bars"
    assert entry["content_hash"] == content_hash
    assert entry["rows"] == 6
    assert entry["origin"] == entry["root_origin"] == "import:databento_dbn"
    assert entry["price_basis"] == "raw"
    assert entry["parent"] is None
    assert entry["range"] == {
        "first": "2024-01-01T00:01:00Z",
        "last": "2024-01-01T00:03:00Z",
        "symbols": 2,
        "symbol_examples": ["ESH4", "ESM4"],
    }
    assert entry["ok"] is True
    assert entry["errors"] == entry["findings"] == []
    assert entry["checksum_verified"] is None


def test_top_bounds_the_symbols_listed_but_not_the_count(tmp_path: Path) -> None:
    _build(tmp_path, "many", "import:x", ["A", "B", "C"])
    entry = _entry(dataset_catalog(ParquetDataStore(tmp_path), top=1), "many")
    assert entry["range"] == {
        "first": "2024-01-01T00:01:00Z",
        "last": "2024-01-01T00:03:00Z",
        "symbols": 3,
        "symbol_examples": ["A"],
    }


def test_lineage_follows_parents_to_the_root_origin(tmp_path: Path) -> None:
    raw_hash = _build(tmp_path, "raw", "import:databento_dbn;price_basis=raw")
    mid_hash = _build(tmp_path, "mid", f"continuous:{DATASET_VERSION};from=raw@{raw_hash[:16]}")
    _build(tmp_path, "top", f"derived:x;from=mid@{mid_hash[:16]}")
    entry = _entry(dataset_catalog(ParquetDataStore(tmp_path)), "top")
    assert entry["parent"] == "mid"
    assert entry["lineage"] == ["mid", "raw"]
    assert entry["root_origin"] == "import:databento_dbn"
    assert entry["findings"] == []


def test_a_rebuilt_parent_is_a_finding_not_an_error(tmp_path: Path) -> None:
    _build(tmp_path, "raw", "import:x")
    _build(tmp_path, "child", f"continuous:{DATASET_VERSION};from=raw@0000000000000000")
    catalog = dataset_catalog(ParquetDataStore(tmp_path))
    entry = _entry(catalog, "child")
    assert entry["ok"] is True
    assert catalog["ok"] is True
    (finding,) = entry["findings"]  # type: ignore[misc]
    assert "parent dataset 'raw' was rebuilt" in finding


def test_a_missing_parent_is_a_finding_and_ends_the_lineage(tmp_path: Path) -> None:
    _build(tmp_path, "child", "derived:x;from=gone@abc")
    entry = _entry(dataset_catalog(ParquetDataStore(tmp_path)), "child")
    assert entry["findings"] == ["parent dataset 'gone' is not in this store"]
    assert entry["lineage"] == ["gone"]
    assert entry["root_origin"] == "unknown"


def test_a_lineage_cycle_stops_instead_of_looping(tmp_path: Path) -> None:
    _build(tmp_path, "a", "derived:x;from=b@")
    _build(tmp_path, "b", "derived:y;from=a@")
    entry = _entry(dataset_catalog(ParquetDataStore(tmp_path)), "a")
    assert entry["lineage"] == ["b", "a"]


def test_an_older_continuous_builder_is_reported_as_superseded(tmp_path: Path) -> None:
    _build(tmp_path, "old", "continuous:v1;root=ES")
    _build(tmp_path, "new", f"continuous:{DATASET_VERSION};root=ES")
    catalog = dataset_catalog(ParquetDataStore(tmp_path))
    (finding,) = _entry(catalog, "old")["findings"]  # type: ignore[misc]
    assert f"the current one is {DATASET_VERSION}" in finding
    assert _entry(catalog, "new")["findings"] == []
    assert catalog["ok"] is True


def test_verify_confirms_the_checksum(tmp_path: Path) -> None:
    _build(tmp_path, "d", "import:x")
    catalog = dataset_catalog(ParquetDataStore(tmp_path), verify=True)
    assert catalog["verified"] is True
    assert _entry(catalog, "d")["checksum_verified"] is True


def test_verify_refuses_a_file_that_is_not_the_manifests(tmp_path: Path) -> None:
    _build(tmp_path, "d", "import:x")
    _edit_manifest(tmp_path, "d", content_hash="f" * 64)
    catalog = dataset_catalog(ParquetDataStore(tmp_path), verify=True)
    entry = _entry(catalog, "d")
    assert catalog["ok"] is False
    assert entry["checksum_verified"] is False
    (error,) = entry["errors"]  # type: ignore[misc]
    assert "the file changed after it was built" in error


def test_a_row_count_mismatch_is_an_error(tmp_path: Path) -> None:
    _build(tmp_path, "d", "import:x")
    _edit_manifest(tmp_path, "d", row_count=99)
    entry = _entry(dataset_catalog(ParquetDataStore(tmp_path)), "d")
    assert entry["errors"] == ["the data file has 3 rows, the manifest says 99"]
    assert entry["ok"] is False


def test_a_manifest_naming_another_dataset_is_an_error(tmp_path: Path) -> None:
    _build(tmp_path, "d", "import:x")
    _edit_manifest(tmp_path, "d", dataset="other")
    entry = _entry(dataset_catalog(ParquetDataStore(tmp_path)), "d")
    assert entry["errors"] == ["the manifest names dataset 'other', not 'd'"]


def test_a_missing_data_file_is_an_error_entry(tmp_path: Path) -> None:
    _build(tmp_path, "d", "import:x")
    (tmp_path / "d" / "data.parquet").unlink()
    entry = _entry(dataset_catalog(ParquetDataStore(tmp_path)), "d")
    assert entry["ok"] is False
    assert entry["range"] is None
    (error,) = entry["errors"]  # type: ignore[misc]
    assert "is missing: rebuild the dataset" in error


def test_datasets_restricts_the_catalog_and_refuses_unknown_names(tmp_path: Path) -> None:
    _build(tmp_path, "a", "import:x")
    _build(tmp_path, "b", "import:x")
    store = ParquetDataStore(tmp_path)
    catalog = dataset_catalog(store, datasets=[DatasetId("b")])
    assert [e["dataset"] for e in catalog["datasets"]] == ["b"]  # type: ignore[attr-defined]
    with pytest.raises(ConfigurationError, match=r"\['missing'\] not found"):
        dataset_catalog(store, datasets=[DatasetId("missing")])


def test_negative_top_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="top must be >= 0"):
        dataset_catalog(ParquetDataStore(tmp_path), top=-1)


def test_the_catalog_is_deterministic_and_sorted(tmp_path: Path) -> None:
    _build(tmp_path, "b", "import:x")
    _build(tmp_path, "a", "import:x")
    store = ParquetDataStore(tmp_path)
    first = dataset_catalog(store)
    assert first == dataset_catalog(store)
    assert [e["dataset"] for e in first["datasets"]] == ["a", "b"]  # type: ignore[attr-defined]


def test_an_empty_store_has_an_empty_ok_catalog(tmp_path: Path) -> None:
    assert dataset_catalog(ParquetDataStore(tmp_path / "none")) == {
        "report": "catalog",
        "verified": False,
        "ok": True,
        "datasets": [],
    }
