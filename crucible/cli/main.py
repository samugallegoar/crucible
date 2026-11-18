"""Crucible CLI entry point.

Implemented: ``backtest`` (the one-step product command, ADR-0068), ``spec``, ``config``,
``run`` (with ``--runtime backtest|paper|live``), ``run-vectorized``, ``report``, ``debug``,
``optimize``, ``validate``, ``compare``, ``schema``, ``futures run|check``,
``data check|list|build|fetch``.
``--json`` and ``--override`` are described in ADR-0059.
"""

from __future__ import annotations

import argparse
import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from crucible import __version__
from crucible.cli import machine, product_commands
from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.experiments.contracts import OUTPUT_SCHEMAS, output_json_schema
from crucible.experiments.optimize import DEFAULT_PBO_GROUPS

if TYPE_CHECKING:
    from collections.abc import Sequence

    from crucible.core.types import TimestampNs
    from crucible.data.interfaces import DatasetManifest


def _add_detail(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--detail",
        action="store_true",
        help="With --json: add the full manifest and the file inventory to the document "
        "(the default document is compact: ids, headline fields and metrics; ADR-0084)",
    )


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print one JSON document on stdout instead of text; a refusal prints "
        '{"error": {...}} (ADR-0059)',
    )


def _add_override(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="Set a config field before validation, e.g. strategy.params.lookback=60 "
        "(repeatable; VALUE is YAML). The run's hash and stored config include it (ADR-0059)",
    )


def _add_home(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--home",
        default=None,
        help="Crucible home folder: the artifacts root becomes its experiments/ folder and "
        "--store defaults to its data/ folder. Pass it or --artifacts, never both (they are "
        "two roots, and one family's trial registry lives in one)",
    )


FUTURES_VERDICT_LINE = (
    "Verdict: not assessed (C6/C7) — absence of assessment, not evidence of no edge."
)
"""The one human line a futures run prints about its verdict (ADR-0097): the same sentence
`futures run` and `artifact show` show, so a null verdict is never read as no edge."""


def _artifacts_root(args: argparse.Namespace) -> Path:
    """The artifacts root of a command: ``--artifacts``, or ``--home``'s experiments folder.

    ``--artifacts`` and ``--home`` together are refused: the root holds the shared
    ``trial_registry.duckdb``, and two roots would split one family's trial count across two
    registries (ADR-0008, ADR-0068). Neither keeps the historical default (``experiments/``
    relative to the working directory).
    """
    home = getattr(args, "home", None)
    artifacts = getattr(args, "artifacts", None)
    if home is None:
        return Path(artifacts) if artifacts is not None else Path("experiments")
    if artifacts is not None:
        msg = (
            f"pass one of --artifacts or --home, not both ({artifacts!r} and {home!r}): the "
            "artifacts root holds the trial registry, so two roots would count one family's "
            "trials in two places and neither count would be complete (ADR-0008)"
        )
        raise ConfigurationError(msg)
    from crucible.product.home import resolve_home

    return resolve_home(home).experiments


