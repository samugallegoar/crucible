# ADR-0014: Trial registry storage, idempotency, and scenario-fanout scoping

- **Status**: accepted
- **Date**: 2026-09-18

## Context

ADR-0008 decided *what* counts as a trial family and that every trial in a
family counts toward DSR/PBO deflation, but left two questions open,
flagged in the project notes: what backs the persistent count (a DuckDB
table under the artifact root was "the working assumption"), and — not
anticipated by ADR-0008 at all — whether re-running an unchanged
`experiment_id`, or running R3.10's execution-scenario fan-out
(optimistic/base/conservative/extreme), should each increment the count.
Both are ambiguities that change the DSR/PBO number a report will
eventually show, so AGENTS.md §10 requires resolving them here rather
than in code.

## Decision

**Storage.** `crucible.validation.trial_registry.DuckDBTrialRegistry`
implements the `TrialRegistry` Protocol over a DuckDB file at
`<artifacts_root>/trial_registry.duckdb` — one file per artifact store,
alongside the `EXP-*` run directories it counts. `experiments/*` is
already gitignored except manifests (CLAUDE.md repo map), so this file
never needs its own gitignore entry.

**Schema and idempotency.** One table, `trials(family VARCHAR,
experiment_id VARCHAR, PRIMARY KEY (family, experiment_id))`.
`record_trial` inserts with `ON CONFLICT DO NOTHING`: recording the same
`experiment_id` under the same family twice does not increment the count.
This is deliberate, not an oversight — `experiment_id` is a pure function
of config hash + data hashes (`runner.experiment_id`), so "the same
experiment_id again" is a re-run of the *same* parameter evaluation (e.g.
regenerating artifacts after deleting them), not a new one. ADR-0008's own
language — "every parameter evaluation" — is about evaluations, not
invocations; counting re-runs would make the count depend on how many
times someone happened to press "run" rather than on genuine search
breadth, which is not the "more trials, more conservative" the pessimism
principle intends — it would just be noise.

**Scenario fan-out does not multiply trials.** `run_with_scenarios` calls
`run_experiment(..., record_trial=False)` for every scenario variant
after the base; only the base run's `experiment_id` is recorded. A
scenario fan-out evaluates the *same* strategy and parameters under
different execution-cost assumptions to measure sensitivity (R3.10) — it
is not a parameter search. Counting each of the (currently) four
variants as a separate trial would inflate every family's count by 4x
purely from running a robustness check, with zero corresponding increase
in actual overfitting risk — the opposite of what trial counting exists
to measure. `record_trial=False` still calls `trial_count(family)` so the
scenario variants' manifests/reports show the family's real, current
count (not a stale or missing value).

## Alternatives considered

- **In-memory / per-process counter**: rejected outright by ADR-0008
  itself ("registry data outlives individual runs").
- **A JSON/text ledger file instead of DuckDB**: workable, but DuckDB is
  already a declared dependency (`pyproject.toml`), already documented as
  the intended backing store for this exact purpose in prior sessions'
  planning, and gives atomic upsert-style counting (`ON CONFLICT DO
  NOTHING`) for free instead of hand-rolled dedup logic over a flat file.
- **Increment on every `record_trial` call, regardless of experiment_id**:
  rejected — see Decision; this is the "counts re-runs, not evaluations"
  alternative and was rejected for not measuring what DSR/PBO need it to
  measure.
- **Count every scenario variant as its own trial**: rejected — see
  Decision; considered because it's the more literal reading of "every
  run in the family counts," but the literal reading conflates a
  robustness check with a parameter search.

## Consequences

`run_experiment` gains a keyword-only `record_trial: bool = True`
parameter; only `run_with_scenarios` passes `False`, and only for
non-base scenarios. `manifest.json`'s `trial_count` field and the report
header's `trial_count` cell now carry the registry's real count instead
of the hardcoded `1`; both were already excluded from/outside the golden
byte-identity surface (`tests/golden/fixtures/README.md`), so this is not
a golden-surface change. If a future contamination-flagging pass
(handoff priority 8) needs to distinguish "same experiment_id, re-run"
from "genuinely new evaluation," it can query `trials` directly rather
than relying on `record_trial`'s return value.
