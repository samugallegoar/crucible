"""Vectorized, deterministic evaluation of a typed expression on a bar frame (ADR-0098).

``evaluate(expr, frame)`` turns the typed tree of :mod:`crucible.dsl` into one column of values,
one per row of ``frame``, in the frame's own order. It evaluates the canonical form
(``canonicalize(expr)``, exact in IEEE-754 by construction): it is the reference implementation of
the operator table's semantics, :class:`crucible.dsl.compile.CompiledSignal` holds and evaluates
that canonical form, and a future incremental evaluator (C4c) must reproduce these values row for
row.

Two invariants make the result a pure function of the frame and the expression:

- **Causality**: every operator reads only rows up to and including the current one of the
  current stream (``delay``/``delta`` shift backwards, the rolling operators look back, ``ema``
  recurses forwards). Nothing reads a clock, a registry or a random generator.
- **Availability (C2 is the single source)**: the frame must carry the C2 row columns
  ``event_time`` and ``available_at`` (``Int64`` UTC ns) and pass :func:`check_availability`, so an
  expression is never evaluated on a bar whose data had not arrived.

Semantics, shared by every operator (ADR-0098):

- **Streams**: a ``symbol`` column makes each symbol its own stream (every rolling, shifting and
  recursive operator is computed per symbol); without it the whole frame is one stream. Rows must
  be sorted by ``(symbol,) event_time``, strictly increasing within a stream (``DataQualityError``
  otherwise).
- **Windows** count rows (bars) of the stream and include the current row.
- **Nulls**: null in gives null out; every non-finite intermediate (``inf``, ``NaN``, a division
  by zero) becomes null; a rolling window is null unless all its ``n`` values are present;
  comparisons with null give null; ``and``/``or``/``not`` follow Kleene's three-valued logic;
  ``if(null, a, b)`` is null; ``min``/``max`` propagate null (unlike ``pl.min_horizontal``, which
  skips a null operand).
- **Session features** (``time_of_day``, ``minutes_since_open``, ``minutes_to_close``) are read
  from the CME session calendar (ADR-0091/0092), so an expression that uses one is refused unless
  a ``SessionCalendar`` is passed.

Units: prices and volume in the frame's own units, time features in whole minutes, everything
else dimensionless. Nothing here reads the wall clock.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Final

import numpy as np
import polars as pl

from crucible.core.errors import DataQualityError, InvariantViolation
from crucible.core.types import NS_PER_S
from crucible.data.calendars import utc_ns_to_chicago_wall
from crucible.data.cme_sessions import session_trade_dates
from crucible.dsl import ast
from crucible.dsl.canonical import canonicalize
from crucible.dsl.errors import ExpressionError
from crucible.dsl.operators import OPERATORS
from crucible.dsl.params import FreeParam, bindings_by_name
from crucible.dsl.types import SESSION_FEATURES

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from crucible.data.cme_sessions import SessionCalendar
    from crucible.dsl.ast import Expr, Expression

_AVAILABLE_AT: Final[str] = "available_at"
_EVENT_TIME: Final[str] = "event_time"
_SYMBOL: Final[str] = "symbol"
_ROW: Final[str] = "__row"
_NS_PER_MINUTE: Final[int] = 60 * NS_PER_S
_NUMERIC_FEATURES: Final[tuple[str, ...]] = ("open", "high", "low", "close", "volume")
"""The bar fields an expression may read directly (every other feature is a session feature)."""
_WINDOW_PRESERVING: Final[frozenset[str]] = frozenset(
    {"ts_mean", "ts_min", "ts_max", "ts_std", "ts_zscore", "ts_rank", "ema"}
)
"""Rolling operators: ``base + n - 1`` leading null rows on a gap-free stream."""


# ----------------------------------------------------------------------------------- refusals


def _iso(ns: int) -> str:
    """UTC nanoseconds as ``2024-03-05T14:01:00Z`` (whole seconds; a message, not a computation)."""
    return dt.datetime.fromtimestamp(int(ns) // NS_PER_S, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_bar_seconds(bar_seconds: int) -> None:
    if type(bar_seconds) is not int or bar_seconds < 1:
        msg = (
            f"bar_seconds={bar_seconds!r} must be a whole number of seconds >= 1 (the bar length "
            "of the frame, e.g. 60 for minute bars)"
        )
        raise DataQualityError(msg)


def _require_int64(frame: pl.DataFrame, column: str) -> None:
    if column not in frame.columns:
        msg = (
            f"the frame has no {column!r} column: the C2 row contract is ``event_time`` and "
            "``available_at`` as Int64 UTC nanoseconds, and the DSL refuses a frame without them. "
            "Read a bar dataset built by the store (CONTINUOUS_BAR_SCHEMA or BAR_SCHEMA)"
        )
        raise DataQualityError(msg)
    dtype = frame.schema[column]
    if dtype != pl.Int64:
        msg = (
            f"the frame's {column!r} column is {dtype}, not Int64: timestamps are Int64 UTC "
            "nanoseconds end to end (docs/CONVENTIONS.md); convert before evaluating"
        )
        raise DataQualityError(msg)


def _stream_rows(frame: pl.DataFrame) -> list[np.ndarray]:
    """Row indices of each stream, in frame order: one per symbol, or the whole frame."""
    if _SYMBOL not in frame.columns:
        return [np.arange(frame.height, dtype=np.int64)]
    symbols = frame.get_column(_SYMBOL).to_numpy()
    return [np.flatnonzero(symbols == symbol) for symbol in dict.fromkeys(symbols.tolist())]


def _check_stream_order(frame: pl.DataFrame) -> None:
    """Refuse a frame whose ``event_time`` is not strictly increasing within every stream."""
    _require_int64(frame, _EVENT_TIME)
    times = frame.get_column(_EVENT_TIME).to_numpy()
    for rows in _stream_rows(frame):
        steps = np.diff(times[rows])
        bad = np.flatnonzero(steps <= 0)
        if bad.size:
            first = int(rows[bad[0]])
            second = int(rows[bad[0] + 1])
            where = "" if _SYMBOL not in frame.columns else f" of symbol {frame[_SYMBOL][first]!r}"
            msg = (
                f"the frame's event_time is not strictly increasing at row {first} "
                f"({_iso(int(times[first]))}) in the stream{where}: {_iso(int(times[first]))} is "
                f"followed by {_iso(int(times[second]))} at row {second}. Rows of one stream must "
                "be sorted by event_time with one row per bar (the DSL evaluates rolling "
                "operators in row order)"
            )
            raise DataQualityError(msg)


def check_availability(frame: pl.DataFrame, *, bar_seconds: int = 60) -> None:
    """Refuse a frame that breaks the C2 availability contract (ADR-0098).

    C2's ``available_at`` is the only availability source: the bar's ``event_time`` is its close
    and ``available_at`` the instant its data became usable. The three refusals are:

    - ``available_at < event_time``: the data claims to be known before the bar closed;
    - ``available_at`` decreasing within a stream: a later bar is known earlier than an earlier
      one, which cannot be ordered causally;
    - ``available_at > event_time + bar_seconds``: the feed latency exceeds one bar, so a decision
      taken at this bar's close could not reach the next bar's open (not supported).

    Timing: this reads ``available_at`` only; it never reads the clock.
    """
    _require_bar_seconds(bar_seconds)
    _require_int64(frame, _EVENT_TIME)
    _require_int64(frame, _AVAILABLE_AT)
    times = frame.get_column(_EVENT_TIME).to_numpy()
    available = frame.get_column(_AVAILABLE_AT).to_numpy()
    limit = bar_seconds * NS_PER_S
    for rows in _stream_rows(frame):
        stream_times = times[rows]
        stream_available = available[rows]
        early = np.flatnonzero(stream_available < stream_times)
        if early.size:
            index = int(early[0])
            row = int(rows[index])
            msg = (
                f"available_at is before event_time at row {row} "
                f"({_iso(int(stream_times[index]))}): the data is stamped available "
                f"{_iso(int(stream_available[index]))}, before the bar closed. A bar's data "
                "cannot be known before the bar ends; fix the available_at column (it is the C2 "
                "contract's only availability source)"
            )
            raise DataQualityError(msg)
        decreasing = np.flatnonzero(np.diff(stream_available) < 0)
        if decreasing.size:
            row = int(rows[decreasing[0]])
            msg = (
                f"available_at decreases within one stream at row {row} "
                f"({_iso(int(stream_times[decreasing[0]]))}): "
                f"{_iso(int(stream_available[decreasing[0]]))} is followed by "
                f"{_iso(int(stream_available[decreasing[0] + 1]))}. A later bar cannot be known "
                "earlier than an earlier one; fix the available_at column"
            )
            raise DataQualityError(msg)
        late = np.flatnonzero(stream_available - stream_times > limit)
        if late.size:
            row = int(rows[late[0]])
            latency = int(stream_available[late[0]] - stream_times[late[0]])
            msg = (
                f"available_at is {latency / NS_PER_S:g}s after event_time at row {row} "
                f"({_iso(int(stream_times[late[0]]))}), more than the bar's {bar_seconds}s: feed "
                "latency longer than one bar: a decision at this bar could not reach the next "
                "bar's open; not supported"
            )
            raise DataQualityError(msg)


# --------------------------------------------------------------------------- feature columns


def _features_used(root: Expr) -> tuple[str, ...]:
    names = {node.name for node in ast.walk_preorder(root) if isinstance(node, ast.Feature)}
    return tuple(sorted(names))


def _require_feature(frame: pl.DataFrame, name: str) -> None:
    if name not in frame.columns:
        msg = (
            f"the frame has no {name!r} column, which the expression reads: a bar frame carries "
            f"{', '.join(_NUMERIC_FEATURES)} plus event_time and available_at (the store's bar "
            "contract); read the dataset through the store rather than building a frame by hand"
        )
        raise DataQualityError(msg)


def _session_feature(
    name: str,
    frame: pl.DataFrame,
    calendar: SessionCalendar,
    bar_seconds: int,
    sessions: Mapping[dt.date, tuple[int, int]],
    on_schedule: np.ndarray,
) -> pl.Series:
    """One session feature per row, null on an off-schedule bar (``minutes_*`` only)."""
    times = frame.get_column(_EVENT_TIME).to_numpy()
    if name == "time_of_day":
        walls = utc_ns_to_chicago_wall([int(value) for value in times])
        return pl.Series(
            name, [float(wall.hour * 60 + wall.minute) for wall in walls], dtype=pl.Float64
        )
    days, _ = session_trade_dates(calendar, times, bar_seconds)
    dates = [dt.date.fromisoformat(str(day)) for day in days]
    out = np.full(times.shape, np.nan, dtype=np.float64)
    for index, end in enumerate(times):
        if not bool(on_schedule[index]):
            continue
        opened, closed = sessions[dates[index]]
        if name == "minutes_since_open":
            out[index] = float((int(end) - opened) // _NS_PER_MINUTE)
        else:
            out[index] = float((closed - int(end)) // _NS_PER_MINUTE)
    return pl.Series(name, out, dtype=pl.Float64, nan_to_null=True)


# ------------------------------------------------------------------------------ the evaluator


class _Evaluator:
    """Evaluates one typed tree over one frame, column by column (post-order)."""

    def __init__(
        self,
        expression: Expression,
        frame: pl.DataFrame,
        calendar: SessionCalendar | None,
        bar_seconds: int,
    ) -> None:
        self._expression = expression
        self._frame = frame
        self._calendar = calendar
        self._bar_seconds = bar_seconds
        self._has_symbol = _SYMBOL in frame.columns
        self._bindings: Mapping[str, FreeParam] = bindings_by_name(expression.params)
        self._types = expression.types
        self._columns: dict[int, str] = {}
        self._counter = 0
        self._work = pl.DataFrame({_ROW: np.arange(frame.height, dtype=np.int64)})
        if self._has_symbol:
            self._work = self._work.with_columns(frame.get_column(_SYMBOL).alias(_SYMBOL))
        self._used = _features_used(expression.root)
        needs_calendar = any(name in SESSION_FEATURES for name in self._used)
        self._sessions = self._session_index() if needs_calendar else {}
        self._on_schedule = (
            self._schedule_mask() if needs_calendar else np.zeros(frame.height, dtype=np.bool_)
        )
        self._features: dict[str, str] = {}
        for name in self._used:
            self._features[name] = self._feature(name)

    # -- helpers

    def _session_index(self) -> dict[dt.date, tuple[int, int]]:
        assert self._calendar is not None
        times = self._frame.get_column(_EVENT_TIME).to_numpy()
        days, _ = session_trade_dates(self._calendar, times, self._bar_seconds)
        sessions: dict[dt.date, tuple[int, int]] = {}
        for raw in days:
            day = dt.date.fromisoformat(str(raw))
            if day not in sessions:
                session = self._calendar.session(day)
                sessions[day] = (session.open_ns, session.close_ns)
        return sessions

    def _schedule_mask(self) -> np.ndarray:
        assert self._calendar is not None
        times = self._frame.get_column(_EVENT_TIME).to_numpy()
        _, on_schedule = session_trade_dates(self._calendar, times, self._bar_seconds)
        return np.asarray(on_schedule, dtype=np.bool_)

    def _feature(self, name: str) -> str:
        if name in SESSION_FEATURES:
            assert self._calendar is not None  # refused by evaluate() before the evaluator runs
            series = _session_feature(
                name,
                self._frame,
                self._calendar,
                self._bar_seconds,
                self._sessions,
                self._on_schedule,
            )
            return self._add_series(series.cast(pl.Float64))
        _require_feature(self._frame, name)
        self._work = self._work.with_columns(self._frame.get_column(name).cast(pl.Float64))
        return self._add(_finite(pl.col(name)), clean=False)

    def _add(self, expr: pl.Expr, *, clean: bool = True) -> str:
        self._counter += 1
        name = f"__e{self._counter}"
        value = _finite(expr) if clean else expr
        self._work = self._work.with_columns(value.alias(name))
        return name

    def _add_series(self, series: pl.Series) -> str:
        self._counter += 1
        name = f"__e{self._counter}"
        self._work = self._work.with_columns(series.alias(name))
        return name

    def _column(self, node: Expr) -> str:
        try:
            return self._columns[id(node)]
        except KeyError:  # pragma: no cover - every child is evaluated before its parent
            msg = f"dsl evaluation reached {type(node).__name__} before its children"
            raise InvariantViolation(msg) from None

    def _series(self, node: Expr) -> pl.Series:
        return self._work.get_column(self._column(node))

    def _over(self, expr: pl.Expr) -> pl.Expr:
        """Per-symbol when the frame has a stream column, over the whole frame otherwise."""
        return expr.over(_SYMBOL) if self._has_symbol else expr

    def _window(self, node: Expr, *, op: str) -> int:
        if isinstance(node, ast.Literal):
            return int(node.value)
        if isinstance(node, ast.Param):
            binding = self._bindings.get(node.name)
            if binding is None:
                msg = f"{op}() window ${node.name} has no binding in the expression"
                raise InvariantViolation(msg)
            return int(binding.default)
        msg = f"{op}() window argument is {type(node).__name__}, not an int literal or parameter"
        raise InvariantViolation(msg)

    # -- traversal

    def run(self) -> pl.Series:
        column = self.evaluate(self._expression.root)
        return self._work.get_column(column)

    def evaluate(self, node: Expr) -> str:
        key = id(node)
        if key in self._columns:
            return self._columns[key]
        if isinstance(node, ast.Literal):
            column = self._add(self._literal(node), clean=False)
        elif isinstance(node, ast.Feature):
            column = self._features[node.name]
        elif isinstance(node, ast.Param):
            column = self._add(self._literal(node), clean=True)
        elif isinstance(node, ast.Unary):
            child = self.evaluate(node.operand)
            column = self._unary(node, child)
        elif isinstance(node, ast.Binary):
            left = self.evaluate(node.left)
            right = self.evaluate(node.right)
            column = self._binary(node, left, right)
        else:
            assert isinstance(node, ast.Call)
            args = [self.evaluate(arg) for arg in node.args]
            column = self._call(node, args)
        self._columns[key] = column
        return column

    # -- nodes

    def _literal(self, node: Expr) -> pl.Expr:
        node_type = self._types[node]
        if node_type.is_bool:
            return pl.lit(bool(node.value), dtype=pl.Boolean)  # type: ignore[attr-defined]
        if isinstance(node, ast.Param):
            binding = self._bindings[node.name]
            return pl.lit(float(binding.default), dtype=pl.Float64)
        return pl.lit(float(node.value), dtype=pl.Float64)  # type: ignore[attr-defined]

    def _unary(self, node: ast.Unary, child: str) -> str:
        if node.op == "not":
            return self._add(pl.col(child).not_(), clean=False)
        return self._add(-pl.col(child))

    def _binary(self, node: ast.Binary, left: str, right: str) -> str:
        first = pl.col(left)
        second = pl.col(right)
        if node.op == "and":
            return self._add(first.and_(second), clean=False)
        if node.op == "or":
            return self._add(first.or_(second), clean=False)
        if node.op in (">", ">=", "<", "<="):
            compared = {
                ">": first > second,
                ">=": first >= second,
                "<": first < second,
                "<=": first <= second,
            }[node.op]
            return self._add(compared, clean=False)
        arithmetic = {
            "+": first + second,
            "-": first - second,
            "*": first * second,
            "/": first / second,
        }[node.op]
        return self._add(arithmetic)

    def _call(self, node: ast.Call, args: list[str]) -> str:
        name = node.name
        if name == "cs_rank":
            msg = "cs_rank is evaluated in C4c"
            raise ExpressionError(
                msg,
                column=node.column,
                token=name,
                hint="rank within a cross-section needs the whole bar; it is not part of C4b",
            )
        if name == "abs":
            return self._add(pl.col(args[0]).abs())
        if name == "sign":
            return self._add(pl.col(args[0]).sign())
        if name in {"min", "max"}:
            return self._add(self._extreme(name, pl.col(args[0]), pl.col(args[1])))
        if name == "if":
            return self._add(self._conditional(node, args), clean=not self._types[node].is_bool)
        definition = OPERATORS[name]
        assert definition.window_args
        window = self._window(node.args[definition.window_args[0]], op=name)
        if name == "ts_rank":
            return self._add_series(self._propagate(self._series(node.args[0]), _ts_rank, window))
        if name == "ema":
            return self._add_series(self._propagate(self._series(node.args[0]), _ema, window))
        return self._add(self._rolling(name, args[0], window))

    # -- operator bodies

    def _extreme(self, name: str, first: pl.Expr, second: pl.Expr) -> pl.Expr:
        """Element-wise min/max that propagates null (``min_horizontal`` skips it)."""
        missing = first.is_null() | second.is_null()
        chosen = (
            pl.when(first <= second).then(first).otherwise(second)
            if name == "min"
            else pl.when(first >= second).then(first).otherwise(second)
        )
        return pl.when(missing).then(pl.lit(None, dtype=pl.Float64)).otherwise(chosen)

    def _conditional(self, node: ast.Call, args: list[str]) -> pl.Expr:
        condition = pl.col(args[0])
        dtype = pl.Boolean if self._types[node].is_bool else pl.Float64
        return (
            pl.when(condition.is_null())
            .then(pl.lit(None, dtype=dtype))
            .when(condition)
            .then(pl.col(args[1]))
            .otherwise(pl.col(args[2]))
        )

    def _rolling(self, name: str, child: str, window: int) -> pl.Expr:
        value = pl.col(child)
        if name == "delay":
            return self._over(value.shift(window))
        if name == "delta":
            return self._over(value - value.shift(window))
        if name == "ts_mean":
            return self._over(value.rolling_mean(window_size=window, min_samples=window))
        if name == "ts_min":
            return self._over(value.rolling_min(window_size=window, min_samples=window))
        if name == "ts_max":
            return self._over(value.rolling_max(window_size=window, min_samples=window))
        if name == "ts_std":
            return self._over(value.rolling_std(window_size=window, min_samples=window, ddof=1))
        if name == "ts_zscore":
            mean = self._over(value.rolling_mean(window_size=window, min_samples=window))
            std = self._over(value.rolling_std(window_size=window, min_samples=window, ddof=1))
            return (
                pl.when(std.is_null() | (std == 0.0))
                .then(pl.lit(None, dtype=pl.Float64))
                .otherwise((value - mean) / std)
            )
        msg = f"{name}() has no vectorized evaluation"
        raise InvariantViolation(msg)

    def _propagate(
        self, values: pl.Series, function: Callable[[np.ndarray, int], np.ndarray], window: int
    ) -> pl.Series:
        """Apply a per-stream numpy kernel (``ts_rank``, ``ema``) to a numeric series."""
        array = values.to_numpy().astype(np.float64, copy=True)
        out = np.full(array.shape, np.nan, dtype=np.float64)
        for rows in _stream_rows(self._work):
            out[rows] = function(array[rows], window)
        return pl.Series(out, dtype=pl.Float64, nan_to_null=True)


def _finite(expr: pl.Expr) -> pl.Expr:
    """``expr`` with every non-finite value (inf, NaN) turned into null."""
    return pl.when(expr.is_finite()).then(expr).otherwise(pl.lit(None, dtype=pl.Float64))


def _ts_rank(values: np.ndarray, window: int) -> np.ndarray:
    """Average-tie rank of the last value among the last ``window`` values, in ``[0, 1]``."""
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if values.size < window:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(values, window)
    complete = ~np.isnan(windows).any(axis=1)
    current = windows[:, -1][:, None]
    less = (windows < current).sum(axis=1)
    equal = (windows == current).sum(axis=1)
    rank = less + (equal + 1) / 2.0
    normalized = (rank - 1.0) / (window - 1.0)
    out[window - 1 :] = np.where(complete, normalized, np.nan)
    return out


def _ema(values: np.ndarray, window: int) -> np.ndarray:
    """Recursive EMA, alpha = 2/(window+1), seeded at the first value; null until n are seen."""
    out = np.full(values.shape, np.nan, dtype=np.float64)
    alpha = 2.0 / (window + 1.0)
    state = 0.0
    seen = 0
    started = False
    for index, value in enumerate(values):
        if np.isnan(value):
            continue  # a null input gives a null output and leaves the state unchanged
        state = value if not started else alpha * value + (1.0 - alpha) * state
        started = True
        seen += 1
        if seen >= window:
            out[index] = state
    return out


# ------------------------------------------------------------------------------ public API


def evaluate(
    expr: Expression,
    frame: pl.DataFrame,
    *,
    calendar: SessionCalendar | None = None,
    bar_seconds: int = 60,
) -> pl.Series:
    """Evaluate ``expr`` over ``frame``: one value per row, in the frame's order.

    ``frame``: the bars, sorted by ``(symbol,) event_time`` with strictly increasing timestamps
    per stream; it must carry ``event_time`` and ``available_at`` (the C2 contract, checked by
    :func:`check_availability`). ``calendar``: the CME session calendar a session feature needs
    (``calendar_for(root)``); without it an expression that reads one is refused. ``bar_seconds``:
    the bar length of the frame.

    Returns a Float64 series for a numeric root (a score) and a Boolean series for a bool root (a
    condition). Evaluation always runs on the canonical form (``canonicalize(expr)``): the
    canonicalization is exact (a property test proves it is bitwise the same, nulls included), so
    ``evaluate(expr)`` and ``evaluate(canonicalize(expr))`` agree row for row.
    """
    _require_bar_seconds(bar_seconds)
    expression = canonicalize(expr)
    check_availability(frame, bar_seconds=bar_seconds)
    _check_stream_order(frame)
    session = sorted(set(_features_used(expression.root)) & SESSION_FEATURES)
    if session and calendar is None:
        msg = (
            f"the expression reads {', '.join(session)}, a session feature computed from the CME "
            "session calendar's schedule and exchange time zone (ADR-0091/0092); evaluate it with "
            "calendar=calendar_for(root)"
        )
        raise ExpressionError(msg, token=session[0], hint="evaluate(expr, bars, calendar=...)")
    evaluator = _Evaluator(expression, frame, calendar, bar_seconds)
    values = evaluator.run()
    if expression.root_type.is_bool:
        return values
    return values.cast(pl.Float64)


def warmup_bars(expr: Expression) -> int:
    """The number of leading rows of a gap-free stream that are null **by construction**.

    ``delay(x, n)``/``delta(x, n)`` add ``n``; a rolling operator adds ``n - 1`` (its window
    includes the current row); ``ema(x, n)`` adds ``n - 1``; composition adds along a path and a
    binary operator or ``if`` takes the largest of its arguments. ``0`` means the first row is
    already defined. Static: it reads the tree and the bound parameters, never data.
    """

    bound = _BoundParams(expr)

    def walk(node: Expr) -> int:
        if isinstance(node, ast.Unary):
            return walk(node.operand)
        if isinstance(node, ast.Binary):
            return max(walk(node.left), walk(node.right))
        if isinstance(node, ast.Call):
            definition = OPERATORS[node.name]
            base = max(
                (
                    walk(arg)
                    for position, arg in enumerate(node.args)
                    if position not in definition.window_args
                ),
                default=0,
            )
            if not definition.window_args:
                return base
            window = bound.window(node.args[definition.window_args[0]], op=node.name)
            if node.name in {"delay", "delta"}:
                return base + window
            if node.name in _WINDOW_PRESERVING:
                return base + window - 1
            return base
        return 0

    return walk(expr.root)


class _BoundParams:
    """The window value of a call argument, from the expression's bound parameters."""

    def __init__(self, expression: Expression) -> None:
        self._bindings = bindings_by_name(expression.params)

    def window(self, node: Expr, *, op: str) -> int:
        if isinstance(node, ast.Literal):
            return int(node.value)
        if isinstance(node, ast.Param):
            binding = self._bindings.get(node.name)
            if binding is None:
                msg = f"{op}() window ${node.name} has no binding in the expression"
                raise InvariantViolation(msg)
            return int(binding.default)
        msg = f"{op}() window argument is {type(node).__name__}, not an int literal or parameter"
        raise InvariantViolation(msg)


__all__ = [
    "SESSION_FEATURES",
    "check_availability",
    "evaluate",
    "warmup_bars",
]
