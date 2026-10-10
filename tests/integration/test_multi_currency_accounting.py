"""Multi-currency accounting through the real engine (ADR-0009).

Hand computation (base USD, symbol EURSTOCK trades in EUR):
  initial cash: 100000 USD
  bar1 (session 1): strategy submits BUY 100 USDSTOCK, BUY 200 EURSTOCK
  bar2: orders fill at bar2's close (Level 1, next-bar, zero cost):
    USD cash: 100000 - 100*100          = 90000
    EUR cash: 0      - 200*50           = -10000
    equity(bar2 marks 100/50, fx mid 1.10):
      90000 + (-10000*1.10) + 100*100 + (200*50*1.10)
      = 90000 - 11000 + 10000 + 11000 = 100000  (no price move yet, so
        equity is unchanged from initial cash -- a sanity check on its own)
  bar3: no new orders; marks move to 110/60, fx mid to 1.20:
    equity = 90000 + (-10000*1.20) + 100*110 + (200*60*1.20)
           = 90000 - 12000 + 11000 + 14400 = 103400

The engine's own I1 check (``check_mark``) runs at every mark and raises
``InvariantViolation`` on any mismatch -- a run that completes without
raising has already proven the invariant held at every step; the equity
assertions below additionally pin the exact numbers per AGENTS.md §7
(hand-computed, never engine-derived).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.analytics.attribution import UNATTRIBUTED, per_strategy_pnl_deltas
from crucible.core.engine import BacktestEngine, BacktestResult
from crucible.core.events import BarEvent
from crucible.core.types import (
    Currency,
    DatasetId,
    OrderSide,
    RealismLevel,
    Symbol,
    TimestampNs,
)
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS, FX_RATE_SCHEMA, FX_RATE_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.risk.engine import CompositeRiskEngine
from crucible.risk.limits import MaxOrderNotionalLimit
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
BARS = DatasetId("mc_bars")
FX = DatasetId("mc_fx")
USDSTOCK = Symbol("USDSTOCK")
EURSTOCK = Symbol("EURSTOCK")
USD = Currency("USD")
EUR = Currency("EUR")


def _build(root: Path) -> None:
    bars = pl.DataFrame(
        {
            "symbol": ["USDSTOCK", "USDSTOCK", "USDSTOCK", "EURSTOCK", "EURSTOCK", "EURSTOCK"],
            "event_time": [1 * DAY, 2 * DAY, 3 * DAY, 1 * DAY, 2 * DAY, 3 * DAY],
            "available_at": [1 * DAY, 2 * DAY, 3 * DAY, 1 * DAY, 2 * DAY, 3 * DAY],
            "open": [100.0, 100.0, 110.0, 50.0, 50.0, 60.0],
            "high": [101.0, 101.0, 111.0, 50.5, 50.5, 60.5],
            "low": [99.0, 99.0, 109.0, 49.5, 49.5, 59.5],
            "close": [100.0, 100.0, 110.0, 50.0, 50.0, 60.0],
            "volume": [1e6] * 6,
        }
    )
    build_dataset(root, BARS, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")

    fx = pl.DataFrame(
        {
            "symbol": ["EURUSD", "EURUSD", "EURUSD"],
            "event_time": [1 * DAY, 2 * DAY, 3 * DAY],
            "available_at": [1 * DAY, 2 * DAY, 3 * DAY],
            "mid": [1.10, 1.10, 1.20],
            "bid": [1.09, 1.09, 1.19],
            "ask": [1.11, 1.11, 1.21],
        }
    )
    build_dataset(root, FX, fx, schema=FX_RATE_SCHEMA, sort_keys=FX_RATE_SORT_KEYS, source="test")


class BuyBothOnce:
    """Buys 100 USDSTOCK + 200 EURSTOCK on the first bar it sees, then
    holds -- no further logic needed to exercise multi-currency marking."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["bought"] = False

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        if ctx.state["bought"]:
            return
        ctx.state["bought"] = True
        ctx.orders.submit(USDSTOCK, OrderSide.BUY, Decimal("100"))
        ctx.orders.submit(EURSTOCK, OrderSide.BUY, Decimal("200"))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("mc_data")
    _build(root)
    return root


