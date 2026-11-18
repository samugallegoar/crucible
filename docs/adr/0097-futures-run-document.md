# ADR-0097: The futures-run document: a null verdict with a reason, a versioned schema, `artifact show`, `--home`

- **Status**: accepted
- **Date**: 2026-11-18

## Context

Fathom records only what Crucible reports; it never computes a verdict or a metric itself. It asked
for four things before it can test its equity-index cells on `crucible futures run` (milestone C3c):
- a verdict in the same vocabulary as `crucible backtest`, or an explicit reason for having none;
- a versioned JSON document carrying the artifact id, experiment id, trial family, trial count and
  headline metrics as `{value, ci_low, ci_high}`;
- `crucible artifact show` for a futures run, which ADR-0095 left open;
- a separate trial registry and artifacts folder for its tests.

ADR-0095 forbids Sharpe, deflated Sharpe, confidence intervals, null tests and any edge claim for a
futures run before C6 (multiple-testing statistics) and C7 (robustness and prop-firm rules). The
owner approved C3c on the condition that this restriction stays.

## Decision

1. **One constructor, one schema.** `crucible.experiments.futures_document.futures_document(run_dir)`
   builds the document from the sealed run directory alone, after verifying the seal.
   `futures run --json` and `artifact show --json` both call it, so the two interfaces emit the same
   document by construction. The document has `schema_version: 1` and its JSON schema is registered
   as an output-schema kind.
2. **The verdict is null, and the document says why.**
   - `verdict.verdict_level` is `null`. `verdict.verdict_reason` takes a code from a closed set:
     today only `not_assessed`, with the milestones that will assess the run (`C6`, `C7`) and a
     message.
   - The message states that **an absence of assessment is not evidence of no edge**. `not_assessed`
     is distinct from `backtest`'s `no_edge_detected`, which is a negative result, and from
     `some_evidence`. A consumer must never map one onto the other.
   - The builder asserts that the level is null exactly when a reason is present.
3. **Metrics carry an assessment status.**
   - Every metric is `{value, ci_low, ci_high, assessment, unit}`. `assessment` is `descriptive` or
     `statistical`.
   - Every futures metric is `descriptive`, and a descriptive metric must have null intervals
     (asserted). A null interval therefore reads as "not assessed", never as "assessed and
     uninformative".
   - `headline` lists the headline metrics in order.
4. **`--home` follows `crucible backtest`.**
   - The same resolver gives the home's experiments folder. That folder becomes the artifacts root,
     and it holds the only trial registry (`trial_registry.duckdb`).
   - Precedence:
     - `--home` and `--artifacts` together are refused;
     - either one alone selects that root;
     - neither keeps the current default.
   - One artifacts root has exactly one authoritative registry.

## Alternatives considered

- **Compute `backtest`'s verdict on the daily returns (option B).** It would lift the ADR-0095
  restriction and pull part of C6 forward. The owner rejected it.
- **Use `no_edge_detected` when nothing is assessed.** It turns an absence of evidence into
  negative evidence. Rejected.
- **Separate builders for `run --json` and `artifact show`.** The two could drift apart. Rejected
  for a single constructor reading the sealed directory.

## Consequences

- **Fathom can fetch both run kinds the same way.** It reads futures runs through `artifact show`
  as it does equity runs, and stores `verdict_level: null` together with the reason code.
- **C6 and C7 change the document additively.** They will add `statistical` metrics and reason or
  level values; the version is bumped if any existing key changes meaning.
