"""Cross-run metrics and a DESCRIPTIVE daily P&L correlation against the artifact pool (C5c).

C5c is the last of the three C5 stages (ADR-0100, ADR-0101): after a run has been produced, it can
be read back and compared with what the artifacts folder already holds. This module is that read.
Nothing here simulates, so nothing here can change a result; the only file it writes is
``<artifacts_root>/<CMP-ID>/cross_run.json``, outside every sealed run directory (ADR-0102).

Hard restriction (ADR-0095, ADR-0097, ADR-0100, ADR-0101, ADR-0102): there is no Sharpe, no IC, no
PSR, no DSR, no p-value, no confidence interval, no shrinkage and no significance anywhere in this
module, and the pool is NEVER sorted by a statistic. A correlation is a descriptive number of the
overlapping trade dates, reported with null intervals (``assessment: "descriptive"``) and the
verdict ``not_assessed`` (ADR-0097's reason). C6 is the first stage allowed to add inference.

The four rules that make the number honest:

- **A member's daily P&L is marked P&L.** For a sealed futures run it is
  ``closing_equity_usd - opening_equity_usd`` of each ``daily.parquet`` row; for a walk-forward
  it is ``net_pnl_usd`` (marked: final equity minus capital, after the fold's terminal exit)
  of each ``oos_daily.parquet`` row. The member total reported here is ``marked_pnl_usd``,
  the sum of those marks, and a run also reports ``realized_pnl_usd`` (its own
  ``metrics.json`` ``net_pnl_usd``: final BALANCE minus capital). The two differ by the mark
  of a position still open at the last bar, and this module never reuses the run's own key
  for a different meaning (``docs/COMPATIBILITY.md`` §3). A trade date a member does not
  have is
  MISSING, never zero (a zero would be an invented flat day); a walk-forward's flat fold does have
  real zero rows, because being flat was a decision (ADR-0101 decision 3).
- **The correlation is computed on the intersection of the trade dates** (an inner join: no fill,
  no reindex, no forward fill). Fewer overlapping dates than ``min_overlap_trade_dates`` (default
  20, never below 10) means ``insufficient_overlap`` and no value; a constant series over the
  overlap means ``constant_series`` and no value.
- **Compatibility is a key, not a judgement.** Two members are correlated only when their
  ``comparison_key`` is equal: the simulator version, the fidelity level, the execution section, the
  session section and the signal input. Root, size, costs, strategy, window, family and capital are
  NOT part of it (a USD daily P&L is scale free, and cross-asset pools are the point); a pair that
  differs is reported ``incompatible`` with the differing dotted paths.
- **An unverifiable member is listed, never dropped.** A run whose seal does not verify (or a
  walk-forward one of whose test runs does not) is ``unverified`` with no value and no metrics.

Position facts, stated because they are the ones a reader will check:

- **Trades** are position episodes: a maximal run of bars whose position has the same non-zero
  sign. An episode still open at the member's last bar counts. A fill that flips a position from
  long to short (+1 to -1 in one bar, the position never passing through zero at a bar close) ends
  one episode and starts another, so a flip counts as ONE episode ending and ONE starting (two
  episodes, not one and not zero).
- **Turnover** is the sum of ``|Δposition|`` in contracts, in total and per trade date, with the
  position at the member's start taken as flat (0) and a trade date's first bar measuring against
  the previous trade date's last position. A roll keeps the net position, so it adds no turnover; it
  is counted in ``fills``/``rolls`` instead.
- **``days_in_market``** counts the trade dates on which the member held a position on at least one
  bar (``max_contracts > 0``).
- **Drawdowns** are conservative on both counts: the closing drawdown is peak-to-trough on the daily
  closing equity, with the opening equity (capital) as the first peak, and the intraday drawdown is
  the same rule ``build_metrics`` applies (the low mark against a running maximum of the high mark),
  so an intrabar extreme is not averaged away.

Units: money in USD, kept as exact ``Decimal`` while the arithmetic runs and rounded to 6 decimals
only in the reported ``value``; turnover in contracts; trade dates as ``YYYY-MM-DD`` labels (a
Globex trade date is a day label, never an instant, ADR-0091).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict

from crucible.core.canonical import canonical_json
from crucible.core.errors import ConfigurationError, ExperimentError, InvariantViolation
from crucible.execution.futures_sim import SIMULATOR_VERSION
from crucible.experiments.artifact_id import verify_artifact
from crucible.experiments.futures_config import FuturesRunConfig, load_futures_config
from crucible.experiments.futures_document import (
    DEFAULT_FIDELITY,
    FuturesVerdictDocument,
    MetricUnit,
    verdict_document,
)

COMPARE_SCHEMA_VERSION = 1
"""Version of ``cross_run.json`` (``docs/COMPATIBILITY.md`` §3: adding a key is additive;
removing, renaming or changing the meaning of one bumps this)."""

CMP_ID_PREFIX = "CMP-"
"""Prefix of a comparison id."""

CMP_ID_HEX = 16
"""Hex digits of the SHA-256 kept in the comparison id (64 bits, like every other id)."""

FUTURES_RUN_PREFIX = "FUT-"
"""Directory prefix of a sealed futures run (ADR-0095): a pool member of kind ``futures_run``."""

WALKFORWARD_PREFIX = "WFA-"
"""Directory prefix of a walk-forward (ADR-0101): a pool member of kind ``futures_walkforward``."""

DEFAULT_MIN_OVERLAP_TRADE_DATES = 20
"""Default number of overlapping trade dates a correlation needs (ADR-0102 decision 5)."""

MIN_OVERLAP_FLOOR = 10
"""The lowest ``min_overlap_trade_dates`` a comparison accepts: fewer overlapping dates cannot
support even a descriptive reading of two P&L series, so the option is refused rather than honoured
(ADR-0102 decision 5)."""

CORRELATION_UNIT = "correlation"
"""The unit of a correlation: dimensionless, hence not one of the metric units."""

CORRELATION_NOTE = (
    "Pearson's correlation of the two members' daily USD P&L over the trade dates they BOTH have "
    "(an inner join: nothing is filled, so a date missing from either series is excluded). It is "
    "descriptive only: no interval, no significance, no claim of edge, and the pool is "
    "never sorted by it (ADR-0102)."
)
"""Recorded in ``cross_run.json`` so a reader knows exactly what the number is."""

MemberKind = Literal["futures_run", "futures_walkforward"]
"""The two artifacts that can be a target or a pool member (ADR-0102 decision 1)."""

MemberStatus = Literal["verified", "unverified"]
"""Whether the member's seal verified. ``unverified`` members are listed with no value."""

