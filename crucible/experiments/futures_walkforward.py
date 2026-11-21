"""Walk-forward evaluation of N strategy expressions on ONE futures-run base (Fathom C5b).

A walk-forward (ADR-0101) splits the base window's Globex trade dates into consecutive FOLDS. Each
fold trains on the dates before it and tests on the next ones:

- **training** runs every candidate of the batch file (ADR-0100's candidate contract) on the fold's
  training window, under the base config, changing only the strategy, the run name and the window;
- **eligibility** is a set of explicit risk constraints (an intraday drawdown ceiling is required,
  a minimum equity, a fill cap and a time-in-market cap are optional). A candidate that breaks one
  is not eligible, whatever it made;
- **selection** is the eligible candidate with the largest training net P&L; a tie goes to the
  earliest submission position, and a fold with no eligible candidate is FLAT (zero P&L, zero
  costs, status ``no_eligible_candidate``) rather than missing;
- **evaluation** runs the selected candidate on the fold's test window only, with the same signal
  warm-up (``window.warmup_trade_dates``, ADR-0101 decision 1), and charges a **terminal exit**:
  the contracts open at the test window's last bar times one side of the full cost, so every fold
  starts and ends flat at a known, pessimistic price.

The out-of-sample series concatenates the folds' daily ledgers in date order
(``oos_daily.parquet``): fold k's equity starts at the base capital plus the net P&L of folds 0 to
k-1 *after their terminal exit costs*, so the chain has no free close and no carried position.

Hard restriction (ADR-0095, ADR-0097, ADR-0101, ADR-0103): this module ranks nothing, and no EDGE
statement appears in its output. Since C6a the out-of-sample series carries the inferential
statistics of ADR-0103 (``oos.statistics``: per-period and annualized Sharpe, mean daily return,
PSR, DSR defined by the family's ``total_trials``), computed on the CONCATENATED chain ALONE; its
IC is null with a reason, because a concatenation of folds has no single signal to rank. The
training numbers — descriptive metrics and their own statistics — are kept for AUDIT only: they
live under ``in_sample_audit``, each entry marked ``in_sample: true``, and are never presented as
out-of-sample. ``window_stability`` lists each fold's OOS net P&L with counts of
positive/negative/flat folds — counts, never a statistic — and the verdict stays
``robustness_not_assessed`` (C7).

Identity: ``wf_id`` = ``WFA-`` + the SHA-256 of the walk-forward file (its base path excluded) and
the resolved base config, so the same submission is the same walk-forward and re-running it is a
reproduction (every run it already computed is ``cached`` and no submission is duplicated).

Units: money in USD as exact micro-dollars (``Decimal(38, 6)`` on disk), ``time_in_market`` a
fraction of the window's simulated bars, times UTC int64 ns, the window in Globex trade dates.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal, cast

import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from crucible.core.canonical import canonical_json
from crucible.core.errors import (
    ConfigurationError,
    DataQualityError,
    ExperimentError,
    InvariantViolation,
)
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.cme_sessions import session_trade_dates
from crucible.data.continuous import calendar_for
from crucible.data.futures_specs import futures_spec
from crucible.data.store import ParquetDataStore
from crucible.data.vault import refuse_protected_window
from crucible.experiments.futures_artifacts import MICRO
from crucible.experiments.futures_batch import (
    REGISTRY_FILE,
    BatchCandidate,
    FuturesBatchCandidateFile,
    FuturesPboFile,
    _cached_run,
)
from crucible.experiments.futures_config import (
    BAR_SECONDS,
    FuturesRunConfig,
    candidate_id,
    futures_config_hash,
    load_futures_config,
    parse_futures_config,
)
from crucible.experiments.futures_document import metric_document, verdict_document
from crucible.experiments.futures_run import MODE, futures_run_id, run_futures
from crucible.experiments.futures_stats import (
    STATISTICS_METRICS,
    daily_returns,
    daily_returns_from_oos,
    futures_statistics,
    no_information_coefficient,
)
from crucible.experiments.futures_trials import (
    PBO_PANEL_RULE,
    FuturesTrialsReport,
    PanelSeries,
    futures_effective_trials,
    pbo_on_panel,
    supplementary_block,
)
from crucible.validation.trial_registry import PBO_PANEL_MODE, DuckDBTrialRegistry

WALKFORWARD_SCHEMA_VERSION = 1
"""Version of ``walkforward.json`` (``docs/COMPATIBILITY.md`` §3: adding a key is additive)."""

WF_ID_PREFIX = "WFA-"
"""Prefix of a walk-forward id."""

WF_ID_HEX = 16
"""Hex digits of the SHA-256 kept in the walk-forward id (64 bits, as every other id here)."""

SCHEMES = ("rolling", "anchored")
"""How a fold's training window is chosen: ``rolling`` = the N trade dates immediately before the
test window, ``anchored`` = every trade date from the first one (the training window grows)."""

FOLD_STATUSES = ("selected", "no_eligible_candidate")
"""What a fold did: it selected a candidate, or no candidate met every constraint and the fold is
evaluated flat (zero P&L and zero costs). Being flat is a decision the constraints made, not a
missing observation (ADR-0101 decision 3)."""

CONSTRAINTS = (
    "max_intraday_drawdown_usd",
    "min_equity_usd",
    "max_fills",
    "max_time_in_market",
)
"""The risk constraints, in the order the checks are recorded: the required conservative intraday
drawdown ceiling, the optional floor on the lowest intraday equity, the optional fill cap and the
optional cap on the fraction of the window's bars holding a position."""

OOS_DAILY_SCHEMA: dict[str, pl.DataType] = {
    "trade_date": pl.Date(),  # Globex trade date of the row (a day label)
    "fold": pl.Int64(),  # 0-based fold index, in date order
    "candidate": pl.String(),  # nullable: the selected candidate's name; null on a flat fold
    "run_id": pl.String(),  # nullable: the FUT- id of the fold's test run; null on a flat fold
    "net_pnl_usd": pl.Decimal(38, 6),  # USD; the row's OOS net P&L (equity change of the day)
    "costs_usd": pl.Decimal(38, 6),  # USD; day's costs plus the terminal exit on the fold's last
    "fills": pl.Int64(),  # fills on the trade date
    "closing_equity_usd": pl.Decimal(38, 6),  # USD; the concatenated chain's closing equity
}
"""The columns of ``oos_daily.parquet``: one row per trade date of every evaluated test window, in
date order. The chain is the OOS series (ADR-0101 decision 4): a fold's equity starts at the base
capital plus the previous folds' net P&L after their terminal exit costs, and the terminal exit of
a fold is booked as a cost on the fold's LAST trade date."""

