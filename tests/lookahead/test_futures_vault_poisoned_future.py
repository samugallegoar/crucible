"""The holdout vault does not change a pre-vault run, and it cannot leak a poisoned vault row
(Fathom C6c, ADR-0105; AGENTS.md §7 and §9).

Two guarantees, at the value level, on the synthetic two-date ES store of
``tests/integration/test_futures_run_artifact.py`` extended with a POISONED trade date inside the
vault (2025-01-06, priced at 1.0, which no signal decides the same way as a 4400 series):

- the poison is real: without a declaration, a window that reaches it simulates it and the marks
  change;
- with the vault declared, a run whose window ends on 2024-03-06 produces the SAME run id, the same
  artifact id and byte-identical result files as it did BEFORE the declaration, and the window that
  reaches the poison is refused -- at the config level and, if it got that far, at the read level.

Nothing here touches a real dataset: the store is built by the test, and the declaration lives in a
throwaway home (``CRUCIBLE_HOME``).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from crucible.core.errors import VaultLockedError
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CONTINUOUS_BAR_SCHEMA,
    CONTINUOUS_BAR_SORT_KEYS,
    ROLL_SCHEMA,
    ROLL_SORT_KEYS,
)
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.data.vault import clear_guard_cache, declare_vault
from crucible.experiments.futures_config import parse_futures_config
from crucible.experiments.futures_run import run_futures
from tests.integration.test_futures_run_artifact import (
    CLOSES,
    DAY1,
    DAY2,
    ESH,
    ESM,
    WALLS,
    _ohlc,
    _raw,
    _rolls,
    mapping,
    utc,
)

pytestmark = pytest.mark.lookahead

POISON_DAY = "2025-01-06"
"""A Globex trade date INSIDE the C6c vault (which starts at 2025-01-01)."""
POISON_PRICES = [1.0, 1.0, 1.0, 1.0, 1.0]
"""Absurd prices: no signal decides the same way on these as on a 4400 series."""


def _poisoned_continuous() -> pl.DataFrame:
    """The artifact test's 2024 series plus one poisoned ESM session inside the vault."""
    rows: list[tuple[int, str, tuple[float, float, float, float]]] = []
    for day, contract in ((DAY1, ESH), (DAY2, ESM)):
        for wall, close in zip(WALLS, CLOSES[day], strict=True):
            rows.append((utc(f"{day} {wall}"), contract, _ohlc(close)))
    for wall, close in zip(WALLS, POISON_PRICES, strict=True):
        rows.append((utc(f"{POISON_DAY} {wall}"), ESM, _ohlc(close)))
    return pl.DataFrame(
        {
            "symbol": ["ES"] * len(rows),
            "event_time": [t for t, _, _ in rows],
            "available_at": [t + 1 for t, _, _ in rows],
            "open": [p[0] for _, _, p in rows],
            "high": [p[1] for _, _, p in rows],
            "low": [p[2] for _, _, p in rows],
            "close": [p[3] for _, _, p in rows],
            "volume": [100.0] * len(rows),
            "contract": [contract for _, contract, _ in rows],
        },
        schema=CONTINUOUS_BAR_SCHEMA,
    )


def _poisoned_raw() -> pl.DataFrame:
    extra = pl.DataFrame(
        {
            "symbol": [ESM] * len(WALLS),
            "event_time": [utc(f"{POISON_DAY} {wall}") for wall in WALLS],
            "available_at": [utc(f"{POISON_DAY} {wall}") + 1 for wall in WALLS],
            "open": [_ohlc(price)[0] for price in POISON_PRICES],
            "high": [_ohlc(price)[1] for price in POISON_PRICES],
            "low": [_ohlc(price)[2] for price in POISON_PRICES],
            "close": [_ohlc(price)[3] for price in POISON_PRICES],
            "volume": [100.0] * len(WALLS),
        },
        schema=BAR_SCHEMA,
    )
    combined = pl.concat([_raw(), extra])
    return combined.sort(["symbol", "event_time"])


