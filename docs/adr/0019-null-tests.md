# ADR-0019: Null test data transforms, temp-store isolation, and scope

- **Status**: accepted
- **Date**: 2026-09-18

## Context

The original requirements: "Null tests: rerun on shuffled returns, sign-flipped,
synthetic GBM, and time-shifted signals; report the strategy's edge
relative to the null distribution." This is a different question from
everything else built so far in Phase 3: Monte Carlo (ADR-0017/0018)
characterizes uncertainty *around* a strategy's own real result; null
tests ask whether the result could have arisen from a process with *no
genuine structure at all* — they require re-running the full engine
against **altered market data**, which nothing built in this phase so far
does (DSR/PBO/sensitivity/perturbation all vary config, never the
underlying bars).

## Decision

**Bar transforms decompose-and-reconstruct rather than touch prices
directly.** `crucible/data/transforms.py` reduces each symbol's bars to
per-bar shape features — `intrabar_return = close/open - 1`,
`high_wick = high/max(open,close) - 1`, `low_wick = 1 - low/min(open,close)`
(both wicks are non-negative by construction from real data) — transforms
only the `intrabar_return`, then re-chains `open[k+1] = close[k]`
(matching `examples/momentum/build_data.py`'s existing "no overnight gap"
convention) and reapplies the *original* wick fractions. This guarantees
every reconstructed bar is valid (`high >= max(open,close)`,
`low <= min(open,close)`) by construction — the wick fractions that
produce high/low are never negative — rather than needing a validity
check-and-reject loop. Reconstruction raises `DataQualityError` if a
transformed return would drive a price to zero or below (refuse, don't
silently emit a corrupt dataset).

- **Shuffle**: independently permutes each symbol's sequence of
  (return, wicks, volume) shapes. Destroys temporal ordering: a strategy
  exploiting genuine autocorrelation/trend structure should degrade;
  total return is unaffected (same multiset of returns, different order)
  the same way Monte Carlo's return-shuffle is (ADR-0017's invariant).
- **Sign-flip**: negates every bar's `intrabar_return`, keeping order,
  wicks, and volume exactly as they were. **Deterministic — no `rng`,
  run once, not a distribution.**
- **Synthetic GBM**: replaces each symbol's returns with a fresh normal
  draw matched to that symbol's own real mean/stdev (same convention as
  the momentum example's own synthetic generator), keeping real wicks.

Corporate actions and universe membership are never transformed — only
bar prices/volume. This is a scope choice, not an oversight: corporate
actions in this codebase are rare, discrete events (one delisting in the
example dataset) that don't interact with the "is the price structure
exploitable" question these null tests ask.

**Each null run gets an isolated temp data store — never writes into the
real one.** `experiments/null_tests.py::_run_on_transformed_bars` builds
a fresh directory under `<artifacts_root>/_null_test_stores/<variant_id>`,
writes the transformed bars there under the *same* dataset name the real
config uses, copies (not moves) the real corporate-actions/universe
dataset directories into it unchanged, and derives a config pointing
`data.store` at this temp location. The user's real dataset is read-only
throughout — null tests must never mutate or pollute the input data a
researcher is trusting.

**None of the null runs count as trials.** Real market data was never
touched by the strategy in a null run — it evaluated the strategy against
synthetic/scrambled data, which isn't a "parameter evaluation" in
ADR-0008's sense by any reading (unlike ADR-0018's split between
execution/parameter perturbation, there's no ambiguity here to resolve).
The one real run (against real data) is executed exactly once per null
test function and *is* subject to normal trial counting via the ordinary
`run_experiment(config, artifacts_root)` call.

**Shuffle and synthetic GBM report a distribution and a p-value;
sign-flip reports a single paired comparison.** `validation/null_tests.py`'s
`compare_to_null(real_value, null_values)` computes
`p_value = P(null >= real)` over however many null values it's given —
this works unchanged for `n=1` (sign-flip), it just degenerates to a
binary 0.0/1.0 rather than a genuine probability, which the caller can
interpret correctly with `len(null_values) == 1` as the tell.

**"Time-shifted signals" is deferred, not implemented.** Unlike the other
three, it targets the *strategy's own signal timing* relative to
execution, not the market data — implementing it generically needs a
way to delay any `Strategy`'s orders by N bars, a distinct piece of
architecture (a wrapping Strategy or an engine-level hook) this ADR
doesn't design. Flagged clearly in the handoff notes and known gaps rather than
silently omitted.

## Alternatives considered

- **Transform prices directly (multiply the whole OHLC by a factor,
  negate absolute price levels, etc.)** instead of decompose/reconstruct:
  rejected — directly manipulating price *levels* either breaks
  OHLC ordering unpredictably or requires a separate validity-repair
  pass; the shape-based approach is correct by construction.
- **Write null-test data into the real `config.data.store`** (matching
  how `run_with_scenarios`/`sweep_1d`/perturbation all write into the
  same `artifacts_root`): rejected specifically for *input* data — those
  mechanisms only ever write *output* artifacts; corrupting a
  researcher's real dataset with synthetic bars, even temporarily, is a
  different and much worse failure mode than an extra artifact
  directory.
- **One null-test function parameterized by transform type**: rejected —
  shuffle/GBM need `n_iterations` and an `rng`; sign-flip needs neither
  and returns a different result shape (no distribution). Forcing one
  signature would mean unused parameters on one side or the other.

## Consequences

`crucible/experiments/null_tests.py` depends on `crucible/data/transforms.py`
and `crucible/data/store.build_dataset` — a new dependency direction
(`experiments` → `data`, already legal per the original requirements's layered view, but
not previously exercised by any Phase 3 code, which had stayed within
`experiments`/`validation`/`analytics`). Each null-test call leaves
behind `_null_test_stores/` directories under `artifacts_root` (one per
variant, growing with `n_iterations`) — not yet cleaned up automatically,
a known gap alongside `sweep_1d`'s and perturbation's "full cost per
run" property. Time-shifted-signal null tests remain unimplemented.
