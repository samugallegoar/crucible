"""Engine feed seam (ADR-0039): the engine merges its feed with its own
scheduled-event queue. Characterization tests (written against the pre-refactor
engine) pin dividend pay-date behavior; seam tests exercise feed_factory."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest

from crucible.core.engine import BacktestEngine
from crucible.core.errors import InvariantViolation
from crucible.core.events import BarEvent, CorporateActionEvent
from crucible.core.types import (
    Currency,
    DatasetId,
    OrderSide,
    RealismLevel,
    Symbol,
    TimestampNs,
)
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CORPORATE_ACTION_SCHEMA,
    CORPORATE_ACTION_SORT_KEYS,
)
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.live.replay import ReplayDataFeed

if TYPE_CHECKING:
    from collections.abc import Iterator

    from crucible.core.interfaces import Event
    from crucible.live.feed import FeedContext
    from crucible.strategy.context import BacktestContext

DAY = 86_400 * 10**9
BARS = DatasetId("seam_bars")
ACTIONS = DatasetId("seam_actions")
DIVCO = Symbol("DIVCO")
SHORTCO = Symbol("SHORTCO")
USD = Currency("USD")


def _build(root: Path, *, pay_day: int) -> None:
    """Five daily bars per symbol; a dividend of 2.00 with ex-date day 3."""
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
    build_dataset(root, BARS, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="t")
    actions = pl.DataFrame(
        {
            "symbol": ["DIVCO", "SHORTCO"],
            "action": ["cash_dividend", "cash_dividend"],
            "effective_at": [3 * DAY, 3 * DAY],
            "event_time": [3 * DAY, 3 * DAY],
            "available_at": [3 * DAY, 3 * DAY],
            "value": [2.0, 2.0],
            "pay_at": [pay_day * DAY, pay_day * DAY],
        },
        schema_overrides={"value": pl.Float64, "pay_at": pl.Int64},
    )
    build_dataset(
        root,
        ACTIONS,
        actions,
        schema=CORPORATE_ACTION_SCHEMA,
        sort_keys=CORPORATE_ACTION_SORT_KEYS,
        source="t",
    )


class BuyDivcoShortShortco:
    """First bar of each symbol: buy 100 DIVCO, short 50 SHORTCO."""

    def __init__(self) -> None:
        self.seen: list[str] = []
        self._done: set[str] = set()

    def on_start(self, ctx: BacktestContext) -> None: ...

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        self.seen.append(str(event.symbol))
        if event.symbol in self._done:
            return
        self._done.add(str(event.symbol))
        if event.symbol == DIVCO:
            ctx.orders.submit(DIVCO, OrderSide.BUY, Decimal("100"))
        elif event.symbol == SHORTCO:
            ctx.orders.submit(SHORTCO, OrderSide.SELL, Decimal("50"))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


def _engine(
    root: Path,
    *,
    end_day: int,
    strategy: BuyDivcoShortShortco | None = None,
    observer: object = None,
    feed_factory: object = None,
) -> BacktestEngine:
    return BacktestEngine(
        store=ParquetDataStore(root),
        bars_dataset=BARS,
        corporate_actions_dataset=ACTIONS,
        strategy=strategy if strategy is not None else BuyDivcoShortShortco(),
        params={},
        initial_cash=Decimal("100000"),
        base_currency=USD,
        realism_level=RealismLevel.BASIC_FRICTION,
        slippage_bps=0.0,
        commission_bps=0.0,
        start=TimestampNs(0),
        end=TimestampNs(end_day * DAY),
        observer=observer,  # type: ignore[arg-type]
        **({"feed_factory": feed_factory} if feed_factory is not None else {}),  # type: ignore[arg-type]
    )


def test_pay_date_after_the_last_bar_is_still_paid(tmp_path: Path) -> None:
    """Characterization: the engine queue outlives the feed. Pay date day 8,
    last bar day 5: both dividends must still post, and a mark must follow."""
    _build(tmp_path, pay_day=8)
    result = _engine(tmp_path, end_day=9).run()
    dividends = {
        row["symbol"]: Decimal(row["amount"])
        for row in result.ledger_rows
        if row["type"] == "dividend"
    }
    assert dividends == {"DIVCO": Decimal("200"), "SHORTCO": Decimal("-100")}
    equity_by_ts = {int(row["ts"]): row["equity"] for row in result.equity_rows}
    assert equity_by_ts[8 * DAY] == pytest.approx(100100.0)


def test_at_a_shared_timestamp_bars_come_before_pay_date_events(tmp_path: Path) -> None:
    """Characterization: pay date == bar timestamp (day 5). Bars first, then
    the engine-scheduled pay-date events (the feed-first merge rule)."""
    _build(tmp_path, pay_day=5)
    seen: list[Event] = []
    _engine(tmp_path, end_day=6, observer=seen.append).run()
    kinds = []
    for event in seen:
        if event.ts != 5 * DAY:
            continue
        if isinstance(event, BarEvent):
            kinds.append("bar")
        else:
            assert isinstance(event, CorporateActionEvent)
            kinds.append("pay" if event.resolved_amount is not None else "ex-date")
    assert kinds == ["bar", "bar", "pay", "pay"]


def test_feed_factory_subscription_narrows_what_the_strategy_sees(tmp_path: Path) -> None:
    _build(tmp_path, pay_day=5)

    def factory(ctx: FeedContext) -> ReplayDataFeed:
        feed = ReplayDataFeed(ctx)
        feed.subscribe(frozenset({DIVCO}))
        return feed

    strategy = BuyDivcoShortShortco()
    _engine(tmp_path, end_day=6, strategy=strategy, feed_factory=factory).run()
    assert set(strategy.seen) == {"DIVCO"}


class _BackwardsFeed:
    """A feed that violates I9: yields day 2 before day 1."""

    stamping = "eager"

    def __init__(self, ctx: FeedContext) -> None:
        self._ctx = ctx

    def subscribe(self, symbols: frozenset[Symbol]) -> None: ...

    def events(self) -> Iterator[Event]:
        def bar(day: int) -> BarEvent:
            return BarEvent(
                id=self._ctx.next_event_id(),
                ts=TimestampNs(day * DAY),
                seq=self._ctx.next_seq(),
                symbol=DIVCO,
                event_time=TimestampNs(day * DAY),
                open_time=TimestampNs(day * DAY),
                open=50.0,
                high=50.5,
                low=49.5,
                close=50.0,
                volume=1e6,
            )

        return iter([bar(2), bar(1)])


def test_out_of_order_feed_is_refused(tmp_path: Path) -> None:
    _build(tmp_path, pay_day=5)
    with pytest.raises(InvariantViolation, match="feed ordering violated"):
        _engine(tmp_path, end_day=6, feed_factory=_BackwardsFeed).run()


def test_balances_reflect_the_ledger_at_the_current_time(tmp_path: Path) -> None:
    _build(tmp_path, pay_day=5)
    engine = _engine(tmp_path, end_day=6)
    engine.run()
    balances = engine.balances()
    assert balances.positions[DIVCO].qty == Decimal("100")
    assert balances.positions[SHORTCO].qty == Decimal("-50")
