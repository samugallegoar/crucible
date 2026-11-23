# Module `crucible/prop` — prop-firm simulation (ADR-0106, ADR-0107)

## What exists

- **`rules_schema.py`**: the Pydantic v2 rule models of schema version 2, split out from the
  loader so the file stays readable.
  - `Attribution`: `url` (null only for an owner-supplied value), `provided_by` (`owner`),
    `quote`, `snapshot_sha256` (64 hex), `retrieved_at` (UTC), optional `section`, `synthetic` —
    and, for a value that is printed only inside an image, the image block
    `image_snapshot_sha256` (the file's own sha256), `image_path` (relative to the private snapshots
    root: never absolute, never through `..`), `transcription` (the values exactly as printed),
    `transcribed_by` and `transcribed_at` (UTC). All five are present together or absent together.
  - `Assumption {name, rationale, assumption_kind}` and the per-rule `evidence` field:
    `official_quote | owner_provided | assumption | conflict_resolution |
    official_image_transcription`; a rule with `evidence: assumption` must carry its named
    assumption, `official_image_transcription` requires the source's image block, and a source that
    carries one must declare that evidence.
  - `Commissions {status: known|unknown, components: {exchange, clearing, nfa, other each
    {status: included|excluded|unknown, evidence: official_quote|owner_provided|not_stated, text}},
    per_side_usd: {ROOT: Decimal}, platform, evidence, source}`. Unknown is never zero; a sentinel
    (>= 1,000,000 USD) is refused. All four `components` keys are **required, with no default**: an
    `included` or `excluded` component needs a quotation that says so, and `unknown` needs
    `evidence: not_stated` plus a note naming what was checked. A missing key is refused, and so is
    the old `includes_exchange_and_regulatory_fees` flag, by name (ADR-0107 section 8 and its
    2026-11-22 amendment).
  - `Conflict {conflict_id, rule_id, field, selected_value, alternatives [{value, source}],
    selected_source, rationale, applicability_checked: true}`.
  - `Verification` (a fact about a hash, never part of it) and `ResetClock {time, tz}` with **no
    default**: the rule-day boundary is a firm's declaration, not the engine's guess.
  - The typed rules as a discriminated union on `kind`:
    `ProfitTargetRule`, `StaticDrawdownRule`, `TrailingDrawdownRule` (with `TrailingLock`,
    including `on: [hwm, first_payout]` as a list of triggers and `hwm_basis`), `DailyLossRule`
    (amount, percentage, balance tiers, or a ratchet on peak profit), `MaxContractsRule`,
    `ScalingPlanRule` (`steps`, where a step is keyed on `min_profit_usd` - profit since the
    phase's start - or `min_balance_usd` - the absolute balance at the rule-day's close -, the FIRST
    step may omit its threshold and is then the FLOOR rung, and a balance ladder takes its boundary
    from `comparison`: `>=` keeps a balance exactly on a threshold in the upper rung, `>` keeps it in
    the lower one; plus `on_excess: clip|reject`), `FlatByRule` (a fixed clock or
    `minutes_before_session_end`), `MinTradingDaysRule` (with `unit` and a composable
    `DayCountsIf`), `ConsistencyRule` (with `window` and separate `numerator_window` /
    `denominator_window`), `PayoutRule` (the C7b payout vocabulary), `TimeLimitRule`, `FeeRule`
    (evaluation, activation, monthly, reset), `DailyProfitCapRule`, `InactivityRule`,
    `ActivityRequirementRule`, `NewsRestrictionRule` and `ComplianceRule`.
    - `ConsistencyRule.window` is the shared window; `numerator_window` (which day is the best:
      `all_time` or `since_last_payout`) and `denominator_window` (which profit it is shared with:
      `all_time`, `since_last_payout` or `current_cycle`, the profit of the payout cycle measured
      from the balance the cycle opened at) override it separately when a firm measures the two
      differently.
    - `ActivityRequirementRule`: `days`, `window`, `unit: calendar_days|trading_days`,
      `qualifies_if {min_trades, min_abs_pnl_usd, min_pnl_usd}`, `observed`, `comparison`,
      `action: fail|close_account`. It is the mirror of `inactivity`: at least N qualifying days in
      EVERY rolling window of M days, tested once the window is full, never a gap since the last
      trade.
  - `Phase`: `phase_id`, `kind` (`evaluation` or `funded`), `starting_balance_usd`, `rules`,
    `pass_conditions`, `max_calendar_days`/`max_trading_days`, `fees`. A rule that gates the phase
    must sit in `pass_conditions` (`is_pass_condition`; a `consistency` rule whose `applies_to` is
    `payout` stays in `rules`).
  - Every rule carries its `source` and may carry `supporting_sources` (attributions that support
    its basis, timing or units WITHOUT carrying the value, so a page quote never hides in a
    description and the self-check covers it), `assumption` (the one that makes the value itself an
    assumption) and `assumptions` (further NAMED readings the value depends on: the tier boundary, a
    silent case, the excess action). Names are unique per rule and `all_assumptions()` reports them.
