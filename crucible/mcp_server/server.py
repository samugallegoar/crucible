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
            raise ToolError(refusal.tool_text()) from refusal

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
        null_iterations: int = 1_000,
        family: str | None = None,
        realism_check: bool = False,
    ) -> dict[str, object]:
        """Backtest a strategy in one step and compare it with buy-and-hold. No files or code
        needed: give the instrument(s), the period and the rule. Downloads prices if they are not
        stored (internet needed the first time), checks the data, runs the backtest, a
        buy-and-hold benchmark and a shuffled-returns test (`null_iterations`, default 1000: about
        30 seconds for ten years of daily bars; use 100 for a quick look), and writes an HTML
        report.

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

        Returns one document: `results_table.markdown` (the metric table: paste it as it is,
        never rebuild, reorder, rename, add or drop rows; a value that does not exist already
        reads `n/a`), `sequence_table.markdown` (resampled outcomes of this one history: paste it
        unchanged under the metric table; it is sequence risk, never evidence of an edge),
        `summary` (headline, verdict, flags in words, next steps),
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
    async def crucible_schema(kind: str = "experiment") -> dict[str, object]:
        """A JSON Schema: the experiment config (default, `experiment`), the strategy spec
        (`strategy-spec`), the futures-run config (`futures-run`), the futures-batch file
        (`futures-batch`), or an output document Crucible prints: `run`, `verification`, `error`,
        `manifest`, `futures-run-document`."""
        return await run_cli(build_argv("schema", [], {"kind": kind}))

    @server.tool()
    async def crucible_prop_validate(ruleset: str) -> dict[str, object]:
        """Validate a prop-firm ruleset file (`crucible prop validate`): its identity, its
        content hash, whether it is verified (only the owner can confirm one, and a synthetic
        ruleset can never be), one coverage row per rule, the evaluation status (`complete`,
        `conditional_on_modeled_rules` or `blocked`) and the warnings that follow. It changes no
        file, and no rule value is ever inferred: the rules are sourced data (ADR-0106)."""
        return await run_cli(
            build_argv(["prop", "validate"], [absolute(ruleset) or ruleset], {"json": True})
        )

    @server.tool()
    async def crucible_prop_list(
        firm: str | None = None, root: str | None = None
    ) -> dict[str, object]:
        """List every prop-firm ruleset (`crucible prop list --json`): its id, version, content
        hash, evidence counts, conflicts, unmodeled rules by materiality and verification status.
        Read-only; `crucible prop confirm` is the owner's TTY-only step and is never exposed here
        (ADR-0107 section 2)."""
        options: dict[str, Option] = {"json": True, "firm": firm, "root": absolute(root)}
        return await run_cli(build_argv(["prop", "list"], [], options))

    @server.tool()
    async def crucible_prop_schema(kind: str = "prop-ruleset") -> dict[str, object]:
        """A prop-firm JSON Schema: `prop-ruleset` (a ruleset file: identity, instruments,
        verification, phases and every rule kind) or `prop-attempt` (the attempt result: outcome,
        phases, breach, buffer, costs, payouts, rule coverage, evaluation status)."""
        return await run_cli(build_argv("schema", [], {"kind": kind}))

    @server.tool()
    async def crucible_artifact(
        artifact_id: str,
        detail: bool = False,
        verify: bool = False,
        artifacts: str | None = None,
        home: str | None = None,
    ) -> dict[str, object]:
        """Fetch a finished run by its artifact id (`ART-...`, or an `EXP-...` id): the compact
        document (ids, headline fields, every metric with its interval) by default, the full
        manifest and file list with `detail`. With `verify`, recompute the id from the files on
        disk and refuse if the artifact was edited. A futures run returns the futures-run
        document instead (ADR-0097). `home` points at a Crucible home folder; its experiments/
        folder is the artifacts root (pass it or `artifacts`, never both)."""
        options: dict[str, Option] = {"home": absolute(home), "json": True}
        if artifacts is not None:
            options["artifacts"] = absolute(artifacts)
        elif home is None:
            options["artifacts"] = _home_paths()[0]
        if verify:
            return await run_cli(build_argv(["artifact", "verify"], [artifact_id], options))
        options["detail"] = detail
        return await run_cli(build_argv(["artifact", "show"], [artifact_id], options))

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
    async def crucible_futures_run(
        config: str,
        store: str | None = None,
        artifacts: str | None = None,
        home: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Simulate one futures-run config on a continuous CME series (one root, one strategy, a
        window of Globex trade dates, explicit costs and execution). Reads the four datasets from
        `store`; writes the sealed artifact under `artifacts` (default: the Crucible home).
        `home` points at a Crucible home folder: its experiments/ folder becomes the artifacts
        root and its data/ folder the default store (pass it or `artifacts`, never both).
        Returns the futures-run document (ADR-0097): the ids, the window, every approximation,
        the null verdict with its reason and every descriptive metric. A second identical run is
        refused unless `overwrite`; a reproduction keeps the same artifact id."""
        options: dict[str, Option] = {
            "config": absolute(config),
            "store": absolute(store),
            "overwrite": overwrite,
            "json": True,
        }
        if home is not None:
            options["home"] = absolute(home)
        if artifacts is not None:
            options["artifacts"] = absolute(artifacts)
        if home is None and artifacts is None:
            options["artifacts"] = _home_paths()[0]
        return await run_cli(build_argv(["futures", "run"], [], options))

    @server.tool()
    async def crucible_futures_check(config: str) -> dict[str, object]:
        """Validate a futures-run config without touching any store: the config hash and the
        canonical config. Call it before `crucible_futures_run` to see how a config will be read."""
        options: dict[str, Option] = {"config": absolute(config), "json": True}
        return await run_cli(build_argv(["futures", "check"], [], options))

    @server.tool()
    async def crucible_futures_batch(
        batch: str,
        store: str | None = None,
        home: str | None = None,
        artifacts: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Run N DSL expressions on one futures base config (C5a). Every candidate shares the
        base's data, window, contracts, costs, execution, session and fidelity; only the strategy
        and the run name change. Reads the four datasets from `store`; writes the sealed run of
        each distinct candidate plus `<batch id>/batch.json` under `artifacts` (default: the
        Crucible home). `home` gives both roots (its experiments/ and data/ folders; pass it or
        `artifacts`, never both). Returns the batch document: the ids, the candidates in SUBMISSION
        order with their descriptive metrics (null intervals) and the null verdict, which is not
        an assessment of edge. Re-running the same batch reuses the runs it already computed."""
        options: dict[str, Option] = {
            "batch": absolute(batch),
            "store": absolute(store),
            "overwrite": overwrite,
            "json": True,
        }
        if home is not None:
            options["home"] = absolute(home)
        if artifacts is not None:
            options["artifacts"] = absolute(artifacts)
        if home is None and artifacts is None:
            options["artifacts"] = _home_paths()[0]
        return await run_cli(build_argv(["futures", "batch"], [], options))

    @server.tool()
    async def crucible_futures_walkforward(
        config: str,
        store: str | None = None,
        home: str | None = None,
        artifacts: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Walk-forward evaluation of N DSL expressions on one futures base config (C5b). The base
        window's Globex trade dates are cut into folds; each fold trains every candidate on the
        trade dates before it, keeps the eligible ones (intraday drawdown ceiling required, minimum
        equity / fill cap / time-in-market cap optional), selects the eligible one with the largest
        TRAINING net P&L (a tie goes to the earlier submission) and evaluates it on the fold's test
        window only, charging a terminal exit so the fold ends flat. Reads the four datasets from
        `store`; writes each run plus `<walk-forward id>/walkforward.json` and
        `oos_daily.parquet` under `artifacts` (default: the Crucible home). `home` gives both roots
        (its experiments/ and data/ folders; pass it or `artifacts`, never both). Returns the
        walk-forward document: the folds, the concatenated OUT-OF-SAMPLE summary, the disjoint
        training audit (marked in_sample) and the null verdict - no Sharpe, no interval, no
        assessment of edge. Re-running the same walk-forward reuses every run it computed."""
        options: dict[str, Option] = {
            "config": absolute(config),
            "store": absolute(store),
            "overwrite": overwrite,
            "json": True,
        }
        if home is not None:
            options["home"] = absolute(home)
        if artifacts is not None:
            options["artifacts"] = absolute(artifacts)
        if home is None and artifacts is None:
            options["artifacts"] = _home_paths()[0]
        return await run_cli(build_argv(["futures", "walkforward"], [], options))

    @server.tool()
    async def crucible_futures_compare(
        target: str,
        home: str | None = None,
        artifacts: str | None = None,
        min_overlap: int = 20,
    ) -> dict[str, object]:
        """Compare a sealed futures run or a walk-forward with the artifact pool (C5c). Reads the
        artifacts root only: nothing is simulated. Every other `<FUT-...>` run and `<WFA-...>`
        walk-forward there becomes a pool member, and each pair gets a comparison-key check (the
        simulator version, fidelity, execution, session and signal input must agree) and then a
        DESCRIPTIVE Pearson correlation of the two daily USD P&L series over the trade dates both
        of them have - an inner join, so a missing date is never a zero. A member whose seal does
        not verify is listed as `unverified`; a pair whose keys differ is `incompatible` with the
        differing paths; fewer overlapping dates than `min_overlap` (default 20, never below 10)
        is `insufficient_overlap`; a constant series is `constant_series`. Returns
        `<CMP-ID>/cross_run.json`: the target's descriptive metrics and window stability, the pool
        in ID ORDER (never sorted by a correlation), the counts per status and the null verdict.
        No Sharpe, IC, p-value, confidence interval, significance or ranking: every number is
        descriptive with null intervals (ADR-0102), so the pool says how close a candidate is to
        what already exists and never whether it is better."""
        options: dict[str, Option] = {
            "target": target,
            "min_overlap": str(min_overlap),
            "json": True,
        }
        if home is not None:
            options["home"] = absolute(home)
        if artifacts is not None:
            options["artifacts"] = absolute(artifacts)
        if home is None and artifacts is None:
            options["artifacts"] = _home_paths()[0]
        return await run_cli(build_argv(["futures", "compare"], [], options))

    @server.tool()
    async def crucible_futures_trials(
        family: str,
        threshold: float = 0.5,
        min_overlap: int = 20,
        home: str | None = None,
        artifacts: str | None = None,
    ) -> dict[str, object]:
        """Estimate a futures family's EFFECTIVE number of trials from its candidates' daily
        returns (C6b, ADR-0104) and write `<EFT-...>/trials.json`. Reads the artifacts root only.
        Each distinct candidate is represented by its run with the most observations; every pair
        gets the C5c overlap and compatibility check (an inner join on trade dates, nothing filled)
        and a Pearson correlation, and agglomerative AVERAGE-LINKAGE clustering of d =
        sqrt((1 - rho) / 2) gives the cluster count at `threshold` (rho*, default 0.5). This is a
        threshold-dependent ESTIMATOR, not a count of independent hypotheses: the report carries
        the sensitivity table for rho* 0.3, 0.5, 0.7 and 0.9, and any pair without a valid
        correlation (fewer than `min_overlap` shared trade dates, default 20 and never below 10,
        incompatible keys, a constant series, a missing or unverified artifact) makes it
        `unavailable` with the reasons - a missing coefficient is never replaced by 0 or 1. The
        deflation it supports (`dsr_effective_trials`) is SUPPLEMENTARY: the primary `dsr`
        deflated by `total_trials` is unchanged, and no verdict is stated."""
        options: dict[str, Option] = {
            "family": family,
            "threshold": str(threshold),
            "min_overlap": str(min_overlap),
            "json": True,
        }
        if home is not None:
            options["home"] = absolute(home)
        if artifacts is not None:
            options["artifacts"] = absolute(artifacts)
        if home is None and artifacts is None:
            options["artifacts"] = _home_paths()[0]
        return await run_cli(build_argv(["futures", "trials"], [], options))

    @server.tool()
    async def crucible_futures_prop(
        config: str,
        ruleset: str,
        horizon: int,
        execution_mode: Literal["automated", "manual"],
        payout_policy: Literal["max_eligible", "none"] = "max_eligible",
        cost_assumption: str | None = None,
        scenarios: Literal["primary", "all"] = "primary",
        news_dataset: str = "econ_events_v2",
        exchange_fees_dataset: str = "exchange_fees_v1",
        store: str | None = None,
        home: str | None = None,
        artifacts: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Evaluate one prop-firm ruleset over a futures run's attempt sequence (C7b, ADR-0107)
        and write the sealed artifact `<PRP-...>/` (attempts.parquet, summary.json,
        ruleset.yaml). The strategy signal is prepared once and every start date of the window
        replays it as an attempt of `horizon` TRADING days under the ruleset's rules. Each start
        is classified pass / fail / timeout / horizon / censored, and the summary reports the
        pass probability (passes over the starts whose horizon fits in the data), its all-start
        bounds and a seeded circular block bootstrap interval whose blocks are at least `horizon`
        trade dates long - with fewer than two blocks the interval is `unavailable` with its
        reason. It is named `conditional_pass_probability` with `definitive: false` and every
        reason (unmodeled rules, an unverified ruleset, a cost assumption, a news or
        session-calendar coverage gap, the counterfactual application to pre-2025 data) whenever
        anything qualifies it, and `practical_eligibility` is judged for `execution_mode`, so a
        mechanically successful attempt under a compliance blocker is never a practically valid
        pass. `scenarios="all"` adds one sensitivity scenario per conflict alternative beside the
        primary. Not a submission: no trial is recorded. No threshold, no verdict."""
        options: dict[str, Option] = {
            "config": absolute(config),
            "ruleset": absolute(ruleset) or ruleset,
            "horizon": str(horizon),
            "execution_mode": execution_mode,
            "payout_policy": payout_policy,
            "scenarios": scenarios,
            "news_dataset": news_dataset,
            "exchange_fees_dataset": exchange_fees_dataset,
            "store": absolute(store),
            "overwrite": overwrite,
            "json": True,
        }
        if cost_assumption is not None:
            options["cost_assumption"] = cost_assumption
        if home is not None:
            options["home"] = absolute(home)
        if artifacts is not None:
            options["artifacts"] = absolute(artifacts)
        if home is None and artifacts is None:
            options["artifacts"] = _home_paths()[0]
        return await run_cli(build_argv(["futures", "prop"], [], options))

    # ---------------------------------------------------------------- the holdout vault tools
    #
    # There is deliberately NO MCP tool for `authorize`, `evaluate` or `set-admin` (ADR-0105): the
    # admin token is a human's, an evaluation is a single human decision, and the research agent
    # drives everything else. Registering, reading the status and reading the access log are the
    # three things an agent may do -- and none of them returns a protected-period number.

    @server.tool()
    async def crucible_vault_status(
        store: str | None = None, home: str | None = None
    ) -> dict[str, object]:
        """Status of the futures holdout vault: the vault id, the protected period, the persistent
        open counter and every registration with its status (`pending`, `authorized`,
        `evaluated`). It reports no metric: a vault result is readable from its sealed artifact
        only after its single authorized evaluation has run. There is no MCP tool to authorize,
        evaluate or set the admin token: those are human steps."""
        options: dict[str, Option] = {"json": True}
        if store is not None:
            options["store"] = absolute(store)
        if home is not None:
            options["home"] = absolute(home)
        return await run_cli(build_argv(["vault", "status"], [], options))

    @server.tool()
    async def crucible_vault_register(
        config: str, store: str | None = None, home: str | None = None
    ) -> dict[str, object]:
        """Register a futures config for the holdout vault, which returns a `VR-` and records its
        complete config hash, the datasets' content hashes, the candidate id and the evaluation
        window (which must lie inside the vault). It reads no protected row. A human then
        authorizes it (`crucible vault authorize`) and runs the one evaluation
        (`crucible vault evaluate`); editing the config afterwards changes its hash and refuses
        the evaluation."""
        options: dict[str, Option] = {"config": absolute(config), "json": True}
        if store is not None:
            options["store"] = absolute(store)
        if home is not None:
            options["home"] = absolute(home)
        return await run_cli(build_argv(["vault", "register"], [], options))

    @server.tool()
    async def crucible_vault_log(
        limit: int = 200, store: str | None = None, home: str | None = None
    ) -> dict[str, object]:
        """The holdout vault's access log: every attempt on the protected period, allowed or
        refused, with the time, caller, purpose, dataset, `as_of`, outcome and registration. Use it
        to see why a read was refused."""
        options: dict[str, Option] = {"limit": _text(limit), "json": True}
        if store is not None:
            options["store"] = absolute(store)
        if home is not None:
            options["home"] = absolute(home)
        return await run_cli(build_argv(["vault", "log"], [], options))

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
    async def crucible_data_integrity(
        dataset: str,
        store: str | None = None,
        bar_seconds: int = 60,
        session: str = "cme",
        calendar: str | None = None,
        top: int = 10,
    ) -> dict[str, object]:
        """Minute-level integrity report of a bar dataset: per symbol the bars, sessions, missing
        minutes, largest hole, short sessions and weekend sessions, plus rows that break the data
        contract (`ok` is false only for those). `session` is `cme` (Globex trade date) or `utc`;
        `calendar` (e.g. CMES) adds a comparison of session dates."""
        options: dict[str, Option] = {
            "store": absolute(store) or _home_paths()[1],
            "dataset": dataset,
            "bar_seconds": _text(bar_seconds),
            "session": session,
            "calendar": calendar,
            "top": _text(top),
            "json": True,
        }
        return await run_cli(build_argv(["data", "integrity"], [], options))

    @server.tool()
    async def crucible_data_catalog(
        store: str | None = None,
        datasets: list[str] | None = None,
        verify: bool = False,
        top: int = 10,
    ) -> dict[str, object]:
        """Dataset registry of a data store: per dataset its identity (schema version, content
        hash, rows, build time), origin and root origin, price basis, lineage (parent datasets),
        data contract and range (first/last event_time, symbols). `ok` is false only when a
        manifest disagrees with its data file; a rebuilt parent or a superseded builder is a
        finding. `verify` recomputes every SHA-256 (slow); `datasets` restricts the listing."""
        options: dict[str, Option] = {
            "store": absolute(store) or _home_paths()[1],
            "dataset": datasets,
            "verify": verify,
            "top": _text(top),
            "json": True,
        }
        return await run_cli(build_argv(["data", "catalog"], [], options))

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
