"""A spec with a stop, through the real vectorized engine (ADR-0082).

The unit tests cover each half on its own (the signal's ``exit_price`` column, the engine valuing
a bar at ``exit_price``). This is the join between them: the signal marks a bar with no stop fill
as ``NaN``, and an engine that read ``NaN`` as a price turned every held bar's return into ``NaN``
(``is_not_null`` is true for ``NaN``) and the whole equity curve with it.

Hand computation, frictionless, 100000 of capital, a long held from the first bar with a 5% stop:
every bar opens and closes at 100 except bar 4, whose low is 94 and close is 99.

* ``level``: the stop level is 95, the bar opened at 100 above it, so it fills at 95 and bar 4
  returns 95 / 100 - 1 = -5%; equity 95000, flat afterwards (the position is re-entered at the
  next close, which earns nothing on flat bars).
* ``close``: the close of 99 is only -1% from 100, so the stop does not trigger; bar 4 returns
  -1% (99000) and bar 5 returns 100 / 99 - 1 (back to 100000).
"""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.core.types import DatasetId, RealismLevel, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.strategy_spec import parse_spec, spec_signal
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig

DAY = 86_400_000_000_000
BARS = DatasetId("stop_bars")
N = 8


def _store(root: Path) -> ParquetDataStore:
    low = [100.0] * N
    close = [100.0] * N
    low[3] = 94.0  # bar index 3 (the fourth): pierces the 95 stop
    close[3] = 99.0
    frame = pl.DataFrame(
        {
            "symbol": ["AAA"] * N,
            "event_time": [DAY * (i + 1) for i in range(N)],
            "available_at": [DAY * (i + 1) for i in range(N)],
            "open": [100.0] * N,
            "high": [100.0] * N,
            "low": low,
            "close": close,
            "volume": [1e6] * N,
        },
        schema=BAR_SCHEMA,
    )
    build_dataset(root, BARS, frame, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")
    return ParquetDataStore(root)


def _final_equity(stop_fill: str) -> tuple[float, int]:
    spec = parse_spec(
        {
            "spec_version": 1,
            "entry": {"long": "always"},
            "sizing": {"type": "all_in"},
            "risk": {"stop_loss_pct": 5, "stop_fill": stop_fill},
        }
    )
    with tempfile.TemporaryDirectory() as raw:
        result = VectorizedBacktestEngine().run(
            VectorizedConfig(
                store=_store(Path(raw)),
                bars_dataset=BARS,
                signal=spec_signal,
                params={"spec": spec.model_dump(mode="json")},
                initial_cash=Decimal("100000"),
                realism_level=RealismLevel.FRICTIONLESS,
                start=TimestampNs(DAY),
                end=TimestampNs(DAY * (N + 1)),
            )
        )
    equity = result.equity.sort("ts").get_column("equity")
    return float(equity[-1]), int(equity.is_nan().sum())


def test_a_wick_through_the_stop_fills_at_the_level_and_leaves_no_nan() -> None:
    final, nan_rows = _final_equity("level")
    assert nan_rows == 0
    assert final == pytest.approx(95_000.0)


def test_the_close_model_waits_for_a_closing_breach() -> None:
    final, nan_rows = _final_equity("close")
    assert nan_rows == 0
    assert final == pytest.approx(100_000.0)
