"""Futures execution simulator in contracts and dollars (Fathom C3, ADR-0090).

Takes a signed whole-contract target per bar of one continuous futures series and simulates how
it would have traded: fills at the next eligible bar's open (or, declared, at the signal bar's
close), costs per contract per side in ticks and dollars, stop/target brackets inside the bar, and
every roll as two causal trades on raw contract prices. Returns per-bar realized and unrealized P&L,
costs, balance and equity in USD, plus the fills and the rolls. Prop-firm rules are not here: they
read this output (milestone C7).

Arithmetic is exact: prices become integer ticks (a price off the grid is refused, so an adjusted
series cannot be an execution price), money is integer micro-dollars, returned as Decimal(38, 6).

Timing: ``event_time`` is a bar's close (UTC ns), its open is ``event_time - bar_seconds``. A target
decided at bar t's close trades at t+1's open at the earliest; brackets read only the bar they act
on; a causal roll trades only at or after its decision (the end of the deciding session).
Brackets are per lot: every lot a signal fill opens carries its own stop and target, measured
from its own fill price, and a roll that keeps the position shifts every lot's levels by the
executed roll spread. A signal reduction closes lots FIFO and leaves the survivor's levels alone.
Pessimism: if any lot's stop is touched in a bar, only the touched stops fill in that bar and no
target fills until a later bar; a stop that gapped fills at the open; a target needs a trade
through it and never fills at a better gap price. A bar flagged off schedule (ADR-0091) cannot
execute anything: no signal fill and no bracket exit.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

import numpy as np
import polars as pl

from crucible.core.errors import ConfigurationError, DataQualityError, InvariantViolation
from crucible.core.types import NS_PER_S
from crucible.data.futures_specs import SPEC_TABLE_VERSION, spec_table_hash

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from crucible.data.futures_specs import FuturesContractSpec

SIMULATOR_VERSION = "2"
FillTiming = Literal["next_eligible_bar_open", "signal_bar_close"]
RollExecution = Literal["causal", "reference_approximation"]
Reentry = Literal["require_signal_reset", "allow_immediate"]

_MICRO = 1_000_000
_GRID_TOLERANCE = 1e-6
RAW_BAR_SECONDS = 60
"""Bar length of the raw per-contract bars (``<root>_1m_raw``, ADR-0085/0086): a causal roll's
legs are priced on ONE-MINUTE raw opens, whatever the simulated series' bar length. The raw
dataset is one-minute bars by contract, so its bar open is ``event_time - 60s``."""
_RAW_BAR_NS = RAW_BAR_SECONDS * NS_PER_S
_CHICAGO = "America/Chicago"
_MONEY = pl.Decimal(38, 6)
_MINUTES_PER_HOUR = 60
_MINUTES_PER_DAY = 24 * 60
_NS_PER_MIN = 60 * NS_PER_S


def _micro(amount: Decimal, what: str) -> int:
    scaled = amount * _MICRO
    if scaled != scaled.to_integral_value():
        msg = f"{what} = {amount} has more than 6 decimals; money is kept in exact micro-dollars"
        raise ConfigurationError(msg)
    return int(scaled)


def _minutes(hhmm: str, what: str) -> int:
    hours, sep, minutes = hhmm.partition(":")
    if not (sep and hours.isdigit() and minutes.isdigit() and len(minutes) == len("mm")):
        msg = f"{what} = {hhmm!r} is not HH:MM"
        raise ConfigurationError(msg)
    total = int(hours) * 60 + int(minutes)
    if int(minutes) >= _MINUTES_PER_HOUR or total >= _MINUTES_PER_DAY:
        msg = f"{what} = {hhmm!r} is not a clock time"
        raise ConfigurationError(msg)
    return total


@dataclass(frozen=True, slots=True)
class SessionCostOverride:
    """Spread and slippage for fills whose Chicago wall-clock minute is in ``[start, end)``
    (``HH:MM``; a window may wrap past midnight). The first matching override wins."""

    name: str
    start: str
    end: str
    spread_ticks: Decimal
    slippage_ticks: Decimal

    def __post_init__(self) -> None:
        if _minutes(self.start, f"{self.name}.start") == _minutes(self.end, f"{self.name}.end"):
            msg = f"session cost window {self.name!r} is empty ({self.start}-{self.end})"
            raise ConfigurationError(msg)
        if self.spread_ticks < 0 or self.slippage_ticks < 0:
            msg = f"session cost window {self.name!r}: spread and slippage ticks must be >= 0"
            raise ConfigurationError(msg)

    def contains(self, minute: int) -> bool:
        start, end = _minutes(self.start, "start"), _minutes(self.end, "end")
        return start <= minute < end if start < end else (minute >= start or minute < end)


@dataclass(frozen=True, slots=True)
class CostSchedule:
    """Costs per contract per side, against the trader (ADR-0090, decision 3).

    ``commission`` is required: there is no default, because a zero would be silently optimistic.
    The three fees default to 0 (an all-in commission includes them). ``spread_ticks`` (the full
    spread; half is paid per side) and ``slippage_ticks`` default to 1 and are uncalibrated
    assumptions unless declared calibrated. ``prices_include_spread`` declares that the execution
    prices already carry the spread, which then must be 0."""

    commission: Decimal
    exchange_fee: Decimal = Decimal(0)
    clearing_fee: Decimal = Decimal(0)
    regulatory_fee: Decimal = Decimal(0)
    spread_ticks: Decimal = Decimal(1)
    slippage_ticks: Decimal = Decimal(1)
    spread_calibrated: bool = False
    slippage_calibrated: bool = False
    prices_include_spread: bool = False
    sessions: tuple[SessionCostOverride, ...] = ()

    def __post_init__(self) -> None:
        amounts = {
            "commission": self.commission,
            "exchange_fee": self.exchange_fee,
            "clearing_fee": self.clearing_fee,
            "regulatory_fee": self.regulatory_fee,
            "spread_ticks": self.spread_ticks,
            "slippage_ticks": self.slippage_ticks,
        }
        negative = [name for name, value in amounts.items() if value < 0]
        if negative:
            msg = f"cost schedule: {negative} must be >= 0"
            raise ConfigurationError(msg)
        if self.prices_include_spread and (
            self.spread_ticks or any(s.spread_ticks for s in self.sessions)
        ):
            msg = (
                "cost schedule declares prices_include_spread, so spread_ticks (and every session "
                "override's) must be 0: the spread would otherwise be charged twice"
            )
            raise ConfigurationError(msg)

    @property
    def fees_per_side(self) -> Decimal:
        return self.commission + self.exchange_fee + self.clearing_fee + self.regulatory_fee

    def ticks_at(self, minute: int) -> tuple[Decimal, Decimal]:
        """``(spread_ticks, slippage_ticks)`` for a fill at that Chicago minute of the day."""
        for window in self.sessions:
            if window.contains(minute):
                return window.spread_ticks, window.slippage_ticks
        return self.spread_ticks, self.slippage_ticks

    def as_dict(self) -> dict[str, object]:
        return {
            "commission": str(self.commission),
            "exchange_fee": str(self.exchange_fee),
            "clearing_fee": str(self.clearing_fee),
            "regulatory_fee": str(self.regulatory_fee),
            "spread_ticks": str(self.spread_ticks),
            "slippage_ticks": str(self.slippage_ticks),
            "spread_calibrated": self.spread_calibrated,
            "slippage_calibrated": self.slippage_calibrated,
            "prices_include_spread": self.prices_include_spread,
            "sessions": [
                {
                    "name": s.name,
                    "start": s.start,
                    "end": s.end,
                    "spread_ticks": str(s.spread_ticks),
                    "slippage_ticks": str(s.slippage_ticks),
                }
                for s in self.sessions
            ],
            "formula": "fees + (spread_ticks / 2 + slippage_ticks) * tick_value per contract per "
            "side; limit (target) fills pay fees only",
        }


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    """How targets become fills (ADR-0090, decisions 2, 5 and 6)."""

    fill: FillTiming = "next_eligible_bar_open"
    stop_ticks: int | None = None
    target_ticks: int | None = None
    target_fill_through_ticks: int = 1
    reentry: Reentry = "require_signal_reset"
    roll_execution: RollExecution = "causal"
    strict: bool = True
    bar_seconds: int = 60

    def __post_init__(self) -> None:
        if self.fill not in ("next_eligible_bar_open", "signal_bar_close"):
            msg = f"fill {self.fill!r}: use next_eligible_bar_open or signal_bar_close"
            raise ConfigurationError(msg)
        if self.reentry not in ("require_signal_reset", "allow_immediate"):
            msg = f"reentry {self.reentry!r}: use require_signal_reset or allow_immediate"
            raise ConfigurationError(msg)
        if self.roll_execution not in ("causal", "reference_approximation"):
            msg = f"roll_execution {self.roll_execution!r}: use causal or reference_approximation"
            raise ConfigurationError(msg)
        for name in ("stop_ticks", "target_ticks", "target_fill_through_ticks"):
            value = getattr(self, name)
            if value is not None and type(value) is not int:
                msg = (
                    f"{name} = {value!r} ({type(value).__name__}): brackets in the futures path "
                    "are whole ticks (ADR-0090) and are refused when they are not a plain int "
                    "(a bool, a float such as 8.0 or 0.25, or a string); a percentage or "
                    "fractional stop is not accepted here"
                )
                raise ConfigurationError(msg)
        for name in ("stop_ticks", "target_ticks"):
            value = getattr(self, name)
            if value is not None and value < 1:
                msg = f"{name} must be >= 1 tick, got {value}"
                raise ConfigurationError(msg)
        if self.target_fill_through_ticks < 0 or self.bar_seconds < 1:
            msg = "target_fill_through_ticks must be >= 0 and bar_seconds >= 1"
            raise ConfigurationError(msg)


def execution_policy(
    spec: FuturesContractSpec, costs: CostSchedule, policy: ExecutionPolicy
) -> dict[str, object]:
    """Everything that decides how a simulation traded, as a JSON-ready record (decision 7)."""
    return {
        "simulator_version": SIMULATOR_VERSION,
        "fill": policy.fill,
        "fill_assumption": (
            "the target decided at a bar's close trades at the open of the next bar at which the "
            "held contract trades"
            if policy.fill == "next_eligible_bar_open"
            else "OPTIMISTIC: the target trades at the close of the bar that decided it"
        ),
        "intrabar": "stop_first",
        "brackets": {
            "stop_ticks": policy.stop_ticks,
            "target_ticks": policy.target_ticks,
            "target_fill_through_ticks": policy.target_fill_through_ticks,
            "stop_order": "stop-market: the level, or the open when gapped; pays spread+slippage",
            "target_order": "limit: needs a trade through, fills at the limit, pays fees only",
            "anchor": "each lot's own fill price (FIFO lots); a roll shifts every lot's levels "
            "by the executed roll spread",
            "reduction": "FIFO",
            "same_bar": "if any lot's stop is touched, only stops fill in that bar; targets need "
            "a later bar",
            "reentry": policy.reentry,
        },
        "off_schedule": "bars with on_schedule false are not eligible for fills or bracket exits",
        "roll_execution": policy.roll_execution,
        "roll_execution_grid_seconds": policy.bar_seconds,
        "roll_execution_grid": (
            "a causal roll executes at the OPEN of the first SIMULATED bar at or after its "
            "decision and at or after the first joint one-minute print, when both contracts have "
            "a raw one-minute bar opening exactly there; both legs are priced at those raw "
            "one-minute opens. On one-minute bars (grid 60) that is the first joint minute; on a "
            "coarser grid the roll waits for such a bar open, at most one bar of delay"
        ),
        "strict": policy.strict,
        "bar_seconds": policy.bar_seconds,
        "costs": costs.as_dict(),
        "spec": spec.as_dict(),
        "spec_table_version": SPEC_TABLE_VERSION,
        "spec_table_sha256": spec_table_hash(),
    }


@dataclass(frozen=True, slots=True)
class FuturesSimResult:
    """``bars``: one row per input bar. ``fills``: one row per fill. ``rolls``: one row per
    contract switch of the series. ``strict_execution`` is False when any roll was valued at
    reference prices (the labelled approximation)."""

    bars: pl.DataFrame
    fills: pl.DataFrame
    rolls: pl.DataFrame
    policy: dict[str, object]
    strict_execution: bool


# ---------------------------------------------------------------------------------------------
# input preparation


def _ticks(values: NDArray[np.float64], tick: float, what: str) -> NDArray[np.int64]:
    scaled = values / tick
    rounded = np.round(scaled)
    off = np.abs(scaled - rounded) > _GRID_TOLERANCE
    if off.any():
        first = int(np.argmax(off))
        msg = (
            f"{what}: price {values[first]} is not on the {tick} tick grid; execution prices must "
            "be raw contract prices (an adjusted continuous series may drive signals, never fills)"
        )
        raise DataQualityError(msg)
    return rounded.astype(np.int64)


def _one_tick(value: object, tick: float, what: str) -> int:
    return int(_ticks(np.array([value], dtype=np.float64), tick, what)[0])


def _validate(bars: pl.DataFrame, targets: pl.DataFrame) -> NDArray[np.int64]:
    needed = {"event_time", "open", "high", "low", "close", "contract"}
    missing = needed - set(bars.columns)
    if missing:
        msg = f"bars are missing columns {sorted(missing)} (CONTINUOUS_BAR_SCHEMA)"
        raise ConfigurationError(msg)
    if bars.height == 0:
        msg = "no bars to simulate"
        raise DataQualityError(msg)
    times = bars["event_time"].to_numpy()
    if not (np.diff(times) > 0).all():
        msg = "bars must be sorted by event_time with one bar per timestamp (no duplicates)"
        raise DataQualityError(msg)
    if set(targets.columns) != {"event_time", "target"}:
        msg = f"targets must have exactly the columns event_time and target, got {targets.columns}"
        raise ConfigurationError(msg)
    if not targets["target"].dtype.is_integer():
        msg = (
            "targets are whole contracts: the target column must be an integer type, got "
            f"{targets['target'].dtype}"
        )
        raise ConfigurationError(msg)
    aligned = bars.select("event_time").join(
        targets, on="event_time", how="left", maintain_order="left"
    )
    if targets.height != bars.height or aligned["target"].null_count():
        msg = (
            f"targets must hold exactly one value per bar ({bars.height} bars, {targets.height} "
            "targets): a missing or extra target would move the fill timing"
        )
        raise ConfigurationError(msg)
    return aligned["target"].to_numpy().astype(np.int64)


def _chicago_minutes(times_ns: NDArray[np.int64]) -> NDArray[np.int64]:
    wall = pl.Series(times_ns).cast(pl.Datetime("ns", "UTC")).dt.convert_time_zone(_CHICAGO)
    minutes = wall.dt.hour().cast(pl.Int64) * 60 + wall.dt.minute().cast(pl.Int64)
    return minutes.to_numpy().astype(np.int64)


@dataclass(slots=True)
class _Roll:
    switch: int  # first bar of the new contract in the continuous series
    index: int  # bar at whose open the position changes contract
    decision: int
    from_contract: str
    to_contract: str
    reason: str
    reference_time: int
    from_ticks: int
    to_ticks: int
    mode: str = "reference_approximation"
    verified: bool = False
    executed_time: int | None = None
    old_ticks: int = 0
    new_ticks: int = 0
    delay_minutes: float | None = None
    error_ticks: int | None = None  # reference-price P&L minus causal P&L, per long contract
    position: int = 0


def _causal_leg(
    raw: pl.DataFrame,
    roll: _Roll,
    times: NDArray[np.int64],
    bar_ns: int,
    *,
    start: int,
    stop: int,
) -> tuple[int, float, float] | None:
    """``(bar index, old open, new open)`` of the first simulated bar in ``[start, stop)`` a causal
    roll can execute at; None when there is none.

    The candidate execution instants are the OPENS of the simulated bars (``event_time -
    bar_seconds``): a fill inside a bar happens at its open, never at a minute buried inside it.
    The first candidate is taken whose open is at or after the decision and at which BOTH
    contracts have a raw one-minute bar opening exactly there; the two legs are priced at those
    raw one-minute opens. On one-minute bars every simulated bar open is a raw minute, so this is
    exactly "the first joint 1m print at or after the decision"; on a coarser grid it delays the
    roll at most one bar rather than pricing it inside a bar it cannot see (the delay is recorded
    as ``delay_minutes``). A candidate whose instant has only one side trading is skipped.

    Timing: every price used is a raw print at that instant, so nothing after the execution
    instant is read.
    """
    if stop <= start:
        return None
    opens = np.asarray(times[start:stop], dtype=np.int64) - bar_ns
    after = np.unique(opens[opens >= roll.decision])
    if after.size == 0:
        return None
    window = raw.filter((pl.col("event_time") - _RAW_BAR_NS).is_in(after.tolist()))
    old = (
        window.filter(pl.col("symbol") == roll.from_contract)
        .select((pl.col("event_time") - _RAW_BAR_NS).alias("instant"), "open")
        .sort("instant")
    )
    new = (
        window.filter(pl.col("symbol") == roll.to_contract)
        .select((pl.col("event_time") - _RAW_BAR_NS).alias("instant"), "open")
        .sort("instant")
    )
    both = old.join(new, on="instant", suffix="_new").sort("instant")
    if both.height == 0:
        return None
    first = both.row(0, named=True)
    at = int(np.searchsorted(np.asarray(times, dtype=np.int64), int(first["instant"]) + bar_ns))
    if (
        at >= len(times)
        or int(times[at]) != int(first["instant"]) + bar_ns
        or not (start <= at < stop)
    ):
        return None
    return at, float(first["open"]), float(first["open_new"])


@dataclass(slots=True)
class _Frame:
    times: NDArray[np.int64]
    open: NDArray[np.int64]
    high: NDArray[np.int64]
    low: NDArray[np.int64]
    close: NDArray[np.int64]
    trades: NDArray[np.bool_]  # the held contract traded in the bar AND the bar is on schedule
    held: list[str]
    rolls: list[_Roll] = field(default_factory=list)


def _on_schedule(bars: pl.DataFrame) -> NDArray[np.bool_]:
    """Whether each bar is on a scheduled session (ADR-0091). A bar outside every scheduled
    Globex segment is not eligible: no signal fills at its open or close and no bracket exits in
    it, because the market is closed and a resting order cannot execute. No ``on_schedule``
    column means every bar is on schedule."""
    if "on_schedule" not in bars.columns:
        return np.ones(bars.height, dtype=np.bool_)
    column = bars["on_schedule"]
    nulls = column.null_count()
    if nulls:
        msg = (
            f"bars.on_schedule has {nulls} null(s): every bar must say whether it is on a "
            "scheduled session (ADR-0091), because a null can be read as neither eligible nor "
            "not eligible and would silently change which fills can happen"
        )
        raise DataQualityError(msg)
    if column.dtype != pl.Boolean:
        msg = (
            f"bars.on_schedule must be a Boolean column, got {column.dtype}: a bar is either on "
            "schedule (true) or it is not (false), never a number or a string"
        )
        raise ConfigurationError(msg)
    return column.to_numpy().astype(np.bool_)


def _prepare(
    bars: pl.DataFrame,
    rolls: pl.DataFrame,
    raw: pl.DataFrame | None,
    tick: float,
    policy: ExecutionPolicy,
) -> _Frame:
    """The execution frame: integer-tick OHLC of the contract actually held at each bar, whether
    that contract could execute in the bar (it traded and the bar is on schedule), the held
    contract, and every roll with its execution."""
    bar_ns = policy.bar_seconds * NS_PER_S
    frame = _Frame(
        times=bars["event_time"].to_numpy().astype(np.int64),
        open=_ticks(bars["open"].to_numpy().astype(np.float64), tick, "bars.open"),
        high=_ticks(bars["high"].to_numpy().astype(np.float64), tick, "bars.high"),
        low=_ticks(bars["low"].to_numpy().astype(np.float64), tick, "bars.low"),
        close=_ticks(bars["close"].to_numpy().astype(np.float64), tick, "bars.close"),
        trades=_on_schedule(bars),
        held=bars["contract"].to_list(),
    )
    series = list(frame.held)
    switches = [i for i in range(1, len(series)) if series[i] != series[i - 1]]
    table = {(r["from_contract"], r["to_contract"]): r for r in rolls.iter_rows(named=True)}
    needed = sorted({c for i in switches for c in (series[i - 1], series[i])})
    raw_needed = (
        raw.filter(pl.col("symbol").is_in(needed)).sort("event_time")
        if raw is not None and needed
        else None
    )
    for n, k in enumerate(switches):
        key = (series[k - 1], series[k])
        row = table.get(key)
        if row is None:
            msg = (
                f"the series switches {key[0]} -> {key[1]} at ts={int(frame.times[k])} but the "
                "rolls table has no such roll; pass the rolls dataset built with this series"
            )
            raise DataQualityError(msg)
        roll = _Roll(
            switch=k,
            index=k,
            decision=int(row["event_time"]),
            from_contract=key[0],
            to_contract=key[1],
            reason=str(row["reason"]),
            reference_time=int(row["reference_time"]),
            from_ticks=_one_tick(row["from_price"], tick, "rolls.from_price"),
            to_ticks=_one_tick(row["to_price"], tick, "rolls.to_price"),
        )
        next_switch = switches[n + 1] if n + 1 < len(switches) else len(series)
        leg = (
            _causal_leg(raw_needed, roll, frame.times, bar_ns, start=k, stop=next_switch)
            if raw_needed is not None
            else None
        )
        at = leg[0] if leg is not None else -1
        if leg is not None and at >= 0:
            old_ticks = _one_tick(leg[1], tick, "raw old-contract open")
            new_ticks = _one_tick(leg[2], tick, "raw new-contract open")
            if new_ticks != int(frame.open[at]):
                msg = (
                    f"roll {key[0]} -> {key[1]}: the new contract's raw open at ts={leg[0]} is not "
                    "the continuous series' open there; rebuild the series from this raw data"
                )
                raise DataQualityError(msg)
            roll.error_ticks = (roll.from_ticks - old_ticks) - (roll.to_ticks - new_ticks)
            roll.delay_minutes = (int(frame.times[at]) - int(frame.times[k])) / _NS_PER_MIN
        if policy.roll_execution == "causal" and leg is not None and at >= 0:
            roll.mode, roll.verified = "causal", True
            roll.index, roll.executed_time = at, int(frame.times[at])
            roll.old_ticks, roll.new_ticks = old_ticks, new_ticks
            _hold_old_contract(frame, raw_needed, k, at, key[0], tick)
        elif policy.roll_execution == "causal" and policy.strict:
            msg = (
                f"roll {key[0]} -> {key[1]} (decided at ts={roll.decision}) has no minute at or "
                "after the decision, before the next roll, in which both contracts traded in the "
                "raw data: it cannot be executed causally. Pass the raw dataset, or run with "
                "strict=False to value it at reference prices (flagged unverified)"
            )
            raise DataQualityError(msg)
        else:
            roll.executed_time = roll.reference_time
            roll.old_ticks, roll.new_ticks = roll.from_ticks, roll.to_ticks
        frame.rolls.append(roll)
    return frame


def _hold_old_contract(
    frame: _Frame, raw: pl.DataFrame | None, start: int, stop: int, old: str, tick: float
) -> None:
    """Bars ``start..stop-1`` are new-contract bars of the continuous series, but the position is
    still in the old contract until the roll executes at ``stop``: they get the old contract's raw
    OHLC aggregated over each bar's interval, or its last close and no trading where it had none."""
    if stop <= start or raw is None:
        return
    rows = raw.filter(
        (pl.col("symbol") == old)
        & (pl.col("event_time") > int(frame.times[start - 1]))
        & (pl.col("event_time") <= int(frame.times[stop - 1]))
    ).sort("event_time")
    groups: dict[int, list[tuple[float, float, float, float]]] = {}
    for r in rows.iter_rows(named=True):
        i = int(np.searchsorted(frame.times, int(r["event_time"]), side="left"))
        groups.setdefault(i, []).append((r["open"], r["high"], r["low"], r["close"]))
    last_close = int(frame.close[start - 1])
    for i in range(start, stop):
        frame.held[i] = old
        group = groups.get(i)
        if group:
            prices = _ticks(np.array(group, dtype=np.float64).ravel(), tick, "raw old contract")
            quad = prices.reshape(-1, 4)
            frame.open[i] = quad[0, 0]
            frame.high[i] = quad[:, 1].max()
            frame.low[i] = quad[:, 2].min()
            frame.close[i] = quad[-1, 3]
            last_close = int(frame.close[i])
        else:
            frame.trades[i] = False
            frame.open[i] = frame.high[i] = frame.low[i] = frame.close[i] = last_close


