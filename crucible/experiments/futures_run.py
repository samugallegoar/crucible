"""The futures run: one config in, one sealed artifact and one registered trial out (ADR-0095).

``run_futures`` is the whole futures pipeline behind one call: read the four datasets of a
continuous build (ADR-0086), cut them to a window of Globex trade dates on the CME session
calendar (ADR-0091), decide signed whole-contract targets with the signal bridge
(``futures_targets``), simulate them with ``simulate_futures`` (ADR-0090), and write the artifact:
per-bar marks, the daily ledger, fills, rolls, ``config.yaml``, descriptive ``metrics.json`` and a
manifest that says exactly what was assumed.

Three things are enforced here rather than documented:

- **determinism**: nothing in a result file reads the wall clock (the only time is the seal's
  ``created_at``, added by ``seal_artifact``) and every frame is written in a stable order, so the
  same config and the same datasets reproduce byte-identical Parquet and the same ``artifact_id``;
- **the ledger balances**: ``check_daily_ledger`` runs before anything is written, and a broken
  identity refuses the run instead of shipping a plausible-looking file;
- **the trial is counted**: the run registers itself in the root's trial registry before sealing,
  because a statistic from a run whose siblings are not counted cannot be read (ADR-0008).

``fidelity`` (C5a, ADR-0100) makes the run read a coarser, cheaper version of the same series: a
resolution of ``5m``/``15m`` aggregates both series causally (``crucible.data.resample``) BEFORE
the bridge sees them, so the bar length downstream is 60 x the resolution and a decision at a close
still reads only bars that had closed; ``cost_detail: commission_only`` charges commission and fees
only and records the optimism.

The run id is ``FUT-`` + a SHA-256 over the config hash, the four dataset content hashes, the
session calendar's table hash, the contract-spec table hash and the simulator version: the same
id exactly when the same inputs would be simulated the same way. The run directory is the id, and
an existing one is refused unless ``overwrite`` is set.

Units: ``capital`` and every ``*_usd`` value in USD, prices in points, times UTC int64 ns, the
window in Globex trade dates.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.core.types import NS_PER_S, DatasetId, TimestampNs
from crucible.data.cme_sessions import session_trade_dates, table_summary
from crucible.data.continuous import calendar_for
from crucible.data.contracts import END_AT_OPEN, ROLL_SCHEMA
from crucible.data.futures_specs import futures_spec, spec_table_hash
from crucible.data.resample import resample_session_bars
from crucible.data.store import ParquetDataStore, price_basis_of
from crucible.execution.futures_sim import SIMULATOR_VERSION, simulate_futures
from crucible.experiments.artifact_id import read_seal, seal_artifact, write_manifest
from crucible.experiments.futures_artifacts import (
    MARKING_POLICY,
    UNHEDGED_MARK_NOTE,
    build_daily,
    build_fills,
    build_marks,
    build_metrics,
    build_rolls,
    check_daily_ledger,
)
from crucible.experiments.futures_config import (
    BAR_SECONDS,
    FuturesRunConfig,
    canonical_futures_yaml,
    futures_config_hash,
)
from crucible.experiments.futures_signals import DatasetRef, FuturesSignalFunction, futures_targets
from crucible.experiments.runner import import_entrypoint
from crucible.strategy_spec.models import parse_spec
from crucible.validation.trial_registry import DuckDBTrialRegistry

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crucible.data.cme_sessions import SessionCalendar
    from crucible.data.interfaces import DatasetManifest
    from crucible.dsl.compile import CompiledSignal
    from crucible.strategy_spec.models import StrategySpec

RUN_ID_PREFIX = "FUT-"
RUN_ID_HEX = 16
"""Hex digits of the SHA-256 kept in the run id (64 bits: collisions are negligible at this
scale, and the artifact id carries the stricter identity)."""

SCHEMA_VERSION = 1
"""Version of this artifact layout (its file set and column set)."""

MODE = "futures"
"""The trial registry's ``mode`` for a futures run (neither optimization nor evaluation: the run
is one evaluation of one config, and the registry counts it as a trial, ADR-0008)."""

DATASET_ROLES = ("execution", "signal", "rolls", "raw")
"""The four roles, in the fixed order the run id hashes them."""

RESULT_FILES = (
    "config.yaml",
    "daily.parquet",
    "fills.parquet",
    "marks.parquet",
    "metrics.json",
    "rolls.parquet",
)
"""The result files of a run directory (the artifact digest covers exactly these)."""

_NS_PER_DAY = 86_400 * NS_PER_S
_RAW_COLUMNS = ("symbol", "event_time", "open", "high", "low", "close")


@dataclass(frozen=True, slots=True)
class FuturesRunResult:
    """What a finished run hands back. ``summary`` is JSON-ready (decimals as strings)."""

    run_dir: Path
    run_id: str
    artifact_id: str
    trial_count: int
    summary: dict[str, object]


# ---------------------------------------------------------------------------------------------
# a. the datasets


def _manifest(store: ParquetDataStore, store_root: Path, name: str, role: str) -> DatasetManifest:
    """The dataset's manifest, refusing a dataset the store does not hold."""
    if not (store_root / name / "manifest.json").is_file():
        msg = (
            f"dataset {name!r} (role {role}) is not in the store {store_root}: no manifest.json "
            "there. Build the continuous futures datasets with `crucible data build` (ADR-0086), "
            "or point the run at the store that holds them"
        )
        raise DataQualityError(msg)
    return store.manifest(DatasetId(name))