- **`ruleset.py`**: `PropRuleset` (`schema_version: 2`; v1 is refused with a migration message),
  the hash lock, the sidecar reader/writer and the loaders.
  - `ruleset_sha256` is the canonical JSON hash of the content **excluding** `verification`, so
    confirming a ruleset never changes its identity.
  - Verification lives in `<file>.verification.yaml` (`VerificationRecord`: hash, status,
    `confirmed_by`, `confirmed_at`, `confirmation_note`, `rules_checked`). A ruleset is `verified`
    only when the sidecar exists, its hash matches, `rules_checked` names every rule and every
    attribution is complete and non-synthetic. An in-file `verification` block is refused unless
    it is `unverified`; a tampered ruleset silently loses its verified status.
  - `load_ruleset(path)` reads one file with its sidecar; `load_registry(dir)` sorts and refuses
    two files with the same `(ruleset_id, version)`.
- **`rules.py`**: one evaluator per rule kind. `breach_price` solves the exact integer price at
  which equity touches a threshold (floor for a long, ceiling for a short); `local_day` /
  `day_instant_ns` place a rule-day from its reset clock. Each evaluator answers `new_day`,
  `favorable`, `thresholds` (intrabar), `eod` (at the rule-day close) and `pass_ok`;
  `contract_limit`/`on_excess` drive admission; `Payout.decision`/`Payout.apply` decide and record
  a withdrawal; `DailyProfitCap`, `Inactivity`, `News` and `Compliance` are the C7b evaluators.
  `build` refuses a kind without an evaluator (`not_modeled`, never approximated).
- **`overlay.py`**: `PropAccountOverlay`, the `AccountOverlay` the futures simulator calls inside
  each bar, and its `snapshot()`/`restore()` (ADR-0041). It holds the phase's rules, the rule-day
  clock, the day statistics, the lock, withdrawals, forfeits, the news windows and the
  `Lifecycle`.
- **`lifecycle.py`**: the explicit account state machine (below).
- **`news.py`**: `NewsEvent {event_id, event_type, scheduled_ns, time_known}`, `coverage_covers`,
  `events_in_window` and `unknown_time_gaps`. `time_known` is required: when the source gives the
  release date but not the time, the event never gets an invented window and its whole trade date
  is outside news coverage (reported by `event_id`, never treated as "no news"). Every event whose
  time IS known keeps its window enforced: an unknown-time event gaps only its own date, it never
  disables the timed windows for the attempt. It imports nothing
  from `crucible.data`: the calendar is ingested and documented separately (the
  economic-calendar dataset doc under `docs/data/`).
- **`scenarios.py`**: `scenarios(ruleset) -> list[RulesetScenario]` (the primary plus one per
  conflict alternative, deterministic order) and `scenario(ruleset, id)`.
- **`promotions.py`**: `resolve_promotions(ruleset, profile) -> (promoted, PromotionOutcome)` and
  `promotion_reason`. A rule may carry `promotions` (a better value for a limited offer: a doubled
  payout cap for an account bought during the offer), each naming the numeric `field` it replaces,
  its `value` or `multiplier`, the offer window and the profile facts it `requires`. Resolution is
  per RUN: a promotion applies only when every requirement is declared and matches and the
  profile's `purchase_date` falls in `[starts_on, ends_on]` (`ends_on: unknown` never continues
  past the ruleset's `as_of`); anything missing or `unknown` leaves the base value and is reported
  (`promotion <id> not applied: <reason>`). A promoted value never changes the file's hash:
  `simulate_attempt` builds its phases from the promoted copy and cites the original.
- **`costs.py`**: the per-COMPONENT execution cost. `FeeRow {component, per_side_usd,
  record_sha256}`, `ComponentFeeRow {root, fee_type, classification_dimension,
  classification_value, covers, per_side_usd, effective_from, effective_to, charge_name}` (one row
  prices exactly its root, its own classification and its dates; a row that covers several
  components is charged once; an `other` row carries its own `charge_name`),
  `ComponentFeeTable {rows, source_sha256}` (rows for one key may not overlap) and the
  `ComponentFeeSource` Protocol: `lookup(root, when, profile=..., components=[...]) ->
  FeeLookup{priced, gaps}` returns only the components it can price — a component in neither map
  was not asked for, and a component it cannot price is a reported gap with its reason, never a
  zero fee. `store_component_fees(store)` returns the `StoreComponentFees` adapter over the stored
  `exchange_fees_v1` dataset, whose every read goes through
  `crucible.data.exchange_fees.fee_rows_as_of` (per root, per participant profile, per component;
  an owner file that prices ES alone is usable).
  `CostPricing`/`ComponentCharge` are the result: one charge per component (`included`,
  `excluded_priced`, `excluded_unpriced`, `unknown`, `assumption`, and `known`/`unknown` for the
  commission), the charged USD, the gaps, and the cost status `complete | conditional |
  unavailable`. `CostAssumption` + `load_cost_assumption(path)` read the unverified, owner-provided
  YAML file (`name`, `kind`, `description`, `provided_by`, `status: unverified`, `evidence`,
  `amounts` per root) that prices exactly the gaps it names; its SHA-256 is recorded.
  `price_components(...)` is the one function that applies the order: commission, then each
  component by its declared status, then the assumption.