CorrelationStatus = Literal["ok", "insufficient_overlap", "constant_series"]
"""What a correlation could do: it was computed, there were too few overlapping trade dates, or one
of the series is constant over the overlap (which makes the coefficient undefined)."""

PoolStatus = Literal["ok", "incompatible", "insufficient_overlap", "constant_series", "unverified"]
"""The status of one pool member against the target, in order of precedence: an unverifiable member
is ``unverified``; a member whose comparison key differs is ``incompatible``; otherwise the
correlation's own status."""

POOL_STATUSES: tuple[PoolStatus, ...] = (
    "ok",
    "incompatible",
    "insufficient_overlap",
    "constant_series",
    "unverified",
)
"""Every pool status, in the order the summary counts them."""

COMPARE_METRIC_UNITS: dict[str, MetricUnit] = {
    "marked_pnl_usd": "usd",
    "realized_pnl_usd": "usd",
    "total_costs_usd": "usd",
    "max_drawdown_usd": "usd",
    "max_intraday_drawdown_usd": "usd",
    "trades": "count",
    "fills": "count",
    "turnover_contracts": "contracts",
    "trade_dates": "trade_dates",
    "days_in_market": "trade_dates",
}
"""The unit of every cross-run metric, in reading order: what the member made on its marks,
what it banked, what it cost, its closing and intraday drawdown, its position episodes, its
fills, the contracts it turned over, the trade dates it covers and the ones it was in the
market on. ``marked_pnl_usd`` is the sum of the daily MARKED P&L (final closing equity minus
capital; for a walk-forward its `oos` series, terminal exit included) and
``realized_pnl_usd`` is the run's own ``metrics.json`` ``net_pnl_usd`` (final BALANCE minus
capital), null for a walk-forward, which has no balance of its own.
``max_drawdown_usd`` is peak-to-trough on the daily CLOSING equity;
``max_intraday_drawdown_usd`` is the conservative OHLC one (``build_metrics``' rule)."""

RUN_ID_PREFIXES = (FUTURES_RUN_PREFIX, WALKFORWARD_PREFIX)
"""The directory prefixes that name a comparison member. Anything else under the artifacts root
(``BAT-``, ``CMP-``, an ``EXP-`` equity run, loose files) is not a member."""


# ---------------------------------------------------------------------------------------------
# a. reading the members


@dataclass(frozen=True, slots=True)
class Member:
    """One artifact read as a comparison member: its daily P&L series and its descriptive facts.

    ``net`` is the daily MARKED P&L by trade date (a date the member does not have is
    ABSENT, never zero) and ``realized`` is the run's own realized total (final balance minus
    capital), which only a futures run has.

    ``status`` is ``unverified`` when the seal (of the run, or of a walk-forward's test runs) does
    not verify: then every series is empty, ``key`` is null and ``detail`` says what failed. An
    unverified member is never dropped from a comparison; it is listed with no value.
    """

    member_id: str
    kind: MemberKind
    directory: Path
    status: MemberStatus
    detail: str | None
    net: Mapping[dt.date, Decimal]
    closing_equity: Mapping[dt.date, Decimal]
    opening_equity: Decimal
    realized: Decimal | None
    costs: Decimal
    intraday_drawdown: Decimal
    trades: int
    fills: int
    turnover: Mapping[dt.date, int]
    in_market: frozenset[dt.date]
    fold_oos: tuple[Decimal, ...]
    key: Mapping[str, object] | None

    @property
    def verified(self) -> bool:
        """The seal verified, so the member's series and metrics can be read."""
        return self.status == "verified"


def _parquet(path: Path, what: str) -> pl.DataFrame:
    """``path`` read as a frame, or a refusal naming the file and what it belongs to."""
    try:
        return pl.read_parquet(path)
    except (OSError, pl.exceptions.PolarsError) as exc:
        msg = (
            f"cannot read the {what} at {path} ({exc}): a comparison member is a "
            "sealed futures run or walk-forward directory, so its result files must "
            "still be there. Re-run the artifact, or drop the directory from the "
            "artifacts root"
        )
        raise ExperimentError(msg).at(path=str(path)) from exc


