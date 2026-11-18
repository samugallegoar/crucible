# ADR-0094: The futures signal bridge: ratio-adjusted signals, scale invariance enforced, series aligned

Status: accepted (2026-11-17). The owner set the requirements (milestone C3b, refinement C).
- **Signal series:** the ratio-adjusted continuous series is the default signal input, and the
  unadjusted contract series is used for fills, P&L, costs and valuation.
- **Scale invariance (ADR-0086):** it is enforced, so there are no absolute price-level operators
  or fixed point thresholds on ratio-adjusted data.
- **Raw input:** it is allowed as an explicit option.
- **Validation:** declarative and Python strategies are both validated.
- **Alignment:** timestamps and contracts are verified between the two series.
- **Provenance:** dataset ids, hashes and adjustment modes are recorded.

The run that consumes this module, with its config, artifact and CLI, is C3b-3.

## Context

ADR-0086 (decision 8) built the ratio-adjusted series for research and wrote that its price levels
depend on later rolls. Every bar before a roll is multiplied by the compounded `next / front`
ratios, so `close > 4500` on it means a different real price at each point in history, and the
meaning changes again whenever a new roll is added. Two parts of that decision were not
implemented: the restriction on level operators and a test of it.

Nothing yet connected a strategy to the futures simulator (ADR-0090), and the strategy-spec path
(ADR-0067) only knew percentage stops and exchange-calendar session rules.

## Decision

1. **`crucible.experiments.futures_signals.futures_targets` is the one bridge.** It takes:
   - the execution bars (unadjusted) and the signal bars, with a `DatasetRef` for each (dataset
     id, content hash, price basis, adjustment);
   - the strategy: a `StrategySpec`, or a `FuturesSignalFunction` that returns signed whole
     contracts per bar;
   - the contract count of a spec;
   - the signal input (`ratio_adjusted` by default, or `unadjusted`);
   - a `FuturesSessionPolicy`.

   It returns the targets for `simulate_futures`, the `on_schedule` column (ADR-0093) and a
   provenance record. It lives in `experiments` because it joins `strategy_spec`, `data` and the
   Python signal functions, and only that layer may import all three.
2. **Datasets are checked against the input mode.**
   - The execution series must be `price_basis=raw`.
   - `ratio_adjusted` needs an `adjusted`/`ratio` signal dataset.
   - `unadjusted` needs a raw one.
3. **Alignment is exact, row by row.** The two frames must have the same height, the same strictly
   increasing `event_time` and the same `contract` on every row. The first mismatch is refused with
   its row, timestamp and both values. Both continuous outputs of one build satisfy this
   (ADR-0086); any other pairing is refused rather than joined.
4. **Scale invariance is enforced twice when the signal is ratio-adjusted.**
   - **Statically, for a spec** (`crucible.strategy_spec.scale`). Every operand has a dimension:
     price (open/high/low/close and the price indicators), volume, dimensionless (rsi, roc), number
     or time. A comparison is refused when one side is a price and the other is not, as in
     `close > 4500`, `close > rsi(14)` or `sma(20) < volume`. Each violation is named with its rule
     path.
   - **Empirically, for a spec and for a Python function.** The decided targets are recomputed
     with the signal bars' open/high/low/close multiplied by 16 and by 1/16. Powers of two scale
     exactly in binary floating point, so scale-invariant logic gives bit-identical decisions. Any
     difference is refused at the first bar that differs.
   - **By declaration, for a Python function.** It must also declare `scale_invariant = True`.
   - **With `signal_input="unadjusted"`** both checks are skipped and recorded as
     `not_applicable`. That is the explicit option for level-based logic.
5. **The spec's futures-incompatible fields are refused, not translated.**
   - `risk.stop_loss_pct` and `risk.take_profit_pct` are refused. Brackets are ticks in the
     execution policy (ADR-0093).
   - `risk.max_holding_bars` is refused. It is not yet defined against bracket exits.
   - An explicit `stop_fill` or `sizing` is refused. The size is the contract count.
   - A `time` operand is refused.
   - A `session` block is refused. Session rules come from `FuturesSessionPolicy`, evaluated on the
     CME calendar (ADR-0091), not on an exchange calendar's 24 h block.
6. **The session rules are part of the decision.**
   - For a spec, `flat_by_close`, `exit_at` and the entry window are the calendar's masks
     (`session_rule_masks`) inside the spec's position state machine. A forced exit resets the
     state as it does on the equity path.
   - For a Python function they filter its targets, bar by bar: a forced flat is 0; outside the
     entry window a target that opens, flips or grows the position keeps the previous one, and a
     reduction is allowed.
   - On an off-schedule bar no decision is taken. The spec's rule columns are frozen there before
     the state machine runs, so an exit judged on a closed-segment print does not leak into later
     bars. For a function, the previous target is carried.
   - Two cases are refused:
     - with `flat_by_close`, a trade date whose final scheduled bar is missing, since the exit
       cannot fill inside the session;
     - an unverified session (ADR-0091), unless `allow_unverified_sessions`.
7. **Provenance record.** It holds:
   - the strategy kind and the signal input;
   - both `DatasetRef`s and the alignment range;
   - the scale-invariance outcome (static, declared, empirical factors, result);
   - the calendar table's version and SHA-256, and the session rules;
   - the off-schedule count, the unverified sessions allowed, and the contract count.

   C3b-3 writes it into the sealed run artifact.

## Alternatives considered

- **Signal on the unadjusted series by default.** Indicators would jump at every roll, so a
  moving-average crossover would fire on the roll gap. Rejected by the owner (ADR-0086).
- **Restrict only the spec, trust Python strategies.** A Python function can hide `close > 4500`.
  The declaration alone is a promise; the empirical check is the enforcement. Rejected.
- **Difference-adjusted series for level logic.** Rejected in ADR-0086. The explicit unadjusted
  input covers level logic without a third series.
- **Translate percentage stops into ticks at the entry price.** A percentage of a ratio-adjusted
  price is not a percentage of the traded price. Translating silently would hide which price the
  stop refers to. Refused instead (refinement B).
- **Join the two series on `event_time`.** A join would drop or duplicate rows silently when the
  builds differ. Exact alignment is refused or accepted as a whole.

## Consequences

- **Run inputs are fixed.** A futures run takes exactly: two datasets of one continuous build, a
  scale-invariant strategy (or an explicit unadjusted signal), tick brackets, and session rules on
  the CME calendar.
- **The equity path is unchanged.** `spec_signal` and `_walk` are unchanged. `spec_positions` is an
  additive wrapper.
- **The check costs two extra signal passes.** It is not optional.
- **Open:** `max_holding_bars`, `time` conditions and percentage-of-traded-price stops in the
  futures path are deferred.