# ---------------------------------------------------------------------------------------------
# the simulation


@dataclass(slots=True)
class _Lot:
    """One FIFO lot: signed quantity, entry ticks, and its OWN bracket levels measured from that
    entry (``None`` where the policy declares no such bracket)."""

    qty: int
    entry: int
    stop: int | None = None
    target: int | None = None

    @property
    def side(self) -> int:
        return 1 if self.qty > 0 else -1


@dataclass(slots=True)
class _Book:
    """Open lots, FIFO as ``_Lot`` (signed quantity, entry ticks, own stop and target)."""

    lots: deque[_Lot] = field(default_factory=deque)

    @property
    def position(self) -> int:
        return sum(lot.qty for lot in self.lots)

    def unrealized_ticks(self, mark: int) -> int:
        return sum(lot.qty * (mark - lot.entry) for lot in self.lots)

    def trade(
        self, qty: int, price: int, stop: int | None = None, target: int | None = None
    ) -> int:
        """Applies a fill of ``qty`` (signed) at ``price`` ticks; returns the realized ticks.

        Opposing lots close FIFO (a lot cut short keeps its own levels); whatever is left over
        opens ONE new lot carrying ``stop``/``target``, which belong to that fill's own price."""
        realized = 0
        while qty and self.lots and (self.lots[0].qty > 0) != (qty > 0):
            lot = self.lots[0]
            closed = min(abs(qty), abs(lot.qty)) * (1 if lot.qty > 0 else -1)
            realized += closed * (price - lot.entry)
            lot.qty -= closed
            qty += closed
            if lot.qty == 0:
                self.lots.popleft()
        if qty:
            self.lots.append(_Lot(qty, price, stop, target))
        return realized

    def close_lot(self, lot: _Lot, price: int) -> int:
        """Closes exactly ``lot`` (not FIFO) at ``price``; returns the realized ticks."""
        for index, candidate in enumerate(self.lots):
            if candidate is lot:
                del self.lots[index]
                return lot.qty * (price - lot.entry)
        msg = (
            f"lot {lot!r} is not in the book (position {self.position}): a bracket exit can only "
            "close a lot that is still open"
        )
        raise InvariantViolation(msg)

    def restore(self, price: int, lots: Sequence[tuple[int, int | None, int | None]]) -> None:
        """Replaces the book with ``lots`` re-opened at ``price`` (a roll that keeps the position):
        the same signed quantities in the same FIFO order, each with its own levels."""
        quantities = sum(qty for qty, _, _ in lots)
        if quantities != self.position:
            msg = (
                f"re-opening {quantities} contracts over a book of {self.position}: a roll that "
                "keeps the position must preserve every lot's quantity"
            )
            raise InvariantViolation(msg)
        self.lots = deque(_Lot(qty, price, stop, target) for qty, stop, target in lots)

    def carry(self) -> list[tuple[int, int | None, int | None]]:
        """The book as ``(quantity, stop, target)`` in FIFO order, for a roll to re-open."""
        return [(lot.qty, lot.stop, lot.target) for lot in self.lots]


