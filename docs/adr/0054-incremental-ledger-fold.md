# ADR-0054: Incremental ledger fold and portfolio snapshot reuse

- **Status**: accepted
- **Date**: 2026-09-27

## Context

Running the momentum example on the imported equities (569 symbols) showed the engine was
quadratic in the number of trades. cProfile on a two-year slice (456 s wall) put about 435 of
452 engine seconds in `InMemoryLedger.fold`, called 27,436 times: every `ctx.portfolio` access
(the strategy reads it once per symbol, 569 times per rebalance) and every invariant check
replayed the whole ledger from its first transaction. The full 2015-2026 run did not finish in
ten minutes.

## Decision

1. **`InMemoryLedger.fold(up_to)` is incremental.** The ledger is append-only in time order, so
   it keeps a running state (cash, available cash, positions, fees, last timestamp) and applies
   only the transactions appended since the last call. A transaction whose `settled_at` is later
   than the fold time is applied to `cash` and parked in a pending list. When a later fold
   reaches its `settled_at` the cache is rebuilt by replaying the ledger in order, so
   `available_cash` equals the full fold exactly (ADR-0028 semantics unchanged). Any
   exception during a catch-up drops the whole cache, so a refused or interrupted fold never
   leaves a half-applied state. A call with an earlier `up_to` than the cached one, or
   with `up_to=None`, replays the whole ledger. Every call returns fresh objects (copies of the
   balances and `PositionState`s), so a caller may mutate a result. `restore()` resets the cache.
   `snapshot()`, and therefore checkpoint files, are unchanged.
2. **The original loop stays as `_fold_full`** and is the test oracle: a property test applies
   random sequences of appends (fills, fees, cash-only rows, lagged fills), folds at random
   cutoffs (including going backwards) and restores, and requires the incremental result to equal
   `_fold_full` field by field.
3. **`InMemoryLedger.version`** increases on every append and restore. The engine reuses the last
   `PortfolioSnapshot` while `(clock.now, ledger.version, marks version, extra currencies)` is
   unchanged; the marks version is bumped wherever `_marks` is written (each bar, checkpoint
   resume). The snapshot is a pure function of those four inputs.

## Equivalence argument

The same transactions are applied in the same order with the same `Decimal` operations to
`cash`, `positions` and `fees`. `available_cash` is the one place where order could matter:
`Decimal` addition is **not** associative once amounts need more than the 28 working digits
(financing charges such as `notional * rate * elapsed / year` do), so adding a lagged amount
after later transactions can differ in the last digit (found in the Batch B review). The
fold therefore replays in ledger order whenever a pending transaction settles, which makes the
result identical to the full fold, not merely close; the unit test uses 28-digit amounts and
the property test includes 22-decimal amounts. Without settlement lag nothing is ever pending
and the fold stays purely incremental. All golden fixtures, the resume-equivalence matrix
(I13) and the live parity tests pass unchanged.

## Alternatives considered

- **Memoize on `(len(txns), up_to)` only.** Misses whenever a fill lands, which is exactly when
  a strategy trades; the incremental fold handles growth.
- **Store balances in each ledger row.** Changes the ledger schema and every artifact.
- **Numba or a Rust port of the fold.** Rejected by the original requirements and by AGENTS.md rule 1; an
  algorithmic fix was enough.
- **Cache inside `ctx.portfolio` only.** Would leave the invariant checks and the other engine
  callers quadratic.

## Consequences

- The cost per fold is proportional to new transactions (plus the number of positions for the
  copy), not to the ledger length. Measured (`docs/data/scale.md`): 569-symbol 2021-2023 slice
  456 s to 14.9 s; full 2015-2026 run from not finishing to 114 s after the fold and 72 s after
  the snapshot reuse; the whole test suite went from 8m46s to about 5 minutes.
- The runtime accounting invariants (I1, I3, I4, I12) compare the snapshot with a fold of the
  same ledger; that fold is now the incremental one, so they no longer check it against an
  independent replay. `_fold_full` is verified against it by the property and unit tests; a
  periodic full-fold check at checkpoints or run end is a possible follow-up.
- Any new code that writes ledger transactions must go through `append`/`restore` (the only
  writers), or the cache and the snapshot key go stale.
- Remaining hotspots (2015-2019 profile): point-in-time history reads 23%, `ladder.on_bar` 21%,
  feed materialisation 16%. Not changed: the targets were met, and the history read is the
  information barrier. Peak memory (1.75-1.94 GB on the full equities run) is the tightest
  margin; a streaming feed is the deferred fix.
- No golden change, no new invariant identity.