def _store_root(args: argparse.Namespace) -> Path:
    """The data store root of a futures run: ``--store``, or ``--home``'s data folder.

    ``--home`` defines ``data/``, so a home-based run needs no ``--store``; without a home the
    store stays required (there is no artifact root to derive it from).
    """
    store = getattr(args, "store", None)
    if store is not None:
        return Path(store)
    home = getattr(args, "home", None)
    if home is None:
        msg = (
            "--store is required: the run reads its four datasets from a data store. Pass "
            "--store DIR, or --home DIR to use its data/ folder as the store"
        )
        raise ConfigurationError(msg)
    from crucible.product.home import resolve_home

    return resolve_home(home).data


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        msg = f"{text} is not a positive integer (1 or more)"
        raise argparse.ArgumentTypeError(msg)
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crucible",
        description=(
            "Crucible: a quant backtesting engine that makes it hard to fool yourself. "
            "Gates: Data Integrity -> Signal Validity -> Execution Realism -> "
            "Statistical Validity."
        ),
    )
    parser.add_argument("--version", action="version", version=f"crucible {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="Run an experiment from a YAML config")
    run.add_argument("config", help="Path to experiment YAML")
    run.add_argument(
        "--artifacts", default="experiments", help="Artifact store root (default: experiments/)"
    )
    run.add_argument(
        "--runtime",
        choices=("backtest", "paper", "live"),
        default="backtest",
        help="Which runtime builds the engine (default: backtest). live needs `live: "
        "{enabled: true}` in the config (ADR-0043); paper and live runs are not new trials "
        "(ADR-0051)",
    )
    run.add_argument(
        "--stop-at",
        default=None,
        metavar="TIME",
        help="Run to the session boundary at or before TIME (ISO date, or datetime with a zone), "
        "write --checkpoint FILE and stop: no experiment, report or trial is produced "
        "(ADR-0058)",
    )
    run.add_argument(
        "--checkpoint",
        default=None,
        metavar="FILE",
        help="The checkpoint file: written at --stop-at, or rewritten atomically every "
        "--checkpoint-every of simulated time; an existing file is replaced",
    )
    run.add_argument(
        "--resume",
        default=None,
        metavar="FILE",
        help="Continue from a checkpoint and finish normally (artifacts equal an uninterrupted "
        "run's); the config must describe the same simulation, or the engine refuses",
    )
    run.add_argument(
        "--checkpoint-every",
        default=None,
        metavar="INTERVAL",
        help="While running to the end, rewrite --checkpoint FILE every INTERVAL of simulated "
        "time (30s, 15m, 4h, 1d, 2w); after a crash, --resume FILE continues from the latest",
    )
    run.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing experiment directory even if it was written by different code "
        "(same commit + same working-tree diff is replaced without this flag; ADR-0079)",
    )
    _add_json(run)
    _add_detail(run)
    _add_override(run)
    run_vec = subparsers.add_parser(
        "run-vectorized", help="Run an experiment on the vectorized engine (Levels 0-1)"
    )
    run_vec.add_argument("config", help="Path to a vectorized experiment YAML")
    run_vec.add_argument("--artifacts", default="experiments")
    run_vec.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing experiment directory written by different code (ADR-0079)",
    )
    _add_json(run_vec)
    _add_detail(run_vec)
    _add_override(run_vec)

    promote = subparsers.add_parser(
        "promote",
        help="Turn a vectorized config into an event-driven config at Level 2+ (ADR-0037)",
    )
    promote.add_argument("config", help="Path to the vectorized experiment YAML")
    promote.add_argument("--level", type=int, required=True, help="Target realism level (2-5)")
    promote.add_argument(
        "--lookback", type=int, required=True, help="History bars the promoted signal needs"
    )
    promote.add_argument(
        "--execution", required=True, help="YAML mapping of ExecutionConfig fields (spread, ...)"
    )
    promote.add_argument(
        "--out", default=None, help="Write the promoted YAML here (default: stdout)"
    )
    promote.add_argument("--run", action="store_true", help="Also run the promoted config")
    promote.add_argument("--artifacts", default="experiments")
    _add_json(promote)
    _add_override(promote)

    report = subparsers.add_parser("report", help="Re-render the report for a finished experiment")
    report.add_argument("experiment_id", help="Experiment id (EXP-...)")
    report.add_argument("--artifacts", default="experiments")
    _add_json(report)

    debug = subparsers.add_parser(
        "debug", help="Replay a recorded experiment, stepping the event loop"
    )
    debug.add_argument("experiment_id", help="Experiment id (EXP-...)")
    debug.add_argument(
        "--at",
        required=True,
        help="Stop at this time (ISO date/datetime or raw UTC ns) and dump state",
    )
    debug.add_argument("--artifacts", default="experiments")
    debug.add_argument("--order", default=None, help="Only explain this order id")
    _add_json(debug)

    optimize = subparsers.add_parser(
        "optimize", help="1D parameter sweep, tagged as trials, assembling a PBO panel (R4.3/R4.9)"
    )
    optimize.add_argument(
        "config", help="Path to experiment YAML (experiment.mode must be optimization)"
    )
    optimize.add_argument("--param", required=True, help="Strategy parameter name to sweep")
    optimize.add_argument("--values", required=True, help="Comma-separated values, e.g. 40,60,80")
    optimize.add_argument("--metric", default="sharpe")
    optimize.add_argument(
        "--pbo-groups",
        type=int,
        default=DEFAULT_PBO_GROUPS,
        help=f"CSCV group count for PBO, must be even (default: {DEFAULT_PBO_GROUPS})",
    )
    optimize.add_argument("--artifacts", default="experiments")
    optimize.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Run the sweep's trials in a process pool of this size (default: sequential); "
        "byte-identical either way (ADR-0038), purely a speed knob",
    )
    optimize.add_argument(
        "--vectorized",
        action="store_true",
        help="Run the sweep on the vectorized engine (signal-function strategies, Levels 0-1); "
        "each point is a trial and the PBO and best-point DSR are reported as usual (ADR-0061)",
    )
    _add_json(optimize)
    _add_override(optimize)

    wf = subparsers.add_parser(
        "walk-forward",
        help="Choose a parameter on train folds, report only out-of-fold metrics (ADR-0081)",
    )
    wf.add_argument("config", help="Path to experiment YAML")
    wf.add_argument("--param", required=True, help="Strategy parameter to choose per fold")
    wf.add_argument("--values", required=True, help="Comma-separated candidate values")
    wf.add_argument("--train", required=True, help="Train span per fold, e.g. 26w (s/m/h/d/w)")
    wf.add_argument("--test", required=True, help="Test span per fold, e.g. 13w")
    wf.add_argument("--step", required=True, help="How far the train window advances per fold")
    wf.add_argument("--metric", default="sharpe", help="Higher-is-better metric to choose by")
    wf.add_argument("--holdout", default=None, help="Final span never used for selection")
    wf.add_argument(
        "--max-runs", type=int, default=250, help="Refuse a plan above this many experiment runs"
    )
    wf.add_argument("--artifacts", default="experiments")
    _add_json(wf)
    _add_override(wf)
    validate = subparsers.add_parser(
        "validate", help="Run an experiment, optionally with a factor regression (R4.7)"
    )
    validate.add_argument("config", help="Path to experiment YAML")
    validate.add_argument(
        "--factors",
        default=None,
        help="CSV of factor return series: one column per factor, one row per period, "
        "row-aligned to the run's own returns (no date column)",
    )
    validate.add_argument("--artifacts", default="experiments")
    _add_json(validate)
    _add_override(validate)

    compare = subparsers.add_parser(
        "compare", help="Compare every recorded trial in a family from the trial registry"
    )
    compare.add_argument("family", help="Trial family name (ExperimentHeader.family)")
    compare.add_argument("--artifacts", default="experiments")
    _add_json(compare)

    artifact = subparsers.add_parser(
        "artifact", help="Show or verify a finished run by its artifact id (ADR-0084)"
    )
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)
    show = artifact_sub.add_parser(
        "show", help="Print a run by artifact id (ART-...) or experiment id (EXP-...)"
    )
    show.add_argument("artifact_id", help="Artifact id (ART-...) or experiment id (EXP-...)")
    show.add_argument("--artifacts", default=None)
    _add_home(show)
    _add_detail(show)
    _add_json(show)
    verify = artifact_sub.add_parser(
        "verify", help="Recompute the artifact id from the files and refuse if it differs"
    )
    verify.add_argument("artifact_id", help="Artifact id (ART-...) or experiment id (EXP-...)")
    verify.add_argument("--artifacts", default=None)
    _add_home(verify)
    _add_json(verify)

    futures = subparsers.add_parser(
        "futures",
        help="Futures runs on a continuous CME series: run | check (ADR-0095)",
    )
    futures_sub = futures.add_subparsers(dest="futures_command", required=True)
    futures_run = futures_sub.add_parser(
        "run",
        help="Simulate a futures config and write its sealed artifact (ADR-0095)",
    )
    futures_run.add_argument("--config", required=True, help="Path to a futures-run YAML")
    futures_run.add_argument(
        "--store",
        default=None,
        help="Data store root holding the four datasets of the root (default: the --home's "
        "data folder when --home is given; required otherwise)",
    )
    futures_run.add_argument(
        "--artifacts",
        default=None,
        help="Artifact store root (default: experiments/, or the --home's experiments folder)",
    )
    _add_home(futures_run)
    futures_run.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing run directory (the same config and data reproduce the same "
        "artifact id, and the family's trial count does not grow)",
    )
    _add_json(futures_run)
    futures_check = futures_sub.add_parser(
        "check", help="Load and validate a futures config only (no store, no run)"
    )
    futures_check.add_argument("--config", required=True, help="Path to a futures-run YAML")
    _add_json(futures_check)

    schema = subparsers.add_parser(
        "schema",
        help="Print a JSON Schema: the experiment config (default), a strategy spec, or an "
        "output document",
    )
    schema.add_argument("--out", default=None, help="Write the schema here (default: stdout)")
    schema.add_argument(
        "--kind",
        choices=["experiment", "strategy-spec", "futures-run", *OUTPUT_SCHEMAS],
        default="experiment",
        help="which schema: the experiment config, the no-code strategy spec (ADR-0067), the "
        "futures-run config (ADR-0095), or an output document: run, verification, error, "
        "manifest (ADR-0084), futures-run-document (the document a sealed futures run prints, "
        "ADR-0097)",
    )

    data = subparsers.add_parser(
        "data", help="Dataset tooling: check | build | continuous | fetch | list"
    )
    data_sub = data.add_subparsers(dest="data_command", required=True)
    check = data_sub.add_parser("check", help="Run quality checks on a dataset")
    check.add_argument("--store", required=True, help="Data store root")
    check.add_argument("--dataset", required=True)
    check.add_argument("--calendar", required=True, help="exchange_calendars name or '24/7'")
    check.add_argument(
        "--skip", action="append", default=[], help="quality check to skip (repeatable)"
    )
    check.add_argument("--skip-reason", default="", help="why the checks are skipped (required)")
    integrity = data_sub.add_parser(
        "integrity",
        help="Minute-level integrity report of a bar dataset: gaps, short sessions, contract "
        "violations (ADR-0088)",
    )
    integrity.add_argument("--store", required=True, help="Data store root")
    integrity.add_argument("--dataset", required=True)
    integrity.add_argument(
        "--bar-seconds", type=_positive_int, default=60, help="bar length (default 60)"
    )
    integrity.add_argument(
        "--session",
        choices=["cme", "utc"],
        default="cme",
        help="how a bar gets its session: cme = Globex trade date from the CME session "
        "calendar (ADR-0092), utc = UTC day",
    )
    integrity.add_argument(
        "--calendar",
        default=None,
        help="exchange_calendars name (e.g. CMES) to compare session dates with",
    )
    integrity.add_argument(
        "--top", type=int, default=10, help="examples listed per finding (default 10)"
    )
    _add_json(integrity)
    catalog = data_sub.add_parser(
        "catalog",
        help="Dataset registry: identity, origin, lineage, contract and range of every dataset "
        "(ADR-0089)",
    )
    catalog.add_argument("--store", required=True, help="Data store root")
    catalog.add_argument(
        "--dataset", action="append", default=[], help="restrict to this dataset (repeatable)"
    )
    catalog.add_argument(
        "--verify", action="store_true", help="recompute each data file's SHA-256 (slow)"
    )
    catalog.add_argument(
        "--top", type=int, default=10, help="symbols listed per dataset (default 10)"
    )
    _add_json(catalog)
    listing = data_sub.add_parser("list", help="List datasets and manifest hashes")
    listing.add_argument("--store", required=True)
    _add_json(listing)
    _add_json(check)
    build = data_sub.add_parser("build", help="Build datasets from an import spec (ADR-0052)")
    build.add_argument("spec", help="Path to an import spec YAML (see examples/imports/)")
    build.add_argument("--store", required=True, help="Data store root to write into")
    build.add_argument("--start", default=None, help="polymarket: first contract start (ISO or ns)")
    build.add_argument("--end", default=None, help="polymarket: contract starts before this")
    build.add_argument(
        "--max-contracts",
        type=_positive_int,
        default=None,
        help="polymarket: keep the first N contracts",
    )
    build.add_argument(
        "--max-rows",
        type=_positive_int,
        default=5_000_000,
        help="refuse to write more rows than this",
    )
    _add_json(build)
    continuous = data_sub.add_parser(
        "continuous",
        help="Build the continuous futures series of each root from its raw contracts (ADR-0086)",
    )
    continuous.add_argument("--store", required=True, help="Data store root (read and write)")
    continuous.add_argument(
        "--roots", required=True, help="Comma-separated roots, e.g. es,nq,ym,rty,nkd"
    )
    continuous.add_argument(
        "--raw",
        default="{root}_1m_raw",
        help="Raw dataset name, with {root} (default {root}_1m_raw, ADR-0085)",
    )
    continuous.add_argument(
        "--threshold",
        type=float,
        default=1.0,
        help="the next contract must exceed this multiple of the held contract's volume",
    )
    continuous.add_argument(
        "--backstop-sessions",
        type=int,
        default=1,
        help="never hold a contract into its final session (1); 0 disables the backstop",
    )
    continuous.add_argument(
        "--trim-to-calendar",
        action="store_true",
        help="drop (and count) raw bars outside the CME session calendar's coverage instead of "
        "refusing, e.g. NKD before 2012-11-19 (ADR-0092)",
    )
    _add_json(continuous)
    fetch = data_sub.add_parser(
        "fetch", help="Fetch prices from a data provider into a dataset (ADR-0063)"
    )
    fetch.add_argument("--store", required=True, help="Data store root to write into")
    fetch.add_argument("--dataset", required=True, help="Name of the dataset to write")
    fetch.add_argument("--symbols", required=True, help="Comma-separated tickers, e.g. AAPL,MSFT")
    fetch.add_argument("--start", required=True, help="First date, YYYY-MM-DD (inclusive)")
    fetch.add_argument("--end", required=True, help="Last date, YYYY-MM-DD (inclusive)")
    fetch.add_argument(
        "--provider",
        default=None,
        help="yfinance or tiingo (default: CRUCIBLE_DATA_PROVIDER, else yfinance)",
    )
    fetch.add_argument("--interval", default="1d", help="Bar size, e.g. 1d, 1h, 5m (default 1d)")
    fetch.add_argument(
        "--price-basis",
        default="adjusted",
        choices=["adjusted", "raw"],
        help="adjusted (default, splits and dividends) or raw (tiingo only)",
    )
    fetch.add_argument("--calendar", default="XNYS", help="exchange_calendars name or '24/7'")
    fetch.add_argument(
        "--allow-partial",
        action="store_true",
        help="write the symbols that worked even if some failed (the report lists the failures)",
    )
    fetch.add_argument(
        "--cache-dir", default="data/cache/providers", help="Raw-response cache directory"
    )
    fetch.add_argument("--no-cache", action="store_true", help="Do not read or write the cache")
    fetch.add_argument("--refresh", action="store_true", help="Ignore cached answers and re-fetch")
    fetch.add_argument(
        "--ohlc-repair",
        default="refuse",
        choices=["refuse", "clamp", "clamp_rounding"],
        help="what to do with a bar whose high/low do not bound its open/close: refuse, clamp "
        "every such bar, or clamp_rounding (only float-rounding-sized violations; real ones "
        "are still refused)",
    )
    fetch.add_argument(
        "--max-rows",
        type=_positive_int,
        default=5_000_000,
        help="refuse to write more rows than this",
    )
    _add_json(fetch)

    product_commands.add_parsers(subparsers)
    return parser


