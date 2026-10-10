# ADR-0066: An MCP server over the machine-readable CLI

- **Status**: accepted
- **Date**: 2026-10-09

## Context

ADR-0059 gave every command a strict `--json` document and deferred an MCP server ("a second
interface with its own contract"). An agent that speaks MCP can then call Crucible directly, without
shelling out and parsing process output. The risk the ADR named is real: a second interface can drift
from the CLI in validation, refusals or numbers.

## Decision

1. **A thin server, built on the CLI.** `crucible/mcp_server/` exposes one tool per command and each
   tool builds the argv of the existing command and runs it as `python -m crucible.cli.main <argv>`
   in a **fresh process** (`invoke.py`), returning the `--json` document. A tool and the command cannot
   disagree: same validation, same refusals, same numbers. A fresh process matters (review finding):
   run in process, `sys.modules` would keep serving a strategy module the agent had just edited, and
   nothing in a manifest hashes the code, so a stale rerun would be indistinguishable from a real one.
   It also keeps the CLI's stdout out of the protocol stream, needs no lock and no stream redirect, and
   a cancelled call cannot leave a half-run in the server (the child's stdin is `/dev/null`).
2. **Tools** (amended 2026-10-10: `crucible_promote` and `crucible_debug` were added when those commands gained `--json`; `debug --json` returns the last 20 events and their total, not the whole stream): `crucible_schema`, `crucible_run`, `crucible_run_vectorized`, `crucible_validate`,
   `crucible_optimize`, `crucible_compare`, `crucible_report`, `crucible_data_list`,
   `crucible_data_check`, `crucible_data_build`, `crucible_data_fetch`, `crucible_promote`,
   `crucible_debug` (owner choice: read-only plus runs).
3. **Optional dependency.** The official `mcp` SDK is the optional extra `mcp` (`uv sync --extra mcp`),
   stdio transport, started by `crucible-mcp` or `python -m crucible.mcp_server`. Without the package
   the server exits with that command; the core install is unchanged. CI installs all extras.
4. **Refusals are tool errors with the CLI's own message.** `ToolRefusal` carries the
   `{"error": {"type", "message"}}` text (or argparse's usage text, or the exception of a missing
   file) and the server re-raises it as the SDK's `ToolError`, the only exception whose message the
   model sees.
5. **Values cannot become flags.** `build_argv` attaches each value with `=` (`--artifacts=VALUE`) and
   puts positionals after `--`, so a hostile value such as `--resume=x` is only ever a value.
6. **Authority is the caller's.** The server runs with the permissions of the user who started it, and
   paths are relative to its working directory, exactly like the CLI. `crucible_data_fetch` makes
   network requests and reads `TIINGO_API_KEY` from the server's environment or `.env` (never from a
   tool argument, so a key cannot enter a transcript). It caches raw answers only if `cache_dir` is
   given (otherwise `--no-cache`), so a tool writes only where its arguments say. Its result carries
   `failed_symbols` and `warnings` (late start, early end), which `data fetch --json` now includes so
   `--allow-partial` cannot silently drop symbols.
7. **Layering.** `crucible.mcp_server` is above `cli` in the import contract.

## Alternatives considered

- *Hand-rolled JSON-RPC over stdio:* no dependency, but the project would own protocol compliance.
- *Tools calling `experiments` directly:* faster, but a second code path that can diverge from the CLI.

## Consequences

- Agents can run, validate, sweep and inspect without shell access; every result carries the headline
  metrics with CI, trial count, DSR/PBO and realism level together (AGENTS.md section 9).
- A tool call blocks its worker thread while the child runs; a cancelled call does not stop the
  child. Acceptable for a local stdio server, revisit if clients need cancellation.
- Pinning: `mcp>=2.3,<3` (the code uses 2.x APIs, `MCPServer` and `mcp.Client`; a 1.x would fail with
  a misleading error). mypy treats `mcp.*` as an optional import, like `yfinance`.
- Each call pays an interpreter start (about a second) for correctness; the first call imports the
  engine's dependencies.
- No engine, config-hash, artifact or golden change.
