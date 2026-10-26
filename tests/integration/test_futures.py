"""Futures MTM settlement and rolls through the real engine (ADR-0033). Hand-computed
ledgers per AGENTS.md §7.

Sign/scale convention verified throughout: dollar PnL for a futures move
is ``price_points * qty * multiplier``. Daily settlement telescopes to
the same total as one lump-sum settlement at exit (that's the point of
mark-to-market) -- every test below checks this by comparing the
step-by-step cash path against the direct entry-to-exit calculation.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.analytics.attribution import UNATTRIBUTED, per_strategy_pnl_deltas
from crucible.core.engine import BacktestEngine
from crucible.core.events import BarEvent
from crucible.core.instruments import FuturesSpec
from crucible.core.types import Currency, DatasetId, OrderSide, RealismLevel, Symbol, TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.risk.engine import CompositeRiskEngine
from crucible.risk.limits import MarginCallLimit, MarginRequirementLimit
from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
BARS = DatasetId("futures_bars")
ES = Symbol("ES")
ES_DEC = Symbol("ES_DEC")
ES_MAR = Symbol("ES_MAR")
USD = Currency("USD")
MULT = Decimal("50")


class _SessionCounter:
    """Fires ``_on_session`` once per distinct timestamp (bars for
    different symbols share a timestamp)."""

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


class OpenOnSessionOne(_SessionCounter):
    def _on_session(self, ctx: BacktestContext, session: int) -> None:
        if session == 1:
            ctx.orders.submit(ES, OrderSide.BUY, Decimal("2"))


class OpenThenCloseOnSessionThree(_SessionCounter):
    def _on_session(self, ctx: BacktestContext, session: int) -> None:
        if session == 1:
            ctx.orders.submit(ES, OrderSide.BUY, Decimal("2"))
        elif session == 3:
            ctx.orders.submit(ES, OrderSide.SELL, Decimal("2"))


class RollFromDecToMar(_SessionCounter):
    """Session 1: open 2 ES_DEC. Session 3: the roll -- close ES_DEC,
    open the same size in ES_MAR, submitted together (a roll needs no
    dedicated API: it's just two ordinary orders across two
    futures-registered symbols, ADR-0033)."""

    def _on_session(self, ctx: BacktestContext, session: int) -> None:
        if session == 1:
            ctx.orders.submit(ES_DEC, OrderSide.BUY, Decimal("2"))
        elif session == 3:
            ctx.orders.submit(ES_DEC, OrderSide.SELL, Decimal("2"))
            ctx.orders.submit(ES_MAR, OrderSide.BUY, Decimal("2"))


def _bar_rows(symbol: str, opens: list[float]) -> dict[str, list[object]]:
    n = len(opens)
    return {
        "symbol": [symbol] * n,
        "event_time": [(d + 1) * DAY for d in range(n)],
        "available_at": [(d + 1) * DAY for d in range(n)],
        "open": opens,
        "high": [o + 1 for o in opens],
        "low": [o - 1 for o in opens],
        "close": opens,
        "volume": [1e6] * n,
    }


def _build_single(root: Path, opens: list[float]) -> None:
    build_dataset(
        root,
        BARS,
        pl.DataFrame(_bar_rows("ES", opens)),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )


def test_daily_mtm_settlement_telescopes_to_the_total_move(tmp_path: Path) -> None:
    """Long 2 ES @ 4500 (fills day2). Marks: day2=4500 (entry, MTM 0),
    day3=4510 (+10 pts -> +$1000), day4=4505 (-5 pts from day3 ->
    -$500). Net move entry(4500)->final mark(4505) = +5 pts * 2 * $50 =
    +$500, matching the two incremental settlements (1000 - 500 = 500).
    """
    _build_single(tmp_path, opens=[4500.0, 4500.0, 4510.0, 4505.0, 4505.0])
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=OpenOnSessionOne(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
        futures_specs={ES: FuturesSpec(multiplier=MULT)},
    )
    result = engine.run()

    snapshot = result.final_snapshot
    assert snapshot.cash(USD) == Decimal("100500")
    assert snapshot.equity(USD) == Decimal("100500")
    assert snapshot.realized_pnl == Decimal("500")
    position = snapshot.position(ES)
    assert position is not None
    assert position.qty == Decimal("2")
    assert position.avg_cost == Decimal("4505")  # rebased to the last mark

    settlements = [r for r in result.ledger_rows if r["type"] == "settlement"]
    # one close+reopen pair per non-zero-delta mark: day3 and day4 (day2's
    # mark == entry price, a no-op, correctly produces no transactions)
    assert len(settlements) == 4


def test_a_fill_that_closes_a_futures_position_realizes_pnl_immediately(tmp_path: Path) -> None:
    """Long 2 ES @ 4500 (fills day2, no move). Day3 mark moves to 4510
    (+10 pts -> +$1000 MTM, avg_cost rebases to 4510). Day3 also submits
    a closing SELL, which fills day4 @ 4520 (+10 more points on the
    remaining unsettled basis -> +$1000 from the closing fill itself).
    Total: entry 4500 -> exit 4520 = +20 pts * 2 * $50 = +$2000,
    matching 1000 (MTM) + 1000 (closing fill).
    """
    _build_single(tmp_path, opens=[4500.0, 4500.0, 4510.0, 4520.0, 4520.0])
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=OpenThenCloseOnSessionThree(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
        futures_specs={ES: FuturesSpec(multiplier=MULT)},
    )
    result = engine.run()

    snapshot = result.final_snapshot
    assert snapshot.position(ES) is None  # flat
    assert snapshot.cash(USD) == Decimal("102000")
    assert snapshot.equity(USD) == Decimal("102000")
    assert snapshot.realized_pnl == Decimal("2000")


def test_a_roll_closes_the_near_contract_and_opens_the_far_one(tmp_path: Path) -> None:
    """Long 2 ES_DEC @ 4500 (fills day2, price constant). Day3: the
    roll -- SELL 2 ES_DEC (closes, fills day4 @ 4505: +5 pts * 2 * $50
    = +$500) and BUY 2 ES_MAR (opens fresh, fills day4 @ 4600: $0 cash,
    a new position with no relation to ES_DEC's basis). No dedicated
    roll API: two ordinary orders across two futures-registered symbols.
    """
    n = 5
    rows_dec = _bar_rows("ES_DEC", [4500.0, 4500.0, 4500.0, 4505.0, 4505.0])
    rows_mar = _bar_rows("ES_MAR", [4600.0] * n)
    merged = {key: rows_dec[key] + rows_mar[key] for key in rows_dec}
    build_dataset(
        tmp_path,
        BARS,
        pl.DataFrame(merged),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=RollFromDecToMar(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
        futures_specs={
            ES_DEC: FuturesSpec(multiplier=MULT),
            ES_MAR: FuturesSpec(multiplier=MULT),
        },
    )
    result = engine.run()

    snapshot = result.final_snapshot
    assert snapshot.position(ES_DEC) is None  # rolled out
    mar_position = snapshot.position(ES_MAR)
    assert mar_position is not None
    assert mar_position.qty == Decimal("2")
    assert mar_position.avg_cost == Decimal("4600")

    assert snapshot.cash(USD) == Decimal("100500")
    assert snapshot.equity(USD) == Decimal("100500")
    assert snapshot.realized_pnl == Decimal("500")


def test_attribution_of_a_futures_round_trip_matches_the_ledger_realized_pnl(
    tmp_path: Path,
) -> None:
    """Same run as the neighboring closing-fill test: long 2 ES fills day2 @ 4500,
    closing SELL fills day4 @ 4520. Fill values: -2 * 4500 * 50 = -450000 and
    +2 * 4520 * 50 = +452000; net +2000, equal to the ledger's realized PnL."""
    _build_single(tmp_path, opens=[4500.0, 4500.0, 4510.0, 4520.0, 4520.0])
    result = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=OpenThenCloseOnSessionThree(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
        futures_specs={ES: FuturesSpec(multiplier=MULT)},
    ).run()
    assert [row["multiplier"] for row in result.fill_rows] == ["50", "50"]
    frame = per_strategy_pnl_deltas(result.fill_rows, [2 * DAY, 4 * DAY, 6 * DAY])
    assert frame[UNATTRIBUTED].to_list() == pytest.approx([-450000.0, 452000.0, 0.0])
    assert sum(frame[UNATTRIBUTED].to_list()) == pytest.approx(
        float(result.final_snapshot.realized_pnl)
    )


_MARGINS = FuturesSpec(
    multiplier=MULT, initial_margin=Decimal("5000"), maintenance_margin=Decimal("4000")
)


class BuyTwoOrders(_SessionCounter):
    """On session 1: BUY 30 ES (needs 150000 initial margin) then BUY 10 ES (50000)."""

    def _on_session(self, ctx: BacktestContext, session: int) -> None:
        if session == 1:
            ctx.orders.submit(ES, OrderSide.BUY, Decimal("30"))
            ctx.orders.submit(ES, OrderSide.BUY, Decimal("10"))


class BuyTwentyOnce(_SessionCounter):
    def _on_session(self, ctx: BacktestContext, session: int) -> None:
        if session == 1:
            ctx.orders.submit(ES, OrderSide.BUY, Decimal("20"))


def _margin_engine(tmp_path: Path, strategy: object, opens: list[float]) -> BacktestEngine:
    _build_single(tmp_path, opens=opens)
    return BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        strategy=strategy,
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(6 * DAY),
        futures_specs={ES: _MARGINS},
        risk_engine=CompositeRiskEngine(
            USD, pre_trade_limits=[MarginRequirementLimit()], mark_limits=[MarginCallLimit()]
        ),
    )


