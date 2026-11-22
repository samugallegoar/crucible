# Module `crucible/prop` — prop-firm simulation (ADR-0106, ADR-0107)

## What exists

- **`rules_schema.py`**: the Pydantic v2 rule models of schema version 2, split out from the
  loader so the file stays readable.
  - `Attribution`: `url` (null only for an owner-supplied value), `provided_by` (`owner`),
    `quote`, `snapshot_sha256` (64 hex), `retrieved_at` (UTC), optional `section`, `synthetic`.
  - `Assumption {name, rationale}` and the per-rule `evidence` field:
    `official_quote | owner_provided | assumption | conflict_resolution`; a rule with
    `evidence: assumption` must carry its named assumption.
  - `Commissions {status: known|unknown, per_side_usd: {ROOT: Decimal}, platform, source}`.
    Unknown is never zero; a sentinel (>= 1,000,000 USD) is refused.
  - `Conflict {conflict_id, rule_id, field, selected_value, alternatives [{value, source}],
    selected_source, rationale, applicability_checked: true}`.
  - `Verification` (a fact about a hash, never part of it) and `ResetClock {time, tz}` with **no
    default**: the rule-day boundary is a firm's declaration, not the engine's guess.
  - The typed rules as a discriminated union on `kind`:
    `ProfitTargetRule`, `StaticDrawdownRule`, `TrailingDrawdownRule` (with `TrailingLock`,
    including `on: hwm|first_payout` and `hwm_basis`), `DailyLossRule` (amount, percentage,
    balance tiers, or a ratchet on peak profit), `MaxContractsRule`, `ScalingPlanRule` (with
    `on_excess`), `FlatByRule` (a fixed clock or `minutes_before_session_end`),
    `MinTradingDaysRule` (with `unit` and a composable `DayCountsIf`), `ConsistencyRule` (with
    `window`), `PayoutRule` (the C7b payout vocabulary), `TimeLimitRule`, `FeeRule` (evaluation,
    activation, monthly, reset), `DailyProfitCapRule`, `InactivityRule`, `NewsRestrictionRule`
    and `ComplianceRule`.
  - `Phase`: `phase_id`, `kind` (`evaluation` or `funded`), `starting_balance_usd`, `rules`,
    `pass_conditions`, `max_calendar_days`/`max_trading_days`, `fees`. A rule that gates the phase
    must sit in `pass_conditions` (`is_pass_condition`; a `consistency` rule whose `applies_to` is
    `payout` stays in `rules`).
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
- **`attempt.py`**: `simulate_attempt(...) -> AttemptResult`, one attempt from one start trade
  date: phases in order, each a fresh `PropAccountOverlay` inside `simulate_futures`; outcome
  `pass`/`fail`/`timeout`/`censored`, `PhaseOutcome` per phase, `min_buffer_usd` with where it
  happened, fees broken out, `payouts` (gross and net), `payout_policy`, overlay events, rule
  coverage, evaluation status, `mechanical_outcome`, `estimate_status` + reasons,
  `practical_eligibility`, `scenario_id`, the applied commissions, warnings, ruleset identity and
  the counterfactual label.
- **`coverage.py`**: `rule_coverage(ruleset, news_covered=...)`, `evaluation_status`
  (`complete`, `conditional_on_modeled_rules`, `blocked`), `material_unmodeled`,
  `coverage_warnings` and `counterfactual_application`.
- **`confirm.py`**: `confirm_ruleset(path, ...)`, the owner's interactive verification: prints
  every rule, conflict and assumption and writes the sidecar only after the owner types the first
  12 hex of the content hash. It refuses without a TTY and is never exposed over MCP.
- **`index.py`**: `build_index`/`render_index` for `rulesets/prop/INDEX.json`, generated by
  `uv run python -m tools.docgen --write`; a v1 file is listed as `pending_migration`.
- **`list.py`**: `list_document`, what `crucible prop list --json` and `crucible_prop_list` print.
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

- `estimate_status` is `unavailable` when a critical rule is unmodeled or the commissions are
  unknown without a named `cost_assumption`; `partial` when a material rule (including an
  uncovered news window) is unmodeled; `conditional` when the ruleset is unverified or a cost
  assumption was used; otherwise `complete`. Every reason is reported.
