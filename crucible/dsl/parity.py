"""Parity between the vectorized and the incremental evaluator, row by row (ADR-0099).

One ``CompiledSignal`` is evaluated twice on the same bars: once by
:meth:`crucible.dsl.compile.CompiledSignal.evaluate` (Polars, whole frame) and once by
:class:`crucible.dsl.incremental.IncrementalEvaluator` (step by step, one decision timestamp at a
time). :func:`parity_report` compares the two series and :func:`assert_parity` refuses the first
disagreement; a live run can use the second, and the tests prove it decides like the backtest.

**The tolerance.** Nulls and booleans must match exactly. Numeric values must match within a
relative tolerance: ``|a - b| <= rel_tol * max(1, |a|)`` (the ``max(1, ...)`` keeps a value near
zero from demanding an absolute error it cannot express). Bitwise equality is deliberately **not**
claimed: Polars aggregates a rolling window from its own columnar accumulators while the
incremental evaluator sums a small buffer, so the two round differently in the last bits. Forcing
one shared slow summation would cost the vectorized path orders of magnitude on years of minute
bars (ADR-0099 §4). Decision timestamps must match exactly.

Nothing here reads the wall clock or a random generator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import polars as pl

from crucible.core.errors import ConfigurationError, InvariantViolation
from crucible.dsl.compile import CONDITION
from crucible.dsl.incremental import IncrementalEvaluator
from crucible.dsl.types import SESSION_FEATURES

if TYPE_CHECKING:
    from crucible.data.cme_sessions import SessionCalendar
    from crucible.dsl.compile import CompiledSignal

MAX_REPORTED: Final[int] = 100
"""How many mismatches of each kind a report keeps (the first ones in time order)."""


@dataclass(frozen=True, slots=True)
class ParityMismatch:
    """One disagreement between the two evaluators at one ``(symbol, event_time)``."""

    kind: str
    """``"null"``, ``"bool"``, ``"value"`` or ``"decision"``."""

    symbol: str | None
    """The stream the row belongs to (``""`` for a frame without a ``symbol`` column)."""

    event_time: int
    """The decision timestamp of the bar, UTC ns."""

    vectorized: object
    """What the vectorized evaluator returned (a value, or a decision timestamp)."""

    incremental: object
    """What the incremental evaluator returned for the same row."""


@dataclass(frozen=True, slots=True)
class ParityReport:
    """The result of comparing both evaluators over one frame."""

    rows: int
    """How many rows were compared (one per frame row)."""

    null_mismatches: tuple[ParityMismatch, ...]
    """Rows where exactly one evaluator produced a null."""

    bool_mismatches: tuple[ParityMismatch, ...]
    """Rows of a condition whose boolean value differs."""

    value_mismatches: tuple[ParityMismatch, ...]
    """Rows of a score whose values differ by more than the tolerance."""

    sign_mismatches: tuple[ParityMismatch, ...]
    """Rows of a score whose **sign** differs, even inside the tolerance: a side would flip."""

    decision_mismatches: tuple[ParityMismatch, ...]
    """Rows whose ``decision_at`` differs (``cs_rank`` publishes the universe's latest one)."""

    max_abs_diff: float
    """The largest absolute difference between two non-null scores (0.0 when none)."""

    max_rel_diff: float
    """The same difference relative to ``max(1, |vectorized|)`` (0.0 when none)."""

    @property
    def matches(self) -> bool:
        """Whether every row agrees (exact for nulls, booleans and timestamps)."""
        return not (
            self.null_mismatches
            or self.bool_mismatches
            or self.value_mismatches
            or self.sign_mismatches
            or self.decision_mismatches
        )

    @property
    def first_mismatch(self) -> ParityMismatch | None:
        """The earliest disagreement by ``(event_time, symbol)``, or ``None``."""
        found = (
            *self.null_mismatches,
            *self.bool_mismatches,
            *self.value_mismatches,
            *self.sign_mismatches,
            *self.decision_mismatches,
        )
        if not found:
            return None
        return min(found, key=lambda hit: (hit.event_time, hit.symbol or ""))


def _require_rel_tol(rel_tol: float) -> float:
    value = float(rel_tol)
    if not math.isfinite(value) or value <= 0.0:
        msg = f"rel_tol={rel_tol!r} must be a positive finite number, e.g. 1e-9"
        raise ConfigurationError(msg)
    return value


def parity_report(
    signal: CompiledSignal,
    frame: pl.DataFrame,
    *,
    calendar: SessionCalendar | None = None,
    bar_seconds: int = 60,
    rel_tol: float = 1e-9,
) -> ParityReport:
    """Evaluate ``signal`` both ways on ``frame`` and compare the results row by row.

    ``frame``: the bars, as :meth:`CompiledSignal.evaluate` takes them (a ``symbol`` column makes
    it a panel; the steps are the frame's distinct ``event_time`` values, ascending). ``rel_tol``:
    the relative tolerance for scores. Returns the :class:`ParityReport`; it never raises on a
    disagreement (:func:`assert_parity` does).
    """
    tolerance = _require_rel_tol(rel_tol)
    evaluated = signal.evaluate(frame, calendar=calendar, bar_seconds=bar_seconds)
    evaluator = IncrementalEvaluator(signal, calendar=calendar, bar_seconds=bar_seconds)
    features = tuple(name for name in signal.features if name not in SESSION_FEATURES)
    for name in features:
        if name not in frame.columns:
            msg = (
                f"the frame has no {name!r} column, which the signal reads: pass the bars the "
                "signal's definition needs"
            )
            raise ConfigurationError(msg)
    times = [int(value) for value in frame.get_column("event_time").to_list()]
    symbols: list[str] = (
        [str(value) for value in frame.get_column("symbol").to_list()]
        if "symbol" in frame.columns
        else [""] * frame.height
    )
    feature_values: dict[str, list[float | int | None]] = {
        name: frame.get_column(name).to_list() for name in features
    }
    available = [int(value) for value in frame.get_column("available_at").to_list()]
    values = evaluated.get_column("value").to_list()
    decisions = evaluated.get_column("decision_at").to_list()
    condition = signal.root_kind == CONDITION
    nulls: list[ParityMismatch] = []
    booleans: list[ParityMismatch] = []
    numbers: list[ParityMismatch] = []
    signs: list[ParityMismatch] = []
    decision_hits: list[ParityMismatch] = []
    max_abs = 0.0
    max_rel = 0.0
    by_time: dict[int, list[int]] = {}
    for index, event_time in enumerate(times):
        by_time.setdefault(event_time, []).append(index)
    for event_time in sorted(by_time):
        rows: dict[str, dict[str, float | int | None]] = {}
        for index in by_time[event_time]:
            row: dict[str, float | int | None] = {
                name: feature_values[name][index] for name in features
            }
            row["available_at"] = available[index]
            rows[symbols[index]] = row
        outputs = evaluator.step(event_time, rows)
        for index in by_time[event_time]:
            symbol = symbols[index]
            output = outputs[symbol]
            expected = values[index]
            actual = output.value
            if (expected is None) != (actual is None):
                nulls.append(ParityMismatch("null", symbol, event_time, expected, actual))
            elif expected is not None and actual is not None:
                if condition:
                    if bool(expected) != bool(actual):
                        booleans.append(
                            ParityMismatch("bool", symbol, event_time, expected, actual)
                        )
                else:
                    first = float(expected)
                    second = float(actual)
                    difference = abs(first - second)
                    relative = difference / max(1.0, abs(first))
                    max_abs = max(max_abs, difference)
                    max_rel = max(max_rel, relative)
                    if difference > tolerance * max(1.0, abs(first)):
                        numbers.append(
                            ParityMismatch("value", symbol, event_time, expected, actual)
                        )
                    if (first > 0) - (first < 0) != (second > 0) - (second < 0):
                        signs.append(ParityMismatch("sign", symbol, event_time, expected, actual))
            if output.decision_at != decisions[index]:
                decision_hits.append(
                    ParityMismatch(
                        "decision", symbol, event_time, decisions[index], output.decision_at
                    )
                )
    return ParityReport(
        rows=frame.height,
        null_mismatches=tuple(nulls[:MAX_REPORTED]),
        bool_mismatches=tuple(booleans[:MAX_REPORTED]),
        value_mismatches=tuple(numbers[:MAX_REPORTED]),
        sign_mismatches=tuple(signs[:MAX_REPORTED]),
        decision_mismatches=tuple(decision_hits[:MAX_REPORTED]),
        max_abs_diff=max_abs,
        max_rel_diff=max_rel,
    )


def assert_parity(
    signal: CompiledSignal,
    frame: pl.DataFrame,
    *,
    calendar: SessionCalendar | None = None,
    bar_seconds: int = 60,
    rel_tol: float = 1e-9,
) -> ParityReport:
    """Like :func:`parity_report`, and raise ``InvariantViolation`` on the first disagreement.

    The message names the first mismatching ``(symbol, event_time)``, both values and what to
    check: a null, boolean or timestamp difference is a bug in the incremental state (or in the
    availability checks), never a rounding one.
    """
    report = parity_report(
        signal, frame, calendar=calendar, bar_seconds=bar_seconds, rel_tol=rel_tol
    )
    first = report.first_mismatch
    if first is not None:
        msg = (
            f"vectorized and incremental evaluation disagree at (symbol={first.symbol!r}, "
            f"event_time={first.event_time}): {first.kind} mismatch, vectorized "
            f"{first.vectorized!r} vs incremental {first.incremental!r}. Nulls, booleans and "
            "decision timestamps must match exactly; a numeric difference beyond "
            f"rel_tol={rel_tol:g} means the incremental state diverged"
        )
        raise InvariantViolation(msg)
    return report


__all__ = ["ParityMismatch", "ParityReport", "assert_parity", "parity_report"]
