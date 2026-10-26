"""Config-driven vectorized runs (ADR-0035).

Translates an ``ExperimentConfig`` into a ``VectorizedConfig`` and runs it,
producing a smaller artifact set than the event-driven ``run_experiment``'s
(a position-episode log instead of a fill-level trade log, ADR-0061; no PBO/
Monte Carlo -- documented known gaps, see ``docs/modules/vectorized.md``). A
vectorized run is a trial in the shared registry with DSR and contamination
like an event-driven run (ADR-0061).

Every ``ExperimentConfig`` field the vectorized engine has no way to honor
is refused here, not silently dropped (AGENTS.md §5): risk limits,
multi-currency, futures, corporate actions, universe membership,
settlement lag, borrow/financing rates, any Level 2+ execution model slot,
and scenario fan-out. ``VectorizedConfig`` simply has no field for most of
these, so silently ignoring a populated one would compute a materially
different result than the config asked for -- most sharply for
``corporate_actions``: bars are raw, unadjusted prices (AGENTS.md §9), and
the event-driven engine's dividend postings are the *only* thing that
turns a raw close-to-close return into a correct total return. Without
that, a vectorized run over dividend-paying data would silently understate
returns with no error to show for it.
"""

from __future__ import annotations

import inspect
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
import polars as pl

from crucible import __version__ as crucible_version
from crucible.analytics.metrics import compute_metrics, simple_returns
from crucible.analytics.plots import plot_equity_drawdown
from crucible.analytics.report import render_report
from crucible.analytics.trades import EPISODE_LABEL, build_episodes
from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.core.stats import is_degenerate_returns, per_period_sharpe
from crucible.core.types import DatasetId, ExperimentId, RealismLevel
from crucible.data.calendars import periods_per_year_for
from crucible.data.store import ParquetDataStore, price_basis_of
from crucible.experiments.artifacts import SCHEMA_VERSION
from crucible.experiments.config import ExperimentConfig, canonical_yaml, config_hash
from crucible.experiments.runner import (
    _code_fingerprint,
    _env_lock_hash,
    _git_provenance,
    _refuse_overwrite,
    _write_parquet,
    experiment_id,
    import_entrypoint,
)
from crucible.validation.contamination import check_contamination
from crucible.validation.dsr import DsrResult, deflated_sharpe_ratio
from crucible.validation.trial_registry import (
    DuckDBTrialRegistry,
    frequency_mismatch,
    median_period_ns,
)
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig, VectorizedResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

    from crucible.analytics.interfaces import MetricValue
    from crucible.vectorized.interfaces import SignalFunction


@dataclass(frozen=True, slots=True)
class VectorizedRunArtifacts:
    experiment_id: ExperimentId
    path: Path
    metrics: dict[str, MetricValue]
    report_path: Path


