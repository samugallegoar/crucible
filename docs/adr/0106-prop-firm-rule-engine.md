# ADR-0106: Generic prop-firm rule engine — sourced versioned rulesets, bar-by-bar account overlay inside the futures simulation, conservative OHLC breach semantics, rule coverage

- **Status**: accepted
- **Date**: 2026-11-21

## Context

C7 is the prop-firm milestone. The prop-firm simulator is the reason Crucible exists, so the owner
ruled that financial and operational correctness takes precedence over the number of firms or the
speed of delivery. C7a, this ADR, is the generic engine. The six firms' rulesets and the attempt
statistics are C7b (ADR-0107). Perturbation, cuts and the verdict methodology are C7c, C7d and C7e.

ADR-0090 decision 8 put prop-firm rules in "a separate configurable, versioned component that reads
the simulator's output". Reading the output afterwards is not enough. A breach liquidates the
account, a soft daily loss locks trading until the reset, and a contract limit resizes an order.
Each of these changes the path the simulation takes from then on. **The owner ruled that the rules
are enforced bar by bar inside the simulation.**

The owner's binding decisions for C7:

1. **No firm values in the engine.** Every rule value is loaded from versioned, sourced ruleset
   data. The engine knows rule *kinds*, never a firm.
2. **Intrabar semantics: `high_before_low_conservative`, applied per rule.**
   - Intraday trailing updates its high-water mark with the bar's favourable extreme before it
     tests the adverse one.
   - EOD trailing updates only by the firm's end-of-day balance or equity rule.
   - A daily loss limit has its own reset and evaluation semantics.
   - A static drawdown never trails.
   - A breach triggers **market liquidation** with exit costs and adverse slippage, never a
     guaranteed fill at the threshold. A bar that opens beyond the threshold liquidates at the
     open.
   - All of this is documented as a conservative OHLC approximation.
3. **Rulesets stay `unverified` until the owner confirms each one.** Every rule value carries an
   attribution: official URL, exact quotation, page snapshot hash, retrieval timestamp, `as_of` and
   effective dates. A ruleset distinguishes firm, product, account size, phase, platform or vendor,
   add-ons and jurisdiction. Old versions are immutable; a change is a new version.
4. **Unmodeled rules are declared, never ignored.**
   - Every unmodeled rule is listed as `not_modeled`, with a materiality.
   - An immaterial rule produces a warning.
   - A material rule prevents a full pass-probability claim; a conditional estimate may be
     reported, labelled conditional on the modeled rules only.
   - A critical rule blocks a definitive verdict.
   - The schema carries `rule_coverage`, `evaluation_status` and `material_unmodeled`.

Time constraints carry over. Market data stays strictly before 2025-01-01 and the vault (ADR-0105)
stays closed. A ruleset's `as_of` is recorded independently of the data window, and current rules
applied to pre-2025 data are labelled a **counterfactual application**.

## Decision

### 1. Where it lives

- **`crucible/prop/`** is a new package in the layer of `risk` and `strategy`.
  - It imports `execution` and `data` (below it) and nothing above.
  - `experiments` (C7b) imports it.
- **The execution layer stays firm-agnostic.** `simulate_futures` gains one optional argument,
  `account: AccountOverlay | None`. The Protocol is defined in `crucible/execution/interfaces.py`.
  - With `account=None`, the simulation is identical to today, byte for byte. Every existing
    golden and fixture stays unchanged.
  - With an overlay, the simulator calls it at fixed points of each bar (section 3). It applies what
    the overlay returns: a resized target, a liquidation, a lock, or the end of the account.
- **`crucible/prop/` contains:**
  - `ruleset.py`: the Pydantic models and the loader.
  - `rules.py`: one evaluator per rule kind.
  - `overlay.py`: the `AccountOverlay` implementation that combines the rules.
  - `attempt.py`: one attempt over one start date.
  - `coverage.py`: the rule coverage and the evaluation status.
- **A test asserts the engine is firm-agnostic.** No firm name, firm URL or firm-specific number
  appears in `crucible/prop/` or `crucible/execution/`.
- **C7a ships synthetic rulesets only,** under `tests/fixtures/prop/`. Their attributions are
  marked `synthetic: true`, and a synthetic ruleset can never be `verified`.

### 2. The ruleset (data, versioned, sourced)

A ruleset file is YAML that validates into `PropRuleset`, with `schema_version` 1.

**Identity.** These fields identify the ruleset:

