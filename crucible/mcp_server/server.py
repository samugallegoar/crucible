"""The Crucible MCP server (ADR-0066, ADR-0068): Crucible's commands as tools, over stdio.

Install it with ``uv tool install`` / ``uvx`` (see the README) and start it with ``crucible-mcp`` or
``python -m crucible.mcp_server``. Every tool runs the matching CLI command in a fresh process,
so its result is the command's ``--json`` document (metrics with CI, trial count, DSR/PBO and
realism level together, AGENTS.md section 9) and its refusals are the command's actionable
messages.

Operational rules, stated once:

* Tools are async. A call the client cancels, or that exceeds the timeout
  (``CRUCIBLE_MCP_TIMEOUT`` seconds, default 900), kills its child process.
* Every path argument is made absolute against ``CRUCIBLE_WORKDIR`` (default: the server's working
  directory) before the command sees it, and the command runs in that directory. Paths in results
  are absolute. Defaults for ``artifacts`` and ``store`` are inside the Crucible home folder
  (``crucible_status`` shows it; ``CRUCIBLE_HOME`` or ``crucible config set-home`` changes it), so
  nothing depends on how the client launched the server.
* The server has the permissions of the user who started it; it does not sandbox paths.
"""

from __future__ import annotations

import json
import os
import sys
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from crucible.core.errors import ConfigurationError
from crucible.mcp_server.invoke import ToolRefusal, ainvoke

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mcp.server.mcpserver import MCPServer

__all__ = ["INSTRUCTIONS", "build_argv", "build_server", "main"]

INSTRUCTIONS = (
    "Crucible backtests a trading idea honestly: it compares it with buy-and-hold, attaches "
    "confidence intervals, counts every variant tried and says in words when the evidence is "
    "weak. When a person describes a strategy, read the resource crucible://guide (or use the "
    "prompt backtest_a_strategy) and then call crucible_backtest: it needs no files and no code. "
    "Never claim a strategy works; report the summary's verdict and its flags. A refusal is an "
    "error whose message says what to fix. Use absolute paths."
)

Option = str | bool | list[str] | None
DEFAULT_TIMEOUT = 900.0


def build_argv(
    command: str | Sequence[str], positionals: Sequence[str], options: Mapping[str, Option]
) -> list[str]:
    """``crucible <command> --name=value ... -- <positionals>``.

    A value is attached to its flag with ``=`` and positionals follow ``--``, so a hostile value
    (``--resume=x``) can only ever be a value, never a flag. ``None`` skips an option, ``True`` adds
    a bare flag, a list repeats the flag. Underscores in a name become hyphens.
    """
    argv = [command] if isinstance(command, str) else list(command)
    for name, value in options.items():
        flag = "--" + name.replace("_", "-")
        if value is None or value is False:
            continue
        if value is True:
            argv.append(flag)
        elif isinstance(value, str):
            argv.append(f"{flag}={value}")
        else:
            argv.extend(f"{flag}={item}" for item in value)
    if positionals:
        argv.append("--")
        argv.extend(positionals)
    return argv


def workdir() -> Path:
    """The directory relative path arguments are resolved against."""
    return Path(os.environ.get("CRUCIBLE_WORKDIR") or Path.cwd()).expanduser().resolve()


def absolute(path: str | None) -> str | None:
    """``path`` made absolute against :func:`workdir` (``None`` stays ``None``)."""
    if path is None:
        return None
    candidate = Path(path).expanduser()
    return str(candidate if candidate.is_absolute() else workdir() / candidate)


def _timeout() -> float:
    raw = os.environ.get("CRUCIBLE_MCP_TIMEOUT")
    try:
        return float(raw) if raw else DEFAULT_TIMEOUT
    except ValueError:
        return DEFAULT_TIMEOUT


def _text(value: float | int | None) -> str | None:
    return None if value is None else str(value)