TERMINAL_EXIT_NOTE = (
    "each fold ends flat: the contracts open at the test window's last bar are charged one side "
    "of the full per-contract cost (fees plus half the spread plus slippage) as its terminal "
    "exit, and the next fold starts flat. This is pessimistic: a position the strategy would have "
    "held through a fold boundary pays one extra side per boundary."
)
"""Recorded in ``walkforward.json`` so a reader knows the fold boundaries are costed, not free."""

IN_SAMPLE_NOTE = (
    "training results, kept for audit only: they are IN-SAMPLE and are never presented as "
    "out-of-sample. The selection reads them; nothing under oos reads them."
)
"""Recorded in ``walkforward.json``'s ``in_sample_audit``."""


class _StrictModel(BaseModel):
    """A walk-forward file is a small contract: a typo or an extra key is an error, not a knob."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _money_field(value: object, what: str) -> object:
    """A USD amount is exact: a float is refused, and so is more than 6 decimals."""
    if isinstance(value, bool | float):
        msg = (
            f"{what} = {value!r} is a float: money is exact, so write it as a string (e.g. "
            '"(5000") or a whole number, and give the decimals explicitly'
        )
        raise ConfigurationError(msg)
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except ArithmeticError as exc:
            msg = f"{what} = {value!r} is not an amount in USD: {exc}"
            raise ConfigurationError(msg) from exc
    if value * MICRO != (value * MICRO).to_integral_value():
        msg = (
            f"{what} = {value} has more than 6 decimals; money is kept in exact micro-dollars, so "
            "round it to at most 6 decimals"
        )
        raise ConfigurationError(msg)
    return value


def _whole(value: object, what: str) -> object:
    """``True``/``False`` are not whole numbers here: a bool is a mistake in an int field."""
    if isinstance(value, bool):
        msg = f"{what} = {value!r} is a bool; give a whole number instead"
        raise ConfigurationError(msg)
    return value


class FuturesWalkForwardConstraints(_StrictModel):
    """The risk constraints a candidate must satisfy in the TRAINING window to be eligible.

    They are what stops a candidate from winning by taking more exposure than the researcher
    accepts (ADR-0101 decision 3): the drawdown ceiling is required and has no default, because a
    selection without one could pick a size the account could not carry.
    """

    max_intraday_drawdown_usd: Decimal = Field(
        gt=0,
        description="Required ceiling on the training window's conservative intraday drawdown "
        "(equity_low against a running equity_high, USD). A candidate whose drawdown is larger is "
        "not eligible.",
    )
    min_equity_usd: Decimal | None = Field(
        default=None,
        gt=0,
        description="Optional floor on the training window's lowest intraday equity, USD. A "
        "candidate that traded below it is not eligible.",
    )
    max_fills: int | None = Field(
        default=None,
        ge=0,
        description="Optional cap on the training window's fills. A candidate that filled more "
        "often is not eligible.",
    )
    max_time_in_market: float | None = Field(
        default=None,
        gt=0,
        le=1,
        description="Optional cap on the fraction of the training window's simulated bars that "
        "hold a non-zero position (0 < x <= 1). A candidate in the market more of the time is not "
        "eligible.",
    )

    @field_validator("max_intraday_drawdown_usd", "min_equity_usd", mode="before")
    @classmethod
    def _exact_money(cls, value: object) -> object:
        if value is None:
            return value
        return _money_field(value, "constraints")

    @field_validator("max_fills", mode="before")
    @classmethod
    def _fills_whole(cls, value: object) -> object:
        return _whole(value, "constraints.max_fills")

    @field_validator("max_time_in_market", mode="before")
    @classmethod
    def _fraction_not_bool(cls, value: object) -> object:
        return _whole(value, "constraints.max_time_in_market")


class FuturesWalkForwardFile(_StrictModel):
    """The walk-forward file: a base futures-run config, the candidates and the fold geometry."""

    kind: Literal["futures_walkforward"] = Field(
        default="futures_walkforward", description="File kind discriminator (a walk-forward)."
    )
    base: str = Field(
        min_length=1,
        description="Path to a futures-run YAML, relative to this file's directory. Its window "
        "gives the trade dates the folds are cut from; its strategy section is REPLACED per "
        "candidate; everything else is shared.",
    )
    candidates: list[FuturesBatchCandidateFile] = Field(
        min_length=1,
        description="The candidates, in submission order (kept, never sorted). Each takes exactly "
        "name, expression and params, as in a batch file.",
    )
    train_trade_dates: int = Field(
        ge=1,
        description="Globex trade dates of each fold's training window (N).",
    )
    test_trade_dates: int = Field(
        ge=1,
        description="Globex trade dates of each fold's test window (M); fold k tests on the dates "
        "N + k*M .. N + (k+1)*M - 1 of the base window.",
    )
    scheme: Literal["rolling", "anchored"] = Field(
        description="rolling: the N trade dates immediately before the test window. anchored: "
        "every trade date from the first one, so the training window grows fold by fold.",
    )
    warmup_trade_dates: int | None = Field(
        default=None,
        ge=0,
        description="Trade dates before each fold's window read only to compute the signal "
        "(window.warmup_trade_dates, ADR-0101 decision 1). Overrides the base config's value; "
        "null keeps the base's.",
    )
    constraints: FuturesWalkForwardConstraints = Field(
        description="What makes a candidate eligible in the training window (a drawdown ceiling "
        "is required)."
    )
    pbo: FuturesPboFile | None = Field(
        default=None,
        description="Optional PBO (C6b, ADR-0104 decision 6): the CSCV group count. When present, "
        "every distinct candidate is also run ONCE on the base window, those runs form a "
        "full-window panel reported under in_sample_audit.pbo_panel, and the selected "
        "out-of-sample path is never an input. When absent, no PBO is computed.",
    )

    @field_validator("train_trade_dates", "test_trade_dates", "warmup_trade_dates", mode="before")
    @classmethod
    def _counts_whole(cls, value: object) -> object:
        if value is None:
            return value
        return _whole(value, "a trade-date count")


@dataclass(frozen=True, slots=True)
class FuturesWalkForward:
    """A loaded walk-forward file: its path, the model, the resolved base config and candidates."""

    path: Path
    file: FuturesWalkForwardFile
    base: FuturesRunConfig
    candidates: tuple[BatchCandidate, ...]

    @property
    def warmup_trade_dates(self) -> int:
        """The warm-up each fold's runs use: the file's value, or the base config's when null."""
        if self.file.warmup_trade_dates is None:
            return self.base.window.warmup_trade_dates
        return self.file.warmup_trade_dates


@dataclass(frozen=True, slots=True)
class Fold:
    """One fold: its index, the trade dates it trains on and the ones it tests on."""

    index: int
    train: tuple[dt.date, ...]
    test: tuple[dt.date, ...]


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    """What a finished walk-forward hands back: where its files are, its id and the document."""

    walkforward_dir: Path
    wf_id: str
    document: dict[str, object]


