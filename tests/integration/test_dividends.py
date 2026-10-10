"""Dividends through the real engine (ADR-0026): received on
longs, paid on shorts, entitlement resolved on the ex-date but cash moves
on the pay-date.

Hand computation -- one combined portfolio (base USD): long 100 DIVCO
(close 50) and short 50 SHORTCO (close 20), both entered on bar2 (Level 1
next-bar fill of bar1's orders):
  initial cash: 100000
  bar2 fills: buy 100 DIVCO @ 50 (-5000), sell 50 SHORTCO @ 20 (+1000)
    cash = 100000 - 5000 + 1000 = 96000
  bar3 (ex-date): entitlement resolved from qty held now -- DIVCO
    100 * 2.00 = +200 receivable, SHORTCO -50 * 2.00 = -100 payable --
    both scheduled for pay_at (bar5); cash unchanged here
    equity = 96000 + 100*50 + (-50)*20 = 96000 + 5000 - 1000 = 100000
  bar5 (pay-date): +200 and -100 post -> cash = 96000 + 200 - 100 = 96100
    equity = 96100 + 100*50 + (-50)*20 = 96100 + 5000 - 1000 = 100100
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.core.engine import BacktestEngine
from crucible.core.events import BarEvent
from crucible.core.types import Currency, DatasetId, OrderSide, RealismLevel, Symbol, TimestampNs
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CORPORATE_ACTION_SCHEMA,
    CORPORATE_ACTION_SORT_KEYS,
)
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
BARS = DatasetId("div_bars")
ACTIONS = DatasetId("div_actions")
DIVCO = Symbol("DIVCO")
SHORTCO = Symbol("SHORTCO")
USD = Currency("USD")


def _build(root: Path) -> None:
    bars = pl.DataFrame(
        {
            "symbol": ["DIVCO"] * 5 + ["SHORTCO"] * 5,
            "event_time": [d * DAY for d in range(1, 6)] * 2,
            "available_at": [d * DAY for d in range(1, 6)] * 2,
            "open": [50.0] * 5 + [20.0] * 5,
            "high": [50.5] * 5 + [20.5] * 5,
            "low": [49.5] * 5 + [19.5] * 5,
            "close": [50.0] * 5 + [20.0] * 5,
            "volume": [1e6] * 10,
        }
    )
    build_dataset(root, BARS, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")

    actions = pl.DataFrame(
        {
            "symbol": ["DIVCO", "SHORTCO"],
            "action": ["cash_dividend", "cash_dividend"],
            "effective_at": [3 * DAY, 3 * DAY],
            "event_time": [3 * DAY, 3 * DAY],
            "available_at": [3 * DAY, 3 * DAY],
            "value": [2.0, 2.0],
            "pay_at": [5 * DAY, 5 * DAY],
        },
        schema_overrides={"value": pl.Float64, "pay_at": pl.Int64},
    )
    build_dataset(
        root,
        ACTIONS,
        actions,
        schema=CORPORATE_ACTION_SCHEMA,
        sort_keys=CORPORATE_ACTION_SORT_KEYS,
        source="test",
    )


class BuyDivcoShortShortco:
    """On the first bar of each symbol: buy 100 DIVCO, short 50 SHORTCO."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["done"] = set()

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        done = ctx.state["done"]
        assert isinstance(done, set)
        if event.symbol in done:
            return
        done.add(event.symbol)
        if event.symbol == DIVCO:
            ctx.orders.submit(DIVCO, OrderSide.BUY, Decimal("100"))
        elif event.symbol == SHORTCO:
            ctx.orders.submit(SHORTCO, OrderSide.SELL, Decimal("50"))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("div_data")
    _build(root)
    return root