def _refuse_out_of_scope(config: ExperimentConfig) -> None:
    """Raises on the first field the vectorized path cannot honor. One
    check at a time (not a batch of every violation) matches every other
    refusal site in this codebase (e.g. ``BacktestEngine.__init__``)."""
    if config.live is not None:
        msg = (
            "live is set, but the vectorized engine has no live runtime; use "
            "crucible.live.runtime.LiveRuntime with the event-driven engine."
        )
        raise ConfigurationError(msg)
    execution = config.execution
    if config.data.corporate_actions is not None:
        msg = (
            f"data.corporate_actions={config.data.corporate_actions!r} is set, but the "
            "vectorized engine applies no corporate actions at all (bars are raw, unadjusted "
            "prices -- AGENTS.md §9); a dividend-paying dataset would silently understate "
            "returns. Use the event-driven engine (BacktestEngine) for this config."
        )
        raise ConfigurationError(msg)
    if config.data.universe is not None:
        msg = (
            f"data.universe={config.data.universe!r} is set, but the vectorized engine applies "
            "no universe(t)/delisting handling; use the event-driven engine for this config."
        )
        raise ConfigurationError(msg)
    foreign = sorted(
        {c for c in config.data.symbol_currency.values() if c != config.data.base_currency}
    )
    if foreign and config.data.fx_rates is None:
        msg = (
            f"data.symbol_currency names {foreign} (base {config.data.base_currency}) but "
            "data.fx_rates is not set: the vectorized FX path needs a rate dataset with a "
            "<CCY><BASE> pair per foreign currency (ADR-0062)"
        )
        raise ConfigurationError(msg)
    # futures_multipliers are accepted (ADR-0065): a vectorized position is a fraction of equity,
    # so a multiplier cancels in the return and the bars are taken as a continuous series
    if config.data.futures_margins:
        msg = (
            f"data.futures_margins={sorted(config.data.futures_margins)!r} is set, but the "
            "vectorized engine does not model margin (no requirement, no margin call, no "
            "financing); remove the margins to run vectorized, or use the event-driven engine."
        )
        raise ConfigurationError(msg)
    if config.risk is not None:
        msg = "risk is set, but the vectorized engine has no risk engine; use BacktestEngine."
        raise ConfigurationError(msg)
    if config.settlement_lag_days:
        msg = (
            f"settlement_lag_days={config.settlement_lag_days} is set, but the vectorized "
            "engine has no cash/settlement model at all; use the event-driven engine."
        )
        raise ConfigurationError(msg)
    if config.short_borrow_rate or config.margin_financing_rate:
        msg = (
            f"short_borrow_rate={config.short_borrow_rate}/"
            f"margin_financing_rate={config.margin_financing_rate} set, but the vectorized "
            "engine has no borrow/financing accrual; use the event-driven engine."
        )
        raise ConfigurationError(msg)
    if execution.scenarios:
        msg = (
            "execution.scenarios is set, but scenario fan-out is an event-driven-only "
            "feature (R3.10); run the base config through the vectorized engine directly."
        )
        raise ConfigurationError(msg)
    for slot_name, slot_value in (
        ("spread", execution.spread),
        ("latency", execution.latency),
        ("slippage", execution.slippage),
        ("commission", execution.commission),
        ("participation", execution.participation),
    ):
        if slot_value is not None:
            msg = (
                f"execution.{slot_name}={slot_value!r} is a Level 2+ model, but the vectorized "
                f"engine only supports the Level 0/1 slippage_bps/commission_bps shorthand; "
                "use the event-driven engine for Level 2+ execution realism."
            )
            raise ConfigurationError(msg)
    if config.experiment.realism_level not in (
        RealismLevel.FRICTIONLESS,
        RealismLevel.BASIC_FRICTION,
    ):
        msg = (
            f"experiment.realism_level={config.experiment.realism_level.name} is not "
            "FRICTIONLESS or BASIC_FRICTION; the vectorized engine supports Level 0/1 only "
            " -- use the event-driven engine for Level 2+."
        )
        raise ConfigurationError(msg)


def assemble_vectorized_engine(
    config: ExperimentConfig, *, store: ParquetDataStore | None = None
) -> tuple[VectorizedBacktestEngine, VectorizedConfig]:
    """Builds a ready-to-run vectorized engine + its config from a validated
    ``ExperimentConfig``, refusing anything out of the vectorized path's
    documented scope. Mirrors ``runner.assemble_engine``'s role for the
    event-driven path."""
    _refuse_out_of_scope(config)
    store = store if store is not None else ParquetDataStore(config.data.store)
    entrypoint = import_entrypoint(config.strategy.entrypoint)
    if inspect.isclass(entrypoint) or not callable(entrypoint):
        msg = (
            f"strategy.entrypoint {config.strategy.entrypoint!r} is not a signal function: the "
            "vectorized engine needs a function (bars, params) -> frame keyed (ts, symbol) with a "
            "score column (crucible/vectorized/interfaces.py). An event-driven strategy class "
            "belongs in `crucible run`; for this config use the event-driven engine, or point "
            "the entrypoint at a signal function"
        )
        raise ConfigurationError(msg)
    signal = cast("SignalFunction", entrypoint)
    vec_config = VectorizedConfig(
        store=store,
        bars_dataset=DatasetId(config.data.bars),
        signal=signal,
        params=config.strategy.params,
        initial_cash=config.initial_cash,
        realism_level=config.experiment.realism_level,
        start=config.start_ns,
        end=config.end_ns,
        slippage_bps=config.execution.slippage_bps,
        commission_bps=config.execution.commission_bps,
        base_currency=config.data.base_currency,
        symbol_currency=dict(config.data.symbol_currency),
        fx_dataset=DatasetId(config.data.fx_rates) if config.data.fx_rates else None,
    )
    return VectorizedBacktestEngine(), vec_config


@dataclass(frozen=True, slots=True)
class _PendingVectorizedRun:
    """Everything a vectorized run needs *before* it touches the shared trial registry
    (ADR-0038, ADR-0061): the simulation, the episode log and the metrics are pure functions of
    the config and the read-only store, so a worker process can compute them while the
    registry-touching half runs serially in the parent."""

    config: ExperimentConfig
    artifacts_root: Path
    data_hashes: dict[str, str]
    exp_id: ExperimentId
    out_dir: Path
    result: VectorizedResult
    episodes: pl.DataFrame
    metrics: dict[str, MetricValue]
    returns: NDArray[np.float64]
    this_sharpe: float | None
    commit: str
    dirty: bool
    code_fingerprint: str