def _rule_options(
    spec: dict[str, Any] | str | None,
    *,
    entry: str | None,
    exit: str | None,
    short_entry: str | None,
    short_exit: str | None,
    direction: str,
    fraction: float | None,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
    max_holding_bars: int | None,
    name: str | None,
    flat_by_close: bool = False,
    entry_window: str | None = None,
    market_on_close: bool = False,
    exit_at: str | None = None,
) -> dict[str, Option]:
    """The strategy part of ``backtest`` / ``spec check``: a spec (object or text) or the inline
    rule options; ``direction`` only applies to an inline rule."""
    spec_text = json.dumps(spec, sort_keys=True) if isinstance(spec, dict) else spec
    return {
        "spec": spec_text,
        "entry": entry,
        "exit": exit,
        "short_entry": short_entry,
        "short_exit": short_exit,
        "direction": direction if spec_text is None else None,
        "fraction": _text(fraction),
        "stop_loss_pct": _text(stop_loss_pct),
        "take_profit_pct": _text(take_profit_pct),
        "max_holding_bars": _text(max_holding_bars),
        "flat_by_close": flat_by_close,
        "market_on_close": market_on_close,
        "exit_at": exit_at,
        "entry_window": entry_window,
        "name": name,
    }


def guide_text() -> str:
    """The agent guide: the packaged resource in an installed wheel (the build copies the root
    ``AGENT_GUIDE.md`` into ``crucible/product/``), else the root file of a source checkout."""
    packaged = resources.files("crucible.product").joinpath("AGENT_GUIDE.md")
    if packaged.is_file():
        return packaged.read_text("utf-8")
    return (Path(__file__).resolve().parents[2] / "AGENT_GUIDE.md").read_text("utf-8")


def _home_paths() -> tuple[str, str, str]:
    """``(experiments, data, cache)`` of the Crucible home, absolute."""
    from crucible.product.home import resolve_home

    home = resolve_home(None)
    return str(home.experiments), str(home.data), str(home.cache)