def _adjustment(role: str, name: str, manifest: DatasetManifest, basis: str) -> str:
    """The ``adjustment=`` token of the dataset's ``source`` (``none`` for a raw series)."""
    for part in manifest.source.split(";"):
        key, _, value = part.partition("=")
        if key.strip() == "adjustment" and value.strip():
            return value.strip()
    if basis == "raw":
        return "none"
    msg = (
        f"dataset {name!r} (role {role}) declares price_basis={basis!r} but its manifest source "
        f"names no adjustment= token ({manifest.source!r}): the run cannot say which adjustment "
        "made these prices. Rebuild the series with `crucible data build` (it writes "
        "adjustment=ratio for the ratio-adjusted series, ADR-0086)"
    )
    raise DataQualityError(msg)


def _dataset_ref(role: str, name: str, manifest: DatasetManifest) -> DatasetRef:
    """What the manifest says about a dataset: the run records this, never the data.

    The execution series, the raw per-contract bars and the rolls table are the contracts' own
    traded prices by construction (``price_basis=raw``): the execution series must declare it,
    because the signal path's guards are built on that declaration, and the other two default to
    it when they say nothing. The signal series may be either and is checked against
    ``signal.input`` by the bridge (ADR-0086, decision 8).
    """
    declared = price_basis_of(manifest)
    if declared is None and role in ("execution", "signal"):
        msg = (
            f"dataset {name!r} (role {role}) does not declare its price basis: its manifest "
            f"source ({manifest.source!r}) has no price_basis=raw|adjusted. The futures path "
            "needs to know whether it is reading traded prices or a research series; rebuild it "
            "with `crucible data build` (ADR-0086)"
        )
        raise DataQualityError(msg)
    basis = declared if declared is not None else "raw"
    if role in ("execution", "rolls", "raw") and basis != "raw":
        msg = (
            f"dataset {name!r} (role {role}) declares price_basis={basis!r}, but the {role} rows "
            "must be the contracts' own traded prices (price_basis=raw): fills, P&L and the "
            "causal roll legs are computed on them, and an adjusted series has no execution "
            "prices (ADR-0086). Use the unadjusted continuous series and the raw per-contract "
            "bars"
        )
        raise DataQualityError(msg)
    return DatasetRef(
        dataset=name,
        content_hash=manifest.content_hash,
        price_basis="raw" if basis == "raw" else "adjusted",
        adjustment=_adjustment(role, name, manifest, basis),
    )