def build_poisoned_store(root: Path) -> Path:
    """The artifact test's store plus a poisoned session inside the vault."""
    root.mkdir(parents=True, exist_ok=True)
    execution = _poisoned_continuous()
    factors = pl.Series([1.01 if contract != ESM else 1.0 for contract in execution["contract"]])
    ratio = execution.with_columns(
        [(pl.col(name) * factors).alias(name) for name in ("open", "high", "low", "close")]
    )
    build_dataset(
        root,
        DatasetId("es_1m_cont_v3"),
        execution,
        schema=CONTINUOUS_BAR_SCHEMA,
        sort_keys=CONTINUOUS_BAR_SORT_KEYS,
        source="continuous:v3;price_basis=raw;adjustment=none;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_cont_ratio_v3"),
        ratio,
        schema=CONTINUOUS_BAR_SCHEMA,
        sort_keys=CONTINUOUS_BAR_SORT_KEYS,
        source="continuous:v3;price_basis=adjusted;adjustment=ratio;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_rolls_v3"),
        _rolls(),
        schema=ROLL_SCHEMA,
        sort_keys=ROLL_SORT_KEYS,
        source="continuous:v3;rolls;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_raw"),
        _poisoned_raw(),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="import:databento;price_basis=raw;rows_read=16;synthetic",
    )
    return root


def _config(store: Path, window_end: str) -> object:
    """The artifact test's config, with the window ending on ``window_end``."""
    from crucible.experiments.futures_config import FuturesRunConfig

    parsed: FuturesRunConfig = parse_futures_config(
        mapping(**{"window": {"start": "2024-03-05", "end": window_end}})
    )
    return parsed


def _declare(store: Path, home: Path) -> None:
    declare_vault(
        store_root=store,
        home=home,
        universe=["ES", "NQ", "YM", "RTY", "NKD"],
        start_trade_date=dt.date(2025, 1, 1),
        audit_ref="the exposure audit of 2026-11-19 (ADR-0105)",
    )


def test_the_poison_is_real_and_the_vault_refuses_the_window_that_reaches_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = build_poisoned_store(tmp_path / "store")
    home = tmp_path / "home"
    monkeypatch.setenv("CRUCIBLE_HOME", str(home))
    clear_guard_cache()

    wide = run_futures(
        _config(store, POISON_DAY),  # type: ignore[arg-type]
        store_root=store,
        artifacts_root=tmp_path / "wide-plain",
    )
    assert wide.summary["trade_dates"] == 3
    marks = pl.read_parquet(wide.run_dir / "marks.parquet")
    daily = pl.read_parquet(wide.run_dir / "daily.parquet")
    # the poisoned session was simulated: it is one of the marks' trade dates
    assert str(max(marks["trade_date"].to_list())) == POISON_DAY
    assert daily.height == 3

    # a narrow run before the declaration, so the comparison below is not against a re-run
    narrow_plain = run_futures(
        _config(store, "2024-03-06"),  # type: ignore[arg-type]
        store_root=store,
        artifacts_root=tmp_path / "narrow-plain",
    )

    _declare(store, home)
    clear_guard_cache()

    # with the vault the window that reaches the poison is refused before a row is read
    with pytest.raises(VaultLockedError) as caught:
        run_futures(
            _config(store, POISON_DAY),  # type: ignore[arg-type]
            store_root=store,
            artifacts_root=tmp_path / "wide-vaulted",
        )
    assert "holdout vault" in str(caught.value)
    with pytest.raises(VaultLockedError):
        ParquetDataStore(store).read(DatasetId("es_1m_cont_v3"), TimestampNs(2**63 - 1))

    # and the pre-vault run is UNCHANGED: same ids, byte-identical result files
    narrow_vaulted = run_futures(
        _config(store, "2024-03-06"),  # type: ignore[arg-type]
        store_root=store,
        artifacts_root=tmp_path / "narrow-vaulted",
    )
    assert narrow_vaulted.run_id == narrow_plain.run_id
    assert narrow_vaulted.artifact_id == narrow_plain.artifact_id
    for name in ("marks.parquet", "daily.parquet", "fills.parquet", "rolls.parquet"):
        assert (narrow_vaulted.run_dir / name).read_bytes() == (
            narrow_plain.run_dir / name
        ).read_bytes()
    assert narrow_vaulted.summary["trade_dates"] == 2
