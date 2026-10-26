"""Compiles a strategy spec into a vectorized signal function (ADR-0067).

``spec_signal(bars, params)`` is a ``SignalFunction`` (``crucible.vectorized.interfaces``): it
returns a frame keyed (ts, symbol) with a ``score`` column that is the **target weight** of that
symbol, decided from bars up to and including ``ts``. The vectorized engine lags it by one bar and
the promotion path (``PromotedSignalStrategy``) trades it at the next bar, so the two engines see
the same decision at the same time. **This module adds no lag of its own**; the convention is
stated once, here and in ``docs/modules/strategy_spec.md``, and nobody writing a spec thinks
about it.

Position logic, per symbol, evaluated bar by bar (so it is identical on the full history and on
the promoted path's growing window):

1. A held position first meets its exits: stop-loss, take-profit, ``max_holding_bars`` and the
   spec's own exit condition. An exit on a bar means flat from that bar's decision; no new entry
   is taken on the same bar (a stopped-out position does not re-enter on the bar that stopped it).
2. A flat position takes an entry. A ``long_short`` spec that is long and sees its short entry
   (or the reverse) flips directly.
3. Both sides entering on the same bar is refused (the conditions must be mutually exclusive).

A run sees exactly the bars of its dataset: indicators warm up inside the window, and no rule can
fire before it has its full history (a null is false).

Time-of-day rules (``session``, ADR-0073) read only the exchange schedule, never another bar: a
bar is its session's last when it ends at the session close, and its next-to-last when one more
bar of the declared interval would reach the close. They need ``params["session"] = {"calendar",
"interval"}`` (the one-step backtest passes it) and intraday bars.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from crucible.core.errors import ConfigurationError
from crucible.core.types import TimestampNs
from crucible.data.calendars import get_trading_calendar
from crucible.orders.interfaces import MOC_CUTOFF_NS
from crucible.strategy_spec.indicators import INDICATORS
from crucible.strategy_spec.models import (
    Always,
    BarField,
    Call,
    ClockTime,
    Group,
    Node,
    Num,
    Operand,
    StrategySpec,
    TimeOfDay,
    parse_condition,
    parse_spec,
)

if TYPE_CHECKING:
    from numpy.typing import NDArray

_BAR_COLUMNS = ("symbol", "event_time", "open", "high", "low", "close", "volume")
_NS_PER_MINUTE = 60 * 10**9
_TIME_COLUMN = "__time_of_day"
_UNIT_MINUTES = {"m": 1, "h": 60}


def _interval_ns(interval: str) -> int:
    """``5m`` / ``1h`` to nanoseconds; anything else (including ``1d``) is refused."""
    text = interval.strip().lower()
    number, unit = text[:-1], text[-1:]
    if unit not in _UNIT_MINUTES or not number.isdigit() or int(number) <= 0:
        msg = (
            f"time-of-day rules (session) need intraday bars, got interval {interval!r}; use an "
            "interval such as 5m, 15m, 30m or 1h, or remove the session block"
        )
        raise ConfigurationError(msg)
    return int(number) * _UNIT_MINUTES[unit] * _NS_PER_MINUTE


@dataclass(frozen=True, slots=True)
class SessionSchedule:
    """Per-bar schedule facts, from the calendar and the declared bar length only (ADR-0073,
    ADR-0074). ``moc_close`` is the session close a market-on-close exit targets on that bar
    (0 where none); ``minutes`` the bar's end time in minutes after local midnight."""

    force_flat: NDArray[np.bool_]
    entry_ok: NDArray[np.bool_]
    moc_close: NDArray[np.int64]
    minutes: NDArray[np.int64]


def uses_time(spec: StrategySpec) -> bool:
    """Whether an entry or exit condition reads ``time``."""
    for rules in (spec.entry, spec.exit):
        for side in ("long", "short"):
            condition = getattr(rules, side)
            if condition is None:
                continue
            node = parse_condition(condition, side)
            if any(isinstance(o, TimeOfDay) for o in condition_operands(node)):
                return True
    return False


