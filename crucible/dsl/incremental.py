"""Incremental (live) evaluation of one compiled signal, one timestamp at a time (ADR-0099).

:class:`IncrementalEvaluator` runs the **same immutable definition** as
:meth:`crucible.dsl.compile.CompiledSignal.evaluate` (the vectorized reference), but from its own
per-stream state instead of over a whole frame. ``step(event_time, rows)`` is one decision
timestamp across every stream: each row carries the bar's features and its ``available_at``, the
window buffers and the EMA recursion advance by one, and the value is returned per symbol.

The definition is never mutated: ``CompiledSignal`` holds the canonical tree, the code above keeps
the state. That is what makes live and backtest one definition (ADR-0098 §6, ADR-0099 §3).

Semantics are exactly ADR-0098's, row for row:

- **Streams.** One stream per symbol. A symbol absent from a step is *not* updated (no forward
  fill) and is not in that step's cross-section. ``event_time`` must be strictly increasing per
  stream (``DataQualityError``), and every availability rule of
  :func:`crucible.dsl.evaluate.check_availability` is applied incrementally: ``available_at >=
  event_time``, never decreasing within a stream, and never more than one bar late.
- **Windows** count the stream's rows, including the current one; a null input stays in the window
  (a window with a null is null), so no row is skipped.
- **Nulls.** Null in gives null out; a non-finite intermediate becomes null; ``and``/``or``/``not``
  follow Kleene's three-valued logic; ``if(null, a, b)`` is null; ``min``/``max`` propagate null.
- **Operators.** ``delay``/``delta`` shift by rows, ``ts_std`` is the sample standard deviation
  (ddof=1), ``ts_rank`` averages ties and normalizes to ``[0, 1]``, ``ts_zscore`` is null when the
  window's standard deviation is null or zero, and ``ema`` (``alpha = 2/(n+1)``, ``adjust=False``)
  is seeded at the first non-null value, gives null for a null input *without changing its state*
  and is null until ``n`` non-null values have been seen.
- **``cs_rank``** ranks the arguments of the step's symbols (only those with a row *and* a non-null
  argument, at least :data:`crucible.dsl.evaluate.MIN_CS_MEMBERS`), average ties, normalized to
  ``[0, 1]``; ``decision_at`` is the latest ``available_at`` of the universe, exactly the column
  the vectorized path publishes as ``decision_at``.
- **Session features** are read from the CME session calendar exactly as the vectorized path does
  (``time_of_day`` exchange-local minutes at the bar's end, ``minutes_since_open``/
  ``minutes_to_close`` against the bar's scheduled session, null on an off-schedule bar).

**Parity, not bitwise equality.** Numerical results agree with the vectorized evaluator within a
relative tolerance (see :mod:`crucible.dsl.parity`): Polars' rolling aggregates and these buffers
sum the same values in a different order, so the last bit can differ. Nulls and booleans agree
exactly.

Nothing here reads the wall clock or a random generator.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import numpy as np

from crucible.core.checkpoint import field as ckpt_field
from crucible.core.checkpoint import field_dict
from crucible.core.errors import CheckpointError, DataQualityError, InvariantViolation
from crucible.core.types import NS_PER_S
from crucible.data.calendars import utc_ns_to_chicago_wall
from crucible.data.cme_sessions import session_trade_dates
from crucible.dsl import ast
from crucible.dsl.errors import ExpressionError
from crucible.dsl.evaluate import (
    MIN_CS_MEMBERS,
    _average_ranks,
    _require_bar_seconds,
)
from crucible.dsl.operators import OPERATORS
from crucible.dsl.params import FreeParam, bindings_by_name
from crucible.dsl.types import SESSION_FEATURES

if TYPE_CHECKING:
    from crucible.data.cme_sessions import SessionCalendar
    from crucible.dsl.ast import Expr, Expression
    from crucible.dsl.compile import CompiledSignal

Value = float | bool | None
"""One node's value at one stream: a float, a bool or null (never ``NaN``: that is null)."""

