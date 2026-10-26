"""Experiment runner: config -> quality gate -> engine -> artifacts.

Artifact layout per run:
``<root>/<EXP-ID>/{config.yaml, manifest.json, ledger.parquet,
orders.parquet, fills.parquet, trades.parquet, equity.parquet, metrics.json,
equity.svg, report.html, logs/run.jsonl}``

Determinism (E1): all Parquet artifacts are written uncompressed with fixed
row order (ADR-0011); metrics.json and manifest.json use sorted keys; the
experiment id is a pure function of config hash + data hashes. manifest.json
additionally records commit/dirty/env — provenance, deliberately outside the
byte-identity golden surface because it changes with the repo, not the run.
"""

from __future__ import annotations

import importlib
import json
import multiprocessing
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np
import polars as pl

from crucible import __version__ as crucible_version
from crucible.analytics.interfaces import MetricValue
from crucible.analytics.metrics import compute_metrics, simple_returns
from crucible.analytics.plots import plot_equity_drawdown
from crucible.analytics.report import render_report
from crucible.analytics.trades import EPISODE_LABEL, build_trades
from crucible.core import checkpoint as ckpt
from crucible.core.checkpoint import read_checkpoint
from crucible.core.engine import BacktestEngine, BacktestResult
from crucible.core.errors import ConfigurationError, CrucibleError, ExperimentError
from crucible.core.instruments import FuturesSpec
from crucible.core.stats import is_degenerate_returns, per_period_sharpe
from crucible.core.types import Currency, DatasetId, ExperimentId, Symbol, TimestampNs
from crucible.data.calendars import get_trading_calendar, periods_per_year_for
from crucible.data.contracts import BAR_QUOTE_SCHEMA
from crucible.data.quality import run_quality_checks
from crucible.data.store import ParquetDataStore, price_basis_of
from crucible.execution import registry
from crucible.execution.ladder import ExecutionSetup, ParticipationLimits
from crucible.execution.models import MarketStats
from crucible.experiments.artifacts import (
    EQUITY_SCHEMA,
    FILL_SCHEMA,
    LEDGER_SCHEMA,
    ORDER_SCHEMA,
    SCHEMA_VERSION,
)
from crucible.experiments.config import (
    ExecutionConfig,
    ExperimentConfig,
    RiskConfig,
    canonical_yaml,
    config_hash,
)
from crucible.risk import registry as risk_registry
from crucible.risk.engine import CompositeRiskEngine
from crucible.validation.contamination import check_contamination
from crucible.validation.dsr import DsrResult, deflated_sharpe_ratio
from crucible.validation.monte_carlo import (
    BlockBootstrapTest,
    ReturnOrderShuffleTest,
    StartDateShiftTest,
)
from crucible.validation.trial_registry import (
    DuckDBTrialRegistry,
    frequency_mismatch,
    median_period_ns,
)

N_MONTE_CARLO_ITERATIONS = 1_000

Runtime = Literal["backtest", "paper", "live"]

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from decimal import Decimal

    from numpy.typing import NDArray

    from crucible.core.interfaces import Event
    from crucible.core.types import RealismLevel
    from crucible.execution.backend import ExecutionBackend, ExecutionContext
    from crucible.live.feed import FeedContext
    from crucible.live.interfaces import DataFeed
    from crucible.strategy.interfaces import Strategy


@dataclass(frozen=True, slots=True)
class RunArtifacts:
    experiment_id: ExperimentId
    path: Path
    metrics: dict[str, MetricValue]
    report_path: Path


def import_entrypoint(entrypoint: str) -> object:
    """Resolves a ``module.path:attr`` string to the raw module attribute
    (a class, a function -- whatever the caller's config field names).
    Shared by ``_load_strategy`` (instantiates a `Strategy` class) and
    ``crucible.experiments.vectorized_runner`` (uses a `SignalFunction`
    directly, no instantiation)."""
    import sys
    from pathlib import Path as _P

    module_name, _, attr_name = entrypoint.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        # CLI runs resolve entrypoints relative to the working directory
        # (e.g. examples.momentum.strategy when run from the repo root).
        cwd = str(_P.cwd())
        if cwd not in sys.path:
            sys.path.insert(0, cwd)
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            msg = f"cannot import entrypoint {entrypoint!r}: {exc}"
            raise ConfigurationError(msg) from exc
    try:
        return getattr(module, attr_name)
    except AttributeError as exc:
        msg = f"cannot import entrypoint {entrypoint!r}: {exc}"
        raise ConfigurationError(msg) from exc


def _load_strategy(entrypoint: str) -> Strategy:
    cls = import_entrypoint(entrypoint)
    strategy: Strategy = cls()  # type: ignore[operator]  # entrypoint names a class
    return strategy


def _resolution_root() -> Path:
    """The directory the loaded package lives in: the repository root in a source checkout
    (``crucible/experiments/runner.py`` is two levels down), ``site-packages`` when installed.

    Provenance is anchored here, not to the process's working directory, so that a run started
    from another directory (or from an installed package) still records the code that produced
    its numbers instead of silently writing ``unknown`` (AGENTS.md §10)."""
    from pathlib import Path as _P

    return _P(__file__).resolve().parents[2]


def _git_root(start: Path) -> Path | None:
    """The nearest directory at or above ``start`` that holds a ``.git`` entry (a directory, or
    a file for a worktree/submodule checkout). ``None`` outside a checkout."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _git_state(root: Path) -> tuple[str, bool] | None:
    """``(HEAD commit, working tree dirty)`` for the checkout at ``root``; ``None`` when git is
    unavailable or ``root`` is not a checkout."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return (commit, dirty) if commit else None


def _git_provenance() -> tuple[str, bool]:
    """``(HEAD commit, dirty)`` of the checkout Crucible itself runs from.

    Best effort, in order: the checkout that contains the loaded package, then the working
    directory's (a config and strategy may live in a different checkout than the library).
    No checkout at all (a wheel install outside any repository) is ``("unknown", True)``:
    honest, and unknown provenance counts as dirty (pessimism)."""
    for start in (_resolution_root(), Path.cwd()):
        root = _git_root(start)
        if root is None:
            continue
        state = _git_state(root)
        if state is not None:
            return state
    return "unknown", True


