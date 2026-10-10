"""Leaky-strategy canary (R2.2b): a strategy that peeks must raise LookaheadError."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.core.engine import BacktestEngine
from crucible.core.errors import LookaheadError
from crucible.core.events import BarEvent
from crucible.core.types import (
    Currency,
    DatasetId,
    RealismLevel,
    TimestampNs,
)
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
BARS = DatasetId("bars_canary")


def _build(root: Path) -> None:
    days = list(range(1, 6))
    frame = pl.DataFrame(
        {
            "symbol": ["AAA"] * 5,
            "event_time": [d * DAY for d in days],
            "available_at": [d * DAY for d in days],
            "open": [100.0] * 5,
            "high": [101.0] * 5,
            "low": [99.0] * 5,
            "close": [100.0] * 5,
            "volume": [1e6] * 5,
        }
    )
    build_dataset(root, BARS, frame, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")


class _NoOpHandlers:
    def on_start(self, ctx: BacktestContext) -> None: ...

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_order_update(self, ctx: object, event: object) -> None: ...

    def on_fill(self, ctx: object, event: object) -> None: ...

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: object) -> None: ...


class PeekTomorrow(_NoOpHandlers):
    """Requests data as of tomorrow. The engine must kill the run."""

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:  # type: ignore[override]
        ctx.data.get(BARS, ["close"], [event.symbol], TimestampNs(int(ctx.clock.now) + DAY))


def _run(root: Path, strategy: object) -> None:
    from typing import cast

    from crucible.strategy.interfaces import Strategy

    BacktestEngine(
        store=ParquetDataStore(root),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=cast(Strategy, strategy),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=Currency("USD"),
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
    ).run()


def test_peeking_strategy_is_killed(tmp_path: Path) -> None:
    _build(tmp_path)
    with pytest.raises(LookaheadError, match="lookahead"):
        _run(tmp_path, PeekTomorrow())


def test_honest_strategy_at_now_is_fine(tmp_path: Path) -> None:
    _build(tmp_path)

    class AskNow(_NoOpHandlers):
        def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:  # type: ignore[override]
            result = ctx.data.get(BARS, ["close"], [event.symbol], ctx.clock.now)
            assert (result.get_column("available_at") <= int(ctx.clock.now)).all()

    _run(tmp_path, AskNow())