_NS_PER_MINUTE: Final[int] = 60 * NS_PER_S
_WINDOW_PRESERVING: Final[frozenset[str]] = frozenset(
    {"ts_mean", "ts_min", "ts_max", "ts_std", "ts_zscore", "ts_rank"}
)
"""Rolling operators whose state is the last ``n`` child values."""


@dataclass(frozen=True, slots=True)
class StepOutput:
    """One symbol's decision at one timestamp: the value, when it is knowable, and the universe."""

    value: float | bool | None
    """The signal's value (a score or a condition); ``None`` is null, which a caller treats as
    flat, never as "hold"."""

    decision_at: int | None
    """UTC ns at which this output is knowable: the row's ``available_at``, or, when the expression
    uses ``cs_rank``, the latest ``available_at`` of the cross-section it ranked (``None`` when that
    universe is empty)."""

    cs_count: int | None
    """The smallest cross-section the expression ranked at this timestamp (``None`` without
    ``cs_rank``)."""


@dataclass(frozen=True, slots=True)
class _NodePlan:
    """What one AST node needs from the incremental state."""

    index: int
    """The node's index in the canonical root's pre-order (the snapshot's stable key)."""

    window: int = 0
    """The resolved window ``n`` of a windowed call (``0`` when the node takes none)."""

    stateful: bool = False
    """Whether the node keeps a rolling buffer."""

    exponential: bool = False
    """Whether the node is the ``ema`` recursion (value + count, no buffer)."""


@dataclass(slots=True)
class _NodeState:
    """One node's state on one stream: a rolling buffer, an EMA value, or nothing."""

    buffer: deque[float | None] = field(default_factory=deque)
    ema: float | None = None
    seen: int = 0


@dataclass(slots=True)
class _Stream:
    """One symbol's state: its last timestamps and the state of every stateful node."""

    last_event_time: int | None = None
    last_available_at: int | None = None
    nodes: dict[int, _NodeState] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _SessionFacts:
    """The session features of one ``event_time`` (computed once per step, from the calendar)."""

    time_of_day: float
    minutes_since_open: float | None
    minutes_to_close: float | None


def _finite(value: float) -> float | None:
    """``value`` if it is finite, null otherwise (every non-finite intermediate is null)."""
    return value if np.isfinite(value) else None