- `ruleset_id`;
- `version`, an integer;
- `firm`, `program` (the product), `account_size_usd`, `platform`, `addons` (a sorted list) and
  `jurisdiction`;
- `as_of` (the date the rules were read);
- `effective_from` and `effective_to`;
- `instruments`, the roots allowed, each with a `contract_weight` for mini/micro equivalence (for
  example, 1 for a mini and 0.1 for a micro).

**Content hash.** `ruleset_sha256` is the canonical hash of the content. Old versions are
immutable: a loader that finds two files with the same `(ruleset_id, version)` and different hashes
refuses. A registry file lists every version with its hash, and a new version may not reuse a
number.

**Verification.**

- `verification.status` is `unverified` or `verified`.
- `verified` requires `verification.confirmed_by`, `confirmed_at` and `confirmation_note`, and
  every rule must carry a complete attribution.
- The engine never sets `verified`. Only an edit of the data file by the owner does. C7b adds a
  CLI step that records the owner's confirmation but cannot be run by the agent; it follows the
  ADR-0105 TTY rule.
- Results carry the status. An `unverified` ruleset makes every result `unverified_ruleset: true`.

**Phases.** `phases` is an ordered list, for example `evaluation_1`, `evaluation_2` and `funded`.
Each phase has:

- `kind`: `evaluation` or `funded`;
- `starting_balance_usd`;
- `rules`: a list of typed rules (section 4);
- `pass_conditions`, for an evaluation phase;
- `max_calendar_days` or `max_trading_days`, or null for no limit;
- `fees`.

**Attribution.** Every rule, pass condition, fee and payout term carries `source`:

- `url`;
- `quote`, the exact supporting quotation;
- `snapshot_sha256`, the hash of the saved page;
- `retrieved_at`, a UTC timestamp;
- optionally `section`.

The ruleset's `as_of` and effective dates sit beside these.

**`not_modeled`.** A list of entries, each with `rule`, `description`, `materiality`
(`immaterial`, `material` or `critical`) and `source`. A firm rule that the vocabulary below cannot
express **must** be listed here; it cannot be silently dropped.

### 3. The overlay inside the simulation: call order per bar

The simulator already keeps balance (initial capital plus realized P&L minus costs) and the open
lots, so equity at any price `p` is `balance + Σ lot.qty × (p − entry) × tick_value`. The book is
always one-sided, because FIFO closes opposing lots first. Equity is therefore linear in price,
with slope `position × tick_value`, and the price at which equity crosses a threshold can be solved
exactly.

**Bar `i`, with an overlay.** Steps 1 to 4 are new. Steps marked "as today" are the existing ones.

1. **Day boundary.** If bar `i` starts a new rule-day for a rule, that rule resets.
   - The rule-day comes from the rule's own reset time and time zone, for example the 17:00 CT
     Globex boundary.
   - The daily-loss reference is the balance or equity at the reset, whichever the rule declares.
   - A soft-daily-loss lock lifts.
   - EOD trailing has already updated at the previous day's close (step 8).
2. **Gap at the open.** The overlay tests equity at the bar's open with the position carried in.
   - If any threshold is crossed, it orders a liquidation at the **open**: a market order paying
     spread and slippage at the open, plus `liquidation_extra_slippage_ticks`.
   - A hard rule ends the account. A soft rule locks trading until its reset.
   - Nothing else happens in this bar.
3. **Admission (roll, then signal fill at the open, as today).** Before a pending target trades,
   the overlay's `admit` returns the target it allows.
   - The contract limit and the scaling plan apply, by contract weight, with
     `on_excess: clip | reject`.
   - A lock, a breach or a closed account forces 0.
   - Inside the forced-flat window, an entry cannot increase exposure.
   - A resize is recorded as an overlay event with the requested and the allowed quantity.
   - A roll is never refused, because it keeps the position.
4. **Intrabar path, `high_before_low_conservative`.** First, the **favourable extreme** in equity
   terms: the high for a long, the low for a short. At that price the overlay updates the intraday
   high-water marks (intraday trailing and any intraday equity peak a rule declares).
   Then the **adverse path**, from the open to the adverse extreme:
   - The overlay computes each active threshold's breach price, given the updated marks.
   - It merges them with the lots' touched stop prices in the order the adverse path reaches them.
   - It walks that order:
     - A stop fills as today, as a stop-market order at its level or at the open if gapped.
     - Each stop changes the position and the balance, so the remaining breach prices are
       recomputed.
     - When the price reaches a breach price with a position still open, everything left is
       liquidated **at the breach price rounded to the tick against the strategy** (floor for a
       long, ceiling for a short), as a market order paying spread, slippage and
       `liquidation_extra_slippage_ticks`.
   - **Targets.** If any stop **or any breach price** is touched in the bar, no target fills in
     that bar. This extends the existing stop-first rule.
   - **Joint pessimism.** The marks updated at the favourable extreme and the adverse touch are
     applied together, even when no single real path inside the bar produces both. That is the
     documented conservative OHLC approximation: an upper bound on harm, not a path claim.