def _run(store: Path) -> object:
    engine = BacktestEngine(
        store=ParquetDataStore(store),
        bars_dataset=BARS,
        corporate_actions_dataset=ACTIONS,
        strategy=BuyDivcoShortShortco(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
    )
    return engine.run()


def test_dividends_are_resolved_on_ex_date_and_paid_on_pay_date(store: Path) -> None:
    result = _run(store)
    equity_by_ts = {int(row["ts"]): row["equity"] for row in result.equity_rows}  # type: ignore[attr-defined]
    assert equity_by_ts[3 * DAY] == pytest.approx(100000.0)  # ex-date: no cash moved yet
    assert equity_by_ts[5 * DAY] == pytest.approx(100100.0)  # pay-date: net +100 received


def test_dividend_with_no_pay_at_is_refused(tmp_path: Path) -> None:
    from crucible.core.errors import DataQualityError

    bars = pl.DataFrame(
        {
            "symbol": ["DIVCO"] * 3,
            "event_time": [d * DAY for d in range(1, 4)],
            "available_at": [d * DAY for d in range(1, 4)],
            "open": [50.0] * 3,
            "high": [50.5] * 3,
            "low": [49.5] * 3,
            "close": [50.0] * 3,
            "volume": [1e6] * 3,
        }
    )
    build_dataset(tmp_path, BARS, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")
    actions = pl.DataFrame(
        {
            "symbol": ["DIVCO"],
            "action": ["cash_dividend"],
            "effective_at": [2 * DAY],
            "event_time": [2 * DAY],
            "available_at": [2 * DAY],
            "value": [2.0],
            "pay_at": [None],  # malformed: dividends must set pay_at
        },
        schema_overrides={"value": pl.Float64, "pay_at": pl.Int64},
    )
    build_dataset(
        tmp_path,
        ACTIONS,
        actions,
        schema=CORPORATE_ACTION_SCHEMA,
        sort_keys=CORPORATE_ACTION_SORT_KEYS,
        source="test",
    )
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=ACTIONS,
        strategy=BuyDivcoShortShortco(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(3 * DAY),
    )
    with pytest.raises(DataQualityError, match="pay_at"):
        engine.run()


def test_dividend_on_a_short_position_is_paid_on_pay_date(store: Path) -> None:
    result = _run(store)
    ledger_rows = result.ledger_rows  # type: ignore[attr-defined]
    dividend_rows = [row for row in ledger_rows if row["type"] == "dividend"]
    shortco_dividend = next(row for row in dividend_rows if row["symbol"] == "SHORTCO")
    assert Decimal(shortco_dividend["amount"]) == Decimal("-100")
    divco_dividend = next(row for row in dividend_rows if row["symbol"] == "DIVCO")
    assert Decimal(divco_dividend["amount"]) == Decimal("200")


class ScriptedDivco:
    """Submits DIVCO orders on chosen bars: ``{bar_day: [(side, qty), ...]}``.
    At Level 1 an order submitted on bar N fills on bar N+1."""

    def __init__(self, script: dict[int, list[tuple[OrderSide, str]]]) -> None:
        self._script = script

    def on_start(self, ctx: BacktestContext) -> None: ...

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        if event.symbol != DIVCO:
            return
        for side, qty in self._script.get(int(event.ts) // DAY, []):
            ctx.orders.submit(DIVCO, side, Decimal(qty))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


def _run_scripted(store: Path, script: dict[int, list[tuple[OrderSide, str]]]) -> object:
    engine = BacktestEngine(
        store=ParquetDataStore(store),
        bars_dataset=BARS,
        corporate_actions_dataset=ACTIONS,
        strategy=ScriptedDivco(script),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
    )
    return engine.run()


def _divco_dividends(result: object) -> list[dict[str, object]]:
    rows = result.ledger_rows  # type: ignore[attr-defined]
    return [r for r in rows if r["type"] == "dividend" and r["symbol"] == "DIVCO"]


def test_a_buy_that_fills_on_the_ex_date_is_not_entitled(store: Path) -> None:
    """BUY 100 submitted on bar2 fills on bar3 = the ex-date bar. The buyer was
    not a holder of record before the ex-date, so no dividend is owed to them:
    cash 100000 - 5000 = 95000, position 100 * 50 = 5000, equity 100000."""
    result = _run_scripted(store, {2: [(OrderSide.BUY, "100")]})
    assert _divco_dividends(result) == []
    equity_by_ts = {int(r["ts"]): r["equity"] for r in result.equity_rows}  # type: ignore[attr-defined]
    assert equity_by_ts[5 * DAY] == pytest.approx(100000.0)


def test_a_sell_that_fills_on_the_ex_date_still_receives_the_dividend(store: Path) -> None:
    """BUY 100 (bar1 -> fills bar2 @ 50), SELL 100 (bar2 -> fills bar3 = ex-date).
    Held 100 before the ex-date, so the dividend is 100 * 2.00 = +200 on the
    pay-date: cash 100000 - 5000 + 5000 + 200 = 100200, flat."""
    result = _run_scripted(store, {1: [(OrderSide.BUY, "100")], 2: [(OrderSide.SELL, "100")]})
    dividends = _divco_dividends(result)
    assert [Decimal(str(r["amount"])) for r in dividends] == [Decimal("200")]
    assert result.final_snapshot.cash(USD) == Decimal("100200")  # type: ignore[attr-defined]


def test_a_short_covered_on_the_ex_date_still_pays_the_dividend(store: Path) -> None:
    """SELL 50 short (bar1 -> fills bar2 @ 50, +2500), BUY 50 cover (bar2 -> fills
    bar3 = ex-date, -2500). Short 50 before the ex-date owes 50 * 2.00 = 100 on
    the pay-date: cash 100000 + 2500 - 2500 - 100 = 99900, flat."""
    result = _run_scripted(store, {1: [(OrderSide.SELL, "50")], 2: [(OrderSide.BUY, "50")]})
    dividends = _divco_dividends(result)
    assert [Decimal(str(r["amount"])) for r in dividends] == [Decimal("-100")]
    assert result.final_snapshot.cash(USD) == Decimal("99900")  # type: ignore[attr-defined]
