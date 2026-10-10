"""The product commands: ``backtest``, ``spec`` and ``config`` (ADR-0068).

Handlers stay thin: they turn arguments into a ``BacktestRequest`` (or a spec) and print what the
product layer returns. Every command has ``--json``; the text form is for people at a terminal.
"""

from __future__ import annotations

import argparse
import sys

from crucible.cli import machine


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", action="store_true", help="print one JSON document instead of text"
    )


def _add_rule_options(parser: argparse.ArgumentParser) -> None:
    """The inline rule: an alternative to ``--spec FILE`` for the common cases."""
    parser.add_argument("--spec", default=None, help="Path to a strategy spec (YAML or JSON)")
    parser.add_argument(
        "--entry", default=None, help='Inline long entry, e.g. "sma(10) crosses_above sma(30)"'
    )
    parser.add_argument(
        "--exit",
        dest="exit_rule",
        default=None,
        help='Inline long exit, e.g. "sma(10) crosses_below sma(30)"',
    )
    parser.add_argument("--short-entry", default=None, help="Inline short entry (long_short only)")
    parser.add_argument("--short-exit", default=None, help="Inline short exit (long_short only)")
    parser.add_argument("--direction", choices=["long_only", "long_short"], default="long_only")
    parser.add_argument(
        "--fraction",
        type=float,
        default=None,
        help="use only this fraction (0-1) of the capital instead of all of it",
    )
    parser.add_argument("--stop-loss-pct", type=float, default=None, help="stop loss, in percent")
    parser.add_argument(
        "--take-profit-pct", type=float, default=None, help="take profit, in percent"
    )
    parser.add_argument("--max-holding-bars", type=int, default=None)
    parser.add_argument("--name", default=None, help="a label for the strategy")


def add_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    backtest = subparsers.add_parser(
        "backtest",
        help="One step: fetch data if needed, run a strategy spec, compare with buy-and-hold",
        description=(
            "Backtests a strategy spec (a file, or an inline rule) on one or more symbols. "
            "Downloads the prices if they are not stored, runs the quality checks, the backtest, "
            "a buy-and-hold benchmark and a shuffled-returns test, and writes a readable report."
        ),
    )
    _add_rule_options(backtest)
    backtest.add_argument("--symbols", required=True, help="Comma-separated tickers, e.g. SPY")
    backtest.add_argument("--start", required=True, help="First date, YYYY-MM-DD")
    backtest.add_argument("--end", required=True, help="Last date, YYYY-MM-DD (in the past)")
    backtest.add_argument("--capital", type=float, default=100_000.0, help="Starting capital")
    backtest.add_argument(
        "--costs", default=None, help="Cost preset: none | standard (default) | conservative"
    )
    backtest.add_argument("--slippage-bps", type=float, default=None)
    backtest.add_argument("--commission-bps", type=float, default=None)
    backtest.add_argument("--provider", default=None, help="yfinance (default) or tiingo")
    backtest.add_argument(
        "--price-basis",
        default="adjusted",
        help="only 'adjusted' (splits and dividends included) is available in one step",
    )
    backtest.add_argument("--calendar", default="XNYS", help="exchange_calendars name or '24/7'")
    backtest.add_argument(
        "--offline", action="store_true", help="never download; use stored data or refuse"
    )
    backtest.add_argument(
        "--null-iterations",
        type=int,
        default=100,
        help="shuffled-returns test size (0 turns it off)",
    )
    backtest.add_argument("--family", default=None, help="trial-counting family (default: auto)")
    backtest.add_argument(
        "--realism-check",
        action="store_true",
        help="also re-run on the event-driven engine with a spread and latency (about 30 s)",
    )
    backtest.add_argument(
        "--home",
        default=None,
        help="Crucible home folder (data, runs, cache); see `crucible config`",
    )
    _add_json(backtest)

    spec = subparsers.add_parser("spec", help="Work with strategy specs: check | templates")
    spec_sub = spec.add_subparsers(dest="spec_command", required=True)
    check = spec_sub.add_parser("check", help="Validate a spec and read it back in plain language")
    _add_rule_options(check)
    _add_json(check)
    templates = spec_sub.add_parser("templates", help="List ready-made specs to start from")
    templates.add_argument("--name", default=None, help="Print one template in full")
    _add_json(templates)

    results = subparsers.add_parser("results", help="List earlier one-step backtests, newest first")
    results.add_argument("--home", default=None)
    results.add_argument("--limit", type=int, default=20)
    _add_json(results)

    config = subparsers.add_parser("config", help="Where Crucible keeps its data and runs")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    show = config_sub.add_parser("show", help="Print the resolved home folder and its subfolders")
    show.add_argument("--home", default=None)
    _add_json(show)
    set_home = config_sub.add_parser("set-home", help="Remember a home folder for every run")
    set_home.add_argument("path")
    _add_json(set_home)