def _read(store: ParquetDataStore, name: str) -> pl.LazyFrame:
    """Every row of a dataset: the open-ended sentinel is a run-level read, not a strategy read
    (the window is cut from trade dates below, and the bridge decides bar by bar)."""
    return store.read(DatasetId(name), TimestampNs(END_AT_OPEN))


# ---------------------------------------------------------------------------------------------
# b. the window


@dataclass(frozen=True, slots=True)
class _Bars:
    """The bars a run simulates: the rows kept, their trade dates and their schedule flags."""

    execution: pl.DataFrame
    trade_dates: pl.Series
    on_schedule: pl.Series

    @property
    def first_ns(self) -> int:
        return int(self.execution["event_time"][0])

    @property
    def last_ns(self) -> int:
        return int(self.execution["event_time"][-1])


def _window_bars(
    config: FuturesRunConfig,
    calendar: SessionCalendar,
    execution_all: pl.DataFrame,
    bar_seconds: int | None = None,
) -> _Bars:
    """Keep the bars whose Globex trade date is in the window (refusing an empty window).

    ``bar_seconds``: the length of the bars in ``execution_all`` (``None``: the run's own fidelity
    grid). The bar length is what places a bar in its scheduled segment, so the one-minute source
    window is measured with ``BAR_SECONDS`` even when the run simulates coarser bars.
    """
    step = config.fidelity.bar_seconds if bar_seconds is None else bar_seconds
    days, on_schedule = session_trade_dates(calendar, execution_all["event_time"].to_numpy(), step)
    date_series = pl.Series("trade_date", days).cast(pl.Date)
    keep = pl.Series(
        "keep",
        np.asarray(date_series >= config.window.start)
        & np.asarray(date_series <= config.window.end),
        dtype=pl.Boolean,
    )
    if not bool(keep.any()):
        msg = (
            f"no bar of the execution dataset {config.datasets.execution} falls on a Globex "
            f"trade date in [{config.window.start}, {config.window.end}]: the window is a range "
            "of trade dates, inclusive. Widen the window or check the dataset's dates"
        )
        raise DataQualityError(msg)
    return _Bars(
        execution=execution_all.filter(keep).sort("event_time"),
        trade_dates=date_series.filter(keep),
        on_schedule=pl.Series("on_schedule", on_schedule, dtype=pl.Boolean).filter(keep),
    )


def _window_signal(signal: pl.DataFrame, bars: _Bars) -> pl.DataFrame:
    """The signal frame's rows for exactly the kept bars (same event_times, same order)."""
    return signal.filter(pl.col("event_time").is_in(bars.execution["event_time"].to_list())).sort(
        "event_time"
    )


def _resampled(
    config: FuturesRunConfig, calendar: SessionCalendar, frame: pl.DataFrame, what: str
) -> tuple[pl.DataFrame, int, int]:
    """``frame`` aggregated to the run's fidelity resolution, with its resampling counts.

    ``fidelity.resolution = 1m`` is the identity (the stored series, nothing dropped, no bucket
    clipped). A coarser resolution aggregates the one-minute bars causally
    (``resample_session_bars``): a bucket never spans a maintenance break or a session boundary, an
    off-schedule bar is not aggregated and is counted, and a bucket with no constituent produces no
    bar. ``what`` names the frame in refusals.

    A bucket CLIPPED by a session's open or close (``partial``) refuses a coarser run: the session
    rules (``flat_by_close``, ``exit_at``) are evaluated on a bar grid that starts at the
    session's scheduled open, and a clipped bucket is off that grid, so the run would either treat
    a tradable bucket as off schedule or pick the wrong final bar. No CME Globex session of this
    table opens or closes off a 5- or 15-minute boundary, so this is a guard, not a limit.
    """
    if not config.fidelity.resampled:
        return frame, 0, 0
    try:
        result = resample_session_bars(
            frame, calendar=calendar, minutes=config.fidelity.minutes, source_seconds=BAR_SECONDS
        )
    except DataQualityError as exc:
        msg = f"the {what} series cannot be resampled to {config.fidelity.resolution}: {exc}"
        raise DataQualityError(msg) from exc
    if result.partial_buckets:
        clipped = result.bars.filter(pl.col("partial"))["event_time"].to_list()
        msg = (
            f"the {what} series has {len(clipped)} {config.fidelity.resolution} bucket(s) clipped "
            f"by a session open or close (first: event_time={int(clipped[0])} ns): the session "
            "rules are evaluated on a grid anchored at the session's scheduled open, so a run "
            "cannot simulate a clipped bucket honestly. Use resolution=1m for this window, or "
            "fix the session schedule"
        )
        raise DataQualityError(msg)
    return result.bars, result.dropped_off_schedule, result.partial_buckets


