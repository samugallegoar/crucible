# Apex Trader Funding — prop-firm research notes (C7b, `firm_slug: apex`, schema v2)

90 rulesets, all `verification.status: unverified`: only the owner can confirm a ruleset
(`crucible prop confirm`, an interactive TTY step). Every value below is quoted from an
official page saved byte-for-byte under
`D:\proyectos\crucible-notes\internal\prop_snapshots\apex\`, and the rulesets are
generated from this page by `generate_v2_apex.py` beside those snapshots.

Official sources only (`apextraderfunding.com`, including its `help-center`). No affiliate,
review or social page was used. Nothing was logged into, submitted or purchased. Every
commission page is public.

## 0. Method, and the one thing that changed in the sources

- **Retrieval date**: 2026-11-22 (UTC). The 20 page snapshots of the first pass are reused
  unchanged; the three **commission pages** were fetched for this pass at 03:53 UTC
  (`20261122_rithmic_commissions.html`, `..._tradovate_commissions.html`,
  `..._wealthcharts_commissions.html`), because the first pass recorded commissions as
  unknown: no page then read carried a per-side table.

- **Access note**: `apextraderfunding.com` answers HTTP 403 to a plain
  `curl -A "Mozilla/5.0"` for every path (Cloudflare). The bytes were fetched with a full
  browser header set (Chrome UA, `Accept`, `Accept-Language`, `Sec-Fetch-*`, `sec-ch-ua`,
  `Accept-Encoding: identity`): the exact request a browser makes, and the response was the
  normal page, not a challenge. `python fetch.py apex <short_name> <url>` reproduces it.

- **Quote verification**: decode the saved bytes as UTF-8, unescape HTML entities, strip
  tags for table cells, collapse whitespace, then require every quotation of every ruleset
  to be a substring of its snapshot; every `snapshot_sha256` must equal the hash of those
  bytes. `check_quotes2.py` performs exactly this over all 90 files and all of `RESEARCH.md`'s
  quotes are the same strings.

- **Generation**: a quote is built *from* the value tables, so a table value the page does
  not state makes the generator abort before it writes anything. The product records of the
  site's `productPickerV3Config` are cross-checked field by field (target, drawdown, DLL,
  contracts, pack price, PA price, `pa_auto_liq_min_max`).

- **Round 2 (the C7b vocabulary round 2) re-read the same 21 snapshots**: no page was
  fetched again and no snapshot changed, so the hashes and the retrieval instants above are
  the ones every attribution still carries. Only the declarations the engine now requires
  (and the vocabulary forms that fit Apex exactly) changed (section 2b).

## 1. Snapshots used

| file | url | sha256 | retrieved_at |
|---|---|---|---|
| `20261122_home.html` | https://apextraderfunding.com/ | `3545df973d7ecc638f674d009a85b351d8da0e32bd224882810617fe16f7be7d` | 2026-11-22T01:35:38Z |
| `20261122_eod_evaluations.html` | https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-evaluations/ | `b66748ac193d77d668067c2177676f65f43eb7b8b684613311bdb7cb721cd829` | 2026-11-22T01:36:04Z |
| `20261122_intraday_evaluations.html` | https://apextraderfunding.com/help-center/evaluation-accounts-ea/intraday-trailing-drawdown-evaluations/ | `c07282c0eecf409c11e4ae948ecb285e9ce4d0d64a6d62b588444b6406bd1b6e` | 2026-11-22T01:39:30Z |
| `20261122_eod_drawdown_explained.html` | https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-drawdown-explained/ | `4b1a18d8c402becb8835243b7f288050f586dcaa60d3b715506fa12811f8c22b` | 2026-11-22T01:36:03Z |
| `20261122_daily_loss_limit.html` | https://apextraderfunding.com/help-center/additional-helpful-items/daily-loss-limit-explained/ | `24548f42f5042c97c70063ceafb6b3460f947a83ab7576294b728565f4a4242d` | 2026-11-22T01:36:41Z |
| `20261122_eod_payouts.html` | https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-payouts/ | `88b18494991d08a793b56c071c59a257da6c75438f530bdcc78a4a90ff61724c` | 2026-11-22T01:36:04Z |
| `20261122_intraday_payouts.html` | https://apextraderfunding.com/help-center/intraday-trailing-drawdown-accounts/intraday-trailing-drawdown-payouts/ | `1b0aa7f6581b95531e1691889292e47e30342992d3b9d9191744b77f9f6a2df7` | 2026-11-22T01:39:31Z |
| `20261122_eod_performance_accounts.html` | https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-performance-accounts-pa/ | `abdbfce5020d2157daf67aed860a1754fa8953c9f1ac9ad63b96685691175bed` | 2026-11-22T01:36:05Z |
| `20261122_intraday_pa.html` | https://apextraderfunding.com/help-center/intraday-trailing-drawdown-accounts/intraday-trailing-drawdown-performance-accounts-pa/ | `60f87b71c625f1240b80f8d5843b1232025c9b2852e24598864a20b4433f4b22` | 2026-11-22T01:39:30Z |
| `20261122_scaling_levels_pa.html` | https://apextraderfunding.com/help-center/additional-helpful-items/scaling-levels-pa-explained/ | `384413b44ab91db82239544686edfd61760ea23a61547ceb18a4e73084eb0a4a` | 2026-11-22T01:36:42Z |
| `20261122_position_sizing_eval.html` | https://apextraderfunding.com/help-center/additional-helpful-items/position-sizing-evaluation/ | `2986d80b60c57f7dbbedbd078dd2ddc7c1d30eeacc250842cb501ac3af57479a` | 2026-11-22T01:36:42Z |
| `20261122_eval_plan_fees.html` | https://apextraderfunding.com/help-center/billing/evaluation-plan-fees-and-access-explained/ | `0c38152a6a4d57b54fe4e9d0999b870aa5337776e2a3a4bc0133928d1d1d9410` | 2026-11-22T01:36:43Z |
| `20261122_pa_activation.html` | https://apextraderfunding.com/help-center/billing/pa-activation-process-deadline-explained/ | `b767c2ebea64a945fb77dec278d09e0f7a21760c686660a604fbccc1d44cd8c6` | 2026-11-22T01:36:43Z |
| `20261122_pa_inactivity.html` | https://apextraderfunding.com/help-center/billing/inactivity-policy-on-performance-accounts-pa | `5b7d69544e047a3e851a95b02074d7ff3d2c896cfb34cc4a8153e5e3efbe5d44` | 2026-11-22T01:36:44Z |
| `20261122_consistency_50.html` | https://apextraderfunding.com/help-center/additional-helpful-items/50-consistency-requirement/ | `4a1906d395be26fa61175b5818d85b7858de4edda6b8901fa691dce1715ff9d6` | 2026-11-22T01:36:40Z |
| `20261122_prohibited_activities.html` | https://apextraderfunding.com/help-center/getting-started/prohibited-activities | `494fd6da079ceaec93f14a5f8ea97299fb7cd9b212bf6fc5e62f00ba6d170c9c` | 2026-11-22T01:36:46Z |
| `20261122_futures_trading_times.html` | https://apextraderfunding.com/help-center/getting-started/futures-trading-times/ | `639a215e3dc30105ff3c783d0c4df1a6fab04783f3bc5d668ae9bb32f29d7aef` | 2026-11-22T01:39:28Z |
| `20261122_time_zone.html` | https://apextraderfunding.com/help-center/helpful-items/what-time-zone-do-you-operate-in/ | `8a85ffc77d7fe1ec14606a391a47fb4a1a4ee7829a559a7df238d76cd4ac02c6` | 2026-11-22T01:39:29Z |
| `20261122_rithmic_commissions.html` | https://apextraderfunding.com/help-center/rithmic/rithmic-commissions-instruments | `311ecf4b57d21610730d7464f02d5ef5d8f70a9f6320ea161aaf134916eb515a` | 2026-11-22T03:53:52Z |
| `20261122_tradovate_commissions.html` | https://apextraderfunding.com/help-center/tradovate/tradovate-commission-instruments | `dd21d47f146177c94ec55c54cc54b7f1cd6d5040cff1aafb5f20a6fe70ba0344` | 2026-11-22T03:53:56Z |
| `20261122_wealthcharts_commissions.html` | https://apextraderfunding.com/help-center/wealthcharts/wealthcharts-commissions-instruments | `381ce34e66f40ff211a907c87fc512a77a7f61f41a43458a6f8f53d54adbe011` | 2026-11-22T03:53:56Z |

Also saved and read but carrying no value used: `20261122_how_it_works.html`,
`20261122_legacy_products.html`, `20261122_new_products.html`, `20261122_accounts.html`,
`20261122_payouts.html`, `20261122_request_payout.html`, `20261122_terms_of_use.html`,
`20261122_code_of_conduct.html`, `20261122_restricted_countries.html`,
`20261122_hc_eval.html`, `20261122_hc_perf.html`, `20261122_hc_intraday.html`,
`20261122_hc_eod_trailing.html`.

## 2. What the schema v2 migration changed

The v1 drafts are rewritten in place: same `ruleset_id`, same `version: 1` (nothing was committed before, so no version number is reused), `schema_version: 2`. The platform axis was then completed, because a platform with its own commission schedule is a distinct ruleset (ADR-0107 section 10): 46 further files carry `-tradovate` and `-wealthcharts`.

| v1 | v2 |
|---|---|
| no `evidence` field | every rule declares `official_quote`, `assumption` or `conflict_resolution` |
| `severity: soft` / `on_excess` / `consequence` | explicit `action`, `comparison`, `basis`, `evaluated`, `reference`, `reset` and `mode` |
| `basis: equity` only | `basis: equity` (tested intrabar) plus `hwm_basis: balance` for the EOD mark and `hwm_basis: equity` for the intraday mark |
| no `commissions` | per-root, per-side commissions, from the ruleset's own platform page |
| one file set, Rithmic doubling for WealthCharts | one file set per platform (`-tradovate`, `-wealthcharts`), each with its own commissions source |
| no `conflicts` | 2 conflict kinds, each with both sources and a sensitivity scenario |
| 10 `not_modeled` entries | 5 kept, 3 added (sub-minute/HFT, correlated-instrument hedging, the undocumented evaluation daily-profit field), 5 removed because the vocabulary now models them exactly |
| PA DLL as a fixed Level-1 amount | `daily_loss.amount_by_balance_tier` (the published ladder) |
| payout cap as the first ladder rung | `payout.max_usd_by_payout` (the whole ladder) |
| days/consistency counted over the whole phase | `window: since_last_payout` |
| scaling plan that always clips | `action: reject` (Apex rejects an oversized order) |
| automation ban as `not_modeled` | `compliance` rule, materiality `critical`, `applies_to_execution: [automated]` |

## 2b. Round 2 changes (the C7b vocabulary round 2)

The engine's vocabulary round 2 added declarations it now REQUIRES and forms that fit a
firm rule EXACTLY (ADR-0107 sections 7-13). Every file was regenerated from the same
snapshots: what changed is the declaration, never a value read from a page. A form is used
only where the firm's own wording fits it; where it does not, the row says so instead of
bending the rule to the schema.

| change | files | before | now | why |
|---|---|---|---|---|
| cost components (REQUIRED) | 90/90 | field absent | `components`: exchange/clearing/NFA/other all `unknown` | No Apex page says whether the per-side commission is all-in or excludes the exchange and NFA fees; `unknown` is the declaration, never `true` (section 4.3) |
| trailing lock trigger (REQUIRED to be a list) | 90/90 files, 166 rules | `'on': hwm` | `'on': [hwm]` | The only trigger Apex states is the high-water mark: the EOD evaluation stops at the profit-target balance, the PA at starting balance + $100, and a payout does not reset the threshold. `first_payout` is therefore NOT declared, even though the list allows it (`first_payout` triggers declared: 0) |
| conflict alternative `absent` | 90/90 files | `value: '1.0'` | `value: absent` | The rendered table says 'Consistency Not Applied', so the alternative reading is that the rule does not exist at all; the scenario drops the consistency pass condition instead of widening its share to 1.0 (section 7.1) |
| `activity_requirement` | 90 rules in 90/90 files | `not_modeled`: `pa_inactivity_closure` | a modeled `close_account` rule | 2 days of >= $50 net profit in every rolling 30 calendar days is exactly the round-2 kind: a count of qualifying days in a rolling window, not the `inactivity` kind's gap (section 3.3) |
| session-relative `flat_by` | 180/180 rules, 90/90 files | `time: 16:59 ET` + `tz` + `reopen: 18:00` | `minutes_before_session_end: 1` | 4:59 PM ET is one minute before the CME session close, so a holiday early close moves the deadline with the calendar instead of a guessed fixed clock; no per-file holiday-early-close entry is needed (the engine reports the calendar's own unsourced windows at attempt time) |
| payout cap `unknown` | 0/90 | a numeric ladder | unchanged | Apex publishes all six rungs for every size, so no cap is `unknown`; `unknown` is never used as a stand-in for a cap a page states, and no cap is assumed unlimited |
| `payout.min_new_profit_share_of_request` | 0/90 | n/a | not used | Apex states no 'new profit share of the request' term (the safety net and the ladder are its caps) |
| `consistency` split windows | 0/90 | `window` only | unchanged | Apex measures the best day and the total profit over the same window (since the last payout, inception before the first), so `numerator_window`/`denominator_window` would invent a difference |
| `set_threshold_to` after a payout | 0/90 | `unchanged` | unchanged | A payout does not move the PA threshold; the safety net 'remains in place for the lifetime of the Performance Account' |
| `news_restriction.effect` (REQUIRED when a news rule exists) | 0/90 | n/a | not used | Apex declares no news rule at all, so there is no effect to declare (section 5) |
| new calendar event types (PPI, FOMC_PRESS_CONFERENCE, FOMC_MINUTES) | 0/90 | n/a | not used | meaningless without a `news_restriction` rule: Apex names no event type, no window and no scope (section 5) |

Net effect on these files: the `pa_inactivity_closure` entry is gone (a material rule is now modeled), the `not_modeled` list is 5 entries per file plus the purchase-path entries, and the cost statistics become `unavailable` because the commission's all-in fact is `unknown` until the owner supplies it (section 4.3, open question 1).

## 3. Values and their sources

### 3.1 Evaluation: profit target, drawdown, DLL, contract limit, access period

The rendered parameter tables of both evaluation types are one contiguous block per page,
so one quote carries the four sizes.

> "25K 50K 100K 150K Profit Target $1,500 $3,000 $6,000 $9,000 Max Drawdown (Intraday Trailing) $1,000 $2,000 $3,000 $4,000 Max Contracts 4 6 8 12 Access Period 30 Days 30 Days 30 Days 30 Days Consistency Not Applied Not Applied Not Applied Not Applied Scaling Not Applied Not Applied Not Applied Not Applied"
>
> — `https://apextraderfunding.com/help-center/evaluation-accounts-ea/intraday-trailing-drawdown-evaluations/` (snapshot `c07282c0eecf`, Account Parameters table)

