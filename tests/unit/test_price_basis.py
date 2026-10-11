"""Price basis: declared in the dataset manifest, and adjusted prices are never combined with
cash dividends that they already contain (ADR-0071)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.core.types import DatasetId
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CORPORATE_ACTION_SCHEMA,
    CORPORATE_ACTION_SORT_KEYS,
)
from crucible.data.store import ParquetDataStore, build_dataset, price_basis_of

if TYPE_CHECKING:
    from pathlib import Path

DAY = 86_400 * 10**9
BARS, ACTIONS = DatasetId("bars"), DatasetId("actions")


def _store(tmp_path: Path, *, bars_source: str, action: str) -> ParquetDataStore:
    bars = pl.DataFrame(
        {
            "symbol": ["X"] * 3,
            "event_time": [DAY, 2 * DAY, 3 * DAY],
            "available_at": [DAY, 2 * DAY, 3 * DAY],
            "open": [10.0] * 3,
            "high": [10.0] * 3,
            "low": [10.0] * 3,
            "close": [10.0] * 3,
            "volume": [1.0] * 3,
        }
    )
    build_dataset(
        tmp_path, BARS, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source=bars_source
    )
    actions = pl.DataFrame(
        {
            "symbol": ["X"],
            "action": [action],
            "effective_at": [2 * DAY],
            "event_time": [2 * DAY],
            "available_at": [2 * DAY],
            "value": [0.5],
            "pay_at": [3 * DAY],
        },
        schema_overrides={"value": pl.Float64, "pay_at": pl.Int64},
    )
    build_dataset(
        tmp_path,
        ACTIONS,
        actions,
        schema=CORPORATE_ACTION_SCHEMA,
        sort_keys=CORPORATE_ACTION_SORT_KEYS,
        source="t",
    )
    return ParquetDataStore(tmp_path)


@pytest.mark.parametrize(
    ("source", "basis"),
    [
        ("import:provider:yfinance;price_basis=adjusted;rows_read=3", "adjusted"),
        ("import:ohlcv_csv;price_basis=raw;rows_read=3", "raw"),
        ("import:polymarket_csv;price_basis=n/a;rows_read=3", None),
        ("examples.momentum.build_data", None),
    ],
)
def test_the_declared_basis_is_read_from_the_manifest(
    tmp_path: Path, source: str, basis: str | None
) -> None:
    store = _store(tmp_path, bars_source=source, action="delisting")
    assert price_basis_of(store.manifest(BARS)) == basis


def test_adjusted_prices_with_cash_dividends_are_refused(tmp_path: Path) -> None:
    store = _store(tmp_path, bars_source="x;price_basis=adjusted;y", action="cash_dividend")
    with pytest.raises(ConfigurationError, match="counted twice"):
        store.refuse_dividends_on_adjusted_bars(BARS, ACTIONS)


@pytest.mark.parametrize(
    ("source", "action"),
    [
        ("x;price_basis=raw;y", "cash_dividend"),  # raw prices need the dividends
        ("x;price_basis=adjusted;y", "delisting"),  # no dividend to double count
        ("hand-built, basis not declared", "cash_dividend"),  # cannot be checked
    ],
)
def test_compatible_or_undeclared_combinations_are_allowed(
    tmp_path: Path, source: str, action: str
) -> None:
    store = _store(tmp_path, bars_source=source, action=action)
    store.refuse_dividends_on_adjusted_bars(BARS, ACTIONS)
    store.refuse_dividends_on_adjusted_bars(BARS, None)