5. **Brackets (as today).** Brackets run inside step 4 when an overlay is present, and unchanged
   when it is not.
6. **Forced flat time.** A rule declares a clock time in its own time zone.
   - The first bar whose interval contains that time, or that opens at or after it within the same
     rule-day, liquidates any position at its **open**, as a market order.
   - No entry is admitted until the rule's reopen time.
   - If the rule says holding past the time is a violation (`consequence: fail`), the account
     fails instead.
7. **Decide (as today).** The decided target becomes pending. Admission happens at the next open,
   step 3.
8. **Close and end of day.**
   - Equity and balance are marked at the close.
   - If bar `i` is the last bar of a rule-day, the overlay applies the EOD rules:
     - EOD trailing updates its high-water mark from the declared basis (`balance` or `equity`) at
       that close. It never uses an intraday high unless the rule declares it.
     - The EOD threshold check runs for every threshold rule declared `evaluated: eod`. A breach
       found there is liquidated **at that bar's close**, as a market order on the close cost
       tables plus the extra-tick cost, not at the next open.
     - Day statistics are recorded for the minimum-days and consistency rules.
     - Pass conditions are evaluated, if the phase evaluates them at EOD.
   - "Last bar of the rule-day" is known causally from the calendar's scheduled session end, never
     from the next bar's existence.
9. **Phase transitions.**
   - When the pass conditions hold, the phase is passed at that instant. An open position is
     flattened at that bar's close as a recorded `phase_flatten` market fill in the passing phase.
   - The next phase starts a fresh, flat account at the next bar with its own
     `starting_balance_usd`, or the attempt ends. The strategy re-enters only after its decided
     target changes (a signal reset), so the new account never joins a trade already in progress.
   - A failed account stops all trading: later targets are ignored, and the account is recorded as
     closed.

The overlay never reads a bar after `i`. It holds state in a `Snapshottable` object, so a
checkpoint can resume it (AGENTS.md §5).

### 4. Rule vocabulary (generic kinds; every value comes from the ruleset)

| Kind | Parameters | Semantics |
|---|---|---|
| `profit_target` | `amount_usd`, `basis: balance\|equity`, `evaluated: eod\|intraday`, `require_flat` | Pass condition: the basis reaches `starting_balance + amount`. |
| `static_drawdown` | `amount_usd`, `basis: equity\|balance`, `evaluated: intraday\|eod` | Threshold `starting_balance − amount`. Never trails. |
| `trailing_drawdown` | `amount_usd`, `mode: intraday\|eod`, `evaluated: intraday\|eod`, `basis`, `lock: {at_balance_usd \| at_offset_usd, locked_threshold_usd \| locked_offset_usd} \| null` | Threshold `hwm − amount`. The high-water mark updates intrabar on the favourable extreme (intraday) or at the rule-day close (EOD). Once the threshold reaches the lock, it stays there. |
| `daily_loss` | `amount_usd \| pct_of_reference`, `reference: day_start_balance\|day_start_equity\|prior_eod_balance`, `basis: equity\|balance`, `reset: {time, tz}`, `evaluated: intraday\|eod`, `severity: soft\|hard` | Threshold `reference − amount`. Soft: liquidate and lock until reset. Hard: fail. |
| `max_contracts` | `limit` (weighted) or `per_instrument`, `on_excess: clip\|reject` | Applied at admission (step 3) and checked as an invariant after every fill. |
| `scaling_plan` | `steps: [{min_profit_usd, max_contracts}]`, `evaluated: eod`, `basis` | The contract limit for the next rule-day, from that day's EOD basis. |
| `flat_by` | `time`, `tz`, `reopen`, `consequence: auto_liquidate\|fail` | Step 6. |
| `min_trading_days` | `days`, `day_counts_if: {min_trades \| min_abs_pnl_usd}` | Pass condition. |
| `consistency` | `max_day_share`, `measure: best_day_profit/total_profit`, `applies_to: pass\|payout` | Pass or payout condition. |
| `time_limit` | `max_calendar_days \| max_trading_days` | The end of a phase without a pass is a timeout. |
| `fee` | `kind: evaluation\|activation\|reset\|monthly`, `amount_usd`, `when` | Attempt cost accounting. Never written into the trading ledger. |
| `payout` | `min_days_since_last`, `min_profitable_days`, `buffer_usd`, `split`, `min_usd`, `max_usd`, `max_payouts`, `threshold_after_payout: unchanged\|trail_from_new_balance` | Funded phase, evaluated at EOD. `withdrawable = balance − (base + buffer)`, and `gross = min(max_usd, withdrawable)` when it is at least `min_usd`. The balance drops by `gross` and the trader receives `split × gross`. `base` stays the starting balance (`unchanged`) or becomes the post-payout balance (`trail_from_new_balance`). Whether the trader takes an eligible payout is a policy of the attempt (`max_eligible` or `none`), not a firm rule. |