# ---------------------------------------------------------------------------------------------
# a. the file


def _validation_message(exc: ValidationError, where: Path) -> str:
    problems = "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or '(root)'}: {error['msg']}"
        for error in exc.errors()
    )
    return (
        f"the futures walk-forward file {where} is invalid: {problems}. A walk-forward takes kind, "
        "base, candidates, train_trade_dates, test_trade_dates, scheme, warmup_trade_dates and "
        "constraints (whose max_intraday_drawdown_usd is required); a candidate takes exactly "
        "name, expression and params, and everything else comes from the base config"
    )


def load_futures_walkforward(path: Path) -> FuturesWalkForward:
    """Load and validate a walk-forward file, resolving its base config against its directory.

    Refuses a file that is not a walk-forward, an extra key anywhere, a candidate with a key other
    than name/expression/params, a duplicate candidate name, a constraints block without the
    drawdown ceiling, and a base that is not a valid futures-run config. Touches no data store: a
    fold needs the store, and this function does not.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"cannot read the futures walk-forward file {path}: {exc}"
        raise ConfigurationError(msg) from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"the futures walk-forward file {path} is not valid YAML: {exc}"
        raise ConfigurationError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"the futures walk-forward file {path} did not parse to a mapping"
        raise ConfigurationError(msg)
    try:
        parsed = FuturesWalkForwardFile.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(_validation_message(exc, path)) from exc
    names = [candidate.name for candidate in parsed.candidates]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        msg = (
            f"the futures walk-forward file {path} names the candidate(s) {duplicates} more than "
            "once: a candidate name identifies its runs (<base>/wf/<fold>/train|test/<name>), so "
            "two candidates cannot share one"
        )
        raise ConfigurationError(msg)
    base_path = Path(parsed.base)
    if not base_path.is_absolute():
        base_path = path.parent / base_path
    base = load_futures_config(base_path)
    candidates = tuple(
        BatchCandidate(
            position=position,
            name=candidate.name,
            expression=candidate.expression,
            params=dict(candidate.params),
        )
        for position, candidate in enumerate(parsed.candidates)
    )
    return FuturesWalkForward(path=path, file=parsed, base=base, candidates=candidates)


def futures_walkforward_json_schema() -> dict[str, object]:
    """The JSON Schema of the walk-forward file (``crucible schema --kind futures-walkforward``)."""
    return FuturesWalkForwardFile.model_json_schema()


def walkforward_id(base: FuturesRunConfig, walkforward: FuturesWalkForwardFile) -> str:
    """``WFA-`` + the SHA-256 of the walk-forward file (path excluded) and the base config dump.

    The same submission is the same walk-forward, whatever the file is called and wherever it
    lives; the base config's CONTENT is hashed, exactly as a futures run hashes it.
    """
    basis = {
        "base": base.model_dump(mode="json"),
        "walkforward": walkforward.model_dump(mode="json", exclude={"base"}),
    }
    return (
        WF_ID_PREFIX + hashlib.sha256(canonical_json(basis).encode("utf-8")).hexdigest()[:WF_ID_HEX]
    )


# ---------------------------------------------------------------------------------------------
# b. the trade dates and the folds


def walkforward_trade_dates(config: FuturesRunConfig, *, store_root: Path) -> tuple[dt.date, ...]:
    """The base window's Globex trade dates that have at least one ON-SCHEDULE bar, in order.

    Measured on the stored one-minute series (``BAR_SECONDS``): a bar's trade date and its
    schedule flag do not change when a coarser resolution aggregates it, so this is the same set a
    run at the base's fidelity simulates. Refuses a store without the execution dataset and a
    window with no such trade date.
    """
    calendar = calendar_for(config.root)
    name = config.datasets.execution
    if not (store_root / name / "manifest.json").is_file():
        msg = (
            f"dataset {name!r} (role execution) is not in the store {store_root}: no manifest.json "
            "there. Build the continuous futures datasets with `crucible data build` (ADR-0086), "
            "or point the walk-forward at the store that holds them"
        )
        raise DataQualityError(msg)
    # the base window's own horizon (the close of its last trade date), so a walk-forward that
    # stops before a declared vault start is admissible (ADR-0105)
    horizon = int(calendar.session(config.window.end).close_ns)
    frame = ParquetDataStore(store_root).read(DatasetId(name), TimestampNs(horizon)).collect()
    days, on_schedule = session_trade_dates(calendar, frame["event_time"].to_numpy(), BAR_SECONDS)
    placed = pl.DataFrame(
        {
            "trade_date": pl.Series("trade_date", days).cast(pl.Date),
            "on_schedule": pl.Series("on_schedule", on_schedule, dtype=pl.Boolean),
        }
    )
    inside = placed.filter(
        (pl.col("trade_date") >= config.window.start) & (pl.col("trade_date") <= config.window.end)
    )
    dates = sorted(set(inside.filter(pl.col("on_schedule"))["trade_date"].to_list()))
    if not dates:
        msg = (
            f"no Globex trade date with on-schedule bars falls in [{config.window.start}, "
            f"{config.window.end}] of the execution dataset {name}: a walk-forward cuts its folds "
            "from the base window's trade dates, so the window must cover data the dataset holds"
        )
        raise DataQualityError(msg)
    return tuple(dates)


def walkforward_folds(
    trade_dates: tuple[dt.date, ...],
    *,
    train_trade_dates: int,
    test_trade_dates: int,
    scheme: str,
) -> tuple[tuple[Fold, ...], tuple[dt.date, ...]]:
    """The folds of one base window, and the trailing dates no fold uses (ADR-0101 decision 2).

    Fold k tests on trade dates ``[N + k*M, N + (k+1)*M)``; its training window is the N dates
    before that (``rolling``) or every date from the first one (``anchored``). The test windows are
    contiguous and never overlap, and a trailing remainder shorter than M is reported as unused
    rather than evaluated on a shorter window. Fewer than one complete fold is refused.
    """
    dates = tuple(trade_dates)
    if scheme not in SCHEMES:
        msg = f"scheme {scheme!r} is not a walk-forward scheme; use one of {list(SCHEMES)}"
        raise ConfigurationError(msg)
    if train_trade_dates < 1 or test_trade_dates < 1:
        msg = (
            f"train_trade_dates = {train_trade_dates} and test_trade_dates = {test_trade_dates}: "
            "a fold needs at least one trade date in each window"
        )
        raise ConfigurationError(msg)
    folds: list[Fold] = []
    start = train_trade_dates
    while start + test_trade_dates <= len(dates):
        train = dates[:start] if scheme == "anchored" else dates[start - train_trade_dates : start]
        folds.append(
            Fold(
                index=len(folds),
                train=train,
                test=dates[start : start + test_trade_dates],
            )
        )
        start += test_trade_dates
    if not folds:
        msg = (
            f"the base window holds {len(dates)} Globex trade date(s) with on-schedule bars, fewer "
            f"than the {train_trade_dates + test_trade_dates} one complete fold needs "
            f"(train_trade_dates {train_trade_dates} + test_trade_dates {test_trade_dates}): a "
            "walk-forward refuses a window it cannot cut at least one fold from. Widen the base "
            "window, or lower train_trade_dates / test_trade_dates"
        )
        raise ConfigurationError(msg)
    return tuple(folds), dates[start:]


# ---------------------------------------------------------------------------------------------
# c. costs and the selection


def terminal_exit_cost(config: FuturesRunConfig, position: int) -> Decimal:
    """One side of the full per-contract cost times the contracts open at the fold's last bar.

    It is exactly what a closing fill would pay on this run (``CostSchedule``'s own formula: the
    fees per side plus half the spread plus the slippage, in ticks, times the contract's tick
    value), read from the run's EFFECTIVE costs: a ``commission_only`` run therefore pays the fees
    only, because its spread and slippage are zero. Zero for a flat position, and always a
    pessimistic charge: the mark at the last bar is already in the fold's equity, and the exit is
    charged on top of it.
    """
    if position == 0:
        return Decimal(0)
    costs = config.cost_schedule()
    tick_value = futures_spec(config.root).tick_value
    per_side = costs.fees_per_side + (costs.spread_ticks / 2 + costs.slippage_ticks) * tick_value
    total = per_side * abs(int(position))
    if total * MICRO != (total * MICRO).to_integral_value():
        msg = (
            f"the terminal exit cost {total} USD has more than 6 decimals; money is kept in exact "
            "micro-dollars, so a per-side cost with that precision cannot be charged exactly"
        )
        raise InvariantViolation(msg)
    return total


def _metric(value: Decimal | float, unit: str) -> dict[str, object]:
    """One descriptive metric in the futures document's shape: a value, no interval, a unit."""
    return {
        "value": round(float(value), 6),
        "ci_low": None,
        "ci_high": None,
        "assessment": "descriptive",
        "unit": unit,
    }