def _checkpoint_options(args: argparse.Namespace) -> tuple[TimestampNs | None, int | None]:
    """Validates how the checkpoint flags combine and parses their values. Every refusal is a
    ``ConfigurationError`` raised before the config's data is touched (ADR-0058)."""
    from crucible.experiments.config import parse_interval, parse_when

    stop, every, path = args.stop_at, args.checkpoint_every, args.checkpoint
    for flag, value in (("--checkpoint", path), ("--resume", args.resume)):
        if value is not None and not value.strip():
            msg = f"{flag} is empty; give a file path"
            raise ConfigurationError(msg)
    if stop is not None and stop.strip().isdigit():
        msg = (
            f"--stop-at {stop} is a raw integer; give an ISO date or datetime "
            "(for example 2020-06-01 or 2020-06-01T14:30:00Z), not a raw integer"
        )
        raise ConfigurationError(msg)
    if stop is not None and every is not None:
        msg = (
            "--stop-at and --checkpoint-every cannot be combined: one stops the run at a time, "
            "the other saves while it keeps running; choose one"
        )
        raise ConfigurationError(msg)
    if stop is not None and path is None:
        msg = "--stop-at needs --checkpoint FILE, the file the run is saved to"
        raise ConfigurationError(msg)
    if every is not None and path is None:
        msg = "--checkpoint-every needs --checkpoint FILE, the file that is rewritten"
        raise ConfigurationError(msg)
    if path is not None and stop is None and every is None:
        msg = (
            "--checkpoint needs --stop-at TIME (save and stop) or --checkpoint-every INTERVAL "
            "(save while running)"
        )
        raise ConfigurationError(msg)
    return (
        parse_when(stop) if stop is not None else None,
        parse_interval(every) if every is not None else None,
    )


