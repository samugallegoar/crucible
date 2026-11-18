"""The futures signal bridge: a strategy's decision as signed whole contracts per bar (C3b).

A continuous futures run needs two things this module produces from one strategy: the **target
position** in whole contracts decided at each bar's close (the input of
``crucible.execution.futures_sim.simulate_futures``, ADR-0090) and the per-bar ``on_schedule``
column that stops orders filling in a closed Globex segment (ADR-0091, ADR-0093 decision 5). The
strategy is a declarative ``StrategySpec`` (compiled by ``spec_positions``, so its sides become
+/-1 and ``contracts`` turns them into a size), a ``FuturesSignalFunction`` that returns signed
contracts itself, or a compiled DSL ``CompiledSignal`` (ADR-0098: a condition is long when true, a
score's sign sets the side, and ``contracts`` sizes it).

Two datasets meet here, and the rule is the owner's (ADR-0086, decision 8):

- **fills and P&L always use the unadjusted series** (``price_basis="raw"``), so
  ``execution_ref`` must be unadjusted and is the series ``execution_bars`` comes from;
- **the signal defaults to the ratio-adjusted series** (``signal_input="ratio_adjusted"``), whose
  price *levels* depend on later rolls. Only scale-invariant logic may read it: a spec is checked
  statically (``crucible.strategy_spec.scale``) and empirically, a Python function must declare
  ``scale_invariant = True`` and pass the same empirical check. ``signal_input="unadjusted"`` is the
  explicit escape hatch for level-based logic (``close > 4500``).

The empirical check multiplies open/high/low/close of the signal bars by 16.0 and by 0.0625 --
powers of two, exact in binary floating point, so scale-invariant logic returns bit-identical
decisions -- and refuses if any decided target differs, naming the first bar that does.

Session rules come from ``FuturesSessionPolicy`` evaluated on the CME Globex calendar
(``crucible.data.cme_sessions``), never from the spec's ``session`` block: the futures path decides
on the same schedule the exchange published (ADR-0091). An off-schedule bar (the print in the minute
after a close, before a reopen) takes no decision: its target is the previous bar's.

Timing: everything here is decided at a bar's close from bars up to and including it, and the
simulator lags the target by one bar (it fills at the next eligible bar's open). Nothing reads the
wall clock, so the output is a pure function of the two frames and the parameters.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal, NoReturn, Protocol

import numpy as np
import polars as pl

from crucible.core.errors import ConfigurationError, DataQualityError, InvariantViolation
from crucible.data.cme_sessions import SessionRuleMasks, session_rule_masks, table_summary
from crucible.data.continuous import calendar_for
from crucible.dsl.compile import CONDITION, CompiledSignal
from crucible.strategy_spec.compile import condition_operands, spec_positions
from crucible.strategy_spec.models import (
    ClockTime,
    StrategySpec,
    TimeOfDay,
    check_clock_time,
    parse_condition,
)
from crucible.strategy_spec.scale import assert_scale_invariant

if TYPE_CHECKING:
    from collections.abc import Mapping

    from numpy.typing import NDArray

SignalInput = Literal["ratio_adjusted", "unadjusted"]
"""Which series the signal reads: the ratio-adjusted one (default, scale-invariant logic only) or
the unadjusted one (allowed for level-based logic)."""

ALIGNMENT_COLUMNS = ("event_time", "contract")
"""Columns the two frames must agree on row by row."""

PRICE_COLUMNS = ("open", "high", "low", "close")
"""The prices the empirical scale-invariance check multiplies (volume is never adjusted)."""

EMPIRICAL_FACTORS = (16.0, 0.0625)
"""Powers of two: multiplying a binary float by them is exact, so scale-invariant logic must give
bit-identical decisions."""

_NS_PER_SECOND = 1_000_000_000
_MAX_LISTED = 10


@dataclass(frozen=True, slots=True)
class DatasetRef:
    """What the dataset's manifest says about a series (the run records this, never the data).

    ``price_basis`` is ``"raw"`` for the contract's own traded prices and ``"adjusted"`` for a
    series built from them; ``adjustment`` names the method (``"ratio"`` for the compounded ratio
    adjustment of ADR-0086, ``"none"`` when prices are untouched)."""

    dataset: str
    content_hash: str
    price_basis: Literal["raw", "adjusted"]
    adjustment: str


@dataclass(frozen=True, slots=True)
class FuturesSessionPolicy:
    """The session rules of the futures path, evaluated on the CME Globex calendar (ADR-0091).

    ``flat_by_close``: be flat by the session's close -- the exit is decided at the close of the
    session's penultimate scheduled bar and fills at the next bar's open, so it is flat from that
    close on. ``exit_at`` (``HH:MM`` Chicago, on the trade-date clock) forces a flat from the first
    bar ending at or after it and blocks entries after it. ``entry_window`` (``(start, end)``,
    ``HH:MM``, inclusive, trade-date clock) restricts new positions to bars ending inside it; exits
    and reductions are always allowed. ``allow_unverified_sessions`` admits trade dates whose
    schedule an unsourced window touches (the times are the regime's, unconfirmed): strict by
    default, because a wrong close would move a flat-by-close exit.
    """

    flat_by_close: bool = False
    exit_at: str | None = None
    entry_window: tuple[str, str] | None = None
    allow_unverified_sessions: bool = False

    def __post_init__(self) -> None:
        if self.exit_at is not None:
            check_clock_time(self.exit_at, "FuturesSessionPolicy.exit_at")
        if self.entry_window is not None:
            start, stop = self.entry_window
            check_clock_time(start, "FuturesSessionPolicy.entry_window start")
            check_clock_time(stop, "FuturesSessionPolicy.entry_window end")


class FuturesSignalFunction(Protocol):
    """A Python signal for the futures path.

    ``__call__(bars, params)`` receives a lazy frame of the SIGNAL series (``event_time``,
    ``open``/``high``/``low``/``close``, ``volume``, ``contract``) and must return the columns
    ``ts`` (``Int64``: the bar's ``event_time``) and ``score`` (the signed whole number of
    CONTRACTS decided at that bar's close; +2 is long two, 0 flat). ``scale_invariant`` declares
    whether the score is unchanged when every price is multiplied by a positive constant; it is
    required to be ``True`` to read the ratio-adjusted series (read with ``getattr``, so a plain
    function object simply fails the declaration).
    """

    scale_invariant: bool

    def __call__(self, bars: pl.LazyFrame, params: Mapping[str, object]) -> pl.LazyFrame: ...


@dataclass(frozen=True, slots=True)
class FuturesTargets:
    """What ``futures_targets`` decides.

    ``targets``: ``event_time`` (``Int64``, UTC ns) and ``target`` (``Int64``, signed whole
    contracts decided at that bar's close), one row per execution bar, in order.
    ``on_schedule``: one Boolean per bar, False on a bar outside every scheduled Globex segment;
    pass it to ``simulate_futures`` as the ``bars`` column ``on_schedule`` (ADR-0093).
    ``record``: JSON-ready provenance of the decision (both datasets, the alignment, the
    scale-invariance result, the session calendar and rules).
    """

    targets: pl.DataFrame
    on_schedule: pl.Series
    record: dict[str, object]


def _iso(ns: int) -> str:
    """UTC nanoseconds as ``2024-03-05T14:01:00Z`` (whole seconds; a message, not a computation)."""
    return dt.datetime.fromtimestamp(int(ns) // _NS_PER_SECOND, tz=dt.UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


# --- a. the two datasets -----------------------------------------------------------------------


def _check_inputs(signal_input: str, execution_ref: DatasetRef, signal_ref: DatasetRef) -> None:
    """Refuses a dataset pair that breaks the owner's rule (ADR-0086, decision 8)."""
    if signal_input not in ("ratio_adjusted", "unadjusted"):
        msg = (
            f"signal_input={signal_input!r} is not a signal input; use 'ratio_adjusted' (the "
            "default: the ratio-adjusted series, scale-invariant logic only) or 'unadjusted' (the "
            "contracts' own prices, for level-based logic)"
        )
        raise ConfigurationError(msg)
    if execution_ref.price_basis != "raw":
        msg = (
            f"the execution dataset {execution_ref.dataset} declares price_basis="
            f"{execution_ref.price_basis!r}; fills and P&L are computed on the contracts' own "
            "traded prices, so execution_ref must be the unadjusted continuous series "
            "(price_basis='raw', ADR-0086): pass <root>_..._cont_v3 as execution_ref"
        )
        raise ConfigurationError(msg)
    if signal_input == "ratio_adjusted":
        if signal_ref.price_basis != "adjusted" or signal_ref.adjustment != "ratio":
            msg = (
                f"signal_input='ratio_adjusted' reads the ratio-adjusted series, but "
                f"{signal_ref.dataset} declares price_basis={signal_ref.price_basis!r} and "
                f"adjustment={signal_ref.adjustment!r}; pass the dataset built with the ratio "
                "adjustment (price_basis='adjusted', adjustment='ratio', ADR-0086), or use "
                "signal_input='unadjusted' with the unadjusted series"
            )
            raise ConfigurationError(msg)
    elif signal_ref.price_basis != "raw":
        msg = (
            f"signal_input='unadjusted' reads the contracts' own prices, but {signal_ref.dataset} "
            f"declares price_basis={signal_ref.price_basis!r}; pass the unadjusted continuous "
            "series as signal_ref (normally the same dataset as execution_ref), or use "
            "signal_input='ratio_adjusted' with the ratio-adjusted series"
        )
        raise ConfigurationError(msg)


# --- b. alignment ------------------------------------------------------------------------------


def _check_alignment(execution: pl.DataFrame, signal: pl.DataFrame) -> None:
    """Refuses two frames that are not the same series row by row (naming the first bad row)."""
    for name, frame in (("execution_bars", execution), ("signal_bars", signal)):
        missing = [c for c in ALIGNMENT_COLUMNS if c not in frame.columns]
        if missing:
            msg = (
                f"{name} lacks {missing}; a continuous futures series carries "
                f"{list(ALIGNMENT_COLUMNS)} (CONTINUOUS_BAR_SCHEMA): read the continuous dataset "
                "the manifest names"
            )
            raise ConfigurationError(msg)
    if execution.height != signal.height:
        msg = (
            f"execution_bars has {execution.height} rows but signal_bars has {signal.height}; the "
            "signal and the execution series must be the same series (same rows), so align them "
            "before calling futures_targets (same window and interval)"
        )
        raise ConfigurationError(msg)
    if execution.height == 0:
        msg = (
            "execution_bars is empty: a futures run needs at least one bar to decide on; trim the "
            "window after loading the continuous dataset, not before"
        )
        raise ConfigurationError(msg)
    for name, frame in (("execution_bars", execution), ("signal_bars", signal)):
        times = frame.get_column("event_time").to_numpy()
        steps = np.diff(times)
        bad = np.flatnonzero(steps <= 0)
        if bad.size:
            i = int(bad[0])
            msg = (
                f"{name}.event_time is not strictly increasing at row {i}: {_iso(times[i])} is "
                f"followed by {_iso(times[i + 1])}; sort by event_time and drop duplicate bars "
                "(one row per bar, oldest first)"
            )
            raise ConfigurationError(msg)
    exec_times = execution.get_column("event_time").to_numpy()
    sig_times = signal.get_column("event_time").to_numpy()
    bad = np.flatnonzero(exec_times != sig_times)
    if bad.size:
        i = int(bad[0])
        msg = (
            f"the signal and execution series disagree at row {i}: execution_bars has "
            f"event_time={_iso(exec_times[i])} ({int(exec_times[i])} ns) and signal_bars has "
            f"{_iso(sig_times[i])} ({int(sig_times[i])} ns); both must come from the same build of "
            "the continuous series (same rows, same order -- the adjusted series has the same "
            "timestamps, ADR-0086)"
        )
        raise ConfigurationError(msg)
    exec_contracts = execution.get_column("contract")
    sig_contracts = signal.get_column("contract")
    bad = np.flatnonzero((exec_contracts != sig_contracts).to_numpy())
    if bad.size:
        i = int(bad[0])
        msg = (
            f"the signal and execution series hold different contracts at row {i} (event_time="
            f"{_iso(exec_times[i])}): execution_bars has {exec_contracts[i]!r} and signal_bars has "
            f"{sig_contracts[i]!r}; the ratio-adjusted series is the same rows and rolls as the "
            "unadjusted one, so rebuild both with the same continuous build (crucible data build)"
        )
        raise ConfigurationError(msg)


# --- c. what the futures path refuses -----------------------------------------------------------


def _time_paths(spec: StrategySpec) -> list[str]:
    """The rule paths (``entry.long``, ``exit.short.all[0]``, ...) that read ``time``."""
    paths: list[str] = []
    for block, rules in (("entry", spec.entry), ("exit", spec.exit)):
        for side in ("long", "short"):
            condition = getattr(rules, side)
            if condition is None:
                continue
            path = f"{block}.{side}"
            node = parse_condition(condition, path)
            if any(isinstance(o, TimeOfDay | ClockTime) for o in condition_operands(node)):
                paths.append(path)
    return paths


def _refuse_spec_contracts(contracts: object) -> NoReturn:
    """The spec path sizes from ``contracts``; anything but a whole number >= 1 is a mistake."""
    msg = (
        f"contracts={contracts!r}: a strategy spec decides a side (+1 long, -1 short) and the "
        "bridge turns it into a size, so contracts must be a whole number of contracts >= 1 "
        "(e.g. contracts=1)"
    )
    raise ConfigurationError(msg)


def _check_spec(spec: StrategySpec, contracts: object) -> int:
    """Refuses a spec the futures path cannot size or exit honestly; returns the contracts."""
    risk = spec.risk
    percentage = [
        name for name in ("stop_loss_pct", "take_profit_pct") if getattr(risk, name) is not None
    ]
    if percentage:
        fields = ", ".join(f"risk.{name} ({getattr(risk, name):g}%)" for name in percentage)
        msg = (
            f"the spec sets {fields}: percentage stops/targets are not accepted in the futures "
            "path; use the execution policy's stop_ticks / target_ticks, ADR-0093 (they are whole "
            "ticks measured from each lot's fill). Remove the percentage from the spec"
        )
        raise ConfigurationError(msg)
    if risk.max_holding_bars is not None:
        msg = (
            f"the spec sets risk.max_holding_bars ({risk.max_holding_bars} bars): a bar-count exit "
            "is not yet defined against the futures path's per-lot bracket exits (ADR-0093). "
            "Remove it and let the strategy's target or the brackets close the position"
        )
        raise ConfigurationError(msg)
    if "stop_fill" in risk.model_fields_set:
        msg = (
            f"the spec sets risk.stop_fill ({risk.stop_fill!r}): how a bracket fills is the "
            "execution policy's decision in the futures path (ADR-0093), not the spec's. Remove "
            "risk.stop_fill from the spec"
        )
        raise ConfigurationError(msg)
    if "sizing" in spec.model_fields_set:
        msg = (
            f"the spec sets sizing ({spec.sizing.type}): in the futures path the position size is "
            "a whole number of contracts, so it comes from the contracts argument, not from "
            "sizing. Remove the sizing block and pass contracts=<n>"
        )
        raise ConfigurationError(msg)
    paths = _time_paths(spec)
    if paths:
        msg = (
            f"the spec decides on `time` (bar end, exchange clock) in {', '.join(paths)}: the "
            "futures path takes its clock rules from FuturesSessionPolicy, evaluated on the CME "
            "Globex calendar (ADR-0091), so a spec-level time rule is refused. Remove the `time` "
            "comparison and pass session=FuturesSessionPolicy(exit_at=..., entry_window=...)"
        )
        raise ConfigurationError(msg)
    if spec.session is not None:
        msg = (
            "the spec sets a session block: the futures path's session rules come from "
            "FuturesSessionPolicy and are evaluated on the CME Globex calendar (ADR-0091), so a "
            "spec-level session block is refused (it would be evaluated on the equity calendar). "
            "Remove spec.session and pass session=FuturesSessionPolicy(flat_by_close=..., "
            "exit_at=..., entry_window=...)"
        )
        raise ConfigurationError(msg)
    if isinstance(contracts, bool) or not isinstance(contracts, int):
        _refuse_spec_contracts(contracts)
    if contracts < 1:
        _refuse_spec_contracts(contracts)
    return contracts


def _check_expression_contracts(expression: CompiledSignal, contracts: object) -> int:
    """An expression decides a side; ``contracts`` sizes it (a whole number of contracts)."""
    if isinstance(contracts, bool) or not isinstance(contracts, int) or contracts < 1:
        msg = (
            f"contracts={contracts!r}: the expression {expression.canonical_text!r} decides a "
            "side (+1 long, -1 short, 0 flat) and the bridge turns it into a size, so contracts "
            "must be a whole number of contracts >= 1 (e.g. contracts=1)"
        )
        raise ConfigurationError(msg)
    return contracts


def _check_expression_input(expression: CompiledSignal, signal_input: str) -> None:
    """Refuse an expression compiled for the other input: its scale guarantee would not apply."""
    if expression.signal_input != signal_input:
        msg = (
            f"the compiled expression {expression.compiled_id} was compiled for "
            f"signal_input={expression.signal_input!r}, but this run reads {signal_input!r}: its "
            "static scale rule belongs to the role it was compiled for. Recompile it with "
            "crucible.dsl.compile.compile_expression(..., signal_input=signal_input), or fix the "
            "run's signal.input"
        )
        raise ConfigurationError(msg)


def _expression_sides(value: pl.Series, root_kind: str) -> NDArray[np.int64]:
    """The signed side per bar: a condition is 1 where true, a score takes its sign; null is 0.

    A null value or the warm-up decides flat, never "hold the previous target": a position
    without a current signal would be one the strategy did not decide (ADR-0098).
    """
    boolean = value.dtype == pl.Boolean
    if boolean != (root_kind == CONDITION):
        msg = (
            f"the compiled expression's root_kind is {root_kind!r} but its evaluation returned "
            f"{value.dtype}; a condition must evaluate to Boolean and a score to Float64"
        )
        raise InvariantViolation(msg)
    if boolean:
        return value.cast(pl.Int64).fill_null(0).to_numpy().astype(np.int64)
    scores = value.to_numpy().astype(np.float64)
    sides = np.zeros(scores.shape, dtype=np.int64)
    finite = np.isfinite(scores)
    sides[finite & (scores > 0.0)] = 1
    sides[finite & (scores < 0.0)] = -1
    return sides


def _check_function_contracts(contracts: object) -> None:
    """A ``FuturesSignalFunction`` decides the size itself, so ``contracts`` is a contradiction."""
    if contracts is not None:
        msg = (
            f"contracts={contracts!r}: a FuturesSignalFunction returns signed whole CONTRACTS as "
            "its score, so it already decides the size. Pass contracts=None and let the score "
            "set the position"
        )
        raise ConfigurationError(msg)


# --- f. the CME session rules ------------------------------------------------------------------


def _masks(
    root: str,
    event_times: NDArray[np.int64],
    policy: FuturesSessionPolicy,
    bar_seconds: int,
) -> SessionRuleMasks:
    """The CME calendar's per-bar masks, refusing what would make an exit unhonest."""
    if (isinstance(bar_seconds, bool) or not isinstance(bar_seconds, int)) or bar_seconds < 1:
        msg = (
            f"bar_seconds={bar_seconds!r} must be a whole number of seconds >= 1 (the bar length "
            "of the series, e.g. 60 for minute bars)"
        )
        raise ConfigurationError(msg)
    masks = session_rule_masks(
        calendar_for(root),
        event_times,
        bar_seconds=bar_seconds,
        flat_by_close=policy.flat_by_close,
        exit_at=policy.exit_at,
        entry_window=policy.entry_window,
    )
    if policy.flat_by_close and masks.missing_final:
        listed = ", ".join(day.isoformat() for day in masks.missing_final[:_MAX_LISTED])
        extra = len(masks.missing_final) - _MAX_LISTED
        more = "" if extra <= 0 else f" (+{extra} more)"
        msg = (
            "flat_by_close is set but the final scheduled bar is missing for "
            f"{len(masks.missing_final)} {root} trade date(s): {listed}{more}. The flat-by-close "
            "exit would have to fill at the final scheduled bar's open, and there is no such bar, "
            "so the exit cannot fill inside the session; trim the window or fix the data"
        )
        raise DataQualityError(msg)
    if masks.unverified and not policy.allow_unverified_sessions:
        listed = ", ".join(day.isoformat() for day in masks.unverified[:_MAX_LISTED])
        extra = len(masks.unverified) - _MAX_LISTED
        more = "" if extra <= 0 else f" (+{extra} more)"
        msg = (
            f"{len(masks.unverified)} {root} trade date(s) touch a window whose CME schedule no "
            f"transcribed source covers: {listed}{more}. Their session times are the regime's, "
            "unconfirmed, so the session rules (and a flat-by-close exit) would run on a guess "
            "(ADR-0091); pass session=FuturesSessionPolicy(allow_unverified_sessions=True) to "
            "accept them, or trim the window"
        )
        raise DataQualityError(msg)
    return masks


# --- decisions ---------------------------------------------------------------------------------


def _python_scores(
    bars: pl.DataFrame,
    strategy: FuturesSignalFunction,
    params: Mapping[str, object],
) -> NDArray[np.int64]:
    """The function's signed contract score for every bar of ``bars``, aligned on ``ts``."""
    name = getattr(strategy, "__name__", type(strategy).__name__)
    out = strategy(bars.lazy(), params).collect()
    missing = [c for c in ("ts", "score") if c not in out.columns]
    if missing:
        msg = (
            f"the signal function {name} returned a frame without {missing}; it must return ts "
            "(Int64, the bar's event_time) and score (signed whole contracts), one row per bar"
        )
        raise ConfigurationError(msg)
    schema = out.schema
    if schema["ts"] != pl.Int64:
        msg = (
            f"the signal function {name} returned ts of type {schema['ts']}; ts must be Int64 UTC "
            "nanoseconds, the bar's event_time (do not convert to a date or a float)"
        )
        raise ConfigurationError(msg)
    if not schema["score"].is_numeric():
        msg = (
            f"the signal function {name} returned score of type {schema['score']}; score is a "
            "signed whole number of contracts, so it must be numeric (+1, 0, -2)"
        )
        raise ConfigurationError(msg)
    frame = out.select(pl.col("ts").cast(pl.Int64), pl.col("score").cast(pl.Float64))
    unique = frame.get_column("ts").n_unique()
    if unique != frame.height:
        repeated = frame.get_column("ts").filter(frame.get_column("ts").is_duplicated())[0]
        msg = (
            f"the signal function {name} returned more than one score for ts={_iso(int(repeated))} "
            f"({int(repeated)} ns); return exactly one row per bar"
        )
        raise ConfigurationError(msg)
    empty = frame.filter(pl.col("score").is_null())
    if empty.height:
        ts = int(empty.get_column("ts")[0])
        msg = (
            f"the signal function {name} returned a null score for ts={_iso(ts)} ({ts} ns); a bar "
            "must decide a position (0 is flat), so return 0 instead of null"
        )
        raise ConfigurationError(msg)
    joined = pl.DataFrame({"event_time": bars.get_column("event_time")}).join(
        frame,
        left_on="event_time",
        right_on="ts",
        how="left",
        maintain_order="left",
    )
    absent = joined.filter(pl.col("score").is_null())
    if absent.height:
        ts = int(absent.get_column("event_time")[0])
        msg = (
            f"the signal function {name} returned no score for the bar ending {_iso(ts)} "
            f"({ts} ns), which is an execution bar; return a score for every bar of the series "
            "(0 when flat), keyed on ts = event_time"
        )
        raise ConfigurationError(msg)
    values = joined.get_column("score").to_numpy()
    finite = np.isfinite(values)
    if not bool(finite.all()):
        i = int(np.flatnonzero(~finite)[0])
        ts = int(joined.get_column("event_time")[i])
        msg = (
            f"the signal function {name} returned score={float(values[i]):g} for "
            f"ts={_iso(ts)} ({ts} ns); a score is a finite signed whole number of contracts"
        )
        raise ConfigurationError(msg)
    whole = values == np.rint(values)
    if not bool(whole.all()):
        i = int(np.flatnonzero(~whole)[0])
        ts = int(joined.get_column("event_time")[i])
        msg = (
            f"the signal function {name} returned score={float(values[i]):g} for "
            f"ts={_iso(ts)} ({ts} ns), which is not a whole number of contracts; the futures "
            "path trades whole contracts, so decide the count yourself (score=1, 2, -1, 0) rather "
            "than a fractional size"
        )
        raise ConfigurationError(msg)
    return np.rint(values).astype(np.int64)


def _apply_session(desired: NDArray[np.int64], masks: SessionRuleMasks) -> NDArray[np.int64]:
    """The decided targets after the session rules, bar by bar (``held`` = the previous target).

    Off-schedule bars take no decision (the segment is closed), ``force_flat`` makes the target 0,
    and outside the entry window only a reduction toward 0 (or 0 itself) is allowed -- an opening,
    flipping or enlarging target keeps the position held.
    """
    out = np.zeros(len(desired), dtype=np.int64)
    held = 0
    for i in range(len(desired)):
        if not bool(masks.on_schedule[i]):
            out[i] = held
            continue
        want = int(desired[i])
        if bool(masks.force_flat[i]):
            out[i] = 0
        elif not bool(masks.entry_ok[i]):
            reduction = want == 0 or (want * held > 0 and abs(want) < abs(held))
            out[i] = want if reduction else held
        else:
            out[i] = want
        held = out[i]
    return out


def _scaled(bars: pl.DataFrame, factor: float) -> pl.DataFrame:
    """``bars`` with every price multiplied by ``factor`` (volume and contract untouched)."""
    return bars.with_columns([(pl.col(c) * factor).alias(c) for c in PRICE_COLUMNS])


def _first_difference(a: NDArray[np.int64], b: NDArray[np.int64]) -> int | None:
    bad = np.flatnonzero(a != b)
    return int(bad[0]) if bad.size else None


def _policy_record(policy: FuturesSessionPolicy) -> dict[str, object]:
    window = list(policy.entry_window) if policy.entry_window is not None else None
    return {
        "flat_by_close": policy.flat_by_close,
        "exit_at": policy.exit_at,
        "entry_window": window,
        "allow_unverified_sessions": policy.allow_unverified_sessions,
    }


def futures_targets(
    *,
    root: str,
    execution_bars: pl.DataFrame,
    signal_bars: pl.DataFrame,
    execution_ref: DatasetRef,
    signal_ref: DatasetRef,
    strategy: StrategySpec | FuturesSignalFunction | CompiledSignal,
    contracts: int | None,
    signal_input: SignalInput = "ratio_adjusted",
    session: FuturesSessionPolicy | None = None,
    params: Mapping[str, object] | None = None,
    bar_seconds: int = 60,
) -> FuturesTargets:
    """Decide signed whole-contract targets for one continuous futures series (C3b).

    ``root``: the CME root whose calendar governs the sessions (``ES``, ``NQ``, ...).
    ``execution_bars``: the UNADJUSTED continuous series (``CONTINUOUS_BAR_SCHEMA``) the fills and
    P&L come from; ``signal_bars``: the series the strategy reads (the ratio-adjusted one, or the
    unadjusted one), the same rows. ``execution_ref``/``signal_ref``: what each dataset's manifest
    says (recorded, and checked against ``signal_input``). ``strategy``: a ``StrategySpec`` or a
    compiled DSL ``CompiledSignal`` (both sized by ``contracts``, a whole number >= 1) or a
    ``FuturesSignalFunction`` (``contracts=None``; its score is the size). ``params``: forwarded to
    a ``FuturesSignalFunction`` (an expression's ``$`` parameters are bound at compile time).
    ``bar_seconds``: the bar length of the series (60 for minute bars), used to place bars in the
    schedule.

    Units: prices in the series' own points, targets in contracts (``Int64``), times UTC ns.
    Timing: every target is decided at that bar's close from bars up to and including it.
    Pessimism: an off-schedule bar decides nothing, a bar outside the entry window may only
    reduce, and a flat-by-close exit needs the final scheduled bar (refused when it is missing).
    """
    policy = session if session is not None else FuturesSessionPolicy()
    _check_inputs(signal_input, execution_ref, signal_ref)
    _check_alignment(execution_bars, signal_bars)
    spec: StrategySpec | None = None
    function: FuturesSignalFunction | None = None
    expression: CompiledSignal | None = None
    size: int | None = None
    if isinstance(strategy, CompiledSignal):
        expression = strategy
        _check_expression_input(expression, signal_input)
        size = _check_expression_contracts(expression, contracts)
    elif isinstance(strategy, StrategySpec):
        spec = strategy
        size = _check_spec(spec, contracts)
    else:
        candidate: object = strategy
        if not callable(candidate):
            msg = (
                f"strategy={strategy!r} is neither a StrategySpec, a compiled DSL CompiledSignal "
                "nor a callable FuturesSignalFunction; pass a spec (crucible strategy spec), a "
                "compile_expression(...) result, or a function with __call__(bars, params) -> "
                "LazyFrame(ts, score) and scale_invariant"
            )
            raise ConfigurationError(msg)
        function = strategy
        _check_function_contracts(contracts)
    event_times = execution_bars.get_column("event_time").to_numpy()
    masks = _masks(root, event_times, policy, bar_seconds)
    on_schedule = np.asarray(masks.on_schedule, dtype=np.bool_)

    if signal_input == "unadjusted":
        declared: bool | None = None
        static = "not_applicable"
        factors: tuple[float, ...] = ()
    elif expression is not None:
        # the compile step refused a score of non-zero price degree: static, by typing
        declared = None
        static = "typed"
        factors = EMPIRICAL_FACTORS
    else:
        if spec is not None:
            assert_scale_invariant(spec, what=f"the spec's signal on {signal_ref.dataset}")
            declared = None
        else:
            assert function is not None
            declared = getattr(function, "scale_invariant", False) is True
            if not declared:
                name = getattr(function, "__name__", type(function).__name__)
                msg = (
                    f"the signal function {name} does not declare scale_invariant = True, and "
                    f"signal_input='ratio_adjusted' reads {signal_ref.dataset}, whose price levels "
                    "depend on later rolls (ADR-0086, decision 8). Declare scale_invariant = True "
                    "on the function (and make sure the score really is unchanged when every price "
                    "is multiplied by a constant), or pass signal_input='unadjusted' with the "
                    "unadjusted series"
                )
                raise ConfigurationError(msg)
        static = "passed"
        factors = EMPIRICAL_FACTORS

    def decide(bars: pl.DataFrame) -> NDArray[np.int64]:
        if expression is not None:
            assert size is not None
            decided_bars = expression.evaluate(
                bars, calendar=calendar_for(root), bar_seconds=bar_seconds
            )
            sides = _expression_sides(decided_bars.get_column("value"), expression.root_kind)
            return _apply_session(sides * size, masks)
        if spec is not None:
            assert size is not None
            sides = spec_positions(
                spec,
                bars,
                force_flat=masks.force_flat,
                entry_ok=masks.entry_ok,
                frozen=~on_schedule,
            )
            return sides * size
        assert function is not None
        scores = _python_scores(bars, function, params if params is not None else {})
        return _apply_session(scores, masks)

    decided = decide(signal_bars)
    for factor in factors:
        other = decide(_scaled(signal_bars, factor))
        i = _first_difference(decided, other)
        if i is not None:
            ts = int(signal_bars.get_column("event_time")[i])
            msg = (
                f"the signal is not scale invariant: multiplying the signal series "
                f"{signal_ref.dataset} by {factor:g} changes the decided target at "
                f"{_iso(ts)} ({ts} ns) from {int(decided[i])} to {int(other[i])} contracts, which "
                "would also change with every later roll (ADR-0086, decision 8). Compare prices "
                "with prices (close > sma(20)), or pass signal_input='unadjusted' with the "
                "unadjusted series"
            )
            raise ConfigurationError(msg)

    strategy_kind = "dsl" if expression is not None else "spec" if spec is not None else "python"
    record: dict[str, object] = {
        "root": root.upper(),
        "strategy_kind": strategy_kind,
        "signal_input": signal_input,
        "signal_dataset": dict(asdict(signal_ref)),
        "execution_dataset": dict(asdict(execution_ref)),
        "alignment": {
            "bars": int(execution_bars.height),
            "first": _iso(int(event_times[0])),
            "last": _iso(int(event_times[-1])),
        },
        "scale_invariance": {
            "static": static,
            "declared": declared,
            "empirical_factors": list(factors),
            "result": "not_applicable" if signal_input == "unadjusted" else "identical",
        },
        "session_calendar": table_summary(calendar_for(root).table),
        "session_rules": _policy_record(policy),
        "off_schedule_bars": int(masks.off_schedule),
        "unverified_sessions": [day.isoformat() for day in masks.unverified],
        "contracts": contracts,
    }
    if expression is not None:
        record["expression"] = expression.describe()
        record["availability"] = {
            "column": "available_at",
            "result": "passed",
            "checks": [
                "available_at >= event_time",
                "available_at does not decrease within a stream",
                "available_at - event_time <= one bar",
            ],
        }
    targets = pl.DataFrame(
        {
            "event_time": execution_bars.get_column("event_time"),
            "target": decided,
        },
        schema={"event_time": pl.Int64(), "target": pl.Int64()},
    )
    return FuturesTargets(
        targets=targets,
        on_schedule=pl.Series("on_schedule", on_schedule, dtype=pl.Boolean),
        record=record,
    )


__all__ = [
    "ALIGNMENT_COLUMNS",
    "EMPIRICAL_FACTORS",
    "PRICE_COLUMNS",
    "DatasetRef",
    "FuturesSessionPolicy",
    "FuturesSignalFunction",
    "FuturesTargets",
    "SignalInput",
    "futures_targets",
]