def _periods_per_year(config: ExperimentConfig, store: ParquetDataStore) -> float:
    """The config's value when the author set it, else the bars' own factor (252 sessions x
    median bars per session; 365 for ``24/7``). The default 252 is a daily factor: an intraday
    config that left it untouched annualized by 1/sqrt(bars_per_session) too little (M5)."""
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


def _run_vectorized_compute(
    config: ExperimentConfig, artifacts_root: Path
) -> _PendingVectorizedRun:
    """The parallelizable half: refuses out-of-scope configs, runs the engine, builds the episode
    log and the metrics. Touches no shared state (module level so a spawn pool can pickle it)."""
    store = ParquetDataStore(config.data.store)
    engine, vec_config = assemble_vectorized_engine(config, store=store)

    data_hashes = {"bars": store.manifest(DatasetId(config.data.bars)).content_hash}
    if config.data.fx_rates:
        data_hashes["fx_rates"] = store.manifest(DatasetId(config.data.fx_rates)).content_hash
    exp_id = experiment_id(config, data_hashes)
    out_dir = artifacts_root / exp_id

    result = engine.run(vec_config)
    values = result.equity.get_column("equity").to_numpy()
    if not np.isfinite(values).all():
        msg = (
            f"the vectorized run {exp_id} produced non-finite equity (a NaN or infinite score, "
            "weight or return, for example a z-score over a zero rolling std): it is refused "
            "before any artifact is written or trial recorded, because a NaN Sharpe in the shared "
            "trial registry would make every later DSR in the family NaN. Fix the signal "
            "function so it returns finite scores"
        )
        raise CrucibleError(msg)
    episodes = build_episodes(result.weights, result.pnl)
    rng = np.random.default_rng(config.experiment.seed)
    metrics = compute_metrics(
        result.equity,
        episodes,
        rng=rng,
        periods_per_year=_periods_per_year(config, store),
    )
    returns = simple_returns(result.equity)
    commit, dirty = _git_provenance()
    return _PendingVectorizedRun(
        config=config,
        artifacts_root=artifacts_root,
        data_hashes=data_hashes,
        exp_id=exp_id,
        out_dir=out_dir,
        result=result,
        episodes=episodes,
        metrics=metrics,
        returns=returns,
        this_sharpe=None if is_degenerate_returns(returns) else per_period_sharpe(returns),
        commit=commit,
        dirty=dirty,
        code_fingerprint=_code_fingerprint(),
    )