def _lockfile() -> Path | None:
    """``uv.lock`` of the checkout the code runs from, then of the working directory; ``None``
    when neither has one (an installed package does not ship the lockfile)."""
    for start in (_resolution_root(), Path.cwd()):
        root = _git_root(start) or start
        lock = root / "uv.lock"
        if lock.is_file():
            return lock
    return None


def _env_lock_hash() -> str:
    lock = _lockfile()
    if lock is None:
        return "unknown"
    return sha256(lock.read_bytes()).hexdigest()


def _code_fingerprint() -> str:
    """SHA-256 over ``HEAD``, ``git status --porcelain`` and ``git diff HEAD --binary``.

    Unlike the commit alone this changes when the working tree changes, so an uncommitted edit
    between two runs of the same config is visible to the overwrite guard (ADR-0079). It is
    best effort: a checkout that git cannot read, or no checkout at all, gives ``"unknown"``
    (the guard then falls back to commit + dirty). ``git`` does not diff untracked files, so a
    brand-new untracked strategy file is represented by its path, not its contents.
    """
    for start in (_resolution_root(), Path.cwd()):
        root = _git_root(start)
        if root is None:
            continue
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
            ).stdout.strip()
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            diff = subprocess.run(
                ["git", "diff", "HEAD", "--binary"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            continue
        return sha256(f"{commit}\n{status}\n{diff}".encode()).hexdigest()
    return "unknown"


def experiment_id(config: ExperimentConfig, data_hashes: dict[str, str]) -> ExperimentId:
    """Deterministic id: same config + same data ⇒ same id ⇒ same artifacts."""
    basis = config_hash(config) + "|" + "|".join(f"{k}={v}" for k, v in sorted(data_hashes.items()))
    return ExperimentId("EXP-" + sha256(basis.encode("utf-8")).hexdigest()[:12])


def _refuse_overwrite(
    out_dir: Path, *, commit: str, dirty: bool, fingerprint: str, overwrite: bool
) -> None:
    """Refuse to replace a finished run written by different code (ADR-0079).

    The experiment id hashes the config and the data, not the code, so re-running the same
    config after a code change resolves to the same directory; writing unconditionally would
    replace the earlier numbers with no trace that they came from other code. A re-run with the
    same code fingerprint (the commit plus the working tree's diff) is idempotent and allowed.
    ``overwrite=True`` (``--overwrite``) replaces it on purpose.
    """
    if overwrite:
        return
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.is_file():
        return
    try:
        previous: dict[str, object] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = (
            f"run directory {out_dir} holds a manifest that cannot be read ({exc}); refusing to "
            "overwrite it. Move it aside, or pass --overwrite to replace it"
        )
        raise ExperimentError(msg) from exc
    previous_commit = str(previous.get("commit", "unknown"))
    previous_dirty = bool(previous.get("dirty", True))
    previous_fingerprint = previous.get("code_fingerprint")
    if isinstance(previous_fingerprint, str) and fingerprint != "unknown":
        same_code = previous_fingerprint == fingerprint
    else:
        # an artifact written before the fingerprint existed: commit + dirty is the best it has
        same_code = previous_commit == commit and previous_dirty == dirty
    if same_code:
        return
    msg = (
        f"experiment {out_dir.name} already exists, written by commit={previous_commit} "
        f"dirty={previous_dirty}, but this run is commit={commit} dirty={dirty} with a "
        "different code fingerprint. The experiment id covers the config and the data, not the "
        "code, so writing here would replace the earlier results with numbers from different "
        f"code and leave no trace of them. Delete {out_dir}, use a different --artifacts root, "
        "or pass --overwrite to replace it on purpose"
    )
    raise ExperimentError(msg)


def _write_parquet(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(path, compression="uncompressed", statistics=False)


def build_execution_setup(execution: ExecutionConfig, level: RealismLevel) -> ExecutionSetup:
    """Turns the execution config into model instances, enforcing the level
    gating in ``execution/registry.py`` (ADR-0012). The shorthand bps fields
    and the model slots were already made mutually exclusive by config
    validation."""
    stats = MarketStats(execution.stats_window)

    def slot(config: object | None, default_key: str) -> tuple[str, dict[str, object]]:
        if config is None:
            return default_key, {}
        dumped = config.model_dump()  # type: ignore[attr-defined]  # all slots are models
        key = str(dumped.pop("type"))
        return key, dumped

    spread_key, spread_params = slot(execution.spread, "none")
    latency_key, latency_params = slot(execution.latency, "zero")
    if execution.slippage is not None:
        slippage_key, slippage_params = slot(execution.slippage, "none")
    elif execution.slippage_bps:
        slippage_key, slippage_params = "fixed_bps", {"bps": execution.slippage_bps}
    else:
        slippage_key, slippage_params = "none", {}
    if execution.commission is not None:
        commission_key, commission_params = slot(execution.commission, "none")
    elif execution.commission_bps:
        commission_key, commission_params = "bps", {"bps": execution.commission_bps}
    else:
        commission_key, commission_params = "none", {}

    participation = None
    if execution.participation is not None:
        participation = ParticipationLimits(**execution.participation.model_dump())

    return ExecutionSetup(
        spread=registry.build_spread(
            spread_key, level, **{k: float(str(v)) for k, v in spread_params.items()}
        ),
        latency=registry.build_latency(
            latency_key, level, **{k: float(str(v)) for k, v in latency_params.items()}
        ),
        slippage=registry.build_slippage(
            slippage_key,
            level,
            stats,
            **{k: float(str(v)) for k, v in slippage_params.items()},
        ),
        commission=registry.build_commission(commission_key, level, **commission_params),
        participation=participation,
        stats=stats,
    )


def build_risk_engine(
    risk: RiskConfig | None, base_currency: Currency
) -> CompositeRiskEngine | None:
    """`None` config means no risk engine at all -- distinct from a
    `RiskConfig` with empty limit lists, which builds an engine that
    always ALLOWs (harmless, but exercises the wiring)."""
    if risk is None:
        return None
    return CompositeRiskEngine(
        base_currency,
        pre_trade_limits=[
            risk_registry.build_pre_trade_limit(limit.type, **limit.model_dump(exclude={"type"}))
            for limit in risk.pre_trade
        ],
        mark_limits=[
            risk_registry.build_mark_limit(limit.type, **limit.model_dump(exclude={"type"}))
            for limit in risk.mark
        ],
    )


def _futures_spec(config: ExperimentConfig, symbol: str, multiplier: Decimal) -> FuturesSpec:
    margin = config.data.futures_margins.get(symbol)
    if margin is None:
        return FuturesSpec(multiplier=multiplier)
    return FuturesSpec(
        multiplier=multiplier,
        initial_margin=margin.initial,
        maintenance_margin=margin.maintenance,
    )


def assemble_engine(
    config: ExperimentConfig,
    *,
    store: ParquetDataStore | None = None,
    observer: Callable[[Event], None] | None = None,
    feed_factory: Callable[[FeedContext], DataFeed] | None = None,
    execution_backend_factory: Callable[[ExecutionContext], ExecutionBackend] | None = None,
) -> BacktestEngine:
    """Builds a ready-to-run engine from a validated config. Shared by the
    runner and the debug stepper so both execute identically.
    ``feed_factory`` overrides the default ``ReplayDataFeed`` (ADR-0039)."""
    store = store if store is not None else ParquetDataStore(config.data.store)
    return BacktestEngine(
        store=store,
        bars_dataset=DatasetId(config.data.bars),
        corporate_actions_dataset=(
            DatasetId(config.data.corporate_actions) if config.data.corporate_actions else None
        ),
        strategy=_load_strategy(config.strategy.entrypoint),
        params=config.strategy.params,
        initial_cash=config.initial_cash,
        base_currency=Currency(config.data.base_currency),
        realism_level=config.experiment.realism_level,
        start=config.start_ns,
        end=config.end_ns,
        execution=build_execution_setup(config.execution, config.experiment.realism_level),
        seed=config.experiment.seed,
        observer=observer,
        calendar=get_trading_calendar(
            config.data.calendar, start=config.start_ns, end=config.end_ns
        ),
        symbol_currency={
            Symbol(symbol): Currency(ccy) for symbol, ccy in config.data.symbol_currency.items()
        },
        fx_dataset=DatasetId(config.data.fx_rates) if config.data.fx_rates else None,
        risk_engine=build_risk_engine(config.risk, Currency(config.data.base_currency)),
        settlement_lag_days=config.settlement_lag_days,
        short_borrow_rate=config.short_borrow_rate,
        margin_financing_rate=config.margin_financing_rate,
        futures_specs={
            Symbol(symbol): _futures_spec(config, symbol, multiplier)
            for symbol, multiplier in config.data.futures_multipliers.items()
        },
        feed_factory=feed_factory,
        execution_backend_factory=execution_backend_factory,
    )


@dataclass(frozen=True, slots=True)
class _PendingRun:
    """Everything ``run_experiment`` needs *before* it touches the shared
    trial registry (ADR-0038): the quality gate, the engine run itself,
    metrics, and Monte Carlo are all pure functions of ``config`` plus the
    (read-only, safely-concurrent) data store -- computed once here so
    ``run_experiment_parallel`` can run this half in a worker process
    while ``_finalize_experiment`` (the registry-touching half) always
    runs serially in the parent, in caller-specified order."""

    config: ExperimentConfig
    artifacts_root: Path
    checks_ran: list[str]
    data_hashes: dict[str, str]
    exp_id: ExperimentId
    out_dir: Path
    family: str
    result: BacktestResult
    equity: pl.DataFrame
    trades: pl.DataFrame
    metrics: dict[str, MetricValue]
    returns: NDArray[np.float64]
    this_sharpe: float | None
    monte_carlo: dict[str, dict[str, float]]
    commit: str
    dirty: bool
    code_fingerprint: str
    runtime: str  # which runtime built the engine (ADR-0051)


def _check_runtime(config: ExperimentConfig, runtime: Runtime) -> None:
    """The runtime and the live feature flag must agree (ADR-0051): the live
    runtime is behind ``live.enabled`` (ADR-0043), and a live-enabled config is
    never silently run as a backtest."""
    live_on = config.live is not None and config.live.enabled
    if runtime == "live" and not live_on:
        msg = (
            "runtime 'live' needs `live: {enabled: true}` in the experiment config (the "
            "live runtime is behind a feature flag, ADR-0043)"
        )
        raise ConfigurationError(msg)
    if runtime != "live" and live_on:
        msg = (
            f"the config has live.enabled but the runtime is {runtime!r}; run a single live "
            "experiment with `crucible run --runtime live`, or set live.enabled to false "
            "(optimize, validate, sensitivity, scenario and backtest runs need it off)"
        )
        raise ConfigurationError(msg)


def _build_engine(
    config: ExperimentConfig, store: ParquetDataStore, runtime: Runtime
) -> BacktestEngine:
    """Only engine construction differs between runtimes; everything after
    ``engine.run()`` (metrics, artifacts) is shared."""
    if runtime == "paper":
        from crucible.live.runtime import PaperRuntime  # local: live.runtime imports this module

        return PaperRuntime(config, store=store).engine
    if runtime == "live":
        from crucible.live.runtime import LiveRuntime  # local: same cycle

        return LiveRuntime(config, store=store).engine
    return assemble_engine(config, store=store)


MAX_CHECKPOINTS = 100_000
"""Most periodic checkpoints one run may write; a smaller interval over a long span is refused
instead of looping for hours (ADR-0058)."""


@dataclass(frozen=True, slots=True)
class CheckpointWritten:
    """What ``checkpoint_experiment`` produced: the file and the session boundary it holds
    (UTC ns): the engine's clock after the last event handled, at or before ``stop_at``."""

    path: Path
    boundary_ts: TimestampNs


@dataclass(frozen=True, slots=True)
class _Prepared:
    engine: BacktestEngine
    checks_ran: list[str]
    data_hashes: dict[str, str]
    resumed_boundary: int | None
    periods_per_year: float


def _utc_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts // 1_000_000_000, tz=UTC).isoformat()


def _checkpoint_boundary(path: Path) -> int:
    header, _ = read_checkpoint(path)
    return ckpt.field(header, "boundary_ts", int)


def _require_directory(path: Path) -> None:
    if path.is_dir():
        msg = f"checkpoint path {path} is a directory; give a file name inside it"
        raise ConfigurationError(msg)
    if not path.parent.is_dir():
        msg = f"checkpoint path {path}: the directory {path.parent} does not exist; create it first"
        raise ConfigurationError(msg)


def _require_quote_columns(config: ExperimentConfig, store: ParquetDataStore) -> None:
    """A ``quoted`` spread on a bar dataset without quote columns is refused before the quality
    gate, so nothing is created (ADR-0060)."""
    spread = config.execution.spread
    if spread is None or spread.type != "quoted":
        return
    present = set(store.read(DatasetId(config.data.bars), config.end_ns).collect_schema().names())
    missing = [c for c in BAR_QUOTE_SCHEMA if c not in present]
    if missing:
        msg = (
            f"execution.spread is 'quoted' but dataset {config.data.bars!r} has no {missing} "
            "columns. Rebuild it from a source that carries bid/ask (for example the Polymarket "
            "importers: `crucible data build examples/imports/polymarket_csv.yaml`) or choose "
            "another spread model. Null tests and transforms drop quote columns, so quoted "
            "spreads cannot run under them"
        )
        raise ConfigurationError(msg)


def _prepare_run(
    config: ExperimentConfig,
    runtime: Runtime,
    resume_from: Path | None,
    *,
    boundary: int | None = None,
) -> _Prepared:
    """Quality gate, dataset hashes, engine build and, when asked, the resume. Nothing here
    creates a directory: a refusal (a failed gate, a checkpoint from a different setup or data)
    must leave no artifacts behind (ADR-0051, ADR-0058)."""
    _check_runtime(config, runtime)
    # read first: a missing, corrupt or old-schema file is refused before the (slow) quality gate
    if boundary is None and resume_from is not None:
        boundary = _checkpoint_boundary(resume_from)
    store = ParquetDataStore(config.data.store)
    _require_quote_columns(config, store)
    calendar = get_trading_calendar(config.data.calendar, start=config.start_ns, end=config.end_ns)

    # Gate 1: quality checks block the run (R1.5); skips demand a reason.
    checks_ran = run_quality_checks(
        store.read(DatasetId(config.data.bars), config.end_ns),
        calendar,
        skip=frozenset(config.data.quality_skip),
        skip_reason=config.data.quality_skip_reason,
    )

    datasets = {"bars": config.data.bars}
    if config.data.corporate_actions:
        datasets["corporate_actions"] = config.data.corporate_actions
    if config.data.universe:
        datasets["universe"] = config.data.universe
    if config.data.fx_rates:
        datasets["fx_rates"] = config.data.fx_rates
    data_hashes = {
        role: store.manifest(DatasetId(name)).content_hash for role, name in datasets.items()
    }

    # built before any directory exists: a runtime's constructor refusals (for example
    # LiveRuntime at Level 0) must leave no artifacts behind (ADR-0051)
    engine = _build_engine(config, store, runtime)
    if resume_from is not None:
        engine.resume_from(resume_from)  # refuses a different setup or data
    return _Prepared(engine, checks_ran, data_hashes, boundary, _periods_per_year(config, store))


def _periods_per_year(config: ExperimentConfig, store: ParquetDataStore) -> float:
    """The annualization factor the metrics use.

    The config's own value when the author set it; otherwise derived from the bars' spacing and
    the calendar (252 sessions a year times the median bars per session; 365 for ``24/7``). The
    field's default is the *daily* 252, so an intraday config that never set it used to annualize
    a per-bar Sharpe by 1/sqrt(bars_per_session) too little -- hourly on XNYS: 0.81 instead of
    2.13 for the same series (2026-10 audit, M5). The derivation is one column scan, only when the
    field is untouched."""
    if "periods_per_year" in config.model_fields_set:
        return float(config.periods_per_year)
    stamps = (
        store.read(DatasetId(config.data.bars), config.end_ns)
        .select("event_time")
        .collect()
        .get_column("event_time")
        .to_list()
    )
    return periods_per_year_for(stamps, config.data.calendar)


def _check_periodic(
    config: ExperimentConfig, checkpoint_path: Path | None, every_ns: int | None
) -> None:
    if every_ns is None:
        if checkpoint_path is not None:
            msg = "checkpoint_path is only used with checkpoint_every_ns (or checkpoint_experiment)"
            raise ConfigurationError(msg)
        return
    if checkpoint_path is None:
        msg = "checkpoint_every_ns needs checkpoint_path, the file the run is saved to"
        raise ConfigurationError(msg)
    if every_ns <= 0:
        msg = f"checkpoint_every_ns must be positive, got {every_ns}"
        raise ConfigurationError(msg)
    span = int(config.end_ns) - int(config.start_ns)
    count = _periodic_count(int(config.start_ns), int(config.end_ns), every_ns)
    if count == 0:
        msg = (
            f"the checkpoint interval ({every_ns // 1_000_000_000} s) is longer than the run "
            f"({span // 1_000_000_000} s): no checkpoint would be written; use a shorter interval"
        )
        raise ConfigurationError(msg)
    if count > MAX_CHECKPOINTS:
        msg = (
            f"a checkpoint every {every_ns // 1_000_000_000} s over this run would write "
            f"up to {count:,} checkpoints (limit {MAX_CHECKPOINTS:,}); use a longer interval"
        )
        raise ConfigurationError(msg)
    _require_directory(checkpoint_path)


def _periodic_count(start: int, end: int, every_ns: int) -> int:
    """How many points ``start + k * every_ns`` (k >= 1) fall strictly before ``end``: the most
    checkpoints a periodic run can write (a point with no new event writes nothing)."""
    return max(0, (end - start - 1) // every_ns)


def _run_with_checkpoints(
    engine: BacktestEngine,
    config: ExperimentConfig,
    path: Path,
    every_ns: int,
    after: int | None,
) -> BacktestResult:
    """Runs to the end, atomically rewriting ``path`` at ``start + k * every_ns`` of simulated
    time for each k whose point lies before the end.

    A point at which the engine reached no new boundary writes nothing (a weekend over daily
    bars, a point at or before the boundary a resume started from), so the number of writes is
    bounded by the number of distinct boundaries, never repeated and never going backwards.
    ``run_until`` and ``checkpoint`` only read engine state, so the result equals a plain
    ``run()`` (ADR-0058)."""
    start, end = int(config.start_ns), int(config.end_ns)
    last = start if after is None else after  # the engine's clock before anything was run
    point = start + every_ns
    while point < end:
        engine.run_until(TimestampNs(point))
        now = int(engine.snapshot().ts)
        if now != last:
            engine.checkpoint(path)
            last = now
        point += every_ns
    return engine.run()


def checkpoint_experiment(
    config: ExperimentConfig,
    path: Path,
    *,
    stop_at: TimestampNs,
    runtime: Runtime = "backtest",
    resume_from: Path | None = None,
) -> CheckpointWritten:
    """Runs to the session boundary at or before ``stop_at``, writes the checkpoint and stops.

    Writes nothing else: no experiment directory, no report, no trial (a partial run is not a
    result, ADR-0058). Timing: the boundary is the engine's (after the last event of a timestamp
    was fully handled), so a ``stop_at`` between two bars holds the earlier one. ``resume_from``
    continues a saved run (chained stops). Every refusal happens before the engine runs.
    """
    start, end = int(config.start_ns), int(config.end_ns)
    if not start < int(stop_at) < end:
        msg = (
            f"stop_at {_utc_iso(int(stop_at))} must fall after the config start "
            f"({_utc_iso(start)}) and before its end ({_utc_iso(end)}); to run to the end, "
            "drop the stop"
        )
        raise ConfigurationError(msg)
    _require_directory(path)
    resumed = _checkpoint_boundary(resume_from) if resume_from is not None else None
    if resumed is not None and int(stop_at) <= resumed:
        held = _utc_iso(resumed)
        msg = (
            f"the checkpoint {resume_from} is already past {_utc_iso(int(stop_at))} "
            f"(it holds {held}); choose a later stop"
        )
        raise ConfigurationError(msg)
    prepared = _prepare_run(config, runtime, resume_from, boundary=resumed)
    prepared.engine.run_until(stop_at)
    prepared.engine.checkpoint(path)
    return CheckpointWritten(path=path, boundary_ts=prepared.engine.snapshot().ts)


def _run_experiment_compute(
    config: ExperimentConfig,
    artifacts_root: Path,
    runtime: Runtime = "backtest",
    *,
    resume_from: Path | None = None,
    checkpoint_path: Path | None = None,
    checkpoint_every_ns: int | None = None,
) -> _PendingRun:
    """The parallelizable half of ``run_experiment`` (ADR-0038): quality
    gate, engine simulation, metrics, Monte Carlo. Touches only the
    (read-only) data store and this run's own, uniquely-named artifact
    directory -- never the shared trial registry, so it is safe to call
    from multiple worker processes at once (``run_experiment_parallel``)."""
    _check_periodic(config, checkpoint_path, checkpoint_every_ns)
    # everything that can refuse (quality gate, runtime, engine construction, a resume) happens
    # before any directory exists: a refusal must leave no artifacts behind (ADR-0051, ADR-0058)
    prepared = _prepare_run(config, runtime, resume_from)
    checks_ran, data_hashes, engine = prepared.checks_ran, prepared.data_hashes, prepared.engine

    exp_id = experiment_id(config, data_hashes)
    out_dir = artifacts_root / exp_id
    family = config.experiment.family

    created = not out_dir.exists()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "logs").mkdir(exist_ok=True)
    try:
        if checkpoint_every_ns is not None and checkpoint_path is not None:
            result = _run_with_checkpoints(
                engine, config, checkpoint_path, checkpoint_every_ns, prepared.resumed_boundary
            )
        else:
            result = engine.run()
    except BaseException:
        if created:  # a run that fails midway leaves nothing behind (only an empty logs folder)
            shutil.rmtree(out_dir, ignore_errors=True)
        raise

    equity = pl.from_dicts(result.equity_rows, schema=EQUITY_SCHEMA)
    trades = build_trades(result.fill_rows)
    rng = np.random.default_rng(config.experiment.seed)
    metrics = compute_metrics(equity, trades, rng=rng, periods_per_year=prepared.periods_per_year)

    returns = simple_returns(equity)
    this_sharpe = None if is_degenerate_returns(returns) else per_period_sharpe(returns)

    # Monte Carlo (ADR-0017): reuses the same seeded rng
    # stream compute_metrics already advanced -- deterministic given the
    # run's seed, no separate generator needed. No trial-registry
    # dependency, so this stays in the parallelizable half.
    returns_list = returns.tolist()
    monte_carlo = {
        test.name: test.run(returns_list, rng, N_MONTE_CARLO_ITERATIONS)
        for test in (ReturnOrderShuffleTest(), StartDateShiftTest(), BlockBootstrapTest())
    }

    commit, dirty = _git_provenance()
    return _PendingRun(
        config=config,
        artifacts_root=artifacts_root,
        checks_ran=checks_ran,
        data_hashes=data_hashes,
        exp_id=exp_id,
        out_dir=out_dir,
        family=family,
        result=result,
        equity=equity,
        trades=trades,
        metrics=metrics,
        returns=returns,
        this_sharpe=this_sharpe,
        monte_carlo=monte_carlo,
        commit=commit,
        dirty=dirty,
        code_fingerprint=_code_fingerprint(),
        runtime=runtime,
    )


def _finalize_experiment(
    pending: _PendingRun, *, record_trial: bool, overwrite: bool = False
) -> RunArtifacts:
    """The trial-registry-touching half of ``run_experiment`` (ADR-0038).
    DuckDB supports only one process holding a database file at a time
    (fails fast with a locking error otherwise) -- ``run_experiment_parallel``
    calls this serially, in the parent process, in a fixed order, so a
    parallel sweep's trial registrations and each trial's own (necessarily
    order-dependent, ADR-0023) provisional DSR are byte-identical to
    running the same configs through ``run_experiment`` sequentially (E1)."""
    if pending.runtime != "backtest":
        record_trial = False  # a re-run of the same parameters, like scenario fan-out (ADR-0014)
    config = pending.config
    exp_id = pending.exp_id
    out_dir = pending.out_dir
    family = pending.family
    end = config.end_ns
    result = pending.result
    equity = pending.equity
    trades = pending.trades
    metrics = pending.metrics
    returns = pending.returns
    data_hashes = pending.data_hashes
    checks_ran = pending.checks_ran
    monte_carlo = pending.monte_carlo
    commit, dirty = pending.commit, pending.dirty

    # before the trial registry and before any file: a refused overwrite must write nothing
    _refuse_overwrite(
        out_dir,
        commit=commit,
        dirty=dirty,
        fingerprint=pending.code_fingerprint,
        overwrite=overwrite,
    )

    # Trial registry + DSR (ADR-0008/0014/0015). This trial's own per-period
    # Sharpe must be recorded before trial_sharpes() is read, so its own
    # dispersion contributes to the benchmark it is then measured against.
    trial_registry = DuckDBTrialRegistry(pending.artifacts_root / "trial_registry.duckdb")
    trial_count = (
        trial_registry.record_trial(
            family,
            str(exp_id),
            sharpe=pending.this_sharpe,
            mode=config.experiment.mode.value,
            start_ns=int(config.start_ns),
            end_ns=int(end),
            period_ns=median_period_ns(equity.get_column("ts").to_list()),
        )
        if record_trial
        else trial_registry.trial_count(family)
    )
    dsr_result: DsrResult | None = None
    dsr_error = frequency_mismatch(trial_registry.trial_periods(family))
    if dsr_error is None:
        try:
            dsr_result = deflated_sharpe_ratio(
                returns,
                trial_registry.trial_sharpes(family),
                n_trials=trial_registry.trial_count(family),
            )
        except CrucibleError as exc:
            dsr_error = str(exc)

    # Contamination flagging (ADR-0021): only meaningful
    # for an evaluation-mode run, and only against trials that were
    # themselves recorded (record_trial=True) with a mode/window -- a run
    # with record_trial=False never inserted its own window either, so it
    # naturally can't spuriously flag or be flagged.
    contamination = check_contamination(
        family, config.experiment.mode, config.start_ns, end, trial_registry
    )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": str(exp_id),
        "config_hash": config_hash(config),
        "crucible_version": crucible_version,
        "commit": commit,
        "dirty": dirty,
        "code_fingerprint": pending.code_fingerprint,
        "data_manifests": data_hashes,
        # the bars' declared price basis (ADR-0071): adjusted prices are a research series, not
        # the quotes that traded; "undeclared" for a dataset that does not say
        "bars_price_basis": price_basis_of(
            ParquetDataStore(config.data.store).manifest(DatasetId(config.data.bars))
        )
        or "undeclared",
        "seed": config.experiment.seed,
        "realism_level": config.experiment.realism_level.name,
        "runtime": pending.runtime,
        "mode": config.experiment.mode.value,
        "trial_family": family,
        "trial_count": trial_count,
        "dsr": dsr_result.dsr if dsr_result is not None else None,
        "dsr_benchmark_sharpe": dsr_result.benchmark_sharpe if dsr_result is not None else None,
        "dsr_error": dsr_error,
        "dsr_n_trials_with_sharpe": (
            dsr_result.n_trials_with_sharpe if dsr_result is not None else None
        ),
        "pbo": None,  # PBO needs a multi-trial panel; not computable for one run (ADR-0015)
        "monte_carlo": monte_carlo,
        "contamination": contamination.contaminated,
        "contamination_reason": contamination.reason,
        "contamination_overlapping_trials": list(contamination.overlapping_trials),
        "quality_checks_ran": checks_ran,
        "quality_checks_skipped": sorted(config.data.quality_skip),
        "quality_skip_reason": config.data.quality_skip_reason,
        "env_lock_hash": _env_lock_hash(),
    }

    # newline="\n" everywhere: platform newline translation would silently
    # change artifact bytes between Windows and Linux (ADR-0011)
    (out_dir / "config.yaml").write_text(canonical_yaml(config), encoding="utf-8", newline="\n")
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_parquet(equity, out_dir / "equity.parquet")
    _write_parquet(trades, out_dir / "trades.parquet")
    _write_parquet(
        pl.from_dicts(
            result.ledger_rows,
            schema=LEDGER_SCHEMA,
        )
        if result.ledger_rows
        else pl.DataFrame(),
        out_dir / "ledger.parquet",
    )
    _write_parquet(
        pl.from_dicts(
            result.order_rows,
            schema=ORDER_SCHEMA,
        )
        if result.order_rows
        else pl.DataFrame(),
        out_dir / "orders.parquet",
    )
    _write_parquet(
        pl.from_dicts(
            result.fill_rows,
            schema=FILL_SCHEMA,
        )
        if result.fill_rows
        else pl.DataFrame(),
        out_dir / "fills.parquet",
    )
    metrics_payload = {
        name: {"value": m.value, "ci_low": m.ci_low, "ci_high": m.ci_high}
        for name, m in sorted(metrics.items())
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics_payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    result.log.write(out_dir / "logs" / "run.jsonl")

    plot_equity_drawdown(equity, out_dir / "equity.svg")
    header = {
        "experiment_id": str(exp_id),
        "commit": commit,
        "dirty": str(dirty),
        "data_manifests": ", ".join(f"{k}:{v[:12]}" for k, v in sorted(data_hashes.items())),
        "seed": str(config.experiment.seed),
        "realism_level": config.experiment.realism_level.name,
        "runtime": pending.runtime,
        "mode": config.experiment.mode.value,
        "trial_family": family,
        "trial_count": str(trial_count),
        "contamination_flags": (
            f"CONTAMINATED: {contamination.reason}"
            if contamination.contaminated
            else contamination.reason
        ),
    }
    if dsr_result is not None:
        dsr_text = (
            f"{dsr_result.dsr:.4f} (benchmark_sharpe={dsr_result.benchmark_sharpe:.4f}, "
            f"n_trials={dsr_result.n_trials})"
        )
    else:
        dsr_text = f"not computable: {dsr_error}"
    validation_summary = {
        "dsr": dsr_text,
        "pbo": (
            "not computed for a single run (needs a multi-trial panel over the same "
            "periods; run `crucible optimize` to assemble one)"
        ),
    }
    report_path = render_report(
        header,
        metrics,
        equity,
        trades,
        out_dir,
        validation_summary=validation_summary,
        monte_carlo=monte_carlo,
    )
    return RunArtifacts(
        experiment_id=exp_id, path=out_dir, metrics=metrics, report_path=report_path
    )


def run_experiment(
    config: ExperimentConfig,
    artifacts_root: Path,
    *,
    record_trial: bool = True,
    runtime: Runtime = "backtest",
    resume_from: Path | None = None,
    checkpoint_path: Path | None = None,
    checkpoint_every_ns: int | None = None,
    overwrite: bool = False,
) -> RunArtifacts:
    """``runtime`` picks how the engine is built (backtest, paper, live) and must
    agree with ``live.enabled`` (ADR-0051); paper and live runs never record a
    trial. ``record_trial=False`` reports the family's current trial count
    without incrementing it — used by scenario fan-out (see
    ``run_with_scenarios``), whose optimistic/conservative/extreme variants
    are cost-sensitivity re-examinations of the base run's one trial, not
    separate parameter evaluations (ADR-0014).

    ``resume_from`` continues a saved run: it restores the checkpoint into the fresh engine
    and finishes through this same pipeline, so it records one trial like any run and writes
    artifacts byte-identical to an uninterrupted run's (I13). ``checkpoint_path`` with
    ``checkpoint_every_ns`` atomically rewrites that file every interval of *simulated* time
    while running, without changing results (ADR-0058); ``checkpoint_experiment`` stops a run
    instead.

    Two-phase internally (ADR-0038): ``_run_experiment_compute`` (quality
    gate, engine, metrics, Monte Carlo) then ``_finalize_experiment``
    (trial registry, DSR, contamination, artifact writing). A single
    sequential run has no reason to care about the split; it exists so
    ``run_experiment_parallel`` can run the first phase across worker
    processes while keeping the registry-touching second phase serial.
    """
    pending = _run_experiment_compute(
        config,
        artifacts_root,
        runtime,
        resume_from=resume_from,
        checkpoint_path=checkpoint_path,
        checkpoint_every_ns=checkpoint_every_ns,
    )
    return _finalize_experiment(pending, record_trial=record_trial, overwrite=overwrite)


def run_experiment_parallel(
    configs: Sequence[ExperimentConfig],
    artifacts_root: Path,
    *,
    max_workers: int | None = None,
    record_trial: bool = True,
    overwrite: bool = False,
) -> list[RunArtifacts]:
    """Runs every config's expensive simulation+metrics phase
    (``_run_experiment_compute``) in a process pool, then records trials
    and writes artifacts (``_finalize_experiment``) serially, in the
    parent, **in ``configs`` order** — not completion order (ADR-0038).

    This is what actually matters for determinism (E1): DuckDB allows only
    one process to hold ``trial_registry.duckdb`` at a time (it fails fast
    with a locking error otherwise, not a silent corruption, but still
    unusable from concurrent workers), and even a lock-protected registry
    write would let *wall-clock scheduling* decide which trial gets
    registered first — making a downstream Sharpe-dispersion consumer
    like DSR's benchmark order-dependent, and therefore non-reproducible
    run to run. Recording strictly in ``configs`` order in a single
    process reproduces exactly what calling ``run_experiment`` in a loop
    over ``configs`` would do, byte for byte — only the simulation itself
    runs concurrently.

    ``max_workers=None`` uses ``ProcessPoolExecutor``'s own default (the
    machine's CPU count). Each worker is a fresh process: strategy/signal
    entrypoints are re-imported there, exactly as a fresh ``crucible run``
    invocation would.
    """
    # spawn on every OS: the Linux default (fork) deadlocked a multithreaded parent (ADR-0055)
    with ProcessPoolExecutor(
        max_workers=max_workers, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        pending_runs = list(
            pool.map(_run_experiment_compute, configs, [artifacts_root] * len(configs))
        )
    return [
        _finalize_experiment(pending, record_trial=record_trial, overwrite=overwrite)
        for pending in pending_runs
    ]


# ------------------------------------------------------- scenario fan-out


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    scenario: str
    artifacts: RunArtifacts


def _derived_scenario_config(config: ExperimentConfig, scenario: str) -> ExperimentConfig:
    """The base config with one scenario's execution overrides applied and
    the scenario table cleared. Re-validated from scratch so every config
    rule still holds; a different config ⇒ a different experiment id."""
    override = config.execution.scenarios[scenario]
    execution = config.execution.model_dump(mode="python")
    execution["scenarios"] = {}
    for slot in ("spread", "latency", "slippage", "commission", "participation"):
        value = getattr(override, slot)
        if value is not None:
            execution[slot] = value.model_dump(mode="python")
            if slot == "slippage":
                execution["slippage_bps"] = 0.0
            if slot == "commission":
                execution["commission_bps"] = 0.0
    dumped = config.model_dump(mode="python")
    dumped["execution"] = execution
    return ExperimentConfig.model_validate(dumped)


def run_with_scenarios(config: ExperimentConfig, artifacts_root: Path) -> list[ScenarioOutcome]:
    """Runs the base config plus every configured scenario (R3.10) and writes
    the decay report into the base run's artifact directory. Only the base
    run counts as a trial (ADR-0014): the scenario variants re-examine the
    same parameter evaluation under different execution assumptions, not a
    parameter search, so counting them separately would inflate DSR
    deflation for zero additional search risk."""
    # derive and pre-check every scenario first: a scenario that cannot run (a quoted spread on a
    # store without quotes) must not leave a recorded base run behind
    derived_configs = {
        scenario: _derived_scenario_config(config, scenario)
        for scenario in sorted(config.execution.scenarios)
    }
    for derived in derived_configs.values():
        _require_quote_columns(derived, ParquetDataStore(derived.data.store))
    outcomes = [ScenarioOutcome("base", run_experiment(config, artifacts_root))]
    for scenario, derived in derived_configs.items():
        outcomes.append(
            ScenarioOutcome(scenario, run_experiment(derived, artifacts_root, record_trial=False))
        )
    _write_scenario_decay(outcomes)
    return outcomes


_DECAY_METRICS = ("sharpe", "cagr", "max_drawdown", "volatility", "n_trades")


def _write_scenario_decay(outcomes: Sequence[ScenarioOutcome]) -> None:
    base_dir = outcomes[0].artifacts.path
    payload = {
        outcome.scenario: {
            "experiment_id": str(outcome.artifacts.experiment_id),
            "metrics": {
                name: {
                    "value": outcome.artifacts.metrics[name].value,
                    "ci_low": outcome.artifacts.metrics[name].ci_low,
                    "ci_high": outcome.artifacts.metrics[name].ci_high,
                }
                for name in _DECAY_METRICS
                if name in outcome.artifacts.metrics
            },
        }
        for outcome in outcomes
    }
    (base_dir / "scenario_decay.json").write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    header_cells = "".join(f"<th>{name}</th>" for name in _DECAY_METRICS)
    rows = []
    for outcome in outcomes:
        cells = []
        for name in _DECAY_METRICS:
            metric = outcome.artifacts.metrics.get(name)
            cells.append(f"<td>{metric.value:.4g}</td>" if metric else "<td>—</td>")
        rows.append(
            f"<tr><td>{outcome.scenario}</td><td>{outcome.artifacts.experiment_id}</td>"
            + "".join(cells)
            + "</tr>"
        )
    html = (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        "<title>Scenario decay</title><style>table{border-collapse:collapse}"
        "th,td{border:1px solid #ccc;padding:0.3rem 0.7rem}</style></head><body>"
        "<h1>Execution scenario decay</h1>"
        "<p>Same strategy, same data, same seed — only execution assumptions "
        "change. If the edge decays fast down this table, the edge is the "
        "execution model, not the strategy.</p>"
        f"<table><tr><th>scenario</th><th>experiment</th>{header_cells}</tr>"
        + "".join(rows)
        + "</table></body></html>\n"
    )
    (base_dir / "scenario_decay.html").write_text(html, encoding="utf-8", newline="\n")


# --------------------------------------------------------------- rebuild


def rebuild_report(out_dir: Path, *, factor_regression: Mapping[str, object] | None = None) -> Path:
    """Re-renders ``report.html`` from a finished run's on-disk artifacts
    (``manifest.json``, ``metrics.json``, equity/trades Parquet).
    ``factor_regression``, if given, is merged into ``manifest.json``
    before rendering (ADR-0022) -- a run has no factor data of its own;
    only the ``crucible validate --factors`` path supplies one. Shared by
    the ``crucible report`` CLI command and
    ``experiments.validate.validate_run`` so re-rendering never drifts
    between the two callers."""
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.is_file():
        msg = f"no run found at {out_dir}: missing manifest.json"
        raise ExperimentError(msg)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if factor_regression is not None:
        manifest["factor_regression"] = dict(factor_regression)
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    metrics_raw = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
    metrics = {
        name: MetricValue(entry["value"], entry["ci_low"], entry["ci_high"])
        for name, entry in metrics_raw.items()
    }
    equity = pl.read_parquet(out_dir / "equity.parquet")
    trades = pl.read_parquet(out_dir / "trades.parquet")

    if manifest.get("contamination_reason") is not None:
        contamination_flags = (
            f"CONTAMINATED: {manifest['contamination_reason']}"
            if manifest.get("contamination")
            else manifest["contamination_reason"]
        )
    else:
        contamination_flags = "not tracked (run predates ADR-0021)"

    header = {
        "experiment_id": manifest["experiment_id"],
        "commit": manifest["commit"],
        "dirty": str(manifest["dirty"]),
        "data_manifests": ", ".join(
            f"{k}:{v[:12]}" for k, v in sorted(manifest["data_manifests"].items())
        ),
        "seed": str(manifest["seed"]),
        "realism_level": manifest["realism_level"],
        "runtime": str(manifest.get("runtime", "backtest")),
        "mode": manifest["mode"],
        "trial_family": manifest["trial_family"],
        "trial_count": str(manifest["trial_count"]),
        "contamination_flags": contamination_flags,
    }
    if manifest.get("dsr") is not None:
        dsr_text = (
            f"{manifest['dsr']:.4f} "
            f"(benchmark_sharpe={manifest.get('dsr_benchmark_sharpe', 0.0):.4f}, "
            f"n_trials={manifest['trial_count']})"
        )
    else:
        dsr_text = f"not computable: {manifest.get('dsr_error', 'unknown (older run)')}"
    validation_summary = {
        "dsr": dsr_text,
        "pbo": (
            "not computed for a single run (needs a multi-trial panel over the same "
            "periods; run `crucible optimize` to assemble one)"
        ),
    }
    plot_equity_drawdown(equity, out_dir / "equity.svg")
    return render_report(
        header,
        metrics,
        equity,
        trades,
        out_dir,
        validation_summary=validation_summary,
        monte_carlo=manifest.get("monte_carlo"),
        factor_regression=manifest.get("factor_regression"),
        trades_label=EPISODE_LABEL if manifest.get("vectorized") else "round trips",
    )