def build_server() -> MCPServer:
    """The server with every tool registered.

    Raises ``ConfigurationError`` if the ``mcp`` package (2.x) is not installed."""
    try:
        from mcp.server.mcpserver import MCPServer
        from mcp.server.mcpserver.exceptions import ToolError
    except ImportError:
        msg = (
            "the MCP server needs the 'mcp' package, version 2.3 or newer (2.x): reinstall "
            "Crucible (`uv tool install --reinstall ...`) or run `uv sync` (it is a core "
            "dependency)"
        )
        raise ConfigurationError(msg) from None

    server = MCPServer("crucible", instructions=INSTRUCTIONS)

    async def run_cli(argv: Sequence[str]) -> dict[str, object]:
        """The CLI's document, or a tool error carrying the CLI's own message (the SDK shows the
        model only an anticipated ``ToolError``'s text)."""
        try:
            return await ainvoke(argv, timeout=_timeout(), cwd=workdir())
        except ToolRefusal as refusal:
            raise ToolError(str(refusal)) from refusal

    # ----------------------------------------------------------------- the product tools

    @server.resource("crucible://guide", mime_type="text/markdown", name="crucible_agent_guide")
    def guide_resource() -> str:
        """How to turn a person's strategy description into a backtest and report it honestly."""
        return guide_text()

    @server.prompt(name="backtest_a_strategy")
    def backtest_prompt(idea: str = "") -> str:
        """Test a trading idea described in plain language, following the Crucible guide."""
        return (
            "Follow this guide exactly to backtest the person's idea with Crucible, then answer "
            "in plain language.\n\n"
            f"The person's idea: {idea or '(ask them)'}\n\n{guide_text()}"
        )

    @server.tool()
    async def crucible_backtest(
        symbols: str,
        start: str,
        end: str,
        spec: dict[str, Any] | str | None = None,
        entry: str | None = None,
        exit: str | None = None,
        short_entry: str | None = None,
        short_exit: str | None = None,
        direction: Literal["long_only", "long_short"] = "long_only",
        fraction: float | None = None,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        max_holding_bars: int | None = None,
        flat_by_close: bool = False,
        market_on_close: bool = False,
        exit_at: str | None = None,
        entry_window: str | None = None,
        name: str | None = None,
        capital: float = 100000.0,
        costs: Literal["none", "standard", "conservative"] | None = None,
        slippage_bps: float | None = None,
        commission_bps: float | None = None,
        provider: Literal["yfinance", "tiingo"] | None = None,
        price_basis: Literal["adjusted"] = "adjusted",
        calendar: str = "XNYS",
        interval: Literal["1d", "1h", "30m", "15m", "5m"] = "1d",
        offline: bool = False,
        null_iterations: int = 100,
        family: str | None = None,
        realism_check: bool = False,
    ) -> dict[str, object]:
        """Backtest a strategy in one step and compare it with buy-and-hold. No files or code
        needed: give the instrument(s), the period and the rule. Downloads prices if they are not
        stored (internet needed the first time), checks the data, runs the backtest, a
        buy-and-hold benchmark and a shuffled-returns test, and writes an HTML report.

        Strategy: either `spec` (an object, see crucible_strategy_templates) or the inline rule
        `entry` / `exit`, e.g. entry="sma(10) crosses_above sma(30)", exit="sma(10) crosses_below
        sma(30)". `symbols` is comma-separated (SPY or SPY,QQQ); `start`/`end` are YYYY-MM-DD and
        `end` must be in the past. `costs`: standard (default), conservative or none.
        `interval`: 1d (default) or intraday 1h/30m/15m/5m (yfinance only; Yahoo keeps about two
        years of 1h bars and about 60 days of 5-30m bars, so the window must fit). Rules count
        bars: sma(20) on 1h bars is a 20-hour average. Intraday only: `flat_by_close` closes
        every position before the session's close (nothing held overnight); add
        `market_on_close` to exit at the closing price instead of one bar early; `exit_at`
        ("12:30") closes positions from that time on; `entry_window` ("10:30-14:30") opens
        positions only on bars ending in that window; conditions can test `time`
        (`time >= 10:30`). All times are exchange time and refer to when a bar ends.
        `realism_check` (about 30 s extra) also re-runs the rules with realistic fills
        (next-bar prices, spread, latency) and reports how much of the result survives.

        Returns one document: `summary` (headline, verdict, flags in words, next steps),
        `results.strategy` and `results.benchmark` (every Sharpe with its 95% range), `validation`
        (trial count, deflated Sharpe, null test, realism level), `trades`, `strategy_explained`
        and the absolute `report` path. Tell the person `summary.verdict` and its flags; never say
        the strategy works."""
        options: dict[str, Option] = {
            **_rule_options(
                spec,
                entry=entry,
                exit=exit,
                short_entry=short_entry,
                short_exit=short_exit,
                direction=direction,
                fraction=fraction,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                max_holding_bars=max_holding_bars,
                flat_by_close=flat_by_close,
                market_on_close=market_on_close,
                exit_at=exit_at,
                entry_window=entry_window,
                name=name,
            ),
            "symbols": symbols,
            "start": start,
            "end": end,
            "capital": _text(capital),
            "costs": costs,
            "slippage_bps": _text(slippage_bps),
            "commission_bps": _text(commission_bps),
            "provider": provider,
            "price_basis": price_basis,
            "calendar": calendar,
            "interval": interval,
            "offline": offline,
            "null_iterations": _text(null_iterations),
            "family": family,
            "realism_check": realism_check,
            "json": True,
        }
        return await run_cli(build_argv("backtest", [], options))

    @server.tool()
    async def crucible_check_strategy(
        spec: dict[str, Any] | str | None = None,
        entry: str | None = None,
        exit: str | None = None,
        short_entry: str | None = None,
        short_exit: str | None = None,
        direction: Literal["long_only", "long_short"] = "long_only",
        fraction: float | None = None,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        max_holding_bars: int | None = None,
        flat_by_close: bool = False,
        market_on_close: bool = False,
        exit_at: str | None = None,
        entry_window: str | None = None,
        name: str | None = None,
    ) -> dict[str, object]:
        """Validate a strategy spec (or inline rule) without running anything and read it back in
        plain language (`explained`). Use it to confirm you understood the person's idea. A bad
        spec is refused with where the problem is and how to fix it."""
        options: dict[str, Option] = {
            **_rule_options(
                spec,
                entry=entry,
                exit=exit,
                short_entry=short_entry,
                short_exit=short_exit,
                direction=direction,
                fraction=fraction,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                max_holding_bars=max_holding_bars,
                flat_by_close=flat_by_close,
                market_on_close=market_on_close,
                exit_at=exit_at,
                entry_window=entry_window,
                name=name,
            ),
            "json": True,
        }
        return await run_cli(build_argv(["spec", "check"], [], options))

    @server.tool()
    async def crucible_strategy_templates(name: str | None = None) -> dict[str, object]:
        """Ready-made strategy specs (moving-average crossover, RSI, breakout, Bollinger,
        momentum, buy and hold, ...). Without `name` lists them; with `name` returns that spec
        in full to adapt."""
        options: dict[str, Option] = {"name": name, "json": True}
        return await run_cli(build_argv(["spec", "templates"], [], options))

    @server.tool()
    async def crucible_strategy_schema() -> dict[str, object]:
        """The JSON Schema of a strategy spec: every field, type and allowed value."""
        return await run_cli(["schema", "--kind=strategy-spec"])

    @server.tool()
    async def crucible_results(home: str | None = None, limit: int = 20) -> dict[str, object]:
        """List earlier one-step backtests (newest first): id, strategy, symbols, period, return
        against buy-and-hold, verdict and report path."""
        options: dict[str, Option] = {
            "home": absolute(home),
            "limit": str(limit),
            "json": True,
        }
        return await run_cli(build_argv("results", [], options))

    @server.tool()
    async def crucible_status(home: str | None = None) -> dict[str, object]:
        """Where Crucible keeps data, runs and cache (absolute paths), and which data provider
        is available. Call it to tell the person where their reports are."""
        options: dict[str, Option] = {"home": absolute(home), "json": True}
        return await run_cli(build_argv(["config", "show"], [], options))

    # ------------------------------------------------------- the engine's advanced commands

    @server.tool()
    async def crucible_schema() -> dict[str, object]:
        """The JSON Schema of the experiment config: every valid field and its type."""
        return await run_cli(["schema"])

    @server.tool()
    async def crucible_run(
        config: str,
        artifacts: str | None = None,
        overrides: list[str] | None = None,
        runtime: Literal["backtest", "paper", "live"] = "backtest",
    ) -> dict[str, object]:
        """Run an event-driven experiment from a YAML config. `overrides` are `PATH=VALUE` edits
        applied before validation (e.g. `strategy.params.lookback=60`). Writes the run under
        `artifacts` (default: the Crucible home). Returns the experiment id, artifact paths,
        metrics with CIs and the manifest headline (trial count, DSR, PBO, realism level,
        contamination). `live` needs `live.enabled` in the config and uses the simulated venue."""
        options: dict[str, Option] = {
            "artifacts": absolute(artifacts) or _home_paths()[0],
            "runtime": runtime,
            "override": overrides,
            "json": True,
        }
        return await run_cli(build_argv("run", [absolute(config) or config], options))

    @server.tool()
    async def crucible_run_vectorized(
        config: str, artifacts: str | None = None, overrides: list[str] | None = None
    ) -> dict[str, object]:
        """Run an experiment on the fast vectorized engine (Levels 0-1, signal-function strategies).
        A vectorized run is recorded as a trial like any other."""
        options: dict[str, Option] = {
            "artifacts": absolute(artifacts) or _home_paths()[0],
            "override": overrides,
            "json": True,
        }
        return await run_cli(build_argv("run-vectorized", [absolute(config) or config], options))

    @server.tool()
    async def crucible_validate(
        config: str,
        artifacts: str | None = None,
        factors: str | None = None,
        overrides: list[str] | None = None,
    ) -> dict[str, object]:
        """Run an experiment and add the statistical validation: DSR, contamination and, if
        `factors` (a CSV of factor returns) is given, a factor regression."""
        options: dict[str, Option] = {
            "artifacts": absolute(artifacts) or _home_paths()[0],
            "factors": absolute(factors),
            "override": overrides,
            "json": True,
        }
        return await run_cli(build_argv("validate", [absolute(config) or config], options))

    @server.tool()
    async def crucible_optimize(
        config: str,
        param: str,
        values: str,
        artifacts: str | None = None,
        metric: str = "sharpe",
        vectorized: bool = False,
        pbo_groups: int | None = None,
        workers: int | None = None,
        overrides: list[str] | None = None,
    ) -> dict[str, object]:
        """Sweep one strategy parameter (`values` is comma-separated, e.g. `40,60,80`). Every point
        is a trial; the PBO and the best point's DSR are computed over the whole sweep. The config's
        `experiment.mode` must be `optimization`."""
        options: dict[str, Option] = {
            "param": param,
            "values": values,
            "artifacts": absolute(artifacts) or _home_paths()[0],
            "metric": metric,
            "vectorized": vectorized,
            "pbo_groups": _text(pbo_groups),
            "workers": _text(workers),
            "override": overrides,
            "json": True,
        }
        return await run_cli(build_argv("optimize", [absolute(config) or config], options))

    @server.tool()
    async def crucible_promote(
        config: str,
        level: int,
        lookback: int,
        execution: str,
        out: str | None = None,
        run: bool = False,
        artifacts: str | None = None,
        overrides: list[str] | None = None,
    ) -> dict[str, object]:
        """Turn a vectorized config into an event-driven config at realism level 2-5 (`execution` is
        a YAML file of ExecutionConfig fields; `lookback` is the history the signal needs). Returns
        the promoted YAML (or the file `out` it was written to). With `run` (which needs `out`) it
        also runs the promoted config and returns the run's metrics and headline set."""
        options: dict[str, Option] = {
            "level": str(level),
            "lookback": str(lookback),
            "execution": absolute(execution),
            "out": absolute(out),
            "run": run,
            "artifacts": absolute(artifacts) or _home_paths()[0],
            "override": overrides,
            "json": True,
        }
        return await run_cli(build_argv("promote", [absolute(config) or config], options))

    @server.tool()
    async def crucible_debug(
        experiment_id: str, at: str, artifacts: str | None = None, order: str | None = None
    ) -> dict[str, object]:
        """Replay a finished experiment deterministically up to `at` (ISO date or datetime, or raw
        UTC ns) and return the engine's state there: cash, positions and orders, with the reasons an
        order was not filled. `events_total` counts the events replayed and `last_events` shows the
        final 20. Pass `order` to explain only that order id."""
        options: dict[str, Option] = {
            "at": at,
            "artifacts": absolute(artifacts) or _home_paths()[0],
            "order": order,
            "json": True,
        }
        return await run_cli(build_argv("debug", [experiment_id], options))

    @server.tool()
    async def crucible_compare(family: str, artifacts: str | None = None) -> dict[str, object]:
        """List every recorded trial of a trial family from the trial registry."""
        options: dict[str, Option] = {
            "artifacts": absolute(artifacts) or _home_paths()[0],
            "json": True,
        }
        return await run_cli(build_argv("compare", [family], options))

    @server.tool()
    async def crucible_report(
        experiment_id: str, artifacts: str | None = None
    ) -> dict[str, object]:
        """Re-render the technical report of a finished experiment and return where it is."""
        options: dict[str, Option] = {
            "artifacts": absolute(artifacts) or _home_paths()[0],
            "json": True,
        }
        return await run_cli(build_argv("report", [experiment_id], options))

    @server.tool()
    async def crucible_data_list(store: str | None = None) -> dict[str, object]:
        """List the datasets of a data store (default: the Crucible home's) with their row counts,
        content hashes and sources."""
        options: dict[str, Option] = {"store": absolute(store) or _home_paths()[1], "json": True}
        return await run_cli(build_argv(["data", "list"], [], options))

    @server.tool()
    async def crucible_data_check(
        dataset: str,
        calendar: str,
        store: str | None = None,
        skip: list[str] | None = None,
        skip_reason: str = "",
    ) -> dict[str, object]:
        """Run the data-quality battery on a dataset. Skipping a check requires a reason."""
        options: dict[str, Option] = {
            "store": absolute(store) or _home_paths()[1],
            "dataset": dataset,
            "calendar": calendar,
            "skip": skip,
            "skip_reason": skip_reason or None,
            "json": True,
        }
        return await run_cli(build_argv(["data", "check"], [], options))

    @server.tool()
    async def crucible_data_build(
        spec: str,
        store: str | None = None,
        start: str | None = None,
        end: str | None = None,
        max_contracts: int | None = None,
        max_rows: int | None = None,
    ) -> dict[str, object]:
        """Build the datasets an import spec describes into `store` (quality-checked before any
        write). `start`/`end`/`max_contracts` apply to Polymarket specs only; `max_rows` is the
        size guard."""
        options: dict[str, Option] = {
            "store": absolute(store) or _home_paths()[1],
            "start": start,
            "end": end,
            "max_contracts": _text(max_contracts),
            "max_rows": _text(max_rows),
            "json": True,
        }
        return await run_cli(build_argv(["data", "build"], [absolute(spec) or spec], options))

    @server.tool()
    async def crucible_data_fetch(
        dataset: str,
        symbols: str,
        start: str,
        end: str,
        store: str | None = None,
        provider: Literal["yfinance", "tiingo"] | None = None,
        interval: str = "1d",
        price_basis: Literal["adjusted", "raw"] = "adjusted",
        calendar: str = "XNYS",
        allow_partial: bool = False,
        cache_dir: str | None = None,
        refresh: bool = False,
        ohlc_repair: Literal["refuse", "clamp", "clamp_rounding"] = "refuse",
        max_rows: int | None = None,
    ) -> dict[str, object]:
        """Fetch prices from a free provider (yfinance by default, or tiingo with TIINGO_API_KEY set
        in the server's environment) into a dataset. This makes network requests. Dates are
        YYYY-MM-DD; `symbols` is comma-separated. Raw provider answers are cached in
        `cache_dir` (default: the Crucible home's cache; `refresh` re-fetches). The result
        lists `failed_symbols` and
        `warnings` (a symbol that started late or stopped early): read them before trusting the
        dataset. Most people want crucible_backtest, which does this itself."""
        options: dict[str, Option] = {
            "store": absolute(store) or _home_paths()[1],
            "dataset": dataset,
            "symbols": symbols,
            "start": start,
            "end": end,
            "provider": provider,
            "interval": interval,
            "price_basis": price_basis,
            "calendar": calendar,
            "allow_partial": allow_partial,
            "cache_dir": absolute(cache_dir) or _home_paths()[2],
            "refresh": refresh,
            "ohlc_repair": ohlc_repair,
            "max_rows": _text(max_rows),
            "json": True,
        }
        return await run_cli(build_argv(["data", "fetch"], [], options))

    return server


def main() -> int:
    """Serve over stdio until the client disconnects."""
    try:
        server = build_server()
    except ConfigurationError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