- **`attempt.py`**: `simulate_attempt(...) -> AttemptResult`, one attempt from one start trade
  date: phases in order, each a fresh `PropAccountOverlay` inside `simulate_futures`; outcome
  `pass`/`fail`/`timeout`/`censored`, `PhaseOutcome` per phase, `min_buffer_usd` with where it
  happened, fees broken out, `payouts` (gross, net and the `exact`/`upper_bound` label),
  `payout_policy`, overlay events, rule coverage, evaluation status, `mechanical_outcome`,
  `estimate_status` + reasons, `practical_eligibility`, `scenario_id`, the applied commissions,
  `cash_estimate_status` + reasons, warnings, ruleset identity and the counterfactual label.
- **`coverage.py`**: `rule_coverage(ruleset, news_covered=...)`, `evaluation_status`
  (`complete`, `conditional_on_modeled_rules`, `blocked`), `material_unmodeled`,
  `coverage_warnings` and `counterfactual_application`.
- **`confirm.py`**: `confirm_ruleset(path, ...)`, the owner's interactive verification: prints
  every rule, conflict and assumption and writes the sidecar only after the owner types the first
  12 hex of the content hash. It refuses without a TTY and is never exposed over MCP.
- **`index.py`**: `build_index`/`render_index` for `rulesets/prop/INDEX.json`, generated by
  `uv run python -m tools.docgen --write`; a v1 file is listed as `pending_migration`.
- **`list.py`**: `list_document`, what `crucible prop list --json` and `crucible_prop_list` print.
- **`sources.py`**: the evidence self-check. `verify_sources(ruleset, root)` refuses a citation that
  does not resolve to saved bytes and `check_sources` returns the same as a report (`SourceCheck`
  with counts and every `SourceProblem`). It hashes every file under `root`, so each attribution's
  `snapshot_sha256` must name a page that is there and its `quote` must appear in THAT page's text
  (UTF-8, entities unescaped, whitespace collapsed, tags stripped on the second pass); an image
  transcription must also resolve `image_path` under the root to a file whose sha256 is
  `image_snapshot_sha256`, and its `transcription` is never compared with page text, because the
  values are printed only in the picture. A `synthetic: true` attribution is skipped and counted.
- **`validate.py`**: `validate_ruleset_document` (`crucible prop validate`), the two JSON Schemas,
  and `listing_document`.

## The account lifecycle (ADR-0107 section 9)

States: `evaluation`, `funded_active`, `payout_pending`, `funded_locked_until_reset`, `failed`,
`passed_terminal`, `censored`. Every transition is recorded with its time, from, to and cause. The
end-of-day order is fixed:

1. EOD marks.
2. Threshold tests.
3. Pass conditions.
4. Payout eligibility.
5. Withdrawal.
6. Post-payout transitions: threshold reset, lock on the first payout, cycle counters reset.
7. Cap and consistency windows reopen.

## Scenarios (ADR-0107 section 7)

A conflict keeps both sources. `scenarios(ruleset)` returns the primary (`scenario_id: primary`,
label `official`) then one full `PropRuleset` per `(conflict, alternative)` with the id
`<conflict_id>#<index>` and label `sensitivity`. A sensitivity scenario is never an official plan
and a result computed from one reports its `scenario_id`.

## Estimate status and practical eligibility (ADR-0107 section 11)

- `estimate_status` is `unavailable` when a critical rule is unmodeled, or the commissions (or a
  fee the commission excludes) are unknown without a named `cost_assumption`; `partial` when a
  material rule is unmodeled, a news window is uncovered, a payout cap is `unknown`, or the attempt
  trades through an unsourced CME session-calendar window; `conditional` when the ruleset is
  unverified or a cost assumption was used; otherwise `complete`. Every reason is reported.
- **Session-calendar coverage.** A rule measured against the session schedule — a session-relative
  `flat_by`, the rule-day boundary, the end-of-day test — is only as good as that schedule. The CME
  table flags the sessions it could not source (`verified: False`: the 2023 holidays other than
  Labor Day, Christmas and New Year, and MLK 2024, were never archived). An attempt that trades
  through such a window reports it as `session_calendar_gaps` (`"<first>..<last>"`, the window's own
  Chicago days, which is why the 2023-11-24 session is caught: it opens on 2023-11-23), the estimate
  becomes `partial` with the reason `session calendar unsourced <first>..<last>`, and a warning says
  which rules are affected.