def _json_object(path: Path, what: str) -> dict[str, object]:
    """``path`` read as a JSON object, or a refusal naming the file and what it belongs to."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = (
            f"cannot read the {what} at {path} ({exc}): a comparison member is a "
            "sealed futures run or walk-forward directory. Re-run the artifact, or "
            "drop the directory from the artifacts root"
        )
        raise ExperimentError(msg).at(path=str(path)) from exc
    if not isinstance(raw, dict):
        msg = f"the {what} at {path} does not hold a JSON object: it is not a Crucible artifact"
        raise ExperimentError(msg).at(path=str(path))
    return {str(key): value for key, value in raw.items()}


def _money(series: pl.Series) -> tuple[Decimal, ...]:
    return tuple(Decimal(value) for value in series.to_list())


def _fidelity_record(manifest: Mapping[str, object]) -> dict[str, object]:
    """The manifest's ``fidelity`` block reduced to the three fields the key compares.

    A manifest written before C5a records no ``fidelity``: it simulated the stored one-minute series
    with the full cost model, so it reads as ``1m`` + ``full`` + table version ``1``
    (``DEFAULT_FIDELITY``), exactly as the futures document reads it.
    """
    raw = manifest.get("fidelity", DEFAULT_FIDELITY)
    if not isinstance(raw, dict):
        msg = (
            f"the manifest records fidelity={raw!r}, which is not an object: the comparison key "
            "compares {resolution, cost_detail, table_version}"
        )
        raise ExperimentError(msg)
    out: dict[str, object] = {}
    for name in ("resolution", "cost_detail", "table_version"):
        value = raw.get(name, DEFAULT_FIDELITY[name])
        out[name] = str(value)
    return out


def _key_from_config(
    config: FuturesRunConfig,
    fidelity: Mapping[str, object],
) -> dict[str, object]:
    """The comparison key of a run whose sealed config and fidelity record are known (decision 4).

    Only what decides how a target became a fill and a mark is in it: the simulator version, the
    fidelity level, the execution section (fill timing, roll execution, strictness, bracket
    policy), the session section and the signal input. Root, contract count, cost amounts,
    strategy, window, family and capital are deliberately absent: a USD daily P&L does not depend on
    scale, and a cross-asset pool is the point of the comparison.
    """
    execution = config.execution
    session = config.session
    entry_window = session.entry_window
    return {
        "simulator_version": SIMULATOR_VERSION,
        "fidelity": dict(fidelity),
        "execution": {
            "fill": execution.fill,
            "roll_execution": execution.roll_execution,
            "strict": execution.strict,
            "brackets": {
                "stop_ticks": execution.stop_ticks,
                "target_ticks": execution.target_ticks,
                "target_fill_through_ticks": execution.target_fill_through_ticks,
                "reentry": execution.reentry,
            },
        },
        "session": {
            "flat_by_close": session.flat_by_close,
            "exit_at": session.exit_at,
            "entry_window": (
                None if entry_window is None else [str(entry_window[0]), str(entry_window[1])]
            ),
            "allow_unverified_sessions": session.allow_unverified_sessions,
        },
        "signal": {"input": config.signal.input},
    }


def _episodes(positions: Sequence[int]) -> int:
    """Position episodes: a maximal run of bars with the same non-zero SIGN.

    A flip from long to short (+1 to -1 without a zero bar) ends one episode and starts another, so
    it counts two; an episode still open at the last bar counts one (it was entered).
    """
    count = 0
    sign = 0
    for position in positions:
        current = (position > 0) - (position < 0)
        if current != 0 and current != sign:
            count += 1
        sign = current
    return count


def _position_facts(
    marks: pl.DataFrame,
) -> tuple[int, dict[dt.date, int], frozenset[dt.date]]:
    """``(trades, turnover per trade date, trade dates in market)`` from one run's marks.

    The position before the run's first bar is flat, and a trade date's first bar measures against
    the previous trade date's last position, so the turnover of a date is exactly the contracts
    traded on it.
    """
    dates = marks["trade_date"].to_list()
    positions = [int(value) for value in marks["position"].to_list()]
    turnover: dict[dt.date, int] = {}
    in_market: set[dt.date] = set()
    previous = 0
    for day, position in zip(dates, positions, strict=True):
        turnover[day] = turnover.get(day, 0) + abs(position - previous)
        if position != 0:
            in_market.add(day)
        previous = position
    return _episodes(positions), turnover, frozenset(in_market)


def _intraday_drawdown(marks: pl.DataFrame) -> Decimal:
    """The conservative intrabar drawdown of one run: the low mark against a running high mark.

    Same rule as ``futures_artifacts.build_metrics`` (``equity_low_usd`` against a running maximum
    of ``equity_high_usd``), so a stop that filled inside a bar is not averaged away.
    """
    low = _money(marks["equity_low_usd"])
    high = _money(marks["equity_high_usd"])
    if not low:
        return Decimal(0)
    running = high[0]
    drawdown = Decimal(0)
    for low_mark, high_mark in zip(low, high, strict=True):
        running = max(running, high_mark)
        drawdown = max(drawdown, running - low_mark)
    return drawdown


def _run_member(directory: Path, member_id: str) -> Member:
    """A sealed futures run read as a member: the daily ledger, the marks and the fills."""
    verify_artifact(directory)
    daily = _parquet(directory / "daily.parquet", "daily ledger")
    marks = _parquet(directory / "marks.parquet", "marks")
    fills = _parquet(directory / "fills.parquet", "fills")
    dates = tuple(daily["trade_date"].to_list())
    opening = _money(daily["opening_equity_usd"])
    closing = _money(daily["closing_equity_usd"])
    trades, turnover, in_market = _position_facts(marks)
    manifest = _json_object(directory / "manifest.json", "manifest")
    config = load_futures_config(directory / "config.yaml")
    return Member(
        member_id=member_id,
        kind="futures_run",
        directory=directory,
        status="verified",
        detail=None,
        net={day: close - open_ for day, open_, close in zip(dates, opening, closing, strict=True)},
        closing_equity=dict(zip(dates, closing, strict=True)),
        opening_equity=opening[0],
        realized=Decimal(daily["closing_balance_usd"][-1]) - opening[0],
        costs=sum(_money(daily["costs_usd"]), Decimal(0)),
        intraday_drawdown=_intraday_drawdown(marks),
        trades=trades,
        fills=fills.height,
        turnover=turnover,
        in_market=in_market,
        fold_oos=(),
        key=_key_from_config(config, _fidelity_record(manifest)),
    )


def _fold_rows(document: Mapping[str, object], directory: Path) -> list[Mapping[str, object]]:
    """The walk-forward document's ``folds`` list, validated enough to be read."""
    folds = document.get("folds")
    if not isinstance(folds, list) or not all(isinstance(fold, dict) for fold in folds):
        msg = (
            f"the walk-forward document at {directory / 'walkforward.json'} has no folds list: a "
            "comparison member is a walk-forward directory written by `crucible futures "
            "walkforward` (ADR-0101)"
        )
        raise ExperimentError(msg).at(path=str(directory))
    return [fold for fold in folds if isinstance(fold, dict)]