def _window_rolls(config: FuturesRunConfig, rolls_all: pl.DataFrame, bars: _Bars) -> pl.DataFrame:
    """The rolls that become effective inside the window and are decided inside it.

    ``effective_trade_date`` is the first trade date of the new contract, so a roll effective on
    the window's first day happened before it and cannot be executed here (the series already
    holds the new contract at the first bar). A roll whose decision bar lies at or after the last
    kept bar switches the series after the window: it is not simulated either. What remains is
    exactly the set of switches ``simulate_futures`` must be able to execute.
    """
    effective = pl.col("effective_trade_date").str.to_date("%Y-%m-%d")
    return rolls_all.filter(
        (effective > config.window.start)
        & (effective <= config.window.end)
        & (pl.col("event_time") > bars.first_ns)
        & (pl.col("event_time") < bars.last_ns)
    ).select(list(ROLL_SCHEMA))


def _window_raw(raw_all: pl.DataFrame, bars: _Bars) -> pl.DataFrame:
    """The raw per-contract bars from the day before the window to its last bar: enough for every
    causal roll leg, and not the whole contract history."""
    return raw_all.filter(
        pl.col("event_time").is_between(bars.first_ns - _NS_PER_DAY, bars.last_ns)
    ).sort("event_time")


# ---------------------------------------------------------------------------------------------
# c. the strategy


def _strategy(
    config: FuturesRunConfig,
) -> StrategySpec | FuturesSignalFunction | CompiledSignal:
    """The spec (parsed), the compiled DSL expression or the imported signal function."""
    if config.strategy.spec is not None:
        return parse_spec(config.strategy.spec)
    if config.strategy.expression is not None:
        # compiled with the config's params and signal role: the ids land in the manifest record
        return config.strategy.compiled_signal(config.signal.input)
    entrypoint = config.strategy.entrypoint
    assert entrypoint is not None  # guaranteed by the config's exactly-one rule
    candidate = import_entrypoint(entrypoint)
    if not callable(candidate):
        msg = (
            f"strategy.entrypoint {entrypoint!r} resolved to {type(candidate).__name__}, which "
            "is not callable: a futures signal is a function (or an object) called as "
            "strategy(bars, params) -> LazyFrame(ts, score)"
        )
        raise ConfigurationError(msg)
    return candidate  # type: ignore[return-value]


# ---------------------------------------------------------------------------------------------
# d. the run


def run_id_basis(
    config: FuturesRunConfig, refs: Mapping[str, DatasetRef], calendar_hash: str
) -> str:
    """The text the run id hashes: config, the four datasets in a fixed order, the calendar, the
    contract-spec table and the simulator version."""
    parts = [
        futures_config_hash(config),
        *(refs[role].content_hash for role in DATASET_ROLES),
        calendar_hash,
        spec_table_hash(),
        SIMULATOR_VERSION,
    ]
    return "|".join(parts)


