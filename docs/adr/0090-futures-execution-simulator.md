# ADR-0090: A futures execution simulator in contracts and dollars: causal fills, tick costs, brackets, causal rolls

Status: accepted (2026-11-17). The owner decided points 1-8 below after a proposed draft (which
valued rolls at `reference_time`; the owner made causal roll execution the default and the
reference prices a labelled approximation). It adds a new path; no existing engine, config,
artifact or golden fixture changes. The wiring (strategy spec to target contracts, CLI, run
manifest) is a second step of milestone C3.

## Context

Fathom's work order, milestone C3, asks for: a signal at the close of bar t executed at the open of
t+1 by default, any other policy declared; a stop and a target touched by the same bar resolved as
the worse case (the stop), recorded in the manifest; commission per contract, spread and slippage in
ticks; tick size and point value per instrument. The use case is intraday ES/NQ/YM/RTY/NKD on
1-minute bars (ADR-0085..0088) under prop-firm rules stated in dollars (milestone C7).

What exists does not fit it. The event-driven engine fills at the next bar's open and knows futures
multipliers and margins (ADR-0033, ADR-0050), but its replay feed cannot hold 5.7 million minute bars
per root. The vectorized engine (ADR-0035) holds **weights**, compounds close-to-close returns and
charges costs in basis points of turnover: a signal at close t earns from close t, so in practice it
executes at the signal bar's close; on minute futures the difference sits across the daily
maintenance break and the weekend. ADR-0082 resolves a stop and a target in one bar as the stop on
the strategy-spec path. The continuous series (ADR-0086) carries the contract that printed each bar
and a rolls table; the roll's cost was a known gap.

### Measurements on the real data (2026-11-17, throwaway scripts)

- **Tick grids.** Every open, high, low and close of the five `*_1m_raw` datasets (28.3 million
  per-contract bars, 2010-06-06 to 2026-11-11; RTY from 2017-07-09) lies on the tick grid below.
- **Roll reference vs the old contract's last bar.** The roll's `reference_time` is the old
  contract's last bar in the continuous series in 65 of 66 ES/NQ/YM rolls and 36 of 37 RTY rolls; for
  NKD in 41 of 66 (up to 49 minutes earlier). `reference_time` lies *inside* the session whose volume
  decides the roll, i.e. before the roll is knowable.
- **Causal roll execution** (decision 6): the first minute at or after the decision (the end of the
  deciding session) at which both contracts have a raw bar exists for all 301 rolls. It is the first
  bar of the effective session in 66/66 ES, 65/66 NQ, 65/66 YM, 36/37 RTY rolls (the others: 1-2
  minutes later) and 31/66 NKD rolls (the others up to 87 minutes later; the old NKD contract is thin
  on its last session).
- **Error of the reference-price approximation**, per contract held through a roll (the change of
  the calendar spread between `reference_time` and the causal execution): mean absolute / maximum
  ES 2.3 / 9 ticks ($28.79 / $112.50), NQ 12.3 / 65 ticks ($61.52 / $325), YM 10.2 / 77 ticks
  ($51.06 / $385), RTY 9.6 / 67 ticks ($47.84 / $335), NKD 2.7 / 18 ticks ($67.80 / $450).

## Decision

1. **A dedicated contract-based simulator**, `crucible/execution/futures_sim.py`. Input: one
   continuous series per root (unadjusted, `CONTINUOUS_BAR_SCHEMA`), its rolls table, the raw
   per-contract bars (for the roll legs), a **signed whole-contract target per bar** decided at that
   bar's close, the contract spec, the cost schedule and the policy. Output per bar: the held
   contract, position, realized and unrealized P&L, costs by kind, balance (initial capital +
   realized - costs) and equity (balance + unrealized), in USD; a fills table and a rolls table. No
   compounding: contract counts are explicit. The weight-based vectorized engine is unchanged.
   **Prop-firm rules are a separate, versioned component** (milestone C7) that reads this output;
   the simulator knows nothing of them.
2. **Fill timing.** Default `next_eligible_bar_open`: the target decided at the close of bar t is
   traded at the open of the next bar at which the held contract trades. Gaps (maintenance break,
   weekend) belong to the position held through them. `signal_bar_close` (trade at the close that
   produced the signal) is an explicit alternative, recorded, and documented as optimistic: it
   assumes the close you observed is a price you can still trade.
3. **Costs per contract per side, in USD**: `commission + exchange_fee + clearing_fee +
   regulatory_fee + (spread_ticks / 2 + slippage_ticks) x tick_value`. `commission` is required (no
   default); the three fees default to 0 (an all-in commission includes them). `spread_ticks` and
   `slippage_ticks` default to 1 and are recorded as **uncalibrated assumptions**. A schedule is per
   root and may override spread/slippage by session window (Chicago wall clock of the fill). A
   schedule that declares `prices_include_spread` must have `spread_ticks = 0` (refused otherwise,
   so a spread is never counted twice). A target (limit) fill pays commission and fees only: its
   price is the limit itself.
