"""Settlement lag wired through the real engine (ADR-0028):
sale proceeds are excluded from available cash until settlement, even
though equity already reflects them -- demonstrated via
``InsufficientCashLimit``, the natural first consumer of available cash
(there is no other observable surface for it: it never appears in
``equity_rows``).

Hand computation (base USD, symbol AAA constant at 100, settlement_lag=2
days):
  initial cash: 10000
  session 1 (day1): submit BUY 100
  session 2 (day2): fill @ 100 -> cash 0, available_cash 0 (a purchase
    settles immediately)
  session 3 (day3): submit SELL 100 (closes the position)
  session 4 (day4): fill @ 100 -> cash 10000 (equity restored);
    available_cash stays 0 until settled_at = day4 + 2 = day6
  session 5 (day5): submit BUY 50 (cost 5000) -> available_cash is still
    0 -> REJECTED (can't afford even 1 share)
  session 6 (day6): settlement lands exactly here -> available_cash
    10000 -> submit BUY 50 (cost 5000) -> ALLOWED, fills session 7
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
from crucible.risk.limits import InsufficientCashLimit
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
BARS = DatasetId("settlement_bars")
AAA = Symbol("AAA")
USD = Currency("USD")
N_BARS = 7


class TradeThenRetryBuy:
    """session1: BUY 100. session3: SELL 100 (closes it). session5 and
    session6: BUY 50, distinguished by ``created_at`` in the assertions
    (the settlement boundary falls exactly between them)."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["sessions"] = 0

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        sessions = ctx.state["sessions"]
        assert isinstance(sessions, int)
        sessions += 1
        ctx.state["sessions"] = sessions
        if sessions == 1:
            ctx.orders.submit(AAA, OrderSide.BUY, Decimal("100"))
        elif sessions == 3:
            ctx.orders.submit(AAA, OrderSide.SELL, Decimal("100"))
        elif sessions in (5, 6):
            ctx.orders.submit(AAA, OrderSide.BUY, Decimal("50"))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


def _build(root: Path) -> None:
    build_dataset(
        root,
        BARS,
        pl.DataFrame(
            {
                "symbol": ["AAA"] * N_BARS,
                "event_time": [(d + 1) * DAY for d in range(N_BARS)],
                "available_at": [(d + 1) * DAY for d in range(N_BARS)],
                "open": [100.0] * N_BARS,
                "high": [101.0] * N_BARS,
                "low": [99.0] * N_BARS,
                "close": [100.0] * N_BARS,
                "volume": [1e6] * N_BARS,
            }
        ),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )


def test_unsettled_sale_proceeds_cannot_be_spent_until_settlement(tmp_path: Path) -> None:
    _build(tmp_path)
    risk = CompositeRiskEngine(USD, pre_trade_limits=[InsufficientCashLimit()])
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=TradeThenRetryBuy(),
        params={},
        initial_cash=Decimal("10000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs((N_BARS + 2) * DAY),
        risk_engine=risk,
        settlement_lag_days=2,
    )
    result = engine.run()

    buy_50_orders = sorted(
        (r for r in result.order_rows if r["qty"] == "50"), key=lambda r: int(r["created_at"])
    )
    assert len(buy_50_orders) == 2
    session5_order, session6_order = buy_50_orders
    assert session5_order["created_at"] == 5 * DAY
    assert session5_order["state"] == "rejected"
    assert session6_order["created_at"] == 6 * DAY
    assert session6_order["state"] == "filled"

    # once everything has settled, available cash equals total cash
    assert result.final_snapshot.available_cash(USD) == result.final_snapshot.cash(USD)


def test_a_purchase_reduces_available_cash_immediately_through_the_engine(tmp_path: Path) -> None:
    _build(tmp_path)
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=TradeThenRetryBuy(),
        params={},
        initial_cash=Decimal("10000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(3 * DAY),  # stop right after the first buy fills (session 2)
        settlement_lag_days=2,
    )
    result = engine.run()
    assert result.final_snapshot.cash(USD) == Decimal("0")
    assert result.final_snapshot.available_cash(USD) == Decimal("0")
