"""``ctx.targets`` resolved into real orders through the engine (ADR-0029). Each test hand-computes
the expected order/qty/equity per
AGENTS.md §7 -- never derived from the engine.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl

from crucible.core.engine import BacktestEngine
from crucible.core.events import BarEvent
from crucible.core.types import Currency, DatasetId, RealismLevel, Symbol, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS, FX_RATE_SCHEMA, FX_RATE_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
BARS = DatasetId("target_bars")
FX = DatasetId("target_fx")
AAA = Symbol("AAA")
BBB = Symbol("BBB")
EUR_STOCK = Symbol("EURSTOCK")
USD = Currency("USD")
EUR = Currency("EUR")


def _bars(root: Path, dataset: DatasetId, rows: dict[str, list[object]]) -> None:
    build_dataset(
        root, dataset, pl.DataFrame(rows), schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test"
    )


class _FirstBarOfSessionGuard:
    """Shared plumbing: fires ``_on_session`` once per distinct
    ``event_time`` (bars for different symbols share a timestamp)."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["sessions"] = 0
        ctx.state["last_event_time"] = -1

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        last_et = ctx.state["last_event_time"]
        assert isinstance(last_et, int)
        if int(event.event_time) <= last_et:
            return
        ctx.state["last_event_time"] = int(event.event_time)
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


class SetOneTarget(_FirstBarOfSessionGuard):
    def _on_session(self, ctx: BacktestContext, session: int) -> None:
        if session == 1:
            ctx.targets.set(AAA, 0.5)


class SetAllThenReplaceBook(_FirstBarOfSessionGuard):
    def _on_session(self, ctx: BacktestContext, session: int) -> None:
        if session == 1:
            ctx.targets.set_all({AAA: 0.5, BBB: 0.5})
        elif session == 3:
            ctx.targets.set_all({BBB: 0.5})  # AAA absent -> driven to 0


class SetForeignCurrencyTarget(_FirstBarOfSessionGuard):
    def _on_session(self, ctx: BacktestContext, session: int) -> None:
        if session == 1:
            ctx.targets.set(EUR_STOCK, 0.5)


def test_set_resolves_a_single_symbol_weight_into_an_order(tmp_path: Path) -> None:
    """USD/AAA at a constant 100, initial cash 10000. weight 0.5 -> target
    notional 5000 -> target_qty floor(5000/100) = 50. Fills next bar
    (Level 1, zero cost) -> position 50, cash 10000 - 50*100 = 5000."""
    n = 4
    _bars(
        tmp_path,
        BARS,
        {
            "symbol": ["AAA"] * n,
            "event_time": [(d + 1) * DAY for d in range(n)],
            "available_at": [(d + 1) * DAY for d in range(n)],
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1e6] * n,
        },
    )
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=SetOneTarget(),
        params={},
        initial_cash=Decimal("10000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs((n + 1) * DAY),
    )
    result = engine.run()

    buys = [r for r in result.order_rows if r["side"] == "buy"]
    assert len(buys) == 1
    assert buys[0]["qty"] == "50"

    snapshot = result.final_snapshot
    position = snapshot.position(AAA)
    assert position is not None
    assert position.qty == Decimal("50")
    assert snapshot.cash(USD) == Decimal("5000")


def test_set_all_replaces_the_full_book_zeroing_absent_symbols(tmp_path: Path) -> None:
    """AAA and BBB both USD at a constant 100. session1: set_all both to
    0.5 -> 50 shares each (equity 10000, 5000/symbol). session3: set_all
    with only BBB -> AAA (absent) is driven to 0 (closes the position);
    BBB's target (50, unchanged since equity is still 10000) needs no
    order. Final: AAA flat, BBB 50, cash back to 5000 (AAA's proceeds)."""
    n = 6
    _bars(
        tmp_path,
        BARS,
        {
            "symbol": ["AAA"] * n + ["BBB"] * n,
            "event_time": [(d + 1) * DAY for d in range(n)] * 2,
            "available_at": [(d + 1) * DAY for d in range(n)] * 2,
            "open": [100.0] * (2 * n),
            "high": [101.0] * (2 * n),
            "low": [99.0] * (2 * n),
            "close": [100.0] * (2 * n),
            "volume": [1e6] * (2 * n),
        },
    )
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=SetAllThenReplaceBook(),
        params={},
        initial_cash=Decimal("10000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs((n + 1) * DAY),
    )
    result = engine.run()

    snapshot = result.final_snapshot
    assert snapshot.position(AAA) is None  # closed out
    bbb = snapshot.position(BBB)
    assert bbb is not None
    assert bbb.qty == Decimal("50")
    assert snapshot.cash(USD) == Decimal("5000")
    assert snapshot.equity(USD) == Decimal("10000")

    sells = [r for r in result.order_rows if r["side"] == "sell"]
    assert len(sells) == 1
    assert sells[0]["symbol"] == "AAA"
    assert sells[0]["qty"] == "50"


def test_set_all_sizes_a_foreign_currency_symbol_via_fx_mid_rate(tmp_path: Path) -> None:
    """EURSTOCK trades in EUR at a constant 50 EUR; EURUSD mid constant
    1.10; base USD, initial cash 11000. weight 0.5 -> target notional
    5500 USD -> convert_from_base_at_mid(5500, USD, EUR, {EUR: 1.10}) =
    5000 EUR -> target_qty floor(5000/50) = 100 shares. Zero-cost fill
    leaves equity unchanged at 11000 (cash and position value trade off
    exactly, same identity as ADR-0025's own multi-currency test)."""
    n = 3
    _bars(
        tmp_path,
        BARS,
        {
            "symbol": ["EURSTOCK"] * n,
            "event_time": [(d + 1) * DAY for d in range(n)],
            "available_at": [(d + 1) * DAY for d in range(n)],
            "open": [50.0] * n,
            "high": [50.5] * n,
            "low": [49.5] * n,
            "close": [50.0] * n,
            "volume": [1e6] * n,
        },
    )
    build_dataset(
        tmp_path,
        FX,
        pl.DataFrame(
            {
                "symbol": ["EURUSD"] * n,
                "event_time": [(d + 1) * DAY for d in range(n)],
                "available_at": [(d + 1) * DAY for d in range(n)],
                "mid": [1.10] * n,
                "bid": [1.09] * n,
                "ask": [1.11] * n,
            }
        ),
        schema=FX_RATE_SCHEMA,
        sort_keys=FX_RATE_SORT_KEYS,
        source="test",
    )
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=SetForeignCurrencyTarget(),
        params={},
        initial_cash=Decimal("11000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs((n + 1) * DAY),
        symbol_currency={EUR_STOCK: EUR},
        fx_dataset=FX,
    )
    result = engine.run()

    buys = [r for r in result.order_rows if r["side"] == "buy"]
    assert len(buys) == 1
    assert buys[0]["qty"] == "100"

    snapshot = result.final_snapshot
    position = snapshot.position(EUR_STOCK)
    assert position is not None
    assert position.qty == Decimal("100")
    assert snapshot.cash(USD) == Decimal("11000")  # fill posted in EUR, not USD
    assert snapshot.cash(EUR) == Decimal("-5000")
    assert snapshot.equity(USD) == Decimal("11000")