- `practical_eligibility` is `blocked_by_compliance` when a critical compliance rule with
  `action: block` applies to the exact `execution_mode` (`automated` or `manual`); the block wins
  over everything, because it says the account may not be traded that way at all. Otherwise, when
  at least one `effect: condition` compliance rule applies, it is `eligible_conditional` and every
  condition is listed (sorted, de-duplicated) in the result, `summary.json` and
  `attempts.parquet`: a condition is an obligation the SIMULATION cannot prove (orders only through
  the firm's API, only from the trader's own device, no HFT), so a mechanically successful attempt
  under one is a CONDITIONALLY valid pass, never a practically valid one. With no blocker and no
  condition it is `eligible`. `PracticalEligibility` (`status`, `conditions`, `blocker`) is what
  `practical_eligibility(ruleset, execution_mode)` returns.

## The per-bar order (ADR-0106 section 3)

The simulator calls the overlay at fixed points of every bar:

| # | Hook | What happens |
|---|------|--------------|
| 1 | `begin_bar` | the rule-day transition (the reset clock): the daily-loss reference resets, soft locks lift, the scaling plan takes the limit its last close chose, inactivity counts |
| 2 | `begin_bar` (gap test) | equity at the bar's open with the position carried in; a threshold already crossed liquidates at the open |
| 3 | `forced_flat` | the first bar reaching a `flat_by` instant (absolute or session-relative) or a news window that flattens liquidates at its open; no entry until the reopen time — for the session-relative form that reopen IS the session's scheduled close, so the block lasts from the flat instant to the close |
| 4 | `admit` | the target the account allows. Each rule that REFUSES the entry is recorded under its own id and reason first (`session_entry_block` for a session-close `flat_by` window, `news_entry_block` for a news window, `entry_blocked` for a lock), then the contract limit and scaling plan by contract weight (`clip` or `reject`) — a `resize` under the size rule only when the SIZE limit changed the size |
| 5 | `favorable` | the bar's favourable extreme in equity terms (high for a long, low for a short) updates the high-water marks **first** |
| 6 | `breach_prices` | each active threshold's breach price, merged with the touched lot stops, recomputed after every stop |
| 7 | `breach_filled`, `fill` | the breach consequence (hard closes, soft locks); on every fill the day statistics and inactivity, AND each `evaluated: intraday` loss threshold tested against the POST-fill basis at the fill's own price, flat included: a crossing fails at that instant and a position still open is liquidated at that fill's price (ADR-0106, amendment of 2026-11-23) |
| 8 | `end_bar` | the close mark; on the rule-day's last scheduled bar the EOD rules, an `activity_requirement` short of its qualifying days in a full rolling window (it closes the account **before** the pass conditions), the time limit, the daily profit cap, the payouts and the pass conditions. An EOD breach liquidates **at that close**; a pass with a position open flattens it **at that close** as `phase_flatten`. The time limit is tested **before** the pass conditions, so a firm's own limit ending the phase on the same close wins (the pessimistic direction). **Pass conditions are split by their declaration** (`crucible.prop.rules.pass_frequency`): an `evaluated: eod` target is tested ONLY here, on the closed trade date, and an `evaluated: intraday` one at every bar's close (its touch counts at the bar's favourable extreme) |
| 9 | `finish` | the end of the data: an unresolved attempt whose data ends inside a rule-day is `censored` |

**Joint pessimism** (`high_before_low_conservative`): the favourable extreme and the adverse touch
are both applied, even when no single path inside the bar produces both. That is an upper bound on
harm, not a claim about the path: it can fail an account a real path would have kept. The bias is
in one direction only, against passing, and it is declared.

**The liquidation model.** A breach is a market liquidation, never a guaranteed fill at the
threshold: the fill pays the bar's open (or close) spread and slippage plus
`liquidation_extra_slippage_ticks` per contract, charged as money, so a fill never leaves the bar's
`[low, high]` (AGENTS.md section 9).

## The rule kinds (schema version 2)