def _run_id(config: FuturesRunConfig, refs: Mapping[str, DatasetRef], calendar_hash: str) -> str:
    """``FUT-`` + the truncated SHA-256 of ``run_id_basis``."""
    return (
        RUN_ID_PREFIX
        + hashlib.sha256(run_id_basis(config, refs, calendar_hash).encode("utf-8")).hexdigest()[
            :RUN_ID_HEX
        ]
    )


def futures_run_id(config: FuturesRunConfig, *, store_root: Path) -> str:
    """The run id ``config`` would get against ``store_root``, WITHOUT simulating anything.

    Same basis as ``run_futures`` (the config hash, the four datasets' content hashes, the session
    calendar's table hash, the contract-spec table hash and the simulator version), so a caller can
    ask "has this exact run been computed already?" by looking for ``artifacts_root/run_id``. Reads
    only the datasets' manifests; refuses the same missing/undeclared datasets a run would.
    """
    calendar = calendar_for(config.root)
    store = ParquetDataStore(store_root)
    names = {role: getattr(config.datasets, role) for role in DATASET_ROLES}
    refs = {
        role: _dataset_ref(role, names[role], _manifest(store, store_root, names[role], role))
        for role in DATASET_ROLES
    }
    return _run_id(config, refs, str(table_summary(calendar.table)["sha256"]))


def _approximations(
    config: FuturesRunConfig,
    rolls: pl.DataFrame,
    signal_record: Mapping[str, object],
    fidelity: Mapping[str, object],
) -> list[str]:
    """What the run assumed: the OHLC marks, uncalibrated costs, approximate rolls, unverified
    sessions, and what a reduced fidelity level leaves out. Each entry says the thing in plain
    words, because a reader of the artifact needs to know what is measured and what is assumed."""
    out = [UNHEDGED_MARK_NOTE]
    costs = config.costs
    if config.fidelity.cost_detail == "commission_only":
        out.append("costs reduced to commission and fees (fidelity screen): optimistic")
    elif not (costs.spread_calibrated and costs.slippage_calibrated):
        uncalibrated = [
            name for name in ("spread", "slippage") if not getattr(costs, f"{name}_calibrated")
        ]
        out.append(
            f"costs uncalibrated: {' and '.join(uncalibrated)} in ticks are the config's "
            "assumption, not a measurement on this instrument and period"
        )
    if config.fidelity.resampled:
        out.append(
            f"bars aggregated to {config.fidelity.resolution} by a causal resampling of the "
            f"{BAR_SECONDS}s series: a bucket never spans a maintenance break or a session "
            f"boundary, {fidelity['dropped_off_schedule']} off-schedule bar(s) were not "
            f"aggregated and {fidelity['partial_buckets']} bucket(s) are clipped by a session "
            "open or close"
        )
        out.append(
            "causal rolls execute at the first coarse-bar open at or after the first joint 1m "
            "print (delay up to one coarse bar)"
        )
    approximate = rolls.filter(pl.col("mode") == "reference_approximation")
    if approximate.height:
        pairs = ", ".join(
            f"{row['from_contract']}->{row['to_contract']}"
            for row in approximate.iter_rows(named=True)
        )
        out.append(
            f"{approximate.height} roll(s) valued at reference prices "
            f"(reference_approximation, not causal): {pairs}"
        )
    unverified = signal_record.get("unverified_sessions")
    if config.session.allow_unverified_sessions and isinstance(unverified, list) and unverified:
        days = [str(day) for day in unverified[:5]]
        out.append(
            "unverified sessions allowed: the CME schedule of "
            f"{len(unverified)} trade date(s) is not covered by a transcribed source "
            f"({', '.join(days)})"
        )
    return out


def _write_parquet(frame: pl.DataFrame, path: Path) -> None:
    """Deterministic Parquet: uncompressed, no statistics, so identical frames are identical
    bytes (ADR-0011)."""
    frame.write_parquet(path, compression="uncompressed", statistics=False)


