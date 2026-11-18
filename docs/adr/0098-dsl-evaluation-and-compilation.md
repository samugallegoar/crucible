# ADR-0098: DSL evaluation semantics, availability, the CompiledSignal, and expressions in the futures run

- **Status**: accepted
- **Date**: 2026-11-18

## Context

ADR-0096 gave the DSL its grammar, types and identities, with no evaluation. For C4b the owner asked
for:
- the complete causal operator library;
- deterministic compilation to an immutable, versioned `CompiledSignal` that live can reuse
  unchanged;
- enforcement of C2's `available_at`, with no second availability system;
- ADR-0086 scale validation, applied to DSL expressions and Python functions alike;
- refusal of ambiguous expressions, never guessing.

Several operator semantics change results and were not fixed by ADR-0096: the null handling, the
standard-deviation estimator, the tie rule, whether a window includes the current bar, and the EMA
seeding. AGENTS.md §10 asks for the conservative option in each case, written down.

## Decision

1. **Streams and windows.**
   - Each symbol is its own stream; a frame without `symbol` is one stream.
   - Rows must be strictly increasing in `event_time` within a stream.
   - Windows count rows (bars) and include the current row.
2. **Null semantics.**
   - Null in gives null out.
   - Every non-finite intermediate becomes null: infinities, NaN, division by zero.
   - Comparisons with null give null, and `and`, `or`, `not` follow Kleene's three-valued logic.
   - `if(null, a, b)` is null.
   - `min` and `max` propagate null (unlike Polars `min_horizontal`, which skips it).
   - A rolling operator is null unless all n values in its window are present.
3. **Operators.**
   - `delay` and `delta` shift by rows.
   - `ts_mean`, `ts_min`, `ts_max` cover the last n rows, including the current one. A breakout
     therefore reads `close > delay(ts_max(close, n), 1)`.
   - `ts_std` is the sample standard deviation (ddof = 1) and needs n ≥ 2.
   - `ts_zscore` is null when the standard deviation is 0.
   - `ts_rank` averages ties and is normalized to `(rank − 1)/(n − 1)` in [0, 1], with n ≥ 2.
   - `ema` uses α = 2/(n+1) and `adjust=False`, as in `strategy_spec`.
     - It is seeded at the first value present.
     - A null input gives a null output and leaves the state unchanged.
     - The output is null until n values have been seen.
   - Each operator declares `min_window`, which is checked at parse time and again by `bind`.
4. **Session features from C2.**
   - `time_of_day` is exchange-local minutes since midnight at the bar end.
   - `minutes_since_open` and `minutes_to_close` are measured against the bar's CME trade-date
     session (ADR-0091/0092), and are null on an off-schedule bar.
   - An expression that uses them without a calendar is refused.
   - `GRAMMAR_VERSION` and `OPERATOR_TABLE_VERSION` go to `"2"`.
5. **Availability (C2 is the single source).**
   - The evaluated frame must carry the C2 row columns `event_time` and `available_at`.
   - These are refused:
     - `available_at < event_time`;
     - an `available_at` that decreases within a stream;
     - a latency longer than one bar, because the decision could not reach the next bar's open.
   - Each output row carries `decision_at = available_at`.
6. **The `CompiledSignal`** (`COMPILER_VERSION = "1"`).
   - It is a frozen definition: canonical text and form, root kind, features, warm-up, bound
     parameters, signal input, the three ids, and the compiler and operator versions. It holds no
     evaluation state. Live state (C4c) lives outside it, per stream.
   - `compiled_id` hashes the parameterization id, the compiler version, the operator versions used
     and the input **roles** (signal input and features), not dataset hashes. This narrows
     ADR-0096 §7: the same definition must run in live unchanged, and the datasets are already part
     of the futures run id.
7. **Scale (ADR-0086).**
   - On ratio-adjusted input a numeric root must have price degree 0. Boolean roots are homogeneous
     by typing.
   - A future roll multiplies the whole past of a ratio-adjusted series by one constant, so a
     degree-0 expression decides the same as on a causally adjusted series.
   - **Decisions before a roll are unaffected by the roll's factor.** The lookahead test scales
     every row before a roll by two different factors and checks the decisions before the roll are
     identical.
   - **Decisions after a roll may read its factor.** A window that straddles a roll does read the
     factor, but by then the roll has happened and its factor is causally known. This is the
     return-preserving adjustment of ADR-0086, not lookahead.
   - The empirical ×16/×0.0625 check of ADR-0094 still runs as a second line of defence.
   - Python functions keep their declaration plus the empirical check.
8. **Futures run.**
   - `strategy.expression` is a third source, exclusive with `spec` and `entrypoint`.
   - `params` bind its `$` parameters, and `contracts` is required.
   - The target is `sign(score) × contracts` for a numeric root, or `contracts` when a boolean root
     is true. A null value or the warm-up gives flat.
   - The session policy is applied as for Python functions.
   - The signal record carries `strategy_kind: dsl` and the compiled signal's description.

## Alternatives considered

- **Population standard deviation (ddof = 0, as Bollinger bands in `strategy_spec`).** Rejected:
  ddof = 1 is the estimator analytics uses, and n ≥ 2 makes it defined.
- **Exclude the current bar from `ts_max` and `ts_min`** (as `highest` and `lowest` do in
  `strategy_spec`). It would make "over the last n bars" mean two different things across operators.
  Rejected in favour of including it and writing the breakout with an explicit `delay`.
- **Skip nulls in windows, or forward-fill them.** It hides missing data and makes windows unequal.
  Rejected.
- **Map a null score to "hold the previous target".** It keeps a position without a current signal.
  Rejected; null means flat.
- **Put dataset hashes in `compiled_id`.** It would tie a live-reusable definition to a historical
  dataset. Rejected; the datasets live in the run id.

## Consequences

- **Every C4a `structure_id` changes** with the version bump. None was persisted outside tests.
- **DSL and `strategy_spec` differ on rolling extremes.** `ts_max(x, n)` ≠ `highest(n)`, and this
  is documented.
- **Expressions join the trial counts.** Futures runs with expressions are registered like any
  other, under their family.
- **C4c builds on this definition.** The incremental evaluator must reproduce these semantics row
  for row, and its parity tests use them.
