# Module `crucible/prop` — prop-firm simulation (ADR-0106)

## What exists

- **`ruleset.py`**: the Pydantic v2 ruleset models and the loaders.
  - `PropRuleset`: `schema_version` 1, identity (`ruleset_id`, `version`, `firm`, `program`,
    `account_size_usd`, `platform`, `addons`, `jurisdiction`), `as_of`, `effective_from`,
    `effective_to`, `instruments` (`Instrument`: root and `contract_weight`, 1 mini and 0.1 micro),
    `verification`, ordered `phases`, and `not_modeled`.
  - `Attribution`: `url`, `quote`, `snapshot_sha256` (64 hex), `retrieved_at` (UTC), optional
    `section`, `synthetic`.
  - Typed rules as a discriminated union on `kind`: `ProfitTargetRule`, `StaticDrawdownRule`,
    `TrailingDrawdownRule` (with `TrailingLock`), `DailyLossRule`, `MaxContractsRule`,
    `ScalingPlanRule` (with `ScalingStep`), `FlatByRule`, `MinTradingDaysRule` (with
    `DayCountsIf`), `ConsistencyRule`, `PayoutRule`, `TimeLimitRule`, `FeeRule`.
  - `Phase`: `phase_id`, `kind` (`evaluation` or `funded`), `starting_balance_usd`, `rules`,
    `pass_conditions`, `max_calendar_days`/`max_trading_days`, `fees`. A rule that gates the phase
    must sit in `pass_conditions` (`is_pass_condition`; a `consistency` rule whose
    `applies_to` is `payout` stays in `rules`).
  - `ruleset_sha256`: the canonical JSON hash of the content. `load_ruleset(path)` reads one file;
    `load_registry(dir)` reads a directory and refuses two files with the same
    `(ruleset_id, version)` and different hashes, or a repeated version.
  - `verification.status: verified` requires a confirmation and a complete, non-synthetic
    attribution on every rule, pass condition and fee; a synthetic attribution can never be
    verified. Old versions are immutable: a change is a new version.
- **`rules.py`**: one evaluator per rule kind.
  - `breach_price(marks, threshold)` solves the exact integer price at which equity touches a
    threshold (floor for a long, ceiling for a short); `local_day`/`day_instant_ns` place a
    rule-day from its reset time and IANA time zone.
  - Each evaluator answers `new_day`, `favorable`, `thresholds` (intrabar), `eod` (at the rule-day
    close) and `pass_ok`; `contract_limit`/`on_excess` drive admission; `Payout.decision`/
    `Payout.apply` decide and record a withdrawal.
  - `build(rule, ...)` maps a typed rule to its evaluator and refuses a kind without one
    (`not_modeled`, never approximated).
- **`overlay.py`**: `PropAccountOverlay`, the `AccountOverlay` the futures simulator calls inside
  each bar, and its `snapshot()`/`restore()` (ADR-0041). It holds the phase's rules, the rule-day
  clock, the day statistics, the lock and the withdrawals.
- **`attempt.py`**: `simulate_attempt(...) -> AttemptResult`, one attempt from one start trade
  date: phases in order, each a fresh `PropAccountOverlay` inside `simulate_futures`; outcome
  `pass`/`fail`/`timeout`/`censored`, `PhaseOutcome` per phase, `min_buffer_usd` with where it
  happened, fees, `payouts` (gross and net) and `payout_policy`, overlay events, rule coverage,
  evaluation status, warnings, ruleset identity and the counterfactual label.
- **`coverage.py`**: `rule_coverage`, `evaluation_status` (`complete`,
  `conditional_on_modeled_rules`, `blocked`), `material_unmodeled`, `coverage_warnings` and
  `counterfactual_application`.
- **`validate.py`**: `validate_ruleset_document` (what `crucible prop validate` prints),
  `ruleset_json_schema` and `attempt_json_schema` (what `crucible schema --kind
  prop-ruleset|prop-attempt` prints).

## Responsibility

Turn sourced, versioned firm rules into account-level consequences *inside* one futures
simulation, with the conservative OHLC semantics of ADR-0106. No firm value lives in code: every
number comes from the ruleset file.

## The per-bar order (ADR-0106 section 3)

The simulator calls the overlay at fixed points of every bar:

| # | Hook | What happens |
|---|------|--------------|
| 1 | `begin_bar` | the rule-day transition (each rule's reset time and zone): the daily-loss reference resets, soft locks lift, the scaling plan takes the limit its last close chose |
| 2 | `begin_bar` (gap test) | equity at the bar's open with the position carried in; a threshold already crossed liquidates at the open |
| 3 | `forced_flat` | the first bar reaching a rule's flat time liquidates at its open and no entry is admitted until the reopen time (`consequence: fail` fails the account instead) |
| 4 | `admit` | the target the account allows: contract limit and scaling plan by contract weight (`clip` or `reject`), a lock, a closed account, the forced-flat window |
| 5 | `favorable` | the bar's favourable extreme in equity terms (high for a long, low for a short) updates the high-water marks **first** |
| 6 | `breach_prices` | each active threshold's breach price, merged with the touched lot stops along the adverse path and recomputed after every stop |
| 7 | `breach_filled`, `fill` | the breach consequence (a hard rule closes the account, a soft one locks it), and every fill for the day statistics |
| 8 | `end_bar` | the close mark; on the rule-day's last scheduled bar the EOD rules, the payouts and the pass conditions. An EOD-evaluated breach liquidates **at that close**; a pass with a position still open flattens it **at that close** as `phase_flatten` |
| 9 | `finish` | the end of the data: a complete rule-day was already handled at its close; an unresolved attempt whose data ends inside a rule-day is `censored` |

**Joint pessimism** (`high_before_low_conservative`): the favourable extreme and the adverse touch
are both applied, even when no single path inside the bar produces both. That is an upper bound on
harm, not a claim about the path: it can fail an account a real path would have kept. The bias is
in one direction only, against passing, and it is declared.

**The liquidation model.** A breach is a market liquidation, never a guaranteed fill at the
threshold: the fill price is the trigger (the breach price rounded against the strategy — floor for
a long, ceiling for a short — or the bar's open when it gapped past it, or the bar's close for an
EOD-evaluated rule), and it pays the bar's open spread and slippage (its close schedule for a close
liquidation) plus `liquidation_extra_slippage_ticks` per contract. That extra slippage is charged as
money, so a fill never leaves the bar's `[low, high]` (AGENTS.md section 9). A fast market can fill
worse; C7c stresses the extra ticks.