@dataclass(frozen=True, slots=True)
class _Fill:
    event_time: int
    fill_time: int
    contract: str
    kind: str
    quantity: int
    price_ticks: int
    realized: int
    fees: int
    spread: int
    slippage: int


@dataclass(slots=True)
class _Costs:
    fees: int  # per contract per side, micro-dollars
    spread: NDArray[np.int64]  # half spread per contract, by bar, for a fill at the bar's open
    slippage: NDArray[np.int64]
    spread_close: NDArray[np.int64]  # the same for a fill at the bar's close
    slippage_close: NDArray[np.int64]


def _cost_tables(
    costs: CostSchedule, tick_value: Decimal, times: NDArray[np.int64], bar_ns: int
) -> _Costs:
    cache: dict[int, tuple[int, int]] = {}

    def per_bar(minutes: NDArray[np.int64]) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
        spread = np.empty(len(minutes), dtype=np.int64)
        slip = np.empty(len(minutes), dtype=np.int64)
        for i, minute in enumerate(minutes.tolist()):
            if minute not in cache:
                s, p = costs.ticks_at(minute)
                cache[minute] = (
                    _micro(s / 2 * tick_value, "half spread per contract"),
                    _micro(p * tick_value, "slippage per contract"),
                )
            spread[i], slip[i] = cache[minute]
        return spread, slip

    spread_open, slip_open = per_bar(_chicago_minutes(times - bar_ns))
    spread_close, slip_close = per_bar(_chicago_minutes(times))
    return _Costs(
        fees=_micro(costs.fees_per_side, "fees per side"),
        spread=spread_open,
        slippage=slip_open,
        spread_close=spread_close,
        slippage_close=slip_close,
    )


