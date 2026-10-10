# ADR-0036: Vectorized config glue — refusal list and artifact scope

- **Status**: accepted
- **Date**: 2026-09-19

## Context

ADR-0035 built the vectorized engine itself but deliberately left it with
no config-driven entry point (`VectorizedConfig` is engine-owned, not
`ExperimentConfig`). This priority adds the `crucible.experiments`-side
glue the original requirements imply ("same config schema... as the event-driven path"):
`assemble_vectorized_engine`/`run_vectorized_experiment`. Two questions
affect results and had to be pinned:

1. Which `ExperimentConfig` fields must the vectorized path *refuse*
   (AGENTS.md §5) rather than silently ignore, given `VectorizedConfig`
   has no slot for most of them?
2. How complete should the written artifact set be — full parity with
   `run_experiment`'s `RunArtifacts` (trade log, DSR, PBO, Monte Carlo,
   trial registry, contamination) or a smaller, honestly-scoped set?

## Decision

**1. Refuse whenever silently ignoring the field would compute a
*different* result than the config asked for, not just an incomplete
one.** Concretely, `_refuse_out_of_scope` (`crucible/experiments/
vectorized_runner.py`) rejects: `data.corporate_actions`,
`data.universe`, `data.symbol_currency`/`fx_rates`,
`data.futures_multipliers`, `risk`, `settlement_lag_days`,
`short_borrow_rate`/`margin_financing_rate`, `execution.scenarios`, any
populated `execution.{spread,latency,slippage,commission,participation}`
model slot, and `realism_level` outside `{FRICTIONLESS, BASIC_FRICTION}`.

`corporate_actions` is the sharpest case and worth stating explicitly:
bars are raw, unadjusted prices (AGENTS.md §9) — the event-driven
engine's dividend postings are the *only* mechanism that turns a raw
close-to-close return into a correct total return. A vectorized run over
a dividend-paying dataset that silently skipped corporate actions
wouldn't just be missing a feature; it would report a **wrong number**
with no indication anything was left out. The same reasoning extends to
every item on the list — each is a case where the vectorized engine has
literally no code path that could account for the field's effect on the
result, so continuing anyway would be reporting a number the config
didn't actually ask for.

**2. The written artifact set is deliberately smaller than
`RunArtifacts`, not equivalent-but-approximate.** `VectorizedRunArtifacts`
writes `config.yaml`, `manifest.json`, `equity.parquet` (`ts`/`equity`
only — no `cash`/`realized_pnl`/`fees_paid`, which need a ledger this path
doesn't have), two vectorized-specific artifacts with no event-driven
analogue (`weights.parquet`, `scores.parquet` — the lagged position and
raw signal output, kept because a future "promotion" priority will need
exactly this record of what was decided when), `metrics.json`,
`equity.svg`, and `report.html`. DSR, PBO, Monte Carlo, and trial-registry
recording are **not computed** — `manifest.json` and the report's
validation summary say so explicitly (`"not tracked for the vectorized
path yet (Phase 6 priority 2, known gap)"`), following the same
honest-placeholder convention this codebase has used since Phase 1's
"DSR/PBO not computed (Phase 3)" and Phase 3's own early-priority gaps
(AGENTS.md §5's "refuse, don't warn" extends naturally to "state the gap,
don't fabricate a number for it").

`build_trades([])` supplies an always-empty trade log rather than
inventing a "trade" concept for continuous weights — `n_trades`/
`hit_rate` in the resulting `metrics.json` are therefore always `0`/absent
for a vectorized run, a known, documented limitation rather than a silent
wrong answer.

**3. `import_entrypoint` is extracted from `runner._load_strategy`** into
a shared helper (same module, `runner.py`, since it's the file that
already owned the import-with-cwd-fallback logic) returning the raw
module attribute rather than an instantiated object — `_load_strategy`
now instantiates it (a `Strategy` class), `assemble_vectorized_engine`
uses it directly (a `SignalFunction`, already callable, no instantiation).
One entrypoint-resolution mechanism, two different things done with the
result — avoids a second copy of the same ~15-line sys.path-fallback
block.

## Alternatives considered

- **Silently ignore out-of-scope fields** (e.g. treat a set
  `corporate_actions` as a no-op): rejected outright — this is exactly
  the "refuse, don't warn" prime directive (AGENTS.md §5); a config that
  asks for dividend-adjusted results and silently gets un-adjusted ones
  is a correctness bug wearing a config-flexibility costume.
- **Full `RunArtifacts` parity for v1** (wire DSR/PBO/Monte Carlo/trial
  registry into the vectorized path immediately): rejected as premature
  scope for this priority — trial counting and DSR are agnostic to engine
  type in principle, so this is worth doing eventually, but doing it now
  would couple this priority to `DuckDBTrialRegistry`'s concurrency
  behavior (relevant to *this* phase's later multiprocessing-sweep
  priority) before that design is settled. Smaller and honestly labeled
  now, extended later, matches how every other Phase 3 priority in this
  codebase shipped (e.g. PBO implemented-but-unwired for several
  priorities before `optimize`/`validate` closed the gap, ADR-0015/0022).
- **A single combined `ExperimentConfig` validator method instead of a
  free function in `vectorized_runner.py`**: considered, but
  `ExperimentConfig` is a generic Pydantic model consumed by both engines;
  putting vectorized-specific refusal logic on the model itself would
  couple the config schema to one particular consumer's scope limits.
  Keeping `_refuse_out_of_scope` in `vectorized_runner.py` (the
  vectorized-specific glue module) keeps that coupling local.

## Consequences

- `examples/trend_demo/config_vectorized.yaml` (new) is the first
  config-driven vectorized run — same dataset as `config.yaml`, strategy
  entrypoint pointed at `trend_follower_signal` instead of
  `TrendFollower`. Not wired into the `crucible run` CLI yet (that's the
  natural next small step, not done this priority — the CLI currently has
  no way to know a config targets the vectorized vs. event-driven engine;
  needs a decision, e.g. an explicit `--vectorized` flag vs. inferring
  from whether the entrypoint resolves to a class or a function).
- Every refusal fires at `assemble_vectorized_engine`/
  `run_vectorized_experiment` time, before any data is read or engine
  work happens — cheap to check, fails fast.
- `runner.py::import_entrypoint` is now a public (non-underscore) helper;
  `_load_strategy` is unchanged in behavior, only in implementation.