The EOD table carries the same profit targets and drawdowns and adds a Daily Loss Limit
column that the intraday table does not have (the intraday evaluation has **no** DLL):

> "25K 50K 100K 150K Profit Target $1,500 $3,000 $6,000 $9,000 Max Drawdown (EOD) $1,000 $2,000 $3,000 $4,000"
>
> — `https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-evaluations/` (snapshot `b66748ac193d`, Account Parameters table, Profit Target and Max Drawdown (EOD) rows)

> "EOD Drawdown Evaluations Only 25K 50K 100K 150K Daily Loss Limit $500 $1,000 $1,500 $2,000"
>
> — `https://apextraderfunding.com/help-center/additional-helpful-items/daily-loss-limit-explained/` (snapshot `24548f42f504`, DLL During Evaluation, EOD Drawdown Evaluations Only table)

> "During the EOD Drawdown Evaluation, the DLL amount is fixed based on your selected account size and does not increase as profits grow. There is no DLL for Intraday Drawdown Evaluations."
>
> — `https://apextraderfunding.com/help-center/additional-helpful-items/daily-loss-limit-explained/` (snapshot `24548f42f504`, DLL During Evaluation)

The contract limit is firm-wide across instruments:

> "Evaluation Account Sizes 25K 50K 100K 150K Max Contracts 4 6 8 12"
>
> — `https://apextraderfunding.com/help-center/additional-helpful-items/position-sizing-evaluation/` (snapshot `2986d80b60c5`, Position sizing at a Glance, Max Contracts table)

> "If an order exceeds your maximum allowable exposure, it will be automatically rejected and it will not count as a rule violation."
>
> — `https://apextraderfunding.com/help-center/additional-helpful-items/position-sizing-evaluation/` (snapshot `2986d80b60c5`, Position sizing at a Glance)

The access period and the moment the target is judged:

> "When you purchase an Evaluation, you receive 30 consecutive calendar days of access. The 30 calendar days run continuously, including weekends and holidays, and they are not based on trading days."
>
> — `https://apextraderfunding.com/help-center/billing/evaluation-plan-fees-and-access-explained/` (snapshot `0c38152a6a4d`, The 30 calendar days of access)

> "your account is reviewed at market close (4:59:59 PM ET)."
>
> — `https://apextraderfunding.com/help-center/billing/evaluation-plan-fees-and-access-explained/` (snapshot `0c38152a6a4d`, Passing an Evaluation)

### 3.2 Evaluation drawdown: how the threshold moves, and where it stops

> "The EOD Threshold is recalculated once per trading day at 4:59:59 PM ET, based on the account’s closing balance. It always trails the highest achieved EOD balance and never moves downward."
>
> — `https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-drawdown-explained/` (snapshot `4b1a18d8c402`, How is EOD Threshold Calculated?)

The stop level is platform-specific for the **EOD** evaluation (this is a variant axis, not
a contradiction: the page states both, for different platforms):

> "Evaluations Rithmic and Wealthcharts EOD Threshold stops trailing and becomes fixed when it reaches an amount equal to the Target Profit balance."
>
> — `https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-drawdown-explained/` (snapshot `4b1a18d8c402`, When EOD Drawdown Stops Trailing - Evaluations Rithmic and Wealthcharts)

> "Evaluations Tradovate EOD Drawdown trails indefinitely with the peak EOD account balance."
>
> — `https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-drawdown-explained/` (snapshot `4b1a18d8c402`, When EOD Drawdown Stops Trailing - Evaluations Tradovate)

The **intraday** evaluation page states the mark and the enforcement, but no stop level:

> "The Intraday Trailing Threshold moves dynamically with your account’s highest balance (Peak Balance), including unrealized gains. It is enforced intraday at all times."
>
> — `https://apextraderfunding.com/help-center/evaluation-accounts-ea/intraday-trailing-drawdown-evaluations/` (snapshot `c07282c0eecf`, Intraday Evaluation at a Glance)

Both evaluation locks are **unreachable before the pass** (they engage only once the peak
exceeds the profit-target balance, and the phase ends at that balance), so they are
immaterial to a pass probability; they are modeled because the firm declares them.

### 3.3 Funded phase: drawdown, tiers, payout, inactivity

> "Once the EOD Threshold reaches Starting Balance + $100, it stops increasing."
>
> — `https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-drawdown-explained/` (snapshot `4b1a18d8c402`, When EOD Drawdown Stops Trailing - Performance Accounts)

> "Your account balance, including unrealized PnL, may never touch or fall below the End-of-Day (EOD) Drawdown threshold. If it does, all positions are automatically liquidated and the PA is permanently closed."
>
> — `https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-performance-accounts-pa/` (snapshot `abdbfce5020d`, Trading Rules)

> "Trailing stops once Max Trailing Drawdown Amount + $100 is reached"
>
> — `https://apextraderfunding.com/help-center/intraday-trailing-drawdown-accounts/intraday-trailing-drawdown-performance-accounts-pa/` (snapshot `60f87b71c625`, Intraday Trailing PA at a Glance)

The PA Daily Loss Limit and the contract limit scale together, by the tier the previous
close's balance falls in:

> "$0 – $1,499 2 Contracts $1,000 DLL Level 1 $1,500 – $2,999 3 Contracts $1,000 DLL Level 2 $3,000 – $5,999 4 Contracts $2,000 DLL Level 3 $6,000 & Up 4 Contracts $3,000 DLL Level 4"
>
> — `https://apextraderfunding.com/help-center/additional-helpful-items/daily-loss-limit-explained/` (snapshot `24548f42f504`, Tier Levels by Account Size, $50K Performance Account)

> "Position size is checked in real time when you place an order. If an order would cause your total exposure to exceed the maximum allowed size, it is automatically rejected."
>
> — `https://apextraderfunding.com/help-center/additional-helpful-items/scaling-levels-pa-explained/` (snapshot `384413b44ab9`, How Position size is enforced)

> "Tier Levels are updated once per trading day before the trading session begins, and are based on your ending account balance at market close (4:59:59 PM ET) of the prior full trading session."
>
> — `https://apextraderfunding.com/help-center/additional-helpful-items/scaling-levels-pa-explained/` (snapshot `384413b44ab9`, How Tier Levels Are Updated)

Payout eligibility, the safety net and the per-request cap ladder:

> "50K 5 $250 $52,100 $52,600 6"
>
> — `https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-payouts/` (snapshot `88b18494991d`, Payout Requirements table (Min Trade Days / Min Daily Profit / Safety Net / Min Balance to Request / Max Payouts))

> "6 $1,000 $3,000 $4,000 $5,000"
>
> — `https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-payouts/` (snapshot `88b18494991d`, Max Payouts table, row Payout 6)

