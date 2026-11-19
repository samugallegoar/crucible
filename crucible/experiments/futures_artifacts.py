"""The futures-run artifact: per-bar marks, a daily ledger, fills, rolls and descriptive metrics.

A futures run writes six results and a manifest (ADR-0095). The *close* of every bar is an exact
mark: the simulator's own ``equity_usd`` (balance plus the open position valued at that bar's
close, ADR-0090). The intrabar extremes cannot be exact from OHLC bars, so they are an explicit,
recorded approximation (``MARKING_POLICY``), and everything downstream that needs a drawdown reads
the conservative side of it.

The daily ledger is the aggregation a trader reads: one row per Globex trade date with the
session's scheduled bounds, the day's flows and its opening and closing marks.
``check_daily_ledger`` asserts the identities that make it a ledger rather than a summary (the
runner refuses to write a broken one: ``InvariantViolation``, naming the trade date).

``build_metrics`` is deliberately DESCRIPTIVE: totals, counts and a conservative drawdown, each in
the artifact contract's ``{"value", "ci_low", "ci_high"}`` shape with the intervals null. The run
adds the inferential statistics of ADR-0103 (per-period and annualized Sharpe, mean daily return,
PSR, DSR, IC — with their intervals and reasons) in ``futures_run`` from ``futures_stats``, and
records the trial counts, the bootstrap recipe and the realism assumptions in the manifest, so a
Sharpe never travels without what AGENTS.md §9 requires beside it. Nothing here computes one.

Units: prices in the series' points, money in USD as exact ``Decimal(38, 6)`` (``MONEY``), times
UTC int64 nanoseconds, ``trade_date`` a Globex trade date (a day label, never an instant).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from crucible.core.errors import DataQualityError, InvariantViolation

if TYPE_CHECKING:
    from crucible.data.cme_sessions import SessionCalendar
    from crucible.data.futures_specs import FuturesContractSpec

MONEY = pl.Decimal(38, 6)
"""Exact money dtype of every ``*_usd`` column (the simulator's: micro-dollars as Decimal 38, 6).

The schema constants below spell the same dtype (``pl.Decimal(38, 6)``) so the generated column
tables document the exact precision the files carry; this constant is the name the builders use.
"""

MICRO = 1_000_000
"""Micro-dollars per dollar: money is kept in exact micro-dollars."""

MICRO_USD = Decimal("0.000001")

MARKING_POLICY = (
    "close marks are exact: equity_usd is the simulator's close mark (balance plus the open "
    "position valued at the bar's close, after the bar's fills and costs). equity_low_usd and "
    "equity_high_usd approximate the intrabar extremes from OHLC bars. With pv the point value, p "
    "the position at the close, q the position at the previous close and eq_prev the previous "
    "close's equity: cand_close = equity_close + p*(low-close)*pv and equity_close + "
    "p*(high-close)*pv; when the contract did not change from the previous bar, cand_prev = "
    "eq_prev + q*(low-prev_close)*pv and eq_prev + q*(high-prev_close)*pv (the position carried "
    "into the bar, before any fill in it); equity_low = min(equity_close, cand_close_low, "
    "cand_prev_low) and equity_high = max(equity_close, cand_close_high, cand_prev_high). "
    "cand_prev is omitted on the first bar and on a contract change. The bar's costs are already "
    "in equity_close and are ignored in cand_prev. The prices are the execution series' own (the "
    "held contract's); on a bar where a causal roll had not executed yet the series already "
    "carries the incoming contract while the position is still in the outgoing one, which is a "
    "second, smaller approximation. This is an approximation from OHLC bars: the order of the "
    "high and the low inside a bar and the path between are unknown; the low is a conservative "
    "(deeper) estimate when a stop filled inside the bar."
)
"""What the marks mean, recorded verbatim in the run manifest."""

UNHEDGED_MARK_NOTE = (
    "equity_low_usd / equity_high_usd are an OHLC approximation of the intrabar extremes, not "
    "observed marks"
)
"""The one-line form of ``MARKING_POLICY`` used in the manifest's ``approximations`` list."""


FUTURES_MARKS_SCHEMA: dict[str, pl.DataType] = {
    "event_time": pl.Int64(),  # UTC ns; the bar's close, i.e. when the mark is taken
    "trade_date": pl.Date(),  # Globex trade date of the bar (a day label, not an instant)
    "contract": pl.String(),  # the contract held when the bar printed (ESH2024)
    "on_schedule": pl.Boolean(),  # false when the bar is outside every scheduled Globex segment
    "position": pl.Int64(),  # signed contracts held at the bar's close (long > 0 > short)
    "balance_usd": pl.Decimal(38, 6),  # USD; cash balance after this bar's flows (Decimal(38, 6))
    "equity_usd": pl.Decimal(38, 6),  # USD; close mark = balance + unrealized (Decimal(38, 6))
    "equity_low_usd": pl.Decimal(38, 6),  # USD; conservative intrabar low (see MARKING_POLICY)
    "equity_high_usd": pl.Decimal(38, 6),  # USD; intrabar high approximation (see MARKING_POLICY)
    "realized_usd": pl.Decimal(38, 6),  # USD; this bar's realized P&L, a flow not a total
    "costs_usd": pl.Decimal(38, 6),  # USD; this bar's fees + spread + slippage, a flow not a total
    "unrealized_usd": pl.Decimal(38, 6),  # USD; the open position valued at this bar's close
}

FUTURES_DAILY_SCHEMA: dict[str, pl.DataType] = {
    "trade_date": pl.Date(),  # Globex trade date the row covers (a day label)
    "session_open_ns": pl.Int64(),  # UTC ns; the calendar's SCHEDULED open of that trade date
    "session_close_ns": pl.Int64(),  # UTC ns; the calendar's SCHEDULED close of that trade date
    "verified": pl.Boolean(),  # false when an unsourced window touches the session's schedule
    "bars": pl.Int64(),  # bars observed on the trade date
    "first_bar_ns": pl.Int64(),  # UTC ns; close of the day's first bar
    "last_bar_ns": pl.Int64(),  # UTC ns; close of the day's last bar
    "opening_balance_usd": pl.Decimal(38, 6),  # USD; previous close's balance (capital day 1)
    "closing_balance_usd": pl.Decimal(38, 6),  # USD; balance after the day's last bar
    "opening_equity_usd": pl.Decimal(38, 6),  # USD; previous close's equity (capital day 1)
    "closing_equity_usd": pl.Decimal(38, 6),  # USD; close mark of the day's last bar
    "realized_usd": pl.Decimal(38, 6),  # USD; sum of the day's realized flows
    "fees_usd": pl.Decimal(38, 6),  # USD; sum of the day's commission and fee flows
    "spread_usd": pl.Decimal(38, 6),  # USD; sum of the day's half-spread flows
    "slippage_usd": pl.Decimal(38, 6),  # USD; sum of the day's slippage flows
    "costs_usd": pl.Decimal(38, 6),  # USD; fees + spread + slippage over the day
    "unrealized_close_usd": pl.Decimal(38, 6),  # USD; open position valued at the day's last close
    "min_equity_usd": pl.Decimal(38, 6),  # USD; lowest equity_low_usd of the day's bars
    "max_equity_usd": pl.Decimal(38, 6),  # USD; highest equity_high_usd of the day's bars
    "max_contracts": pl.Int64(),  # largest |position| over the day's bars, in contracts
    "fills": pl.Int64(),  # fills that happened on the trade date
}

FUTURES_FILLS_SCHEMA: dict[str, pl.DataType] = {
    "event_time": pl.Int64(),  # UTC ns; close of the bar the fill belongs to
    "fill_time": pl.Int64(),  # UTC ns; when the fill happened (the bar's open on a next-open fill)
    "contract": pl.String(),  # the contract that traded (the held one, or a roll leg's)
    "kind": pl.String(),  # signal | stop | target | roll_close | roll_open
    "quantity": pl.Int64(),  # signed contracts filled (a close of a long is negative)
    "price": pl.Decimal(38, 6),  # points; the fill price (Decimal(38, 6), on the tick grid)
    "realized_usd": pl.Decimal(38, 6),  # USD; realized P&L booked by THIS fill
    "fees_usd": pl.Decimal(38, 6),  # USD; commission and fees paid by this fill
    "spread_usd": pl.Decimal(38, 6),  # USD; half-spread paid by this fill (limit fills pay none)
    "slippage_usd": pl.Decimal(38, 6),  # USD; slippage paid by this fill (limit fills pay none)
    "trade_date": pl.Date(),  # Globex trade date the fill happened on (a day label)
    "position_after": pl.Int64(),  # signed contracts held after this fill, in fill order
}

FUTURES_ROLLS_SCHEMA: dict[str, pl.DataType] = {
    "decision_time": pl.Int64(),  # UTC ns; end of the session that decided the roll
    "from_contract": pl.String(),  # the contract held before the roll
    "to_contract": pl.String(),  # the contract held from the roll on
    "reason": pl.String(),  # volume | backstop | expired (the series build's reason)
    "mode": pl.String(),  # causal (executed on raw prices) | reference_approximation
    "verified": pl.Boolean(),  # true when both legs traded at the executed minute
    "executed_time": pl.Int64(),  # UTC ns; when the legs traded (reference time if approximate)
    "old_price": pl.Decimal(38, 6),  # points; the old contract's executed price (Decimal(38, 6))
    "new_price": pl.Decimal(38, 6),  # points; the new contract's executed price (Decimal(38, 6))
    "delay_minutes": pl.Float64(),  # minutes from the decision to the execution (null if unknown)
    "reference_time": pl.Int64(),  # UTC ns; the reference prices' timestamp
    "approximation_error_ticks": pl.Int64(),  # ticks per long contract the approximation costs
    "approximation_error_usd": pl.Decimal(38, 6),  # USD per long contract (Decimal(38, 6))
    "position": pl.Int64(),  # signed contracts rolled by this roll
}


def _micro(value: Decimal | str) -> int:
    """Exact micro-dollars of a ``Decimal`` amount (it never has more than 6 decimals)."""
    scaled = Decimal(value) * MICRO
    if scaled != scaled.to_integral_value():
        msg = f"amount {value} has more than 6 decimals; money is kept in exact micro-dollars"
        raise InvariantViolation(msg)
    return int(scaled)


def _micro_list(series: pl.Series) -> list[int]:
    return [_micro(value) for value in series.to_list()]


def _money(values: list[int]) -> pl.Series:
    """Micro-dollars as an exact ``Decimal(38, 6)`` of dollars."""
    return pl.Series(values, dtype=pl.Int64).cast(pl.Decimal(38, 0)).cast(MONEY) / MICRO


def _mark_delta(points: float, contracts: int, point_value: Decimal) -> Decimal:
    """``contracts * points * point_value`` in USD, exactly enough to quantize to micro-dollars."""
    if contracts == 0 or points == 0:
        return Decimal(0)
    return Decimal(repr(float(points))) * contracts * point_value


def _floor_usd(value: Decimal) -> Decimal:
    return value.quantize(MICRO_USD, rounding=ROUND_FLOOR)


def _ceil_usd(value: Decimal) -> Decimal:
    return value.quantize(MICRO_USD, rounding=ROUND_CEILING)


def build_marks(
    *,
    bars: pl.DataFrame,
    execution: pl.DataFrame,
    trade_dates: pl.Series,
    on_schedule: pl.Series,
    spec: FuturesContractSpec,
) -> pl.DataFrame:
    """One row per execution bar: the exact close mark and the OHLC intrabar approximation.

    ``bars``: the simulator's per-bar output (same rows and order as ``execution``, the prices it
    simulated). ``execution``: those bars (its OHLC are the held contract's own prices).
    ``trade_dates``: each bar's Globex trade date; ``on_schedule``: whether each bar is inside a
    scheduled session. Timing: everything on a row is knowable at that bar's close.
    """
    if bars.height != execution.height:
        msg = (
            f"the simulator returned {bars.height} bars but the execution series has "
            f"{execution.height}: the marks are one row per simulated bar"
        )
        raise DataQualityError(msg)
    missing = {"open", "high", "low", "close"} - set(execution.columns)
    if missing:
        msg = f"the execution series lacks {sorted(missing)}; the OHLC marks need all four prices"
        raise DataQualityError(msg)
    n = bars.height
    if trade_dates.len() != n or on_schedule.len() != n:
        msg = (
            f"trade_dates has {trade_dates.len()} and on_schedule {on_schedule.len()} rows for "
            f"{n} bars: both must have one value per bar"
        )
        raise DataQualityError(msg)
    low = execution["low"].to_numpy().astype(np.float64)
    high = execution["high"].to_numpy().astype(np.float64)
    close = execution["close"].to_numpy().astype(np.float64)
    positions = bars["position"].to_numpy().astype(np.int64)
    contracts = bars["contract"].to_list()
    point_value = spec.point_value
    equity = _micro_list(bars["equity_usd"])
    low_marks = equity.copy()
    high_marks = equity.copy()
    for i in range(n):
        p = int(positions[i])
        at_close = _mark_delta(float(low[i]) - float(close[i]), p, point_value)
        close_low = _floor_usd(Decimal(equity[i]) / MICRO + at_close)
        at_close = _mark_delta(float(high[i]) - float(close[i]), p, point_value)
        close_high = _ceil_usd(Decimal(equity[i]) / MICRO + at_close)
        candidates_low = [equity[i], _micro(close_low)]
        candidates_high = [equity[i], _micro(close_high)]
        if i > 0 and contracts[i] == contracts[i - 1]:
            q = int(positions[i - 1])
            previous = _mark_delta(float(low[i]) - float(close[i - 1]), q, point_value)
            previous_low = _floor_usd(Decimal(equity[i - 1]) / MICRO + previous)
            previous = _mark_delta(float(high[i]) - float(close[i - 1]), q, point_value)
            previous_high = _ceil_usd(Decimal(equity[i - 1]) / MICRO + previous)
            candidates_low.append(_micro(previous_low))
            candidates_high.append(_micro(previous_high))
        low_marks[i] = min(candidates_low)
        high_marks[i] = max(candidates_high)
    out = pl.DataFrame(
        {
            "event_time": _int64_series(bars, "event_time"),
            "trade_date": pl.Series(trade_dates).cast(pl.Date),
            "contract": pl.Series(contracts, dtype=pl.String),
            "on_schedule": pl.Series(on_schedule).cast(pl.Boolean),
            "position": pl.Series(positions, dtype=pl.Int64),
            "balance_usd": _money(_micro_list(bars["balance_usd"])),
            "equity_usd": _money(equity),
            "equity_low_usd": _money(low_marks),
            "equity_high_usd": _money(high_marks),
            "realized_usd": _money(_micro_list(bars["realized_usd"])),
            "costs_usd": _money(_micro_list(bars["costs_usd"])),
            "unrealized_usd": _money(_micro_list(bars["unrealized_usd"])),
        }
    )
    return out.select(list(FUTURES_MARKS_SCHEMA))


def _int64_series(frame: pl.DataFrame, column: str) -> pl.Series:
    """``frame[column]`` as an ``Int64`` series (the artifact's timestamp dtype)."""
    return pl.Series(frame[column].to_list(), dtype=pl.Int64)


def build_fills(*, fills: pl.DataFrame, marks: pl.DataFrame) -> pl.DataFrame:
    """The simulator's fills plus each fill's trade date and the position after it.

    ``position_after`` is the cumulative sum of the signed quantities in fill order (the
    simulator books fills in bar and bracket order, so that is the held position after each one).
    """
    if fills.height == 0:
        return pl.DataFrame(
            {
                "event_time": pl.Series([], dtype=pl.Int64),
                "fill_time": pl.Series([], dtype=pl.Int64),
                "contract": pl.Series([], dtype=pl.String),
                "kind": pl.Series([], dtype=pl.String),
                "quantity": pl.Series([], dtype=pl.Int64),
                "price": pl.Series([], dtype=MONEY),
                "realized_usd": pl.Series([], dtype=MONEY),
                "fees_usd": pl.Series([], dtype=MONEY),
                "spread_usd": pl.Series([], dtype=MONEY),
                "slippage_usd": pl.Series([], dtype=MONEY),
                "trade_date": pl.Series([], dtype=pl.Date),
                "position_after": pl.Series([], dtype=pl.Int64),
            }
        ).select(list(FUTURES_FILLS_SCHEMA))
    dates = marks.select(pl.col("event_time"), pl.col("trade_date"))
    joined = fills.join(dates, on="event_time", how="left", maintain_order="left")
    missing = joined.filter(pl.col("trade_date").is_null())
    if missing.height:
        msg = (
            f"{missing.height} fill(s) name a bar that is not in the marks (first event_time="
            f"{int(missing['event_time'][0])} ns): every fill belongs to a simulated bar"
        )
        raise InvariantViolation(msg)
    after = np.cumsum(joined["quantity"].to_numpy().astype(np.int64))
    out = joined.with_columns(
        pl.col("trade_date").cast(pl.Date),
        pl.Series(name="position_after", values=after, dtype=pl.Int64),
    )
    return out.select(list(FUTURES_FILLS_SCHEMA))


def build_rolls(rolls: pl.DataFrame) -> pl.DataFrame:
    """The simulator's rolls, unchanged (one row per contract switch of the series)."""
    missing = [name for name in FUTURES_ROLLS_SCHEMA if name not in rolls.columns]
    if missing:
        msg = (
            f"the rolls frame lacks {missing}; it must be simulate_futures' rolls output "
            "(ROLL output columns of ADR-0090)"
        )
        raise DataQualityError(msg)
    return rolls.select(list(FUTURES_ROLLS_SCHEMA))


@dataclass(frozen=True, slots=True)
class FuturesDay:
    """One trade date's aggregation, in micro-dollars (the daily builder's working type)."""

    trade_date: dt.date
    session_open_ns: int
    session_close_ns: int
    verified: bool
    bars: int
    first_bar_ns: int
    last_bar_ns: int
    opening_balance: int
    closing_balance: int
    opening_equity: int
    closing_equity: int
    realized: int
    fees: int
    spread: int
    slippage: int
    costs: int
    unrealized_close: int
    min_equity: int
    max_equity: int
    max_contracts: int
    fills: int


def _days(
    marks: pl.DataFrame,
    bars: pl.DataFrame,
    fills: pl.DataFrame,
    calendar: SessionCalendar,
    capital: int,
) -> list[FuturesDay]:
    """The marks folded into one ``FuturesDay`` per trade date, in trade-date order.

    ``fees_usd``/``spread_usd``/``slippage_usd`` come from the simulator's per-bar flows
    (``bars``): the marks carry the bar's cost total, which is the sum of the three.
    """
    if bars.height != marks.height:
        msg = (
            f"the simulator returned {bars.height} bars for {marks.height} marks: the daily "
            "ledger decomposes each bar's costs from the simulator's own flows"
        )
        raise DataQualityError(msg)
    trade_dates = marks["trade_date"].to_list()
    if trade_dates != sorted(trade_dates):
        msg = "the marks are not in trade-date order; the daily ledger folds them in order"
        raise InvariantViolation(msg)
    times = marks["event_time"].to_list()
    positions = marks["position"].to_list()
    balance = _micro_list(marks["balance_usd"])
    equity = _micro_list(marks["equity_usd"])
    low = _micro_list(marks["equity_low_usd"])
    high = _micro_list(marks["equity_high_usd"])
    realized = _micro_list(marks["realized_usd"])
    fees = _micro_list(bars["fees_usd"])
    spread = _micro_list(bars["spread_usd"])
    slippage = _micro_list(bars["slippage_usd"])
    costs = _micro_list(marks["costs_usd"])
    unrealized = _micro_list(marks["unrealized_usd"])
    fill_dates = fills["trade_date"].to_list() if fills.height else []
    out: list[FuturesDay] = []
    previous_balance, previous_equity = capital, capital
    start = 0
    for i in range(1, marks.height + 1):
        if i < marks.height and trade_dates[i] == trade_dates[start]:
            continue
        day = trade_dates[start]
        session = calendar.session(day)
        rows = range(start, i)
        out.append(
            FuturesDay(
                trade_date=day,
                session_open_ns=session.open_ns,
                session_close_ns=session.close_ns,
                verified=session.verified,
                bars=i - start,
                first_bar_ns=int(times[start]),
                last_bar_ns=int(times[i - 1]),
                opening_balance=previous_balance,
                closing_balance=balance[i - 1],
                opening_equity=previous_equity,
                closing_equity=equity[i - 1],
                realized=sum(realized[r] for r in rows),
                fees=sum(fees[r] for r in rows),
                spread=sum(spread[r] for r in rows),
                slippage=sum(slippage[r] for r in rows),
                costs=sum(costs[r] for r in rows),
                unrealized_close=unrealized[i - 1],
                min_equity=min(low[r] for r in rows),
                max_equity=max(high[r] for r in rows),
                max_contracts=max(abs(int(positions[r])) for r in rows),
                fills=sum(1 for value in fill_dates if value == day),
            )
        )
        previous_balance, previous_equity = balance[i - 1], equity[i - 1]
        start = i
    return out


def build_daily(
    *,
    marks: pl.DataFrame,
    bars: pl.DataFrame,
    fills: pl.DataFrame,
    calendar: SessionCalendar,
    capital: Decimal,
) -> pl.DataFrame:
    """One row per trade date with at least one bar: session bounds, flows and marks.

    ``marks``: the per-bar marks; ``bars``: the simulator's bars they were built from (the cost
    decomposition comes from there).

    Timing: a day's row is complete at its last observed bar's close. ``session_open_ns`` /
    ``session_close_ns`` are the CALENDAR's scheduled bounds (ADR-0091), not the data's first and
    last bar, so a missing final bar is visible in the row rather than hidden by it.
    """
    days = _days(marks, bars, fills, calendar, _micro(capital))
    if not days:
        msg = "no marks to aggregate: a futures run needs at least one bar"
        raise DataQualityError(msg)
    return pl.DataFrame(
        {
            "trade_date": pl.Series([d.trade_date for d in days], dtype=pl.Date),
            "session_open_ns": pl.Series([d.session_open_ns for d in days], dtype=pl.Int64),
            "session_close_ns": pl.Series([d.session_close_ns for d in days], dtype=pl.Int64),
            "verified": pl.Series([d.verified for d in days], dtype=pl.Boolean),
            "bars": pl.Series([d.bars for d in days], dtype=pl.Int64),
            "first_bar_ns": pl.Series([d.first_bar_ns for d in days], dtype=pl.Int64),
            "last_bar_ns": pl.Series([d.last_bar_ns for d in days], dtype=pl.Int64),
            "opening_balance_usd": _money([d.opening_balance for d in days]),
            "closing_balance_usd": _money([d.closing_balance for d in days]),
            "opening_equity_usd": _money([d.opening_equity for d in days]),
            "closing_equity_usd": _money([d.closing_equity for d in days]),
            "realized_usd": _money([d.realized for d in days]),
            "fees_usd": _money([d.fees for d in days]),
            "spread_usd": _money([d.spread for d in days]),
            "slippage_usd": _money([d.slippage for d in days]),
            "costs_usd": _money([d.costs for d in days]),
            "unrealized_close_usd": _money([d.unrealized_close for d in days]),
            "min_equity_usd": _money([d.min_equity for d in days]),
            "max_equity_usd": _money([d.max_equity for d in days]),
            "max_contracts": pl.Series([d.max_contracts for d in days], dtype=pl.Int64),
            "fills": pl.Series([d.fills for d in days], dtype=pl.Int64),
        }
    ).select(list(FUTURES_DAILY_SCHEMA))


def _fail(trade_date: dt.date, identity: str, detail: str) -> None:
    msg = (
        f"the daily ledger breaks {identity} on trade date {trade_date}: {detail}. The daily row "
        "is a fold of the marks, so a mismatch means a mark, a flow or an opening value was "
        "written wrongly; re-run the simulation rather than editing the artifact"
    )
    raise InvariantViolation(msg)


def check_daily_ledger(daily: pl.DataFrame, marks: pl.DataFrame, capital: Decimal) -> None:
    """Assert the daily ledger's identities against the marks it was built from.

    Refuses (``InvariantViolation``, naming the trade date) when any of these fails:

    - ``closing_balance = opening_balance + realized - costs``;
    - ``closing_equity = closing_balance + unrealized_close``;
    - ``opening_balance`` of a day is the previous day's ``closing_balance`` (``capital`` on the
      first day), and the same for ``opening_equity`` / ``closing_equity``;
    - ``min_equity <= closing_equity <= max_equity``;
    - the last ``closing_equity`` is the last mark's ``equity_usd``;
    - the sum over days of ``realized - costs`` is the final balance minus ``capital``.
    """
    if daily.height == 0:
        msg = "no daily rows to check: a futures run needs at least one trade date with a bar"
        raise InvariantViolation(msg)
    money = {name: _micro_list(daily[name]) for name in FUTURES_DAILY_SCHEMA if "usd" in name}
    days = daily["trade_date"].to_list()
    for i, day in enumerate(days):
        if (
            money["closing_balance_usd"][i]
            != money["opening_balance_usd"][i] + money["realized_usd"][i] - money["costs_usd"][i]
        ):
            _fail(
                day,
                "closing_balance = opening_balance + realized - costs",
                f"{money['closing_balance_usd'][i]} != {money['opening_balance_usd'][i]} + "
                f"{money['realized_usd'][i]} - {money['costs_usd'][i]} (micro-dollars)",
            )
        if (
            money["closing_equity_usd"][i]
            != money["closing_balance_usd"][i] + money["unrealized_close_usd"][i]
        ):
            _fail(
                day,
                "closing_equity = closing_balance + unrealized_close",
                f"{money['closing_equity_usd'][i]} != {money['closing_balance_usd'][i]} + "
                f"{money['unrealized_close_usd'][i]} (micro-dollars)",
            )
        if not (
            money["min_equity_usd"][i]
            <= money["closing_equity_usd"][i]
            <= money["max_equity_usd"][i]
        ):
            _fail(
                day,
                "min_equity <= closing_equity <= max_equity",
                f"min {money['min_equity_usd'][i]}, close {money['closing_equity_usd'][i]}, "
                f"max {money['max_equity_usd'][i]} (micro-dollars)",
            )
        if i == 0:
            if money["opening_balance_usd"][i] != _micro(capital):
                _fail(
                    day,
                    "the first day opens at the starting capital (balance)",
                    f"opening {money['opening_balance_usd'][i]} != {_micro(capital)} "
                    "(micro-dollars)",
                )
            if money["opening_equity_usd"][i] != _micro(capital):
                _fail(
                    day,
                    "the first day opens at the starting capital (equity)",
                    f"opening {money['opening_equity_usd'][i]} != {_micro(capital)} "
                    "(micro-dollars)",
                )
            continue
        if money["opening_balance_usd"][i] != money["closing_balance_usd"][i - 1]:
            _fail(
                day,
                "opening_balance = the previous day's closing_balance",
                f"opening {money['opening_balance_usd'][i]} != "
                f"{money['closing_balance_usd'][i - 1]} (micro-dollars)",
            )
        if money["opening_equity_usd"][i] != money["closing_equity_usd"][i - 1]:
            _fail(
                day,
                "opening_equity = the previous day's closing_equity",
                f"opening {money['opening_equity_usd'][i]} != "
                f"{money['closing_equity_usd'][i - 1]} (micro-dollars)",
            )
    last_mark = _micro(marks["equity_usd"][-1])
    if money["closing_equity_usd"][-1] != last_mark:
        _fail(
            days[-1],
            "the last closing_equity is the last mark's equity_usd",
            f"{money['closing_equity_usd'][-1]} != {last_mark} (micro-dollars)",
        )
    flows = sum(money["realized_usd"][i] - money["costs_usd"][i] for i in range(len(days)))
    final = money["closing_balance_usd"][-1]
    if flows != final - _micro(capital):
        _fail(
            days[-1],
            "sum of (realized - costs) = final balance - capital",
            f"{flows} != {final} - {_micro(capital)} (micro-dollars)",
        )


def _metric(value: Decimal | int | float) -> dict[str, float | None]:
    """One metrics.json entry: the value, with the interval fields the contract requires."""
    return {"value": round(float(value), 6), "ci_low": None, "ci_high": None}


def build_metrics(
    *,
    marks: pl.DataFrame,
    daily: pl.DataFrame,
    fills: pl.DataFrame,
    rolls: pl.DataFrame,
    capital: Decimal,
) -> dict[str, dict[str, float | None]]:
    """Descriptive totals only: no Sharpe, no return ratio, no claim of edge (see the module
    docstring). Floats rounded to 6 decimals.

    ``min_equity_usd`` and ``max_intraday_drawdown_usd`` read the CONSERVATIVE marks
    (``equity_low_usd`` against a running maximum of ``equity_high_usd``), so a stop that filled
    inside a bar is not averaged away.
    """
    low = [Decimal(v) for v in marks["equity_low_usd"].to_list()]
    high = [Decimal(v) for v in marks["equity_high_usd"].to_list()]
    running = high[0]
    drawdown = Decimal(0)
    for low_mark, high_mark in zip(low, high, strict=True):
        running = max(running, high_mark)
        drawdown = max(drawdown, running - low_mark)
    final_balance = Decimal(daily["closing_balance_usd"][-1])
    final_equity = Decimal(daily["closing_equity_usd"][-1])
    return {
        "final_balance_usd": _metric(final_balance),
        "final_equity_usd": _metric(final_equity),
        "net_pnl_usd": _metric(final_balance - capital),
        "total_costs_usd": _metric(sum(Decimal(v) for v in daily["costs_usd"].to_list())),
        "fills": _metric(fills.height),
        "rolls": _metric(rolls.height),
        "trade_dates": _metric(daily.height),
        "max_contracts": _metric(max(abs(int(p)) for p in marks["position"].to_list())),
        "min_equity_usd": _metric(min(low)),
        "max_intraday_drawdown_usd": _metric(drawdown),
    }


__all__ = [
    "FUTURES_DAILY_SCHEMA",
    "FUTURES_FILLS_SCHEMA",
    "FUTURES_MARKS_SCHEMA",
    "FUTURES_ROLLS_SCHEMA",
    "MARKING_POLICY",
    "MICRO",
    "MONEY",
    "UNHEDGED_MARK_NOTE",
    "build_daily",
    "build_fills",
    "build_marks",
    "build_metrics",
    "build_rolls",
    "check_daily_ledger",
]
