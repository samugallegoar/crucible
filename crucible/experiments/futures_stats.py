"""Futures statistics: daily returns on FIXED capital, Sharpe, PSR, DSR, bootstrap intervals, IC.

This is the module C6a adds (ADR-0103). Before it, every futures number was descriptive (a total, a
count, a conservative drawdown). The three owner decisions that shape what it reports:

1. **Returns are daily marked P&L over the fixed initial capital.**
   ``daily_return_t = (closing_equity_t - closing_equity_{t-1}) / initial_capital``, where
   ``closing_equity_{t-1}`` is the previous trade date's closing equity and ``initial_capital`` on
   the first date. The difference is exact ``Decimal`` money; only the division becomes float64.
   Returns therefore do NOT compound, and the P&L they measure contains realized P&L, the change in
   unrealized P&L and every cost exactly once.
   - a trade date with on-schedule bars and no position is a **zero-return observation** (the day
     happened, the strategy simply held nothing);
   - a trade date with no valid bars is **missing**, never zero: it is excluded and counted as
     ``missing_sessions`` against the session calendar. Inventing a flat day would invent an
     observation.
2. **PSR and DSR use the PER-PERIOD Sharpe** (``core.stats.per_period_sharpe``: mean over ddof=1
   standard deviation). The annualized Sharpe (``x sqrt(252)``) is presentation only, and the
   manifest records the convention.
3. **There is no edge verdict.** ``verdict_level`` stays null everywhere with the reason code
   ``robustness_not_assessed``: robustness and prop-firm rules are C7. A number here is a
   statistic, never a recommendation.

The confidence intervals are a seeded CIRCULAR BLOCK bootstrap (blocks of ``ceil(sqrt(n))``
consecutive observations, wrapped circularly), because daily P&L is autocorrelated and an i.i.d.
resample would understate the interval. The seed is a pure function of the artifact's identity and
the statistic's name (``bootstrap_seed(owner_id, name)``), never of a global sequence, so the same
run reports the same interval whatever order the runs execute in or how many threads do it.

The information coefficient (decision 6) is a time-series Spearman correlation per trade date
between the expression's score at a decision bar and the close-to-close return over the next
``ic_horizon_bars`` bars of the SIGNAL series. A pair that crosses a session edge or a contract
change is dropped, never filled; a trade date with fewer than ``MIN_IC_PAIRS`` valid pairs gives no
IC. Only a DSL expression has one: a Python function or a spec strategy gets null with a reason.

``daily_returns`` is the ONE returns function: standalone runs, batch candidates, walk-forward OOS
series and comparisons all call it, so two artifacts can never disagree about what a daily return
is (ADR-0103 decision 1).

Timing: every input here is a finished artifact's own ledger; nothing reads the clock, the data
store or the registry.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from crucible.core.errors import ConfigurationError, CrucibleError, DataQualityError
from crucible.core.stats import is_degenerate_returns, per_period_sharpe
from crucible.data.cme_sessions import session_trade_dates
from crucible.experiments.futures_config import (
    ANNUALIZATION_PERIODS_PER_YEAR,
    FuturesStatisticsConfig,
)
from crucible.validation.dsr import (
    deflated_sharpe_ratio,
    pearson_kurtosis,
    probabilistic_sharpe_ratio,
    skewness,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from numpy.typing import NDArray

    from crucible.data.cme_sessions import SessionCalendar

StatisticsConfig = FuturesStatisticsConfig
"""The config type ``futures_statistics`` takes (``FuturesRunConfig.statistics``)."""

RETURNS_CONVENTION = (
    "daily_return_t = (closing_equity_t - closing_equity_{t-1}) / initial_capital, where "
    "closing_equity_{t-1} is the previous trade date's closing equity and initial_capital on the "
    "first trade date; the differences are exact Decimal money and only the division is float64. "
    "Returns do NOT compound. A trade date with on-schedule bars and no position is a zero-return "
    "observation; a trade date with no valid bars is excluded and counted as missing_sessions."
)
"""Recorded verbatim in the manifest: what one number in the returns series means (ADR-0103)."""

ANNUALIZATION: dict[str, object] = {
    "periods_per_year": ANNUALIZATION_PERIODS_PER_YEAR,
    "convention": "sqrt",
}
"""The annualized Sharpe is ``per_period * sqrt(252)`` and is PRESENTATION ONLY: PSR and DSR are
computed on the per-period Sharpe (annualizing would decouple the estimator from its observation
count, ADR-0015)."""

BOOTSTRAP_RNG = "numpy.random.PCG64"
"""The bit generator every interval uses, recorded in the manifest."""

BLOCK_LENGTH_POLICY = "ceil(sqrt(n))"
"""How the circular block bootstrap's block length is chosen from ``n`` observations."""

