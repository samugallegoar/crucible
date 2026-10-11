"""Parquet dataset store with manifests (ADR-0002).

Layout: ``<root>/<dataset_id>/data.parquet`` + ``manifest.json``. Writes are
deterministic: rows sorted by the contract's sort keys, uncompressed Parquet
(ADR-0011), so identical inputs produce byte-identical files and stable
content hashes.

There is deliberately no unfiltered read: :meth:`ParquetDataStore.read`
requires ``as_of`` and filters ``available_at <= as_of`` at the scan level.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING

import polars as pl

from crucible.core.errors import ConfigurationError, DataQualityError, ExperimentError
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.contracts import END_AT_OPEN
from crucible.data.interfaces import DatasetManifest

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_MANIFEST_NAME = "manifest.json"
_DATA_NAME = "data.parquet"


def build_dataset(
    root: Path,
    dataset: DatasetId,
    frame: pl.DataFrame,
    *,
    schema: dict[str, pl.DataType],
    sort_keys: Sequence[str],
    source: str,
    schema_version: str = "1",
) -> DatasetManifest:
    """Writes a contract-conforming dataset deterministically and returns its
    manifest. Build time is an I/O boundary: wall-clock is allowed here and
    only here; it is recorded in the manifest, never hashed."""
    missing = [c for c in schema if c not in frame.columns]
    if missing:
        msg = f"dataset {dataset}: missing contract columns {missing}"
        raise DataQualityError(msg)
    out = frame.select(list(schema)).cast(schema).sort(list(sort_keys))  # type: ignore[arg-type]

    directory = root / dataset
    directory.mkdir(parents=True, exist_ok=True)
    data_path = directory / _DATA_NAME
    out.write_parquet(data_path, compression="uncompressed", statistics=False)

    content_hash = hashlib.sha256(data_path.read_bytes()).hexdigest()
    manifest = DatasetManifest(
        dataset=dataset,
        schema_version=schema_version,
        content_hash=content_hash,
        row_count=out.height,
        source=source,
        built_at=TimestampNs(time.time_ns()),
    )
    (directory / _MANIFEST_NAME).write_text(
        json.dumps(
            {
                "dataset": str(manifest.dataset),
                "schema_version": manifest.schema_version,
                "content_hash": manifest.content_hash,
                "row_count": manifest.row_count,
                "source": manifest.source,
                "built_at": int(manifest.built_at),
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",  # platform newline translation would change bytes (ADR-0011)
    )
    return manifest


def price_basis_of(manifest: DatasetManifest) -> str | None:
    """The price basis a dataset declares (``"raw"`` or ``"adjusted"``), read from the
    ``price_basis=`` field the importers and providers write into ``source``; None when the
    dataset does not declare one (a hand-built or synthetic dataset): unknown, not raw
    (ADR-0071)."""
    for part in manifest.source.split(";"):
        key, _, value = part.partition("=")
        if key.strip() == "price_basis" and value.strip() in ("raw", "adjusted"):
            return value.strip()
    return None


class ParquetDataStore:
    """Satisfies ``crucible.data.interfaces.DataStore``."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _dir(self, dataset: DatasetId) -> Path:
        directory = self._root / dataset
        if not (directory / _MANIFEST_NAME).is_file():
            msg = (
                f"dataset {dataset!r} not found under {self._root} "
                f"(no {_MANIFEST_NAME}). Build it with `crucible data build` "
                "or crucible.data.store.build_dataset."
            )
            raise ExperimentError(msg)
        return directory

    def read(self, dataset: DatasetId, as_of: TimestampNs) -> pl.LazyFrame:
        """Lazy scan filtered to ``available_at <= as_of``. The filter is part
        of the read itself; no caller ever sees the unfiltered file."""
        return pl.scan_parquet(self._dir(dataset) / _DATA_NAME).filter(
            pl.col("available_at") <= int(as_of)
        )

    def manifest(self, dataset: DatasetId) -> DatasetManifest:
        raw = json.loads((self._dir(dataset) / _MANIFEST_NAME).read_text(encoding="utf-8"))
        return DatasetManifest(
            dataset=DatasetId(raw["dataset"]),
            schema_version=raw["schema_version"],
            content_hash=raw["content_hash"],
            row_count=raw["row_count"],
            source=raw["source"],
            built_at=TimestampNs(raw["built_at"]),
        )

    def refuse_dividends_on_adjusted_bars(
        self, bars: DatasetId, corporate_actions: DatasetId | None
    ) -> None:
        """Adjusted prices already contain every dividend; booking the dataset's cash dividends
        on top would count each one twice. Refuses that combination (ADR-0071). A bars dataset
        that does not declare its basis cannot be checked and is let through."""
        if corporate_actions is None or price_basis_of(self.manifest(bars)) != "adjusted":
            return
        # a configuration check over the whole actions file, not a strategy read: the as_of is
        # the open-ended sentinel on purpose
        n_dividends = (
            self.read(corporate_actions, TimestampNs(END_AT_OPEN))
            .filter(pl.col("action") == "cash_dividend")
            .select(pl.len())
            .collect()
            .item()
        )
        if n_dividends:
            msg = (
                f"bars dataset {bars} is dividend-adjusted (price_basis=adjusted) and corporate "
                f"actions dataset {corporate_actions} has {n_dividends} cash dividend(s): each "
                "dividend would be counted twice, once in the adjusted prices and once as cash. "
                "Use raw prices with the dividends, or adjusted prices without them"
            )
            raise ConfigurationError(msg)

    def list_datasets(self) -> list[DatasetId]:
        if not self._root.is_dir():
            return []
        return sorted(
            DatasetId(p.name) for p in self._root.iterdir() if (p / _MANIFEST_NAME).is_file()
        )