def _finalize_vectorized(
    pending: _PendingVectorizedRun, *, record_trial: bool, overwrite: bool = False
) -> VectorizedRunArtifacts:
    """The trial-registry-touching half (ADR-0038): records the trial, computes DSR and
    contamination exactly as ``runner._finalize_experiment`` does, writes the artifacts."""
    config = pending.config
    exp_id = pending.exp_id
    out_dir = pending.out_dir
    result = pending.result
    metrics = pending.metrics
    data_hashes = pending.data_hashes
    commit, dirty = pending.commit, pending.dirty
    family = config.experiment.family
    # before the trial registry and before any file: a refused overwrite writes nothing (ADR-0079)
    _refuse_overwrite(
        out_dir,
        commit=commit,
        dirty=dirty,
        fingerprint=pending.code_fingerprint,
        overwrite=overwrite,
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    # this trial's own per-period Sharpe is recorded before trial_sharpes() is read, so its own
    # dispersion contributes to the benchmark it is measured against (ADR-0008/0014/0015/0023)
    trial_registry = DuckDBTrialRegistry(pending.artifacts_root / "trial_registry.duckdb")
    trial_count = (
        trial_registry.record_trial(
            family,
            str(exp_id),
            sharpe=pending.this_sharpe,
            mode=config.experiment.mode.value,
            start_ns=int(config.start_ns),
            end_ns=int(config.end_ns),
            period_ns=median_period_ns(pending.result.equity.get_column("ts").to_list()),
        )
        if record_trial
        else trial_registry.trial_count(family)
    )
    dsr_result: DsrResult | None = None
    dsr_error = frequency_mismatch(trial_registry.trial_periods(family))
    if dsr_error is None:
        try:
            dsr_result = deflated_sharpe_ratio(
                pending.returns,
                trial_registry.trial_sharpes(family),
                n_trials=trial_registry.trial_count(family),
            )
        except CrucibleError as exc:
            dsr_error = str(exc)
    contamination = check_contamination(
        family, config.experiment.mode, config.start_ns, config.end_ns, trial_registry
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
        "mode": config.experiment.mode.value,
        "trial_family": family,
        "vectorized": True,
        "trial_count": trial_count,
        "dsr": dsr_result.dsr if dsr_result is not None else None,
        "dsr_benchmark_sharpe": dsr_result.benchmark_sharpe if dsr_result is not None else None,
        "dsr_error": dsr_error,
        "dsr_n_trials_with_sharpe": (
            dsr_result.n_trials_with_sharpe if dsr_result is not None else None
        ),
        "pbo": None,
        "monte_carlo": None,
        "contamination": contamination.contaminated,
        "contamination_reason": contamination.reason,
        "contamination_overlapping_trials": list(contamination.overlapping_trials),
        "env_lock_hash": _env_lock_hash(),
    }
    (out_dir / "config.yaml").write_text(canonical_yaml(config), encoding="utf-8", newline="\n")
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    _write_parquet(result.equity, out_dir / "equity.parquet")
    _write_parquet(result.weights, out_dir / "weights.parquet")
    _write_parquet(result.scores, out_dir / "scores.parquet")
    _write_parquet(pending.episodes, out_dir / "trades.parquet")
    metrics_payload = {
        name: {"value": m.value, "ci_low": m.ci_low, "ci_high": m.ci_high}
        for name, m in sorted(metrics.items())
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics_payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    plot_equity_drawdown(result.equity, out_dir / "equity.svg")

    header = {
        "experiment_id": str(exp_id),
        "commit": commit,
        "dirty": str(dirty),
        "data_manifests": ", ".join(f"{k}:{v[:12]}" for k, v in sorted(data_hashes.items())),
        "seed": str(config.experiment.seed),
        "realism_level": config.experiment.realism_level.name,
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
            "not computed for a single run (a sweep through `crucible optimize --vectorized` "
            "reports it, ADR-0015)"
        ),
    }
    report_path = render_report(
        header,
        metrics,
        result.equity,
        pending.episodes,
        out_dir,
        validation_summary=validation_summary,
        trades_label=EPISODE_LABEL,
    )
    return VectorizedRunArtifacts(
        experiment_id=exp_id, path=out_dir, metrics=metrics, report_path=report_path
    )


def run_vectorized_experiment(
    config: ExperimentConfig,
    artifacts_root: Path,
    *,
    record_trial: bool = True,
    overwrite: bool = False,
) -> VectorizedRunArtifacts:
    """Runs a vectorized backtest end-to-end and writes artifacts under
    ``<artifacts_root>/<EXP-ID>/``: ``config.yaml``, ``manifest.json``, ``equity.parquet``
    (``ts``/``equity`` only), ``weights.parquet``/``scores.parquet`` (vectorized-specific),
    ``trades.parquet`` (closed position episodes, ADR-0061 -- not fill-level round trips),
    ``metrics.json``, ``equity.svg``, ``report.html``.

    The run is a trial in ``<artifacts_root>/trial_registry.duckdb`` (same family and rules as an
    event-driven run, ADR-0014); ``record_trial=False`` reports the family's current count
    instead. DSR and contamination are computed like the event-driven path; PBO and Monte Carlo
    stay unreported for a single vectorized run (``None`` in the manifest, stated in the report).
    """
    return _finalize_vectorized(
        _run_vectorized_compute(config, artifacts_root),
        record_trial=record_trial,
        overwrite=overwrite,
    )


def run_vectorized_experiment_parallel(
    configs: Sequence[ExperimentConfig],
    artifacts_root: Path,
    *,
    max_workers: int | None = None,
    record_trial: bool = True,
    overwrite: bool = False,
) -> list[VectorizedRunArtifacts]:
    """The vectorized twin of ``runner.run_experiment_parallel`` (ADR-0038, ADR-0061).

    Every config is checked first (a refusal leaves no artifact and no trial), the simulations run
    in a spawn pool (the Linux fork default deadlocked a multithreaded parent, ADR-0055), and trials
    are recorded and artifacts written serially in the parent, **in ``configs`` order** -- not
    completion order -- so the result equals a sequential loop of ``run_vectorized_experiment``
    byte for byte, including each trial's order-dependent provisional DSR (E1).
    ``max_workers=None`` uses the pool's default (the machine's CPU count).
    """
    for config in configs:
        assemble_vectorized_engine(config)  # refuses an out-of-scope config before any work
    with ProcessPoolExecutor(
        max_workers=max_workers, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        pending = list(pool.map(_run_vectorized_compute, configs, [artifacts_root] * len(configs)))
    return [
        _finalize_vectorized(item, record_trial=record_trial, overwrite=overwrite)
        for item in pending
    ]