**`evaluated` is required on every threshold rule** (static, trailing, daily loss), with no default: when a threshold is tested is firm semantics, so the ruleset must state it. For trailing, `mode` says when the high-water mark moves and `evaluated` when the threshold is tested; EOD mode with intraday evaluation is expressible.

**Extra liquidation ticks are a cost, not a price.** A liquidation fills at the breach price, the open or the close, always inside the bar's range (AGENTS.md §9). `liquidation_extra_slippage_ticks` is charged as dollars in the fill's slippage.

**Adding a kind.** It takes a new evaluator plus a schema version. A firm rule that does not fit an
existing kind goes into `not_modeled`. The engine never approximates a rule it cannot represent.

### 5. Attempt result and coverage

`simulate_attempt(...)` runs one attempt from one start trade date. It takes the bars, targets,
rolls, spec and costs of a futures run (ADR-0095), a ruleset and `max_horizon`. It returns an
`AttemptResult` with these fields:

- `outcome`: `pass`, `fail`, `timeout` or `censored`.
  - `censored` means the data ended before the attempt resolved, and it is its own class.
- `phase_outcomes`.
- `breached_rule` and `breach_time`.
- `days_to_pass`, in trading and calendar days.
- `min_buffer_usd`, the smallest distance between equity and any failure threshold, with where it
  occurred.
- `fees_usd`, `payouts_usd` and `net_cash_usd` (payouts minus fees).
- `overlay_events`: resizes, rejections, liquidations, locks and resets, each with time and reason.
- `rule_coverage`: one row per firm rule, with `modeled` or `not_modeled`, its materiality and
  source.
- `evaluation_status`:
  - `complete` if no rule is unmodeled, or only immaterial ones;
  - `conditional_on_modeled_rules` if any material rule is unmodeled;
  - `blocked` if any critical rule is unmodeled.
- `material_unmodeled` and `warnings`.
- `ruleset_id`, `version`, `ruleset_sha256`, `verification_status`, `unverified_ruleset`, the
  ruleset's `as_of` and effective dates.
- The data window, and `counterfactual_application: true` when the data window precedes the
  ruleset's `effective_from`. That is every pre-2025 run under current rules.
- `semantics: "high_before_low_conservative"`, and the liquidation assumptions.

There is no pass probability in C7a. Starting attempts on every eligible trade date, the
overlapping-attempt block bootstrap and right censoring as a class are C7b. **No threshold or
verdict exists in C7a or C7b.** The verdict is C7e.

### 6. Entry points in C7a

- `crucible prop validate <ruleset.yaml>` checks a ruleset. It reports identity, hash, verification,
  coverage and warnings, and changes no file.
- `crucible schema --kind prop-ruleset|prop-attempt`.
- The MCP tools `crucible_prop_validate` and `crucible_prop_schema`.
- Running an attempt from a futures run config and the attempt artifacts are C7b, where the start
  sequence gives them meaning. C7a's `simulate_attempt` is a library function, tested by hand.

## Amendment (2026-11-23): breach on fill and cost postings

The Topstep review (E2, F3/F4) found two engine behaviours the rules do not support. Both are
fixed here; neither changes a ruleset value.

**1. A threshold crossed by realized P&L or by costs fails at that instant, even when flat.**

The breach test solved the PRICE at which an open position's equity touches a loss threshold. In
the reference run a round turn's exit fill and its costs left the FLAT account at 47,992.40,
below the 48,000.00 maximum loss limit, and no breach was recorded: a flat book has no price to
solve. The account kept trading and failed eight minutes later on the next position's adverse
extreme. A loss the account has already taken is not a loss it may still trade through.