DEFAULT_MIN_COMPUTED = 3
"""Fewest return observations a Sharpe/PSR/DSR is computed from (below it the normal approximation
of PSR is meaningless and ``deflated_sharpe_ratio`` itself refuses)."""

MIN_IC_PAIRS = 10
"""Fewest (score, forward return) pairs a trade date needs before it gets an IC (ADR-0103)."""

IC_UNIT = "correlation"
"""The IC is a (Spearman) correlation: dimensionless, in [-1, 1]."""

STATISTICS_METRIC_UNITS: dict[str, str] = {
    "sharpe_per_period": "sharpe",
    "sharpe_annualized": "sharpe",
    "mean_daily_return": "fraction",
    "psr": "probability",
    "dsr": "probability",
    "ic_mean": IC_UNIT,
}
"""The unit of every statistic this module reports, in reading order: the per-period Sharpe (the
one PSR and DSR use), the annualized Sharpe (presentation), the mean daily return (a fraction of
the fixed capital per trade date), PSR and DSR (probabilities in [0, 1]) and the mean information
coefficient (a correlation)."""

STATISTICS_METRICS: tuple[str, ...] = tuple(STATISTICS_METRIC_UNITS)
"""Every statistic name, in the order a report reads them."""

PSR_METHOD = (
    "probabilistic_sharpe_ratio on the per-period Sharpe against a benchmark of 0, with the "
    "skewness and Pearson-kurtosis correction of ADR-0015; no interval (it is a probability, "
    "computed in closed form)"
)
"""Recorded in the PSR metric's ``method`` field: what the number is, and why it carries no CI."""

DSR_METHOD = (
    "deflated_sharpe_ratio on the per-period Sharpe, deflated by the expected maximum Sharpe of "
    "total_trials candidates whose cross-trial dispersion is estimated from the family's distinct "
    "candidate Sharpes (ADR-0015, ADR-0103); null with a reason rather than computed over fewer "
    "than two candidate Sharpes"
)
"""Recorded in the DSR metric's ``method`` field."""

IC_METHOD = (
    "mean over trade dates of Spearman's correlation (average ties) between the expression's score "
    "at each decision bar and the close-to-close return over ic_horizon_bars bars of the signal "
    "series; a pair crossing a session edge or a contract change is dropped, never filled"
)
"""Recorded in the IC metric's ``method`` field."""


