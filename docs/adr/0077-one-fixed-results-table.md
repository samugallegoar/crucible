# ADR-0077: One fixed results table for the one-step backtest

- **Status**: accepted
- **Date**: 2026-10-18

## Context

The one-step backtest (ADR-0068) is driven mostly by agents through the MCP tool. They show the
result as a table, but they assemble it themselves from `results.strategy`, `results.benchmark`
and `validation`, so two agents (or the same agent on two days) show different rows, rename them,
format numbers differently or leave out a metric such as the trial count or the realism level,
which `AGENTS.md` §9 says must never be missing next to a headline number. Inside Crucible the
same table was also written three times (terminal, HTML report, README text) with different rows.

## Decision

- `crucible/product/table.py::build_results_table` builds the table once, from the finished result
  document. Fixed rows (`ROW_IDS`, 14: final value, total return, return per year, volatility,
  worst fall, Sharpe with its 95% range, completed trades, winning trades before costs, average
  bars held, time in the market, trial count, deflated Sharpe, shuffled-returns p-value, realism
  level), fixed columns (Metric, Strategy, Buy and hold), fixed labels and formats, and `n/a` or
  `-` where a value does not exist or does not apply: a row is never omitted.
- The document gains `results_table` = `{columns, rows: [{id, label, strategy, benchmark}],
  markdown}`. The terminal output and the HTML report render the same rows.
- `AGENT_GUIDE.md` and the `crucible_backtest` tool description tell agents to paste
  `results_table.markdown` unchanged and to put emphasis in prose below it.
- The evidence rows (trial count, deflated Sharpe, p-value, realism level) are part of the table so
  that no table can show a Sharpe without them.

## Alternatives considered

- **Only tell agents to be consistent**: what already failed; a convention without code
  (`AGENTS.md` §1.2).
- **A JSON schema for the table and let agents render it**: agents would still pick their own
  labels and formats.
- **A varying set of rows (hide what is `n/a`)**: shape changes between runs, which is the problem.
- **A realism-check column**: a column that exists only sometimes; the realism check stays in
  `validation.realism_check` and the summary.

## Consequences

- Additive: `schema_version` stays 2 (docs/COMPATIBILITY.md §3). The product golden surface
  (`results`, `validation`, `summary`, `trades`, specs) is untouched and did not change. Row ids
  are now a contract: removing or renaming one is a bump.
- The terminal and report tables are longer than before (6-7 rows to 14).
- Agents can still ignore the instruction; the fix is that the correct table is one field away and
  needs no assembly. Older `summary.json` files have no `results_table`.
