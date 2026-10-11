"""Run-artifact schemas, the artifact schema version, and a reader for past runs.

The column and key definitions here are the single source of truth for what the
runner writes: ``experiments/runner.py`` builds its frames from these schemas and
``docs/SCHEMAS.md`` is generated from them (``tools/docgen.py``), so the docs cannot
drift from the code. Compatibility rules: ``docs/COMPATIBILITY.md`` §3.

Timing: every timestamp column is UTC int64 nanoseconds of *simulation* time
(``ts`` is the engine timestamp of the row, i.e. when it became knowable).
Units and signs: ``docs/CONVENTIONS.md``.

Reading is read-only and never re-simulates: :func:`load_experiment` returns what is on
disk, and refuses a run written by a newer schema than this code understands.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import polars as pl
import yaml

from crucible.analytics.interfaces import MetricValue
from crucible.core.errors import ExperimentError
from crucible.core.types import ExperimentId
from crucible.experiments.config import ExperimentConfig

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

SCHEMA_VERSION = 1
"""Version of the run-artifact layout (``manifest.json`` key ``schema_version``).
Bumped when a column/key of any artifact is removed, renamed, retyped or changes
unit/meaning; additive columns do not bump it (``docs/COMPATIBILITY.md`` §3)."""

# ------------------------------------------------------------------ Parquet schemas

LEDGER_SCHEMA: dict[str, pl.DataType] = {
    "txn_id": pl.String(),  # T-<8-digit counter>, unique per run
    "ts": pl.Int64(),  # UTC ns; when the transaction posted
    "type": pl.String(),  # TransactionType value: fill, fee, dividend, borrow, ...
    "symbol": pl.String(),  # nullable: null for cash-only rows (fees, financing)
    "qty": pl.String(),  # Decimal, signed like a position delta ("0" when none)
    "price": pl.String(),  # nullable: Decimal; null when the row has no price
    "amount": pl.String(),  # Decimal, sum of the row's cash deltas (see currency)
    "currency": pl.String(),  # currency of `amount`
    "refs": pl.String(),  # "k=v;k=v" sorted: order_id, fill_id, strategy_id, event_id, ...
}

ORDER_SCHEMA: dict[str, pl.DataType] = {
    "order_id": pl.String(),  # O-<8-digit counter>
    "symbol": pl.String(),  # instrument identifier
    "side": pl.String(),  # buy | sell
    "type": pl.String(),  # OrderType value
    "qty": pl.String(),  # Decimal, positive
    "limit_price": pl.Float64(),  # nullable: null unless limit / stop-limit
    "tif": pl.String(),  # TimeInForce value
    "created_at": pl.Int64(),  # UTC ns; clock.now when the order was created
    "state": pl.String(),  # final OrderState value
    "filled_qty": pl.String(),  # Decimal
    "strategy_id": pl.String(),  # nullable: null unless the order came from a MultiStrategy child
}

FILL_SCHEMA: dict[str, pl.DataType] = {
    "fill_id": pl.String(),  # F-<8-digit counter>
    "order_id": pl.String(),  # the order this fill belongs to (orders.parquet)
    "ts": pl.Int64(),  # UTC ns; the fill bar's available_at
    "symbol": pl.String(),  # instrument identifier
    "side": pl.String(),  # buy | sell
    "qty": pl.String(),  # Decimal, positive
    "price": pl.Float64(),  # in the symbol's currency
    "commission": pl.String(),  # Decimal, positive, in `currency`
    "currency": pl.String(),  # the symbol's currency
    "multiplier": pl.String(),  # Decimal; futures contract multiplier, "1" for equities
    "fx_to_base": pl.String(),  # Decimal; FX mid (currency -> base) at the fill's ts
    "strategy_id": pl.String(),  # nullable: null unless the order came from a MultiStrategy child
}

EQUITY_SCHEMA: dict[str, pl.DataType] = {
    "ts": pl.Int64(),  # UTC ns; one row per mark (timestamp with events)
    "equity": pl.Float64(),  # base currency, marked at ts
    "cash": pl.Float64(),  # base currency, all currencies converted at FX mid
    "realized_pnl": pl.Float64(),  # base currency, cumulative
    "fees_paid": pl.Float64(),  # base currency, cumulative, positive
}

# ---------------------------------------------------------------- manifest.json keys

ManifestPath = Literal["both", "event-driven", "vectorized"]


@dataclass(frozen=True, slots=True)
class ManifestField:
    """One key of ``manifest.json``. ``type`` is the JSON type; ``paths`` says which
    runner writes it; ``optional`` keys appear only after the step that adds them."""

    type: str
    nullable: bool
    description: str
    paths: ManifestPath = "both"
    optional: bool = False


MANIFEST_FIELDS: dict[str, ManifestField] = {
    "schema_version": ManifestField(
        "integer",
        False,
        "Artifact layout version (`SCHEMA_VERSION`); absent in runs before it existed.",
    ),
    "experiment_id": ManifestField("string", False, "`EXP-<12 hex>`: config hash + data hashes."),
    "config_hash": ManifestField("string", False, "SHA-256 of the canonical config JSON."),
    "commit": ManifestField(
        "string", False, "Git commit of the code that ran (`unknown` outside git)."
    ),
    "dirty": ManifestField("boolean", False, "True if the working tree had uncommitted changes."),
    "data_manifests": ManifestField(
        "object",
        False,
        "Role (`bars`, `corporate_actions`, `universe`, `fx_rates`) -> dataset content hash.",
    ),
    "bars_price_basis": ManifestField(
        "string",
        False,
        "The bars dataset's declared price basis: `adjusted` (a research series, not historical "
        "quotes), `raw`, or `undeclared` (ADR-0071).",
    ),
    "seed": ManifestField("integer", False, "`experiment.seed`."),
    "realism_level": ManifestField("string", False, "`RealismLevel` name, e.g. `BASIC_FRICTION`."),
    "runtime": ManifestField(
        "string", False, "`backtest`, `paper` or `live` (ADR-0051).", paths="event-driven"
    ),
    "vectorized": ManifestField(
        "boolean", False, "Always true for a vectorized run.", paths="vectorized"
    ),
    "mode": ManifestField("string", False, "`optimization` or `evaluation` (ADR-0021)."),
    "trial_family": ManifestField(
        "string", False, "`experiment.family`: the trial-counting scope (ADR-0008)."
    ),
    "trial_count": ManifestField(
        "integer",
        True,
        "Trials recorded in the family, this run included (a vectorized run is a trial too, "
        "ADR-0061).",
    ),
    "dsr": ManifestField(
        "number",
        True,
        "Deflated Sharpe probability in [0, 1] (per-period scale, ADR-0015); null if not "
        "computable.",
    ),
    "dsr_benchmark_sharpe": ManifestField(
        "number", True, "The per-period benchmark Sharpe the DSR is measured against."
    ),
    "dsr_error": ManifestField("string", True, "Why the DSR is null, when it is."),
    "dsr_n_trials_with_sharpe": ManifestField(
        "integer",
        True,
        "Trials whose Sharpe entered the DSR dispersion; below `trial_count` when some lack one "
        "(they still count toward N, ADR-0071). Null when the DSR is.",
    ),
    "pbo": ManifestField(
        "number", True, "Always null for a single run; PBO needs a multi-trial panel (ADR-0015)."
    ),
    "monte_carlo": ManifestField(
        "object",
        True,
        "Test name -> named statistics (ADR-0017); null on the vectorized path.",
        paths="both",
    ),
    "contamination": ManifestField(
        "boolean", True, "True if an optimization trial saw this window (ADR-0021)."
    ),
    "contamination_reason": ManifestField("string", True, "Human-readable contamination verdict."),
    "contamination_overlapping_trials": ManifestField(
        "array<string>", False, "Experiment ids that overlap this window."
    ),
    "quality_checks_ran": ManifestField(
        "array<string>", False, "Quality checks that passed before the run.", paths="event-driven"
    ),
    "quality_checks_skipped": ManifestField(
        "array<string>", False, "Checks skipped via `data.quality_skip`.", paths="event-driven"
    ),
    "quality_skip_reason": ManifestField(
        "string", False, "The recorded reason for the skips (empty if none).", paths="event-driven"
    ),
    "env_lock_hash": ManifestField("string", False, "SHA-256 of `uv.lock` (the environment)."),
    "factor_regression": ManifestField(
        "object",
        False,
        "Alpha, t-stat, loadings; added by `crucible validate --factors` (ADR-0022).",
        optional=True,
    ),
}


def manifest_keys(path: Literal["event-driven", "vectorized"]) -> set[str]:
    """Keys a freshly written manifest of this runner carries (optional keys excluded)."""
    return {
        key
        for key, spec in MANIFEST_FIELDS.items()
        if not spec.optional and spec.paths in ("both", path)
    }


# ------------------------------------------------------------------------ the reader


@dataclass(frozen=True, slots=True)
class LoadedExperiment:
    """A finished run read back from disk. Frames a runner did not write (a vectorized
    run has no orders, fills, ledger or trades) are empty. Nothing here is re-simulated."""

    experiment_id: ExperimentId
    path: Path
    config: ExperimentConfig
    manifest: dict[str, object]
    metrics: dict[str, MetricValue]
    equity: pl.DataFrame
    trades: pl.DataFrame
    orders: pl.DataFrame
    fills: pl.DataFrame
    ledger: pl.DataFrame


def _read_frame(path: Path) -> pl.DataFrame:
    return pl.read_parquet(path) if path.is_file() else pl.DataFrame()


def load_experiment(artifacts_root: Path, experiment_id: str) -> LoadedExperiment:
    """Reads ``<artifacts_root>/<experiment_id>/`` back into memory.

    Raises ``ExperimentError`` if the run or its ``manifest.json`` is missing, or if it
    was written by a newer artifact ``schema_version`` than this code understands. A
    manifest without ``schema_version`` is a version-0 run (same columns as version 1).
    """
    out_dir = artifacts_root / experiment_id
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.is_file():
        msg = (
            f"no run {experiment_id!r} under {artifacts_root}: missing {manifest_path}. "
            "Check the id (`crucible compare <family>` lists them) and --artifacts."
        )
        raise ExperimentError(msg)
    manifest: dict[str, object] = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = manifest.get("schema_version", 0)
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        msg = (
            f"run {experiment_id} has artifact schema_version {version!r}, this build reads "
            f"up to {SCHEMA_VERSION}: upgrade Crucible to read it (docs/COMPATIBILITY.md §3)"
        )
        raise ExperimentError(msg)
    raw_config = yaml.safe_load((out_dir / "config.yaml").read_text(encoding="utf-8"))
    metrics_raw: dict[str, dict[str, Any]] = json.loads(
        (out_dir / "metrics.json").read_text(encoding="utf-8")
    )
    metrics = {
        name: MetricValue(float(entry["value"]), entry["ci_low"], entry["ci_high"])
        for name, entry in metrics_raw.items()
    }
    return LoadedExperiment(
        experiment_id=ExperimentId(experiment_id),
        path=out_dir,
        config=ExperimentConfig.model_validate(raw_config),
        manifest=manifest,
        metrics=metrics,
        equity=_read_frame(out_dir / "equity.parquet"),
        trades=_read_frame(out_dir / "trades.parquet"),
        orders=_read_frame(out_dir / "orders.parquet"),
        fills=_read_frame(out_dir / "fills.parquet"),
        ledger=_read_frame(out_dir / "ledger.parquet"),
    )


def compare_metrics(
    runs: Sequence[LoadedExperiment], names: Sequence[str] | None = None
) -> pl.DataFrame:
    """One row per run: identity and provenance columns, then each metric with its
    confidence interval (``<name>``, ``<name>_ci_low``, ``<name>_ci_high``).

    The provenance columns (``realism_level``, ``mode``, ``trial_count``, ``dsr``) are
    always present: a headline metric never travels without them (AGENTS.md §9).
    ``names`` restricts and orders the metrics; unknown names raise ``ExperimentError``.
    """
    available = sorted({name for run in runs for name in run.metrics})
    chosen = list(names) if names is not None else available
    unknown = [name for name in chosen if name not in available]
    if unknown:
        msg = f"unknown metric(s) {unknown}; the loaded runs have {available}"
        raise ExperimentError(msg)
    rows: list[dict[str, object]] = []
    for run in runs:
        row: dict[str, object] = {
            "experiment_id": str(run.experiment_id),
            "realism_level": run.manifest.get("realism_level"),
            "mode": run.manifest.get("mode"),
            "trial_family": run.manifest.get("trial_family"),
            "trial_count": run.manifest.get("trial_count"),
            "dsr": run.manifest.get("dsr"),
        }
        for name in chosen:
            metric = run.metrics.get(name)
            row[name] = metric.value if metric is not None else None
            row[f"{name}_ci_low"] = metric.ci_low if metric is not None else None
            row[f"{name}_ci_high"] = metric.ci_high if metric is not None else None
        rows.append(row)
    return pl.DataFrame(rows)