> "Approved payouts are issued at a 100% payout split, you receive 100% of the approved payout amount."
>
> — `https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-payouts/` (snapshot `88b18494991d`, Payouts at a glance)

> "No single profitable trading day may account for 50% or more of total profit earned since your last approved payout."
>
> — `https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-payouts/` (snapshot `88b18494991d`, 50% Consistency Requirement)

> "Future payout eligibility is based only on profits earned after the last approved payout."
>
> — `https://apextraderfunding.com/help-center/additional-helpful-items/50-consistency-requirement/` (snapshot `4a1906d395be`, Reset After Payout)

> "Your largest profitable trading day must represent less than 50% of your net profit since your last payout request, or since account inception if no payout has been made."
>
> — `https://apextraderfunding.com/help-center/additional-helpful-items/50-consistency-requirement/` (snapshot `4a1906d395be`, How it works)

The inactivity rule is a count of qualifying days in a rolling window, not a gap between
traded days. Round 2 of the vocabulary added exactly that kind (`activity_requirement`), so
it is now a modeled rule in every funded phase instead of a `not_modeled` entry (section
9):

> "For Performance Accounts (PAs) to remain active, you must record at least 2 trading days with $50 or more in net profit within every rolling 30-day period."
>
> — `https://apextraderfunding.com/help-center/billing/inactivity-policy-on-performance-accounts-pa` (snapshot `5b7d69544e04`, Inactivity Policy)

> "Calendar days include weekends and holidays, which are all counted as part of the rolling 30 days."
>
> — `https://apextraderfunding.com/help-center/billing/inactivity-policy-on-performance-accounts-pa` (snapshot `5b7d69544e04`, What does “rolling 30 days” mean?)

`days: 2`, `window: 30`, `unit: calendar_days`, `qualifies_if {min_pnl_usd: 50}`,
`observed: eod`, `comparison: '>='`, `action: close_account`. A qualifying day is a
rule-day whose session ends at least $50 up (the page says a breakeven day does not count),
and the first window starts on the PA's own first day, as the page states (the purchase date
is day 1 of the initial 30-day period). The engine tests every FULL rolling
30-calendar-day window ending at a rule-day close. Apex's own phrasing - count from the
earlier of your 2 most recent qualifying days - is the same test: that day is outside the
lookback exactly when fewer than 2 qualifying days remain in it. The consequence is the
firm's: the account is closed and its payout eligibility forfeited, so the action is
`close_account` and the test runs before the pass conditions at that close.

### 3.4 The trading day, the flatten clock and the time zone

> "ALL times are published in the USA Eastern Time zone."
>
> — `https://apextraderfunding.com/help-center/helpful-items/what-time-zone-do-you-operate-in/` (snapshot `8a85ffc77d7f`, What Time Zone Do You Use)

> "A trading day is defined from 6 PM ET one day to 4:59 PM ET the next day ."
>
> — `https://apextraderfunding.com/help-center/getting-started/futures-trading-times/` (snapshot `639a215e3dc3`, Understanding Trading Days and System Updates)

> "All trades must be closed before 4:59 PM ET. It is your responsibility to ensure that your account is flat before 4:59 PM ET."
>
> — `https://apextraderfunding.com/help-center/getting-started/futures-trading-times/` (snapshot `639a215e3dc3`, Trading Times)

> "Holding open trade positions through the market close. Traders are responsible for ensuring that all open trade positions are closed prior to the market close. Traders engaging in these prohibited activities will forfeit their accounts and all associated balances."
>
> — `https://apextraderfunding.com/help-center/getting-started/prohibited-activities` (snapshot `494fd6da079c`, Prohibited Activities)

The flatten deadline is declared relative to the session, `minutes_before_session_end: 1`,
not as a fixed 16:59 clock: 4:59 PM ET is one minute before the 5:00 PM ET end of a regular
CME session, so a holiday early close moves the deadline with the calendar (2024-11-29,
whose 12:15 Chicago close is the sourced instance, makes it 13:14 ET) instead of a guessed
fixed time. A session the CME table cannot source is reported by the engine at attempt time
(`session_calendar_gaps`, and the estimate becomes `partial`), which is why no per-file
holiday-early-close entry is declared: an unsourced window is a fact about an attempt, not
a rule of the firm. The daily 5-6 PM ET maintenance break leaves no bar to trade between
the flattened close and the 6:00 PM ET reopen, so the rule declares no reopen clock.

## 4. Commissions (per side, USD)

### 4.1 Platform availability (sourced, never assumed)

Apex sells the same two programs on three platforms. Commissions are part of a
ruleset (ADR-0107 section 10) and the three schedules differ, so a platform is a
**variant axis** and every platform gets its own files. Availability is taken from
three official statements, never from a guess:

1. the evaluation position-sizing page links one commission and instrument page per
   platform, and the same page says the contract limits are 'identical for both EOD
   and Intraday Trailing evaluations';
2. the site navigation offers the three platforms as products;
3. the site's product catalogue (the same `productPickerV3Config` the values come
   from) carries one record per platform, program, size, purchase path and pack, each
   with its `platform` field and its own signup `product_url` on the dashboard.

> "Rithmic Commissions & Instruments Tradovate Commission & Instruments WealthCharts Commissions & Instruments"
>
> — `https://apextraderfunding.com/help-center/additional-helpful-items/position-sizing-evaluation/` (snapshot `2986d80b60c5`, one commission and instrument page per platform)

> "Products Tradovate Rithmic WealthCharts"
>
> — `https://apextraderfunding.com/` (snapshot `3545df973d7e`, site navigation, Products menu)

> "Welcome to the current commission schedule for both Evaluation and Paid/Funded Accounts"
>
> — `https://apextraderfunding.com/help-center/rithmic/rithmic-commissions-instruments` (snapshot `311ecf4b57d2`, Commissions for this platform)

> "Welcome to the current commission schedule for both Evaluation and Paid/Funded Accounts"
>
> — `https://apextraderfunding.com/help-center/wealthcharts/wealthcharts-commissions-instruments` (snapshot `381ce34e66f4`, Commissions for this platform)

> "Commissions are automatically deducted from your account balance at the time of the trade."
>
> — `https://apextraderfunding.com/help-center/tradovate/tradovate-commission-instruments` (snapshot `dd21d47f1461`, How Commissions Are Deducted)

The catalogue record of each newly added family, quoted with the platform field and the
signup path that exists only on that platform:

> ""platform":"Wealthcharts","scaling""
>
> — `https://apextraderfunding.com/` (snapshot `3545df973d7e`, productPickerV3Config, id 5002 "50k Wealthcharts EOD Trail", platform)

> ""product_url":"https:\/\/dashboard.apextraderfunding.com\/signup\/50k-Wealthcharts-eod-trail""
>
> — `https://apextraderfunding.com/` (snapshot `3545df973d7e`, productPickerV3Config, id 5002 "50k Wealthcharts EOD Trail", product_url)

> ""platform":"Wealthcharts","scaling""
>
> — `https://apextraderfunding.com/` (snapshot `3545df973d7e`, productPickerV3Config, id 5018 "50k Wealthcharts Intraday Trail", platform)

> ""product_url":"https:\/\/dashboard.apextraderfunding.com\/signup\/50k-Wealthcharts-intraday-trail""
>
> — `https://apextraderfunding.com/` (snapshot `3545df973d7e`, productPickerV3Config, id 5018 "50k Wealthcharts Intraday Trail", product_url)

> ""platform":"Tradovate","scaling""
>
> — `https://apextraderfunding.com/` (snapshot `3545df973d7e`, productPickerV3Config, id 4018 "50k Tradovate Intraday Trail", platform)

> ""product_url":"https:\/\/dashboard.apextraderfunding.com\/signup\/50k-Tradovate-intraday-trail""
>
> — `https://apextraderfunding.com/` (snapshot `3545df973d7e`, productPickerV3Config, id 4018 "50k Tradovate Intraday Trail", product_url)

Consequence: 90 rulesets, 30 per platform (EOD 14 + intraday 16), cover every
product, size, pack and fee variant the catalogue sells. The only combinations it
does **not** sell are the 100k and 150k
No-Activation-Fee packs (EOD: 25k and 50k only; intraday: all four sizes), and no
file exists for them.

### 4.2 The schedules

Apex publishes one schedule per platform, for **both** evaluations and Performance
Accounts. All three pages were fetched in this pass; the values differ by platform, which
is why every ruleset carries its own platform's table.

| root | Rithmic | Tradovate | WealthCharts |
|---|---|---|---|
| ES | 1.99 | 1.55 | 1.55 |
| NQ | 1.99 | 1.55 | 1.55 |
| YM | 1.99 | 1.55 | 1.55 |
| RTY | 1.99 | 1.55 | 1.55 |
| NKD | 1.99 | 2.32 | 2.32 |
| MES | 0.51 | 0.52 | 0.52 |
| MNQ | 0.51 | 0.52 | 0.52 |
| MYM | 0.51 | 0.52 | 0.52 |
| M2K | 0.51 | 0.52 | 0.52 |

> "The per side commission is $1.99"
>
> — `https://apextraderfunding.com/help-center/rithmic/rithmic-commissions-instruments` (snapshot `311ecf4b57d2`, How Commissions Are Deducted)

> "E-mini S&P 500 (ES) ES CME 1.99 3.98"
>
> — `https://apextraderfunding.com/help-center/rithmic/rithmic-commissions-instruments` (snapshot `311ecf4b57d2`, Current Commission Schedule)

> "Micro E-Mini S&P 500 (MES) MES CME 0.51 1.02"
>
> — `https://apextraderfunding.com/help-center/rithmic/rithmic-commissions-instruments` (snapshot `311ecf4b57d2`, Micro Futures)

> "E-Mini S&P 500 ES CME 1.55 3.1"
>
> — `https://apextraderfunding.com/help-center/tradovate/tradovate-commission-instruments` (snapshot `dd21d47f1461`, Current Commission Schedule)

> "Nikkei 225 (USD) NKD CME 2.32 4.64"
>
> — `https://apextraderfunding.com/help-center/tradovate/tradovate-commission-instruments` (snapshot `dd21d47f1461`, Equity Futures)

> "Micro E-Mini S&P 500 MES CME 0.52 1.04"
>
> — `https://apextraderfunding.com/help-center/tradovate/tradovate-commission-instruments` (snapshot `dd21d47f1461`, Micro Futures)

> "E-Mini S&P 500 ES CME 1.55 3.1"
>
> — `https://apextraderfunding.com/help-center/wealthcharts/wealthcharts-commissions-instruments` (snapshot `381ce34e66f4`, Commissions)

> "Nikkei 225 (USD) NKD CME 2.32 4.64"
>
> — `https://apextraderfunding.com/help-center/wealthcharts/wealthcharts-commissions-instruments` (snapshot `381ce34e66f4`, Equity Futures)

> "Micro E-Mini S&P 500 MES CME 0.52 1.04"
>
> — `https://apextraderfunding.com/help-center/wealthcharts/wealthcharts-commissions-instruments` (snapshot `381ce34e66f4`, Micro Futures)