def _clock_minutes(text: str) -> int:
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def session_schedule(
    spec: StrategySpec, event_times: NDArray[np.int64], params: dict[str, object]
) -> SessionSchedule:
    """The schedule facts the spec needs; trivial when it uses no time-of-day rule."""
    n = len(event_times)
    session = spec.session
    timed = uses_time(spec)
    trivial = SessionSchedule(
        force_flat=np.zeros(n, dtype=np.bool_),
        entry_ok=np.ones(n, dtype=np.bool_),
        moc_close=np.zeros(n, dtype=np.int64),
        minutes=np.zeros(n, dtype=np.int64),
    )
    if (session is None and not timed) or n == 0:
        return trivial
    raw = params.get("session")
    if not isinstance(raw, dict) or "calendar" not in raw or "interval" not in raw:
        msg = (
            "this spec has time-of-day rules (session, or `time` in a condition) but the run did "
            'not say when sessions close; pass params.session = {"calendar": "XNYS", "interval": '
            '"1h"} (the one-step backtest does this for you)'
        )
        raise ConfigurationError(msg)
    calendar = str(raw["calendar"])
    step = _interval_ns(str(raw["interval"]))
    week = 7 * 24 * 60 * _NS_PER_MINUTE
    first, last = int(event_times.min()), int(event_times.max())
    cal = get_trading_calendar(
        calendar, start=TimestampNs(first - week), end=TimestampNs(last + week)
    )
    closes = np.asarray(
        cal.session_closes(TimestampNs(first), TimestampNs(last + week)), dtype=np.int64
    )
    index = np.searchsorted(closes, event_times, side="left")
    if closes.size == 0 or np.any(index >= closes.size):
        msg = (
            f"a bar ends after the last session close the {calendar} calendar knows; check the "
            "calendar matches the data"
        )
        raise ConfigurationError(msg)
    close_of = closes[index]
    is_last = event_times == close_of
    is_next_to_last = (~is_last) & (event_times + step >= close_of)
    local = (
        pl.Series("t", event_times)
        .cast(pl.Datetime("ns", "UTC"))
        .dt.convert_time_zone(cal.timezone)
    )
    minutes = (local.dt.hour().cast(pl.Int64) * 60 + local.dt.minute().cast(pl.Int64)).to_numpy()

    force_flat = np.zeros(n, dtype=np.bool_)
    no_entry = np.zeros(n, dtype=np.bool_)
    moc_close = np.zeros(n, dtype=np.int64)
    if session is not None and session.flat_by_close:
        if bool(np.all(is_last)):
            msg = (
                "session.flat_by_close needs intraday bars: every bar here ends a session (daily "
                "bars), so the strategy could never hold a position"
            )
            raise ConfigurationError(msg)
        if session.close_with == "market_on_close":
            if calendar == "24/7":
                msg = (
                    "session.close_with: market_on_close needs an exchange with a closing "
                    "auction; a 24/7 market has none. Use close_with: next_to_last_bar"
                )
                raise ConfigurationError(msg)
            # the headline decides flat on the last bar (filled at its close); the event-driven
            # run sends a market-on-close order on the last bar ending by the exchanges' cutoff
            # (ten minutes before the close) for that same close; no entry after the cutoff,
            # since the event-driven run could no longer take it out at the close
            cutoff = close_of - MOC_CUTOFF_NS
            decides = (event_times <= cutoff) & (event_times + step > cutoff)
            force_flat |= is_last
            moc_close = np.where(decides, close_of, 0).astype(np.int64)
            no_entry |= event_times > cutoff
        else:
            force_flat |= is_last | is_next_to_last
        no_entry |= force_flat
    if session is not None and session.exit_at is not None:
        after = minutes >= _clock_minutes(session.exit_at)
        force_flat |= after
        no_entry |= after
    entry_ok = ~no_entry
    if session is not None and session.entry_window is not None:
        window = session.entry_window
        entry_ok &= (minutes >= _clock_minutes(window.start)) & (
            minutes <= _clock_minutes(window.end)
        )
    return SessionSchedule(
        force_flat=force_flat, entry_ok=entry_ok, moc_close=moc_close, minutes=minutes
    )


