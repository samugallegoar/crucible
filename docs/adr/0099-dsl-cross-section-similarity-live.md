# ADR-0099: Cross-sectional rank, structural similarity, and the incremental evaluator with parity

- **Status**: accepted
- **Date**: 2026-11-18

## Context

C4c closes the DSL milestone (PRD §13). It adds:
- a cross-sectional rank over the five instruments;
- a structural similarity measured by the largest common subtree against a pool;
- proof that one compiled signal runs unchanged in vectorized and in live (incremental) evaluation.

The owner set these requirements for the rank:
- only instruments with a valid observation at the same decision timestamp are ranked;
- at least three, else the result is null;
- no forward-fill;
- only normalized, comparable features;
- average-rank ties, normalized to [0, 1];
- the universe and count are recorded at each timestamp.

For similarity:
- Sørensen–Dice on canonical ASTs, with a precise common subtree;
- operators, topology, features and fixed literals are compared;
- parameters are placeholders whose binding pattern is preserved.

For live:
- one immutable `CompiledSignal`, with state kept separate per stream;
- parity tests over warm-up, missing observations, timestamps and restoration.

## Decision

1. **`cs_rank`.**
   - **Universe.** The decision timestamp is `event_time`. The universe at `t` is every symbol with
     a row exactly at `t` and a non-null argument. An absent symbol is not carried forward.
   - **Value.** With fewer than three members the value is null. Otherwise it is
     `(average rank − 1)/(m − 1)`, ascending.
   - **Timing.** The decision time of a rank-dependent value is the latest `available_at` in the
     universe.
   - **Recording.** `cs_universe` records, for each timestamp and rank node, the sorted symbols and
     their count.
   - **Arguments.** Typing (ADR-0096) already restricts the argument to dimensionless values.
   - **Futures runs.** They trade one root, so they refuse an expression that uses `cs_rank`.
2. **Similarity.**
   - **The common subtree.** A complete subtree is a node with all its descendants. Two complete
     subtrees are equal when their canonical forms are equal after the parameter placeholders are
     renumbered inside the subtree. So:
     - `$a + $a` and `$a + $b` differ;
     - a parameter never equals a literal;
     - an int parameter never equals a float one;
     - parameter names, defaults and bounds are ignored.
   - **The measure.** `common` is the node count of the largest complete subtree present in both
     canonical ASTs, and `similarity = 2·common/(nodes_a + nodes_b)`.
   - **Pool queries.** `pool_similarity` ranks a pool by similarity, then by key.
3. **The incremental evaluator.**
   - `IncrementalEvaluator(CompiledSignal)` holds per-symbol state (window buffers, EMA value and
     count, last timestamps) and implements `Snapshottable`.
   - `step(event_time, rows)` processes one decision timestamp across all streams. Absent symbols
     are not updated.
   - Out-of-order timestamps and the availability rules of ADR-0098 are refused at every step.
   - Restoring a snapshot into an evaluator for a different `compiled_id` is refused.
4. **Parity is tested, with a stated tolerance.**
   - Nulls and booleans must match exactly. Numeric values must match within a relative 1e-9.
   - Bitwise equality is not claimed. Polars rolling aggregates and incremental buffers sum in
     different orders, so they round differently. Making the vectorized path sum like the buffer
     would make it orders of magnitude slower on years of minute bars.
   - A real-data bench test counts decisions whose sign differs between the two paths, and it must
     be zero.
   - On one week of real ES ratio-adjusted bars (6,479 rows) the two paths agreed bitwise for both
     example expressions.
   - A timestamp whose universe is empty has no decision, so its `decision_at` is null.

## Alternatives considered

- **Forward-fill a missing instrument into the rank.** It would rank stale data as current. The
  owner ruled it out.
- **Fewer than three members, or ordinal ranks.** Ranking two instruments is a comparison, not a
  rank, and ordinal ranks make ties depend on order. Rejected.
- **Tree edit distance, or a maximum common top-down mapping.** Both are more expensive and less
  predictable. The owner approved the complete-subtree Dice measure.
- **Bitwise parity through a shared slow summation.** Too slow for the vectorized path. Rejected
  for a stated tolerance plus an exact check on decisions.

## Consequences

- **C4 is complete.** C5 (batches, walk-forward, PnL correlation) can deduplicate and cluster by
  `structure_id` and similarity.
- **The cross-section needs a multi-root run.** `cs_rank` is usable from the library on a panel;
  no futures run evaluates it yet.
- **Live has an evaluator but no runtime yet.** The incremental evaluator is the piece live reuses,
  but it is not yet wired into a live futures runtime.