def _metric_value(metrics: dict[str, object], name: str, run_id: str) -> Decimal:
    """The run's own reported value of ``name``, as an exact Decimal."""
    entry = metrics.get(name)
    value = entry.get("value") if isinstance(entry, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = (
            f"the training run {run_id} has no usable {name!r} metric: a walk-forward's "
            "constraints read the run's own descriptive metrics (net_pnl_usd, "
            "max_intraday_drawdown_usd, min_equity_usd, fills), so the artifact must be a sealed "
            "futures run"
        )
        raise ExperimentError(msg).at(key=name)
    return Decimal(str(value))


def constraint_checks(
    constraints: FuturesWalkForwardConstraints,
    *,
    metrics: dict[str, object],
    time_in_market: Fraction,
    run_id: str,
) -> list[dict[str, object]]:
    """Every constraint, as ``{constraint, limit, value, ok}``, evaluated on ONE training run.

    The values are the run's own descriptive metrics, except ``max_time_in_market``, which is
    recomputed from the run's marks (the fraction of simulated bars with a non-zero position).
    ``ok`` is the check itself, computed exactly (``Decimal`` for money and counts, ``Fraction``
    for the fraction) so a report that is on the limit is not decided by a rounding step.
    """
    limits: list[tuple[str, Decimal, Decimal, bool]] = [
        (
            "max_intraday_drawdown_usd",
            constraints.max_intraday_drawdown_usd,
            _metric_value(metrics, "max_intraday_drawdown_usd", run_id),
            True,
        )
    ]
    if constraints.min_equity_usd is not None:
        limits.append(
            (
                "min_equity_usd",
                constraints.min_equity_usd,
                _metric_value(metrics, "min_equity_usd", run_id),
                False,
            )
        )
    if constraints.max_fills is not None:
        limits.append(
            (
                "max_fills",
                Decimal(constraints.max_fills),
                _metric_value(metrics, "fills", run_id),
                True,
            )
        )
    checks: list[dict[str, object]] = [
        {
            "constraint": name,
            "limit": round(float(limit), 6),
            "value": round(float(value), 6),
            "ok": value <= limit if is_cap else value >= limit,
        }
        for name, limit, value, is_cap in limits
    ]
    if constraints.max_time_in_market is not None:
        limit = Fraction(Decimal(str(constraints.max_time_in_market)))
        checks.append(
            {
                "constraint": "max_time_in_market",
                "limit": round(float(constraints.max_time_in_market), 6),
                "value": round(float(time_in_market), 6),
                "ok": time_in_market <= limit,
            }
        )
    return checks


def _violation(check: dict[str, object]) -> str:
    """The check as a sentence: which constraint, by how much, and in which direction."""
    name = str(check["constraint"])
    relation = "<" if name == "min_equity_usd" else ">"
    return f"{name}: {check['value']} {relation} {check['limit']}"


def _selection_reason(eligible: int, total: int, tied: bool) -> str:
    """Why the fold selected what it selected: counts and the tie rule, never a result."""
    if eligible == 0:
        return (
            f"no eligible candidate: all {total} candidate(s) broke at least one constraint, so "
            "the fold is evaluated flat (zero P&L and zero costs)"
        )
    reason = (
        f"largest training net P&L among the {eligible} of {total} candidate(s) that met every "
        "constraint"
    )
    failed = total - eligible
    if failed:
        reason += f"; {failed} candidate(s) failed at least one constraint"
    if tied:
        reason += "; a tie on training net P&L was broken by submission position (earliest wins)"
    return reason


# ---------------------------------------------------------------------------------------------
# d. reading a fold's runs


@dataclass(frozen=True, slots=True)
class _RunFacts:
    """What the walk-forward reads back from one sealed run: its id, metrics, daily and marks."""

    run_id: str
    artifact_id: str
    metrics: dict[str, object]
    daily: pl.DataFrame
    marks: pl.DataFrame

    @property
    def time_in_market(self) -> Fraction:
        """The fraction of the run's simulated bars holding a non-zero position."""
        if self.marks.height == 0:
            msg = f"the run {self.run_id} has no marks: a walk-forward reads its position by bar"
            raise InvariantViolation(msg)
        open_bars = int((self.marks["position"] != 0).sum())
        return Fraction(open_bars, self.marks.height)


def _facts(run_dir: Path) -> _RunFacts:
    """A sealed run's metrics and frames (the seal is verified before anything is read)."""
    artifact_id, metrics = _cached_run(run_dir)
    try:
        daily = pl.read_parquet(run_dir / "daily.parquet")
        marks = pl.read_parquet(run_dir / "marks.parquet")
    except (OSError, pl.exceptions.PolarsError) as exc:
        msg = f"cannot read the daily ledger or the marks of {run_dir}: {exc}"
        raise ExperimentError(msg).at(path=str(run_dir)) from exc
    return _RunFacts(
        run_id=run_dir.name, artifact_id=artifact_id, metrics=metrics, daily=daily, marks=marks
    )


def _fold_run(
    base: FuturesRunConfig,
    candidate: BatchCandidate,
    *,
    name: str,
    start: dt.date,
    end: dt.date,
    warmup: int,
) -> FuturesRunConfig:
    """The base config with ONLY the strategy, the run name and the window changed for one run.

    This is the batch rule (ADR-0100 decision 3) plus the fold's window: contracts, costs,
    execution, session, fidelity and family stay the base's, so every candidate of every fold is
    compared under the same conditions. The dump is ``exclude_unset`` for the batch's reason: a
    base field left at its default must stay unset, or re-validation would read it as explicit.
    """
    raw = base.model_dump(mode="json", exclude_unset=True)
    raw["strategy"] = {"expression": candidate.expression, "params": candidate.params}
    raw["run"] = {**raw["run"], "name": name}
    raw["window"] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "warmup_trade_dates": warmup,
    }
    return parse_futures_config(raw)