Each ruleset's `commissions.source` quotes the whole block from the Equity Futures
rows through the Micro Futures rows of its **own** platform's page, so every
per-side number used is inside the quotation and under that page's hash. Tradovate
and WealthCharts happen to charge the same per-side amounts (1.55 / 2.32 / 0.52);
they are still separate files with separate sources, because a schedule is one
platform's own document and either could change alone.

**NKD is not a micro.** No micro Nikkei is offered, Apex treats NKD as a standard
contract (weight 1), and it is the one root whose commission differs from the other
minis.

### 4.3 Does the commission include the exchange and regulatory fees? No page says

The engine requires the declaration (`commissions.components`, all four keys), because the
difference between an all-in commission and a commission that excludes the exchange and
NFA fees is a real cost (ADR-0107 section 8). Every Apex page was re-read for it in round 2
and none states it:

- the three commission pages carry `Name / Symbol / Exchange / Per Side / Round Turn` and
  the worked example (`2 contracts multiplied by $1.99 commission = $3.98`), which is the
  commission doubled, not a commission plus a fee;
- the only fee note on any of them is a per-instrument one, and it names no root of ours;
- no other Apex page (how-it-works, accounts, legacy and new products, the payouts pages,
  the evaluation and PA pages) mentions an exchange fee, an NFA assessment or a clearing
  fee at all.

> "Instruments marked in red text have extra fees associated with them."
>
> — `https://apextraderfunding.com/help-center/tradovate/tradovate-commission-instruments` (snapshot `dd21d47f1461`, Additional Fees)

So every component is `unknown` in all 90 files,
with the platform's own page as its source (the same attribution the per-side table uses).
It is NOT `true`: reading a per-side table as all-in because the number looks plausible is
exactly the guess AGENTS.md section 1 forbids, and it is not `false` either, because no
page says a fee is added. The consequence is the schema's: `unknown` is a cost gap, so the
cost-dependent statistics are `unavailable` (never a commission of zero, and never a
silent all-in) until the owner supplies the fact. That single fact is what turns a
`partial` estimate into a `complete` one (open question 1).

## 5. News rules

No `news_restriction` rule is declared for Apex, because the firm states no event type, no
restricted instrument, no pre- or post-event window and no scope. Its rule is a conduct
standard judged case by case:

> "NEWS TRADING: Trading during news is allowed for your normal trading strategy. Using “news trading” strategies that “chase the market” or place orders on both sides but to be lucky or gamble the outcome of news is not allowed."
>
> — `https://apextraderfunding.com/help-center/getting-started/prohibited-activities` (snapshot `494fd6da079c`, Prohibited Activities)

That is exactly the case ADR-0107 section 7 calls `not_modeled` with materiality `material`
(`news_trading_restriction_is_discretionary`, in every file): a discretionary news rule.
Apex names no FOMC, CPI or NFP window, so no calendar coverage gap can be claimed either.
The economic calendar now also carries PPI, the FOMC press conference and the FOMC minutes,
and `news_restriction` now declares an `effect` (block or a contract cap); neither changes
anything here, because there is no Apex rule to attach them to. Inventing a window from a
general 'news trading is allowed' sentence would be the engine inventing a firm rule.

## 6. Compliance rules (practical eligibility, never the mechanical account)

The Prohibited Activities page is firm-wide: it names no plan, size or platform, so the
rules apply to every product in this directory and are declared once, in the evaluation
phase (practical eligibility is a ruleset-level fact).

| rule id | restriction | appears for | materiality | action |
|---|---|---|---|---|
| `compliance_no_automation` | automated systems / algorithms executing preprogrammed logic | `automated` | **critical** | block |
| `compliance_no_trade_copying` | trade copying and account/resource sharing | `automated`, `manual` | material | block |
| `compliance_no_high_risk_strategy` | small profit target with disproportionately large risk | `automated`, `manual` | material | block |

> "No Automation or Algorithm Usage allowed: Rewards are intended to recognize human traders actively participating in the learning process, not to reward automated systems executing preprogrammed logic."
>
> — `https://apextraderfunding.com/help-center/getting-started/prohibited-activities` (snapshot `494fd6da079c`, Prohibited Activities)

> "Account and Resource Sharing: Sharing MAC addresses, computers, IPs, credit cards, or trade copying with other traders is strictly forbidden."
>
> — `https://apextraderfunding.com/help-center/getting-started/prohibited-activities` (snapshot `494fd6da079c`, Prohibited Activities)

> "High-Risk Strategies: Strategies that involve small profit targets while risking disproportionately large amounts are not allowed."
>
> — `https://apextraderfunding.com/help-center/getting-started/prohibited-activities` (snapshot `494fd6da079c`, Prohibited Activities)

Consequence: `practical_eligibility` is `blocked_by_compliance` for `execution_mode:
automated` on **every** Apex ruleset, so a mechanically successful Apex attempt is never
reported as a practically valid pass. With `execution_mode: manual` the other two
compliance rules are recorded but do not block, because neither is critical.

Hedging is **not** a compliance rule: it needs position-level logic the compliance kind
does not carry, so it is `not_modeled` (section 9).

## 7. Conflicts (both sources, the selected value, the alternative)

Applied check before either was called a conflict: same firm, same program, same account
size, same phase, same platform and same retrieval date.

### 7.1 `evaluation_consistency` (every file)

Selected: the evaluation carries a 30% consistency pass condition (`max_day_share: 0.3`, `applies_to: pass`, `window: all_time`). Alternative (`evaluation_consistency#0`): `value: absent`, the reading in which the rule does not exist at all, which is exactly what the rendered table says ('Consistency Not Applied'). The round-2 `absent` marker is used instead of the old `max_day_share: 1.0`, which widened the rule rather than removing it: a sensitivity scenario for 'not applied' must carry no consistency condition.

Source A — the store configuration of the product (the selected value):

> ""consistency_rule_percentage":30"
>
> — `https://apextraderfunding.com/` (snapshot `3545df973d7e`, productPickerV3Config, consistency_rule_percentage of every 2026 evaluation record)

Source B — the rendered rules table (the alternative):

> "Consistency Not Applied Not Applied Not Applied Not Applied"
>
> — `https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-evaluations/` (snapshot `b66748ac193d`, Account Parameters table, Consistency row)

Why the constraint is the selected value: ADR-0107 section 7 requires the more restrictive
reading of a genuine conflict, and a constraint is more restrictive than none. Why it is
still a conflict: the rendered table is the page a trader reads, the store's
`consistency_rule_percentage` is the value the platform charges, and the record even
carries a second field with the same 30 (`max_eval_daily_profit_percent`). The owner must
confirm this one; it is the single most consequential choice in these files, because it
means an evaluation passes only once its best day is at most 30% of its total profit.

### 7.2 `tradovate_eod_lock` (the 12 EOD Tradovate files)

Selected: no lock (the threshold trails the peak EOD balance indefinitely). Alternative (`tradovate_eod_lock#0`): the `lock` of the same product's `auto_liq_min_max`, i.e. threshold fixed at the profit-target balance once the peak reaches target + drawdown.

Source A — the drawdown article (the selected value):

> "Evaluations Tradovate EOD Drawdown trails indefinitely with the peak EOD account balance."
>
> — `https://apextraderfunding.com/help-center/eod-trailing-drawdown-accounts/eod-drawdown-explained/` (snapshot `4b1a18d8c402`, When EOD Drawdown Stops Trailing - Evaluations Tradovate)

Source B — the product record of the same product (the alternative):

> ""auto_liq_min_max":53000"
>
> — `https://apextraderfunding.com/` (snapshot `3545df973d7e`, productPickerV3Config, id 4002 "50k Tradovate EOD Trail", auto_liq_min_max)

Why no lock is selected: trailing forever leaves the smaller buffer, so it is the more
restrictive reading, and it is also what the article says. Immaterial in practice, because
the lock engages only above the balance at which the evaluation has already passed.

## 8. Assumptions (named, each with its rationale)

Only two values needed an assumption, both for the **intraday** program, where no page
states where the trailing threshold stops. Both are `evidence: assumption` on the trailing
rule itself.

| name | files | value | rationale |
|---|---|---|---|
| `intraday_evaluation_lock_taken_from_auto_liq_min_max` | 48 | lock at the profit-target balance, reached at peak = lock + drawdown | No page states a stop level; the product's own `auto_liq_min_max` is that balance and the shape is taken from the EOD drawdown page for the EOD evaluation. Unreachable before the pass. |
| `intraday_pa_lock_taken_from_pa_auto_liq_min_max` | 48 | threshold fixed at starting balance + $100, reached at peak = start + drawdown + $100 | The intraday PA page states only that trailing stops; the level is the product's `pa_auto_liq_min_max`, the same structure the EOD PA page states in prose. |

Nothing else in these files is an assumption: the time zone is published (`ALL times are
published in the USA Eastern Time zone`, mapped to `America/New_York` including DST), the
observation frequency of every threshold is stated (`monitored in real time`, `calculated
once per trading day at 4:59:59 PM ET`), the profit target is judged on the closed balance
(`reviewed at market close`), and Apex states the reset clock itself (`DLL resets daily at
6PM ET`, `A trading day is defined from 6 PM ET one day to 4:59 PM ET the next day`).

In particular no file needs the `unspecified_target_frequency_is_eod` default: Apex
states the moment the evaluation target is judged, so every pass condition is
`evaluated: eod` on the closed balance (`basis: balance`) under an `official_quote`, and
no target is checked intraday anywhere in the 90 files.

The commission's four `unknown` components are **not** an assumption:
it is a declaration that the sources are silent (ADR-0107 section 8), and it leaves the cost
statistics unavailable rather than making the commission all-in by default (section 4.3).

Where the pages are silent about a rule that would change a result the entry is
`not_modeled` instead of an assumption (section 9): no page states a PA access period, so
the funded phase carries no `time_limit` and no entry, because a missing limit is not a
rule the firm states.

## 9. `not_modeled`, by materiality

| entry | materiality | files | why it is not modeled |
|---|---|---|---|
| `sub_minute_holding_and_high_frequency_trading` | material | 90/90 | OHLC bars cannot detect a holding time shorter than the bar; Apex bans HFT and exploitation of the simulation |
| `within_account_hedging_of_correlated_instruments` | material | 90/90 | one net position per instrument, but a long NQ against a short ES is representable and the engine has no correlated-instrument logic |
| `news_trading_restriction_is_discretionary` | material | 90/90 | Apex names no event type, instrument, window or scope; it judges the strategy (section 5) |
| `hedging_between_evaluation_accounts` | immaterial | 90/90 | a single simulated account cannot hedge another account |
| `evaluation_daily_profit_percent_field` | immaterial | 90/90 | the store record also carries `max_eval_daily_profit_percent: 30`; no page explains it and it is most likely the same 30% consistency, so it is not counted twice |
| `five_pack_is_five_separate_accounts` | immaterial | 42/90 | five accounts at one price, modeled as one account at a fifth of the price |
| `activation_fee_waiver` | immaterial | 42/90 | the waiver is `free_activation: true` in the store; no page states the waived amount |