@dataclass(slots=True)
class _State:
    """The simulation's mutable state, one instance per run."""

    book: _Book
    pending: int | None = None  # the target waiting for the next eligible open
    pending_raw: int = 0  # the decided target behind ``pending`` (before re-entry blocking)
    in_force_raw: int = 0  # the decided target the position currently reflects
    blocked: int | None = None  # require_signal_reset: the decided target that must change


class _Run:
    """One simulation: the frame, the cost tables, the per-bar money arrays and the fills."""

    def __init__(
        self, frame: _Frame, table: _Costs, policy: ExecutionPolicy, tick_micro: int, bar_ns: int
    ) -> None:
        n = len(frame.times)
        self.frame, self.table, self.policy = frame, table, policy
        self.tick_micro, self.bar_ns = tick_micro, bar_ns
        self.state = _State(book=_Book())
        self.position = np.zeros(n, dtype=np.int64)
        self.realized = np.zeros(n, dtype=np.int64)
        self.unrealized = np.zeros(n, dtype=np.int64)
        self.fees = np.zeros(n, dtype=np.int64)
        self.spread = np.zeros(n, dtype=np.int64)
        self.slippage = np.zeros(n, dtype=np.int64)
        self.fills: list[_Fill] = []

    def levels(self, price: int, side: int) -> tuple[int | None, int | None]:
        """The ``(stop, target)`` levels measured from a fill at ``price`` for a lot of ``side``
        (``None`` where the policy declares no such bracket)."""
        stop, take = self.policy.stop_ticks, self.policy.target_ticks
        return (
            None if stop is None else price - side * stop,
            None if take is None else price + side * take,
        )

    def fill(
        self,
        i: int,
        qty: int,
        price: int,
        kind: str,
        *,
        at_close: bool = False,
        market: bool = True,
        contract: str | None = None,
        fill_time: int | None = None,
    ) -> None:
        """Books a signal fill of ``qty`` contracts at ``price`` ticks in bar ``i``: opposing lots
        close FIFO and any position left over opens ONE lot whose brackets are measured from THIS
        fill's price (an add to an existing position does not move the other lots' levels)."""
        if qty == 0:
            return
        stop, target = self.levels(price, 1 if qty > 0 else -1)
        gained = self.state.book.trade(qty, price, stop, target)
        self._book(
            i,
            qty,
            price,
            kind,
            gained,
            at_close=at_close,
            market=market,
            contract=contract,
            fill_time=fill_time,
        )

    def bracket_exit(self, i: int, lot: _Lot, price: int, kind: str) -> None:
        """Exits exactly ``lot`` in bar ``i``: a stop is a stop-market order (pays spread and
        slippage), a target is a limit order (pays the fees only)."""
        gained = self.state.book.close_lot(lot, price)
        self._book(
            i,
            -lot.qty,
            price,
            kind,
            gained,
            at_close=False,
            market=kind == "stop",
            contract=None,
            fill_time=None,
        )

    def _book(
        self,
        i: int,
        qty: int,
        price: int,
        kind: str,
        gained_ticks: int,
        *,
        at_close: bool,
        market: bool,
        contract: str | None,
        fill_time: int | None,
    ) -> None:
        """Records already-booked realized ticks as a fill: money arrays, then the fill row."""
        table = self.table
        gained = gained_ticks * self.tick_micro
        contracts = abs(qty)
        fees = table.fees * contracts
        spread = int((table.spread_close if at_close else table.spread)[i]) * contracts
        slip = int((table.slippage_close if at_close else table.slippage)[i]) * contracts
        if not market:
            spread = slip = 0
        self.realized[i] += gained
        self.fees[i] += fees
        self.spread[i] += spread
        self.slippage[i] += slip
        close_time = int(self.frame.times[i])
        self.fills.append(
            _Fill(
                event_time=close_time,
                fill_time=fill_time
                if fill_time is not None
                else (close_time if at_close else close_time - self.bar_ns),
                contract=contract or self.frame.held[i],
                kind=kind,
                quantity=qty,
                price_ticks=price,
                realized=gained,
                fees=fees,
                spread=spread,
                slippage=slip,
            )
        )

    def roll(self, i: int, roll: _Roll) -> None:
        """Closes the old contract and opens the new one at the roll's execution prices; a target
        pending for this open is traded in the new leg instead of a separate fill. A roll that
        keeps the position re-opens the same lots (same quantities, same FIFO order) with every
        lot's levels shifted by the executed roll spread."""
        st = self.state
        held = st.book.position
        roll.position = held
        if held == 0:
            return
        next_open = self.policy.fill == "next_eligible_bar_open"
        goal = st.pending if (st.pending is not None and next_open) else held
        when = roll.reference_time if roll.mode == "reference_approximation" else None
        carried = st.book.carry()
        self.fill(
            i, -held, roll.old_ticks, "roll_close", contract=roll.from_contract, fill_time=when
        )
        if goal == held:
            self.fill(i, held, roll.new_ticks, "roll_open", fill_time=when)
            shift = roll.new_ticks - roll.old_ticks
            st.book.restore(
                roll.new_ticks,
                [
                    (
                        qty,
                        None if stop is None else stop + shift,
                        None if take is None else take + shift,
                    )
                    for qty, stop, take in carried
                ],
            )
        else:
            self.fill(i, goal, roll.new_ticks, "signal", fill_time=when)
            st.in_force_raw = st.pending_raw
        if next_open:
            st.pending = None

    def brackets(self, i: int) -> None:
        """Per-lot stops and targets inside bar ``i``, pessimistic about the intrabar path.

        If ANY open lot's stop is touched, only the touched stops fill in this bar (the order of
        the high and the low inside it is unknown, so the worse path is assumed) and no target
        fills until a later bar. Lots whose stop is not touched stay open with their levels."""
        st, frame, policy = self.state, self.frame, self.policy
        if not st.book.lots or not frame.trades[i]:
            return
        o, h, lo = int(frame.open[i]), int(frame.high[i]), int(frame.low[i])
        through = policy.target_fill_through_ticks
        stops: list[tuple[_Lot, int]] = []
        targets: list[tuple[_Lot, int]] = []
        for lot in list(st.book.lots):
            side, stop, take = lot.side, lot.stop, lot.target
            if stop is not None and (lo <= stop if side > 0 else h >= stop):
                gapped = o <= stop if side > 0 else o >= stop
                stops.append((lot, o if gapped else stop))
            elif take is not None and (h >= take + through if side > 0 else lo <= take - through):
                targets.append((lot, take))
        if stops:
            for lot, price in stops:
                self.bracket_exit(i, lot, price, "stop")
        elif targets:
            for lot, price in targets:
                self.bracket_exit(i, lot, price, "target")
        else:
            return
        if policy.reentry == "require_signal_reset":
            st.blocked = st.in_force_raw
        st.pending = None

    def decide(self, i: int, decided: int) -> None:
        """The target decided at bar ``i``'s close: traded now (``signal_bar_close``) or at the
        next eligible open; after a bracket exit the decided target holds whatever survived the
        exit (nothing, after a full exit) until it changes."""
        st = self.state
        effective = decided
        if st.blocked is not None:
            if decided == st.blocked:
                effective = st.book.position
            else:
                st.blocked = None
        if self.policy.fill == "signal_bar_close":
            if effective != st.book.position and self.frame.trades[i]:
                qty = effective - st.book.position
                self.fill(i, qty, int(self.frame.close[i]), "signal", at_close=True)
                st.in_force_raw = decided
        else:
            st.pending = effective if effective != st.book.position else None
            st.pending_raw = decided

    def bar(self, i: int, decided: int, roll: _Roll | None) -> None:
        st = self.state
        if roll is not None:
            self.roll(i, roll)
        elif st.pending is not None and self.frame.trades[i]:
            self.fill(i, st.pending - st.book.position, int(self.frame.open[i]), "signal")
            st.in_force_raw = st.pending_raw
            st.pending = None
        self.brackets(i)
        self.decide(i, decided)
        self.position[i] = st.book.position
        self.unrealized[i] = st.book.unrealized_ticks(int(self.frame.close[i])) * self.tick_micro


