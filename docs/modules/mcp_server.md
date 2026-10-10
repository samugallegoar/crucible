# Module: mcp_server

## What exists

An MCP server (stdio) that exposes the `--json` CLI as tools (ADR-0066). It needs the optional extra
`mcp` (`uv sync --extra mcp`); start it with `crucible-mcp` or `python -m crucible.mcp_server`.

- `invoke.py` — `invoke(argv)` runs `python -m crucible.cli.main <argv>` in a fresh process (stdin
  closed) and returns the JSON document; a non-zero exit, an argparse error (the last lines of its
  output, where the actionable `error:` line is) or a timeout becomes `ToolRefusal`.
- `server.py` — `build_argv` (values attached with `=`, positionals after `--`), `build_server()`
  registering the tools, and `main()` serving over stdio.
- Tools: `crucible_schema`, `crucible_run`, `crucible_run_vectorized`, `crucible_validate`,
  `crucible_optimize`, `crucible_compare`, `crucible_report`, `crucible_data_list`,
  `crucible_data_check`, `crucible_data_build`, `crucible_data_fetch`, `crucible_promote` and
  `crucible_debug` (the last two since `promote`/`debug` gained `--json`). Each takes the command's
  arguments (`overrides` as a list of `PATH=VALUE`) and returns its `--json` document.

## Responsibility

Make Crucible callable by an MCP client without a second code path: the tool and the command share
validation, refusals and numbers. It adds no business logic.

## Interfaces

`MCPServer` from the `mcp` package (2.3 or newer, below 3). A refusal is raised as the SDK's
`ToolError` so the model reads the CLI's actionable message. Because every call is a new process,
editing a strategy between two calls takes effect (a long-lived server would keep the cached module).

## Extension points

A new tool is a new thin function in `server.py` that builds an argv and calls `run`; the command it
wraps needs `--json` first (ADR-0059). Add it to `EXPECTED_TOOLS` in the test.

## Known gaps

Not every flag is a tool argument: `data_build`
has no `--start/--end/--max-contracts/--max-rows`, `optimize` no `--pbo-groups`, `data_fetch` no
`--refresh/--ohlc-repair/--max-rows`. A call blocks until the child ends and a cancelled call does not
stop it. Relative paths depend on the working directory the client launched the server with. The server has the permissions of the user who starts it and resolves paths against its
working directory; it does not sandbox them. `crucible_data_fetch` uses the network and the server's
environment for `TIINGO_API_KEY`, and caches only if `cache_dir` is given.