The owner's standing entries are present: sub-minute holding and micro-scalping (`90` files), cross-account hedging (`90` files), and - checked against every snapshot - no Apex page states a 2% price-limit restriction, so no such entry exists for this firm (it is a Topstep rule).

## 10. `not_modeled` entries removed because the vocabulary models them exactly

| v1 entry | now modeled by |
|---|---|
| `daily_loss_limit_is_tier_based_in_the_pa` | `daily_loss.amount_by_balance_tier` (the published PA ladder) |
| `max_payout_per_request_is_a_ladder` | `payout.max_usd_by_payout` (all six rungs) |
| `payout_window_resets_after_each_payout` | `payout.window: since_last_payout` and `consistency.window: since_last_payout` |
| `scaling_plan_rejects_an_oversized_order` | `scaling_plan.action: reject` |
| `no_automated_or_algorithmic_trading` | `compliance` rule `compliance_no_automation` (critical, `blocked_by_compliance` for automated execution) |
| `pa_inactivity_closure` (round 2) | `activity_requirement` in the funded phase: 2 qualifying days (`min_pnl_usd: 50`) in every rolling 30 `calendar_days`, `action: close_account` |

The `inactivity` kind is still not what Apex describes (it measures a gap since the last traded day, not a count of qualifying days in a window), which is why the entry waited for the round-2 `activity_requirement` and no file uses `inactivity`.

## 11. Product matrix (regenerated from the YAML)

One row per file. `lock a->b` is the peak balance at which the trailing threshold stops and
the level it then holds (`on: [hwm]` is the only trigger Apex states); `tiers` are the PA's
(DLL by balance tier); `scale` is the PA's (contract limit by profit, above the starting
balance); `cap` is the per-request payout ladder; `flat` is the forced-flat deadline, one
minute before the CME scheduled session close in every file; `PA activity` is the rolling
window rule (`2d>=$50/30cd` = two days of at least $50 net profit in every rolling 30
calendar days).

