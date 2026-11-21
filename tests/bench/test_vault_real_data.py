"""The holdout vault against the REAL store path, without touching it (C6c, ADR-0105).

Run: CRUCIBLE_DATA_STORE=D:/proyectos/crucible/data/processed uv run pytest -m bench \\
        tests/bench/test_vault_real_data.py

This is the only place where a declaration meets the real store, and it is careful about it:

- the declaration is written to a THROWAWAY store root and a THROWAWAY home; nothing is written
  into the real store or into the real Crucible home. The guard is pointed at the throwaway
  declaration by the ``home=`` argument of ``ParquetDataStore``, the seam a test needs;
- a read with ``as_of`` before the vault start succeeds, and a read with an ``as_of`` in 2025 is
  REFUSED BEFORE ANY ROW IS READ: the spy proves ``pl.scan_parquet`` is never called for it, which
  is what "the guard is in the data layer, not in the CLI" means.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import polars as pl
import pytest

from crucible.core.errors import VaultLockedError
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.store import ParquetDataStore
from crucible.data.vault import clear_guard_cache, declare_vault, vault_start_ns

STORE = Path(os.environ.get("CRUCIBLE_DATA_STORE", "data/processed"))
pytestmark = pytest.mark.bench

DATASET = DatasetId("es_1m_cont_v3")
START = dt.date(2025, 1, 1)


@pytest.fixture
def declared_home(tmp_path: Path) -> Path:
    """A throwaway declaration (tmp store root AND tmp home): the real store stays untouched."""
    assert not (STORE / "vault.json").exists(), (
        "this bench must not run against a store that already carries a declaration: it is a "
        "measurement, not the vault's installation"
    )
    home = tmp_path / "home"
    declare_vault(
        store_root=tmp_path / "declaration-store",
        home=home,
        universe=["ES", "NQ", "YM", "RTY", "NKD"],
        start_trade_date=START,
        audit_ref="bench: a throwaway declaration over the real store path (ADR-0105)",
    )
    clear_guard_cache()
    return home


def _need() -> None:
    if not (STORE / DATASET / "data.parquet").exists():
        pytest.skip(f"{DATASET} not built in {STORE}; see docs/data/glbx-futures-1m.md")


def test_a_pre_vault_read_succeeds_and_a_2025_read_is_refused_before_any_scan(
    declared_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _need()
    store = ParquetDataStore(STORE, home=declared_home)
    start_ns = vault_start_ns(_declaration(store))
    scans = {"count": 0}
    real_scan = pl.scan_parquet

    def spy(*args: object, **kwargs: object) -> pl.LazyFrame:
        scans["count"] += 1
        return real_scan(*args, **kwargs)

    monkeypatch.setattr("polars.scan_parquet", spy)

    # before the vault: the read is admitted and the scan happens
    frame = store.read(DATASET, TimestampNs(start_ns - 1)).select(pl.len()).collect()
    assert int(frame["len"][0] or 0) > 0
    assert scans["count"] == 1

    # inside the vault: refused, and NOTHING is scanned (the guard runs before the file is opened)
    with pytest.raises(VaultLockedError):
        store.read(DATASET, TimestampNs(start_ns)).collect()
    with pytest.raises(VaultLockedError):
        store.read(DATASET, TimestampNs(2**63 - 1)).collect()
    assert scans["count"] == 1, "a refused read must not reach the Parquet file at all"


def _declaration(store: ParquetDataStore) -> object:
    guard = store.guard
    assert guard is not None
    return guard.declaration
