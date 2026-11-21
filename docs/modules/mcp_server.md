# Module: mcp_server

## What exists

An MCP server (stdio) that exposes Crucible as tools for an agent (ADR-0066, ADR-0068). It ships in
the core install; start it with `crucible-mcp` or `python -m crucible.mcp_server`.

- `invoke.py` — `invoke(argv)` / `ainvoke(argv)` run `python -m crucible.cli.main <argv>` in a fresh
  process (stdin closed, `PYTHONUTF8=1`, no inherited `VIRTUAL_ENV`) and return the JSON document.
  `ainvoke` is cancellable: a cancelled task or a timeout kills the child. A non-zero exit, an
  argparse error (the last lines of its output, where the actionable `error:` line is) or a timeout
  becomes `ToolRefusal`; when the command printed its structured error document (every
  `CrucibleError` under `--json`) `ToolRefusal.envelope` holds it and the tool error text is that
  JSON (`code`, `message`, `location`), prefixed by the SDK's `Error executing tool <name>: `
  (ADR-0084).
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

Engine tools (advanced; all return the command's `--json` document): `crucible_schema` (`kind`:
the config, a spec, or an output document), `crucible_artifact` (a run by artifact id: compact,
`detail`, or `verify`),
`crucible_run`, `crucible_run_vectorized`, `crucible_validate`, `crucible_optimize`,
`crucible_compare`, `crucible_report`, `crucible_promote`, `crucible_debug`, `crucible_data_list`,
`crucible_data_check`, `crucible_data_integrity` (minute-level integrity report, ADR-0088),
`crucible_data_catalog` (dataset registry: identity, lineage, contract, range; ADR-0089),
`crucible_data_build`, `crucible_data_fetch`.

Futures tools (ADR-0095): `crucible_futures_run(config, store, artifacts=None, overwrite=False)`
simulates one futures-run config on the continuous CME series of `store` and returns the run id, the
artifact id, the trial family and count, the summary and the manifest (with its approximations);
`crucible_futures_check(config)` validates the config without touching a store and returns the
config hash and the canonical config. `crucible_futures_batch(batch, store=None, home=None,
artifacts=None, overwrite=False)` (C5a, ADR-0100) runs N DSL expressions on one base futures config
and returns the batch document (`BAT-` id, the candidates in submission order with their status and
descriptive metrics, the null verdict). `crucible_futures_walkforward(config, store=None,
home=None, artifacts=None, overwrite=False)` (C5b, ADR-0101) runs a walk-forward and returns its
document (`WFA-` id, the folds with their selection and out-of-sample run, the concatenated `oos`
summary, the disjoint `in_sample_audit` and the null verdict). `crucible_futures_compare(target,
home=None, artifacts=None, min_overlap=20)` (C5c, ADR-0102) reads the artifacts root only (no
`store`): it compares a `FUT-`/`WFA-` target with every other `FUT-`/`WFA-` artifact there and
returns `cross_run.json` — the target's descriptive metrics and window stability, the pool in ID
order with each member's status (`ok`, `incompatible` with the differing comparison-key paths,
`insufficient_overlap`, `constant_series`, `unverified`), the overlap, the descriptive correlation
(null intervals) and the null verdict. `min_overlap` is how many overlapping trade dates a value
needs (default 20, refused below 10). `crucible_futures_trials(family, threshold=0.5,
min_overlap=20, home=None, artifacts=None)` (C6b, ADR-0104) reads the artifacts root only and
returns `trials.json`: the family's counts, each candidate's representative run, every pair's status
and correlation, the ESTIMATE of the effective number of trials (average linkage on
`d = sqrt((1 - rho) / 2)`, threshold `threshold`) with its sensitivity table for
`0.3/0.5/0.7/0.9`, the reasons when one pair has no valid correlation, and the null verdict. The
defletion it supports (`dsr_effective_trials`) is supplementary: the primary `dsr` is unchanged.
All six are thin `build_argv` + `run_cli` wrappers over
`crucible futures run|check|batch|walkforward|compare|trials` (ADR-0066), with absolute paths and
the home's experiments folder as the default `artifacts`.

Holdout vault tools (C6c, ADR-0105): `crucible_vault_status(store=None, home=None)` returns the
vault id, the protected period, the persistent open counter and every registration with its status;
`crucible_vault_register(config, store=None, home=None)` records a `VR-<16 hex>` for a futures config
(its complete config hash, the datasets' content hashes, the candidate id and the window, which must
lie inside the vault) and reads no protected row; `crucible_vault_log(limit=200, store=None,
home=None)` returns the access log — every attempt on protected data, allowed or refused, with the
caller, the purpose, the dataset, the `as_of` and the outcome. None of the three returns a
protected-period number. There is deliberately **no** MCP tool for `vault authorize`, `vault
evaluate` or `vault set-admin`: the admin token is a human's and an evaluation is a single human
decision, so an agent cannot read the holdout by asking for it.

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