def _spec_from_args(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    from crucible.core.errors import ConfigurationError
    from crucible.strategy_spec import load_spec, parse_spec

    inline = any(
        getattr(args, key) is not None
        for key in (
            "entry",
            "exit_rule",
            "short_entry",
            "short_exit",
            "fraction",
            "stop_loss_pct",
            "take_profit_pct",
            "max_holding_bars",
        )
    )
    if args.spec and inline:
        msg = "give either --spec FILE or the inline rule options (--entry, --exit, ...), not both"
        raise ConfigurationError(msg)
    if args.spec:
        return load_spec(args.spec)
    if not inline:
        msg = (
            "no strategy given: pass --spec FILE, or an inline rule such as "
            '--entry "sma(10) crosses_above sma(30)" --exit "sma(10) crosses_below sma(30)". '
            "`crucible spec templates` lists ready-made specs"
        )
        raise ConfigurationError(msg)
    raw: dict[str, object] = {"direction": args.direction, "entry": {}, "exit": {}}
    entry: dict[str, object] = {}
    leave: dict[str, object] = {}
    if args.entry is not None:
        entry["long"] = args.entry
    if args.short_entry is not None:
        entry["short"] = args.short_entry
    if args.exit_rule is not None:
        leave["long"] = args.exit_rule
    if args.short_exit is not None:
        leave["short"] = args.short_exit
    raw["entry"], raw["exit"] = entry, leave
    if args.name:
        raw["name"] = args.name
    if args.fraction is not None:
        raw["sizing"] = {"type": "fixed_fraction", "fraction": args.fraction}
    risk = {
        key: value
        for key, value in (
            ("stop_loss_pct", args.stop_loss_pct),
            ("take_profit_pct", args.take_profit_pct),
            ("max_holding_bars", args.max_holding_bars),
        )
        if value is not None
    }
    if risk:
        raw["risk"] = risk
    return parse_spec(raw)


def _print_backtest(doc: dict[str, object]) -> None:
    summary = doc["summary"]
    assert isinstance(summary, dict)
    results = doc["results"]
    assert isinstance(results, dict)
    s, b = results["strategy"], results["benchmark"]
    assert isinstance(s, dict)
    assert isinstance(b, dict)
    out = sys.stdout.write
    out(f"{summary['headline']}\n\n")
    out(f"Verdict: {summary['verdict']}\n\n")
    rows = [
        ("", "Strategy", "Buy and hold"),
        ("Final value", f"${s['final_equity']:,.0f}", f"${b['final_equity']:,.0f}"),
        ("Return per year", f"{s['cagr_pct']:.1f}%", f"{b['cagr_pct']:.1f}%"),
        ("Worst fall", f"{s['max_drawdown_pct']:.1f}%", f"{b['max_drawdown_pct']:.1f}%"),
        (
            "Sharpe (95% range)",
            f"{s['sharpe']:.2f} ({s['sharpe_low']:.2f} to {s['sharpe_high']:.2f})",
            f"{b['sharpe']:.2f} ({b['sharpe_low']:.2f} to {b['sharpe_high']:.2f})",
        ),
        ("Trades", str(s["n_trades"]), "-"),
    ]
    for label, left, right in rows:
        out(f"  {label:<20}{left:<28}{right}\n")
    flags = summary["flags"]
    assert isinstance(flags, list)
    if flags:
        out("\nWarnings:\n")
        for flag in flags:
            out(f"  - {flag['text']}\n")
    out(f"\nReport:    {doc['report']}\n")
    out(f"Artifacts: {doc['artifacts']}\n")
    out(f"Experiment {doc['experiment_id']}\n")


def run_backtest_command(args: argparse.Namespace) -> int:
    from crucible.product.backtest import BacktestRequest, run_backtest

    spec = _spec_from_args(args)
    doc = run_backtest(
        BacktestRequest(
            spec=spec,
            symbols=args.symbols.split(","),
            start=args.start,
            end=args.end,
            capital=args.capital,
            cost_preset=args.costs,
            slippage_bps=args.slippage_bps,
            commission_bps=args.commission_bps,
            provider=args.provider,
            price_basis=args.price_basis,
            calendar=args.calendar,
            offline=args.offline,
            null_iterations=args.null_iterations,
            family=args.family,
            realism_check=args.realism_check,
            home=args.home,
        )
    )
    if args.json:
        machine.emit(doc)
    else:
        _print_backtest(doc)
    return 0


def run_spec_command(args: argparse.Namespace) -> int:
    from crucible.core.errors import ConfigurationError
    from crucible.strategy_spec import canonical_spec, describe_spec, warmup_bars
    from crucible.strategy_spec.templates import TEMPLATES

    if args.spec_command == "templates":
        if args.name is not None:
            if args.name not in TEMPLATES:
                msg = f"no template named {args.name!r}; choose one of {', '.join(TEMPLATES)}"
                raise ConfigurationError(msg)
            template = TEMPLATES[args.name]
            if args.json:
                machine.emit({"name": args.name, **template.as_dict()})
            else:
                import yaml

                sys.stdout.write(f"# {template.title}: {template.summary}\n")
                sys.stdout.write(yaml.safe_dump(template.spec, sort_keys=False))
            return 0
        listing = [{"name": n, **t.as_dict(include_spec=False)} for n, t in TEMPLATES.items()]
        if args.json:
            machine.emit({"templates": listing})
        else:
            for item in listing:
                sys.stdout.write(f"{item['name']:<22}{item['summary']}\n")
        return 0

    spec = _spec_from_args(args)
    document: dict[str, object] = {
        "valid": True,
        "spec": canonical_spec(spec),
        "explained": describe_spec(spec),
        "bars_of_history_needed": warmup_bars(spec),
    }
    if args.json:
        machine.emit(document)
    else:
        sys.stdout.write("The spec is valid. This is what it does:\n")
        for line in describe_spec(spec):
            sys.stdout.write(f"  - {line}\n")
        sys.stdout.write(f"It needs {warmup_bars(spec)} bars of history before it can act.\n")
    return 0


def run_config_command(args: argparse.Namespace) -> int:
    from crucible.product.home import HOME_ENV, resolve_home, set_home, settings_path

    if args.config_command == "set-home":
        home = set_home(args.path)
        document: dict[str, object] = {"home": str(home), "settings_file": str(settings_path())}
        if args.json:
            machine.emit(document)
        else:
            sys.stdout.write(f"Home folder set to {home}\n(remembered in {settings_path()})\n")
        return 0
    import importlib.util
    import os

    from crucible import __version__

    home_obj = resolve_home(args.home)
    document = {
        "version": __version__,
        "providers": {
            "yfinance": {"installed": importlib.util.find_spec("yfinance") is not None},
            "tiingo": {"api_key_set": bool(os.environ.get("TIINGO_API_KEY"))},
        },
        "home": str(home_obj.root),
        "data": str(home_obj.data),
        "experiments": str(home_obj.experiments),
        "cache": str(home_obj.cache),
        "settings_file": str(settings_path()),
        "environment_variable": HOME_ENV,
    }
    if args.json:
        machine.emit(document)
    else:
        for key, value in document.items():
            if not isinstance(value, dict):
                sys.stdout.write(f"{key:<22}{value}\n")
    return 0


def run_results_command(args: argparse.Namespace) -> int:
    import json

    from crucible.product.home import resolve_home

    home = resolve_home(args.home)
    rows: list[dict[str, object]] = []
    for path in home.experiments.glob("EXP-*/summary.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            s, b = doc["results"]["strategy"], doc["results"]["benchmark"]
            rows.append(
                {
                    "experiment_id": doc["experiment_id"],
                    "strategy": doc["request"]["strategy_name"],
                    "symbols": doc["request"]["symbols"],
                    "start": doc["request"]["start"],
                    "end": doc["request"]["end"],
                    "cagr_pct": s["cagr_pct"],
                    "benchmark_cagr_pct": b["cagr_pct"],
                    "n_trades": s["n_trades"],
                    "verdict_level": doc["summary"]["verdict_level"],
                    "report": str(path.with_name("summary.html")),
                    "modified": path.stat().st_mtime,
                }
            )
        except (OSError, ValueError, KeyError):
            continue  # an artifact folder of another kind (or an older format): not listed
    rows.sort(key=lambda r: (-float(str(r["modified"])), str(r["experiment_id"])))
    shown = [{k: v for k, v in r.items() if k != "modified"} for r in rows[: args.limit]]
    if args.json:
        machine.emit({"home": str(home.root), "results": shown, "total": len(rows)})
        return 0
    for r in shown:
        names = ",".join(str(x) for x in r["symbols"])  # type: ignore[attr-defined]
        sys.stdout.write(
            f"{r['experiment_id']}  {r['strategy']}  {names}  {r['start']}..{r['end']}  "
            f"{float(str(r['cagr_pct'])):.1f}%/yr vs {float(str(r['benchmark_cagr_pct'])):.1f}%  "
            f"{r['verdict_level']}\n"
        )
    if not shown:
        sys.stdout.write("no backtests yet; run `crucible backtest ...`\n")
    return 0


def dispatch(command: str, args: argparse.Namespace) -> int | None:
    """The exit code if ``command`` is a product command, else ``None``."""
    if command == "backtest":
        return run_backtest_command(args)
    if command == "spec":
        return run_spec_command(args)
    if command == "config":
        return run_config_command(args)
    if command == "results":
        return run_results_command(args)
    return None
