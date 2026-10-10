# ADR-0068: A one-step product layer on top of the engine

- **Status**: accepted
- **Date**: 2026-10-10

## Context

Fetching data, writing a config and running were three steps with relative paths; data was
gitignored per checkout; the MCP server was a thin CLI wrapper with blocking calls and no
cancellation; and reports were written for quants (no benchmark, no plain-language reading, no
words when the evidence is weak). The target user describes a strategy to an agent and needs an
honest, understandable answer without touching Python or YAML.

## Decision

1. **`crucible/product/`** sits above `experiments` and below `cli` in the layering contract. One
   call (`backtest.run_backtest`, `crucible backtest`, the `crucible_backtest` MCP tool) takes a
   strategy spec (file, object or inline rule), symbols, window, capital and a cost preset, and:
   fetches the data if missing, runs the quality battery, runs the vectorized backtest as one
   recorded trial (DSR, contamination), runs a buy-and-hold of the same symbols on the same engine and
   costs, runs a seeded shuffled-returns null test, and writes `summary.json`, `summary.html`,
   `benchmark_equity.parquet` and `strategy_spec.json` beside the run's technical artifacts.
2. **A home folder** (`CRUCIBLE_HOME`, else the remembered setting, else the platform data
   directory) holds `data/`, `experiments/`, `cache/`; always absolute, never the working
   directory (`crucible config set-home` writes it once).
3. **A dataset per request.** The name encodes provider, symbols, window, interval and price basis,
   so a repeat is offline and identical, and the strategy sees exactly the bars of its window (no
   pre-window history; indicators warm up inside it). An `end` that is not in the past is refused:
   it would return different data tomorrow.
4. **Engine and fills.** The headline run is the vectorized Level 0/1 engine (fills at the signal
   bar's close with the mandatory one-bar lag, ADR-0035), the engine the reference SMA example used
   and the only one fast enough for a null test of 100 shuffles in seconds. This is the *optimistic*
   timing the vectorized path documents; the report says "vectorized (fills at the signal bar's
   close)" in its footer, and `promote` is the path to next-open fills and Level 2+ friction. That
   trade is recorded here as the one place the product default is not the more pessimistic option:
   reproducing the reference numbers and keeping a cheap null test outweighed it, and the verdict
   never rests on fill timing alone.
5. **The reading is generated from the numbers** (`product/summary.py`): pure functions, named
   thresholds, no free text, no randomness. The strongest verdict, `some_evidence`, requires a
   Sharpe interval above zero, 100 or more trades, at least 5 years, DSR of 0.95 or more, a shuffled
   test beaten at 5 %, no contamination and **more than one instrument**; otherwise `not_conclusive`,
   or `no_edge_detected` for a non-positive result. The text never says a strategy works.
6. **Seed.** The default experiment seed is 1 (the example convention) so the bootstrap intervals of
   the reference SMA run reproduce.
7. **`clamp_rounding` OHLC repair.** Yahoo's adjusted series has bars whose high is 3e-14 below the
   close, so every fetch of SPY refused. The provider path gains `ohlc_repair="clamp_rounding"`:
   repair only a violation within 1e-6 of the close (counted in the import report), still refuse a
   larger one. The product flow uses it; the CLI default stays `refuse`.
8. **MCP.** Tools become async and cancellable (a cancelled or timed-out call kills the child
   process; `CRUCIBLE_MCP_TIMEOUT`, default 900 s); path arguments are made absolute against
   `CRUCIBLE_WORKDIR`/the working directory and defaults point into the home; the missing flags
   are exposed; `crucible://guide` and the `backtest_a_strategy` prompt serve the agent guide. The
   child's `VIRTUAL_ENV` is removed so a stale one prints no warning.
9. **Windows console.** `crucible` reconfigures stdout/stderr to UTF-8 with replacement, so a table or a
   ticker never raises `UnicodeEncodeError` on a legacy code page.
10. **Dependencies.** `yfinance` and `mcp` become core dependencies (the extras remain, as aliases):
    the product must work after one install command. Recorded in `docs/DEPENDENCIES.md`.

## Alternatives considered

- *Headline on the event-driven engine:* more pessimistic fills, but a run of 11 years of daily bars
  took about 25 s against 0.03 s (measured on the SPY example), so no 100-shuffle null test in a
  few seconds, and it would not reproduce the reference. Offered as `realism_check` (the same
  rules promoted to Level 2, not counted as a trial) instead.
- *A new MCP server code path calling the library:* a second path that can diverge from the CLI
  (ADR-0066 reasons still hold); the product tools wrap the new CLI command.
- *Pre-window warm-up history:* more "natural" (a rule can act on day one) but made the result
  depend on how much history the store happened to hold; window-exact data is simpler and stricter.
- *Free-text summaries from a model:* not reproducible and able to overclaim.

## Consequences

- A result is a pure function of (spec, window, symbols, costs, capital, seed, data hash, code).
  The experiment id also covers the home path (the config records the store location), so two homes
  give two ids with identical numbers; `summary.json` bytes are equal for the same home.
- The family for trial counting defaults to symbols + window, so every variant of an idea tried on
  the same data raises the trial count and deflates the DSR (the honest price of looking).
- A not-in-the-past `end` is refused instead of truncated.
- The result document has its own `schema_version` (1); `docs/COMPATIBILITY.md` lists the rule.

**Amendment (2026-10-10): the realism cap.** Section 4 admits the headline run uses the
optimistic fill timing of the vectorized engine. Consequence added: `some_evidence` additionally
requires that `realism_check` ran and that no `fragile_to_execution` flag was raised. A result that
clears every other guard without the check is `not_conclusive` with the blocker
`realism_not_checked` (a flag and a first next step to re-run with the check); one that fails it is
`not_conclusive` with `fragile_to_execution`. Outputs that were already `not_conclusive` or
`no_edge_detected` are unchanged. This restores prime directive 4 at the verdict, the only place
the product default was not the more pessimistic option.