def test_initial_margin_rejects_the_order_it_cannot_fund(tmp_path: Path) -> None:
    """Equity 100000. BUY 30 needs 150000 -> rejected; BUY 10 needs 50000 -> fills."""
    result = _margin_engine(tmp_path, BuyTwoOrders(), [4500.0] * 5).run()
    states = [row["state"] for row in result.order_rows]
    assert states == ["rejected", "filled"]
    position = result.final_snapshot.position(ES)
    assert position is not None
    assert position.qty == Decimal("10")


def test_a_margin_call_flattens_a_futures_book_when_equity_falls_below_maintenance(
    tmp_path: Path,
) -> None:
    """BUY 20 (initial 100000 == equity: allowed) fills day2 @ 4500. Day3 opens at 4000:
    settling -500 points * 20 * 50 = -500000 leaves equity -400000, below the
    maintenance requirement 20 * 4000 = 80000 -> FLATTEN; the closing order fills day4."""
    result = _margin_engine(
        tmp_path, BuyTwentyOnce(), [4500.0, 4500.0, 4000.0, 4000.0, 4000.0]
    ).run()
    assert result.final_snapshot.position(ES) is None
    assert len(result.fill_rows) == 2  # the entry and the flatten


def test_delisting_a_futures_position_settles_the_price_delta_not_the_notional(
    tmp_path: Path,
) -> None:
    """Regression (2026-10 audit): the delisting path booked ``qty * mark`` as cash, i.e. the
    whole notional (+9040 for 2 ES at 4520) instead of the price delta since the last daily
    settlement. Long 2 ES @4500, marks 4500 / 4510 / 4520, delisting after day 4:

        day 3 settlement  (4510-4500)*2*50 = +1000
        day 4 delisting   (4520-4510)*2*50 = +1000
        equity            100000 + 2000 = 102000

    not 110040. Nothing is refused for a futures symbol today, and a delisting row is the only
    way to settle an expiring contract (there is no expiry field yet).
    """
    from crucible.data.contracts import CORPORATE_ACTION_SCHEMA, CORPORATE_ACTION_SORT_KEYS

    _build_single(tmp_path, opens=[4500.0, 4500.0, 4510.0, 4520.0])
    corp = DatasetId("futures_actions")
    build_dataset(
        tmp_path,
        corp,
        pl.DataFrame(
            {
                "symbol": ["ES"],
                "action": ["delisting"],
                "effective_at": [4 * DAY],
                "event_time": [4 * DAY],
                "available_at": [4 * DAY],
                "value": [None],
                "pay_at": [None],
            },
            schema=CORPORATE_ACTION_SCHEMA,
        ),
        schema=CORPORATE_ACTION_SCHEMA,
        sort_keys=CORPORATE_ACTION_SORT_KEYS,
        source="test",
    )
    engine = BacktestEngine(
        store=ParquetDataStore(tmp_path),
        bars_dataset=BARS,
        corporate_actions_dataset=corp,
        strategy=OpenOnSessionOne(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        start=TimestampNs(DAY),
        end=TimestampNs(4 * DAY),
        futures_specs={ES: FuturesSpec(multiplier=MULT)},
    )
    result = engine.run()
    final = result.final_snapshot
    assert final.equity(USD) == Decimal("102000")
    assert final.position(ES) is None or final.position(ES).qty == 0
