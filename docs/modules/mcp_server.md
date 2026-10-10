# Module: mcp_server

## What exists

An MCP server (stdio) that exposes Crucible as tools for an agent (ADR-0066, ADR-0068). It ships in
the core install; start it with `crucible-mcp` or `python -m crucible.mcp_server`.

- `invoke.py` — `invoke(argv)` / `ainvoke(argv)` run `python -m crucible.cli.main <argv>` in a fresh
  process (stdin closed, `PYTHONUTF8=1`, no inherited `VIRTUAL_ENV`) and return the JSON document.
  `ainvoke` is cancellable: a cancelled task or a timeout kills the child. A non-zero exit, an
  argparse error (the last lines of its output, where the actionable `error:` line is) or a timeout
  becomes `ToolRefusal`.
- `server.py` — `build_argv` (values attached with `=`, positionals after `--`), `absolute`/`workdir`
  (path resolution), `build_server()` registering the tools, a resource and a prompt, and `main()`.

### Tools

Product tools (for a person who does not code; descriptions are written for an agent):

| Tool | Does |
|---|---|
| `crucible_backtest` | the one-step backtest: symbols, window, a spec (object) or inline `entry`/`exit`; returns the result document |
| `crucible_check_strategy` | validate a spec or inline rule and read it back in plain language |
| `crucible_strategy_templates` | list ready-made specs, or return one in full |
| `crucible_strategy_schema` | the JSON Schema of a spec |
| `crucible_results` | earlier backtests, newest first |
| `crucible_status` | the home folder (absolute), cache, provider availability, version |

Engine tools (advanced; all return the command's `--json` document): `crucible_schema`,
`crucible_run`, `crucible_run_vectorized`, `crucible_validate`, `crucible_optimize`,
`crucible_compare`, `crucible_report`, `crucible_promote`, `crucible_debug`, `crucible_data_list`,
`crucible_data_check`, `crucible_data_build`, `crucible_data_fetch`.

Resource `crucible://guide` and prompt `backtest_a_strategy`: the agent guide
(`AGENT_GUIDE.md` at the repository root, packaged into the wheel as a resource).

### Operational rules

- **Cancellation and time**: every tool is async; cancelling a call, or exceeding
  `CRUCIBLE_MCP_TIMEOUT` seconds (default 900), kills the child process.
- **Paths**: a relative path argument is made absolute against `CRUCIBLE_WORKDIR` (default: the
  server's working directory) and the command runs there; defaults for `artifacts`, `store` and
  `cache_dir` are inside the Crucible home, which `crucible_status` reports. Results contain
  absolute paths.
- **Flags**: every CLI flag of the wrapped commands is a tool argument (`data_build`
  `start/end/max_contracts/max_rows`, `optimize` `pbo_groups/workers`, `data_fetch`
  `refresh/ohlc_repair/max_rows`).

## Responsibility

Make Crucible callable by an MCP client without a second code path: the tool and the command share
validation, refusals and numbers. It adds no business logic.

## Interfaces

`MCPServer` from the `mcp` package (2.3 or newer, below 3). A refusal is raised as the SDK's
`ToolError` so the model reads the CLI's actionable message. Because every call is a new process,
editing a strategy between calls takes effect (a long-lived server would keep the cached module).

## Extension points

A new tool is a new thin `async` function in `server.py` that builds an argv and calls `run_cli`; the
command it wraps needs `--json` first (ADR-0059). Add it to `EXPECTED_TOOLS` and the argv check in
`tests/integration/test_mcp_server.py`.

## Known gaps

- The server has the permissions of the user who starts it and does not sandbox paths; a tool writes
  where its arguments (or the home folder) say.
- `crucible_data_fetch` and `crucible_backtest` use the network and the server's environment for
  `TIINGO_API_KEY`; the key is never a tool argument.
- stdio only: no HTTP transport, so clients that accept only a remote MCP URL cannot attach it
  directly.
- A call has no progress notifications; a long call (a realism check is about 30 s, a sweep longer)
  is silent until it ends or the timeout kills it.
- Each call starts an interpreter (about a second) so strategy code edits take effect.
- Engine tools that need a config file (`run`, `promote`, `optimize`) assume the caller can write
  that file; the no-code path does not.