def session_masks(
    spec: StrategySpec, event_times: NDArray[np.int64], params: dict[str, object]
) -> tuple[NDArray[np.bool_], NDArray[np.bool_]]:
    """Per bar: ``force_flat`` and ``entry_ok`` (see ``session_schedule``)."""
    schedule = session_schedule(spec, event_times, params)
    return schedule.force_flat, schedule.entry_ok


def _operand_expr(operand: Operand) -> pl.Expr:
    if isinstance(operand, Num):
        return pl.lit(operand.value, dtype=pl.Float64)
    if isinstance(operand, BarField):
        return pl.col(operand.name)
    if isinstance(operand, TimeOfDay):
        return pl.col(_TIME_COLUMN).cast(pl.Float64)
    if isinstance(operand, ClockTime):
        return pl.lit(float(operand.minutes), dtype=pl.Float64)
    return INDICATORS[operand.name].build(operand.period, operand.field, operand.k)


def _node_expr(node: Node) -> pl.Expr:
    """A boolean expression over one symbol's bars; a null (warm-up) counts as false."""
    if isinstance(node, Always):
        return pl.lit(True)
    if isinstance(node, Group):
        parts = [_node_expr(item) for item in node.items]
        combined = pl.all_horizontal(parts) if node.kind == "all" else pl.any_horizontal(parts)
        return combined.fill_null(False)
    left, right = _operand_expr(node.left), _operand_expr(node.right)
    if node.op == ">":
        result = left > right
    elif node.op == ">=":
        result = left >= right
    elif node.op == "<":
        result = left < right
    elif node.op == "<=":
        result = left <= right
    else:
        # a constant is the same on the previous bar; only a series is shifted
        previous_left = left if isinstance(node.left, Num) else left.shift(1).over("symbol")
        previous_right = right if isinstance(node.right, Num) else right.shift(1).over("symbol")
        if node.op == "crosses_above":
            result = (previous_left <= previous_right) & (left > right)
        else:
            result = (previous_left >= previous_right) & (left < right)
    return result.fill_null(False)


def condition_operands(node: Node) -> list[Operand]:
    if isinstance(node, Always):
        return []
    if isinstance(node, Group):
        return [o for item in node.items for o in condition_operands(item)]
    return [node.left, node.right]


def warmup_bars(spec: StrategySpec) -> int:
    """Bars of history before the first bar on which every rule of the spec is defined."""
    needed = 0
    for rules in (spec.entry, spec.exit):
        for side in ("long", "short"):
            condition = getattr(rules, side)
            if condition is None:
                continue
            for operand in condition_operands(parse_condition(condition, f"{side}")):
                if isinstance(operand, Call):
                    needed = max(needed, INDICATORS[operand.name].warmup(operand.period))
    # a crossing also looks one bar back
    return needed + 1


def _signals(spec: StrategySpec, frame: pl.DataFrame) -> pl.DataFrame:
    """The boolean rule columns of ``frame`` (sorted by symbol, event_time)."""
    columns: list[pl.Expr] = []
    for block, rules in (("entry", spec.entry), ("exit", spec.exit)):
        for side in ("long", "short"):
            condition = getattr(rules, side)
            expr = (
                _node_expr(parse_condition(condition, f"{block}.{side}"))
                if condition is not None
                else pl.lit(False)
            )
            columns.append(expr.alias(f"{block}_{side}"))
    return frame.with_columns(columns)


def _exit_levels(
    state: int, entry_price: float, stop: float | None, take: float | None
) -> tuple[float | None, float | None]:
    """Absolute stop-loss and take-profit prices for a position held at ``state`` (+1 / -1)."""
    stop_level = None
    if stop is not None:
        stop_level = (
            entry_price * (1.0 - stop / 100.0) if state > 0 else entry_price * (1.0 + stop / 100.0)
        )
    take_level = None
    if take is not None:
        take_level = (
            entry_price * (1.0 + take / 100.0) if state > 0 else entry_price * (1.0 - take / 100.0)
        )
    return stop_level, take_level