| file | size | plat | path | target | eval DD | eval lock | eval DLL | eval contracts | PA DD | PA lock | PA DLL tiers | scale | pay days / day profit | safety net | cap ladder | fees | flat | PA activity |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `apex-eod-100k-5pack` | $100,000 | Rithmic | standard 5-pack | $6,000 | $3,000 | lock $109,000->$106,000 | $1,500 | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$300 | $3,100 buffer | $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000 | evaluation $990 at_start, activation $139 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-100k-no-activation-fee` | $100,000 | Rithmic | no-act | $6,000 | $3,000 | lock $109,000->$106,000 | $1,500 | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$300 | $3,100 buffer | $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000 | evaluation $1,590 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-100k-tradovate-5pack` | $100,000 | Tradovate | standard 5-pack | $6,000 | $3,000 | no lock | $1,500 | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$300 | $3,100 buffer | $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000 | evaluation $990 at_start, activation $139 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-100k-tradovate-no-activation-fee` | $100,000 | Tradovate | no-act | $6,000 | $3,000 | no lock | $1,500 | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$300 | $3,100 buffer | $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000 | evaluation $1,590 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-100k-tradovate` | $100,000 | Tradovate | standard | $6,000 | $3,000 | no lock | $1,500 | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$300 | $3,100 buffer | $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000 | evaluation $1,190 at_start, activation $139 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-100k-wealthcharts-5pack` | $100,000 | WealthCharts | standard 5-pack | $6,000 | $3,000 | lock $109,000->$106,000 | $1,500 | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$300 | $3,100 buffer | $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000 | evaluation $990 at_start, activation $139 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-100k-wealthcharts-no-activation-fee` | $100,000 | WealthCharts | no-act | $6,000 | $3,000 | lock $109,000->$106,000 | $1,500 | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$300 | $3,100 buffer | $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000 | evaluation $1,590 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-100k-wealthcharts` | $100,000 | WealthCharts | standard | $6,000 | $3,000 | lock $109,000->$106,000 | $1,500 | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$300 | $3,100 buffer | $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000 | evaluation $1,190 at_start, activation $139 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-100k` | $100,000 | Rithmic | standard | $6,000 | $3,000 | lock $109,000->$106,000 | $1,500 | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$300 | $3,100 buffer | $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000 | evaluation $1,190 at_start, activation $139 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-150k-5pack` | $150,000 | Rithmic | standard 5-pack | $9,000 | $4,000 | lock $163,000->$159,000 | $2,000 | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$350 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000 | evaluation $1,990 at_start, activation $159 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-150k-no-activation-fee` | $150,000 | Rithmic | no-act | $9,000 | $4,000 | lock $163,000->$159,000 | $2,000 | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$350 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000 | evaluation $2,490 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-150k-tradovate-5pack` | $150,000 | Tradovate | standard 5-pack | $9,000 | $4,000 | no lock | $2,000 | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$350 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000 | evaluation $1,990 at_start, activation $159 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-150k-tradovate-no-activation-fee` | $150,000 | Tradovate | no-act | $9,000 | $4,000 | no lock | $2,000 | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$350 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000 | evaluation $2,490 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-150k-tradovate` | $150,000 | Tradovate | standard | $9,000 | $4,000 | no lock | $2,000 | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$350 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000 | evaluation $2,190 at_start, activation $159 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-150k-wealthcharts-5pack` | $150,000 | WealthCharts | standard 5-pack | $9,000 | $4,000 | lock $163,000->$159,000 | $2,000 | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$350 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000 | evaluation $1,990 at_start, activation $159 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-150k-wealthcharts-no-activation-fee` | $150,000 | WealthCharts | no-act | $9,000 | $4,000 | lock $163,000->$159,000 | $2,000 | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$350 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000 | evaluation $2,490 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-150k-wealthcharts` | $150,000 | WealthCharts | standard | $9,000 | $4,000 | lock $163,000->$159,000 | $2,000 | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$350 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000 | evaluation $2,190 at_start, activation $159 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-150k` | $150,000 | Rithmic | standard | $9,000 | $4,000 | lock $163,000->$159,000 | $2,000 | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$350 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000 | evaluation $2,190 at_start, activation $159 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-25k-5pack` | $25,000 | Rithmic | standard 5-pack | $1,500 | $1,000 | lock $27,500->$26,500 | $500 | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $450 at_start, activation $109 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-25k-no-activation-fee-5pack` | $25,000 | Rithmic | no-act 5-pack | $1,500 | $1,000 | lock $27,500->$26,500 | $500 | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $890 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-25k-no-activation-fee` | $25,000 | Rithmic | no-act | $1,500 | $1,000 | lock $27,500->$26,500 | $500 | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $1,090 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-25k-tradovate-5pack` | $25,000 | Tradovate | standard 5-pack | $1,500 | $1,000 | no lock | $500 | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $450 at_start, activation $109 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-25k-tradovate-no-activation-fee-5pack` | $25,000 | Tradovate | no-act 5-pack | $1,500 | $1,000 | no lock | $500 | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $890 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-25k-tradovate-no-activation-fee` | $25,000 | Tradovate | no-act | $1,500 | $1,000 | no lock | $500 | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $1,090 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-25k-tradovate` | $25,000 | Tradovate | standard | $1,500 | $1,000 | no lock | $500 | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $490 at_start, activation $109 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-25k-wealthcharts-5pack` | $25,000 | WealthCharts | standard 5-pack | $1,500 | $1,000 | lock $27,500->$26,500 | $500 | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $450 at_start, activation $109 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-25k-wealthcharts-no-activation-fee-5pack` | $25,000 | WealthCharts | no-act 5-pack | $1,500 | $1,000 | lock $27,500->$26,500 | $500 | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $890 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-25k-wealthcharts-no-activation-fee` | $25,000 | WealthCharts | no-act | $1,500 | $1,000 | lock $27,500->$26,500 | $500 | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $1,090 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-25k-wealthcharts` | $25,000 | WealthCharts | standard | $1,500 | $1,000 | lock $27,500->$26,500 | $500 | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $490 at_start, activation $109 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-25k` | $25,000 | Rithmic | standard | $1,500 | $1,000 | lock $27,500->$26,500 | $500 | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $490 at_start, activation $109 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-50k-5pack` | $50,000 | Rithmic | standard 5-pack | $3,000 | $2,000 | lock $55,000->$53,000 | $1,000 | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$250 | $2,100 buffer | $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000 | evaluation $490 at_start, activation $129 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-50k-no-activation-fee-5pack` | $50,000 | Rithmic | no-act 5-pack | $3,000 | $2,000 | lock $55,000->$53,000 | $1,000 | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$250 | $2,100 buffer | $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000 | evaluation $1,090 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-50k-no-activation-fee` | $50,000 | Rithmic | no-act | $3,000 | $2,000 | lock $55,000->$53,000 | $1,000 | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$250 | $2,100 buffer | $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000 | evaluation $1,190 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-50k-tradovate-5pack` | $50,000 | Tradovate | standard 5-pack | $3,000 | $2,000 | no lock | $1,000 | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$250 | $2,100 buffer | $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000 | evaluation $490 at_start, activation $129 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-50k-tradovate-no-activation-fee-5pack` | $50,000 | Tradovate | no-act 5-pack | $3,000 | $2,000 | no lock | $1,000 | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$250 | $2,100 buffer | $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000 | evaluation $1,090 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-50k-tradovate-no-activation-fee` | $50,000 | Tradovate | no-act | $3,000 | $2,000 | no lock | $1,000 | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$250 | $2,100 buffer | $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000 | evaluation $1,190 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-50k-tradovate` | $50,000 | Tradovate | standard | $3,000 | $2,000 | no lock | $1,000 | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$250 | $2,100 buffer | $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000 | evaluation $590 at_start, activation $129 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-50k-wealthcharts-5pack` | $50,000 | WealthCharts | standard 5-pack | $3,000 | $2,000 | lock $55,000->$53,000 | $1,000 | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$250 | $2,100 buffer | $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000 | evaluation $490 at_start, activation $129 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-50k-wealthcharts-no-activation-fee-5pack` | $50,000 | WealthCharts | no-act 5-pack | $3,000 | $2,000 | lock $55,000->$53,000 | $1,000 | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$250 | $2,100 buffer | $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000 | evaluation $1,090 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-50k-wealthcharts-no-activation-fee` | $50,000 | WealthCharts | no-act | $3,000 | $2,000 | lock $55,000->$53,000 | $1,000 | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$250 | $2,100 buffer | $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000 | evaluation $1,190 at_start | 1min before close | 2d>=$50/30cd |
| `apex-eod-50k-wealthcharts` | $50,000 | WealthCharts | standard | $3,000 | $2,000 | lock $55,000->$53,000 | $1,000 | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$250 | $2,100 buffer | $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000 | evaluation $590 at_start, activation $129 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-eod-50k` | $50,000 | Rithmic | standard | $3,000 | $2,000 | lock $55,000->$53,000 | $1,000 | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$250 | $2,100 buffer | $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000 | evaluation $590 at_start, activation $129 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-100k-5pack` | $100,000 | Rithmic | standard 5-pack | $6,000 | $3,000 | lock $109,000->$106,000 | - | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$250 | $3,100 buffer | $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000 | evaluation $690 at_start, activation $129 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-100k-no-activation-fee-5pack` | $100,000 | Rithmic | no-act 5-pack | $6,000 | $3,000 | lock $109,000->$106,000 | - | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$250 | $3,100 buffer | $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000 | evaluation $890 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-100k-no-activation-fee` | $100,000 | Rithmic | no-act | $6,000 | $3,000 | lock $109,000->$106,000 | - | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$250 | $3,100 buffer | $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000 | evaluation $999 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-100k-tradovate-5pack` | $100,000 | Tradovate | standard 5-pack | $6,000 | $3,000 | lock $109,000->$106,000 | - | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$250 | $3,100 buffer | $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000 | evaluation $690 at_start, activation $129 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-100k-tradovate-no-activation-fee-5pack` | $100,000 | Tradovate | no-act 5-pack | $6,000 | $3,000 | lock $109,000->$106,000 | - | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$250 | $3,100 buffer | $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000 | evaluation $890 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-100k-tradovate-no-activation-fee` | $100,000 | Tradovate | no-act | $6,000 | $3,000 | lock $109,000->$106,000 | - | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$250 | $3,100 buffer | $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000 | evaluation $999 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-100k-tradovate` | $100,000 | Tradovate | standard | $6,000 | $3,000 | lock $109,000->$106,000 | - | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$250 | $3,100 buffer | $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000 | evaluation $790 at_start, activation $129 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-100k-wealthcharts-5pack` | $100,000 | WealthCharts | standard 5-pack | $6,000 | $3,000 | lock $109,000->$106,000 | - | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$250 | $3,100 buffer | $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000 | evaluation $690 at_start, activation $129 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-100k-wealthcharts-no-activation-fee-5pack` | $100,000 | WealthCharts | no-act 5-pack | $6,000 | $3,000 | lock $109,000->$106,000 | - | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$250 | $3,100 buffer | $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000 | evaluation $890 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-100k-wealthcharts-no-activation-fee` | $100,000 | WealthCharts | no-act | $6,000 | $3,000 | lock $109,000->$106,000 | - | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$250 | $3,100 buffer | $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000 | evaluation $999 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-100k-wealthcharts` | $100,000 | WealthCharts | standard | $6,000 | $3,000 | lock $109,000->$106,000 | - | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$250 | $3,100 buffer | $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000 | evaluation $790 at_start, activation $129 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-100k` | $100,000 | Rithmic | standard | $6,000 | $3,000 | lock $109,000->$106,000 | - | 8 | $3,000 | lock $103,100->$100,100 | $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000 | 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000 | 5d>=$250 | $3,100 buffer | $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000 | evaluation $790 at_start, activation $129 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-150k-5pack` | $150,000 | Rithmic | standard 5-pack | $9,000 | $4,000 | lock $163,000->$159,000 | - | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$300 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000 | evaluation $990 at_start, activation $149 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-150k-no-activation-fee-5pack` | $150,000 | Rithmic | no-act 5-pack | $9,000 | $4,000 | lock $163,000->$159,000 | - | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$300 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000 | evaluation $1,790 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-150k-no-activation-fee` | $150,000 | Rithmic | no-act | $9,000 | $4,000 | lock $163,000->$159,000 | - | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$300 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000 | evaluation $1,890 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-150k-tradovate-5pack` | $150,000 | Tradovate | standard 5-pack | $9,000 | $4,000 | lock $163,000->$159,000 | - | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$300 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000 | evaluation $990 at_start, activation $149 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-150k-tradovate-no-activation-fee-5pack` | $150,000 | Tradovate | no-act 5-pack | $9,000 | $4,000 | lock $163,000->$159,000 | - | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$300 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000 | evaluation $1,790 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-150k-tradovate-no-activation-fee` | $150,000 | Tradovate | no-act | $9,000 | $4,000 | lock $163,000->$159,000 | - | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$300 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000 | evaluation $1,890 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-150k-tradovate` | $150,000 | Tradovate | standard | $9,000 | $4,000 | lock $163,000->$159,000 | - | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$300 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000 | evaluation $1,190 at_start, activation $149 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-150k-wealthcharts-5pack` | $150,000 | WealthCharts | standard 5-pack | $9,000 | $4,000 | lock $163,000->$159,000 | - | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$300 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000 | evaluation $990 at_start, activation $149 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-150k-wealthcharts-no-activation-fee-5pack` | $150,000 | WealthCharts | no-act 5-pack | $9,000 | $4,000 | lock $163,000->$159,000 | - | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$300 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000 | evaluation $1,790 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-150k-wealthcharts-no-activation-fee` | $150,000 | WealthCharts | no-act | $9,000 | $4,000 | lock $163,000->$159,000 | - | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$300 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000 | evaluation $1,890 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-150k-wealthcharts` | $150,000 | WealthCharts | standard | $9,000 | $4,000 | lock $163,000->$159,000 | - | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$300 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000 | evaluation $1,190 at_start, activation $149 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-150k` | $150,000 | Rithmic | standard | $9,000 | $4,000 | lock $163,000->$159,000 | - | 12 | $4,000 | lock $154,100->$150,100 | $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000 | 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000 | 5d>=$300 | $4,100 buffer | $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000 | evaluation $1,190 at_start, activation $149 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-25k-5pack` | $25,000 | Rithmic | standard 5-pack | $1,500 | $1,000 | lock $27,500->$26,500 | - | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $149.9 at_start, activation $89 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-25k-no-activation-fee-5pack` | $25,000 | Rithmic | no-act 5-pack | $1,500 | $1,000 | lock $27,500->$26,500 | - | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $590 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-25k-no-activation-fee` | $25,000 | Rithmic | no-act | $1,500 | $1,000 | lock $27,500->$26,500 | - | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $690 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-25k-tradovate-5pack` | $25,000 | Tradovate | standard 5-pack | $1,500 | $1,000 | lock $27,500->$26,500 | - | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $149.9 at_start, activation $89 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-25k-tradovate-no-activation-fee-5pack` | $25,000 | Tradovate | no-act 5-pack | $1,500 | $1,000 | lock $27,500->$26,500 | - | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $590 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-25k-tradovate-no-activation-fee` | $25,000 | Tradovate | no-act | $1,500 | $1,000 | lock $27,500->$26,500 | - | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $690 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-25k-tradovate` | $25,000 | Tradovate | standard | $1,500 | $1,000 | lock $27,500->$26,500 | - | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $167 at_start, activation $89 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-25k-wealthcharts-5pack` | $25,000 | WealthCharts | standard 5-pack | $1,500 | $1,000 | lock $27,500->$26,500 | - | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $149.9 at_start, activation $89 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-25k-wealthcharts-no-activation-fee-5pack` | $25,000 | WealthCharts | no-act 5-pack | $1,500 | $1,000 | lock $27,500->$26,500 | - | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $590 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-25k-wealthcharts-no-activation-fee` | $25,000 | WealthCharts | no-act | $1,500 | $1,000 | lock $27,500->$26,500 | - | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $690 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-25k-wealthcharts` | $25,000 | WealthCharts | standard | $1,500 | $1,000 | lock $27,500->$26,500 | - | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $167 at_start, activation $89 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-25k` | $25,000 | Rithmic | standard | $1,500 | $1,000 | lock $27,500->$26,500 | - | 4 | $1,000 | lock $26,100->$25,100 | $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000 | 1c@>$0 / 2c@>$1,000 / 2c@>$2,000 | 5d>=$100 | $1,100 buffer | $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000 | evaluation $167 at_start, activation $89 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-50k-5pack` | $50,000 | Rithmic | standard 5-pack | $3,000 | $2,000 | lock $55,000->$53,000 | - | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$200 | $2,100 buffer | $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000 | evaluation $190 at_start, activation $99 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-50k-no-activation-fee-5pack` | $50,000 | Rithmic | no-act 5-pack | $3,000 | $2,000 | lock $55,000->$53,000 | - | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$200 | $2,100 buffer | $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000 | evaluation $690 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-50k-no-activation-fee` | $50,000 | Rithmic | no-act | $3,000 | $2,000 | lock $55,000->$53,000 | - | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$200 | $2,100 buffer | $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000 | evaluation $799 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-50k-tradovate-5pack` | $50,000 | Tradovate | standard 5-pack | $3,000 | $2,000 | lock $55,000->$53,000 | - | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$200 | $2,100 buffer | $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000 | evaluation $190 at_start, activation $99 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-50k-tradovate-no-activation-fee-5pack` | $50,000 | Tradovate | no-act 5-pack | $3,000 | $2,000 | lock $55,000->$53,000 | - | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$200 | $2,100 buffer | $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000 | evaluation $690 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-50k-tradovate-no-activation-fee` | $50,000 | Tradovate | no-act | $3,000 | $2,000 | lock $55,000->$53,000 | - | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$200 | $2,100 buffer | $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000 | evaluation $799 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-50k-tradovate` | $50,000 | Tradovate | standard | $3,000 | $2,000 | lock $55,000->$53,000 | - | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$200 | $2,100 buffer | $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000 | evaluation $249 at_start, activation $99 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-50k-wealthcharts-5pack` | $50,000 | WealthCharts | standard 5-pack | $3,000 | $2,000 | lock $55,000->$53,000 | - | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$200 | $2,100 buffer | $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000 | evaluation $190 at_start, activation $99 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-50k-wealthcharts-no-activation-fee-5pack` | $50,000 | WealthCharts | no-act 5-pack | $3,000 | $2,000 | lock $55,000->$53,000 | - | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$200 | $2,100 buffer | $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000 | evaluation $690 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-50k-wealthcharts-no-activation-fee` | $50,000 | WealthCharts | no-act | $3,000 | $2,000 | lock $55,000->$53,000 | - | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$200 | $2,100 buffer | $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000 | evaluation $799 at_start | 1min before close | 2d>=$50/30cd |
| `apex-intraday-50k-wealthcharts` | $50,000 | WealthCharts | standard | $3,000 | $2,000 | lock $55,000->$53,000 | - | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$200 | $2,100 buffer | $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000 | evaluation $249 at_start, activation $99 at_pass | 1min before close | 2d>=$50/30cd |
| `apex-intraday-50k` | $50,000 | Rithmic | standard | $3,000 | $2,000 | lock $55,000->$53,000 | - | 6 | $2,000 | lock $52,100->$50,100 | $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000 | 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000 | 5d>=$200 | $2,100 buffer | $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000 | evaluation $249 at_start, activation $99 at_pass | 1min before close | 2d>=$50/30cd |