## The rule kinds

| Kind | Parameters | Semantics |
|---|---|---|
| `profit_target` | `amount_usd`, `basis: balance\|equity`, `evaluated: eod\|intraday`, `require_flat` | pass: the basis reaches `starting_balance + amount` |
| `static_drawdown` | `amount_usd`, `basis: equity\|balance`, `evaluated: intraday\|eod` (**required**) | threshold `starting_balance - amount`, never trails |
| `trailing_drawdown` | `amount_usd`, `mode: intraday\|eod` (when the mark moves), `evaluated: intraday\|eod` (when the threshold is tested), `basis`, `lock` | threshold `hwm - amount`; the lock freezes it |
| `daily_loss` | `amount_usd \| pct_of_reference`, `reference: day_start_balance\|day_start_equity\|prior_eod_balance`, `basis`, `evaluated`, `reset {time, tz}`, `severity: soft\|hard` | threshold `reference - amount`; soft liquidates and locks until the reset, hard fails |
| `max_contracts` | `limit` (weighted) or `per_instrument`, `on_excess: clip\|reject` | admission; weights from `instruments` |
| `scaling_plan` | `steps [{min_profit_usd, max_contracts}]`, `evaluated: eod`, `basis` | the limit for the next rule-day, from the close |
| `flat_by` | `time`, `tz`, `reopen`, `consequence: auto_liquidate\|fail` | step 3 above |
| `min_trading_days` | `days`, `day_counts_if {min_trades \| min_abs_pnl_usd}` | pass condition |
| `consistency` | `max_day_share`, `measure: best_day_profit/total_profit`, `applies_to: pass\|payout` | the best day's share of total profit |
| `payout` | `min_days_since_last`, `min_profitable_days`, `min_day_profit_usd`, `buffer_usd`, `split`, `min_usd`, `max_usd`, `max_payouts`, `threshold_after_payout: unchanged\|trail_from_new_balance` | a withdrawal from a funded phase at the close |
| `time_limit` | `max_calendar_days \| max_trading_days` | a phase without a pass times out |
| `fee` | `kind`, `amount_usd`, `when` | attempt cost accounting only, never the trading ledger |

`evaluated` is required on every threshold rule because when a firm tests a threshold is a firm's
rule, not the engine's guess; a trailing rule's `mode` (when the mark moves) and `evaluated` (when
the threshold is tested) are separate declarations.

## Attempts and payouts

`simulate_attempt(..., payout_policy="max_eligible"|"none")` runs the phases in order and records
the trader's choice. A payout is a withdrawal recorded apart from trading P&L:
`withdrawable = balance - (base + buffer_usd)`, `gross = min(max_usd, withdrawable)` when
`gross >= min_usd`, the balance falls by `gross` and the trader receives `split * gross`. `base`
starts at the phase's starting balance and `threshold_after_payout` either keeps it (`unchanged`) or
moves it to the post-payout balance (`trail_from_new_balance`). `payouts_usd` is the trader's net,
`net_cash_usd` is that minus the fees, and `payouts` lists every payout with its gross and net.

## Interfaces

- `crucible.execution.interfaces.AccountOverlay` (Protocol) with `AccountMarks`, `BreachPrice`,
  `OverlayAction` and `OverlayEvent`; implemented by `PropAccountOverlay`.
- `simulate_futures(..., account=..., liquidation_extra_slippage_ticks=...,
  initial_blocked_target=...)` in `crucible/execution/futures_sim.py` is the only execution-layer
  coupling. With `account=None` the simulation is byte-for-byte what it always was.
- Entry points: `crucible prop validate <ruleset.yaml>`; `crucible schema --kind
  prop-ruleset|prop-attempt`; the MCP tools `crucible_prop_validate` and `crucible_prop_schema`.

## Extension points

- A new rule kind is a new model in `ruleset.py`, a new evaluator in `rules.py`, its branch in
  `build`, and a schema version. A firm rule that fits no kind goes into `not_modeled` with a
  materiality.
- A different account type (a firm whose semantics differ structurally, not just numerically)
  implements `AccountOverlay` and is passed as `account=` to `simulate_futures`.
- New firm rulesets are data, not code: add versioned YAML under a ruleset registry and point
  `load_registry` at it (never a value in Python).

## Known gaps

- The contract limit is enforced at admission and on every candidate target; it is not re-checked
  as an invariant after a fill that must reduce exposure (a stop or a liquidation only reduces).
- With several contract limits (`max_contracts` and `scaling_plan`), the smallest limit applies and
  a rejection in any of them wins over a clip.
- A payout is a withdrawal in the overlay's accounting: the simulator's own balance column is the
  trading ledger and does not show it.
- The six real firm rulesets, the attempt statistics (the overlapping-attempt bootstrap and right
  censoring as a class) and any threshold or verdict are C7b-C7e; C7a ships synthetic rulesets
  only, and a synthetic ruleset can never be `verified`.
- `crucible prop validate` reports a ruleset but does not run an attempt: the futures-run config
  that names one is C7b.