def _audit_rows(document: Mapping[str, object]) -> list[Mapping[str, object]]:
    """The ``in_sample_audit.folds`` list of a walk-forward document (may be empty)."""
    audit = document.get("in_sample_audit")
    if not isinstance(audit, dict):
        return []
    folds = audit.get("folds")
    if not isinstance(folds, list):
        return []
    return [fold for fold in folds if isinstance(fold, dict)]


def _run_id(entry: Mapping[str, object]) -> str | None:
    """The ``run_id`` an entry records, or null when it has none (a flat fold has none)."""
    run_id = entry.get("run_id")
    return run_id if isinstance(run_id, str) else None


def _test_run_id(fold: Mapping[str, object]) -> str | None:
    """The ``run_id`` of a fold's ``oos`` block, or null when the fold selected nothing."""
    oos = fold.get("oos")
    if not isinstance(oos, dict):
        return None
    return _run_id(oos)


def walkforward_run_ids(directory: Path) -> tuple[str, ...]:
    """Every run a walk-forward owns: its test runs and its training runs, sorted.

    A comparison of a walk-forward excludes exactly these from the pool (decision 1): its own
    training and test runs are that walk-forward's inputs, not independent members. Everything else
    stays in the pool, including the runs of another walk-forward.
    """
    document = _json_object(directory / "walkforward.json", "walk-forward document")
    ids: set[str] = set()
    for fold in _fold_rows(document, directory):
        run_id = _test_run_id(fold)
        if run_id is not None:
            ids.add(run_id)
    for fold in _audit_rows(document):
        candidates = fold.get("candidates")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            train_id = _run_id(candidate)
            if train_id is not None:
                ids.add(train_id)
    return tuple(sorted(ids))


def _walkforward_member(
    directory: Path,
    member_id: str,
    artifacts_root: Path,
) -> Member:
    """A walk-forward read as a member: its concatenated OOS series plus its test runs' marks."""
    document = _json_object(directory / "walkforward.json", "walk-forward document")
    oos = _parquet(directory / "oos_daily.parquet", "out-of-sample series")
    for column in ("trade_date", "fold", "net_pnl_usd", "costs_usd", "closing_equity_usd"):
        if column not in oos.columns:
            msg = (
                f"the out-of-sample series at {directory / 'oos_daily.parquet'} has no {column!r} "
                "column: a walk-forward member is read from oos_daily.parquet (ADR-0101)"
            )
            raise ExperimentError(msg).at(path=str(directory))
    dates = tuple(oos["trade_date"].to_list())
    net = _money(oos["net_pnl_usd"])
    closing = _money(oos["closing_equity_usd"])
    if not dates:
        msg = (
            f"the out-of-sample series at {directory / 'oos_daily.parquet'} has no row: a "
            "walk-forward always evaluates at least one fold, so an empty series is not one"
        )
        raise ExperimentError(msg).at(path=str(directory))
    folds = [int(value) for value in oos["fold"].to_list()]
    fold_order: list[int] = []
    fold_net: dict[int, Decimal] = {}
    for _day, fold_index, value in zip(dates, folds, net, strict=True):
        if fold_index not in fold_net:
            fold_order.append(fold_index)
            fold_net[fold_index] = Decimal(0)
        fold_net[fold_index] += value
    trades = 0
    fills = 0
    turnover: dict[dt.date, int] = {}
    in_market: set[dt.date] = set()
    drawdown = Decimal(0)
    for fold_row in _fold_rows(document, directory):
        run_id = _test_run_id(fold_row)
        if run_id is None:
            continue  # a flat fold has no run and contributes no position facts
        run_dir = artifacts_root / run_id
        verify_artifact(run_dir)
        marks = _parquet(run_dir / "marks.parquet", f"marks of the test run {run_id}")
        run_fills = _parquet(run_dir / "fills.parquet", f"fills of the test run {run_id}")
        fold_trades, fold_turnover, fold_in_market = _position_facts(marks)
        trades += fold_trades
        fills += run_fills.height
        for day, traded in fold_turnover.items():
            turnover[day] = turnover.get(day, 0) + traded
        in_market |= fold_in_market
        drawdown = max(drawdown, _intraday_drawdown(marks))
    key = _walkforward_key(directory, artifacts_root, document)
    return Member(
        member_id=member_id,
        kind="futures_walkforward",
        directory=directory,
        status="verified",
        detail=None,
        net=dict(zip(dates, net, strict=True)),
        closing_equity=dict(zip(dates, closing, strict=True)),
        opening_equity=closing[0] - net[0],
        realized=None,  # a walk-forward has no balance of its own: only the marked chain
        costs=sum(_money(oos["costs_usd"]), Decimal(0)),
        intraday_drawdown=drawdown,
        trades=trades,
        fills=fills,
        turnover=turnover,
        in_market=frozenset(in_market),
        fold_oos=tuple(fold_net[index] for index in fold_order),
        key=key,
    )


def _walkforward_key(
    directory: Path, artifacts_root: Path, document: Mapping[str, object]
) -> dict[str, object]:
    """A walk-forward's comparison key: its BASE config's key (decision 4).

    A fold's runs change only the strategy, the run name and the window of the base
    config (ADR-0101 decision 3), so the base's execution, session and signal sections
    are the ones a fold's sealed ``config.yaml`` carries, and the walk-forward document
    records the base's ``fidelity`` block. The key is therefore read from the
    walk-forward's own files: no config file has to travel with it.
    """
    run_ids = walkforward_run_ids(directory)
    for run_id in run_ids:
        run_dir = artifacts_root / run_id
        config_path = run_dir / "config.yaml"
        if not config_path.is_file():
            continue
        config = load_futures_config(config_path)
        return _key_from_config(config, _fidelity_record(document))
    msg = (
        f"the walk-forward at {directory} names no run whose sealed config could be read: its "
        "comparison key is its base config's execution, session and signal sections, taken from a "
        "fold's own run. A walk-forward with no run at all is not a member"
    )
    raise ExperimentError(msg).at(path=str(directory))