| Kind | Parameters | Semantics |
|---|---|---|
| `profit_target` | `amount_usd`, `basis: balance\|equity`, `evaluated`, `require_flat` | pass: the basis reaches `starting_balance + amount`; `evaluated: eod` is tested only at the rule-day's last scheduled bar (a touch lost by the close does not pass), `evaluated: intraday` at every close |
| `static_drawdown` | `amount_usd`, `basis`, `evaluated` (**required**) | threshold `starting_balance - amount`, never trails |
| `trailing_drawdown` | `amount_usd`, `mode`, `evaluated`, `basis`, `hwm_basis`, `lock {on: [hwm, first_payout], ...}` | threshold `hwm - amount`; the lock freezes it at the FIRST trigger that fires. `on` is a LIST: a bare `on: hwm` is refused |
| `daily_loss` | `amount_usd` / `pct_of_reference` / `amount_by_balance_tier` / `pct_of_peak_profit` (`non_decreasing`), `reference`, `basis`, `evaluated`, `reset {time, tz}`, `severity` | threshold `reference - amount`; soft locks, hard fails |
| `max_contracts` | `limit` (weighted) or `per_instrument`, `on_excess` | admission |
| `scaling_plan` | `steps` (`min_profit_usd` or `min_balance_usd` per rung, the first may omit it = the floor rung), `evaluated`, `basis`, `comparison` (the rung boundary of a balance ladder), `on_excess: clip\|reject` | the limit for the next rule-day, chosen at the close; a balance ladder reads the closing BALANCE (absolute tiers, no profit subtraction) |
| `flat_by` | `time`+`tz` **or** `minutes_before_session_end`, `reopen`, `consequence` | a forced-flat clock; the session-relative form follows the CME early close |
| `min_trading_days` | `days`, `unit: trading_days\|winning_days\|calendar_days\|trade_dates`, `day_counts_if` | pass condition |
| `consistency` | `max_day_share`, `measure`, `applies_to`, `window`, `numerator_window`, `denominator_window` | the best day's share of total profit, with the two windows declared separately |
| `payout` | `min_days_since_last`, `min_profitable_days`, `min_traded_days`, `min_day_profit_usd`, `window`, `buffer_usd`, `split`, `min_usd`, `max_usd: number\|unlimited\|unknown`, `max_usd_by_payout`, `max_pct_of_balance`, `max_share_of_withdrawable`, `min_new_profit_share_of_request`, `min_profit_since_last_usd`, `cycle_goal_usd`, `first_payout_after_calendar_days`, `payout_group`, `max_payouts`, `threshold_after_payout`, `set_threshold_to` | a withdrawal from a funded phase at the close |
| `time_limit` | `max_calendar_days` or `max_trading_days` | a phase without a pass times out |
| `fee` | `fee_kind: evaluation\|activation\|reset\|monthly`, `amount_usd`, `when` | attempt cost accounting only |
| `daily_profit_cap` | `amount_usd`, `action: forfeit_excess\|promote_phase`, `basis`, `evaluated` | the per-day profit ceiling |
| `inactivity` | `max_gap`, `unit`, `rolling_window`, `action: fail` | a maximum gap between trading days |
| `activity_requirement` | `days`, `window`, `unit: calendar_days\|trading_days`, `qualifies_if`, `observed`, `action: fail\|close_account` | at least N qualifying days in every rolling window of M days |
| `news_restriction` | `event_types`, `instruments`, `pre_minutes`, `post_minutes`, `scope: new_entries\|holding\|all_trading`, `flatten: before_window\|none`, `effect: block\|contract_cap` (**required**, no default), `cap_contracts` (a contract WEIGHT, like `max_contracts.limit`, required when the effect is `contract_cap`), `action` | a scheduled-event trading window: block the entry or clip the size inside it |
| `compliance` | `restriction`, `applies_to_execution: [automated\|manual]`, `materiality`, `action: block\|none`, `effect: condition` with a REQUIRED `condition` text | practical eligibility, never the mechanical account: `action: block` gates it, `effect: condition` lists an obligation the sim cannot prove |

Every rule kind requires `comparison` and `action` (its state transition) explicitly, and none of
`basis`/`hwm_basis`, the threshold, `evaluated`/`mode`/`observed`, `reset`, `comparison` or `action`
has a default: the declaration is the rule, and the C7a implicit forms (`severity`, `consequence`,
`on_excess`, `on_breach`) are gone. `evaluated` is required on every threshold rule because when a
firm tests a threshold is a firm's rule, not the engine's guess; a trailing rule's `mode` (when the
mark moves) and `evaluated` (when the threshold is tested) are separate declarations, and
`hwm_basis` is separate from `basis`. Per-rule `effective_from`/`effective_to` are informational
(a version carries a change), but a rule whose `effective_to` is before the ruleset's `as_of` is
refused: an expired rule cannot sit in a current ruleset.

## Attempts and payouts

`simulate_attempt(..., payout_policy="max_eligible"|"none", execution_mode="automated"|"manual",
news_events=..., news_coverage=..., exchange_fees=..., cost_assumption=..., resets_purchased=...,
scenario_id=...)` runs the phases in order and records the trader's choice. A payout is a
withdrawal recorded apart from trading P&L: `withdrawable = balance - (base + buffer_usd)`; the
gross is the smallest of the declared caps and `withdrawable`, and a payout happens when it is at
least `min_usd` and every gate holds. `min_new_profit_share_of_request` is one of those caps: a
request of X needs new profit since the last payout of at least `share * X`, so the policy asks
for the largest X that satisfies every term. A `payout_group` pays at most one path per close
(`max_eligible` takes the largest net). `payouts_usd` is the trader's net, `fees` breaks the costs
into evaluation, activation, monthly (per started calendar month of the attempt) and reset,
`net_cash_usd` is the payouts minus the total, and `payouts` lists every payout with its gross,
net and `exact`/`upper_bound` label.