@dataclass(frozen=True, slots=True)
class _Computed:
    """One run of the walk-forward: which candidate, its config, its status and its facts."""

    candidate: BatchCandidate
    config: FuturesRunConfig
    status: str
    facts: _RunFacts


def _compute(
    config: FuturesRunConfig,
    *,
    store_root: Path,
    artifacts_root: Path,
    overwrite: bool,
    computed: dict[str, tuple[str, _RunFacts]],
    mode: str = MODE,
) -> tuple[str, _RunFacts, str]:
    """Run ``config`` (or reuse the run it already has) and hand back its status and facts.

    ``computed`` maps a parameterization id to what computed it, so two candidates with the same
    bound expression run ONCE per window, exactly as in a batch. A run directory that already
    exists and verifies is ``cached``, which is what makes re-running a walk-forward a
    reproduction.

    ``mode`` is the ``mode`` the trial is recorded with: ``MODE`` (``futures``) for a fold's
    training or test run, ``PBO_PANEL_MODE`` for an audit-panel run, which is recorded in
    ``trials`` and NOT counted as a submission event (C6b, ADR-0104 decision 6).
    """
    compiled = config.strategy.compiled_signal(config.signal.input)
    key = compiled.parameterization_id
    reused = computed.get(key)
    if reused is not None:
        run_id, facts = reused
        return run_id, facts, "cached"
    run_id = futures_run_id(config, store_root=store_root)
    run_dir = artifacts_root / run_id
    if not overwrite and run_dir.is_dir():
        facts = _facts(run_dir)
        status = "cached"
    else:
        result = run_futures(
            config,
            store_root=store_root,
            artifacts_root=artifacts_root,
            overwrite=overwrite,
            mode=mode,
        )
        run_id = result.run_id
        facts = _facts(result.run_dir)
        status = "computed"
    computed[key] = (run_id, facts)
    return run_id, facts, status


# ---------------------------------------------------------------------------------------------
# e. the out-of-sample chain


@dataclass(frozen=True, slots=True)
class _FoldChain:
    """One fold's rows of the OOS chain and the totals they add up to."""

    rows: list[dict[str, object]]
    net_usd: Decimal
    costs_usd: Decimal
    fills: int


def _fold_rows(
    *,
    fold: Fold,
    candidate: str,
    run_id: str,
    facts: _RunFacts,
    capital: Decimal,
    opening: Decimal,
    terminal: Decimal,
) -> _FoldChain:
    """One fold's rows of the OOS chain, and the net, cost and fill totals of them.

    ``opening`` is the chain's closing equity before the fold (the base capital plus the previous
    folds' net P&L). Each day's row is the run's own daily equity shifted into the chain, and the
    terminal exit is booked as a cost - and a reduction of the closing equity - on the fold's LAST
    trade date, so the fold ends flat at a known, pessimistic price.
    """
    dates = facts.daily["trade_date"].to_list()
    if dates != list(fold.test):
        msg = (
            f"the test run {run_id} of fold {fold.index} has trade dates {dates[:3]}... but the "
            f"fold's test window is {list(fold.test)[:3]}...: a fold's OOS rows are exactly its "
            "test window's trade dates, so a missing session would break the chain"
        )
        raise InvariantViolation(msg)
    rows: list[dict[str, object]] = []
    previous = opening
    costs_total = Decimal(0)
    fills_total = 0
    last = facts.daily.height - 1
    for index in range(facts.daily.height):
        closing = Decimal(facts.daily["closing_equity_usd"][index]) + (opening - capital)
        costs = Decimal(facts.daily["costs_usd"][index])
        fills = int(facts.daily["fills"][index])
        if index == last:
            closing -= terminal
            costs += terminal
        costs_total += costs
        fills_total += fills
        rows.append(
            {
                "trade_date": facts.daily["trade_date"][index],
                "fold": fold.index,
                "candidate": candidate,
                "run_id": run_id,
                "net_pnl_usd": closing - previous,
                "costs_usd": costs,
                "fills": fills,
                "closing_equity_usd": closing,
            }
        )
        previous = closing
    return _FoldChain(
        rows=rows, net_usd=previous - opening, costs_usd=costs_total, fills=fills_total
    )


def _flat_rows(fold: Fold, *, opening: Decimal) -> list[dict[str, object]]:
    """A fold with no eligible candidate: zero P&L and zero costs on each of its test dates."""
    return [
        {
            "trade_date": day,
            "fold": fold.index,
            "candidate": None,
            "run_id": None,
            "net_pnl_usd": Decimal(0),
            "costs_usd": Decimal(0),
            "fills": 0,
            "closing_equity_usd": opening,
        }
        for day in fold.test
    ]


def _oos_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    """The OOS rows as the documented frame (money as exact ``Decimal(38, 6)``)."""
    money = pl.Decimal(38, 6)
    return pl.DataFrame(
        {
            "trade_date": pl.Series([row["trade_date"] for row in rows], dtype=pl.Date),
            "fold": pl.Series([row["fold"] for row in rows], dtype=pl.Int64),
            "candidate": pl.Series([row["candidate"] for row in rows], dtype=pl.String),
            "run_id": pl.Series([row["run_id"] for row in rows], dtype=pl.String),
            "net_pnl_usd": pl.Series([row["net_pnl_usd"] for row in rows], dtype=money),
            "costs_usd": pl.Series([row["costs_usd"] for row in rows], dtype=money),
            "fills": pl.Series([row["fills"] for row in rows], dtype=pl.Int64),
            "closing_equity_usd": pl.Series(
                [row["closing_equity_usd"] for row in rows], dtype=money
            ),
        }
    ).select(list(OOS_DAILY_SCHEMA))


