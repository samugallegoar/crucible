"""An imported contract settles through the engine's delisting mechanism (ADR-0052).

Hand computation. Level 1, zero costs, initial cash 10000. UP bars (bar_seconds=2) at
mid 0.40 close at 1102, 1104 and 1106; the strategy submits a buy of 100 UP on the first
bar, it fills on the next bar at its open 0.40 (cash 10000 - 40 = 9960), and the contract
settles at 1.0 (winner Up): the delisting liquidates at the settlement bar's mark,
+100 -> cash 10060, no position left.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from crucible.core.engine import BacktestEngine
from crucible.core.events import BarEvent
from crucible.core.types import Currency, DatasetId, OrderSide, RealismLevel, Symbol, TimestampNs
from crucible.data.importers.build import build_from_spec
from crucible.data.store import ParquetDataStore
from crucible.execution.ladder import ExecutionSetup
from crucible.execution.models import (
    MarketStats,
    NoCommission,
    NoSlippage,
    QuotedSpread,
    ZeroLatency,
)
from crucible.strategy.context import BacktestContext

NS = 10**9
USD = Currency("USD")
HEADER = (
    "slug,start_time,elapsed,ask_YES,bid_YES,ask_NO,bid_NO,btc_strike,btc_current,btc_gap,"
    "timestamp_log,resolved,winner"
)


class BuyUpOnce:
    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["done"] = False

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:  # type: ignore[override]
        if ctx.state["done"] or not str(event.symbol).endswith("-UP"):
            return
        ctx.state["done"] = True
        ctx.orders.submit(event.symbol, OrderSide.BUY, Decimal("100"))

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_order_update(self, ctx: object, event: object) -> None: ...

    def on_fill(self, ctx: object, event: object) -> None: ...

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: object) -> None: ...


def test_holding_a_contract_through_settlement_pays_the_outcome(tmp_path: Path) -> None:
    rows = [
        f"btc-updown-5m-1000,1000,{ts - 1000},0.42,0.38,0.62,0.58,100.0,100.0,0.0,{ts},True,Up"
        for ts in (1100, 1102, 1104)
    ]
    (tmp_path / "pm.csv").write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        f"kind: polymarket_csv\ndataset: pm\ninput: '{tmp_path / 'pm.csv'}'\nbar_seconds: 2\n",
        encoding="utf-8",
    )
    store = tmp_path / "store"
    build_from_spec(spec, store)

    result = BacktestEngine(
        store=ParquetDataStore(store),
        bars_dataset=DatasetId("pm"),
        corporate_actions_dataset=DatasetId("pm_actions"),
        strategy=BuyUpOnce(),
        params={},
        initial_cash=Decimal("10000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(2000 * NS),
    ).run()
    prices = {row["symbol"]: row["price"] for row in result.fill_rows}
    assert prices == {"BTC5M-1000-UP": 0.4}
    assert result.final_snapshot.cash(USD) == Decimal("10060")
    assert result.final_snapshot.position(Symbol("BTC5M-1000-UP")) is None


def test_a_quoted_level_two_run_pays_half_the_spread_and_settlement_pays_none(
    tmp_path: Path,
) -> None:
    """Level 2, ``QuotedSpread``. UP quotes 0.39/0.41 (mid 0.40, half-spread 0.01): the buy
    fills at the next bar's open 0.40 + 0.01 = 0.41, cash 10000 - 41 = 9959; the settlement bar
    has bid = ask = 1.0 so the delisting pays 100 exactly: 9959 + 100 = 10059."""
    rows = [
        f"btc-updown-5m-1000,1000,{ts - 1000},0.41,0.39,0.61,0.59,100.0,100.0,0.0,{ts},True,Up"
        for ts in (1100, 1102, 1104)
    ]
    (tmp_path / "pm.csv").write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        f"kind: polymarket_csv\ndataset: pm\ninput: '{tmp_path / 'pm.csv'}'\nbar_seconds: 2\n",
        encoding="utf-8",
    )
    store = tmp_path / "store"
    build_from_spec(spec, store)

    result = BacktestEngine(
        store=ParquetDataStore(store),
        bars_dataset=DatasetId("pm"),
        corporate_actions_dataset=DatasetId("pm_actions"),
        strategy=BuyUpOnce(),
        params={},
        initial_cash=Decimal("10000"),
        base_currency=USD,
        realism_level=RealismLevel.SPREAD_LATENCY,
        execution=ExecutionSetup(
            spread=QuotedSpread(),
            latency=ZeroLatency(),
            slippage=NoSlippage(),
            commission=NoCommission(),
            participation=None,
            stats=MarketStats(),
        ),
        start=TimestampNs(0),
        end=TimestampNs(2000 * NS),
    ).run()
    prices = {row["symbol"]: row["price"] for row in result.fill_rows}
    assert prices["BTC5M-1000-UP"] == 0.41
    assert result.final_snapshot.cash(USD) == Decimal("10059")