4. **Contract specifications** in a versioned table, `crucible/data/futures_specs.py`: per root the
   tick size, the point value, the tick value, currency, exchange, source, the effective date
   range, plus the table's version, retrieval date and SHA-256 of its canonical form. Values (owner
   decision, CME outright contracts; CME's pages refused automated access, so the source names the
   product page and no URL is asserted): ES 0.25 / $50 ($12.50 per tick), NQ 0.25 / $20 ($5.00), YM
   1.00 / $5 ($5.00), RTY 0.10 / $50 ($5.00), NKD 5.00 / $5 ($25.00). The values were supplied by the
   owner, not fetched from the URLs; the effective ranges start at the first raw bar, the range over
   which the tick grids were verified. Execution prices are refused off the tick grid
   (`DataQualityError`): only raw, tradable contract prices are execution prices; an adjusted series
   may feed signals but never fills. Arithmetic: prices in integer ticks, money in integer
   micro-dollars, returned as `Decimal(38, 6)`.
5. **Brackets in ticks from the actual execution price**, evaluated intrabar on OHLC from the fill
   bar on (a market fill is at the open, so the whole fill bar is after it). A bar touching both
   levels exits at the stop. A stop is a stop-market order: it fills at the level, or at the open when
   the bar gapped through it, and pays spread and slippage. A target is a limit order: it fills only
   when the price trades **through** it by `target_fill_through_ticks` (default 1) and fills at the
   limit, never at a better gap price. Levels are anchored to the fill that opened (or flipped) the
   position; adding or reducing keeps them; a roll shifts them by the executed roll spread so the
   risk in points is unchanged. Re-entry after a bracket exit is configurable: default
   `require_signal_reset` (flat until the decided target changes), or `allow_immediate`.
6. **Rolls are two trades, executed causally by default.** The decision is known at the roll's
   `event_time` (the end of the deciding session). Strict mode (`roll_execution: causal`, the
   default) closes the old contract and opens the new one at the first minute at or after the
   decision at which both contracts have a raw bar, each at that bar's open, paying the costs of two
   fills per contract. Until then the position stays in the old contract, marked and bracketed on the
   old contract's raw bars. The price difference between contracts is never P&L. No such minute ->
   strict mode refuses (`DataQualityError`). `reference_approximation` values the roll at
   `reference_time` prices instead; it is labelled, marks every result `strict_execution: false`, and
   is the fallback (flagged `unverified`) only when strict is off. The rolls output reports, for every
   roll, the decision time, the executed time and prices, the delay, and the reference-price error in
   ticks and USD per contract.
7. **The execution policy is recorded** (`execution_policy()`): simulator version, fill timing,
   intrabar rule, bracket and re-entry settings, the cost schedule with its uncalibrated flags, the
   spec table version and hash, the roll execution mode; the per-roll raw timestamps are in the rolls
   output. The run manifest (second step) stores it as fields.
8. **Prop-firm rules** (daily loss, trailing drawdown, contract limits, balance vs equity,
   unrealized P&L, consistency, minimum trading days, payouts) are a separate configurable, versioned
   component in milestone C7, not part of execution or accounting.

## Alternatives considered

- **Extend the weight-based vectorized engine.** Rejected: weights converted to contracts at each bar
  is rounding plus compounding the prop-firm rules do not use, and every existing vectorized result
  would need a compatibility story.
- **Minute bars on the event-driven engine.** Rejected for now (memory and speed at 5.7 million
  bars); C5's multi-fidelity can promote a short window to it.
- **Rolls at `reference_time` prices by default** (the draft). Rejected by the owner: those prices
  precede the decision. Kept only as the labelled approximation; its error is measured above.
- **Roll at the first bar of the effective session from the continuous series alone.** Rejected: the
  old contract's price there is not in the continuous series, and for NKD the old contract often has
  no bar in that minute (35 of 66 rolls).
- **A YAML spec file.** Rejected: a Python table ships in the wheel with no loader and is hashed the
  same way.

## Consequences

- C7 gets realized, unrealized, balance and equity per bar in USD, and fills with their kinds.
- The simulator is a sequential loop over bars (brackets and rolls need state): correct first, with
  hand-computed tests; speed is a later concern behind the same function.
- The signal producer is outside the simulator: the strategy-spec position times a contract count is
  the first producer (second step), the DSL (C4) the next.
- Lookahead: a target decided at bar t is applied at t+1 at the earliest (at t's close only under
  the declared `signal_bar_close`); brackets read only the bar they act on; a causal roll trades only
  at or after its decision.