def simulate_futures(
    *,
    bars: pl.DataFrame,
    targets: pl.DataFrame,
    rolls: pl.DataFrame,
    spec: FuturesContractSpec,
    costs: CostSchedule,
    initial_capital: Decimal,
    policy: ExecutionPolicy | None = None,
    raw: pl.DataFrame | None = None,
) -> FuturesSimResult:
    """Simulate ``targets`` (``event_time``, integer ``target`` contracts decided at each bar's
    close) on one continuous futures series (ADR-0090).

    ``bars``: the unadjusted continuous series (``CONTINUOUS_BAR_SCHEMA``: raw prices of the held
    contract, on its tick grid), optionally with a Boolean ``on_schedule`` column (a false bar is
    outside every scheduled session, so nothing can fill in it: ADR-0091). ``rolls``: its rolls
    table (``ROLL_SCHEMA``). ``raw``: the raw per-contract bars (``symbol`` = contract,
    ``event_time``, OHLC) the causal roll legs come from; without it, strict causal mode refuses
    any roll. ``initial_capital`` in USD. Prices in points; money in USD as ``Decimal(38, 6)``.
    """
    policy = policy or ExecutionPolicy()
    tick = float(spec.tick_size)
    decided = _validate(bars, targets)
    bar_ns = policy.bar_seconds * NS_PER_S
    frame = _prepare(bars, rolls, raw, tick, policy)
    run = _Run(
        frame,
        _cost_tables(costs, spec.tick_value, frame.times, bar_ns),
        policy,
        _micro(spec.tick_value, "tick value"),
        bar_ns,
    )
    rolls_at = {r.index: r for r in frame.rolls}
    for i in range(len(frame.times)):
        run.bar(i, int(decided[i]), rolls_at.get(i))
    strict = policy.roll_execution == "causal" and all(
        r.mode == "causal" or r.position == 0 for r in frame.rolls
    )
    return FuturesSimResult(
        bars=_bars_frame(run, _micro(initial_capital, "initial_capital")),
        fills=_fills_frame(run.fills, spec),
        rolls=_rolls_frame(frame.rolls, spec),
        policy=execution_policy(spec, costs, policy),
        strict_execution=strict,
    )