def test_multi_currency_run_completes_without_an_invariant_violation(store: Path) -> None:
    """If I1 (or any mark-time invariant) had failed, `check_mark` would
    have raised `InvariantViolation` and this run would never finish."""
    engine = BacktestEngine(
        store=ParquetDataStore(store),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=BuyBothOnce(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(4 * DAY),
        symbol_currency={EURSTOCK: EUR},
        fx_dataset=FX,
    )
    result = engine.run()
    assert result.final_snapshot.equity(USD) == Decimal("103400.00")


def test_multi_currency_equity_matches_hand_computed_reference_at_each_mark(
    store: Path,
) -> None:
    engine = BacktestEngine(
        store=ParquetDataStore(store),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=BuyBothOnce(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(4 * DAY),
        symbol_currency={EURSTOCK: EUR},
        fx_dataset=FX,
    )
    result = engine.run()
    equity_by_ts = {int(row["ts"]): row["equity"] for row in result.equity_rows}
    assert equity_by_ts[2 * DAY] == pytest.approx(100000.0)  # fills happened, no price move yet
    assert equity_by_ts[3 * DAY] == pytest.approx(103400.0)


def test_holding_a_foreign_symbol_with_no_currency_mapped_and_no_fx_dataset_refuses(
    store: Path,
) -> None:
    """Refuses at construction, not mid-run (fail fast) -- no engine
    should discover a missing FX rate only after simulating for a while."""
    from crucible.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="fx_dataset"):
        BacktestEngine(
            store=ParquetDataStore(store),
            bars_dataset=BARS,
            corporate_actions_dataset=None,
            strategy=BuyBothOnce(),
            params={},
            initial_cash=Decimal("100000"),
            base_currency=USD,
            realism_level=RealismLevel.BASIC_FRICTION,
            slippage_bps=0.0,
            commission_bps=0.0,
            start=TimestampNs(0),
            end=TimestampNs(4 * DAY),
            symbol_currency={EURSTOCK: EUR},
            fx_dataset=None,
        )


class RoundTripEurstock:
    """BUY 10 EURSTOCK on session 1, SELL 10 (closing) on session 3 --
    a clean round trip to exercise ``realized_pnl``'s FX conversion."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["sessions"] = 0

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        sessions = ctx.state["sessions"]
        assert isinstance(sessions, int)
        sessions += 1
        ctx.state["sessions"] = sessions
        if sessions == 1:
            ctx.orders.submit(EURSTOCK, OrderSide.BUY, Decimal("10"))
        elif sessions == 3:
            ctx.orders.submit(EURSTOCK, OrderSide.SELL, Decimal("10"))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


def test_realized_pnl_converts_a_foreign_currency_gain_to_base(tmp_path: Path) -> None:
    """Regression test (found by code review): a
    multi-currency round trip's realized PnL must convert to base
    currency at the mid rate, exactly like ``equity()`` already does --
    ``PortfolioSnapshot.realized_pnl`` previously summed raw per-symbol
    amounts with no FX conversion at all.

    BUY 10 EURSTOCK @ 50 (fills day2), SELL 10 @ 60 (fills day4): a
    round trip realizing (60-50)*10 = 100 EUR. FX mid held constant at
    1.10 throughout, so base-currency realized PnL must be exactly
    100 * 1.10 = 110 USD, not 100 (which is what summing raw EUR would
    give if treated as if it were already USD).
    """
    n = 5
    bars = pl.DataFrame(
        {
            "symbol": ["EURSTOCK"] * n,
            "event_time": [(d + 1) * DAY for d in range(n)],
            "available_at": [(d + 1) * DAY for d in range(n)],
            "open": [50.0, 50.0, 50.0, 60.0, 60.0],
            "high": [50.5, 50.5, 50.5, 60.5, 60.5],
            "low": [49.5, 49.5, 49.5, 59.5, 59.5],
            "close": [50.0, 50.0, 50.0, 60.0, 60.0],
            "volume": [1e6] * n,
        }
    )
    build_dataset(tmp_path, BARS, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")
    fx = pl.DataFrame(
        {
            "symbol": ["EURUSD"] * n,
            "event_time": [(d + 1) * DAY for d in range(n)],
            "available_at": [(d + 1) * DAY for d in range(n)],
            "mid": [1.10] * n,
            "bid": [1.09] * n,
            "ask": [1.11] * n,
        }
    )
    build_dataset(
        tmp_path, FX, fx, schema=FX_RATE_SCHEMA, sort_keys=FX_RATE_SORT_KEYS, source="test"
    )

    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=RoundTripEurstock(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
        symbol_currency={EURSTOCK: EUR},
        fx_dataset=FX,
    )
    result = engine.run()

    assert result.final_snapshot.realized_pnl == Decimal("110.0")
    assert result.final_snapshot.equity(USD) == Decimal("100110.0")


class BuyEurstockOnce:
    """BUY 100 EURSTOCK on the first bar: the run's first order in EUR."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["done"] = False

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        if ctx.state["done"] or event.symbol != EURSTOCK:
            return
        ctx.state["done"] = True
        ctx.orders.submit(EURSTOCK, OrderSide.BUY, Decimal("100"))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


def test_the_first_foreign_order_is_risk_checked_in_base_currency(store: Path) -> None:
    """Bar1 EURSTOCK mark 50 EUR, FX mid 1.10: one share is 55 USD. BUY 100 =
    5500 USD > a 1000 USD cap, so it is RESIZEd to floor(1000 / 55) = 18 and the
    resized order fills 18 on bar2. No EUR cash or position exists yet, so the
    pre-trade snapshot must fetch the EUR rate itself."""
    engine = BacktestEngine(
        store=ParquetDataStore(store),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=BuyEurstockOnce(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(4 * DAY),
        symbol_currency={EURSTOCK: EUR},
        fx_dataset=FX,
        risk_engine=CompositeRiskEngine(
            USD, pre_trade_limits=[MaxOrderNotionalLimit(Decimal("1000"))]
        ),
    )
    result = engine.run()
    assert [row["qty"] for row in result.fill_rows] == ["18"]


def _eur_round_trip_store(root: Path) -> None:
    n = 5
    bars = pl.DataFrame(
        {
            "symbol": ["EURSTOCK"] * n,
            "event_time": [(d + 1) * DAY for d in range(n)],
            "available_at": [(d + 1) * DAY for d in range(n)],
            "open": [50.0, 50.0, 50.0, 60.0, 60.0],
            "high": [50.5, 50.5, 50.5, 60.5, 60.5],
            "low": [49.5, 49.5, 49.5, 59.5, 59.5],
            "close": [50.0, 50.0, 50.0, 60.0, 60.0],
            "volume": [1e6] * n,
        }
    )
    build_dataset(root, BARS, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")
    fx = pl.DataFrame(
        {
            "symbol": ["EURUSD"] * n,
            "event_time": [(d + 1) * DAY for d in range(n)],
            "available_at": [(d + 1) * DAY for d in range(n)],
            "mid": [1.10] * n,
            "bid": [1.09] * n,
            "ask": [1.11] * n,
        }
    )
    build_dataset(root, FX, fx, schema=FX_RATE_SCHEMA, sort_keys=FX_RATE_SORT_KEYS, source="test")


def _run_eur_round_trip(tmp_path: Path) -> BacktestResult:
    _eur_round_trip_store(tmp_path)
    return BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=RoundTripEurstock(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
        symbol_currency={EURSTOCK: EUR},
        fx_dataset=FX,
    ).run()


def test_fill_rows_carry_currency_multiplier_and_the_fill_time_fx_rate(tmp_path: Path) -> None:
    result = _run_eur_round_trip(tmp_path)
    assert len(result.fill_rows) == 2
    for row in result.fill_rows:
        assert row["currency"] == "EUR"
        assert Decimal(str(row["multiplier"])) == Decimal("1")
        assert Decimal(str(row["fx_to_base"])) == Decimal("1.1")


def test_attribution_values_a_foreign_round_trip_in_base_currency(tmp_path: Path) -> None:
    """BUY 10 @ 50 EUR (fills day2) = -500 EUR = -550 USD at 1.10; SELL 10 @ 60
    (fills day4) = +600 EUR = +660 USD. Net +110 USD, the same 110 USD realized
    PnL asserted by the neighboring test. (Old: -500, +600.)"""
    result = _run_eur_round_trip(tmp_path)
    frame = per_strategy_pnl_deltas(result.fill_rows, [2 * DAY, 4 * DAY, 5 * DAY])
    assert frame[UNATTRIBUTED].to_list() == pytest.approx([-550.0, 660.0, 0.0])