The ruleset's commissions replace the run's fee schedule (spread and slippage still come from the
run's cost schedule). Unknown costs are never treated as zero. `commissions.components` declares,
for each of the four components (`exchange`, `clearing`, `nfa`, `other`), whether the firm's
per-side commission contains it (`included`), excludes it (`excluded`: the amount is added from the
`ComponentFeeSource`, resolved through the run's participant profile) or does not say
(`unknown`). All four keys are REQUIRED and there is no `all_in` shortcut: an `included` or
`excluded` declaration needs a quotation that says so, and `commissions.evidence` records whether
the commission figures themselves are `official_quote` or `owner_provided`. The old
`commissions.includes_exchange_and_regulatory_fees` flag is REFUSED by name, with a message naming
this block.

Every gap — an `unknown` component, an `excluded` one the dataset cannot price, an unknown
commission — makes `cash_estimate_status` `unavailable`. The only way to a number is a
`cost_assumption` FILE the run passes explicitly (`--cost-assumption`, MCP `cost_assumption`): it
prices exactly the root and components it lists, it may not override a component the ruleset
includes or the dataset already priced, an `unknown` component it prices is ADDED (worse for the
strategy), and the recorded SHA-256 names the file. Because it is a user's statement and not a firm
value, the resulting estimate is `conditional`, never `exact`.

### The kind of a cost assumption: `point_estimate` or `upper_bound`

An assumption file says what its amounts CLAIM (`kind`, REQUIRED since the 2026-11-23
owner-decision amendment of ADR-0107; `docs/GLOSSARY.md`, "Upper-bound cost assumption"):

- `point_estimate` — the owner's best single figure. It names the costs it estimates, so an amount
  that lands on a component the firm already has (an `included` one, one the fee dataset priced, a
  stated commission) is a contradiction and is REFUSED.
- `upper_bound` — an explicit, versioned ceiling (`rulesets/prop/cost_assumptions/upper_bound_v1.yaml`)
  that fills only the GAPS a firm's own sources leave, for a preliminary analysis across every firm.
  It is a table over every root and component, so an amount that lands on a cost the firm already
  has is skipped, never charged and never an error. It never prices an `included` component, never
  one the dataset priced, never a commission the firm states, and its estimate is still
  `conditional` — never `complete`.

An upper-bound run labels the artifact: `cost_bound: upper` in `summary.json` (top level and every
scenario) and in every `attempts.parquet` row, the cash statistic `lower_bound` (the cost is a
ceiling, so the net cash can only rise once real costs arrive), the pass probability's reason
`costs are an upper bound: the probability and the net cash are pessimistic (lower bounds) under
it`, and the comparability note *firms with fewer sourced cost components receive more of the
bound, so cross-firm comparisons under it are pessimistic for the less documented firms* (the bound
fills gaps, so a firm that states its costs is charged less of it). The file is hashed like a
ruleset: its `sha256` is in `rulesets/prop/INDEX.json` (an entry of kind `cost_assumption`) and in
the run's `summary.json`, sealed manifest and every attempt row. A change is a NEW version
(`upper_bound_v2.yaml`), never an edit in place once merged.

### The participant profile: classification resolved per component

A fee row does not state a participant type. It states the ONE classification dimension it needs
(`classification_dimension`) and the value it is written for (`classification_value`) — an exchange
row `cme_membership_status = non_member`, the NFA row `nfa_assessment_eligibility = fcm_member`, a
charge the source says is the same for everyone `none`/`all`. A run therefore declares a
**participant profile**: an immutable, flat mapping from dimension name (an identifier matching
`^[a-z][a-z0-9_]*$`, not a fixed enum) to value, in a YAML file
(`crucible.data.exchange_fees.ParticipantProfile`, `load_participant_profile`,
`--participant-profile FILE`, MCP `participant_profile` as an object):

```yaml
cme_membership_status: non_member
nfa_assessment_eligibility: fcm_member
```

Resolution is PER COMPONENT, and it has no default:

- a row whose dimension the profile does not declare, or declares `unknown`, makes that component a
  gap whose reason is `classification <dim> not declared`;
- a row whose stated value differs does not apply;
- `none`/`all` rows apply to every participant and need no profile entry;
- exactly one applicable row prices the component; two are refused as ambiguous; none is a gap.

There is never a fallback to "the only row there is", and the former "an NFA row prices any
participant" pass-through is gone. `other` is the one summing exception: two rows with different
`charge_name`s on one date are two distinct charges and both are added.

The profile is REQUIRED as soon as a component is `excluded`, and optional otherwise (recorded when
given). Its canonical SHA-256 goes in `summary.json`, the sealed manifest and every
`attempts.parquet` row (`participant_profile_sha256`), and it is part of the evaluation id, so two
profiles are two artifacts. Using it makes the estimate `conditional` with the reason
`participant profile declared by the run, not stated by the firm`: a profile is a run's declaration,
never a firm's statement, so it never makes a cost `complete`.

The per-side amounts are resolved at the attempt's `start_trade_date`, and a fee change the table
states inside the attempt's window is reported in `warnings` (one schedule per attempt, never a
silent mid-window change).

`cash_estimate_status` is the label on the money: `exact`, `conditional` (a named cost assumption
was used), `lower_bound` (the run's cost assumption is an `upper_bound` file: the cost is a ceiling,
so every net-cash number is the LEAST it can be), `upper_bound` (a payout cap the sources do not
state: the simulation pays what the other terms allow, so every payout amount and cash statistic is
the MOST it can be) or `unavailable`; `cash_estimate_reasons` names the gap, and `estimate_status`
is at best `partial` when a cap is unknown. An `unknown` cap is never read as `unlimited`.
`lower_bound` wins over a payout cap's `upper_bound` on the cash statistic because it applies to
every attempt of the run; the per-payout `bound` still says `upper_bound`.

## The attempt sequence (C7b, ADR-0107 section 4)

`crucible.experiments.futures_prop.run_prop_evaluation` is the only caller that runs
`simulate_attempt` in sequence: one attempt per Globex trade date of a futures run's window, over
the run's own prepared bars, targets, rolls and raw per-contract bars, with an analyst horizon H in
TRADING days and one ruleset per scenario (`scenarios="primary"` or every sensitivity scenario of
its conflicts). It classifies each attempt `pass | fail | timeout | horizon | censored`, and a
`censored` attempt is its own class: never a failure, never a pass. `classify_attempt` reads the
EVALUATION phases only, so a funded phase's own breach or timeout is a descriptive fact about a
start whose evaluation passed, not a different outcome class.

The flat-window half of a session-relative `flat_by` is enforced by the overlay and, since C7b,
in BOTH directions: a position is liquidated at the bar that reaches the flat instant
(`forced_flat`) and no entry is admitted from that instant until the session's scheduled close
(`_flat_window`), which is what `flat_by.reopen` defaults to for the session-relative form. A firm
that states its own reopen clock keeps it (the C7a form). Hand test:
`tests/unit/test_prop_flat_by_entry_block.py` on the sourced 2024-11-29 early close (18:15 UTC).

`simulate_attempt` reports `days_to_pass_trading` / `days_to_pass_calendar` from the attempt's OWN
first bar (the phase's bars are numbered from zero inside the simulation, so the offset is added
before the day counts and the pass date are read), and `PhaseOutcome.first_bar`/`last_bar` are in the
attempt's coordinates. Hand test: `tests/integration/test_prop_pass_frequency.py` and the 06-05
assertions of `tests/integration/test_futures_prop.py`.

## Interfaces

- `crucible.execution.interfaces.AccountOverlay` (Protocol) with `AccountMarks`, `BreachPrice`,
  `OverlayAction` and `OverlayEvent`; implemented by `PropAccountOverlay`.
- `simulate_futures(..., account=..., liquidation_extra_slippage_ticks=...,
  initial_blocked_target=...)` in `crucible/execution/futures_sim.py` is the only execution-layer
  coupling. With `account=None` the simulation is byte-for-byte what it always was.
- `simulate_attempt` takes a `Sequence[NewsEvent]` and a `Sequence[(start_ns, end_ns)]` coverage
  record; it imports the calendar dataset only through those values. A news rule whose declared
  event types the calendar does not carry is `not_modeled` for that attempt (material, reported by
  rule and by type in `warnings`), while every window the calendar does carry stays enforced.
- `crucible.prop.costs.ComponentFeeSource` (Protocol) with `ComponentFeeTable`/`ComponentFeeRow`
  and `StoreComponentFees`: the per-root, per-side amounts of the components a commission charges
  on top of itself. `simulate_attempt(fee_source=..., profile=...)` takes one;
  `store_component_fees(store)` is the adapter over the stored `exchange_fees_v1` dataset.
  `crucible.data.exchange_fees` owns the row contract itself: `ParticipantProfile`,
  `load_participant_profile`, `FeeLookup`, `resolve_component_rows` (the one resolution rule, used
  by both the stored table and an in-code `ComponentFeeTable`) and `fee_rows_as_of`.
- `crucible.prop.costs.ComponentFeeSource`'s stored implementation takes the dataset NAME
  (`store_component_fees(store, dataset="exchange_fees_v1")`, `StoreComponentFees(dataset=None)`),
  so a consumer that pinned a version reads that version and the content hash it cites is the table
  it priced with.
- Entry points: `crucible prop validate [--snapshots-root DIR]|list|confirm`, `crucible futures prop`
  (the evaluation), `crucible schema --kind prop-ruleset|prop-attempt|prop-evaluation`; the MCP tools
  `crucible_prop_validate`, `crucible_prop_list`, `crucible_prop_schema` and
  `crucible_futures_prop` (never `confirm`). `--snapshots-root` runs `crucible.prop.sources` over the
  file: every quote is looked for in the page its own hash names and every image transcription's file
  is hashed, so the report says `N attribution(s), M image(s), 0 synthetic` and refuses a mismatch.

## Extension points

- A new rule kind is a new model in `rules_schema.py`, a new evaluator in `rules.py`, its branch in
  `build`, and a schema version. A firm rule that fits no kind goes into `not_modeled` with a
  materiality and, when an audit could change that materiality, a `becomes_immaterial_if` text: the
  declared materiality stands until the audit shows the condition holds (on an immaterial entry the
  same field states what would make it bind).
- A different account type (a firm whose semantics differ structurally, not just numerically)
  implements `AccountOverlay` and is passed as `account=` to `simulate_futures`.
- New firm rulesets are data, not code: add versioned YAML under a ruleset registry and point
  `load_registry` at it (never a value in Python). `tools.docgen --write` refreshes INDEX.json.

## Known gaps

- The contract limit is enforced at admission and on every candidate target; it is not re-checked
  as an invariant after a fill that must reduce exposure (a stop or a liquidation only reduces).
- The per-side fee schedule is resolved once, at the attempt's `start_trade_date`, against one
  participant profile: a fee change inside a long attempt is reported in `warnings` but the start
  date's row is charged throughout (a per-date schedule would need the simulator to price each fill
  on its own date), and a row of another classification value never prices it.
