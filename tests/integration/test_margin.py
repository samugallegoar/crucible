"""Margin and short-selling through the real engine (ADR-0031). Hand-computed ledgers per AGENTS.md
§7 -- never derived from the
engine.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl

from crucible.core.engine import BacktestEngine
from crucible.core.events import BarEvent
from crucible.core.types import Currency, DatasetId, OrderSide, RealismLevel, Symbol, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.risk.engine import CompositeRiskEngine
from crucible.risk.limits import MarginCallLimit, MarginRequirementLimit
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
BARS = DatasetId("margin_bars")
AAA = Symbol("AAA")
USD = Currency("USD")


def _bars(root: Path, rows: dict[str, list[object]]) -> None:
    build_dataset(
        root, BARS, pl.DataFrame(rows), schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test"
    )


class _SessionCounter:
    """Shared plumbing: tracks a 1-indexed session counter (one bar ==
    one session, single symbol) and delegates to ``_on_session``."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["sessions"] = 0

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        sessions = ctx.state["sessions"]
        assert isinstance(sessions, int)
        sessions += 1
        ctx.state["sessions"] = sessions
        self._on_session(ctx, sessions)

    def _on_session(self, ctx: BacktestContext, session: int) -> None:
        raise NotImplementedError

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


class ShortThenCover(_SessionCounter):
    """Opens a 50-share short on session 1, covers it on session 4."""

    def _on_session(self, ctx: BacktestContext, session: int) -> None:
        if session == 1:
            ctx.orders.submit(AAA, OrderSide.SELL, Decimal("50"))
        elif session == 4:
            ctx.orders.submit(AAA, OrderSide.BUY, Decimal("50"))


class OpenShortAndHold(_SessionCounter):
    """Opens a 50-share short on session 1 and takes no further action --
    any subsequent close is the risk engine's doing (a margin call)."""

    def _on_session(self, ctx: BacktestContext, session: int) -> None:
        if session == 1:
            ctx.orders.submit(AAA, OrderSide.SELL, Decimal("50"))


def test_a_short_position_round_trips_with_a_hand_computed_realized_gain(tmp_path: Path) -> None:
    """USD/AAA. Short 50 @ 100 (day2 fill), price drops to 80, cover 50 @ 80
    (day5 fill) -- a classic profitable short.
      day2 fill: SELL 50@100 -> cash 10000+5000=15000; position -50@100
      day5 fill: BUY  50@80  -> cash 15000-4000=11000; realized_pnl =
        (80-100)*(-50) = 1000 (profit); position flat
      final equity = cash 11000 + 0 = 11000 = initial 10000 + 1000 profit
    """
    _bars(
        tmp_path,
        {
            "symbol": ["AAA"] * 6,
            "event_time": [(d + 1) * DAY for d in range(6)],
            "available_at": [(d + 1) * DAY for d in range(6)],
            "open": [100.0, 100.0, 100.0, 90.0, 80.0, 80.0],
            "high": [100.5, 100.5, 100.5, 90.5, 80.5, 80.5],
            "low": [99.5, 99.5, 99.5, 89.5, 79.5, 79.5],
            "close": [100.0, 100.0, 100.0, 90.0, 80.0, 80.0],
            "volume": [1e6] * 6,
        },
    )
    risk = CompositeRiskEngine(USD, pre_trade_limits=[MarginRequirementLimit(1.5)])
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=ShortThenCover(),
        params={},
        initial_cash=Decimal("10000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(7 * DAY),
        risk_engine=risk,
    )
    result = engine.run()

    snapshot = result.final_snapshot
    assert snapshot.position(AAA) is None  # flat
    assert snapshot.cash(USD) == Decimal("11000")
    assert snapshot.equity(USD) == Decimal("11000")
    assert snapshot.realized_pnl == Decimal("1000")

    sells = [r for r in result.order_rows if r["side"] == "sell"]
    buys = [r for r in result.order_rows if r["side"] == "buy"]
    assert len(sells) == 1
    assert sells[0]["state"] == "filled"
    assert len(buys) == 1
    assert buys[0]["state"] == "filled"


def test_a_short_beyond_initial_margin_is_rejected(tmp_path: Path) -> None:
    """Same setup, but initial cash too small: short notional 5000 at
    open (50@100), required = 1.5*5000 = 7500 > cash 5000 -> REJECT."""
    _bars(
        tmp_path,
        {
            "symbol": ["AAA"] * 3,
            "event_time": [(d + 1) * DAY for d in range(3)],
            "available_at": [(d + 1) * DAY for d in range(3)],
            "open": [100.0] * 3,
            "high": [100.5] * 3,
            "low": [99.5] * 3,
            "close": [100.0] * 3,
            "volume": [1e6] * 3,
        },
    )
    risk = CompositeRiskEngine(USD, pre_trade_limits=[MarginRequirementLimit(1.5)])
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=OpenShortAndHold(),
        params={},
        initial_cash=Decimal("5000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(4 * DAY),
        risk_engine=risk,
    )
    result = engine.run()

    assert len(result.order_rows) == 1
    assert result.order_rows[0]["state"] == "rejected"
    assert result.final_snapshot.position(AAA) is None
    assert result.final_snapshot.cash(USD) == Decimal("5000")


def test_a_margin_call_force_covers_a_short_at_a_hand_computed_loss(tmp_path: Path) -> None:
    """USD/AAA. Short 50 @ 100 (day2 fill); price jumps to 140 (day3) --
    equity 15000-7000=8000 < maintenance requirement 1.3*7000=9100 ->
    MarginCallLimit FLATTENs; the forced BUY fills day4 @ 140.
      day2 fill: SELL 50@100 -> cash 15000; position -50@100
      day4 fill: BUY  50@140 -> cash 15000-7000=8000; realized_pnl =
        (140-100)*(-50) = -2000 (forced-cover loss); position flat
      final equity = cash 8000 + 0 = 8000 = initial 10000 - 2000 loss
    """
    _bars(
        tmp_path,
        {
            "symbol": ["AAA"] * 5,
            "event_time": [(d + 1) * DAY for d in range(5)],
            "available_at": [(d + 1) * DAY for d in range(5)],
            "open": [100.0, 100.0, 140.0, 140.0, 140.0],
            "high": [100.5, 100.5, 140.5, 140.5, 140.5],
            "low": [99.5, 99.5, 139.5, 139.5, 139.5],
            "close": [100.0, 100.0, 140.0, 140.0, 140.0],
            "volume": [1e6] * 5,
        },
    )
    risk = CompositeRiskEngine(
        USD,
        pre_trade_limits=[MarginRequirementLimit(1.5)],
        mark_limits=[MarginCallLimit(1.3)],
    )
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=OpenShortAndHold(),
        params={},
        initial_cash=Decimal("10000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
        risk_engine=risk,
    )
    result = engine.run()

    snapshot = result.final_snapshot
    assert snapshot.position(AAA) is None  # margin-called flat
    assert snapshot.cash(USD) == Decimal("8000")
    assert snapshot.equity(USD) == Decimal("8000")
    assert snapshot.realized_pnl == Decimal("-2000")

    buys = [r for r in result.order_rows if r["side"] == "buy"]
    assert len(buys) == 1
    assert buys[0]["state"] == "filled"
    assert buys[0]["qty"] == "50"
