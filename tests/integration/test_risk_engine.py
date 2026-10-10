"""Risk engine wiring through the real engine (ADR-0027):
pre-trade RESIZE/REJECT and on-mark HALT/FLATTEN each proven with a real
run, not just the limit classes in isolation
(`tests/unit/test_risk_limits.py`).
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
from crucible.risk.limits import DailyLossFlattenLimit, DrawdownHaltLimit, MaxOrderNotionalLimit
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
HOUR = 3_600 * 10**9
BARS = DatasetId("risk_bars")
AAA = Symbol("AAA")
USD = Currency("USD")


def _build_daily(root: Path, closes: list[float]) -> None:
    n = len(closes)
    build_dataset(
        root,
        BARS,
        pl.DataFrame(
            {
                "symbol": ["AAA"] * n,
                "event_time": [(d + 1) * DAY for d in range(n)],
                "available_at": [(d + 1) * DAY for d in range(n)],
                "open": closes,
                "high": [c * 1.01 for c in closes],
                "low": [c * 0.99 for c in closes],
                "close": closes,
                "volume": [1e6] * n,
            }
        ),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )


def _build_hourly(root: Path, closes: list[float]) -> None:
    n = len(closes)
    build_dataset(
        root,
        BARS,
        pl.DataFrame(
            {
                "symbol": ["AAA"] * n,
                "event_time": [(h + 1) * HOUR for h in range(n)],
                "available_at": [(h + 1) * HOUR for h in range(n)],
                "open": closes,
                "high": [c * 1.01 for c in closes],
                "low": [c * 0.99 for c in closes],
                "close": closes,
                "volume": [1e6] * n,
            }
        ),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )


class BuyFixedQtyOnce:
    """Submits one BUY of ``qty`` shares on the first bar it sees."""

    def __init__(self, qty: str) -> None:
        self._qty = Decimal(qty)

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["done"] = False

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        if ctx.state["done"]:
            return
        ctx.state["done"] = True
        ctx.orders.submit(AAA, OrderSide.BUY, self._qty)

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


class BuyThenTryAgainOnSession5:
    """Buys 100 on session 1; tries to buy 10 more on session 5 (used to
    probe whether trading has been halted by then)."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["sessions"] = 0

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        sessions = ctx.state["sessions"]
        assert isinstance(sessions, int)
        sessions += 1
        ctx.state["sessions"] = sessions
        if sessions == 1:
            ctx.orders.submit(AAA, OrderSide.BUY, Decimal("100"))
        elif sessions == 5:
            ctx.orders.submit(AAA, OrderSide.BUY, Decimal("10"))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


def _engine(store: Path, strategy: object, *, risk_engine: object, end_bars: int) -> BacktestEngine:
    return BacktestEngine(
        store=ParquetDataStore(store),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=strategy,  # type: ignore[arg-type]
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs((end_bars + 2) * DAY),
        risk_engine=risk_engine,  # type: ignore[arg-type]
    )


def test_pre_trade_resize_shrinks_the_order_before_it_fills(tmp_path: Path) -> None:
    _build_daily(tmp_path, [50.0, 50.0, 50.0])
    risk = CompositeRiskEngine(USD, pre_trade_limits=[MaxOrderNotionalLimit(Decimal("1000"))])
    engine = _engine(tmp_path, BuyFixedQtyOnce("100"), risk_engine=risk, end_bars=3)
    result = engine.run()
    fills = [r for r in result.fill_rows if r["symbol"] == "AAA"]
    assert len(fills) == 1
    assert Decimal(fills[0]["qty"]) == Decimal("20")  # floor(1000 / 50)


def test_pre_trade_reject_leaves_the_position_untouched(tmp_path: Path) -> None:
    _build_daily(tmp_path, [2000.0, 2000.0, 2000.0])
    risk = CompositeRiskEngine(USD, pre_trade_limits=[MaxOrderNotionalLimit(Decimal("1000"))])
    engine = _engine(tmp_path, BuyFixedQtyOnce("1"), risk_engine=risk, end_bars=3)
    result = engine.run()
    assert result.fill_rows == []
    rejected = [r for r in result.order_rows if r["state"] == "rejected"]
    assert len(rejected) == 1


def test_on_mark_halt_blocks_all_future_orders(tmp_path: Path) -> None:
    # day1: submit 100 @ 100 (unfilled); day2: fill @ 100; day3: peak @ 150;
    # day4: drop to 80 -> drawdown (105000-98000)/105000 = 6.7% > 5% -> HALT;
    # day5: a second order attempt must be rejected as halted.
    _build_daily(tmp_path, [100.0, 100.0, 150.0, 80.0, 80.0])
    risk = CompositeRiskEngine(USD, mark_limits=[DrawdownHaltLimit(max_drawdown=0.05)])
    engine = _engine(tmp_path, BuyThenTryAgainOnSession5(), risk_engine=risk, end_bars=5)
    result = engine.run()
    second_order = next(r for r in result.order_rows if r["qty"] == "10")
    assert second_order["state"] == "rejected"


def test_on_mark_flatten_closes_the_position_automatically(tmp_path: Path) -> None:
    # hour1: submit 100 @ 100; hour2: fill @ 100 (equity 100000, day-start);
    # hour3: price 40 -> equity 94000, loss 6% > 5% -> FLATTEN queues a
    # closing SELL, bypassing risk; hour4: that SELL fills @ 45.
    _build_hourly(tmp_path, [100.0, 100.0, 40.0, 45.0, 45.0])
    risk = CompositeRiskEngine(USD, mark_limits=[DailyLossFlattenLimit(max_daily_loss=0.05)])
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=BuyFixedQtyOnce("100"),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * HOUR),
        risk_engine=risk,
    )
    result = engine.run()
    fills = [r for r in result.fill_rows if r["symbol"] == "AAA"]
    assert len(fills) == 2  # the buy, then the auto-flatten sell
    sells = [f for f in fills if f["side"] == "sell"]
    assert len(sells) == 1
    assert Decimal(sells[0]["qty"]) == Decimal("100")
    assert result.final_snapshot.position(AAA) is None  # fully closed