- The profile is a single run-level declaration, so an attempt cannot be priced as one class for
  the exchange fee and another for the NFA assessment; a firm whose clearing chain splits the
  classes would need a per-component profile (not built).
- A promotion's `requires` are string comparisons on the profile: a fact the profile states in
  another spelling (`yes` for `'true'`) does not match, so the base value stands and the reason is
  recorded. That is the conservative direction, not a normalisation step.
- A static threshold (`static_drawdown`) has no post-payout reset or lock: a file that wants one
  has to express it as a locked `trailing_drawdown` (ADR-0107, amendment of 2026-11-23, section 3).
- A row that covers several components is charged once, under the first component in report order:
  the amount is one cell the owner reported, and splitting it across the components it covers
  would be a number no source states.
- A `flat_by` relative to a session end trusts the CME session table, and that table's unsourced
  windows are reported as a coverage gap rather than repaired: 2023-11-24 still closes at the 16:00
  Chicago regime close because the 2023 Thanksgiving schedule was never archived (see the
  session-calendar paragraph above). The sourced 2024 instance (2024-11-29, 12:15 Chicago) is the
  hand test, and a firm rule that assumes the 2023 early close stays `not_modeled` for that date.
- The upper-bound file (`rulesets/prop/cost_assumptions/upper_bound_v1.yaml`) is a PRELIMINARY
  stand-in, not a cost: its exchange margin, its clearing and its `other` amounts are the owner's
  bounds, and a firm whose components are all sourced is charged none of it while a firm with no
  sourced component is charged all of it — which is why the run carries the comparability note. It
  prices no commission, so a firm whose per-side commission the sources do not state still reports
  `commission` as a gap (the file is not a substitute for a commission).
