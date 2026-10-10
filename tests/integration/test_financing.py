"""Borrow cost and margin financing accrual through the real engine (ADR-0032).
Hand-computed ledgers per AGENTS.md §7.

Both accrue proportionally to elapsed simulation time (Actual/365) against
the position/balance *as of the end of* the just-elapsed period (an
end-of-period snapshot convention, not intraday time-weighting) --
`short_borrow_rate`/`margin_financing_rate` of 0.365 (36.5% annualized) is
chosen only so ``rate / 365 == 0.001`` exactly, giving clean per-day
dollar amounts; it is not meant to be a realistic rate.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl

from crucible.core.engine import BacktestEngine
from crucible.core.events import BarEvent
from crucible.core.instruments import FuturesSpec
from crucible.core.types import Currency, DatasetId, OrderSide, RealismLevel, Symbol, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
BARS = DatasetId("financing_bars")
AAA = Symbol("AAA")
USD = Currency("USD")


def _bars(root: Path, n: int, price: float) -> None:
    build_dataset(
        root,
        BARS,
        pl.DataFrame(
            {
                "symbol": ["AAA"] * n,
                "event_time": [(d + 1) * DAY for d in range(n)],
                "available_at": [(d + 1) * DAY for d in range(n)],
                "open": [price] * n,
                "high": [price + 0.5] * n,
                "low": [price - 0.5] * n,
                "close": [price] * n,
                "volume": [1e6] * n,
            }
        ),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )


class OpenPositionAndHold:
    """Submits one order on session 1 (side/qty given), then holds."""

    def __init__(self, side: OrderSide, qty: str) -> None:
        self._side = side
        self._qty = Decimal(qty)

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["sessions"] = 0

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        sessions = ctx.state["sessions"]
        assert isinstance(sessions, int)
        sessions += 1
        ctx.state["sessions"] = sessions
        if sessions == 1:
            ctx.orders.submit(AAA, self._side, self._qty)

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


def test_borrow_cost_accrues_daily_on_a_held_short(tmp_path: Path) -> None:
    """Short 100 AAA @ 100 (fills day2), held through day4, constant
    price (isolates borrow cost from price P&L). short_borrow_rate=0.365
    -> exactly $10/day on a $10000 short notional.
      day1 mark: no position yet (order not filled) -> accrual 0
      day2 mark: fill just posted this bar -> full day's fee on the
        now-open short: 10000 * 0.365 * (1/365) = 10
      day3, day4 marks: still short 100 @ 100 -> 10/day each
      total accrued over days 2-4: 30
      final cash = 100000 (initial) + 10000 (short proceeds) - 30 (fees)
      final equity = cash - 10000 (short's own mark, unchanged price)
                   = 100000 - 30 (price didn't move; only cost is borrow)
    """
    _bars(tmp_path, n=4, price=100.0)
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=OpenPositionAndHold(OrderSide.SELL, "100"),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(5 * DAY),
        short_borrow_rate=0.365,
    )
    result = engine.run()

    snapshot = result.final_snapshot
    assert snapshot.cash(USD) == Decimal("109970")  # 100000 + 10000 - 30
    assert snapshot.equity(USD) == Decimal("99970")  # 100000 - 30

    borrow_txns = [r for r in result.ledger_rows if r["type"] == "borrow"]
    assert len(borrow_txns) == 3  # day2, day3, day4 marks
    assert all(Decimal(str(t["amount"])) == Decimal("-10") for t in borrow_txns)


def test_margin_financing_accrues_on_a_negative_cash_balance(tmp_path: Path) -> None:
    """Buy 100 AAA @ 100 (fills day2) with only 1000 initial cash and no
    risk engine to stop it -> cash goes to -9000. margin_financing_rate
    =0.365 -> exactly $9/day on a $9000 debit balance.
      day2 mark: fill just posted this bar -> full day's fee on the
        now-negative cash: 9000 * 0.365 * (1/365) = 9
      final cash = 1000 - 10000 (buy) - 9 (financing) = -9009
    """
    _bars(tmp_path, n=2, price=100.0)
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=OpenPositionAndHold(OrderSide.BUY, "100"),
        params={},
        initial_cash=Decimal("1000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(3 * DAY),
        margin_financing_rate=0.365,
    )
    result = engine.run()

    snapshot = result.final_snapshot
    assert snapshot.cash(USD) == Decimal("-9009")

    financing_txns = [r for r in result.ledger_rows if r["type"] == "financing"]
    assert len(financing_txns) == 1
    assert Decimal(str(financing_txns[0]["amount"])) == Decimal("-9")


def test_zero_rates_accrue_nothing(tmp_path: Path) -> None:
    """Default rates (0.0) -- zero behavior change: a held short accrues
    no borrow cost at all."""
    _bars(tmp_path, n=4, price=100.0)
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=OpenPositionAndHold(OrderSide.SELL, "100"),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(5 * DAY),
    )
    result = engine.run()

    assert not [r for r in result.ledger_rows if r["type"] in ("borrow", "financing")]
    assert result.final_snapshot.equity(USD) == Decimal("100000")


def test_borrow_cost_never_applies_to_a_short_futures_position(tmp_path: Path) -> None:
    """Regression test (found by code review): a short
    *futures* position must never accrue a stock-loan borrow fee --
    shorting a future is entering a symmetric contract, not borrowing a
    security to sell, so there is nothing to charge. Constant price
    (no MTM either) isolates this: with the bug, cash would still drop
    from the (wrongly charged, wrongly unscaled) borrow fee; fixed,
    cash and equity stay exactly at the initial amount."""
    _bars(tmp_path, n=4, price=100.0)
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=OpenPositionAndHold(OrderSide.SELL, "100"),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(5 * DAY),
        short_borrow_rate=0.365,
        futures_specs={AAA: FuturesSpec(multiplier=Decimal("50"))},
    )
    result = engine.run()

    assert not [r for r in result.ledger_rows if r["type"] == "borrow"]
    assert result.final_snapshot.cash(USD) == Decimal("100000")
    assert result.final_snapshot.equity(USD) == Decimal("100000")
