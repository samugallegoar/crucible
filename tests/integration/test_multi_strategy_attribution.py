"""Multiple strategies sharing one portfolio, with per-strategy attribution,
correlation, and marginal risk contribution -- the attribution
demonstration (ADR-0030). Hand-computed per AGENTS.md §7.

Two strategies, disjoint symbols, constant prices (isolates the
attribution mechanism from price-move noise):
  Alpha trades AAA (100/share, qty 10): BUY session 1 (fills day2),
    SELL session 3 (fills day4).
  Beta trades BBB (50/share, qty 5): same session pattern.

Per-period (ts grid = every mark) PnL deltas:
  day1: Alpha=0,    Beta=0     (orders submitted, not yet filled)
  day2: Alpha=-1000, Beta=-250  (BUY fills: -10*100, -5*50)
  day3: Alpha=0,    Beta=0     (SELL submitted, not yet filled)
  day4: Alpha=+1000, Beta=+250  (SELL fills: +10*100, +5*50)
  day5: Alpha=0,    Beta=0

Alpha_i = 4 * Beta_i at every period exactly -> correlation = 1.0.
portfolio_i = Alpha_i + Beta_i = [0, -1250, 0, 1250, 0], mean 0,
  var(ddof=1) = (1250^2 * 2) / 4 = 781250, sd = sqrt(781250).
cov(Alpha, portfolio) = (1000*1250 + 1000*1250) / 4 = 625000
  -> MRC_Alpha = 625000 / sqrt(781250)
cov(Beta, portfolio) = (250*1250 + 250*1250) / 4 = 156250
  -> MRC_Beta = 156250 / sqrt(781250)
MRC_Alpha + MRC_Beta == sqrt(781250) (covariance-decomposition identity).
"""

from __future__ import annotations

import math
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.analytics.attribution import (
    marginal_risk_contribution,
    per_strategy_pnl_deltas,
    strategy_correlation,
)
from crucible.core.engine import BacktestEngine
from crucible.core.events import BarEvent
from crucible.core.types import (
    Currency,
    DatasetId,
    OrderSide,
    RealismLevel,
    StrategyId,
    Symbol,
    TimestampNs,
)
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.strategy.context import BacktestContext
from crucible.strategy.multi import MultiStrategy

DAY = 86_400 * 10**9
BARS = DatasetId("multi_strategy_bars")
AAA = Symbol("AAA")
BBB = Symbol("BBB")
USD = Currency("USD")
ALPHA = StrategyId("alpha")
BETA = StrategyId("beta")


class OneSymbolTrader:
    """Buys ``qty`` on session 1, sells it on session 3; ignores bars for
    any symbol other than its own -- session counting is per-symbol so a
    shared multi-symbol run doesn't need cross-symbol dedup."""

    def __init__(self, symbol: Symbol, qty: str) -> None:
        self._symbol = symbol
        self._qty = Decimal(qty)

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["sessions"] = 0

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        if event.symbol != self._symbol:
            return
        sessions = ctx.state["sessions"]
        assert isinstance(sessions, int)
        sessions += 1
        ctx.state["sessions"] = sessions
        if sessions == 1:
            ctx.orders.submit(self._symbol, OrderSide.BUY, self._qty)
        elif sessions == 3:
            ctx.orders.submit(self._symbol, OrderSide.SELL, self._qty)

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


def _build(root: Path) -> None:
    n = 5
    build_dataset(
        root,
        BARS,
        pl.DataFrame(
            {
                "symbol": ["AAA"] * n + ["BBB"] * n,
                "event_time": [(d + 1) * DAY for d in range(n)] * 2,
                "available_at": [(d + 1) * DAY for d in range(n)] * 2,
                "open": [100.0] * n + [50.0] * n,
                "high": [101.0] * n + [50.5] * n,
                "low": [99.0] * n + [49.5] * n,
                "close": [100.0] * n + [50.0] * n,
                "volume": [1e6] * (2 * n),
            }
        ),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )


def test_multi_strategy_attribution_correlation_and_marginal_risk(tmp_path: Path) -> None:
    _build(tmp_path)
    multi = MultiStrategy({ALPHA: OneSymbolTrader(AAA, "10"), BETA: OneSymbolTrader(BBB, "5")})
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=multi,
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
    )
    result = engine.run()

    # every fill is attributed to exactly the strategy that traded its symbol
    fills_by_symbol = {str(r["symbol"]): str(r["strategy_id"]) for r in result.fill_rows}
    assert fills_by_symbol == {"AAA": "alpha", "BBB": "beta"}
    assert len(result.fill_rows) == 4  # 2 fills per strategy

    period_ts = [int(row["ts"]) for row in result.equity_rows]
    assert period_ts == [DAY * d for d in range(1, 6)]

    deltas = per_strategy_pnl_deltas(result.fill_rows, period_ts)
    assert deltas.get_column("alpha").to_list() == [
        pytest.approx(v) for v in (0.0, -1000.0, 0.0, 1000.0, 0.0)
    ]
    assert deltas.get_column("beta").to_list() == [
        pytest.approx(v) for v in (0.0, -250.0, 0.0, 250.0, 0.0)
    ]

    corr = strategy_correlation(deltas)
    ab = corr.filter((corr["strategy_id"] == "alpha") & (corr["other_id"] == "beta")).row(
        0, named=True
    )
    assert ab["correlation"] == pytest.approx(1.0)

    mrc = marginal_risk_contribution(deltas)
    portfolio_sd = math.sqrt(781250)
    assert mrc["alpha"] == pytest.approx(625000 / portfolio_sd)
    assert mrc["beta"] == pytest.approx(156250 / portfolio_sd)
    assert sum(mrc.values()) == pytest.approx(portfolio_sd)

    # both strategies' round trips net to zero PnL at constant prices --
    # the shared portfolio's final equity is exactly the initial cash
    assert result.final_snapshot.equity(USD) == Decimal("100000")