- An `activity_requirement` window is judged on the overlay's COMPLETE rule-days: a window is never
  judged on the rule-day in progress, it is judged at that day's close.
- `crucible prop list` and the generated `rulesets/prop/INDEX.json` report a v2 file that does not
  validate yet (a declaration this engine now requires is missing) as `pending_migration`, without
  a hash, so both keep working while the firm files catch up. `crucible prop validate <file>` is the
  command that refuses, and its message names the missing field.
- With several contract limits (`max_contracts` and `scaling_plan`), the smallest limit applies and
  a rejection in any of them wins over a clip.
- A `scaling_plan` ladder keyed on `min_profit_usd` keeps the reading it has always had: the rung
  applies at `>=` its threshold and its `comparison` is a vestigial required declaration (every
  shipped profit ladder declares `<=` and the engine has never read it). Only a BALANCE ladder
  (`min_balance_usd`) takes its boundary from that field, and it refuses `<=` / `<` by name. Making
  the profit form honour it would silently change 112 shipped rulesets, so it is declared here
  instead: `>` on a balance ladder is the boundary-in-the-lower-rung reading, `>=` the upper one.
- The tier a scaling plan reads at a close is the BALANCE (realized plus commissions), never equity:
  an open position that has doubled the account moves no tier until it is closed and the close is
  marked, which is the pessimistic direction (a firm grows the size on the balance, and the balance
  is what the next session's books carry).
- A payout is a withdrawal in the overlay's accounting: the simulator's own balance column is the
  trading ledger and does not show it. A `daily_profit_cap` forfeit is the same kind of adjustment.
- A session-relative `flat_by` reads the bar's scheduled session close, not a per-instrument
  holiday table; the CME calendar is the source, and an off-schedule bar has no flat instant.
- The session-relative `flat_by`'s entry block ends at the scheduled session close (the reopen
  the overlay uses when a firm states no clock), so an account cannot re-enter in the minutes
  between the firm's flat time and the close. A firm that states `reopen` keeps its own clock.
- The news calendar is ingested separately (the economic-calendar dataset doc under `docs/data/`); an uncovered period makes
  the news rule `not_modeled` and the estimate `partial`, never "no news".
- The attempt statistics (the overlapping-attempt bootstrap, censoring as a class) live in
  `crucible.experiments.futures_prop` (below), and any verdict is C7e: `attempt.py` reports one
  attempt's mechanics, estimate status and practical eligibility.