def _numeric(value: object, what: str) -> float | None:
    """A row value as a float, or null; refuses anything that is not a number or null."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{what} must be a number or null, got {type(value).__name__} ({value!r})"
        raise DataQualityError(msg)
    return float(value)


def _sample_std(values: np.ndarray) -> float:
    """The sample standard deviation (ddof=1) of a window, one pass (Welford).

    One pass matters for parity, not for speed: an identical window has ``M2`` exactly ``0.0``
    (every ``value - mean`` is exactly zero), so a constant window gives exactly ``0.0`` -- the
    same reading Polars' ``rolling_std`` publishes, and the one ``ts_zscore`` turns into null. A
    two-pass ``sum((x - mean)**2)`` leaves a rounding residue of ``1e-18`` on values such as
    ``0.05``, which would make the z-score a huge number instead of null.
    """
    mean = 0.0
    m2 = 0.0
    for count, value in enumerate(values.tolist(), start=1):
        delta = value - mean
        mean += delta / count
        m2 += delta * (value - mean)
    return math.sqrt(max(m2, 0.0) / (values.size - 1))


def _number(value: Value, what: str) -> float | None:
    """A node value where the type checker guarantees a number: null passes, a bool does not."""
    if value is None:
        return None
    if isinstance(value, bool):
        msg = f"{what} received a bool where the node's type allows only a number"
        raise InvariantViolation(msg)
    return value


class IncrementalEvaluator:
    """One :class:`CompiledSignal`, evaluated one decision timestamp at a time (ADR-0099).

    ``signal``: the immutable definition; it is never mutated. ``calendar``: the CME session
    calendar a session feature needs (``calendar_for(root)``); without it an expression that reads
    one is refused. ``bar_seconds``: the bar length, which bounds the accepted ``available_at``
    latency.

    The state is per symbol: rolling buffers and delays, the EMA value and count, and the
    stream's last ``event_time``/``available_at``. It implements
    :class:`crucible.core.interfaces.Snapshottable` (``snapshot``/``restore``), so a caller can
    checkpoint a live run and resume it.
    """

    def __init__(
        self,
        signal: CompiledSignal,
        *,
        calendar: SessionCalendar | None = None,
        bar_seconds: int = 60,
    ) -> None:
        _require_bar_seconds(bar_seconds)
        session = sorted(set(signal.features) & SESSION_FEATURES)
        if session and calendar is None:
            msg = (
                f"the expression reads {', '.join(session)}, a session feature computed from the "
                "CME session calendar's schedule and exchange time zone (ADR-0091/0092); build "
                "the evaluator with calendar=calendar_for(root)"
            )
            raise ExpressionError(
                msg,
                token=session[0],
                hint="IncrementalEvaluator(signal, calendar=calendar_for(root))",
            )
        self._signal = signal
        self._expression: Expression = signal.expression
        self._calendar = calendar
        self._bar_seconds = bar_seconds
        self._bindings = bindings_by_name(self._expression.params)
        self._plans: dict[int, _NodePlan] = _node_plans(self._expression, self._bindings)
        self._cs_nodes: tuple[ast.Call, ...] = tuple(
            node
            for node in ast.walk_preorder(self._expression.root)
            if isinstance(node, ast.Call) and node.name == "cs_rank"
        )
        self._features: tuple[str, ...] = tuple(
            name for name in signal.features if name not in SESSION_FEATURES
        )
        self._streams: dict[str, _Stream] = {}
        self._event_time: int | None = None
        self._rows: Mapping[str, Mapping[str, float | int | None]] = {}
        self._available: dict[str, int] = {}
        self._symbols: tuple[str, ...] = ()
        self._values: dict[int, dict[str, Value]] = {}
        self._cs_values: dict[int, dict[str, float | None]] = {}
        self._cs_counts: dict[int, int] = {}
        self._cs_decision: dict[int, int | None] = {}
        self._session: tuple[int, _SessionFacts] | None = None

    # ------------------------------------------------------------------------ the definition

    @property
    def signal(self) -> CompiledSignal:
        """The definition this evaluator runs (never mutated)."""
        return self._signal

    @property
    def bar_seconds(self) -> int:
        """The bar length the availability rules are checked against."""
        return self._bar_seconds

    # ----------------------------------------------------------------------------- one step

    def step(
        self, event_time: int, rows: Mapping[str, Mapping[str, float | int | None]]
    ) -> Mapping[str, StepOutput]:
        """Advance every stream by one decision timestamp and return one output per symbol.

        ``event_time``: the bars' close, UTC ns ``Int64``. ``rows``: the bar of each symbol, with
        every non-session feature the signal reads plus ``available_at`` (UTC ns). A symbol absent
        from ``rows`` is not updated and is not in the cross-section (no forward fill).

        Refuses (``DataQualityError``) an ``event_time`` that is not strictly later than the
        stream's previous one, any availability violation of ADR-0098, a missing feature and a
        non-numeric feature value. Returns one :class:`StepOutput` per symbol of ``rows``.
        """
        self._begin(event_time, rows)
        values = {symbol: self._value(self._expression.root, symbol) for symbol in self._symbols}
        decision_at, cs_count = self._step_cross_section()
        outputs = {
            symbol: StepOutput(
                value=values[symbol],
                decision_at=decision_at[symbol],
                cs_count=cs_count,
            )
            for symbol in self._symbols
        }
        for symbol in self._symbols:
            stream = self._streams[symbol]
            stream.last_event_time = self._event_time
            stream.last_available_at = self._available[symbol]
        return outputs

    def _begin(self, event_time: int, rows: Mapping[str, Mapping[str, float | int | None]]) -> None:
        """Validate one step and reset the per-step caches (no state advances here)."""
        if type(event_time) is not int:
            msg = (
                f"event_time={event_time!r} must be an int (UTC ns); timestamps are Int64 UTC "
                "nanoseconds end to end (docs/CONVENTIONS.md)"
            )
            raise DataQualityError(msg)
        limit = self._bar_seconds * NS_PER_S
        available_at: dict[str, int] = {}
        for symbol in sorted(rows):
            row = rows[symbol]
            if "available_at" not in row:
                msg = (
                    f"the bar of symbol {symbol!r} has no 'available_at': the C2 row contract is "
                    "``event_time`` and ``available_at`` as UTC nanoseconds, and the DSL refuses a "
                    "bar without it"
                )
                raise DataQualityError(msg)
            available = row["available_at"]
            if type(available) is not int:
                msg = (
                    f"the bar of symbol {symbol!r} has available_at={available!r}, not an int: "
                    "timestamps are Int64 UTC nanoseconds"
                )
                raise DataQualityError(msg)
            stream = self._streams.setdefault(symbol, _Stream())
            if stream.last_event_time is not None and event_time <= stream.last_event_time:
                msg = (
                    f"event_time={event_time} is not strictly later than the stream's last one "
                    f"({stream.last_event_time}) for symbol {symbol!r}: steps must be in "
                    "time order, one bar at a time"
                )
                raise DataQualityError(msg)
            if available < event_time:
                msg = (
                    f"available_at={available} is before event_time={event_time} for symbol "
                    f"{symbol!r}: a bar's data cannot be known before the bar closed"
                )
                raise DataQualityError(msg)
            if stream.last_available_at is not None and available < stream.last_available_at:
                msg = (
                    f"available_at={available} is earlier than the previous bar's "
                    f"{stream.last_available_at} for symbol {symbol!r}: a later bar cannot be "
                    "known earlier than an earlier one"
                )
                raise DataQualityError(msg)
            if available - event_time > limit:
                latency = (available - event_time) / NS_PER_S
                msg = (
                    f"available_at is {latency:g}s after event_time={event_time} for symbol "
                    f"{symbol!r}, more than the bar's {self._bar_seconds}s: feed latency longer "
                    "than one bar is not supported"
                )
                raise DataQualityError(msg)
            for name in self._features:
                if name not in row:
                    msg = (
                        f"the bar of symbol {symbol!r} has no {name!r} column, which the "
                        "expression reads: every bar carries the features the signal's "
                        "definition needs"
                    )
                    raise DataQualityError(msg)
                _numeric(row[name], f"the bar of symbol {symbol!r}, feature {name!r}")
            available_at[symbol] = available
        self._event_time = event_time
        self._rows = rows
        self._available = available_at
        self._symbols = tuple(sorted(rows))
        self._values = {}
        self._cs_values = {}
        self._cs_counts = {}
        self._cs_decision = {}

    # ------------------------------------------------------------------------- evaluation

    def _value(self, node: Expr, symbol: str) -> Value:
        """The node's value for ``symbol`` at the current step, memoized (state advances once)."""
        key = id(node)
        memo = self._values.get(key)
        if memo is None:
            memo = {}
            self._values[key] = memo
        if symbol in memo:
            return memo[symbol]
        value = self._compute(node, symbol)
        memo[symbol] = value
        return value

    def _compute(self, node: Expr, symbol: str) -> Value:
        if isinstance(node, ast.Literal):
            if node.kind == "bool":
                return bool(node.value)
            return float(node.value)
        if isinstance(node, ast.Feature):
            if node.name in SESSION_FEATURES:
                return self._session_value(node.name)
            return self._feature_value(node.name, symbol)
        if isinstance(node, ast.Param):
            return float(self._bindings[node.name].default)
        if isinstance(node, ast.Unary):
            operand = self._value(node.operand, symbol)
            if node.op == "not":
                return None if operand is None else not operand
            number = _number(operand, "unary -")
            return None if number is None else _finite(-number)
        if isinstance(node, ast.Binary):
            left = self._value(node.left, symbol)
            right = self._value(node.right, symbol)
            return self._binary(node.op, left, right)
        assert isinstance(node, ast.Call)
        return self._call(node, symbol)

    def _feature_value(self, name: str, symbol: str) -> float | None:
        raw = self._rows[symbol][name]
        value = _numeric(raw, f"the bar of symbol {symbol!r}, feature {name!r}")
        return None if value is None else _finite(value)

    def _session_value(self, name: str) -> float | None:
        facts = self._session_facts()
        if name == "time_of_day":
            return facts.time_of_day
        if name == "minutes_since_open":
            return facts.minutes_since_open
        return facts.minutes_to_close

    def _session_facts(self) -> _SessionFacts:
        """The three session features of the step's ``event_time``, computed once."""
        assert self._event_time is not None
        if self._session is not None and self._session[0] == self._event_time:
            return self._session[1]
        assert self._calendar is not None  # refused by __init__ when a session feature is used
        times = np.asarray([self._event_time], dtype=np.int64)
        wall = utc_ns_to_chicago_wall([self._event_time])[0]
        days, on_schedule = session_trade_dates(self._calendar, times, self._bar_seconds)
        since: float | None = None
        to_close: float | None = None
        if bool(on_schedule[0]):
            session = self._calendar.session(dt.date.fromisoformat(str(days[0])))
            since = float((self._event_time - session.open_ns) // _NS_PER_MINUTE)
            to_close = float((session.close_ns - self._event_time) // _NS_PER_MINUTE)
        facts = _SessionFacts(
            time_of_day=float(wall.hour * 60 + wall.minute),
            minutes_since_open=since,
            minutes_to_close=to_close,
        )
        self._session = (self._event_time, facts)
        return facts

    def _binary(self, op: str, left: Value, right: Value) -> Value:
        if op == "and":
            if left is False or right is False:
                return False
            return None if left is None or right is None else True
        if op == "or":
            if left is True or right is True:
                return True
            return None if left is None or right is None else False
        first = _number(left, f"operator {op}")
        second = _number(right, f"operator {op}")
        if first is None or second is None:
            return None
        if op in (">", ">=", "<", "<="):
            return {
                ">": first > second,
                ">=": first >= second,
                "<": first < second,
                "<=": first <= second,
            }[op]
        if op == "+":
            return _finite(first + second)
        if op == "-":
            return _finite(first - second)
        if op == "*":
            return _finite(first * second)
        if second == 0.0:
            return None
        return _finite(first / second)

    def _call(self, node: ast.Call, symbol: str) -> Value:
        name = node.name
        if name == "cs_rank":
            return self._cs_rank(node, symbol)
        if name == "abs":
            child = _number(self._value(node.args[0], symbol), "abs()")
            return None if child is None else _finite(abs(child))
        if name == "sign":
            child = _number(self._value(node.args[0], symbol), "sign()")
            return None if child is None else float((child > 0) - (child < 0))
        if name in {"min", "max"}:
            first = _number(self._value(node.args[0], symbol), f"{name}()")
            second = _number(self._value(node.args[1], symbol), f"{name}()")
            if first is None or second is None:
                return None
            return _finite(min(first, second) if name == "min" else max(first, second))
        if name == "if":
            condition = self._value(node.args[0], symbol)
            # both branches are always evaluated: the vectorized path computes both columns, so
            # their state advances on every row here too
            first = self._value(node.args[1], symbol)
            second = self._value(node.args[2], symbol)
            if condition is None:
                return None
            return first if condition is True else second
        return self._windowed(node, symbol)

    def _windowed(self, node: ast.Call, symbol: str) -> Value:
        name = node.name
        window = self._plans[id(node)].window
        value = _number(self._value(node.args[0], symbol), f"{name}()")
        if name in {"delay", "delta"}:
            state = self._state(node, symbol)
            previous = state.buffer[0] if len(state.buffer) == window else None
            state.buffer.append(value)
            if name == "delay":
                return previous
            if previous is None or value is None:
                return None
            return _finite(value - previous)
        if name == "ema":
            return self._ema(node, symbol, value, window)
        state = self._state(node, symbol)
        state.buffer.append(value)
        if len(state.buffer) < window or any(item is None for item in state.buffer):
            return None
        values = np.asarray(state.buffer, dtype=np.float64)
        if name == "ts_mean":
            return _finite(float(values.mean()))
        if name == "ts_min":
            return _finite(float(values.min()))
        if name == "ts_max":
            return _finite(float(values.max()))
        if name == "ts_std":
            return _finite(_sample_std(values))
        if name == "ts_rank":
            less = int((values < values[-1]).sum())
            equal = int((values == values[-1]).sum())
            rank = less + (equal + 1) / 2.0
            return float((rank - 1.0) / (window - 1.0))
        if name == "ts_zscore":
            std = _sample_std(values)
            if not np.isfinite(std) or std == 0.0:
                return None
            return _finite(float((values[-1] - values.mean()) / std))
        msg = f"{name}() has no incremental evaluation"
        raise CheckpointError(msg)  # pragma: no cover - the table and this dispatch agree

    def _ema(self, node: ast.Call, symbol: str, value: float | None, window: int) -> Value:
        state = self._state(node, symbol)
        if value is None:
            return None  # a null input is null and leaves the state unchanged
        alpha = 2.0 / (window + 1.0)
        if state.seen == 0:
            state.ema = value
        else:
            assert state.ema is not None
            state.ema = alpha * value + (1.0 - alpha) * state.ema
        state.seen += 1
        if state.seen < window:
            return None
        return _finite(state.ema)

    def _cs_rank(self, node: ast.Call, symbol: str) -> float | None:
        """The rank of ``symbol``'s argument across the step's symbols (ADR-0099)."""
        key = id(node)
        if key not in self._cs_values:
            self._rank_cross_section(node)
        return self._cs_values[key][symbol]

    def _rank_cross_section(self, node: ast.Call) -> None:
        """Rank one ``cs_rank`` node's argument over every symbol of the step (once per step)."""
        key = id(node)
        argument = node.args[0]
        values: dict[str, float | None] = {}
        for symbol in self._symbols:
            values[symbol] = _number(self._value(argument, symbol), "cs_rank()")
        members = sorted(symbol for symbol, value in values.items() if value is not None)
        ranks: dict[str, float | None] = dict.fromkeys(values)
        self._cs_counts[key] = len(members)
        self._cs_decision[key] = (
            max(self._available[symbol] for symbol in members) if members else None
        )
        if len(members) >= MIN_CS_MEMBERS:
            normalized = _average_ranks(np.asarray([values[symbol] for symbol in members]))
            for symbol, rank in zip(members, normalized, strict=True):
                ranks[symbol] = float(rank)
        self._cs_values[key] = ranks

    def _step_cross_section(self) -> tuple[dict[str, int | None], int | None]:
        """``decision_at`` per symbol and the step's ``cs_count`` (ADR-0099)."""
        if not self._cs_nodes:
            return dict(self._available), None
        present = sorted(self._cs_decision)
        known = [
            value for value in (self._cs_decision[key] for key in present) if value is not None
        ]
        latest = max(known) if known else None
        return dict.fromkeys(self._symbols, latest), min(self._cs_counts[key] for key in present)

    # ------------------------------------------------------------------------------ state

    def _plan(self, node: Expr) -> _NodePlan:
        return self._plans[id(node)]

    def _state(self, node: Expr, symbol: str) -> _NodeState:
        plan = self._plan(node)
        stream = self._streams[symbol]
        state = stream.nodes.get(plan.index)
        if state is None:
            state = _NodeState(buffer=deque(maxlen=max(plan.window, 1)))
            stream.nodes[plan.index] = state
        return state

    # ------------------------------------------------------------------ snapshot / restore

    def snapshot(self) -> dict[str, object]:
        """The per-stream state, JSON-able: buffers, the EMA value and count, last timestamps.

        It never includes the definition (``compiled_id`` is recorded as an identity, and the
        definition's setup is verified elsewhere): the same snapshot feeds a fresh evaluator built
        for the same ``CompiledSignal``.
        """
        streams: dict[str, object] = {}
        for symbol in sorted(self._streams):
            stream = self._streams[symbol]
            nodes: dict[str, object] = {}
            for index in sorted(stream.nodes):
                state = stream.nodes[index]
                nodes[str(index)] = {
                    "buffer": list(state.buffer),
                    "ema": state.ema,
                    "seen": state.seen,
                }
            streams[symbol] = {
                "last_event_time": stream.last_event_time,
                "last_available_at": stream.last_available_at,
                "nodes": nodes,
            }
        return {"compiled_id": self._signal.compiled_id, "streams": streams}

    def restore(self, state: Mapping[str, object]) -> None:
        """Replace the per-stream state in place; refuses another signal's snapshot.

        Raises ``CheckpointError`` on a snapshot of a different ``compiled_id``, on a node that
        this signal does not keep state for, and on any value of the wrong type.
        """
        compiled = ckpt_field(state, "compiled_id", str)
        if compiled != self._signal.compiled_id:
            msg = (
                f"checkpoint was written for compiled_id {compiled}, but this evaluator runs "
                f"{self._signal.compiled_id}: a snapshot only resumes the definition that wrote it"
            )
            raise CheckpointError(msg)
        streams = field_dict(state, "streams")
        restored: dict[str, _Stream] = {}
        for symbol in sorted(streams):
            raw = streams[symbol]
            if not isinstance(raw, Mapping):
                msg = f"checkpoint stream {symbol!r} must be a mapping, got {type(raw).__name__}"
                raise CheckpointError(msg)
            stream = _Stream(
                last_event_time=_optional_int(raw, "last_event_time", symbol),
                last_available_at=_optional_int(raw, "last_available_at", symbol),
            )
            nodes = raw.get("nodes")
            if not isinstance(nodes, Mapping):
                msg = f"checkpoint stream {symbol!r} has no 'nodes' mapping"
                raise CheckpointError(msg)
            for key in sorted(nodes, key=lambda item: int(str(item))):
                index = _node_index(str(key), symbol)
                plan = _plan_by_index(self._plans, index)
                if plan is None or not (plan.stateful or plan.exponential):
                    msg = (
                        f"checkpoint stream {symbol!r} carries state for node {index}, which is "
                        "not a stateful node of this signal"
                    )
                    raise CheckpointError(msg)
                stream.nodes[index] = _state_from_snapshot(nodes[key], plan, symbol)
            restored[symbol] = stream
        self._streams = restored
        self._values = {}
        self._cs_values = {}
        self._cs_counts = {}
        self._cs_decision = {}
        self._session = None


def _optional_int(raw: Mapping[str, object], key: str, symbol: str) -> int | None:
    """A stream's last timestamp: an int or null (the key must exist)."""
    if key not in raw:
        msg = f"checkpoint stream {symbol!r} is missing field {key!r}"
        raise CheckpointError(msg)
    value = raw[key]
    if value is None:
        return None
    if type(value) is not int:
        msg = (
            f"checkpoint stream {symbol!r} field {key!r} must be an int or null, got "
            f"{type(value).__name__}"
        )
        raise CheckpointError(msg)
    return value


def _node_index(key: str, symbol: str) -> int:
    try:
        index = int(key)
    except ValueError:
        msg = f"checkpoint stream {symbol!r} has a node key {key!r}, not an integer index"
        raise CheckpointError(msg) from None
    if index < 0:
        msg = f"checkpoint stream {symbol!r} has a negative node index {index}"
        raise CheckpointError(msg)
    return index


def _plan_by_index(plans: Mapping[int, _NodePlan], index: int) -> _NodePlan | None:
    for plan in plans.values():
        if plan.index == index:
            return plan
    return None


def _state_from_snapshot(raw: object, plan: _NodePlan, symbol: str) -> _NodeState:
    """One node's state from a snapshot, checked against the plan's window and kind."""
    if not isinstance(raw, Mapping):
        msg = (
            f"checkpoint node {plan.index} of stream {symbol!r} must be a mapping, got "
            f"{type(raw).__name__}"
        )
        raise CheckpointError(msg)
    state = _NodeState(buffer=deque(maxlen=max(plan.window, 1)))
    buffer = raw.get("buffer")
    if not isinstance(buffer, list):
        msg = f"checkpoint node {plan.index} of stream {symbol!r} has no 'buffer' list"
        raise CheckpointError(msg)
    if len(buffer) > max(plan.window, 1):
        msg = (
            f"checkpoint node {plan.index} of stream {symbol!r} holds {len(buffer)} buffered "
            f"values, more than its window of {plan.window}"
        )
        raise CheckpointError(msg)
    for item in buffer:
        if item is not None and (isinstance(item, bool) or not isinstance(item, int | float)):
            msg = (
                f"checkpoint node {plan.index} of stream {symbol!r} buffers "
                f"{type(item).__name__}, not a number or null"
            )
            raise CheckpointError(msg)
        state.buffer.append(None if item is None else float(item))
    ema = raw.get("ema")
    if ema is not None and (isinstance(ema, bool) or not isinstance(ema, int | float)):
        msg = (
            f"checkpoint node {plan.index} of stream {symbol!r} has ema={ema!r}, not a number "
            "or null"
        )
        raise CheckpointError(msg)
    state.ema = None if ema is None else float(ema)
    seen = raw.get("seen", 0)
    if type(seen) is not int or seen < 0:
        msg = (
            f"checkpoint node {plan.index} of stream {symbol!r} has seen={seen!r}, not a "
            "non-negative int"
        )
        raise CheckpointError(msg)
    state.seen = seen
    return state


def _node_plans(expression: Expression, bindings: Mapping[str, FreeParam]) -> dict[int, _NodePlan]:
    """One plan per node: its pre-order index and the state its operator keeps."""
    plans: dict[int, _NodePlan] = {}
    for index, node in enumerate(ast.walk_preorder(expression.root)):
        window = 0
        stateful = False
        exponential = False
        if isinstance(node, ast.Call):
            definition = OPERATORS[node.name]
            if definition.window_args:
                window = int(_window_value(node.args[definition.window_args[0]], bindings))
            stateful = node.name in _WINDOW_PRESERVING or node.name in {"delay", "delta"}
            exponential = node.name == "ema"
        plans[id(node)] = _NodePlan(
            index=index, window=window, stateful=stateful, exponential=exponential
        )
    return plans


def _window_value(node: Expr, bindings: Mapping[str, FreeParam]) -> int:
    if isinstance(node, ast.Literal):
        return int(node.value)
    if isinstance(node, ast.Param):
        return int(bindings[node.name].default)
    msg = f"window argument is {type(node).__name__}, not an int literal or parameter"
    raise CheckpointError(msg)  # pragma: no cover - refused by the type checker before


__all__ = ["IncrementalEvaluator", "StepOutput"]