def _intrabar_exit(
    state: int,
    open_: float,
    high: float,
    low: float,
    stop_level: float | None,
    take_level: float | None,
) -> float | None:
    """The price a stop or take-profit fills at inside one bar, or None when neither is touched.

    The **open decides first**, because it is the only fill whose ordering against the levels is
    known: opening through the stop fills at the open (that gap is the price that was available),
    and opening beyond the take-profit fills at the open (price improvement, the event ladder's
    rule, ADR-0010 5). Then, inside the bar, the stop wins when both levels are touched -- the
    worse outcome (ADR-0012's adverse rule). ``low``/``high`` reach the level only when the bar
    actually traded there, which is the whole point of ADR-0082.
    """
    if state > 0:
        if stop_level is not None and open_ <= stop_level:
            return open_
        if take_level is not None and open_ >= take_level:
            return open_
        if stop_level is not None and low <= stop_level:
            return stop_level
        if take_level is not None and high >= take_level:
            return take_level
    else:
        if stop_level is not None and open_ >= stop_level:
            return open_
        if take_level is not None and open_ <= take_level:
            return open_
        if stop_level is not None and high >= stop_level:
            return stop_level
        if take_level is not None and low <= take_level:
            return take_level
    return None


def _walk(
    spec: StrategySpec,
    symbol: str,
    ts: NDArray[np.int64],
    open_: NDArray[np.float64],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    entry_long: NDArray[np.bool_],
    entry_short: NDArray[np.bool_],
    exit_long: NDArray[np.bool_],
    exit_short: NDArray[np.bool_],
    force_flat: NDArray[np.bool_] | None = None,
    entry_ok: NDArray[np.bool_] | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """The position (-1, 0, +1) held after each bar's decision, and the price a stop or
    take-profit closed it at *inside* that bar (NaN when the bar has no such fill).

    ``force_flat`` closes any position and blocks entries on that bar; ``entry_ok`` false blocks
    new entries and flips. ``risk.stop_fill == "close"`` reproduces the pre-ADR-0082 behaviour:
    exits are compared and filled on closes, so the exit price is always NaN (the close the
    engine already uses)."""
    if force_flat is None:
        force_flat = np.zeros(len(ts), dtype=np.bool_)
    if entry_ok is None:
        entry_ok = np.ones(len(ts), dtype=np.bool_)
    stop = spec.risk.stop_loss_pct
    take = spec.risk.take_profit_pct
    max_bars = spec.risk.max_holding_bars
    level_fill = spec.risk.stop_fill == "level"
    position = np.zeros(len(ts), dtype=np.float64)
    exit_prices = np.full(len(ts), np.nan, dtype=np.float64)
    state = 0
    entry_price = math.nan
    held = 0
    for i in range(len(ts)):
        price = float(close[i])
        exited = False
        if state != 0:
            held += 1
            fill: float | None = None
            if level_fill:
                stop_level, take_level = _exit_levels(state, entry_price, stop, take)
                fill = _intrabar_exit(
                    state, float(open_[i]), float(high[i]), float(low[i]), stop_level, take_level
                )
                hit = fill is not None
            else:
                move = (price / entry_price - 1.0) * 100.0 * state
                hit = (stop is not None and move <= -stop) or (take is not None and move >= take)
            if (
                hit
                or (max_bars is not None and held >= max_bars)
                or (exit_long[i] if state > 0 else exit_short[i])
                or force_flat[i]
            ):
                state = 0
                exited = True
                if fill is not None:
                    exit_prices[i] = float(fill)
        if exited or force_flat[i]:
            position[i] = 0.0
            continue
        if not entry_ok[i]:
            position[i] = float(state)
            continue
        go_long = bool(entry_long[i])
        go_short = bool(entry_short[i])
        if go_long and go_short:
            msg = (
                f"the long and short entry rules are both true for {symbol} at ts={int(ts[i])}; "
                "a position cannot be both. Make entry.long and entry.short mutually exclusive "
                "(for example `rsi(14) < 30` for long and `rsi(14) > 70` for short)"
            )
            raise ConfigurationError(msg)
        if go_long and state <= 0:
            state, entry_price, held = 1, price, 0
        elif go_short and state >= 0:
            state, entry_price, held = -1, price, 0
        position[i] = float(state)
    return position, exit_prices


def spec_signal(bars: pl.LazyFrame, params: dict[str, object]) -> pl.LazyFrame:
    """The ``SignalFunction`` of a strategy spec.

    ``params["spec"]``: the spec as a mapping. Output columns: ``ts``, ``symbol``, ``score``
    (target weight: +/- sizing / number of symbols, 0 when flat).
    """
    raw_spec = params.get("spec")
    if raw_spec is None:
        msg = (
            "strategy.params.spec is missing: this signal function compiles a strategy spec "
            "(crucible schema --kind strategy-spec); pass the spec as params.spec"
        )
        raise ConfigurationError(msg)
    spec = parse_spec(raw_spec)

    frame = (
        bars.select([c for c in _BAR_COLUMNS if c in bars.collect_schema().names()])
        .sort(["symbol", "event_time"])
        .collect()
    )
    missing = [c for c in _BAR_COLUMNS if c not in frame.columns]
    if missing:
        msg = f"the bars lack columns {missing}; a strategy spec needs {list(_BAR_COLUMNS)}"
        raise ConfigurationError(msg)
    n_symbols = frame.get_column("symbol").n_unique()
    schedule = session_schedule(spec, frame.get_column("event_time").to_numpy(), params)
    frame = frame.with_columns(pl.Series(_TIME_COLUMN, schedule.minutes))
    scored = _signals(spec, frame).with_columns(
        pl.Series("force_flat", schedule.force_flat),
        pl.Series("entry_ok", schedule.entry_ok),
        pl.Series("moc_close", schedule.moc_close),
    )
    with_moc = spec.session is not None and spec.session.close_with == "market_on_close"
    weight = spec.sizing.weight / max(n_symbols, 1)

    parts: list[pl.DataFrame] = []
    for symbol, group in scored.group_by("symbol", maintain_order=True):
        name = str(symbol[0])
        position, exit_prices = _walk(
            spec,
            name,
            group.get_column("event_time").to_numpy(),
            group.get_column("open").to_numpy(),
            group.get_column("high").to_numpy(),
            group.get_column("low").to_numpy(),
            group.get_column("close").to_numpy(),
            group.get_column("entry_long").to_numpy(),
            group.get_column("entry_short").to_numpy(),
            group.get_column("exit_long").to_numpy(),
            group.get_column("exit_short").to_numpy(),
            group.get_column("force_flat").to_numpy(),
            group.get_column("entry_ok").to_numpy(),
        )
        columns: dict[str, object] = {
            "ts": group.get_column("event_time"),
            "symbol": group.get_column("symbol"),
            "score": position * weight,
        }
        schema: dict[str, pl.DataType] = {
            "ts": pl.Int64(),
            "symbol": pl.String(),
            "score": pl.Float64(),
        }
        if spec.risk.stop_fill == "level" and (
            spec.risk.stop_loss_pct is not None or spec.risk.take_profit_pct is not None
        ):
            # the price a stop/take-profit closed inside the bar; NaN when the bar has none. The
            # vectorized engine replaces that bar's close with it (ADR-0082)
            columns["exit_price"] = exit_prices
            schema["exit_price"] = pl.Float64()
        part = pl.DataFrame(columns, schema=schema)
        if with_moc:
            # the session close a market-on-close order should take this bar's position out at
            # (event-driven path, ADR-0074); null where there is nothing to close
            moc = group.get_column("moc_close").to_numpy()
            part = part.with_columns(
                pl.Series(
                    "close_at",
                    [int(c) if c and p != 0 else None for c, p in zip(moc, position, strict=True)],
                    dtype=pl.Int64(),
                )
            )
        parts.append(part)
    if not parts:
        return pl.DataFrame(
            schema={"ts": pl.Int64(), "symbol": pl.String(), "score": pl.Float64()}
        ).lazy()
    return pl.concat(parts).sort(["symbol", "ts"]).lazy()