## 12. Owner review checklist, per file

Every value below is what the engine will enforce, grouped the way `crucible prop confirm`
shows it. Confirm the **conflicts** first: they are the only places where an official page
was not followed literally.

### `apex-eod-100k-5pack` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; EOD trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL $1,500; 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $990 at_start, activation $139 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-100k-no-activation-fee` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; EOD trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL $1,500; 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,590 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-100k-tradovate-5pack` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; EOD trailing drawdown $3,000 (no lock); evaluation DLL $1,500; 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $990 at_start, activation $139 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $109,000->$106,000); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-100k-tradovate-no-activation-fee` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; EOD trailing drawdown $3,000 (no lock); evaluation DLL $1,500; 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,590 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $109,000->$106,000); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-100k-tradovate` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; EOD trailing drawdown $3,000 (no lock); evaluation DLL $1,500; 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,190 at_start, activation $139 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $109,000->$106,000); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-100k-wealthcharts-5pack` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; EOD trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL $1,500; 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $990 at_start, activation $139 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-100k-wealthcharts-no-activation-fee` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; EOD trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL $1,500; 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,590 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-100k-wealthcharts` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; EOD trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL $1,500; 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,190 at_start, activation $139 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-100k` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; EOD trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL $1,500; 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $2,500 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,190 at_start, activation $139 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-150k-5pack` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; EOD trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL $2,000; 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $350 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,990 at_start, activation $159 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-150k-no-activation-fee` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; EOD trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL $2,000; 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $350 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $2,490 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-150k-tradovate-5pack` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; EOD trailing drawdown $4,000 (no lock); evaluation DLL $2,000; 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $350 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,990 at_start, activation $159 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $163,000->$159,000); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-150k-tradovate-no-activation-fee` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; EOD trailing drawdown $4,000 (no lock); evaluation DLL $2,000; 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $350 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $2,490 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $163,000->$159,000); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-150k-tradovate` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; EOD trailing drawdown $4,000 (no lock); evaluation DLL $2,000; 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $350 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $2,190 at_start, activation $159 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $163,000->$159,000); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-150k-wealthcharts-5pack` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; EOD trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL $2,000; 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $350 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,990 at_start, activation $159 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-150k-wealthcharts-no-activation-fee` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; EOD trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL $2,000; 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $350 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $2,490 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-150k-wealthcharts` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; EOD trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL $2,000; 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $350 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $2,190 at_start, activation $159 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-150k` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; EOD trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL $2,000; 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $350 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $3,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $2,190 at_start, activation $159 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-25k-5pack` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; EOD trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL $500; 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $450 at_start, activation $109 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-25k-no-activation-fee-5pack` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; EOD trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL $500; 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $890 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-25k-no-activation-fee` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; EOD trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL $500; 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,090 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-25k-tradovate-5pack` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; EOD trailing drawdown $1,000 (no lock); evaluation DLL $500; 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $450 at_start, activation $109 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $27,500->$26,500); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-25k-tradovate-no-activation-fee-5pack` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; EOD trailing drawdown $1,000 (no lock); evaluation DLL $500; 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $890 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $27,500->$26,500); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-25k-tradovate-no-activation-fee` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; EOD trailing drawdown $1,000 (no lock); evaluation DLL $500; 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,090 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $27,500->$26,500); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-25k-tradovate` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; EOD trailing drawdown $1,000 (no lock); evaluation DLL $500; 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $490 at_start, activation $109 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $27,500->$26,500); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-25k-wealthcharts-5pack` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; EOD trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL $500; 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $450 at_start, activation $109 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-25k-wealthcharts-no-activation-fee-5pack` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; EOD trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL $500; 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $890 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-25k-wealthcharts-no-activation-fee` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; EOD trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL $500; 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,090 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-25k-wealthcharts` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; EOD trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL $500; 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $490 at_start, activation $109 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-25k` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; EOD trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL $500; 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $490 at_start, activation $109 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-50k-5pack` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; EOD trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL $1,000; 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $490 at_start, activation $129 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-50k-no-activation-fee-5pack` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; EOD trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL $1,000; 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,090 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-50k-no-activation-fee` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; EOD trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL $1,000; 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,190 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-50k-tradovate-5pack` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; EOD trailing drawdown $2,000 (no lock); evaluation DLL $1,000; 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $490 at_start, activation $129 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $55,000->$53,000); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-50k-tradovate-no-activation-fee-5pack` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; EOD trailing drawdown $2,000 (no lock); evaluation DLL $1,000; 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,090 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $55,000->$53,000); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-50k-tradovate-no-activation-fee` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; EOD trailing drawdown $2,000 (no lock); evaluation DLL $1,000; 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,190 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $55,000->$53,000); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-50k-tradovate` — EOD Drawdown Evaluation (Tradovate) -> EOD Performance Account

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; EOD trailing drawdown $2,000 (no lock); evaluation DLL $1,000; 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $590 at_start, activation $129 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `tradovate_eod_lock`: lock = no lock (alternative lock $55,000->$53,000); `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-50k-wealthcharts-5pack` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; EOD trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL $1,000; 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $490 at_start, activation $129 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-50k-wealthcharts-no-activation-fee-5pack` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; EOD trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL $1,000; 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,090 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-50k-wealthcharts-no-activation-fee` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; EOD trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL $1,000; 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,190 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-50k-wealthcharts` — EOD Drawdown Evaluation (WealthCharts) -> EOD Performance Account

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; EOD trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL $1,000; 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $590 at_start, activation $129 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-eod-50k` — EOD Drawdown Evaluation (Rithmic) -> EOD Performance Account

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; EOD trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL $1,000; 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA EOD trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $1,500 / $2,000 / $2,500 / $2,500 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $590 at_start, activation $129 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: none

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-100k-5pack` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; intraday trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL none (the intraday evaluation has no DLL); 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $690 at_start, activation $129 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-100k-no-activation-fee-5pack` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; intraday trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL none (the intraday evaluation has no DLL); 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $890 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-100k-no-activation-fee` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; intraday trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL none (the intraday evaluation has no DLL); 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $999 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-100k-tradovate-5pack` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; intraday trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL none (the intraday evaluation has no DLL); 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $690 at_start, activation $129 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-100k-tradovate-no-activation-fee-5pack` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; intraday trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL none (the intraday evaluation has no DLL); 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $890 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-100k-tradovate-no-activation-fee` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; intraday trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL none (the intraday evaluation has no DLL); 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $999 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-100k-tradovate` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; intraday trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL none (the intraday evaluation has no DLL); 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $790 at_start, activation $129 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-100k-wealthcharts-5pack` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; intraday trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL none (the intraday evaluation has no DLL); 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $690 at_start, activation $129 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-100k-wealthcharts-no-activation-fee-5pack` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; intraday trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL none (the intraday evaluation has no DLL); 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $890 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-100k-wealthcharts-no-activation-fee` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; intraday trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL none (the intraday evaluation has no DLL); 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $999 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-100k-wealthcharts` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; intraday trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL none (the intraday evaluation has no DLL); 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $790 at_start, activation $129 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-100k` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account

- **Account / thresholds**: $100,000; evaluation target $6,000 on the closed balance; intraday trailing drawdown $3,000 (lock $109,000->$106,000); evaluation DLL none (the intraday evaluation has no DLL); 8 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $3,000 (lock $103,100->$100,100); PA DLL tiers $1,750@>=$100,000 / $1,750@>=$102,000 / $1,750@>=$103,000 / $2,500@>=$105,000 / $3,500@>=$110,000; PA scaling 3c@>$0 / 4c@>$2,000 / 5c@>$3,000 / 6c@>$5,000 / 6c@>$10,000.

- **Payouts**: 5 qualifying days of >= $250 net profit (since the last payout); safety net $3,100 above the starting balance; minimum $500; ladder $2,000 / $2,500 / $3,000 / $3,000 / $4,000 / $4,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $790 at_start, activation $129 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-150k-5pack` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; intraday trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL none (the intraday evaluation has no DLL); 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $990 at_start, activation $149 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-150k-no-activation-fee-5pack` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; intraday trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL none (the intraday evaluation has no DLL); 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,790 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-150k-no-activation-fee` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; intraday trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL none (the intraday evaluation has no DLL); 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,890 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-150k-tradovate-5pack` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; intraday trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL none (the intraday evaluation has no DLL); 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $990 at_start, activation $149 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-150k-tradovate-no-activation-fee-5pack` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; intraday trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL none (the intraday evaluation has no DLL); 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,790 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-150k-tradovate-no-activation-fee` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; intraday trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL none (the intraday evaluation has no DLL); 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,890 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-150k-tradovate` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; intraday trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL none (the intraday evaluation has no DLL); 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,190 at_start, activation $149 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-150k-wealthcharts-5pack` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; intraday trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL none (the intraday evaluation has no DLL); 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $990 at_start, activation $149 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-150k-wealthcharts-no-activation-fee-5pack` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; intraday trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL none (the intraday evaluation has no DLL); 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,790 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-150k-wealthcharts-no-activation-fee` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; intraday trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL none (the intraday evaluation has no DLL); 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,890 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-150k-wealthcharts` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; intraday trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL none (the intraday evaluation has no DLL); 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,190 at_start, activation $149 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-150k` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account

- **Account / thresholds**: $150,000; evaluation target $9,000 on the closed balance; intraday trailing drawdown $4,000 (lock $163,000->$159,000); evaluation DLL none (the intraday evaluation has no DLL); 12 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $4,000 (lock $154,100->$150,100); PA DLL tiers $2,500@>=$150,000 / $2,500@>=$152,000 / $2,500@>=$153,000 / $3,000@>=$155,000 / $4,000@>=$160,000; PA scaling 4c@>$0 / 5c@>$2,000 / 7c@>$3,000 / 10c@>$5,000 / 10c@>$10,000.