def _cmd_run(args: argparse.Namespace) -> int:
    from crucible.experiments.config import load_config
    from crucible.experiments.runner import (
        checkpoint_experiment,
        run_experiment,
        run_with_scenarios,
    )

    config = load_config(Path(args.config), args.override)
    runtime = args.runtime
    stop_at, every_ns = _checkpoint_options(args)
    if config.execution.scenarios:
        if any(
            value is not None
            for value in (args.stop_at, args.checkpoint, args.resume, args.checkpoint_every)
        ):
            msg = (
                "execution.scenarios (scenario fan-out) cannot be checkpointed or resumed: it "
                "runs several simulations; run one experiment, or remove the scenarios"
            )
            raise CrucibleError(msg)
        if runtime != "backtest":
            msg = (
                "execution.scenarios (scenario fan-out) runs only with --runtime backtest; "
                f"got --runtime {runtime}. Remove the scenarios or use the backtest runtime"
            )
            raise CrucibleError(msg)
        outcomes = run_with_scenarios(config, Path(args.artifacts))
        if args.json:
            base_run = outcomes[0].artifacts
            machine.emit(
                {
                    **machine.run_payload(base_run),
                    "decay_report": str(base_run.path / "scenario_decay.html"),
                    "scenarios": [
                        {"scenario": o.scenario, "experiment_id": str(o.artifacts.experiment_id)}
                        for o in outcomes
                    ],
                }
            )
            return 0
        for outcome in outcomes:
            sys.stdout.write(f"{outcome.scenario}: {outcome.artifacts.experiment_id}\n")
        base = outcomes[0].artifacts
        sys.stdout.write(
            f"artifacts: {base.path}\ndecay:     {base.path / 'scenario_decay.html'}\n"
        )
        return 0
    resume = Path(args.resume) if args.resume is not None else None
    checkpoint = Path(args.checkpoint) if args.checkpoint is not None else None
    if stop_at is not None and checkpoint is not None:
        written = checkpoint_experiment(
            config, checkpoint, stop_at=stop_at, runtime=runtime, resume_from=resume
        )
        boundary = datetime.fromtimestamp(int(written.boundary_ts) // 10**9, tz=UTC)
        if args.json:
            machine.emit(
                {
                    "checkpoint": str(written.path),
                    "boundary": boundary.isoformat(),
                    "boundary_ns": int(written.boundary_ts),
                }
            )
            return 0
        sys.stdout.write(
            f"checkpoint: {written.path}\n"
            f"boundary:   {boundary.isoformat()} (ns {int(written.boundary_ts)})\n"
        )
        return 0
    artifacts = run_experiment(
        config,
        Path(args.artifacts),
        runtime=runtime,
        resume_from=resume,
        checkpoint_path=checkpoint if every_ns is not None else None,
        checkpoint_every_ns=every_ns,
        overwrite=args.overwrite,
    )
    if args.json:
        machine.emit(machine.run_payload(artifacts, detail=args.detail))
        return 0
    sys.stdout.write(
        f"{artifacts.experiment_id}\n"
        f"artifacts: {artifacts.path}\n"
        f"report:    {artifacts.report_path}\n"
    )
    return 0


def _cmd_run_vectorized(args: argparse.Namespace) -> int:
    from crucible.experiments.config import load_config
    from crucible.experiments.vectorized_runner import run_vectorized_experiment

    config = load_config(Path(args.config), args.override)
    artifacts = run_vectorized_experiment(config, Path(args.artifacts), overwrite=args.overwrite)
    if args.json:
        machine.emit(machine.run_payload(artifacts, detail=args.detail))
        return 0
    sys.stdout.write(
        f"{artifacts.experiment_id}\n"
        f"artifacts: {artifacts.path}\n"
        f"report:    {artifacts.report_path}\n"
    )
    return 0


def _cmd_promote(args: argparse.Namespace) -> int:
    import yaml
    from pydantic import ValidationError

    from crucible.core.errors import ConfigurationError
    from crucible.core.types import RealismLevel
    from crucible.experiments.config import ExecutionConfig, canonical_yaml, load_config
    from crucible.experiments.promotion import promote_config
    from crucible.experiments.runner import run_experiment

    if args.run and not args.out:
        msg = (
            "--run needs --out so the promoted config is kept next to its run and stdout "
            "stays pure YAML"
        )
        raise ConfigurationError(msg)
    try:
        level = RealismLevel(args.level)
    except ValueError:
        msg = f"--level {args.level} is not a realism level; use 2 to 5"
        raise ConfigurationError(msg) from None
    execution_path = Path(args.execution)
    if not execution_path.is_file():
        msg = f"--execution file {execution_path} does not exist"
        raise ConfigurationError(msg)
    try:
        raw = yaml.safe_load(execution_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        msg = f"--execution file {execution_path} is not valid UTF-8 text: {exc}"
        raise ConfigurationError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"--execution file {execution_path} must be a YAML mapping of ExecutionConfig fields"
        raise ConfigurationError(msg)
    try:
        execution = ExecutionConfig.model_validate(raw)
    except ValidationError as exc:
        msg = f"--execution file {execution_path} is not a valid ExecutionConfig: {exc}"
        raise ConfigurationError(msg) from exc

    promoted = promote_config(
        load_config(Path(args.config), args.override),
        target_realism_level=level,
        execution=execution,
        promotion_lookback=args.lookback,
    )
    text = canonical_yaml(promoted)
    config_out: str | None = None
    yaml_out: str | None = None
    if args.out:
        if not Path(args.out).parent.is_dir():
            msg = f"--out directory {Path(args.out).parent} does not exist; create it first"
            raise ConfigurationError(msg)
        Path(args.out).write_text(text, encoding="utf-8", newline=chr(10))
        config_out = str(args.out)
        if not args.json:
            sys.stdout.write(f"promoted config: {args.out}\n")
    elif args.json:
        yaml_out = text
    else:
        sys.stdout.write(text)
    run_doc: dict[str, object] | None = None
    if args.run:
        artifacts = run_experiment(promoted, Path(args.artifacts))
        if args.json:
            run_doc = machine.run_payload(artifacts)
        else:
            sys.stdout.write(
                f"{artifacts.experiment_id}\n"
                f"artifacts: {artifacts.path}\n"
                f"report:    {artifacts.report_path}\n"
            )
    if args.json:
        machine.emit({"config": config_out, "yaml": yaml_out, "run": run_doc})
    return 0


_DEBUG_LAST_EVENTS = 20
"""How many of the final events ``debug --json`` returns (the total is reported beside them)."""


def _cmd_debug(args: argparse.Namespace) -> int:
    """Deterministic replay: rebuild the engine from the run's stored config
    and step events until --at, then dump portfolio/order state.
    Determinism makes replay equal to the original run."""
    from crucible.core.errors import CrucibleError as _CrucibleError
    from crucible.core.interfaces import Event
    from crucible.core.types import Currency
    from crucible.experiments.config import load_config, parse_when
    from crucible.experiments.runner import assemble_engine

    out_dir = Path(args.artifacts) / args.experiment_id
    config_path = out_dir / "config.yaml"
    if not config_path.is_file():
        msg = f"no run found at {out_dir}; check the experiment id and --artifacts root"
        raise _CrucibleError(msg)
    config = load_config(config_path)
    at = int(args.at) if args.at.isdigit() else int(parse_when(args.at))

    class _Halt(Exception):
        pass

    events_total = 0
    last_events: deque[dict[str, object]] = deque(maxlen=_DEBUG_LAST_EVENTS)

    def observer(event: Event) -> None:
        nonlocal events_total
        symbol = getattr(event, "symbol", "")
        if args.json:  # one document at the end: nothing else may reach stdout
            events_total += 1
            last_events.append(
                {
                    "ts": int(event.ts),
                    "seq": int(event.seq),
                    "kind": type(event).__name__,
                    "symbol": str(symbol),
                }
            )
        else:
            sys.stdout.write(
                f"{int(event.ts):>20} seq={event.seq:<6} {type(event).__name__:<22} {symbol}\n"
            )
        if int(event.ts) >= at:
            raise _Halt

    import contextlib

    if config.live is not None and config.live.enabled:
        from crucible.live.runtime import LiveRuntime

        engine = LiveRuntime(config, observer=observer).engine  # same venue and feed as the run
    else:
        engine = assemble_engine(config, observer=observer)
    with contextlib.suppress(_Halt):
        engine.run()
    snapshot = engine.snapshot()
    base = Currency(config.data.base_currency)
    if args.json:
        machine.emit(
            {
                "experiment_id": args.experiment_id,
                "at": at,
                "events_total": events_total,
                "last_events": list(last_events),
                "state": {
                    "cash": {"currency": str(base), "amount": str(snapshot.cash(base))},
                    "positions": [
                        {"symbol": str(s), "qty": str(p.qty), "avg_cost": str(p.avg_cost)}
                        for s, p in sorted(snapshot.positions().items())
                    ],
                    "orders": [
                        {
                            "id": str(o.id),
                            "symbol": str(o.symbol),
                            "side": o.side.value,
                            "type": o.type.value,
                            "qty": str(o.qty),
                            "state": o.state.value,
                            "filled_qty": str(o.filled_qty),
                            "why_not_filled": [
                                {"ts": int(ts), "reason": reason}
                                for ts, reason in engine.execution.why_not_filled(o.id)
                            ],
                        }
                        for o in engine.order_manager.all_orders()
                        if args.order is None or str(o.id) == args.order
                    ],
                },
            }
        )
        return 0
    sys.stdout.write(f"\n--- state at ts<={at} ---\n")
    sys.stdout.write(f"cash({base}): {snapshot.cash(base)}\n")
    for symbol, position in sorted(snapshot.positions().items()):
        sys.stdout.write(f"position {symbol}: qty={position.qty} avg_cost={position.avg_cost}\n")
    for order in engine.order_manager.all_orders():
        if args.order is not None and str(order.id) != args.order:
            continue
        sys.stdout.write(
            f"order {order.id} {order.symbol} {order.side.value} {order.type.value} "
            f"qty={order.qty} state={order.state.value} filled={order.filled_qty}\n"
        )
        for ts, reason in engine.execution.why_not_filled(order.id):
            sys.stdout.write(f"    {ts}: {reason}\n")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from crucible.experiments.runner import rebuild_report

    out_dir = Path(args.artifacts) / args.experiment_id
    if not (out_dir / "manifest.json").is_file():
        msg = f"no run found at {out_dir}; check the experiment id and --artifacts root"
        raise CrucibleError(msg)
    report_path = rebuild_report(out_dir)
    if args.json:
        machine.emit({"experiment_id": args.experiment_id, "report": str(report_path)})
        return 0
    sys.stdout.write(f"report: {report_path}\n")
    return 0


def _cmd_optimize(args: argparse.Namespace) -> int:
    from crucible.experiments.config import load_config
    from crucible.experiments.optimize import optimize_1d

    config = load_config(Path(args.config), args.override)
    values = [float(v) for v in args.values.split(",")]
    result, _runs = optimize_1d(
        config,
        args.param,
        values,
        Path(args.artifacts),
        metric=args.metric,
        pbo_groups=args.pbo_groups,
        max_workers=args.workers,
        engine="vectorized" if args.vectorized else "event",
    )
    if args.json:
        machine.emit(
            {
                "param": args.param,
                "metric": args.metric,
                "points": [
                    {"value": value, "experiment_id": exp_id, "metric_value": metric_value}
                    for value, exp_id, metric_value in zip(
                        result.values, result.experiment_ids, result.metric_values, strict=True
                    )
                ],
                "pbo": {
                    "pbo": result.pbo.pbo,
                    "n_combinations": result.pbo.n_combinations,
                    "n_trials": result.pbo.n_trials,
                    "n_tied_splits": result.pbo.n_tied_splits,
                },
                "best": {
                    "experiment_id": result.best_experiment_id,
                    "dsr": None if result.best_dsr is None else result.best_dsr.dsr,
                    "benchmark_sharpe": (
                        None if result.best_dsr is None else result.best_dsr.benchmark_sharpe
                    ),
                    "dsr_error": result.best_dsr_error,
                },
                "reality_check": (
                    None
                    if result.reality_check is None
                    else {
                        **result.reality_check.as_dict(),
                        "best_value": result.values[result.reality_check.best_index],
                    }
                ),
                "reality_check_error": result.reality_check_error,
            }
        )
        return 0
    for value, exp_id, metric_value in zip(
        result.values, result.experiment_ids, result.metric_values, strict=True
    ):
        sys.stdout.write(f"{args.param}={value}: {exp_id} {args.metric}={metric_value:.6g}\n")
    sys.stdout.write(
        f"PBO: {result.pbo.pbo:.4f} "
        f"(n_combinations={result.pbo.n_combinations}, n_trials={result.pbo.n_trials}, "
        f"n_tied_splits={result.pbo.n_tied_splits})\n"
    )
    check = result.reality_check
    if check is None:
        sys.stdout.write(f"reality check: not computable: {result.reality_check_error}\n")
    else:
        sys.stdout.write(
            f"reality check over {check.n_candidates} values (does the best beat zero after the "
            f"search?): White p={check.p_value_rc:.4f}, Hansen SPA p={check.p_value_spa:.4f}; best "
            f"by mean return: {args.param} {result.values[check.best_index]} "
            f"(n_periods={check.n_periods}, block={check.mean_block:.1f})\n"
        )
    if result.best_dsr is None:
        sys.stdout.write(
            f"best: {result.best_experiment_id} DSR not computable: {result.best_dsr_error}\n"
        )
    else:
        sys.stdout.write(
            f"best: {result.best_experiment_id} DSR={result.best_dsr.dsr:.4f} "
            f"(benchmark_sharpe={result.best_dsr.benchmark_sharpe:.4f})\n"
        )
    return 0


def _cmd_walk_forward(args: argparse.Namespace) -> int:
    from crucible.experiments.config import load_config
    from crucible.experiments.walk_forward import walk_forward

    config = load_config(Path(args.config), args.override)
    values = [float(part) for part in args.values.split(",")]
    result = walk_forward(
        config,
        Path(args.artifacts),
        param_name=args.param,
        values=values,
        train=args.train,
        test=args.test,
        step=args.step,
        metric=args.metric,
        holdout=args.holdout,
        max_runs=args.max_runs,
    )
    if args.json:
        machine.emit(
            {
                "param": result.param_name,
                "metric": result.metric,
                "values": list(result.values),
                "folds": [
                    {
                        "index": fold.index,
                        "chosen": fold.chosen_value,
                        "test_experiment_id": fold.test_experiment_id,
                        "test_metric": fold.test_metrics[result.metric].value,
                    }
                    for fold in result.folds
                ],
                "mean_test_metric": result.mean_metric,
                "std_test_metric": result.std_metric,
                "share_positive": result.share_positive,
                "holdout": (
                    None
                    if result.holdout is None
                    else {
                        "chosen": result.holdout.chosen_value,
                        "test_experiment_id": result.holdout.test_experiment_id,
                        "test_metric": result.holdout.test_metrics[result.metric].value,
                    }
                ),
                "summary": str(result.summary_path),
            }
        )
        return 0
    for fold in result.folds:
        sys.stdout.write(
            f"fold {fold.index}: {args.param}={fold.chosen_value} out-of-fold "
            f"{result.metric}={fold.test_metrics[result.metric].value:.4f} "
            f"({fold.test_experiment_id})\n"
        )
    sys.stdout.write(
        f"mean {result.metric}={result.mean_metric:.4f} sd={result.std_metric:.4f} "
        f"positive folds={result.share_positive:.0%}\n"
    )
    if result.holdout is not None:
        sys.stdout.write(
            f"holdout: {args.param}={result.holdout.chosen_value} "
            f"{result.metric}={result.holdout.test_metrics[result.metric].value:.4f} "
            "(never used for selection)\n"
        )
    sys.stdout.write(f"summary: {result.summary_path}\n")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    from crucible.experiments.config import load_config
    from crucible.experiments.validate import load_factors_csv, validate_run

    config = load_config(Path(args.config), args.override)
    factors = load_factors_csv(Path(args.factors)) if args.factors else None
    result = validate_run(config, Path(args.artifacts), factors=factors)
    if args.json:
        fr = result.factor_regression
        machine.emit(
            {
                **machine.run_payload(result.run),
                "factor_regression": None
                if fr is None
                else {
                    "alpha": fr.alpha,
                    "alpha_t_stat": fr.alpha_t_stat,
                    "r_squared": fr.r_squared,
                },
            }
        )
        return 0
    sys.stdout.write(
        f"{result.run.experiment_id}\n"
        f"artifacts: {result.run.path}\n"
        f"report:    {result.run.report_path}\n"
    )
    if result.factor_regression is not None:
        fr = result.factor_regression
        sys.stdout.write(
            f"factor regression: alpha={fr.alpha:.6g} t_stat={fr.alpha_t_stat:.4f} "
            f"r_squared={fr.r_squared:.4f}\n"
        )
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    """Result-registry queries (ADR-0038):
    every trial recorded for a family, ranked by per-period Sharpe
    (descending, untracked trials last), with each trial's DSR read back
    from its own ``manifest.json`` when that artifact is still on disk."""
    import json

    from crucible.validation.trial_registry import DuckDBTrialRegistry

    artifacts_root = Path(args.artifacts)
    registry = DuckDBTrialRegistry(artifacts_root / "trial_registry.duckdb")
    trials = registry.all_trials(args.family)
    if not trials and args.json:
        machine.emit({"family": args.family, "trials": []})
        return 0
    if not trials:
        sys.stdout.write(f"no trials recorded for family {args.family!r}\n")
        return 0

    trials.sort(key=lambda t: t.sharpe if t.sharpe is not None else float("-inf"), reverse=True)
    if args.json:
        rows: list[dict[str, object]] = []
        for trial in trials:
            manifest_file = artifacts_root / trial.experiment_id / "manifest.json"
            dsr_json = (
                json.loads(manifest_file.read_text(encoding="utf-8")).get("dsr")
                if manifest_file.is_file()
                else None
            )
            rows.append(
                {
                    "experiment_id": trial.experiment_id,
                    "sharpe": trial.sharpe,
                    "dsr": dsr_json,
                    "mode": trial.mode,
                    "start_ns": trial.start_ns,
                    "end_ns": trial.end_ns,
                }
            )
        machine.emit({"family": args.family, "trials": rows})
        return 0
    for trial in trials:
        dsr_text = "unknown"
        manifest_path = artifacts_root / trial.experiment_id / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            dsr_text = f"{manifest['dsr']:.4f}" if manifest.get("dsr") is not None else "n/a"
        sharpe_text = f"{trial.sharpe:.4f}" if trial.sharpe is not None else "n/a"
        window_text = (
            f"[{trial.start_ns},{trial.end_ns})"
            if trial.start_ns is not None and trial.end_ns is not None
            else "n/a"
        )
        sys.stdout.write(
            f"{trial.experiment_id}  sharpe={sharpe_text}  dsr={dsr_text}  "
            f"mode={trial.mode or 'n/a'}  window={window_text}\n"
        )
    return 0


def _manifest_row(manifest: DatasetManifest) -> dict[str, object]:
    return {
        "dataset": str(manifest.dataset),
        "rows": manifest.row_count,
        "content_hash": manifest.content_hash,
        "source": manifest.source,
    }


def _cmd_artifact(args: argparse.Namespace) -> int:
    """``crucible artifact show|verify``: a run by its artifact id (ADR-0084).

    ``show`` prints the run document, or — when the artifact is a futures run — the futures-run
    document (ADR-0097), the same document ``crucible futures run --json`` prints.
    """
    from crucible.experiments.artifact_id import find_artifact, verify_artifact
    from crucible.experiments.contracts import run_document, verification_document

    run_dir = find_artifact(_artifacts_root(args), args.artifact_id)
    if args.artifact_command == "verify":
        verified = verify_artifact(run_dir)
        if args.json:
            machine.emit(verification_document(verified, run_dir))
            return 0
        sys.stdout.write(f"verified: {verified}\n")
        return 0
    if _manifest_kind(run_dir) == "futures_run":
        return _show_futures_run(run_dir, json_output=bool(args.json))
    doc = run_document(run_dir, detail=args.detail)
    if args.json:
        machine.emit(doc)
        return 0
    metrics = doc["metrics"]
    assert isinstance(metrics, dict)
    lines = [
        f"{doc['artifact_id'] or '(no artifact id: written before ADR-0084)'}  "
        f"({doc['experiment_id']})",
        f"artifacts: {doc['artifacts']}",
    ]
    for name, metric in metrics.items():
        lines.append(f"{name}: {metric['value']}")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def _manifest_kind(run_dir: Path) -> object:
    """The ``kind`` of the run's manifest (``None`` when it has none: a run from before the
    artifact contract), read without validating it: the caller decides which document fits."""
    import json

    try:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return manifest.get("kind") if isinstance(manifest, dict) else None


def _show_futures_run(run_dir: Path, *, json_output: bool) -> int:
    """The futures-run document on stdout: JSON with ``--json``, a short rendering otherwise."""
    from typing import cast

    from crucible.experiments.futures_document import futures_document

    doc = futures_document(run_dir)
    if json_output:
        machine.emit(doc)
        return 0
    # the document is a JSON-ready dict; the rendering reads these four keys of it
    metrics = cast("dict[str, dict[str, object]]", doc["metrics"])
    headline = cast("list[str]", doc["headline"])
    verdict = cast("dict[str, object]", doc["verdict"])
    reason = cast("dict[str, object]", verdict["verdict_reason"])
    lines = [
        f"{doc['artifact_id']}  ({doc['experiment_id']})",
        f"artifacts: {doc['run_dir']}",
        f"run: {doc['run_name']} (family {doc['trial_family']}, trial {doc['trial_count']})",
        f"window: {cast('dict[str, object]', doc['window'])['start']}.."
        f"{cast('dict[str, object]', doc['window'])['end']}",
        FUTURES_VERDICT_LINE,
        f"reason: {reason['code']}",
    ]
    for name in headline:
        lines.append(f"{name}: {metrics[name]['value']} {metrics[name]['unit']}")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def _cmd_futures(args: argparse.Namespace) -> int:
    """``crucible futures run|check``: one futures config in, one sealed artifact out (ADR-0095).

    ``check`` loads and validates the config only: no store is touched, so it answers "is this
    config valid, and what does the run's identity cover" before any data is read.

    ``run`` writes the artifact and prints the futures-run document (``--json``) or a short
    headline plus the verdict line (ADR-0097). ``--home`` makes the artifacts root its
    ``experiments/`` folder and defaults ``--store`` to its ``data/`` folder (ADR-0068).
    """
    import json

    from crucible.experiments.futures_config import (
        canonical_futures_yaml,
        futures_config_hash,
        load_futures_config,
    )

    config = load_futures_config(Path(args.config))
    if args.futures_command == "check":
        config_hash = futures_config_hash(config)
        if args.json:
            machine.emit(
                {
                    "kind": "futures_run_config",
                    "config_hash": config_hash,
                    "config": config.model_dump(mode="json"),
                }
            )
            return 0
        sys.stdout.write(canonical_futures_yaml(config))
        sys.stdout.write(f"config hash: {config_hash}\n")
        return 0

    from crucible.experiments.futures_document import futures_document
    from crucible.experiments.futures_run import run_futures

    artifacts_root = _artifacts_root(args)
    store_root = _store_root(args)
    result = run_futures(
        config,
        store_root=store_root,
        artifacts_root=artifacts_root,
        overwrite=args.overwrite,
    )
    if args.json:
        machine.emit(futures_document(result.run_dir))
        return 0
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = result.summary
    lines = [
        f"run:          {result.run_id}",
        f"artifact:     {result.artifact_id}",
        f"trial:        family {config.run.family}, trial {result.trial_count} of it",
        f"window:       {config.window.start} .. {config.window.end} "
        f"({summary['trade_dates']} trade dates)",
        f"bars:         {summary['bars']}",
        f"fills:        {summary['fills']}",
        f"final:        balance {summary['final_balance_usd']} USD, "
        f"equity {summary['final_equity_usd']} USD",
        FUTURES_VERDICT_LINE,
    ]
    approximations = manifest.get("approximations") or []
    assert isinstance(approximations, list)
    for index, note in enumerate(approximations):
        lines.append(f"{'assumed:     ' if index == 0 else '             '}{note}")
    lines.append(f"run dir:      {result.run_dir}")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    """Prints a JSON Schema: the experiment config, the strategy spec or a futures-run config."""
    if args.kind == "strategy-spec":
        from crucible.strategy_spec import spec_json_schema

        schema = spec_json_schema()
    elif args.kind == "futures-run":
        from crucible.experiments.futures_config import futures_config_json_schema

        schema = futures_config_json_schema()
    elif args.kind in OUTPUT_SCHEMAS:
        schema = output_json_schema(args.kind)
    else:
        from crucible.experiments.config import config_json_schema

        schema = config_json_schema()
    text = machine.render(schema)
    if args.out:
        if not Path(args.out).parent.is_dir():
            msg = f"--out directory {Path(args.out).parent} does not exist; create it first"
            raise ConfigurationError(msg)
        Path(args.out).write_text(text, encoding="utf-8", newline=chr(10))
        sys.stdout.write(f"schema: {args.out}\n")
    else:
        sys.stdout.write(text)
    return 0


def _cmd_data(args: argparse.Namespace) -> int:
    import polars as pl

    from crucible.core.types import DatasetId, TimestampNs
    from crucible.data.calendars import get_trading_calendar
    from crucible.data.quality import run_quality_checks
    from crucible.data.store import ParquetDataStore

    store = ParquetDataStore(Path(args.store)) if hasattr(args, "store") else None
    if args.data_command == "list":
        assert store is not None
        if args.json:
            machine.emit(
                {
                    "datasets": [
                        _manifest_row(store.manifest(dataset)) for dataset in store.list_datasets()
                    ]
                }
            )
            return 0
        for dataset in store.list_datasets():
            manifest = store.manifest(dataset)
            sys.stdout.write(
                f"{dataset}  rows={manifest.row_count}  hash={manifest.content_hash[:12]}  "
                f"source={manifest.source}\n"
            )
        return 0
    if args.data_command == "check":
        assert store is not None
        frame = store.read(DatasetId(args.dataset), TimestampNs(2**63 - 1))
        bounds = frame.select(
            first=pl.col("event_time").min(), last=pl.col("event_time").max()
        ).collect()
        ran = run_quality_checks(
            frame,
            get_trading_calendar(
                args.calendar,
                start=TimestampNs(int(bounds["first"][0])),
                end=TimestampNs(int(bounds["last"][0])),
            ),
            skip=frozenset(args.skip),
            skip_reason=args.skip_reason,
        )
        if args.json:
            machine.emit({"dataset": args.dataset, "ok": True, "checks_ran": list(ran)})
            return 0
        sys.stdout.write(f"OK: {args.dataset} passed {len(ran)} checks: {', '.join(ran)}\n")
        return 0
    if args.data_command == "integrity":
        return _cmd_data_integrity(args)
    if args.data_command == "catalog":
        return _cmd_data_catalog(args)
    if args.data_command == "fetch":
        return _cmd_data_fetch(args)
    if args.data_command == "continuous":
        return _cmd_data_continuous(args)
    from crucible.data.importers.build import build_from_spec
    from crucible.experiments.config import parse_when

    start = int(parse_when(args.start)) if args.start else None
    end = int(parse_when(args.end)) if args.end else None
    _report, manifests = build_from_spec(
        Path(args.spec),
        Path(args.store),
        start=start,
        end=end,
        max_contracts=args.max_contracts,
        max_rows=args.max_rows,
    )
    if args.json:
        machine.emit({"datasets": [_manifest_row(manifest) for manifest in manifests]})
        return 0
    for manifest in manifests:
        sys.stdout.write(
            f"{manifest.dataset}  rows={manifest.row_count}  hash={manifest.content_hash[:12]}  "
            f"source={manifest.source}\n"
        )
    return 0


def _cmd_data_integrity(args: argparse.Namespace) -> int:
    """Integrity report of one dataset (ADR-0088). Exit 1 when a row breaks the data contract
    (``ok`` false); gaps and short sessions are findings and leave the exit code at 0."""
    from crucible.core.types import DatasetId, TimestampNs
    from crucible.data.integrity import integrity_report
    from crucible.data.store import ParquetDataStore

    store = ParquetDataStore(Path(args.store))
    report = integrity_report(
        store.read(DatasetId(args.dataset), TimestampNs(2**63 - 1)),
        bar_seconds=args.bar_seconds,
        session=args.session,
        calendar=args.calendar,
        top=args.top,
    )
    exit_code = 0 if report["ok"] else 1
    if args.json:
        machine.emit({"dataset": args.dataset, **report})
        return exit_code
    symbols = report["symbols"]
    assert isinstance(symbols, list)
    sys.stdout.write(
        f"{args.dataset}: {'OK' if report['ok'] else 'CONTRACT VIOLATIONS'} "
        f"({len(symbols)} symbols, session rule {report['session_rule']}); "
        f"errors {report['errors']}\n"
    )
    for sym in symbols:
        sys.stdout.write(
            f"  {sym['symbol']}: {sym['rows']} bars, {sym['sessions']} sessions, "
            f"{sym['missing_minutes']} missing minutes in {sym['sessions_with_gaps']} sessions "
            f"(largest hole {sym['largest_gap_minutes']} min), {sym['short_sessions']} short, "
            f"{sym['weekend_sessions']} weekend\n"
        )
    return exit_code


class _FuturesRunSupport(TypedDict):
    """Whether `crucible futures run` can run a root from this store, and why not."""

    supported: bool
    reasons: list[str]


def _futures_run_support(store_root: Path) -> dict[str, _FuturesRunSupport]:
    """Per CME root, whether a futures run could read this store (ADR-0097, part 5).

    A root is supported when it has a CME session calendar, a contract specification and the four
    default v3 datasets of the continuous build in the store. Computed here, in the CLI, because
    the default dataset names live in ``experiments.futures_config.default_datasets`` and
    ``crucible.data`` must not import ``crucible.experiments`` (docs/ARCHITECTURE.md, layering
    rule). The roots are the contract-spec table's: those are the roots Crucible can simulate.
    """
    from crucible.data.continuous import calendar_for
    from crucible.data.futures_specs import SPEC_TABLE, futures_spec
    from crucible.data.store import ParquetDataStore
    from crucible.experiments.futures_config import default_datasets

    present = {str(name) for name in ParquetDataStore(store_root).list_datasets()}
    support: dict[str, _FuturesRunSupport] = {}
    for root in sorted({spec.root for spec in SPEC_TABLE}):
        reasons: list[str] = []
        try:
            calendar_for(root)
        except CrucibleError as exc:
            reasons.append(f"no CME session calendar: {exc}")
        try:
            futures_spec(root)
        except CrucibleError as exc:
            reasons.append(f"no contract specification: {exc}")
        missing = sorted(name for name in default_datasets(root).values() if name not in present)
        if missing:
            reasons.append(f"missing datasets: {', '.join(missing)}")
        support[root] = {"supported": not reasons, "reasons": reasons}
    return support


def _cmd_data_catalog(args: argparse.Namespace) -> int:
    """The dataset registry of a store (ADR-0089). Exit 1 when an entry has an error (a manifest
    that disagrees with its data file); stale lineage and superseded builders are findings.

    It also answers "which CME roots can `crucible futures run` read from this store", per root
    (ADR-0097): a calendar, a contract spec and the four default v3 datasets.
    """
    from crucible.core.types import DatasetId
    from crucible.data.catalog import dataset_catalog
    from crucible.data.store import ParquetDataStore

    support = _futures_run_support(Path(args.store))
    catalog = dataset_catalog(
        ParquetDataStore(Path(args.store)),
        datasets=[DatasetId(d) for d in args.dataset] or None,
        verify=args.verify,
        top=args.top,
    )
    catalog["futures_run"] = support
    exit_code = 0 if catalog["ok"] else 1
    if args.json:
        machine.emit(catalog)
        return exit_code
    entries = catalog["datasets"]
    assert isinstance(entries, list)
    for entry in entries:
        span = entry["range"] or {}
        sys.stdout.write(
            f"{entry['dataset']}  {'OK' if entry['ok'] else 'ERROR'}  {entry['contract']}  "
            f"rows={entry['rows']}  hash={str(entry['content_hash'])[:12]}  "
            f"{span.get('first')}..{span.get('last')}  symbols={span.get('symbols')}  "
            f"origin={entry['root_origin']}\n"
        )
        for line in [*entry["errors"], *entry["findings"]]:
            sys.stdout.write(f"    {line}\n")
    for root, status in support.items():
        if status["supported"]:
            sys.stdout.write(f"futures run {root}: supported\n")
        else:
            sys.stdout.write(
                f"futures run {root}: not supported ({'; '.join(status['reasons'])})\n"
            )
    return exit_code


def _cmd_data_continuous(args: argparse.Namespace) -> int:
    """Raw per-contract bars -> unadjusted, ratio-adjusted and rolls datasets, per root
    (ADR-0086). Nothing is written for a root whose build refuses; roots before it are kept."""
    from crucible.core.errors import ConfigurationError
    from crucible.data.continuous import RollParams, build_continuous_datasets

    roots = [r.strip().upper() for r in str(args.roots).split(",") if r.strip()]
    if not roots:
        msg = "--roots is empty; pass roots such as es,nq,ym,rty,nkd"
        raise ConfigurationError(msg)
    if "{root}" not in args.raw:
        msg = f"--raw {args.raw!r} must contain {{root}} (default {{root}}_1m_raw)"
        raise ConfigurationError(msg)
    params = RollParams(threshold=args.threshold, backstop_sessions=args.backstop_sessions)
    reports: list[dict[str, object]] = []
    for root in roots:
        series, manifests = build_continuous_datasets(
            Path(args.store),
            root,
            raw_dataset=args.raw.format(root=root.lower()),
            params=params,
            trim_to_calendar=args.trim_to_calendar,
        )
        reports.append(
            {**series.summary(), "datasets": [_manifest_row(manifest) for manifest in manifests]}
        )
    if args.json:
        machine.emit({"parameters": params.describe(), "roots": reports})
        return 0
    for report in reports:
        sys.stdout.write(
            f"{report['root']}: {report['rolls']} rolls {report['rolls_by_reason']}, "
            f"{report['bars']} bars, {report['sessions']} sessions, "
            f"first contract {report['first_contract']}, calendar {report['calendar']}, "
            f"trimmed {report['trimmed_rows']} raw rows\n"
        )
        datasets = report["datasets"]
        assert isinstance(datasets, list)
        for row in datasets:
            sys.stdout.write(
                f"  {row['dataset']}  rows={row['rows']}  hash={str(row['content_hash'])[:12]}\n"
            )
    return 0


def _cmd_data_fetch(args: argparse.Namespace) -> int:
    """Provider -> normalized bars -> quality battery -> dataset. The key is read from the
    environment or ``.env`` by the settings object and never printed (ADR-0063)."""
    import datetime as dt

    from crucible.core.errors import ConfigurationError
    from crucible.data.importers.build import write_import_result
    from crucible.data.providers.cache import RawCache
    from crucible.data.providers.fetch import fetch_dataset
    from crucible.data.providers.registry import build_provider
    from crucible.data.providers.settings import ProviderSettings

    try:
        start = dt.date.fromisoformat(args.start)
        end = dt.date.fromisoformat(args.end)
    except ValueError as exc:
        msg = f"--start and --end must be dates like 2024-01-31 ({exc})"
        raise ConfigurationError(msg) from None
    settings = ProviderSettings.load()
    name = args.provider or settings.default_provider()
    cache = RawCache(None if args.no_cache else Path(args.cache_dir), refresh=args.refresh)
    provider = build_provider(
        name, settings, calendar=args.calendar, ohlc_repair=args.ohlc_repair, cache=cache
    )
    result = fetch_dataset(
        provider,
        symbols=args.symbols.split(","),
        start=start,
        end=end,
        interval=args.interval,
        price_basis=args.price_basis,
        dataset=args.dataset,
        calendar=args.calendar,
        allow_partial=args.allow_partial,
    )
    manifests = write_import_result(result, Path(args.store), max_rows=args.max_rows)
    extra = result.report.extra
    warnings: list[str] = []
    if "failed_symbols" in extra:
        warnings.append(f"failed symbols: {extra['failed_symbols']}")
    for key, value in extra.items():
        symbol = key.split(":", 1)[-1]
        if key.startswith("early_end:"):
            warnings.append(f"{symbol} has no bars after {value}, earlier than --end")
        if key.startswith("late_start:"):
            warnings.append(f"{symbol} has no bars before {value}, later than --start")
    if args.json:
        failed = [s for s in str(extra.get("failed_symbols", "")).split(",") if s]
        machine.emit(
            {
                "datasets": [_manifest_row(manifest) for manifest in manifests],
                "failed_symbols": failed,
                "warnings": warnings,
            }
        )
        return 0
    for manifest in manifests:
        sys.stdout.write(
            f"{manifest.dataset}  rows={manifest.row_count}  hash={manifest.content_hash[:12]}  "
            f"source={manifest.source}\n"
        )
    for warning in warnings:
        sys.stderr.write(f"warning: {warning}\n")
    return 0


def _use_utf8_console() -> None:
    """Prints never crash on a legacy Windows code page (cp1252 cannot encode a table's box
    characters, or a ticker's accent): stdout and stderr are UTF-8, unencodable text is replaced."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    _use_utf8_console()
    args = build_parser().parse_args(argv)

    if args.command is None:
        build_parser().print_help()
        return 0

    try:
        product_exit = product_commands.dispatch(args.command, args)
        if product_exit is not None:
            return product_exit
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "run-vectorized":
            return _cmd_run_vectorized(args)
        if args.command == "promote":
            return _cmd_promote(args)
        if args.command == "report":
            return _cmd_report(args)
        if args.command == "debug":
            return _cmd_debug(args)
        if args.command == "optimize":
            return _cmd_optimize(args)
        if args.command == "walk-forward":
            return _cmd_walk_forward(args)
        if args.command == "validate":
            return _cmd_validate(args)
        if args.command == "compare":
            return _cmd_compare(args)
        if args.command == "data":
            return _cmd_data(args)
        if args.command == "schema":
            return _cmd_schema(args)
        if args.command == "futures":
            return _cmd_futures(args)
        if args.command == "artifact":
            return _cmd_artifact(args)
    except CrucibleError as exc:
        sys.stderr.write(f"refused: {exc}\n")
        if getattr(args, "json", False):
            machine.emit(machine.error_payload(exc, command=str(args.command)))
        return 1

    build_parser().error(f"unknown command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
