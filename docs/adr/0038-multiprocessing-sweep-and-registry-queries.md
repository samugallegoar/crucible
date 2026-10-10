# ADR-0038: Multiprocessing sweep runner and result-registry queries

- **Status**: accepted
- **Date**: 2026-09-20

## Context

The original requirements's Phase 6 scope names two remaining deliverables: a multiprocessing
experiment runner ("1,000-config sweep runs in parallel") and result
registry queries. `run_experiment` (`crucible/experiments/runner.py`)
already calls `DuckDBTrialRegistry` internally to record every trial and
read back its Sharpe/contamination history for DSR. Naively calling
`run_experiment` from multiple worker processes concurrently is exactly
the kind of thing that looks fine until it silently isn't, so two
questions had to be settled before writing any parallel code:

1. **Is concurrent multi-process access to `trial_registry.duckdb` even
   safe?** Verified (not assumed) via DuckDB's own documentation: DuckDB
   is designed for a single owning process per database file; a second
   process opening the same file "fails fast with a locking error." Not
   silent corruption, but also not usable from multiple simultaneous
   workers without extra machinery.
2. **If workers serialize on the registry (e.g. via a lock), is the
   result still deterministic (E1)?** No. Each trial's own provisional
   DSR is computed against whatever the registry's trial-Sharpe history
   happens to contain *at the moment that trial's registry block runs*
   (already true and documented for the existing sequential case,
   ADR-0023's `optimize_1d` bugfix). In a sequential loop that moment is
   always "after every earlier config in the list" — deterministic. Under
   a lock shared by concurrent workers, that moment is "whichever worker
   happened to acquire the lock first" — a function of OS scheduling, not
   of the configs themselves. The same set of configs could legitimately
   produce a different per-trial provisional DSR on two different runs.
   That is a real violation of CLAUDE.md's prime directive #3
   ("identical inputs ⇒ byte-identical outputs... a bug, even if the
   numbers look 'better'"), not a cosmetic concern.

## Decision

**Split `run_experiment` into two phases and run only the first one in
parallel.** `_run_experiment_compute` (quality gate, engine simulation,
metrics, Monte Carlo) touches only the read-only data store and this run's
own uniquely-named artifact directory — safe to call from any number of
worker processes at once. `_finalize_experiment` (trial registration, DSR,
contamination, manifest/artifact writing) is the only part that touches
`trial_registry.duckdb`, and it always runs **serially, in the parent
process, in caller-specified order** — never in a worker, never behind a
lock racing against other workers. `run_experiment` itself becomes a
two-line wrapper (`_finalize_experiment(_run_experiment_compute(config,
root), record_trial=record_trial)`) — behavior-preserving by construction,
confirmed by the full existing runner/optimize/DSR/contamination test
suite passing unchanged after the refactor.

`run_experiment_parallel(configs, artifacts_root, *, max_workers=None,
record_trial=True) -> list[RunArtifacts]` runs `_run_experiment_compute`
across a `ProcessPoolExecutor`, using `pool.map` specifically because it
returns results **in input order, not completion order** — then finalizes
each one serially in that same order in the parent. This reproduces
calling `run_experiment` in a loop over `configs`, byte for byte,
regardless of how the worker processes actually finish — the property
that makes this safe under CLAUDE.md's determinism directive, not just
"probably fine because DuckDB usually behaves."

`optimize_1d` gained `max_workers: int | None = None` — `None` (default)
keeps today's sequential behavior (a typical Phase 3 sweep is small
enough that spinning up a pool would only add overhead); passing a value
routes the sweep through `run_experiment_parallel` instead, byte-identical
either way. `crucible optimize --workers N` exposes this on the CLI.

**Result-registry queries**: `DuckDBTrialRegistry.all_trials(family) ->
list[TrialRecord]`, ordered by `experiment_id` (DuckDB gives no ordering
guarantee without an explicit `ORDER BY`, so an unordered query would
itself be a small determinism leak). `crucible compare FAMILY` (previously
a `_PLANNED` stub refusing with "Phase 6") lists every trial, sorted by
per-period Sharpe descending, with each trial's DSR read back from its own
`manifest.json` when that artifact is still on disk (a trial can outlive
its artifact directory being pruned; the registry row is still valid
without it — shown as `dsr=unknown` rather than raising, since a missing
sibling artifact for an old trial is an expected, not exceptional, state).

## Alternatives considered

- **A lock around the whole `run_experiment` call per worker**: rejected
  — this serializes the expensive part (the simulation) too, giving no
  real parallelism at all; the whole point is to parallelize
  `BacktestEngine.run()`, not just avoid a crash.
- **A lock around only the registry-touching block, held briefly by each
  worker as it finishes**: rejected in Context above — this fixes the
  DuckDB crash but not the determinism problem (registration order
  becomes wall-clock-dependent). This was the design this session's own
  prior handoff notes entry initially leaned toward before the concurrency
  question was actually verified; recorded here so a future session
  doesn't re-propose it without re-deriving why it's wrong.
- **Assume DuckDB's file locking "probably serializes writers safely"
  without verifying**: rejected per AGENTS.md §10 — checked instead
  (DuckDB's own docs, not just recollection), and the answer materially
  changed the design (a naive concurrent-registry-access sweep would have
  been an intermittent crash risk, not a performance suboptimality).
- **Parallelize the vectorized path instead of (or in addition to) the
  event-driven path this priority**: not done — `run_vectorized_experiment`
  (ADR-0036) has no trial-registry coupling at all today (deferred, same
  ADR), so it has no analogous concurrency hazard to solve, and
  parallelizing it would be a smaller, separate piece of work. Left as an
  explicit open item, not silently out of scope.
- **A full artifact-comparison/diff view for `crucible compare`** (reading
  every trial's full `metrics.json`, rendering a comparison table with
  every metric): rejected as scope beyond what "result registry queries"
  requires; the registry itself only ever stored `sharpe`/`mode`/window,
  so a query surface over exactly that (plus the one extra `dsr` lookup,
  since DSR is the headline validation number the original requirements emphasize) is the
  honest scope for this priority.

## Consequences

- `crucible/experiments/runner.py`: `run_experiment`'s public signature
  and behavior are unchanged; internals are now `_run_experiment_compute`
  + `_finalize_experiment` + `_PendingRun` (the data handed between them,
  including the `BacktestResult` and the seeded `rng`'s post-`compute_metrics`
  state — `numpy.random.Generator` pickles its full internal state, so
  Monte Carlo's "reuse the same advanced rng stream" property survives
  the process boundary unchanged).
- `crucible/experiments/optimize.py::optimize_1d` gained `max_workers`;
  `crucible/cli/main.py` gained `--workers` on `optimize` and a real
  `compare` subcommand (removing it from `_PLANNED`, now empty).
- Every worker process re-imports the strategy/signal entrypoint fresh,
  exactly as a standalone `crucible run` invocation would — no shared
  Python state between workers beyond what `ProcessPoolExecutor` pickles
  across the boundary (a validated `ExperimentConfig`, a `Path`).
- Known gap: no parallel runner for the vectorized path yet (see
  Alternatives). No CLI surface for `run_vectorized_experiment`/
  `promote_config` still (ADR-0036/0037, unrelated to this priority).
- **Phase 6 is now complete**: all four the original requirements Phase 6 deliverables
  (vectorized Level 0/1 engine + shift discipline + poison test,
  config-driven vectorized runs, promotion to event-driven, multiprocessing
  sweep runner + result-registry queries) have a working implementation
  and tests. the roadmap's phase table reflects this.