def _kind_of(member_id: str) -> MemberKind:
    """The kind a member id names, from its prefix."""
    if member_id.startswith(FUTURES_RUN_PREFIX):
        return "futures_run"
    if member_id.startswith(WALKFORWARD_PREFIX):
        return "futures_walkforward"
    msg = (
        f"{member_id!r} is not a futures run or a walk-forward id: a comparison member is a "
        f"sealed `{FUTURES_RUN_PREFIX}...` run (ADR-0095) or a `{WALKFORWARD_PREFIX}...` "
        "walk-forward (ADR-0101). An equity artifact is compared with `crucible compare`"
    )
    raise ConfigurationError(msg)


def _unverified(member_id: str, kind: MemberKind, directory: Path, detail: str) -> Member:
    """The member of a directory whose seal or files could not be read: listed, with no value."""
    return Member(
        member_id=member_id,
        kind=kind,
        directory=directory,
        status="unverified",
        detail=detail,
        net={},
        closing_equity={},
        opening_equity=Decimal(0),
        realized=None,
        costs=Decimal(0),
        intraday_drawdown=Decimal(0),
        trades=0,
        fills=0,
        turnover={},
        in_market=frozenset(),
        fold_oos=(),
        key=None,
    )


def load_member(artifacts_root: Path, member_id: str) -> Member:
    """Read the artifact ``member_id`` under ``artifacts_root`` as a comparison member.

    ``FUT-`` members are read from their daily ledger (daily P&L, closing equity, costs) and their
    marks (episodes, turnover, days in market, the conservative intraday drawdown) and fills;
    ``WFA-`` members from ``oos_daily.parquet`` (the concatenated out-of-sample series)
    plus the marks and fills of their test runs, a flat fold contributing nothing. Every
    seal involved is verified first: a member that does not verify is returned with
    status ``unverified`` and the reason in its ``detail``, never dropped, never read as
    if it were sound (ADR-0102 decision 1).

    Refuses an id that is not a member id, and a directory that does not exist (that is a caller
    error: the pool is built by listing the artifacts root).
    """
    kind = _kind_of(member_id)
    directory = artifacts_root / member_id
    if not directory.is_dir():
        msg = (
            f"no comparison member {member_id!r} under {artifacts_root}: pass the artifacts root "
            "that holds the run, or run it first with `crucible futures run`"
        )
        raise ConfigurationError(msg).at(path=str(directory), member_id=member_id)
    try:
        if kind == "futures_run":
            return _run_member(directory, member_id)
        return _walkforward_member(directory, member_id, artifacts_root)
    except ExperimentError as exc:
        return _unverified(member_id, kind, directory, str(exc))


# ---------------------------------------------------------------------------------------------
# b. the comparison key


def comparison_key(member: Member) -> dict[str, object]:
    """The member's comparison key (ADR-0102 decision 4): equal keys may be correlated.

    Refuses an unverified member: its key would have to be read from files whose seal did not
    verify, and a difference in a key nobody can trust would be a misleading ``incompatible``.
    """
    if member.key is None:
        msg = (
            f"the member {member.member_id} is unverified ({member.detail}), so it has "
            "no comparison key: a key is read from the run's sealed config and "
            "manifest. Restore or re-run the artifact"
        )
        raise ConfigurationError(msg).at(member_id=member.member_id)
    return dict(member.key)


def key_diff(a: Mapping[str, object], b: Mapping[str, object]) -> list[str]:
    """The dotted paths at which two comparison keys differ, sorted (``[]`` when they agree).

    A path reported means the two members were not simulated under the same execution and session
    rules, so their daily P&L is not comparable and no correlation is computed for the pair.
    """
    out: list[str] = []
    _diff(a, b, "", out)
    return sorted(out)


def _diff(a: Mapping[str, object], b: Mapping[str, object], prefix: str, out: list[str]) -> None:
    for name in sorted(set(a) | set(b)):
        path = f"{prefix}{name}"
        left, right = a.get(name), b.get(name)
        if name not in a or name not in b:
            out.append(path)
            continue
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            _diff(left, right, f"{path}.", out)
        elif left != right:
            out.append(path)


# ---------------------------------------------------------------------------------------------
# c. the correlation


@dataclass(frozen=True, slots=True)
class CorrelationResult:
    """What two members' daily P&L series gave: a status, a value (or null) and the overlap."""

    status: CorrelationStatus
    value: float | None
    overlap_trade_dates: int
    first: dt.date | None
    last: dt.date | None


def _constant(values: Sequence[Decimal]) -> bool:
    """Whether every value is the same (an undefined coefficient, not a strong one)."""
    first = values[0]
    return all(value == first for value in values[1:])


def daily_correlation(a: Member, b: Member, *, min_overlap: int) -> CorrelationResult:
    """Pearson's correlation of two members' daily P&L over the trade dates they BOTH have.

    The join is an INNER join on ``trade_date``: a date present in one series and not in
    the other is excluded, never filled with zero (a zero would be an invented flat day,
    ADR-0102 decision 5). With fewer than ``min_overlap`` overlapping dates the status
    is ``insufficient_overlap`` and the value null; when either series is constant over
    the overlap the status is ``constant_series`` and the value null. Otherwise the
    value is the coefficient, clamped to [-1, 1] for rounding only (the unclamped value
    is asserted to be within 1e-12 of that interval first).

    The arithmetic is float64 over the exact ``Decimal`` daily P&L, so the same two series always
    give the same number. Nothing here is a test: no interval, no p-value, no significance.
    """
    if min_overlap < 1:
        msg = (
            f"min_overlap = {min_overlap}: a correlation needs at least one overlapping trade date"
        )
        raise ConfigurationError(msg)
    shared = sorted(set(a.net) & set(b.net))
    xs = [a.net[day] for day in shared]
    ys = [b.net[day] for day in shared]
    overlap = len(shared)
    if overlap < min_overlap or not shared:
        return CorrelationResult(
            status="insufficient_overlap",
            value=None,
            overlap_trade_dates=overlap,
            first=shared[0] if shared else None,
            last=shared[-1] if shared else None,
        )
    if _constant(xs) or _constant(ys):
        return CorrelationResult(
            status="constant_series",
            value=None,
            overlap_trade_dates=overlap,
            first=shared[0],
            last=shared[-1],
        )
    xv = np.asarray([float(value) for value in xs], dtype=np.float64)
    yv = np.asarray([float(value) for value in ys], dtype=np.float64)
    dx = xv - xv.mean()
    dy = yv - yv.mean()
    denominator = math.sqrt(float((dx * dx).sum()) * float((dy * dy).sum()))
    if denominator == 0.0:  # a constant-up-to-rounding series: no coefficient exists
        return CorrelationResult(
            status="constant_series",
            value=None,
            overlap_trade_dates=overlap,
            first=shared[0],
            last=shared[-1],
        )
    raw = float((dx * dy).sum()) / denominator
    if not math.isfinite(raw) or abs(raw) > 1.0 + 1e-12:
        msg = (
            f"the Pearson coefficient of {a.member_id} and {b.member_id} came out {raw!r} over "
            f"{overlap} overlapping trade dates: a correlation is in [-1, 1], so the series or the "
            "arithmetic is wrong. Do not clamp a broken value: check the two daily series"
        )
        raise InvariantViolation(msg)
    return CorrelationResult(
        status="ok",
        value=min(1.0, max(-1.0, raw)),
        overlap_trade_dates=overlap,
        first=shared[0],
        last=shared[-1],
    )