def _oos_summary(frame: pl.DataFrame, capital: Decimal) -> dict[str, object]:
    """The OOS summary, computed from ``oos_daily`` ALONE (ADR-0101 decision 5).

    Net P&L, costs and fills are sums of the days; the maximum drawdown is peak-to-trough on the
    concatenated closing equity, in USD, with the base capital as the first peak; the fold count
    with a selection is the number of distinct folds whose rows name a candidate. Nothing here is
    a statistic: there is no return ratio, no risk adjustment and no interval.
    """
    net = sum((Decimal(value) for value in frame["net_pnl_usd"].to_list()), Decimal(0))
    costs = sum((Decimal(value) for value in frame["costs_usd"].to_list()), Decimal(0))
    fills = int(frame["fills"].sum())
    peak = capital
    drawdown = Decimal(0)
    for value in frame["closing_equity_usd"].to_list():
        equity = Decimal(value)
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    selected = frame.filter(pl.col("candidate").is_not_null())["fold"].n_unique()
    return {
        "net_pnl_usd": _metric(net, "usd"),
        "total_costs_usd": _metric(costs, "usd"),
        "fills": _metric(Decimal(fills), "count"),
        "trade_dates": _metric(Decimal(frame.height), "trade_dates"),
        "max_drawdown_usd": _metric(drawdown, "usd"),
        "folds_with_selection": _metric(Decimal(int(selected)), "count"),
    }


OOS_IC_REASON = (
    "a walk-forward's out-of-sample series is a concatenation of folds, so there is no single "
    "signal whose score could be ranked against a forward return: an information coefficient "
    "belongs to one fold's run, and the training runs' own ICs are IN-SAMPLE only"
)
"""Why the OOS statistics carry no information coefficient (ADR-0103 decision 7)."""


def _statistics_metrics(metrics: dict[str, object], run_id: str) -> dict[str, object]:
    """A run's own C6a statistics, as its sealed ``metrics.json`` recorded them.

    Used for the training runs under ``in_sample_audit``: they were measured IN SAMPLE when the run
    executed, and re-deriving them here would be a second implementation of the same number.
    """
    out: dict[str, object] = {}
    for name in STATISTICS_METRICS:
        entry = metrics.get(name)
        if not isinstance(entry, dict):
            msg = (
                f"the run {run_id} has no {name!r} statistic: since C6a every futures run reports "
                "its statistics in metrics.json (ADR-0103). Re-run it with `crucible futures run`"
            )
            raise ExperimentError(msg).at(key=name)
        out[name] = metric_document(name, entry).model_dump(mode="json")
    return out


def _oos_statistics(
    oos_frame: pl.DataFrame,
    *,
    base: FuturesRunConfig,
    identifier: str,
    registry: DuckDBTrialRegistry,
    estimate: FuturesTrialsReport,
) -> dict[str, object]:
    """The walk-forward's statistics, computed on the OOS chain ALONE (ADR-0101, ADR-0103).

    The series is ``oos_daily.parquet``'s ``closing_equity_usd`` chain, whose folds already start
    and end flat with the terminal exit cost booked: nothing of a training run leaks in. The
    deflation uses the FAMILY's ``total_trials`` (the walk-forward's own training and test runs are
    part of the search that produced the selected candidates, so deflating by anything smaller
    would flatter the result). ``owner_id`` is the ``WFA-`` id, so the bootstrap seeds are the
    walk-forward's own.
    """
    if oos_frame.height == 0:
        msg = "the out-of-sample chain has no row: a walk-forward evaluates at least one fold"
        raise InvariantViolation(msg)
    dates = oos_frame["trade_date"].to_list()
    series = daily_returns_from_oos(
        oos_frame,
        initial_capital=base.capital,
        calendar=calendar_for(base.root),
        window=(dates[0], dates[-1]),
    )
    report = futures_statistics(
        series,
        owner_id=identifier,
        total_trials=registry.total_trials(base.run.family),
        trial_sharpes=registry.candidate_sharpes(base.run.family),
        config=base.statistics,
        ic=no_information_coefficient(OOS_IC_REASON, horizon_bars=base.statistics.ic_horizon_bars),
    )
    block = dict(cast("dict[str, object]", report["block"]))
    trials = dict(cast("dict[str, object]", block["trials"]))
    trials["submission_count"] = registry.submission_count(base.run.family)
    trials["unique_candidate_count"] = registry.unique_candidate_count(base.run.family)
    block["trials"] = trials
    # C6b (ADR-0104 decision 4): the SUPPLEMENTARY deflation sits beside the OOS ``dsr``, which
    # stays the primary reading and is unchanged; only N differs.
    block["supplementary"] = supplementary_block(series.returns, report=estimate)
    return {"metrics": report["metrics"], **block}


def _write_parquet(frame: pl.DataFrame, path: Path) -> None:
    """Deterministic Parquet: uncompressed, no statistics, so identical frames are identical
    bytes (ADR-0011)."""
    frame.write_parquet(path, compression="uncompressed", statistics=False)


# ---------------------------------------------------------------------------------------------
# f. the walk-forward


