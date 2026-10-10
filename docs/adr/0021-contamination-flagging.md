# ADR-0021: Contamination flagging via a trial-registry schema extension

- **Status**: accepted
- **Date**: 2026-09-18

## Context

The original requirements: "Optimization vs evaluation separation: the engine tags
every run as `optimization` or `evaluation`; an evaluation on data used
for optimization is flagged in the report header." `ExperimentHeader.mode:
RunMode` (`optimization`/`evaluation`) already existed but was unused for
this purpose; the report header's `contamination_flags` cell was
hardcoded to `"not tracked until Phase 3"` since Phase 1.

Answering "did an optimization-mode trial in this family already see this
evaluation's data window?" needs, for every past trial in the family: its
`mode` and its data window (`start`/`end`). Neither was available from
`DuckDBTrialRegistry` (`trials(family, experiment_id, sharpe)`) — only
`experiment_id` and `sharpe` were persisted there.

## Decision

**Extend the trial registry's schema** with `mode`, `start_ns`, `end_ns`
columns, recorded at `record_trial` time, rather than reconstructing them
from each trial's `config.yaml` in the artifact store. The registry
becomes self-sufficient for this query — no filesystem re-reads,
consistent with `sharpe`'s own precedent (added to the same table for
DSR, ADR-0015: "the registry already knows what a query needs" beats
re-deriving it from artifacts on every check). This project is pre-1.0
with no persisted user registries to migrate — a schema change with no
migration path is the correct amount of engineering here (CLAUDE.md:
don't add backwards-compatibility shims for scenarios that can't happen).

A new `TrialRegistry.overlapping_optimization_trials(family, start_ns,
end_ns) -> Sequence[str]` method answers the query directly in SQL (a
standard half-open-interval overlap: `a.start < b.end AND a.end >
b.start`), returning the overlapping trials' `experiment_id`s for the
report/manifest to name explicitly (never a bare boolean — "refuse, don't
warn" extends to explaining *which* trials contaminated the run).

**`crucible/validation/contamination.py::check_contamination(family,
mode, start_ns, end_ns, registry) -> ContaminationResult`** is pure logic
over the registry: only an `evaluation`-mode run can be contaminated (an
`optimization` run is never flagged, regardless of overlap — R4.9's own
wording is about evaluations, not optimizations examining old
optimization windows). `ContaminationResult.reason` is always a populated
human-readable string, whether or not contamination was found — mirrors
DSR/PBO's precedent of an explicit "why" string rather than a bare flag.

**Only trials recorded with `record_trial=True` participate.** A run
executed with `record_trial=False` (scenario fan-out variants, execution
perturbation, null-test re-runs) never inserts a registry row at all, so
its mode/window is never recorded and it can neither contaminate nor be
checked for contamination. This falls out of the existing
`record_trial=False` semantics (ADR-0014) with no special-casing needed:
those runs were already deliberately excluded from trial counting for the
same reason (they're re-examinations of an already-counted evaluation,
not independent looks at the data).

**Wired into every run via `run_experiment`**: `manifest.json` gains
`contamination` (bool), `contamination_reason` (string), and
`contamination_overlapping_trials` (list of experiment ids); the report
header's `contamination_flags` cell now shows the real reason string,
prefixed `"CONTAMINATED: "` when true. This is the last of PBO/DSR/Monte
Carlo/null-test/factor-regression-shaped features to actually complete
its report-header wiring in this phase, rather than being deferred to
priority 9's CLI — the difference is that contamination flagging needs no
external input beyond what a single run already has (its own mode/window
plus the family's existing trial history), unlike PBO (needs a
multi-trial panel) or factor regression (needs external factor files).

## Alternatives considered

- **Join against each trial's `manifest.json`/`config.yaml` in the
  artifact store** instead of a schema extension: rejected — slower (N
  file reads per contamination check, growing with family size), and
  `manifest.json` doesn't even carry the data window today (only
  `config.yaml` does), so this path would also need to parse YAML per
  trial. The registry is already the authoritative, queryable home for
  per-trial facts a validation check needs (ADR-0015's precedent).
- **Store `mode` as a DuckDB `ENUM` type** instead of `VARCHAR`: rejected
  — `RunMode` already round-trips through `.value` (a plain string)
  everywhere else in this codebase (e.g. `manifest["mode"] =
  config.experiment.mode.value`); an enum column adds DuckDB-specific
  schema ceremony for no behavioral benefit here.
- **Flag contamination for optimization runs too** (i.e. any overlap with
  any prior trial, regardless of mode): rejected — the original requirements' stated
  concern is specifically about evaluating on data an optimization
  search already touched (lookahead into "future" trial selection, not a
  simulator sense); two optimization runs overlapping is just... two
  points in the same search, not contamination.

## Consequences

`DuckDBTrialRegistry`'s schema changed (three new nullable columns); no
migration exists or is needed (pre-1.0, `trial_registry.duckdb` files are
generated artifacts, not checked-in data). Contamination flagging is
scoped to same-process, same-artifacts-root registries — a distributed or
multi-machine trial registry (not built yet, flagged as a known gap
alongside the existing single-file-DuckDB concurrency gap) would need the
same schema. `overlapping_optimization_trials` doesn't account for purge/
embargo windows from a splitter — it's a raw date-range overlap, which is
the conservative (stricter) choice: even a purged/embargoed adjacent
window still shares information through serial correlation the purge
convention itself is designed to guard against elsewhere (docs/GLOSSARY.md:
purge, embargo), so treating any raw overlap as contamination is the
pessimistic default per AGENTS.md §10, not an oversight.
