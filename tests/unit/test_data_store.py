"""Store: deterministic builds, manifests, as-of filtered reads."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest

from crucible.core.errors import DataQualityError, ExperimentError
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset

if TYPE_CHECKING:
    from pathlib import Path

BARS = DatasetId("bars_test")


def _bars_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["AAA", "AAA", "BBB", "BBB"],
            "event_time": [100, 200, 100, 200],
            "available_at": [100, 200, 100, 200],
            "open": [10.0, 10.5, 20.0, 21.0],
            "high": [10.6, 11.0, 21.5, 22.0],
            "low": [9.9, 10.4, 19.5, 20.5],
            "close": [10.5, 10.8, 21.0, 21.5],
            "volume": [1e5, 1.1e5, 2e5, 2.1e5],
        }
    )


def test_build_and_read_roundtrip(tmp_path: Path) -> None:
    manifest = build_dataset(
        tmp_path, BARS, _bars_frame(), schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test"
    )
    assert manifest.row_count == 4
    store = ParquetDataStore(tmp_path)
    assert store.manifest(BARS).content_hash == manifest.content_hash
    assert store.list_datasets() == [BARS]

    visible = store.read(BARS, TimestampNs(100)).collect()
    assert visible.height == 2
    assert set(visible.get_column("available_at").to_list()) == {100}


def test_identical_builds_hash_identically(tmp_path: Path) -> None:
    scrambled = _bars_frame().sample(fraction=1.0, shuffle=True, seed=7)
    m1 = build_dataset(
        tmp_path / "a",
        BARS,
        _bars_frame(),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )
    m2 = build_dataset(
        tmp_path / "b",
        BARS,
        scrambled,
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )
    assert m1.content_hash == m2.content_hash  # row order never leaks into identity


def test_missing_contract_column_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DataQualityError, match="missing contract columns"):
        build_dataset(
            tmp_path,
            BARS,
            _bars_frame().drop("available_at"),
            schema=BAR_SCHEMA,
            sort_keys=BAR_SORT_KEYS,
            source="test",
        )


def test_unknown_dataset_is_refused(tmp_path: Path) -> None:
    store = ParquetDataStore(tmp_path)
    with pytest.raises(ExperimentError, match="not found"):
        store.read(DatasetId("nope"), TimestampNs(0))