def _pbo_panel(
    loaded: FuturesWalkForward,
    *,
    store_root: Path,
    artifacts_root: Path,
    overwrite: bool,
    warmup: int,
) -> dict[str, object] | None:
    """The full-window panel of distinct candidates and its PBO (C6b, ADR-0104 decision 6).

    ``None`` when the walk-forward file asks for no PBO. Otherwise every DISTINCT candidate (the
    compiled parameterization, as the folds dedupe) runs ONCE on the base window with the base
    config and the same warm-up, under the run name ``<base>/wf/full/<name>``. Those runs record
    their trial with their ``candidate_id`` and ``mode = PBO_PANEL_MODE``: the candidate already
    exists in the family, so ``total_trials`` does not grow, no submission row is written and
    ``submission_count`` does not move either (nothing was submitted or selected: this is an
    audit panel, not a search), while every panel run stays auditable in the registry. The
    panel's dates are the runs' own trade dates on the base window, and they must be identical
    -- nothing is filled.
    """
    if loaded.file.pbo is None:
        return None
    base = loaded.base
    calendar = calendar_for(base.root)
    window = (base.window.start, base.window.end)
    computed: dict[str, tuple[str, _RunFacts]] = {}
    panel: list[PanelSeries] = []
    candidates: list[dict[str, object]] = []
    for candidate in loaded.candidates:
        config = _fold_run(
            base,
            candidate,
            name=f"{base.run.name}/wf/full/{candidate.name}",
            start=base.window.start,
            end=base.window.end,
            warmup=warmup,
        )
        run_id, facts, status = _compute(
            config,
            store_root=store_root,
            artifacts_root=artifacts_root,
            overwrite=overwrite,
            computed=computed,
            mode=PBO_PANEL_MODE,
        )
        identifier = candidate_id(config)
        if any(entry["candidate_id"] == identifier for entry in candidates):
            continue
        series = daily_returns(
            facts.daily, initial_capital=base.capital, calendar=calendar, window=window
        )
        panel.append(
            PanelSeries(
                candidate_id=identifier,
                trade_dates=series.trade_dates,
                returns=series.returns,
                source=run_id,
            )
        )
        candidates.append(
            {
                "candidate_id": identifier,
                "name": candidate.name,
                "run_id": run_id,
                "status": status,
                "n_obs": series.n_observations,
            }
        )
    outcome = pbo_on_panel(panel, n_groups=loaded.file.pbo.n_groups)
    block = outcome.record()
    block["in_sample"] = True
    block["candidates"] = candidates
    block["note"] = (
        "these runs are IN SAMPLE: each candidate was simulated once on the whole base window to "
        "form a comparable panel, and nothing of them is out-of-sample. The walk-forward's OOS "
        "series is a different artifact and is never an input of this PBO"
    )
    return block