- **Payouts**: 5 qualifying days of >= $300 net profit (since the last payout); safety net $4,100 above the starting balance; minimum $500; ladder $2,500 / $3,000 / $3,000 / $4,000 / $4,000 / $5,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $1,190 at_start, activation $149 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-25k-5pack` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; intraday trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL none (the intraday evaluation has no DLL); 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $149.9 at_start, activation $89 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-25k-no-activation-fee-5pack` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; intraday trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL none (the intraday evaluation has no DLL); 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $590 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-25k-no-activation-fee` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; intraday trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL none (the intraday evaluation has no DLL); 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $690 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-25k-tradovate-5pack` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; intraday trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL none (the intraday evaluation has no DLL); 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $149.9 at_start, activation $89 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-25k-tradovate-no-activation-fee-5pack` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; intraday trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL none (the intraday evaluation has no DLL); 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $590 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-25k-tradovate-no-activation-fee` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; intraday trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL none (the intraday evaluation has no DLL); 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $690 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-25k-tradovate` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; intraday trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL none (the intraday evaluation has no DLL); 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $167 at_start, activation $89 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-25k-wealthcharts-5pack` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; intraday trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL none (the intraday evaluation has no DLL); 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $149.9 at_start, activation $89 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-25k-wealthcharts-no-activation-fee-5pack` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; intraday trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL none (the intraday evaluation has no DLL); 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $590 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-25k-wealthcharts-no-activation-fee` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; intraday trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL none (the intraday evaluation has no DLL); 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $690 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-25k-wealthcharts` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; intraday trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL none (the intraday evaluation has no DLL); 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $167 at_start, activation $89 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-25k` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account

- **Account / thresholds**: $25,000; evaluation target $1,500 on the closed balance; intraday trailing drawdown $1,000 (lock $27,500->$26,500); evaluation DLL none (the intraday evaluation has no DLL); 4 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $1,000 (lock $26,100->$25,100); PA DLL tiers $500@>=$25,000 / $500@>=$26,000 / $1,250@>=$27,000; PA scaling 1c@>$0 / 2c@>$1,000 / 2c@>$2,000.

- **Payouts**: 5 qualifying days of >= $100 net profit (since the last payout); safety net $1,100 above the starting balance; minimum $500; ladder $1,000 / $1,000 / $1,000 / $1,000 / $1,000 / $1,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $167 at_start, activation $89 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-50k-5pack` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; intraday trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL none (the intraday evaluation has no DLL); 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $200 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $190 at_start, activation $99 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-50k-no-activation-fee-5pack` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; intraday trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL none (the intraday evaluation has no DLL); 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $200 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $690 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-50k-no-activation-fee` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; intraday trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL none (the intraday evaluation has no DLL); 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $200 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $799 at_start; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-50k-tradovate-5pack` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; intraday trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL none (the intraday evaluation has no DLL); 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $200 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $190 at_start, activation $99 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-50k-tradovate-no-activation-fee-5pack` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; intraday trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL none (the intraday evaluation has no DLL); 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $200 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $690 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-50k-tradovate-no-activation-fee` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; intraday trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL none (the intraday evaluation has no DLL); 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $200 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $799 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-50k-tradovate` — Intraday Trailing Drawdown Evaluation (Tradovate) -> Intraday Performance Account

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; intraday trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL none (the intraday evaluation has no DLL); 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $200 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $249 at_start, activation $99 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (Tradovate); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-50k-wealthcharts-5pack` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; intraday trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL none (the intraday evaluation has no DLL); 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $200 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $190 at_start, activation $99 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-50k-wealthcharts-no-activation-fee-5pack` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account - 5-pack (per-account cost)

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; intraday trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL none (the intraday evaluation has no DLL); 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $200 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $690 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 7 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-50k-wealthcharts-no-activation-fee` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; intraday trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL none (the intraday evaluation has no DLL); 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $200 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $799 at_start; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 6 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-50k-wealthcharts` — Intraday Trailing Drawdown Evaluation (WealthCharts) -> Intraday Performance Account

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; intraday trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL none (the intraday evaluation has no DLL); 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $200 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $249 at_start, activation $99 at_pass; commissions per side ES 1.55, NQ 1.55, YM 1.55, RTY 1.55, NKD 2.32, MES 0.52, MNQ 0.52, MYM 0.52, M2K 0.52 (WealthCharts); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

### `apex-intraday-50k` — Intraday Trailing Drawdown Evaluation (Rithmic) -> Intraday Performance Account

- **Account / thresholds**: $50,000; evaluation target $3,000 on the closed balance; intraday trailing drawdown $2,000 (lock $55,000->$53,000); evaluation DLL none (the intraday evaluation has no DLL); 6 contracts; flat 1 minute before the scheduled session end (16:59 ET on a regular session), consequence fail; access 30 calendar days; PA intraday trailing drawdown $2,000 (lock $52,100->$50,100); PA DLL tiers $1,000@>=$50,000 / $1,000@>=$51,500 / $2,000@>=$53,000 / $3,000@>=$56,000; PA scaling 2c@>$0 / 3c@>$1,500 / 4c@>$3,000 / 4c@>$6,000.

- **Payouts**: 5 qualifying days of >= $200 net profit (since the last payout); safety net $2,100 above the starting balance; minimum $500; ladder $1,500 / $2,000 / $2,500 / $2,500 / $3,000 / $3,000; at most 6; split 1.0; 50% consistency since the last payout; the threshold after a payout is unchanged.

- **Fees / commissions**: evaluation $249 at_start, activation $99 at_pass; commissions per side ES 1.99, NQ 1.99, YM 1.99, RTY 1.99, NKD 1.99, MES 0.51, MNQ 0.51, MYM 0.51, M2K 0.51 (Rithmic); every component `unknown` (no page says, so the cost statistics stay unavailable).

- **News / compliance**: no news window modeled (discretionary rule, section 5); automation ban critical -> `blocked_by_compliance` for automated execution; trade copying and high-risk strategies material

- **Activity**: at least 2 days of >=$50 net profit in every rolling 30 calendar days, tested at each rule-day close once the window is full; a window short of its days closes the account (`close_account`) before the pass conditions are tested, so the payout eligibility is forfeited.

- **Assumptions**: `intraday_evaluation_lock_taken_from_auto_liq_min_max`, `intraday_pa_lock_taken_from_pa_auto_liq_min_max`

- **Conflicts**: `evaluation_consistency`: max_day_share = 0.3 (alternative the rule does not exist (`absent`))

- **Coverage**: 5 `not_modeled` entries (3 material), evaluation status `conditional_on_modeled_rules`, estimate status `unavailable` and cash statistics `unavailable`: the commission does not declare whether it includes the exchange and regulatory fees, so no cost is assumed; unverified.

## 13. Open questions for the owner

### Per-component costs (C7b fix, 2026-11-22)

`commissions.includes_exchange_and_regulatory_fees` is gone. The ruleset now declares, for each of the four components, whether the firm's per-side commission CONTAINS it (`included`), EXCLUDES it (`excluded`, so the run adds the dataset's amount for its participant type) or does not say (`unknown`, which is never a zero cost). All four keys are required, and no component may be inferred from another firm's page, another product or another participant type (ADR-0107 section 10 as amended).

| Component | Status in the files | Evidence kind | Evidence |
|---|---|---|---|
| `exchange` | `unknown` | `not_stated` | the commission table does not say whether exchange, clearing, NFA or other fees are included |
| `clearing` | `unknown` | `not_stated` | the same: the table itemizes no component at all |
| `nfa` | `unknown` | `not_stated` | the same: the page states no NFA assessment |
| `other` | `unknown` | `not_stated` | the same: no other per-side charge is named |

An `excluded` component needs a participant type at RUN time (`--fee-participant-type`): the ruleset never states one, and using it makes the cost `conditional`. An `unknown` component is a gap, and the only way to a number is a cost-assumption FILE the user passes, which prices exactly the root and component it names and is recorded by its SHA-256. The unverified owner reference in `docs/data/cme-exchange-fees.md` ("Estimated fee per side") is documentation only: the engine never reads it.

Owner questions, one per component the files declare `unknown`:

1. **exchange**: Does the per-side commission already contain the exchange fee, or is the exchange fee charged on top of it?
2. **clearing**: Does the per-side commission already contain the clearing fee, or is the clearing fee charged on top of it?
3. **nfa**: Does the per-side commission already contain the NFA assessment, or is it charged on top of it?
4. **other**: Is there any other per-side charge beside the commission, the exchange fee, the clearing fee and the NFA assessment?


1. **Do the commissions include the exchange and regulatory fees?** This is now
   the one fact that gates every Apex cost statistic: no page says whether the
   per-side amount is all-in, so every file declares `unknown` and its cost
   statistics are `unavailable` (section 4.3). One owner sentence (or the firm's
   clearing agreement) turns them on; reading the table as all-in would be a guess,
   and reading it as ex-fees would be a second guess.
2. **The evaluation consistency conflict (section 7.1) is the other one to settle.**
   These files apply the store's 30% to every evaluation, because that is the more
   restrictive reading of an official contradiction. If you read the rendered table
   as authoritative, the primary should drop the rule (`value: absent`) and the store
   value should become the sensitivity scenario - one field per file.
3. **Are automated strategies eligible at all?** The compliance rule is `critical`
   because Apex bans automation outright, so every Apex number is
   `blocked_by_compliance` for `execution_mode: automated`. You have ruled that the
   ban stays `critical`; it is kept here as the settled position, not a question.
4. **Platform variants are complete.** Rithmic, Tradovate and WealthCharts each head
   every product, size, pack and fee variant the catalogue sells (section 4.1), each
   with its own platform field and its own commission source. The only undrafted
   family is Legacy (sold before 2026-03-01), whose rules are documented on
   `/legacy-products/` and snapshotted.
5. **`pa_inactivity_closure` is now modeled** (round 2): the funded phase carries an
   `activity_requirement` (2 days of >= $50 in every rolling 30 calendar days,
   `action: close_account`). Confirm the action: an inactivity closure forfeits the
   payout eligibility, so the engine ends the account rather than only blocking a
   payout.
6. **`max_eval_daily_profit_percent`**: if that store field is a separate daily
   profit cap rather than the same 30% consistency, it needs a `daily_profit_cap`
   rule and the `evaluation_daily_profit_percent_field` entry must be replaced by it.
7. **No Apex page states a 2% price-limit restriction**, so the owner's standing
   entry is absent here; if the intent was to carry it for every firm anyway, it
   should be added with a source.

## 14. Reproduction and self-check

```bash
cd /d/proyectos/crucible-notes/internal/prop_snapshots
uv run --project D:/proyectos/crucible/.claude/worktrees/fathom-c7b-firm-rulesets python generate_v2_apex.py
uv run --project D:/proyectos/crucible/.claude/worktrees/fathom-c7b-firm-rulesets python write_apex_research.py
uv run --project D:/proyectos/crucible/.claude/worktrees/fathom-c7b-firm-rulesets python check_v2_apex.py
uv run --project D:/proyectos/crucible/.claude/worktrees/fathom-c7b-firm-rulesets python check_quotes2.py '<worktree>/rulesets/prop/apex/*.yaml'
cd /d/proyectos/crucible/.claude/worktrees/fathom-c7b-firm-rulesets
for f in rulesets/prop/apex/*.v1.yaml; do uv run crucible prop validate "$f" --json >/dev/null || echo "FAIL $f"; done
uv run crucible prop list --firm apex --json >/dev/null
```

`python fetch.py apex <short_name> <url>` re-fetches a page (full browser headers); a
re-fetch is a **new** snapshot with a new hash, never a rewrite of the old bytes.