def _metric(
    value: float | None,
    unit: str,
    *,
    assessment: str,
    ci_low: float | None = None,
    ci_high: float | None = None,
    method: str | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    """One statistic in the futures metric shape ``{value, ci_low, ci_high, assessment, unit}``.

    ``assessment`` is ``inferential`` when the number carries an interval (or is a probability
    computed in closed form) and ``descriptive`` when it is just a sum or a mean. A null ``value``
    always comes with a ``reason``: a null is a missing number, never a zero.
    """
    return {
        "value": None if value is None else float(value),
        "ci_low": None if ci_low is None else float(ci_low),
        "ci_high": None if ci_high is None else float(ci_high),
        "assessment": assessment,
        "unit": unit,
        "method": method,
        "reason": reason,
    }


# ---------------------------------------------------------------------------------------------
# a. daily returns on fixed capital


@dataclass(frozen=True, slots=True)
class ReturnsSeries:
    """The daily return series of one artifact, on its FIXED initial capital (ADR-0103 decision 1).

    ``trade_dates`` and ``returns`` are aligned and in trade-date order. ``missing_sessions``
    counts the calendar's trade dates of the window that produced no valid bar (excluded, never
    zero-filled) and ``zero_position_days`` the observed ones on which the artifact held nothing
    (a real zero return, not a missing one).
    """

    trade_dates: tuple[dt.date, ...]
    returns: NDArray[np.float64]
    missing_sessions: int
    zero_position_days: int
    initial_capital: Decimal

    @property
    def n_observations(self) -> int:
        """How many daily observations the series holds."""
        return len(self.trade_dates)

    @property
    def degenerate(self) -> bool:
        """Whether the series has no dispersion, so its Sharpe ratio is undefined."""
        return is_degenerate_returns(self.returns)


def _window_dates(calendar: SessionCalendar, window: tuple[dt.date, dt.date]) -> list[dt.date]:
    """The session calendar's trade dates in ``window`` (inclusive on both ends)."""
    start, end = window
    if end < start:
        msg = (
            f"the statistics window is [{start}, {end}]: a window is a range of Globex trade "
            "dates, inclusive on both ends, so its end cannot precede its start"
        )
        raise ConfigurationError(msg)
    out: list[dt.date] = []
    day = start
    step = dt.timedelta(days=1)
    while day <= end:
        if calendar.is_trade_date(day):
            out.append(day)
        day += step
    return out


def _frame_returns(
    *,
    days: Sequence[dt.date],
    equity: Sequence[Decimal],
    initial_capital: Decimal,
    zero_position: Sequence[bool],
    calendar: SessionCalendar,
    window: tuple[dt.date, dt.date],
    what: str,
) -> ReturnsSeries:
    """The returns series of one daily chain, after the window and the calendar are applied.

    Every difference is exact ``Decimal``; only ``(difference) / capital`` becomes float64, which
    is the one place a return can lose precision and the only one the ADR allows.
    """
    if not days:
        msg = (
            f"the {what} has no trade date in [{window[0]}, {window[1]}]: there is no return to "
            "compute. Widen the window or re-run the artifact"
        )
        raise DataQualityError(msg)
    if initial_capital <= 0:
        msg = f"the initial capital {initial_capital} must be positive to divide by it"
        raise ConfigurationError(msg)
    capital = Decimal(initial_capital)
    observed: dict[dt.date, tuple[Decimal, bool]] = {}
    for day, value, flat in zip(days, equity, zero_position, strict=True):
        if day < window[0] or day > window[1]:
            msg = (
                f"the {what} holds a row for trade date {day}, outside its window "
                f"[{window[0]}, {window[1]}]: the statistics are computed over the window's trade "
                "dates alone, so a row from outside it means the frame is not this window's chain"
            )
            raise DataQualityError(msg)
        if day in observed:
            msg = (
                f"the {what} holds trade date {day} twice: one row per trade date is what makes "
                "the returns a chained series"
            )
            raise DataQualityError(msg)
        observed[day] = (Decimal(value), flat)
    expected = _window_dates(calendar, window)
    ordered = sorted(observed)
    returns: list[float] = []
    previous = capital
    flat_days = 0
    for day in ordered:
        closing, flat = observed[day]
        returns.append(float((closing - previous) / capital))
        if flat:
            flat_days += 1
        previous = closing
    return ReturnsSeries(
        trade_dates=tuple(ordered),
        returns=np.asarray(returns, dtype=np.float64),
        missing_sessions=sum(1 for day in expected if day not in observed),
        zero_position_days=flat_days,
        initial_capital=capital,
    )


def _require_columns(frame: pl.DataFrame, names: Sequence[str], what: str) -> None:
    missing = [name for name in names if name not in frame.columns]
    if missing:
        msg = (
            f"the {what} lacks the column(s) {missing}: the daily returns are read from "
            "trade_date and closing_equity_usd (plus max_contracts, which is how a zero-position "
            "day is recognised). Re-run the artifact with `crucible futures run`"
        )
        raise DataQualityError(msg)


def daily_returns(
    daily: pl.DataFrame,
    *,
    initial_capital: Decimal,
    calendar: SessionCalendar,
    window: tuple[dt.date, dt.date],
) -> ReturnsSeries:
    """The daily returns of a futures RUN's ledger on its fixed capital (ADR-0103 decision 1).

    ``daily`` is the run's ``daily.parquet`` (``trade_date``, ``closing_equity_usd``,
    ``max_contracts``); ``window`` the run's ``(start, end)`` trade dates. A trade date the ledger
    does not have is ``missing_sessions`` (excluded, never zero); a trade date with
    ``max_contracts == 0`` is a genuine zero-return observation (the strategy held nothing).

    Timing: the ledger is the run's own record of closed marks, so nothing here looks at a bar, a
    clock or a store.
    """
    _require_columns(daily, ("trade_date", "closing_equity_usd", "max_contracts"), "daily ledger")
    return _frame_returns(
        days=daily["trade_date"].to_list(),
        equity=[Decimal(value) for value in daily["closing_equity_usd"].to_list()],
        initial_capital=initial_capital,
        zero_position=[int(value) == 0 for value in daily["max_contracts"].to_list()],
        calendar=calendar,
        window=window,
        what="daily ledger",
    )


def daily_returns_from_oos(
    oos_daily: pl.DataFrame,
    *,
    initial_capital: Decimal,
    calendar: SessionCalendar,
    window: tuple[dt.date, dt.date],
) -> ReturnsSeries:
    """The daily returns of a WALK-FORWARD's out-of-sample chain on its fixed capital.

    ``oos_daily`` is ``oos_daily.parquet`` (``trade_date``, ``closing_equity_usd``,
    ``candidate``): the concatenated chain of ADR-0101, whose ``closing_equity_usd`` already
    carries every fold's net P&L and the terminal exit cost of the fold before it. The chain has
    no position column of its own, so a day counts as a zero-position day exactly when its row
    names no candidate (a fold that was evaluated FLAT because no candidate was eligible): that is
    the only position fact the chain records, and calling a selected fold's flat day anything else
    would be a guess.
    """
    _require_columns(oos_daily, ("trade_date", "closing_equity_usd", "candidate"), "OOS chain")
    return _frame_returns(
        days=oos_daily["trade_date"].to_list(),
        equity=[Decimal(value) for value in oos_daily["closing_equity_usd"].to_list()],
        initial_capital=initial_capital,
        zero_position=[value is None for value in oos_daily["candidate"].to_list()],
        calendar=calendar,
        window=window,
        what="out-of-sample chain",
    )


# ---------------------------------------------------------------------------------------------
# b. the seeded circular block bootstrap


def bootstrap_seed(owner_id: str, statistic_name: str) -> int:
    """The 64-bit seed of one statistic's interval (ADR-0103 decision 5).

    A pure function of the artifact's id (a ``FUT-`` run id, a ``WFA-`` id or a member id) and the
    statistic's NAME, so: two runs cannot share a stream, the same run reproduces its interval,
    and the interval does not depend on the order the artifacts were computed in or on how many
    threads did it. Never a global sequence.
    """
    if not owner_id:
        msg = "a bootstrap seed needs the artifact's id: pass the run, walk-forward or member id"
        raise ConfigurationError(msg)
    digest = hashlib.sha256(f"{owner_id}:{statistic_name}".encode()).hexdigest()[:16]
    return int(digest, 16)


def block_length(n: int) -> int:
    """The circular block bootstrap's block length for ``n`` observations: ``ceil(sqrt(n))``."""
    if n < 1:
        msg = f"a bootstrap block length needs at least one observation; got n={n}"
        raise ConfigurationError(msg)
    return max(1, math.ceil(math.sqrt(n)))


def circular_block_bootstrap(
    values: NDArray[np.float64],
    statistic: Callable[[NDArray[np.float64]], float],
    *,
    rng: np.random.Generator,
    resamples: int,
    length: int,
) -> NDArray[np.float64]:
    """``resamples`` circular block resamples of ``values``, each scored by ``statistic``.

    Circular: a block that runs past the end wraps to the beginning, which is what keeps every
    observation equally likely when ``n`` is not a multiple of the block length. Blocks preserve
    the local autocorrelation a daily P&L series has; an i.i.d. resample would understate the
    interval.
    """
    n = len(values)
    if n < 1:
        msg = "a bootstrap needs at least one observation"
        raise ConfigurationError(msg)
    if resamples < 1:
        msg = f"resamples = {resamples}: a bootstrap needs at least one resample"
        raise ConfigurationError(msg)
    blocks = -(-n // length)
    offsets = np.arange(length)
    out = np.empty(resamples, dtype=np.float64)
    for index in range(resamples):
        starts = rng.integers(0, n, size=blocks)
        chosen = (starts[:, None] + offsets[None, :]).ravel()[:n] % n
        out[index] = statistic(values[chosen])
    return out


def _interval(samples: NDArray[np.float64], confidence: float) -> tuple[float, float]:
    """The percentile interval of a bootstrap sample at ``confidence``."""
    alpha = (1.0 - confidence) / 2.0
    low = float(np.quantile(samples, alpha))
    high = float(np.quantile(samples, 1.0 - alpha))
    return low, high


@dataclass(frozen=True, slots=True)
class _BootstrapRecord:
    """The manifest's ``bootstrap`` block: exactly how every interval in this report was made."""

    seed: int
    block_length: int
    resamples: int
    confidence: float
    seeds: Mapping[str, int]

    def record(self, n: int) -> dict[str, object]:
        """The JSON block (``n`` is the observation count the block length was derived from)."""
        return {
            "rng": BOOTSTRAP_RNG,
            "seed": self.seed,
            "block_length_policy": BLOCK_LENGTH_POLICY,
            "block_length": self.block_length,
            "resamples": self.resamples,
            "confidence": self.confidence,
            "observations": n,
            "seeds": dict(self.seeds),
        }


# ---------------------------------------------------------------------------------------------
# c. the information coefficient


@dataclass(frozen=True, slots=True)
class InformationCoefficient:
    """One artifact's per-trade-date information coefficient (ADR-0103 decision 6).

    ``value`` is the mean of ``by_date``'s values (null when no trade date had enough pairs, with
    ``reason`` saying why). ``by_month`` groups the same values by ``YYYY-MM`` label. ``pairs`` is
    the number of (score, forward return) pairs that survived the session-edge and roll rules.
    """

    value: float | None
    by_date: Mapping[dt.date, float]
    by_month: Mapping[str, Mapping[str, object]]
    pairs: int
    horizon_bars: int
    reason: str | None = None

    @property
    def ic_days(self) -> int:
        """How many trade dates contributed an IC."""
        return len(self.by_date)

    def record(self) -> dict[str, object]:
        """The JSON block the manifest and the documents record."""
        return {
            "horizon_bars": self.horizon_bars,
            "days": self.ic_days,
            "pairs": self.pairs,
            "by_month": {month: dict(entry) for month, entry in self.by_month.items()},
            "reason": self.reason,
        }


def no_information_coefficient(reason: str, *, horizon_bars: int = 0) -> InformationCoefficient:
    """An IC that was not computed, with the reason a reader needs (never a zero)."""
    return InformationCoefficient(
        value=None,
        by_date={},
        by_month={},
        pairs=0,
        horizon_bars=horizon_bars,
        reason=reason,
    )


def _average_ranks(values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Ranks 1..n with ties averaged, so Spearman's correlation can use Pearson on the ranks."""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    index = 0
    while index < len(values):
        stop = index
        while stop + 1 < len(values) and values[order[stop + 1]] == values[order[index]]:
            stop += 1
        ranks[order[index : stop + 1]] = (index + stop) / 2.0 + 1.0
        index = stop + 1
    return ranks


def spearman(a: NDArray[np.float64], b: NDArray[np.float64]) -> float | None:
    """Spearman's rank correlation with average ties, or ``None`` when it is undefined.

    Undefined when either side is constant over the sample (a rank series with no dispersion has
    no correlation): that is a missing number, never a zero.
    """
    if len(a) != len(b) or len(a) < 2:
        return None
    ra, rb = _average_ranks(a), _average_ranks(b)
    if ra.std() == 0.0 or rb.std() == 0.0:
        return None
    da, db = ra - ra.mean(), rb - rb.mean()
    denominator = math.sqrt(float((da * da).sum()) * float((db * db).sum()))
    if denominator == 0.0:
        return None
    value = float((da * db).sum()) / denominator
    return max(-1.0, min(1.0, value))


def information_coefficient(
    outputs: pl.DataFrame,
    signal_bars: pl.DataFrame,
    *,
    horizon_bars: int,
    calendar: SessionCalendar,
    bar_seconds: int = 60,
) -> InformationCoefficient:
    """The time-series IC of a compiled signal on its own signal series (ADR-0103 decision 6).

    ``outputs``: the compiled signal's evaluation, one row per signal bar (``event_time`` and
    ``value``; a condition's booleans count as 0/1). ``signal_bars``: the same series the signal
    read (``event_time``, ``close``, ``contract``), so the forward return is the one a trader could
    have captured on that series. ``horizon_bars``: the forward horizon in BARS of the run's
    resolution. ``bar_seconds``: the bar length the trade dates are measured with.

    Rules (each one drops a pair, never fills it):

    - both bars of a pair must be on schedule and on the SAME Globex trade date (a pair across a
      session edge is a different day's return);
    - both bars must be on the same ``contract`` (a pair across a roll compares two contracts);
    - a null score or a null/zero close contributes nothing;
    - a trade date with fewer than ``MIN_IC_PAIRS`` surviving pairs gets no IC.

    Timing: the score at bar ``i`` is decided at that bar's close, and the forward return uses
    bars ``i`` and ``i + horizon`` of the signal series, so no value reads the future of the pair
    it scores. ``by_date`` is ordered by date, which makes the report (and the interval over it)
    order independent.
    """
    if horizon_bars < 1:
        msg = (
            f"ic_horizon_bars = {horizon_bars}: the information coefficient needs a forward "
            "horizon of at least one bar"
        )
        raise ConfigurationError(msg)
    for name, frame in (("signal outputs", outputs), ("signal bars", signal_bars)):
        missing = [c for c in ("event_time",) if c not in frame.columns]
        if missing:
            raise DataQualityError(f"{name} lacks {missing}: one row per bar, keyed by event_time")
    for name in ("close", "contract", "event_time"):
        if name not in signal_bars.columns:
            msg = (
                f"the signal series lacks {name!r}: the information coefficient pairs a score "
                "with a close-to-close return on the same session and contract, so it needs "
                "event_time, close and contract"
            )
            raise DataQualityError(msg)
    if "value" not in outputs.columns:
        msg = "the signal outputs lack 'value': a CompiledSignal evaluates to a score or condition"
        raise DataQualityError(msg)
    joined = (
        signal_bars.select("event_time", "close", "contract")
        .join(outputs.select("event_time", "value"), on="event_time", how="inner")
        .sort("event_time")
    )
    if joined.height != joined["event_time"].n_unique():
        msg = (
            "the signal outputs hold more than one score for the same event_time: the information "
            "coefficient needs exactly one decision per bar"
        )
        raise DataQualityError(msg)
    n = joined.height
    if n <= horizon_bars:
        return no_information_coefficient(
            f"the signal series has {n} bar(s) and the horizon is {horizon_bars}: no pair "
            "reaches a forward bar",
            horizon_bars=horizon_bars,
        )
    times = joined["event_time"].to_numpy()
    placed_days, on_schedule = session_trade_dates(calendar, times, bar_seconds)
    days = [value.astype(dt.date) for value in placed_days]  # numpy datetime64[D] -> date
    closes = joined["close"].to_numpy().astype(np.float64)
    contracts = joined["contract"].to_list()
    scores = [math.nan if value is None else float(value) for value in joined["value"].to_list()]
    collected: dict[dt.date, tuple[list[float], list[float]]] = {}
    pairs = 0
    for index in range(n - horizon_bars):
        forward = index + horizon_bars
        if not (on_schedule[index] and on_schedule[forward]):
            continue
        if days[index] != days[forward] or contracts[index] != contracts[forward]:
            continue
        score, start_close, end_close = scores[index], closes[index], closes[forward]
        if not (math.isfinite(score) and math.isfinite(start_close) and math.isfinite(end_close)):
            continue
        if start_close == 0.0:
            continue
        buckets = collected.setdefault(days[index], ([], []))
        buckets[0].append(score)
        buckets[1].append((end_close - start_close) / start_close)
        pairs += 1
    by_date: dict[dt.date, float] = {}
    for day in sorted(collected):
        day_scores, day_returns = collected[day]
        if len(day_scores) < MIN_IC_PAIRS:
            continue
        value = spearman(
            np.asarray(day_scores, dtype=np.float64),
            np.asarray(day_returns, dtype=np.float64),
        )
        if value is not None:
            by_date[day] = value
    if not by_date:
        return no_information_coefficient(
            "no trade date had at least "
            f"{MIN_IC_PAIRS} valid (score, forward return) pairs on one session and one contract "
            f"(the window held {pairs} pair(s) in total); an IC needs more than that to mean "
            "anything",
            horizon_bars=horizon_bars,
        )
    months: dict[str, list[float]] = {}
    for day, value in by_date.items():
        months.setdefault(f"{day.year:04d}-{day.month:02d}", []).append(value)
    by_month = {
        month: {
            "ic_mean": float(np.mean(values)),
            "ic_days": len(values),
        }
        for month, values in sorted(months.items())
    }
    return InformationCoefficient(
        value=float(np.mean(list(by_date.values()))),
        by_date=by_date,
        by_month=by_month,
        pairs=pairs,
        horizon_bars=horizon_bars,
    )


# ---------------------------------------------------------------------------------------------
# d. the report


def _null_reason(values: NDArray[np.float64], what: str) -> str | None:
    """Why a Sharpe-like statistic cannot be computed, or None when it can."""
    if len(values) < DEFAULT_MIN_COMPUTED:
        return (
            f"{what} needs at least {DEFAULT_MIN_COMPUTED} daily return observations; this "
            f"artifact has {len(values)}. Widen the window or re-run the artifact"
        )
    if is_degenerate_returns(values):
        return (
            f"{what} is undefined: the daily returns have no dispersion (a strategy that never "
            "held a position, or one whose equity grew by the same fraction every trade date), so "
            "the Sharpe ratio does not exist. This is not a Sharpe of zero"
        )
    return None


def futures_statistics(
    returns: ReturnsSeries,
    *,
    owner_id: str,
    total_trials: int,
    trial_sharpes: Sequence[float],
    config: StatisticsConfig,
    ic: InformationCoefficient | None = None,
) -> dict[str, object]:
    """The C6a statistics of one returns series (ADR-0103): metrics plus the manifest block.

    Returns ``{"metrics": {...}, "block": {...}}``:

    - ``metrics`` maps each of :data:`STATISTICS_METRICS` to the futures metric shape
      ``{value, ci_low, ci_high, assessment, unit, method, reason}``. The per-period Sharpe, the
      annualized Sharpe (presentation only, ``x sqrt(252)``), the mean daily return and the mean IC
      carry a percentile interval (``assessment: "inferential"``); PSR and DSR are probabilities
      computed in closed form, so they are ``inferential`` with null intervals and a ``method``
      note. A statistic that cannot be computed is null with a ``reason``, never a zero.
    - ``block`` is the manifest's ``statistics`` block: the returns convention, the annualization,
      the bootstrap recipe (rng, seed, block length policy and value, resamples, confidence), the
      trial counts and the IC record. ``submission_count`` and ``unique_candidate_count`` are the
      caller's (registry) business; ``total_trials`` is the one the deflation used.

    Timing: a pure function of its arguments. Determinism: every interval is seeded by
    ``bootstrap_seed(owner_id, name)``, so the numbers do not depend on the order the artifacts
    were computed in, and a thread pool computing several series reproduces them exactly.
    """
    values = returns.returns
    n = len(values)
    if total_trials < 1:
        msg = (
            f"total_trials = {total_trials}: a deflation needs the trial being evaluated to be "
            "itself one, so the count must be at least 1"
        )
        raise ConfigurationError(msg)
    reasons = _null_reason(values, "the annualized Sharpe")
    confidence = float(config.confidence)
    resamples = int(config.resamples)
    length = block_length(n) if n else 0
    seeds: dict[str, int] = {}
    samples: dict[str, NDArray[np.float64]] = {}
    if reasons is None:
        for name, statistic in (
            (
                "sharpe_per_period",
                per_period_sharpe,
            ),
            (
                "sharpe_annualized",
                lambda r: per_period_sharpe(r) * math.sqrt(ANNUALIZATION_PERIODS_PER_YEAR),
            ),
            ("mean_daily_return", _mean_daily_return),
        ):
            seed = bootstrap_seed(owner_id, name)
            seeds[name] = seed
            samples[name] = circular_block_bootstrap(
                values,
                statistic,
                rng=np.random.Generator(np.random.PCG64(seed)),
                resamples=resamples,
                length=length,
            )

    metrics: dict[str, dict[str, object]] = {}
    if reasons is None:
        sharpe = per_period_sharpe(values)
        annualized = sharpe * math.sqrt(ANNUALIZATION_PERIODS_PER_YEAR)
        sharpe_low, sharpe_high = _interval(samples["sharpe_per_period"], confidence)
        annual_low, annual_high = _interval(samples["sharpe_annualized"], confidence)
        mean_low, mean_high = _interval(samples["mean_daily_return"], confidence)
        metrics["sharpe_per_period"] = _metric(
            sharpe,
            "sharpe",
            assessment="inferential",
            ci_low=sharpe_low,
            ci_high=sharpe_high,
        )
        metrics["sharpe_annualized"] = _metric(
            annualized,
            "sharpe",
            assessment="inferential",
            ci_low=annual_low,
            ci_high=annual_high,
        )
        metrics["mean_daily_return"] = _metric(
            _mean_daily_return(values),
            "fraction",
            assessment="inferential",
            ci_low=mean_low,
            ci_high=mean_high,
        )
    else:
        metrics["sharpe_per_period"] = _metric(
            None, "sharpe", assessment="inferential", reason=reasons
        )
        metrics["sharpe_annualized"] = _metric(
            None, "sharpe", assessment="inferential", reason=reasons
        )
        metrics["mean_daily_return"] = _metric(
            None if n == 0 else _mean_daily_return(values),
            "fraction",
            assessment="descriptive",
            reason=None if n == 0 else reasons,
        )

    metrics["psr"] = _psr_metric(values, reasons)
    metrics["dsr"] = _dsr_metric(
        values, reasons, total_trials=total_trials, trial_sharpes=trial_sharpes
    )
    metrics["ic_mean"] = _ic_metric(
        ic,
        owner_id=owner_id,
        seeds=seeds,
        confidence=confidence,
        resamples=resamples,
    )

    record = _BootstrapRecord(
        seed=seeds.get("sharpe_per_period", bootstrap_seed(owner_id, "sharpe_per_period")),
        block_length=length,
        resamples=resamples,
        confidence=confidence,
        seeds=seeds,
    )
    ic_record: dict[str, object] = (
        no_information_coefficient(
            "the run records no information coefficient", horizon_bars=config.ic_horizon_bars
        ).record()
        if ic is None
        else ic.record()
    )
    block: dict[str, object] = {
        "returns_convention": RETURNS_CONVENTION,
        "annualization": dict(ANNUALIZATION),
        "bootstrap": record.record(n),
        "trials": {
            "total_trials": int(total_trials),
            "trials_with_sharpe": len(trial_sharpes),
        },
        "observations": n,
        "missing_sessions": returns.missing_sessions,
        "zero_position_days": returns.zero_position_days,
        "ic": ic_record,
    }
    return {"metrics": metrics, "block": block}


def _mean_daily_return(values: NDArray[np.float64]) -> float:
    """The arithmetic mean of the daily returns (a fraction of the fixed capital per trade date)."""
    return float(values.mean()) if len(values) else 0.0


def _psr_metric(values: NDArray[np.float64], reasons: str | None) -> dict[str, object]:
    """PSR against a benchmark of 0, on the per-period Sharpe (ADR-0015)."""
    if reasons is not None:
        return _metric(
            None, "probability", assessment="inferential", method=PSR_METHOD, reason=reasons
        )
    try:
        value = probabilistic_sharpe_ratio(
            per_period_sharpe(values),
            0.0,
            len(values),
            skewness(values),
            pearson_kurtosis(values),
        )
    except CrucibleError as exc:  # a non-positive PSR denominator is refused, not scored
        return _metric(
            None, "probability", assessment="inferential", method=PSR_METHOD, reason=str(exc)
        )
    return _metric(value, "probability", assessment="inferential", method=PSR_METHOD)


def _dsr_metric(
    values: NDArray[np.float64],
    reasons: str | None,
    *,
    total_trials: int,
    trial_sharpes: Sequence[float],
) -> dict[str, object]:
    """DSR deflated by ``total_trials`` over the family's distinct candidate Sharpes (ADR-0103)."""
    if reasons is not None:
        return _metric(
            None, "probability", assessment="inferential", method=DSR_METHOD, reason=reasons
        )
    if len(trial_sharpes) < 2:
        reason = (
            "DSR needs at least 2 distinct candidate Sharpe ratios to estimate the cross-trial "
            f"dispersion of the expected maximum Sharpe; this family has {len(trial_sharpes)} "
            f"(over {total_trials} trial(s)). It is never computed from an invented variance: "
            "evaluate a second candidate to deflate against it"
        )
        return _metric(
            None, "probability", assessment="inferential", method=DSR_METHOD, reason=reason
        )
    try:
        result = deflated_sharpe_ratio(values, trial_sharpes, n_trials=total_trials)
    except CrucibleError as exc:  # a refused series (degenerate, non-finite) is null
        return _metric(
            None, "probability", assessment="inferential", method=DSR_METHOD, reason=str(exc)
        )
    return _metric(result.dsr, "probability", assessment="inferential", method=DSR_METHOD)


def _ic_metric(
    ic: InformationCoefficient | None,
    *,
    owner_id: str,
    seeds: dict[str, int],
    confidence: float,
    resamples: int,
) -> dict[str, object]:
    """The mean IC with a block-bootstrap interval over its daily values (ADR-0103 decision 6)."""
    if ic is None:
        return _metric(
            None,
            IC_UNIT,
            assessment="inferential",
            method=IC_METHOD,
            reason="no information coefficient was recorded for this artifact",
        )
    if ic.value is None:
        return _metric(
            None,
            IC_UNIT,
            assessment="inferential",
            method=IC_METHOD,
            reason=ic.reason,
        )
    daily = np.asarray([value for _, value in sorted(ic.by_date.items())], dtype=np.float64)
    if len(daily) < 2:
        return _metric(
            ic.value,
            IC_UNIT,
            assessment="inferential",
            method=IC_METHOD,
            reason=(
                f"the mean IC rests on {len(daily)} trade date(s), too few for an interval; the "
                "value is reported without one"
            ),
        )
    seed = bootstrap_seed(owner_id, "ic_mean")
    seeds["ic_mean"] = seed
    samples = circular_block_bootstrap(
        daily,
        lambda r: float(r.mean()),
        rng=np.random.Generator(np.random.PCG64(seed)),
        resamples=resamples,
        length=block_length(len(daily)),
    )
    low, high = _interval(samples, confidence)
    return _metric(
        ic.value, IC_UNIT, assessment="inferential", ci_low=low, ci_high=high, method=IC_METHOD
    )


__all__ = [
    "ANNUALIZATION",
    "BLOCK_LENGTH_POLICY",
    "BOOTSTRAP_RNG",
    "DEFAULT_MIN_COMPUTED",
    "DSR_METHOD",
    "IC_METHOD",
    "IC_UNIT",
    "MIN_IC_PAIRS",
    "PSR_METHOD",
    "RETURNS_CONVENTION",
    "STATISTICS_METRICS",
    "STATISTICS_METRIC_UNITS",
    "InformationCoefficient",
    "ReturnsSeries",
    "StatisticsConfig",
    "block_length",
    "bootstrap_seed",
    "circular_block_bootstrap",
    "daily_returns",
    "daily_returns_from_oos",
    "futures_statistics",
    "information_coefficient",
    "no_information_coefficient",
    "spearman",
]
