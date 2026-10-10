"""The Crucible MCP server (ADR-0066): the ``--json`` CLI as tools, over stdio.

Install the optional extra (``uv sync --extra mcp``) and start it with ``crucible-mcp`` or
``python -m crucible.mcp_server``. Every tool runs the matching CLI command in a fresh process, so
its result is the command's ``--json`` document (metrics with CI, trial count, DSR/PBO and realism
level together, AGENTS.md section 9) and its refusals are the command's actionable messages. Paths
are resolved against the server's working directory and a tool writes only where its arguments say
(``artifacts``, ``store``, ``cache_dir``): the server has the permissions of the user who started
it, like the CLI.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Literal

from crucible.core.errors import ConfigurationError
from crucible.mcp_server.invoke import ToolRefusal, invoke

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mcp.server.mcpserver import MCPServer

INSTRUCTIONS = (
    "Crucible is a backtesting engine that refuses to flatter a strategy. Use crucible_schema to "
    "see what a valid experiment config contains. Run results always carry the headline metrics "
    "with confidence intervals, the trial count, DSR/PBO and the realism level together; quote "
    "them together. A refusal is an error whose message says what to fix. Relative paths resolve "
    "against the server's working directory, which depends on how the client launched it: prefer "
    "absolute paths."
)

Option = str | bool | list[str] | None


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


def build_server() -> MCPServer:
    """The server with every tool registered.

    Raises ``ConfigurationError`` if the ``mcp`` package (2.x) is not installed."""
    try:
        from mcp.server.mcpserver import MCPServer
        from mcp.server.mcpserver.exceptions import ToolError
    except ImportError:
        msg = (
            "the MCP server needs the optional 'mcp' package, version 2.3 or newer (2.x): run "
            "`uv sync --extra mcp`"
        )
        raise ConfigurationError(msg) from None

    server = MCPServer("crucible", instructions=INSTRUCTIONS)

    def run_cli(argv: Sequence[str]) -> dict[str, object]:
        """The CLI's document, or a tool error carrying the CLI's own message (the SDK shows the
        model only an anticipated ``ToolError``'s text)."""
        try:
            return invoke(argv)
        except ToolRefusal as refusal:
            raise ToolError(str(refusal)) from refusal

    @server.tool()
    def crucible_schema() -> dict[str, object]:
        """The JSON Schema of the experiment config: every valid field and its type."""
        return run_cli(["schema"])

    @server.tool()
    def crucible_run(
        config: str,
        artifacts: str = "experiments",
        overrides: list[str] | None = None,
        runtime: Literal["backtest", "paper", "live"] = "backtest",
    ) -> dict[str, object]:
        """Run an event-driven experiment from a YAML config. `overrides` are `PATH=VALUE` edits
        applied before validation (e.g. `strategy.params.lookback=60`). Writes the run under
        `artifacts`. Returns the experiment id, artifact paths, metrics with CIs and the manifest
        headline (trial count, DSR, PBO, realism level, contamination). `live` needs
        `live.enabled` in the config and uses the simulated venue."""
        options: dict[str, Option] = {
            "artifacts": artifacts,
            "runtime": runtime,
            "override": overrides,
            "json": True,
        }
        return run_cli(build_argv("run", [config], options))

    @server.tool()
    def crucible_run_vectorized(
        config: str, artifacts: str = "experiments", overrides: list[str] | None = None
    ) -> dict[str, object]:
        """Run an experiment on the fast vectorized engine (Levels 0-1, signal-function strategies).
        A vectorized run is recorded as a trial like any other."""
        options: dict[str, Option] = {"artifacts": artifacts, "override": overrides, "json": True}
        return run_cli(build_argv("run-vectorized", [config], options))

    @server.tool()
    def crucible_validate(
        config: str,
        artifacts: str = "experiments",
        factors: str | None = None,
        overrides: list[str] | None = None,
    ) -> dict[str, object]:
        """Run an experiment and add the statistical validation: DSR, contamination and, if
        `factors` (a CSV of factor returns) is given, a factor regression."""
        options: dict[str, Option] = {
            "artifacts": artifacts,
            "factors": factors,
            "override": overrides,
            "json": True,
        }
        return run_cli(build_argv("validate", [config], options))

    @server.tool()
    def crucible_optimize(
        config: str,
        param: str,
        values: str,
        artifacts: str = "experiments",
        metric: str = "sharpe",
        vectorized: bool = False,
        overrides: list[str] | None = None,
    ) -> dict[str, object]:
        """Sweep one strategy parameter (`values` is comma-separated, e.g. `40,60,80`). Every point
        is a trial; the PBO and the best point's DSR are computed over the whole sweep. The config's
        `experiment.mode` must be `optimization`."""
        options: dict[str, Option] = {
            "param": param,
            "values": values,
            "artifacts": artifacts,
            "metric": metric,
            "vectorized": vectorized,
            "override": overrides,
            "json": True,
        }
        return run_cli(build_argv("optimize", [config], options))

    @server.tool()
    def crucible_promote(
        config: str,
        level: int,
        lookback: int,
        execution: str,
        out: str | None = None,
        run: bool = False,
        artifacts: str = "experiments",
        overrides: list[str] | None = None,
    ) -> dict[str, object]:
        """Turn a vectorized config into an event-driven config at realism level 2-5 (`execution` is
        a YAML file of ExecutionConfig fields; `lookback` is the history the signal needs). Returns
        the promoted YAML (or the file `out` it was written to). With `run` (which needs `out`) it
        also runs the promoted config and returns the run's metrics and headline set."""
        options: dict[str, Option] = {
            "level": str(level),
            "lookback": str(lookback),
            "execution": execution,
            "out": out,
            "run": run,
            "artifacts": artifacts,
            "override": overrides,
            "json": True,
        }
        return run_cli(build_argv("promote", [config], options))

    @server.tool()
    def crucible_debug(
        experiment_id: str, at: str, artifacts: str = "experiments", order: str | None = None
    ) -> dict[str, object]:
        """Replay a finished experiment deterministically up to `at` (ISO date or datetime, or raw
        UTC ns) and return the engine's state there: cash, positions and orders, with the reasons an
        order was not filled. `events_total` counts the events replayed and `last_events` shows the
        final 20. Pass `order` to explain only that order id."""
        options: dict[str, Option] = {
            "at": at,
            "artifacts": artifacts,
            "order": order,
            "json": True,
        }
        return run_cli(build_argv("debug", [experiment_id], options))

    @server.tool()
    def crucible_compare(family: str, artifacts: str = "experiments") -> dict[str, object]:
        """List every recorded trial of a trial family from the trial registry."""
        return run_cli(build_argv("compare", [family], {"artifacts": artifacts, "json": True}))

    @server.tool()
    def crucible_report(experiment_id: str, artifacts: str = "experiments") -> dict[str, object]:
        """Re-render the report of a finished experiment and return where it is."""
        return run_cli(
            build_argv("report", [experiment_id], {"artifacts": artifacts, "json": True})
        )

    @server.tool()
    def crucible_data_list(store: str) -> dict[str, object]:
        """List the datasets of a data store with their row counts, content hashes and sources."""
        return run_cli(build_argv(["data", "list"], [], {"store": store, "json": True}))

    @server.tool()
    def crucible_data_check(
        store: str,
        dataset: str,
        calendar: str,
        skip: list[str] | None = None,
        skip_reason: str = "",
    ) -> dict[str, object]:
        """Run the data-quality battery on a dataset. Skipping a check requires a reason."""
        options: dict[str, Option] = {
            "store": store,
            "dataset": dataset,
            "calendar": calendar,
            "skip": skip,
            "skip_reason": skip_reason or None,
            "json": True,
        }
        return run_cli(build_argv(["data", "check"], [], options))

    @server.tool()
    def crucible_data_build(spec: str, store: str) -> dict[str, object]:
        """Build the datasets an import spec describes into `store` (quality-checked before any
        write)."""
        return run_cli(build_argv(["data", "build"], [spec], {"store": store, "json": True}))

    @server.tool()
    def crucible_data_fetch(
        store: str,
        dataset: str,
        symbols: str,
        start: str,
        end: str,
        provider: Literal["yfinance", "tiingo"] | None = None,
        interval: str = "1d",
        price_basis: Literal["adjusted", "raw"] = "adjusted",
        calendar: str = "XNYS",
        allow_partial: bool = False,
        cache_dir: str | None = None,
    ) -> dict[str, object]:
        """Fetch prices from a free provider (yfinance by default, or tiingo with TIINGO_API_KEY set
        in the server's environment) into a dataset. This makes network requests. Dates are
        YYYY-MM-DD; `symbols` is comma-separated. Raw provider answers are cached only if
        `cache_dir` is given. The result lists `failed_symbols` and `warnings` (a symbol that
        started late or stopped early): read them before trusting the dataset."""
        options: dict[str, Option] = {
            "store": store,
            "dataset": dataset,
            "symbols": symbols,
            "start": start,
            "end": end,
            "provider": provider,
            "interval": interval,
            "price_basis": price_basis,
            "calendar": calendar,
            "allow_partial": allow_partial,
            "cache_dir": cache_dir,
            "no_cache": cache_dir is None,
            "json": True,
        }
        return run_cli(build_argv(["data", "fetch"], [], options))

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