# ---------------------------------------------------------------------------------------------
# d. the metrics


def _metric(value: Decimal | int | None, unit: MetricUnit) -> CompareMetric:
    """One cross-run metric: its value, its unit and its descriptive assessment (null intervals).

    ``value`` is null only for a metric the member cannot have (a walk-forward's
    ``realized_pnl_usd``); a null value is never a zero (ADR-0102).
    """
    return CompareMetric(
        value=None if value is None else round(float(value), 6),
        ci_low=None,
        ci_high=None,
        assessment="descriptive",
        unit=unit,
    )


def _closing_drawdown(member: Member) -> Decimal:
    """Peak-to-trough on the daily closing equity, with the opening equity as the first peak."""
    peak = member.opening_equity
    drawdown = Decimal(0)
    for day in sorted(member.closing_equity):
        equity = member.closing_equity[day]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def member_metrics(member: Member) -> dict[str, CompareMetric]:
    """The member's descriptive metrics (ADR-0102 decision 3), in ``COMPARE_METRIC_UNITS`` order.

    Every value is computed from exact ``Decimal`` money and rounded to 6 decimals only when it is
    reported. ``marked_pnl_usd`` is the sum of the daily marked P&L (final closing equity minus
    capital) and ``realized_pnl_usd`` is the run's own ``metrics.json`` ``net_pnl_usd`` (final
    balance minus capital), null for a walk-forward: the keys are NOT the run's own, so a reader
    can never read a marked total as a realized one. ``max_drawdown_usd`` is the closing drawdown;
    ``max_intraday_drawdown_usd`` is the conservative OHLC one (for a walk-forward, the worst of
    its test runs: a fold's chain offset cancels out of a drawdown, and the flat folds
    contribute none).
    """
    metrics: dict[str, CompareMetric] = {
        "marked_pnl_usd": _metric(sum(member.net.values(), Decimal(0)), "usd"),
        "realized_pnl_usd": _metric(member.realized, "usd"),
        "total_costs_usd": _metric(member.costs, "usd"),
        "max_drawdown_usd": _metric(_closing_drawdown(member), "usd"),
        "max_intraday_drawdown_usd": _metric(member.intraday_drawdown, "usd"),
        "trades": _metric(member.trades, "count"),
        "fills": _metric(member.fills, "count"),
        "turnover_contracts": _metric(sum(member.turnover.values()), "contracts"),
        "trade_dates": _metric(len(member.net), "trade_dates"),
        "days_in_market": _metric(len(member.in_market), "trade_dates"),
    }
    assert tuple(metrics) == tuple(COMPARE_METRIC_UNITS), "the metric table drifted from its units"
    return metrics


def window_stability(member: Member) -> dict[str, object]:
    """Each calendar month's net P&L, by trade date, and the counts of their signs.

    Months are ``YYYY-MM`` labels of the trade dates (a day label's month, UTC-free by
    construction, ADR-0091). The counts are counts: there is no dispersion statistic, no
    test and no interval. Every value here is MARKED, like ``marked_pnl_usd``: a month's
    ``net_pnl_usd`` entry and a fold's ``fold_oos_net_pnl_usd`` entry are both final equity
    minus capital over the period, a walk-forward's including its terminal exits. They are
    period totals nested under their own keys, never the run's realized ``net_pnl_usd``.
    A walk-forward also gets ``fold_oos_net_pnl_usd``, its per-fold out-of-sample net P&L,
    listed in fold order (ADR-0102 decision 3).
    """
    monthly: dict[str, Decimal] = {}
    days: dict[str, int] = {}
    for day in sorted(member.net):
        month = f"{day.year:04d}-{day.month:02d}"
        monthly[month] = monthly.get(month, Decimal(0)) + member.net[day]
        days[month] = days.get(month, 0) + 1
    months = [
        {
            "month": month,
            "net_pnl_usd": _metric(monthly[month], "usd").model_dump(mode="json"),
            "trade_dates": days[month],
        }
        for month in sorted(monthly)
    ]
    stability: dict[str, object] = {
        "months": months,
        "months_positive": sum(1 for value in monthly.values() if value > 0),
        "months_negative": sum(1 for value in monthly.values() if value < 0),
        "months_flat": sum(1 for value in monthly.values() if value == 0),
    }
    if member.kind == "futures_walkforward":
        stability["fold_oos_net_pnl_usd"] = [
            _metric(value, "usd").model_dump(mode="json") for value in member.fold_oos
        ]
    return stability


# ---------------------------------------------------------------------------------------------
# e. the document