- Every loss threshold declared ``evaluated: intraday`` (trailing, static or daily loss, on any
  basis that includes realized P&L or costs) is now tested immediately after every fill and every
  cost or fee posting, FLAT OR NOT: the basis is the post-fill one, the fill's own commissions,
  spread and slippage included.
- A crossing, with the rule's own comparison (``<=`` for a floor, so equality breaches), is a
  breach at that fill's timestamp. The breached value is the post-fill basis at that instant.
- When flat, nothing is liquidated: the account simply takes no further entries. When a position
  remains, it is liquidated at the fill's own price — the instant the account crossed — with the
  fill's costs, through the existing breach path (``pending_liquidation`` in the overlay, consumed
  by the simulator right after the fill that set it).
- ``evaluated: eod`` thresholds are unchanged: still tested at the rule-day's close alone, so an
  intraday dip that recovers is not a breach.
- Consequences of pessimism (AGENTS.md section 1.4): the earliest provable instant wins, so an
  attempt that used to fail on a later bar now fails on the fill that crossed the threshold; and
  ``min_buffer`` records the post-fill basis, which is why a breach liquidation now reports the
  liquidation's own costs as the worst the account got (``test_intraday_trailing_joint_pessimism``:
  -20.75 rather than the pre-cost 0).
- ``AccountOverlay.fill`` gained the fill's own ``time_ns`` and the simulation calls
  ``take_pending_liquidation()`` after booking a fill. With ``account=None`` nothing changes: the
  plain simulation is byte-identical.

**2. A blocked entry names the rule that blocked it.**

Inside the 15:10-17:00 CT ``flat_by`` window an entry was recorded as ``resize requested 1,
allowed 0`` under ``maximum_position_size``. The account was kept out correctly but the event named
the wrong rule, so an artifact read "the size limit clipped" where the truth was "the session's
close window refused the entry".

- ``admit`` now collects the rules that REFUSE the entry, and records one event per rule, sorted by
  rule id: ``session_entry_block`` for a session-close ``flat_by`` window (the owner's name), with
  the window's own id and a reason (``entry blocked: flat_by_1510_ct until 17:00 CT``);
  ``news_entry_block`` for a news window (``block``, or ``all_trading`` which freezes any change);
  ``entry_blocked`` for a lock.
- The blocking logic (``_entry_blockers``) and the rejection reason are separate: the logic answers
  which rules refuse, the reason says why in the firm's own terms.
- ``maximum_position_size`` (any contract limit or scaling plan) is recorded only when the SIZE
  limit itself changed the size, as a ``resize`` under that rule. A legal size refused by a window
  never appears under the size rule again.

**What this does not change.** The breach order (a breach touched in a bar beats a pass in the same
bar), the EOD timing, the pessimistic gap test at the open, the liquidation cost tables, and every
golden fixture of the plain simulation.

## Alternatives considered

- **Post-process the simulator output (the ADR-0090 plan).** Rejected by the owner. A breach,
  lock or resize changes the path, and a post-processor would score a path the account could not
  have traded.
- **Put the rules inside `execution/futures_sim.py`.** Rejected. It would mix firm concepts into
  execution and grow the simulator file. A Protocol hook keeps execution generic and makes the
  no-overlay path provably unchanged.
- **Assume a fill at the threshold.** Rejected by the owner. A breach is a market liquidation.
- **Treat the favourable and adverse extremes as one consistent path, such as O→L→H→C chosen per
  bar.** Rejected. The real order inside the bar is unknown. The conservative joint rule is the
  owner's choice, and documented as an approximation.
- **Hardcode the common values, such as a $2,500 trailing drawdown.** Forbidden (decision 1).
- **Drop rules the engine cannot express.** Forbidden (decision 4). They go into `not_modeled`
  with a materiality.

## Consequences

- `simulate_futures` gains an optional overlay. All existing results, goldens and run ids are
  unchanged when it is absent, and a test proves it on the existing fixtures.
- The attempt result carries the rule coverage, the evaluation status and the counterfactual label
  from the first stage.
- A rule kind not yet in the vocabulary forces a `not_modeled` entry, which may block or condition
  a claim. It never silently weakens one.
- The joint-pessimism rule can fail an account that a real path would have kept. That bias is
  declared and in one direction only: against passing.
- Liquidation at the rounded breach price, plus spread, slippage and the extra ticks, is still an
  approximation. A fast market can fill worse. C7c stresses `liquidation_extra_slippage_ticks`.