- `practical_eligibility` is `blocked_by_compliance` when a critical compliance rule that bans the
  exact `execution_mode` (`automated` or `manual`) applies, otherwise `eligible`. A mechanically
  successful attempt under a compliance blocker is never reported as a practically valid pass.

## The per-bar order (ADR-0106 section 3)

The simulator calls the overlay at fixed points of every bar:

| # | Hook | What happens |
|---|------|--------------|
| 1 | `begin_bar` | the rule-day transition (the reset clock): the daily-loss reference resets, soft locks lift, the scaling plan takes the limit its last close chose, inactivity counts |
| 2 | `begin_bar` (gap test) | equity at the bar's open with the position carried in; a threshold already crossed liquidates at the open |
| 3 | `forced_flat` | the first bar reaching a `flat_by` instant (absolute or session-relative) or a news window that flattens liquidates at its open; no entry until the reopen time |
| 4 | `admit` | the target the account allows: contract limit and scaling plan by contract weight (`clip` or `reject`), a lock, a closed account, the forced-flat window, an active news window |
| 5 | `favorable` | the bar's favourable extreme in equity terms (high for a long, low for a short) updates the high-water marks **first** |
| 6 | `breach_prices` | each active threshold's breach price, merged with the touched lot stops, recomputed after every stop |
| 7 | `breach_filled`, `fill` | the breach consequence (hard closes, soft locks), every fill for the day statistics and inactivity |
| 8 | `end_bar` | the close mark; on the rule-day's last scheduled bar the EOD rules, the daily profit cap, the payouts and the pass conditions. An EOD breach liquidates **at that close**; a pass with a position open flattens it **at that close** as `phase_flatten` |
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
| `profit_target` | `amount_usd`, `basis: balance\|equity`, `evaluated`, `require_flat` | pass: the basis reaches `starting_balance + amount` |
| `static_drawdown` | `amount_usd`, `basis`, `evaluated` (**required**) | threshold `starting_balance - amount`, never trails |
| `trailing_drawdown` | `amount_usd`, `mode`, `evaluated`, `basis`, `hwm_basis`, `lock {on: hwm\|first_payout, ...}` | threshold `hwm - amount`; the lock freezes it |
| `daily_loss` | `amount_usd` / `pct_of_reference` / `amount_by_balance_tier` / `pct_of_peak_profit` (`non_decreasing`), `reference`, `basis`, `evaluated`, `reset {time, tz}`, `severity` | threshold `reference - amount`; soft locks, hard fails |
| `max_contracts` | `limit` (weighted) or `per_instrument`, `on_excess` | admission |
| `scaling_plan` | `steps`, `evaluated`, `basis`, `on_excess: clip\|reject` | the limit for the next rule-day |
| `flat_by` | `time`+`tz` **or** `minutes_before_session_end`, `reopen`, `consequence` | a forced-flat clock; the session-relative form follows the CME early close |
| `min_trading_days` | `days`, `unit: trading_days\|winning_days\|calendar_days\|trade_dates`, `day_counts_if` | pass condition |
| `consistency` | `max_day_share`, `measure`, `applies_to`, `window: all_time\|since_last_payout` | the best day's share of total profit |
| `payout` | `min_days_since_last`, `min_profitable_days`, `min_traded_days`, `min_day_profit_usd`, `window`, `buffer_usd`, `split`, `min_usd`, `max_usd: number\|unlimited`, `max_usd_by_payout`, `max_pct_of_balance`, `max_share_of_withdrawable`, `min_profit_since_last_usd`, `cycle_goal_usd`, `first_payout_after_calendar_days`, `payout_group`, `max_payouts`, `threshold_after_payout` | a withdrawal from a funded phase at the close |
| `time_limit` | `max_calendar_days` or `max_trading_days` | a phase without a pass times out |
| `fee` | `fee_kind: evaluation\|activation\|reset\|monthly`, `amount_usd`, `when` | attempt cost accounting only |
| `daily_profit_cap` | `amount_usd`, `action: forfeit_excess\|promote_phase`, `basis`, `evaluated` | the per-day profit ceiling |
| `inactivity` | `max_gap`, `unit`, `rolling_window`, `action: fail` | a maximum gap between trading days |
| `news_restriction` | `event_types`, `instruments`, `pre_minutes`, `post_minutes`, `scope: new_entries\|holding\|all_trading`, `flatten: before_window\|none`, `action` | a scheduled-event trading window |
| `compliance` | `restriction`, `applies_to_execution: [automated\|manual]`, `materiality`, `action: block\|none` | practical eligibility, never the mechanical account |

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
news_events=..., news_coverage=..., cost_assumption=..., resets_purchased=..., scenario_id=...)`
runs the phases in order and records the trader's choice. A payout is a withdrawal recorded apart
from trading P&L: `withdrawable = balance - (base + buffer_usd)`; the gross is the smallest of the
declared caps and `withdrawable`, and a payout happens when it is at least `min_usd` and every gate
holds. A `payout_group` pays at most one path per close (`max_eligible` takes the largest net).
`payouts_usd` is the trader's net, `fees` breaks the costs into evaluation, activation, monthly
(per started calendar month of the attempt) and reset, `net_cash_usd` is the payouts minus the
total, and `payouts` lists every payout with its gross and net.

The ruleset's commissions replace the run's fee schedule (spread and slippage still come from the
run's cost schedule). Unknown commissions are never treated as zero: the cost-dependent statistics
are `unavailable` unless an explicit named `cost_assumption` is given, and the result says which.

## Interfaces

- `crucible.execution.interfaces.AccountOverlay` (Protocol) with `AccountMarks`, `BreachPrice`,
  `OverlayAction` and `OverlayEvent`; implemented by `PropAccountOverlay`.
- `simulate_futures(..., account=..., liquidation_extra_slippage_ticks=...,
  initial_blocked_target=...)` in `crucible/execution/futures_sim.py` is the only execution-layer
  coupling. With `account=None` the simulation is byte-for-byte what it always was.
- `simulate_attempt` takes a `Sequence[NewsEvent]` and a `Sequence[(start_ns, end_ns)]` coverage
  record; it imports the calendar dataset only through those values.
- Entry points: `crucible prop validate|list|confirm`, `crucible schema --kind
  prop-ruleset|prop-attempt`; the MCP tools `crucible_prop_validate`, `crucible_prop_list` and
  `crucible_prop_schema` (never `confirm`).

## Extension points

- A new rule kind is a new model in `rules_schema.py`, a new evaluator in `rules.py`, its branch in
  `build`, and a schema version. A firm rule that fits no kind goes into `not_modeled` with a
  materiality.
- A different account type (a firm whose semantics differ structurally, not just numerically)
  implements `AccountOverlay` and is passed as `account=` to `simulate_futures`.
- New firm rulesets are data, not code: add versioned YAML under a ruleset registry and point
  `load_registry` at it (never a value in Python). `tools.docgen --write` refreshes INDEX.json.

## Known gaps

- The contract limit is enforced at admission and on every candidate target; it is not re-checked
  as an invariant after a fill that must reduce exposure (a stop or a liquidation only reduces).
- With several contract limits (`max_contracts` and `scaling_plan`), the smallest limit applies and
  a rejection in any of them wins over a clip.
- A payout is a withdrawal in the overlay's accounting: the simulator's own balance column is the
  trading ledger and does not show it. A `daily_profit_cap` forfeit is the same kind of adjustment.
- A session-relative `flat_by` reads the bar's scheduled session close, not a per-instrument
  holiday table; the CME calendar is the source, and an off-schedule bar has no flat instant.
- The news calendar is ingested separately (the economic-calendar dataset doc under `docs/data/`); an uncovered period makes
  the news rule `not_modeled` and the estimate `partial`, never "no news".
- The attempt statistics (the overlapping-attempt bootstrap, censoring as a class) and any verdict
  are C7c-C7e; this stage reports one attempt's mechanics, estimate status and practical
  eligibility.