class _Document(BaseModel):
    """A ``cross_run.json`` contract: a typo or an extra key is an error, not a silent extra."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CompareMetric(_Document):
    """One cross-run metric: a value (or null), null intervals, its assessment and its unit.

    The shape is the futures document's metric shape, with one difference: ``value`` may be null,
    and only for a metric the member cannot have (a walk-forward has no ``realized_pnl_usd``). A
    null is a missing number, never a zero.
    """

    value: float | None
    ci_low: None
    ci_high: None
    assessment: Literal["descriptive"]
    unit: MetricUnit


class CompareOverlap(_Document):
    """The trade dates the correlation used, or nulls when none was computed.

    ``trade_dates`` is the size of the INNER join of the two series' trade dates (nothing filled);
    it is null for a pair that was not correlated at all (an unverifiable member, or one whose
    comparison key differs), because those have no overlap to report.
    """

    trade_dates: int | None
    first: str | None
    last: str | None


class CompareCorrelation(_Document):
    """One descriptive correlation: a value (or null), null intervals and the unit ``correlation``.

    The intervals are typed null: a futures comparison computes no confidence interval
    before C6, and an interval here would read as a claim about a population this
    milestone says nothing about (ADR-0095, ADR-0102).
    """

    value: float | None
    ci_low: None
    ci_high: None
    assessment: Literal["descriptive"]
    unit: Literal["correlation"]


class CompareTarget(_Document):
    """The artifact under examination: its descriptive metrics, its stability and its key."""

    id: str
    kind: MemberKind
    metrics: dict[str, CompareMetric]
    window_stability: dict[str, object]
    comparison_key: dict[str, object]


class ComparePoolMember(_Document):
    """One other artifact: its status against the target and, when it was correlated, the value.

    ``differing_keys`` lists the dotted paths of the comparison key that do not match (empty when
    they match); ``metrics`` is null exactly when the member could not be read (``unverified``).
    """

    id: str
    kind: MemberKind
    status: PoolStatus
    differing_keys: list[str]
    overlap: CompareOverlap
    correlation: CompareCorrelation
    metrics: dict[str, CompareMetric] | None


class CompareOptions(_Document):
    """The options the comparison ran with, so the document says how it was computed."""

    min_overlap_trade_dates: int


class CompareMaxCorrelation(_Document):
    """The pool member whose correlation has the largest ABSOLUTE value, and that value.

    ``value`` is the correlation itself, signed (``|value|`` is the largest in the pool): the sign
    is part of what was computed and dropping it would throw information away. It is a summary of
    what the comparison produced, not a ranking: the pool stays in id order, and no member is
    ordered by this value (ADR-0102 decision 6).
    """

    value: float
    member_id: str


class CompareSummary(_Document):
    """How many members the comparison had, how they ended up, and the largest absolute value."""

    members: int
    by_status: dict[str, int]
    max_abs_correlation: CompareMaxCorrelation | None


class CompareDocument(_Document):
    """``cross_run.json`` (``schema_version`` 1): the target, the pool in id order and no verdict.

    ``pool`` is sorted by member id and NEVER by a statistic; ``verdict`` is the futures
    null verdict with ADR-0097's ``not_assessed`` reason, because C5c assesses nothing.
    """

    schema_version: Literal[1]
    kind: Literal["futures_compare"]
    cmp_id: str
    target: CompareTarget
    options: CompareOptions
    pool: list[ComparePoolMember]
    summary: CompareSummary
    correlation_note: str
    verdict: FuturesVerdictDocument


@dataclass(frozen=True, slots=True)
class CompareResult:
    """What a finished comparison hands back: where its ``cross_run.json`` is, its id and it."""

    compare_dir: Path
    cmp_id: str
    document: dict[str, object]


def futures_compare_json_schema() -> dict[str, object]:
    """JSON Schema (draft 2020-12) of ``cross_run.json`` (``schema --kind futures-compare``).

    The correlation's intervals are typed null and its assessment is the single value
    ``descriptive``, so a consumer that validates before reading cannot accept a document that
    claims an interval; every metric is the futures document's own metric shape, with null
    intervals too.
    """
    schema: dict[str, object] = CompareDocument.model_json_schema()
    return schema


def _pool_ids(artifacts_root: Path) -> list[str]:
    """Every comparison member directory under ``artifacts_root``, sorted by id.

    Only ``FUT-``/``WFA-`` directories are members: ``BAT-``, ``CMP-``, an ``EXP-``
    equity run and loose files are not runs to compare here, and mistaking one for a run
    would put a document in the pool.
    """
    if not artifacts_root.is_dir():
        msg = (
            f"the artifacts root {artifacts_root} does not exist: a comparison reads the sealed "
            "artifacts it holds. Run the target first (`crucible futures run`), or pass the root "
            "that holds it"
        )
        raise ConfigurationError(msg).at(path=str(artifacts_root))
    return sorted(
        path.name
        for path in artifacts_root.iterdir()
        if path.is_dir() and path.name.startswith(RUN_ID_PREFIXES)
    )


def _overlap(result: CorrelationResult | None) -> CompareOverlap:
    if result is None:
        return CompareOverlap(trade_dates=None, first=None, last=None)
    return CompareOverlap(
        trade_dates=result.overlap_trade_dates,
        first=None if result.first is None else result.first.isoformat(),
        last=None if result.last is None else result.last.isoformat(),
    )


def _correlation(value: float | None) -> CompareCorrelation:
    return CompareCorrelation(
        value=value, ci_low=None, ci_high=None, assessment="descriptive", unit="correlation"
    )


def _entry(
    member: Member,
    status: PoolStatus,
    *,
    differing: Sequence[str] = (),
    result: CorrelationResult | None = None,
    metrics: Mapping[str, CompareMetric] | None = None,
) -> ComparePoolMember:
    """One pool row: its status, the key paths that differ, the overlap and the value (or null)."""
    return ComparePoolMember(
        id=member.member_id,
        kind=member.kind,
        status=status,
        differing_keys=list(differing),
        overlap=_overlap(result),
        correlation=_correlation(None if result is None else result.value),
        metrics=None if metrics is None else dict(metrics),
    )


def _max_abs(entries: Sequence[ComparePoolMember]) -> CompareMaxCorrelation | None:
    """The largest absolute correlation in the pool, ties going to the lowest member id."""
    best: CompareMaxCorrelation | None = None
    for entry in entries:  # entries are in id order, so a tie keeps the first
        value = entry.correlation.value
        if value is None:
            continue
        if best is None or abs(value) > abs(best.value):
            best = CompareMaxCorrelation(value=value, member_id=entry.id)
    return best


def compare_futures(
    target_id: str,
    *,
    artifacts_root: Path,
    min_overlap_trade_dates: int = DEFAULT_MIN_OVERLAP_TRADE_DATES,
) -> CompareResult:
    """Compare ``target_id`` with every other member under ``artifacts_root`` (ADR-0102).

    The pool is every ``FUT-``/``WFA-`` directory except the target and, when the target is a
    walk-forward, that walk-forward's own training and test runs (its inputs, not independent
    members). Each pair gets a status from its comparison key and, when the keys agree, a
    descriptive Pearson correlation over the overlapping trade dates.

    The id is ``CMP-`` + the hash of the target, the VERIFIED pool ids and the overlap
    option, so the same comparison is the same id and re-running it reproduces
    ``cross_run.json`` byte for byte; a corrupted member is reported ``unverified`` and
    does not change the id. The document is written under
    ``<artifacts_root>/<CMP-ID>/cross_run.json``, never inside a sealed run directory.

    Refuses ``min_overlap_trade_dates`` below 10 (too few overlapping dates for even a descriptive
    reading, ADR-0102 decision 5) and an unverified TARGET (there is nothing to compare a run whose
    own seal failed against).
    """
    if min_overlap_trade_dates < MIN_OVERLAP_FLOOR:
        msg = (
            f"min_overlap_trade_dates = {min_overlap_trade_dates}: a correlation needs at least "
            f"{MIN_OVERLAP_FLOOR} overlapping trade dates. Pass {MIN_OVERLAP_FLOOR} or more (the "
            "default is 20), or compare members whose windows overlap"
        )
        raise ConfigurationError(msg)
    target = load_member(artifacts_root, target_id)
    if not target.verified or target.key is None:
        msg = (
            f"the target {target_id} does not verify ({target.detail}): a comparison of "
            "a run whose own seal failed would report a correlation against numbers "
            "nobody can trust. Restore the artifact, or compare another run"
        )
        raise ConfigurationError(msg).at(member_id=target_id)
    excluded = {target_id}
    if target.kind == "futures_walkforward":
        excluded |= set(walkforward_run_ids(target.directory))
    target_key = comparison_key(target)
    pool_ids = [name for name in _pool_ids(artifacts_root) if name not in excluded]
    pool: list[ComparePoolMember] = []
    verified_ids: list[str] = []
    for member_id in pool_ids:
        member = load_member(artifacts_root, member_id)
        if not member.verified or member.key is None:
            pool.append(_entry(member, "unverified"))  # listed, never dropped (decision 1)
            continue
        differing = key_diff(target_key, member.key)
        if differing:
            pool.append(
                _entry(member, "incompatible", differing=differing, metrics=member_metrics(member))
            )
            continue
        verified_ids.append(member_id)
        result = daily_correlation(target, member, min_overlap=min_overlap_trade_dates)
        pool.append(_entry(member, result.status, result=result, metrics=member_metrics(member)))
    by_status = {
        status: sum(1 for entry in pool if entry.status == status)
        for status in POOL_STATUSES
        if any(entry.status == status for entry in pool)
    }
    cmp_id = comparison_id(target_id, verified_ids, min_overlap_trade_dates)
    document = CompareDocument(
        schema_version=COMPARE_SCHEMA_VERSION,
        kind="futures_compare",
        cmp_id=cmp_id,
        target=CompareTarget(
            id=target.member_id,
            kind=target.kind,
            metrics=member_metrics(target),
            window_stability=window_stability(target),
            comparison_key=target_key,
        ),
        options=CompareOptions(min_overlap_trade_dates=min_overlap_trade_dates),
        pool=pool,
        summary=CompareSummary(
            members=len(pool), by_status=by_status, max_abs_correlation=_max_abs(pool)
        ),
        correlation_note=CORRELATION_NOTE,
        verdict=verdict_document(),
    )
    compare_dir = artifacts_root / cmp_id
    compare_dir.mkdir(parents=True, exist_ok=True)
    written = document.model_dump(mode="json")
    (compare_dir / "cross_run.json").write_text(
        json.dumps(written, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return CompareResult(compare_dir=compare_dir, cmp_id=cmp_id, document=written)


def comparison_id(target_id: str, pool_ids: Sequence[str], min_overlap: int) -> str:
    """``CMP-`` + the SHA-256 of the target, the sorted VERIFIED pool ids and the overlap option."""
    basis = {
        "target": target_id,
        "pool": sorted(pool_ids),
        "min_overlap_trade_dates": min_overlap,
    }
    digest = hashlib.sha256(canonical_json(basis).encode("utf-8")).hexdigest()[:CMP_ID_HEX]
    return CMP_ID_PREFIX + digest


__all__ = [
    "CMP_ID_HEX",
    "CMP_ID_PREFIX",
    "COMPARE_METRIC_UNITS",
    "COMPARE_SCHEMA_VERSION",
    "CORRELATION_NOTE",
    "CORRELATION_UNIT",
    "DEFAULT_MIN_OVERLAP_TRADE_DATES",
    "FUTURES_RUN_PREFIX",
    "MIN_OVERLAP_FLOOR",
    "POOL_STATUSES",
    "RUN_ID_PREFIXES",
    "WALKFORWARD_PREFIX",
    "CompareDocument",
    "CompareMetric",
    "CompareResult",
    "CorrelationResult",
    "Member",
    "compare_futures",
    "comparison_id",
    "comparison_key",
    "daily_correlation",
    "futures_compare_json_schema",
    "key_diff",
    "load_member",
    "member_metrics",
    "walkforward_run_ids",
    "window_stability",
]