def _replace(run_dir: Path, overwrite: bool) -> None:
    """Create the run directory, or replace it (keeping the previous seal for ``created_at``)."""
    if run_dir.exists():
        if not overwrite:
            msg = (
                f"run directory {run_dir} already exists: this config and these datasets were "
                "already simulated. Pass overwrite=True to re-run it (a reproduction keeps the "
                "same artifact id, and the trial count of the family does not grow)"
            )
            raise ConfigurationError(msg)
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)


def run_futures(
    config: FuturesRunConfig,
    *,
    store_root: Path,
    artifacts_root: Path,
    overwrite: bool = False,
) -> FuturesRunResult:
    """Simulate one futures config and write its sealed artifact.

    ``store_root``: the ParquetDataStore root holding the four datasets. ``artifacts_root``: where
    the run directory and the shared ``trial_registry.duckdb`` live. ``overwrite``: replace an
    existing run directory (the same config and data reproduce the same artifact id).

    Timing: the whole run is a function of the config and the datasets; nothing reads the clock
    except the artifact seal. Pessimism: fills come from ``simulate_futures`` (next-eligible-open
    by default, stops before targets, nothing fills off schedule), the daily ledger is asserted
    against the marks, and an unverified session or an approximate roll is recorded as an
    approximation rather than passed off as measured. A fidelity resolution coarser than ``1m``
    aggregates both series causally BEFORE the bridge sees them (``_resampled``), so the decision
    at a bar's close still reads only bars that had closed by then.
    """
    calendar = calendar_for(config.root)
    spec = futures_spec(config.root)
    store = ParquetDataStore(store_root)
    names = {role: getattr(config.datasets, role) for role in DATASET_ROLES}
    manifests = {role: _manifest(store, store_root, names[role], role) for role in DATASET_ROLES}
    refs = {role: _dataset_ref(role, names[role], manifests[role]) for role in DATASET_ROLES}

    # the window of the SOURCE series first: its one-minute bars are what a coarser resolution
    # aggregates, so the signal series is read for exactly the same source instants and both are
    # aggregated with the same function (the bridge's alignment check then passes by construction)
    source_bars = _window_bars(
        config, calendar, _read(store, names["execution"]).collect(), BAR_SECONDS
    )
    # the signal, rolls and raw scans are bounded before they are materialized: the C3 store
    # holds years of minute bars and the whole contract history, and only these rows are read
    signal_source = (
        _read(store, names["signal"])
        .filter(pl.col("event_time").is_between(source_bars.first_ns, source_bars.last_ns))
        .collect()
    )
    execution, dropped_execution, partial_execution = _resampled(
        config, calendar, source_bars.execution, "execution"
    )
    signal, dropped_signal, partial_signal = _resampled(config, calendar, signal_source, "signal")
    bars = _window_bars(config, calendar, execution)
    signal = _window_signal(signal, bars)
    rolls = _window_rolls(config, _read(store, names["rolls"]).collect(), bars)
    raw = _window_raw(_read(store, names["raw"]).collect(), bars)
    missing = [name for name in _RAW_COLUMNS if name not in raw.columns]
    if missing:
        msg = (
            f"the raw dataset {names['raw']} lacks {missing}: the causal roll legs need the "
            "per-contract bars (symbol, event_time, OHLC) of BAR_SCHEMA"
        )
        raise DataQualityError(msg)
    first_ns, last_ns = bars.first_ns, bars.last_ns
    fidelity = config.fidelity.record(
        dropped_off_schedule=dropped_execution + dropped_signal,
        partial_buckets=partial_execution + partial_signal,
    )

    targets = futures_targets(
        root=config.root,
        execution_bars=bars.execution,
        signal_bars=signal,
        execution_ref=refs["execution"],
        signal_ref=refs["signal"],
        strategy=_strategy(config),
        contracts=config.contracts,
        signal_input=config.signal.input,
        session=config.session_policy(),
        params=config.strategy.params,
        bar_seconds=config.fidelity.bar_seconds,
    )
    simulation = simulate_futures(
        bars=bars.execution.with_columns(targets.on_schedule),
        targets=targets.targets,
        rolls=rolls,
        spec=spec,
        costs=config.cost_schedule(),
        initial_capital=config.capital,
        policy=config.execution_policy(),
        raw=raw,
    )

    marks = build_marks(
        bars=simulation.bars,
        execution=bars.execution,
        trade_dates=bars.trade_dates,
        on_schedule=targets.on_schedule,
        spec=spec,
    )
    fills = build_fills(fills=simulation.fills, marks=marks)
    rolls = build_rolls(simulation.rolls)
    daily = build_daily(
        marks=marks,
        bars=simulation.bars,
        fills=fills,
        calendar=calendar,
        capital=config.capital,
    )
    check_daily_ledger(daily, marks, config.capital)
    metrics = build_metrics(
        marks=marks, daily=daily, fills=fills, rolls=rolls, capital=config.capital
    )

    calendar_summary = table_summary(calendar.table)
    run_id = _run_id(config, refs, str(calendar_summary["sha256"]))
    run_dir = artifacts_root / run_id
    prior = read_seal(run_dir) if run_dir.is_dir() else None
    _replace(run_dir, overwrite)

    registry = DuckDBTrialRegistry(artifacts_root / "trial_registry.duckdb")
    trial_count = registry.record_trial(
        config.run.family,
        run_id,
        sharpe=None,
        mode=MODE,
        start_ns=first_ns,
        end_ns=last_ns,
        period_ns=config.fidelity.bar_seconds * NS_PER_S,
    )

    manifest: dict[str, object] = {
        "kind": "futures_run",
        "schema_version": SCHEMA_VERSION,
        "experiment_id": run_id,
        "run_name": config.run.name,
        "trial_family": config.run.family,
        "config_hash": futures_config_hash(config),
        "root": config.root,
        "window": {
            "start": config.window.start.isoformat(),
            "end": config.window.end.isoformat(),
        },
        "datasets": {role: asdict(refs[role]) for role in DATASET_ROLES},
        "fidelity": fidelity,
        "signal": targets.record,
        "execution_policy": simulation.policy,
        "strict_execution": simulation.strict_execution,
        "session_calendar": calendar_summary,
        "marking_policy": MARKING_POLICY,
        "approximations": _approximations(config, rolls, targets.record, fidelity),
        "files": sorted(RESULT_FILES),
        "bars": marks.height,
        "trade_dates": daily.height,
        "trial_count": trial_count,
    }
    (run_dir / "config.yaml").write_text(
        canonical_futures_yaml(config), encoding="utf-8", newline="\n"
    )
    write_manifest(run_dir, manifest)
    _write_parquet(marks, run_dir / "marks.parquet")
    _write_parquet(daily, run_dir / "daily.parquet")
    _write_parquet(fills, run_dir / "fills.parquet")
    _write_parquet(rolls, run_dir / "rolls.parquet")
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    artifact_id = seal_artifact(run_dir, prior=prior)
    summary: dict[str, object] = {
        "run_name": config.run.name,
        "trial_family": config.run.family,
        "bars": marks.height,
        "trade_dates": daily.height,
        "fills": fills.height,
        "rolls": rolls.height,
        "strict_execution": simulation.strict_execution,
        "final_balance_usd": str(daily["closing_balance_usd"][-1]),
        "final_equity_usd": str(daily["closing_equity_usd"][-1]),
        "trial_count": trial_count,
    }
    return FuturesRunResult(
        run_dir=run_dir,
        run_id=run_id,
        artifact_id=artifact_id,
        trial_count=trial_count,
        summary=summary,
    )


__all__ = [
    "DATASET_ROLES",
    "MODE",
    "RESULT_FILES",
    "RUN_ID_PREFIX",
    "SCHEMA_VERSION",
    "FuturesRunResult",
    "futures_run_id",
    "run_futures",
    "run_id_basis",
]