def run_futures_walkforward(
    walkforward: FuturesWalkForward | Path | str,
    *,
    store_root: Path,
    artifacts_root: Path,
    overwrite: bool = False,
) -> WalkForwardResult:
    """Run every fold of ``walkforward`` and write ``<artifacts>/<WFA-ID>/``.

    ``walkforward``: a loaded :class:`FuturesWalkForward`, or the path of a file to load.
    ``store_root``: the ParquetDataStore root (shared by every run). ``artifacts_root``: where the
    run directories, the shared ``trial_registry.duckdb`` and the walk-forward directory live.
    ``overwrite``: re-simulate a run whose directory already exists instead of reusing it.

    Timing: each run decides its targets at a bar's close from bars up to and including it, and a
    fold's training window ends before its test window begins, so no test bar is ever decided on
    training data - the folds are the causality. Determinism: ``wf_id``, every run id,
    ``walkforward.json`` (sorted keys) and ``oos_daily.parquet`` are pure functions of the file,
    the base config and the datasets, so a second run reproduces them (with every run ``cached``).
    """
    loaded = (
        load_futures_walkforward(Path(walkforward))
        if isinstance(walkforward, str | Path)
        else walkforward
    )
    base = loaded.base
    refuse_protected_window(
        root=base.root,
        start=base.window.start,
        end=base.window.end,
        store_root=store_root,
        what=f"the futures walk-forward {base.run.name!r}",
    )
    identifier = walkforward_id(base, loaded.file)
    constraints = loaded.file.constraints
    warmup = loaded.warmup_trade_dates
    train_dates = loaded.file.train_trade_dates
    test_dates = loaded.file.test_trade_dates
    scheme = loaded.file.scheme
    trade_dates = walkforward_trade_dates(base, store_root=store_root)
    folds, unused = walkforward_folds(
        trade_dates,
        train_trade_dates=train_dates,
        test_trade_dates=test_dates,
        scheme=scheme,
    )
    registry = DuckDBTrialRegistry(artifacts_root / REGISTRY_FILE)
    candidates = loaded.candidates
    rows: list[dict[str, object]] = []
    folds_document: list[dict[str, object]] = []
    audit_folds: list[dict[str, object]] = []
    opening = base.capital
    fold_nets: list[Decimal] = []
    for fold in folds:
        trained: list[_Computed] = []
        computed: dict[str, tuple[str, _RunFacts]] = {}
        for candidate in candidates:
            config = _fold_run(
                base,
                candidate,
                name=f"{base.run.name}/wf/{fold.index}/train/{candidate.name}",
                start=fold.train[0],
                end=fold.train[-1],
                warmup=warmup,
            )
            run_id, facts, status = _compute(
                config,
                store_root=store_root,
                artifacts_root=artifacts_root,
                overwrite=overwrite,
                computed=computed,
            )
            registry.record_submission(
                identifier,
                fold.index * len(candidates) + candidate.position,
                config.run.family,
                run_id,
                config.strategy.compiled_signal(config.signal.input).structure_id,
                config.strategy.compiled_signal(config.signal.input).parameterization_id,
                candidate.name,
                status,
                candidate_id=candidate_id(config),
            )
            trained.append(_Computed(candidate, config, status, facts))

        audited: list[dict[str, object]] = []
        eligible: list[tuple[Decimal, _Computed]] = []
        for entry in trained:
            strategy = entry.config.strategy.compiled_signal(entry.config.signal.input)
            checks = constraint_checks(
                constraints,
                metrics=entry.facts.metrics,
                time_in_market=entry.facts.time_in_market,
                run_id=entry.facts.run_id,
            )
            violations = [_violation(check) for check in checks if not check["ok"]]
            if not violations:
                eligible.append(
                    (
                        _metric_value(entry.facts.metrics, "net_pnl_usd", entry.facts.run_id),
                        entry,
                    )
                )
            audited.append(
                {
                    "position": entry.candidate.position,
                    "name": entry.candidate.name,
                    "in_sample": True,
                    "status": entry.status,
                    "structure_id": strategy.structure_id,
                    "parameterization_id": strategy.parameterization_id,
                    "candidate_id": candidate_id(entry.config),
                    "run_id": entry.facts.run_id,
                    "artifact_id": entry.facts.artifact_id,
                    "metrics": {
                        name: metric_document(name, value).model_dump(mode="json")
                        for name, value in sorted(entry.facts.metrics.items())
                        if isinstance(value, dict)
                    },
                    "statistics": _statistics_metrics(entry.facts.metrics, entry.facts.run_id),
                    "time_in_market": _metric(float(entry.facts.time_in_market), "fraction"),
                    "checks": checks,
                    "violations": violations,
                    "eligible": not violations,
                }
            )

        selected: _Computed | None = None
        best: Decimal | None = None
        tied = False
        for net, entry in eligible:  # submission order: a tie keeps the earliest position
            if best is None or net > best:
                best, selected, tied = net, entry, False
            elif net == best:
                tied = True
        reason = _selection_reason(len(eligible), len(candidates), tied)
        status = "selected" if selected is not None else "no_eligible_candidate"
        fold_rows: list[dict[str, object]]
        fold_net = Decimal(0)
        fold_costs = Decimal(0)
        fold_fills = 0
        terminal = Decimal(0)
        open_contracts = 0
        oos_run_id: str | None = None
        oos_artifact_id: str | None = None
        oos_time_in_market: dict[str, object] | None = None
        if selected is None:
            fold_rows = _flat_rows(fold, opening=opening)
        else:
            test_config = _fold_run(
                base,
                selected.candidate,
                name=f"{base.run.name}/wf/{fold.index}/test/{selected.candidate.name}",
                start=fold.test[0],
                end=fold.test[-1],
                warmup=warmup,
            )
            run_id, facts, _ = _compute(
                test_config,
                store_root=store_root,
                artifacts_root=artifacts_root,
                overwrite=overwrite,
                computed={},
            )
            open_contracts = int(facts.marks["position"][-1])
            terminal = terminal_exit_cost(test_config, open_contracts)
            chain = _fold_rows(
                fold=fold,
                candidate=selected.candidate.name,
                run_id=run_id,
                facts=facts,
                capital=base.capital,
                opening=opening,
                terminal=terminal,
            )
            fold_rows = chain.rows
            fold_net = chain.net_usd
            fold_costs = chain.costs_usd
            fold_fills = chain.fills
            oos_run_id = run_id
            oos_artifact_id = facts.artifact_id
            oos_time_in_market = _metric(float(facts.time_in_market), "fraction")
        last_row = fold_rows[-1]["closing_equity_usd"]
        assert isinstance(last_row, Decimal)  # the chain's closing equity, always exact money
        opening = last_row
        rows.extend(fold_rows)
        fold_nets.append(fold_net)
        folds_document.append(
            {
                "fold": fold.index,
                "status": status,
                "train": {
                    "start": fold.train[0].isoformat(),
                    "end": fold.train[-1].isoformat(),
                    "trade_dates": len(fold.train),
                },
                "test": {
                    "start": fold.test[0].isoformat(),
                    "end": fold.test[-1].isoformat(),
                    "trade_dates": len(fold.test),
                },
                "selection": None
                if selected is None
                else {
                    "candidate": selected.candidate.name,
                    "position": selected.candidate.position,
                },
                "selection_reason": reason,
                "oos": {
                    "candidate": None if selected is None else selected.candidate.name,
                    "run_id": oos_run_id,
                    "artifact_id": oos_artifact_id,
                    "net_pnl_usd": _metric(fold_net, "usd"),
                    "costs_usd": _metric(fold_costs, "usd"),
                    "fills": _metric(Decimal(fold_fills), "count"),
                    "terminal_exit_cost_usd": _metric(terminal, "usd"),
                    "open_contracts_at_last_bar": open_contracts,
                    "time_in_market": oos_time_in_market,
                },
            }
        )
        audit_folds.append(
            {
                "fold": fold.index,
                "train": {
                    "start": fold.train[0].isoformat(),
                    "end": fold.train[-1].isoformat(),
                    "trade_dates": len(fold.train),
                },
                "candidates": audited,
            }
        )

    oos_frame = _oos_frame(rows)
    pbo_panel = _pbo_panel(
        loaded,
        store_root=store_root,
        artifacts_root=artifacts_root,
        overwrite=overwrite,
        warmup=warmup,
    )
    estimate = futures_effective_trials(base.run.family, artifacts_root=artifacts_root)
    stability = {
        "fold_oos_net_pnl_usd": [_metric(net, "usd") for net in fold_nets],
        "folds_positive": sum(1 for net in fold_nets if net > 0),
        "folds_negative": sum(1 for net in fold_nets if net < 0),
        "folds_flat": sum(1 for net in fold_nets if net == 0),
    }
    document: dict[str, object] = {
        "schema_version": WALKFORWARD_SCHEMA_VERSION,
        "kind": "futures_walkforward",
        "wf_id": identifier,
        "family": base.run.family,
        "base_config_hash": futures_config_hash(base),
        "fidelity": base.fidelity.record(),
        "scheme": scheme,
        "train_trade_dates": train_dates,
        "test_trade_dates": test_dates,
        "warmup_trade_dates": warmup,
        "constraints": constraints.model_dump(mode="json"),
        "folds": folds_document,
        "oos": {
            **_oos_summary(oos_frame, base.capital),
            "statistics": _oos_statistics(
                oos_frame,
                base=base,
                identifier=identifier,
                registry=registry,
                estimate=estimate,
            ),
        },
        "window_stability": stability,
        "in_sample_audit": {"note": IN_SAMPLE_NOTE, "folds": audit_folds},
        "unused_trade_dates": [day.isoformat() for day in unused],
        "terminal_exit": TERMINAL_EXIT_NOTE,
        "trials": {
            "submission_count": registry.submission_count(base.run.family),
            "unique_candidate_count": registry.unique_candidate_count(base.run.family),
            "total_trials": registry.total_trials(base.run.family),
        },
        "verdict": verdict_document().model_dump(mode="json"),
    }
    if pbo_panel is not None:
        audit = cast("dict[str, object]", document["in_sample_audit"])
        audit["pbo_panel"] = pbo_panel
        document["pbo"] = {
            "pointer": "in_sample_audit.pbo_panel",
            "note": (
                "the probability of backtest overfitting of this walk-forward is computed on the "
                "full-window panel of its distinct candidates (one extra run each, recorded as "
                "trials of the same candidates, so total_trials does not grow) and reported under "
                "in_sample_audit.pbo_panel. It is never computed on the selected out-of-sample "
                "path (ADR-0104 decision 6): " + PBO_PANEL_RULE
            ),
        }
    walkforward_dir = artifacts_root / identifier
    walkforward_dir.mkdir(parents=True, exist_ok=True)
    (walkforward_dir / "walkforward.json").write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    _write_parquet(oos_frame, walkforward_dir / "oos_daily.parquet")
    return WalkForwardResult(walkforward_dir=walkforward_dir, wf_id=identifier, document=document)


__all__ = [
    "CONSTRAINTS",
    "FOLD_STATUSES",
    "IN_SAMPLE_NOTE",
    "OOS_DAILY_SCHEMA",
    "SCHEMES",
    "TERMINAL_EXIT_NOTE",
    "WALKFORWARD_SCHEMA_VERSION",
    "WF_ID_HEX",
    "WF_ID_PREFIX",
    "Fold",
    "FuturesWalkForward",
    "FuturesWalkForwardConstraints",
    "FuturesWalkForwardFile",
    "WalkForwardResult",
    "constraint_checks",
    "futures_walkforward_json_schema",
    "load_futures_walkforward",
    "run_futures_walkforward",
    "terminal_exit_cost",
    "walkforward_folds",
    "walkforward_id",
    "walkforward_trade_dates",
]