# ---------------------------------------------------------------------------------------------
# output


def _money(values: NDArray[np.int64] | list[int]) -> pl.Series:
    """Micro-dollars as an exact ``Decimal(38, 6)`` of dollars."""
    return pl.Series(values, dtype=pl.Int64).cast(pl.Decimal(38, 0)).cast(_MONEY) / _MICRO


def _bars_frame(run: _Run, capital: int) -> pl.DataFrame:
    costs = run.fees + run.spread + run.slippage
    balance = capital + np.cumsum(run.realized - costs)
    return pl.DataFrame(
        {
            "event_time": pl.Series(run.frame.times, dtype=pl.Int64),
            "contract": pl.Series(run.frame.held, dtype=pl.String),
            "tradable": pl.Series(run.frame.trades, dtype=pl.Boolean),
            "position": pl.Series(run.position, dtype=pl.Int64),
            "realized_usd": _money(run.realized),
            "unrealized_usd": _money(run.unrealized),
            "fees_usd": _money(run.fees),
            "spread_usd": _money(run.spread),
            "slippage_usd": _money(run.slippage),
            "costs_usd": _money(costs),
            "balance_usd": _money(balance),
            "equity_usd": _money(balance + run.unrealized),
        }
    )


def _fills_frame(fills: list[_Fill], spec: FuturesContractSpec) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "event_time": pl.Series([f.event_time for f in fills], dtype=pl.Int64),
            "fill_time": pl.Series([f.fill_time for f in fills], dtype=pl.Int64),
            "contract": pl.Series([f.contract for f in fills], dtype=pl.String),
            "kind": pl.Series([f.kind for f in fills], dtype=pl.String),
            "quantity": pl.Series([f.quantity for f in fills], dtype=pl.Int64),
            "price": pl.Series(
                [Decimal(f.price_ticks) * spec.tick_size for f in fills], dtype=_MONEY
            ),
            "realized_usd": _money([f.realized for f in fills]),
            "fees_usd": _money([f.fees for f in fills]),
            "spread_usd": _money([f.spread for f in fills]),
            "slippage_usd": _money([f.slippage for f in fills]),
        }
    )


