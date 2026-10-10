"""Crucible CLI entry point.

Implemented: ``run`` (with ``--runtime backtest|paper|live``), ``run-vectorized``,
``report``, ``debug``, ``optimize``, ``validate``, ``compare``, ``schema``,
``data check|list|build``. ``--json`` and ``--override`` are described in ADR-0059.
"""

from __future__ import annotations

import argparse
import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from crucible import __version__
from crucible.cli import machine
from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.experiments.optimize import DEFAULT_PBO_GROUPS

if TYPE_CHECKING:
    from collections.abc import Sequence

    from crucible.core.types import TimestampNs
    from crucible.data.interfaces import DatasetManifest


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
    _add_json(run)
    _add_override(run)
    run_vec = subparsers.add_parser(
        "run-vectorized", help="Run an experiment on the vectorized engine (Levels 0-1)"
    )
    run_vec.add_argument("config", help="Path to a vectorized experiment YAML")
    run_vec.add_argument("--artifacts", default="experiments")
    _add_json(run_vec)
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

    schema = subparsers.add_parser(
        "schema", help="Print the JSON Schema of the experiment config (every valid field)"
    )
    schema.add_argument("--out", default=None, help="Write the schema here (default: stdout)")

    data = subparsers.add_parser("data", help="Dataset tooling: check | build | list")
    data_sub = data.add_subparsers(dest="data_command", required=True)
    check = data_sub.add_parser("check", help="Run quality checks on a dataset")
    check.add_argument("--store", required=True, help="Data store root")
    check.add_argument("--dataset", required=True)
    check.add_argument("--calendar", required=True, help="exchange_calendars name or '24/7'")
    check.add_argument(
        "--skip", action="append", default=[], help="quality check to skip (repeatable)"
    )
    check.add_argument("--skip-reason", default="", help="why the checks are skipped (required)")
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
        choices=["refuse", "clamp"],
        help="what to do with a bar whose high/low do not bound its open/close",
    )
    fetch.add_argument(
        "--max-rows",
        type=_positive_int,
        default=5_000_000,
        help="refuse to write more rows than this",
    )
    _add_json(fetch)

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
    )
    if args.json:
        machine.emit(machine.run_payload(artifacts))
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
    artifacts = run_vectorized_experiment(config, Path(args.artifacts))
    if args.json:
        machine.emit(machine.run_payload(artifacts))
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
                },
                "best": {
                    "experiment_id": result.best_experiment_id,
                    "dsr": result.best_dsr.dsr,
                    "benchmark_sharpe": result.best_dsr.benchmark_sharpe,
                },
            }
        )
        return 0
    for value, exp_id, metric_value in zip(
        result.values, result.experiment_ids, result.metric_values, strict=True
    ):
        sys.stdout.write(f"{args.param}={value}: {exp_id} {args.metric}={metric_value:.6g}\n")
    sys.stdout.write(
        f"PBO: {result.pbo.pbo:.4f} "
        f"(n_combinations={result.pbo.n_combinations}, n_trials={result.pbo.n_trials})\n"
    )
    sys.stdout.write(
        f"best: {result.best_experiment_id} DSR={result.best_dsr.dsr:.4f} "
        f"(benchmark_sharpe={result.best_dsr.benchmark_sharpe:.4f})\n"
    )
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


def _cmd_schema(args: argparse.Namespace) -> int:
    """Prints the experiment config's JSON Schema: what a valid config may contain."""
    from crucible.experiments.config import config_json_schema

    text = machine.render(config_json_schema())
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
    if args.data_command == "fetch":
        return _cmd_data_fetch(args)
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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command is None:
        build_parser().print_help()
        return 0

    try:
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
        if args.command == "validate":
            return _cmd_validate(args)
        if args.command == "compare":
            return _cmd_compare(args)
        if args.command == "data":
            return _cmd_data(args)
        if args.command == "schema":
            return _cmd_schema(args)
    except CrucibleError as exc:
        sys.stderr.write(f"refused: {exc}\n")
        if getattr(args, "json", False):
            machine.emit(machine.error_payload(exc))
        return 1

    build_parser().error(f"unknown command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