def _rolls_frame(rolls: list[_Roll], spec: FuturesContractSpec) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "decision_time": pl.Series([r.decision for r in rolls], dtype=pl.Int64),
            "from_contract": pl.Series([r.from_contract for r in rolls], dtype=pl.String),
            "to_contract": pl.Series([r.to_contract for r in rolls], dtype=pl.String),
            "reason": pl.Series([r.reason for r in rolls], dtype=pl.String),
            "mode": pl.Series([r.mode for r in rolls], dtype=pl.String),
            "verified": pl.Series([r.verified for r in rolls], dtype=pl.Boolean),
            "executed_time": pl.Series([r.executed_time for r in rolls], dtype=pl.Int64),
            "old_price": pl.Series(
                [Decimal(r.old_ticks) * spec.tick_size for r in rolls], dtype=_MONEY
            ),
            "new_price": pl.Series(
                [Decimal(r.new_ticks) * spec.tick_size for r in rolls], dtype=_MONEY
            ),
            "delay_minutes": pl.Series([r.delay_minutes for r in rolls], dtype=pl.Float64),
            "reference_time": pl.Series([r.reference_time for r in rolls], dtype=pl.Int64),
            "approximation_error_ticks": pl.Series([r.error_ticks for r in rolls], dtype=pl.Int64),
            "approximation_error_usd": pl.Series(
                [
                    None if r.error_ticks is None else Decimal(r.error_ticks) * spec.tick_value
                    for r in rolls
                ],
                dtype=_MONEY,
            ),
            "position": pl.Series([r.position for r in rolls], dtype=pl.Int64),
        }
    )
