# FundedNext Futures - ruleset research (fifteen rulesets, schema version 2)

- Firm slug: `fundednext`; files `rulesets/prop/fundednext/*.v1.yaml`, version 1 each, **schema
  version 2** (ADR-0107 sections 7-13). Migration of the v1 drafts, rewritten in place because they
  were never committed.
- Retrieval: 2026-11-22 (UTC), official FundedNext pages only; no login, form or purchase. Raw
  snapshots and their sha256 live in `D:/proyectos/crucible-notes/internal/prop_snapshots/fundednext/`.
- `verification.status: unverified` on every file. Only the owner can confirm a ruleset (ADR-0106)
  and confirmation lives in a `<file>.verification.yaml` sidecar that this migration did not write.
- Every rule declares `evidence`: `official_quote` (a verbatim quote from an official page),
  `conflict_resolution` (a genuine contradiction resolved to the more restrictive value) or
  `assumption` (a named ADR-0107 section 7 default applied where the firm is silent). No rule in
  these files is `owner_provided`.
- Quote normalisation: UTF-8 decode, unescape unicode-escaped tags, drop
  `<script>/<style>/<noscript>/<svg>`, replace each tag with one space, unescape HTML entities,
  collapse whitespace. The page's own spaces before punctuation and its invisible directional
  isolates (U+2066/U+2069) are kept verbatim. A self-check re-reads every quote against its snapshot
  after unescaping and whitespace normalisation: 411 attributions, 411 hashes match, 0 quotes
  missing (69 found in the raw bytes, 342 after tag stripping of a table row or list item). The
  count fell from 417 because nine `not_modeled` entries were lifted out of the files by the
  round-2 vocabulary and three rules were added (section 5b).

## 1. Does FundedNext offer a futures program?

Yes - CME futures, on four exchanges, in both the Challenge and the FundedNext phase.

#### `fundednext_offers_futures`
- url: https://fundednext.com/general-rules/futures/symbols-and-conditions
- snapshot: `20261122_fn_rules_symbols.html`
- sha256: `bba18431ac110c2fa1e2ee875d88b9c8d43a9aaf9443a3ad63bc4c15315c13c5`
- retrieved_at: `2026-11-22T01:39:33Z`
- quote: "Trade futures contracts across six product categories on four major exchanges."

## 2. Products sold, and what was drafted

| product | sizes | variants drafted | files |
|---|---|---|---|
| Flex | 50K, 100K, 150K | none (no add-ons offered on Flex) | 3 |
| Rapid Pro | 25K, 50K, 100K | base, and with the optional Daily Loss Limit Add-On (adds a soft DLL in both phases and a lower price) | 6 |
| Rapid Daily | 25K, 50K, 100K | none ("The Rapid Daily path does not include any Add-Ons") | 3 |
| Direct | 50K, 100K, 150K | none (no Challenge phase; funded-only) | 3 |
| Legacy | 25K, 50K, 100K | **not drafted** - see below | 0 |

All fifteen files use the same platforms (Tradovate, NinjaTrader, TradingView) and the same
instruments (ES, NQ, MES, MNQ - the four equity-index roots the firm names), so platform and
instrument variants do not exist. The only rule-changing variant is the Rapid Pro DLL add-on.

**Legacy is NOT drafted.** The purchase chooser offers three models only ("Three different
Challenges"), `https://fundednext.com/futures/legacy` serves the same generic futures page as
`/futures` (byte-identical content: no Legacy card, no Legacy price), and the account-prices
article has pricing sections for Direct, Rapid and Flex but none for Legacy. Legacy documents
remain in the help centre and its values still appear in the general-rules tables (MLL, Benchmark
Days), so it may still serve existing owners. **No official page states a discontinuation date**, so
none is recorded; the values seen for it ($25K/$50K/$100K, target $1,250/$3,000/$6,000, MLL
$1,000/$2,000/$3,000) were read but not drafted. The general loss-limit article also distinguishes
Legacy from Flex/Rapid/Direct on the MLL lock point ("for Flex, Rapid Pro & Daily, and Direct
Account it locks at initial balance + $100"), which is the only place Legacy's different lock level
matters.

## 3. Product matrix (generated from the YAML)

| file | size | addons | target | MLL eval/funded | lock eval/funded (triggers) | DLL eval/funded | contracts eval/funded | consistency eval/funded | payout: split / cap / min / buffer / count / after | payout gates | fee | reset fee | inactivity (calendar days) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `fundednext-futures-direct-100k` | 100K | - | - | -/3500 | -/3600 -> 100 + 1st payout | -/2000 | -/6 | -/0.20 | 0.90 / 2000 / min 1500 / buffer 3600 / max 5 / lock_on_first_payout |  | 584.99 | - | -/7 ca |
| `fundednext-futures-direct-150k` | 150K | - | - | -/5000 | -/5100 -> 100 + 1st payout | -/3000 | -/8 | -/0.20 | 0.90 / 2500 / min 2000 / buffer 5100 / max 5 / lock_on_first_payout |  | 754.99 | - | -/7 ca |
| `fundednext-futures-direct-50k` | 50K | - | - | -/2000 | -/2100 -> 100 + 1st payout | -/1000 | -/3 | -/0.20 | 0.90 / 1200 / min 800 / buffer 2100 / max 5 / lock_on_first_payout |  | 284.99 | - | -/7 ca |
| `fundednext-futures-flex-100k` | 100K | - | 5000 | 2500/2500 | 2600 -> 100/2600 -> 100 + 1st payout | -/- | 5/5 | 0.4/- | 0.95 / 2500 / min 250 / buffer 0 / max 5 / lock_on_first_payout | min_profitable_days=5, min_day_profit_usd=200, min_profit_since_last_usd=500, max_share_of_withdrawable=0.5 | 273.99 | 157.99 | 30 ca/30 ca |
| `fundednext-futures-flex-150k` | 150K | - | 8000 | 4000/4000 | 4100 -> 100/4100 -> 100 + 1st payout | -/- | 8/8 | 0.4/- | 0.95 / 4000 / min 250 / buffer 0 / max 5 / lock_on_first_payout | min_profitable_days=5, min_day_profit_usd=250, min_profit_since_last_usd=500, max_share_of_withdrawable=0.5 | 490.99 | 284.99 | 30 ca/30 ca |
| `fundednext-futures-flex-50k` | 50K | - | 2500 | 1500/1500 | 1600 -> 100/1600 -> 100 + 1st payout | -/- | 3/3 | 0.4/- | 0.95 / 1500 / min 250 / buffer 0 / max 5 / lock_on_first_payout | min_profitable_days=5, min_day_profit_usd=200, min_profit_since_last_usd=500, max_share_of_withdrawable=0.5 | 141.99 | 82.99 | 30 ca/30 ca |
| `fundednext-futures-rapiddaily-100k` | 100K | - | 5000 | 2500/2500 | 2600 -> 100/2600 -> 100 | 1250/1250 | 6/6 | -/- | 0.90 / 2000 (2000/2500) / min 250 / buffer 2600 / max 5 / unchanged | min_profit_since_last_usd=500 | 483.99 | 287.99 | 30 ca/30 ca |
| `fundednext-futures-rapiddaily-25k` | 25K | - | 1500 | 1000/1000 | 1100 -> 100/1100 -> 100 | 500/500 | 2/2 | -/- | 0.90 / 600 (600/850) / min 250 / buffer 1100 / max 5 / unchanged | min_profit_since_last_usd=500 | 125.99 | 72.99 | 30 ca/30 ca |
| `fundednext-futures-rapiddaily-50k` | 50K | - | 3000 | 2000/2000 | 2100 -> 100/2100 -> 100 | 1000/1000 | 4/4 | -/- | 0.90 / 1000 (1000/1250) / min 250 / buffer 2100 / max 5 / unchanged | min_profit_since_last_usd=500 | 299.99 | 177.99 | 30 ca/30 ca |
| `fundednext-futures-rapidpro-100k-dlladdon` | 100K | daily_loss_limit | 5000 | 2500/2500 | 2600 -> 100/2600 -> 100 | 1250/1250 | 6/6 | -/0.4 | 0.90 / 2000 (2000/2500) / min 250 / buffer 0 / max 5 / unchanged | min_days_since_last=3, min_profit_since_last_usd=500 | 433.99 | 237.99 | 30 ca/30 ca |
| `fundednext-futures-rapidpro-100k` | 100K | - | 5000 | 2500/2500 | 2600 -> 100/2600 -> 100 | -/- | 6/6 | -/0.4 | 0.90 / 2000 (2000/2500) / min 250 / buffer 0 / max 5 / unchanged | min_days_since_last=3, min_profit_since_last_usd=500 | 483.99 | 287.99 | 30 ca/30 ca |
| `fundednext-futures-rapidpro-25k-dlladdon` | 25K | daily_loss_limit | 1500 | 1000/1000 | 1100 -> 100/1100 -> 100 | 500/500 | 2/2 | -/0.4 | 0.90 / 600 (600/850) / min 250 / buffer 0 / max 5 / unchanged | min_days_since_last=3, min_profit_since_last_usd=500 | 105.99 | 52.99 | 30 ca/30 ca |
| `fundednext-futures-rapidpro-25k` | 25K | - | 1500 | 1000/1000 | 1100 -> 100/1100 -> 100 | -/- | 2/2 | -/0.4 | 0.90 / 600 (600/850) / min 250 / buffer 0 / max 5 / unchanged | min_days_since_last=3, min_profit_since_last_usd=500 | 125.99 | 72.99 | 30 ca/30 ca |
| `fundednext-futures-rapidpro-50k-dlladdon` | 50K | daily_loss_limit | 3000 | 2000/2000 | 2100 -> 100/2100 -> 100 | 1000/1000 | 4/4 | -/0.4 | 0.90 / 1000 (1000/1250) / min 250 / buffer 0 / max 5 / unchanged | min_days_since_last=3, min_profit_since_last_usd=500 | 259.99 | 132.99 | 30 ca/30 ca |
| `fundednext-futures-rapidpro-50k` | 50K | - | 3000 | 2000/2000 | 2100 -> 100/2100 -> 100 | -/- | 4/4 | -/0.4 | 0.90 / 1000 (1000/1250) / min 250 / buffer 0 / max 5 / unchanged | min_days_since_last=3, min_profit_since_last_usd=500 | 299.99 | 172.99 | 30 ca/30 ca |

Column notes: "eval" is the Challenge phase (Direct has none, so its eval cells are `-`); "MLL eval/funded" is the Maximum Loss Limit amount; the lock cell shows the trailing trigger offset and the locked offset in USD above the starting balance, and "+ 1st payout" marks a second trigger that fires the same lock on the first withdrawal (Flex funded, Direct); `payout: split / cap / min / buffer / count / after` shows the reward share, the first cap (and the from-4th-reward cap for Rapid Pro and Rapid Daily), the minimum withdrawal, the buffer above it, the reward count and `threshold_after_payout`. "reset fee" is empty for Direct because a Direct account cannot be reset.

## 4. What the v2 migration changed

Every value below is either unchanged from the v1 draft (re-quoted from the same snapshot) or read
fresh from an official page. Nothing was inferred.

**New in every file:**

- `schema_version: 2`, a top-level `reset` clock (`17:00:00 America/Chicago`, quoted in
  section 10)
  and `commissions` (section 5).
- `evidence` on every rule, `assumption` where a default was applied, `conflicts` where the pages
  contradict themselves.
- `comparison` and `action` on every rule (the v2 vocabulary replaced the v1 `severity`,
  `consequence` and `on_excess` fields), `hwm_basis` on every trailing drawdown and
  `lock.on: [hwm]` on every lock (a list, per round 2; Flex funded and Direct add `first_payout`).
- `evaluated: eod` on every Challenge profit target with the assumption
  `unspecified_target_frequency_is_eod`: the pages state the target's basis but not when it is
  tested, and the ADR-0107 section 7 intraday default is for **failure thresholds** only (it makes
  enforcement stricter). For a pass condition the conservative reading is the end of the trade date
  on the closed balance, so the trader passes no earlier than the close and a later same-day breach
  still counts. A target is never treated as intraday unless the firm states it.
- `inactivity`: 30 consecutive calendar days for the Challenge and FundedNext accounts, 7 for
  Direct. This replaced a v1 `not_modeled` entry.
- `compliance` rules for copy/group trading and account sharing (section 7).
- `challenge_reset_fee` (`fee_kind: reset`, `when: on_reset`) in every plan that can be reset. This
  replaced a v1 `not_modeled` entry; Direct cannot be reset, so it carries no reset fee.

**New by plan:**

- Flex (challenge): `consistency` (`max_day_share: 0.4`, `applies_to: pass`). The firm raises the
  required profit to highest day / 40% instead of failing the account, and that is arithmetically
  the same test as "profit >= target AND best day <= 40% of total profit", so the v1 `not_modeled`
  entry is removed.
- Flex (funded): `max_share_of_withdrawable: 0.5`, `min_profit_since_last_usd: 500`,
  `threshold_after_payout: lock_on_first_payout`, `window: since_last_payout`.
- Rapid Pro / Rapid Daily (funded): `min_profit_since_last_usd: 500`,
  `max_usd_by_payout` (the cap rises from the 4th reward: 600 -> 850, 1,000 -> 1,250,
  2,000 -> 2,500), `window: since_last_payout`.
- Direct (funded): `max_payouts: 5` (the page states the account concludes after the 5th reward; the
  v1 draft had `null`), `threshold_after_payout: lock_on_first_payout`.
- Rapid Pro (funded): `consistency` stays a payout gate, now with an explicit
  `window: since_last_payout`.

**`not_modeled` entries removed because the vocabulary now models them exactly:** the Flex 40%
consistency rule that raises the target, the 50% withdrawable cap, the $500 cycle-profit floor, the
reset fee, inactivity closure, the escalating payout cap, and (Flex and Direct) the first-withdrawal
MLL reset, which is declared on the payout rule as `threshold_after_payout: lock_on_first_payout`.
That last one kept a `not_modeled` entry through the v2 pass because the engine could not yet act on
the declaration; the round-2 `lock.on: [hwm, first_payout]` removed the entry (section 5b).

**Unchanged values worth re-stating:** the MLL lock is modelled at the lock point as a level (floor
= initial + $100, reached when the end-of-day balance reaches initial + limit + $100), which is the
more restrictive of the two readings the firm publishes; the other reading is a sensitivity scenario
in every Flex/Rapid Pro/Rapid Daily file (see the conflicts below). The trailing high-water mark is
marked on the **end-of-day balance** (`hwm_basis: balance`), not on equity: the pages say the MLL
"updates once per day based on your highest balance that day". The tested basis is equity
(`basis: equity`, `evaluated: intraday`), because "a floating loss that hits the MLL during a live
trade breaches your account instantly".

## 5. Commissions

The firm's own commission article (`20261122_fn_a_commissions.html`, sha256
`d3243eb03af444670f9475e44d99c4c3ef36dd85cbca4be7cfdd30c3cca71a02`) defines the all-in rate and
gives one worked example:

> "You place a Buy trade of 3 contracts on the E-mini Nasdaq-100 (NQ), where the all-in rate is
> $2.88 per contract: 3 contracts x $2.88 x 2 = $17.28 So your total commission for opening and
> closing this trade would be $17.28 ."

- That is **NQ at 2.88 USD per contract per side**, charged on entry and exit (the article's
  "round-turn" is `number of contracts x all-in rate x 2`). The rate is an all-in rate: broker
  commission, exchange and NFA fees and clearing fees together, which is what the ruleset's
  `per_side_usd` replaces (the attempt zeroes the run's exchange, clearing and regulatory fees when
  the ruleset's commission is used).
- **Every other root is unpublished.** The article sends the reader to each platform's pricing page
  ("simply search for the instrument to view its associated Commission/Fees. For example,
  NinjaTrader's rates are available on the NinjaTrader Commissions page .") and no FundedNext page
  carries a per-root or per-platform table: ES, MES and MNQ have no known commission in these files.
- Consequence, and the reason `not_modeled` keeps a material entry
  (`commission_table_not_published_per_root`): a run on an unpublished root has **no known
  commission**, so its cost-dependent statistics are `unavailable` unless an explicit, named cost
  assumption is passed. A commission is never treated as zero. The NQ figure is declared at ruleset
  level, so an attempt on NQ uses it and an attempt on ES does not inherit it.
- `commissions.platform` is `null`: the article is not platform-specific and each file's `platform`
  field names three platforms, which a single per-side table cannot separate. Reading the
  Tradovate/NinjaTrader/TradingView pricing pages per platform is an open owner decision
  (section 9, item 2), not a value guessed here.
- **`includes_exchange_and_regulatory_fees: true`** (round 2, `Commissions` now REQUIRES the field).
  The article's own definition is the evidence: the all-in rate "includes the broker commission,
  exchange & NFA fees, and the clearing fee", the three components it then lists. So the 2.88 USD
  per side is a complete per-side cost: an attempt charges the ruleset's commission and adds no
  `ExchangeFeeSource`, and the cost statistics are `exact` on NQ (still `unavailable` on a root
  with no published rate). The `commissions.source` attribution's quote is the "What makes up the
  all-in rate?" passage read through the worked NQ example, so one verbatim quote carries both the
  flag and the amount; the section label is that passage's heading.

## 5b. Round 2 changes (the second C7b pass)

The round-2 vocabulary (ADR-0107 sections 7-13) made three declarations REQUIRED and added nine
generic fields. This pass updated all fifteen files: `uv run crucible prop validate <file> --json`
passes on every one of them, the quote/hash self-check re-reads 411 attributions with 0 missing, and
the conflict scenarios still build (each alternative is applied as the rule's whole `lock`
field and the switched ruleset re-validates).

**Now required, added or fixed in every file:**

- `commissions.includes_exchange_and_regulatory_fees: true` (section 5), sourced from the article's
  own definition of the all-in rate.
- `lock.on` is a LIST (`on: [hwm]`); the schema refuses a bare `on: hwm`. Every conflict's
  `selected_value` and every alternative `value` were rewritten the same way, because a scenario
  applies the alternative as the rule's whole `lock` field and then re-validates the ruleset.
- `news_restriction.effect` (`block|contract_cap`) is required only WHERE a news rule exists. None
  exists here (section 6), so no file carries one.

**Round-2 fields used, and the `not_modeled` entries they lift (9 entries, 6 files):**

- `lock.on: [hwm, first_payout]` (Flex funded, Direct): the first withdrawal locks the MLL at the
  lock point (initial balance + $100) even when the trailing level had not reached it. That statement
  is now the trailing rule's second trigger, so a withdrawal before the account reaches the lock
  point freezes the floor at the firm's level instead of leaving it below.
  `max_loss_limit_reset_after_first_withdrawal` (material; the three Flex files and the three
  Direct files) is removed because the effect is enforced, not merely declared. The funded lock-point
  conflict's selected value and its alternative both carry the two triggers, so the sensitivity
  scenario still differs from the primary in the lock LEVEL only, never in what fires it. The
  Challenge phase keeps `on: [hwm]`: no withdrawal happens there.
- `consistency.numerator_window` / `denominator_window` (Direct): the Perpetual Consistency Rule
  compares the all-time best day with the CURRENT cycle's profit, so it is declared as
  `max_day_share: 0.2`, `applies_to: payout`, `numerator_window: all_time`, `denominator_window:
  current_cycle`, `action: block_payout`. `direct_perpetual_consistency_20pct` (material; the three
  Direct files) is removed. The engine measures the cycle from the balance the cycle opened at and
  re-anchors that balance after every withdrawal, which is the "best day carries forward" mechanism
  the page describes.
- `payout.threshold_after_payout: lock_on_first_payout` was already declared on Flex and Direct and
  is now ENFORCED by the lock trigger above (it was a declared-but-inert value in the v2 pass).
  `set_threshold` / `set_threshold_to` is deliberately NOT used: the level the firm names (initial +
  $100) is exactly the lock the trailing rule already declares, so a second declaration in the payout
  rule would duplicate the same level instead of adding a source.

**Round-2 vocabulary that did not fit, and the source that rules it out (nothing was invented):**

- `payout.max_usd: unknown` - unused. Every plan states its cap (600/850, 1,000/1,250, 2,000/2,500
  for Rapid Pro and Rapid Daily; Flex 1,500/2,500/4,000 with `max_share_of_withdrawable: 0.5`; Direct
  1,200/2,000/2,500), and no file declares `unlimited`, so no payout or cash statistic is an upper
  bound.
- `payout.min_new_profit_share_of_request` - unused. No page states that a share of a request must be
  new profit; the cycle floors are absolute amounts (`min_profit_since_last_usd: 500`).
- `news_restriction`, including `effect: contract_cap` and the event types the calendar now carries
  (`PPI`, `FOMC_PRESS_CONFERENCE`, `FOMC_MINUTES`) - unused. News trading is allowed with no timing
  or event-type restriction (section 6), so there is no window to declare and no calendar
  dependency in these files.
- `activity_requirement` - unused. The only gap rule is `inactivity` (30 calendar days, 7 for
  Direct). Flex's "at least 5 Benchmark Days before every withdrawal" is a per-cycle count on the
  payout rule (`min_profitable_days: 5`, `min_day_profit_usd`), and Direct's "at least one trade per
  week (Monday through Friday)" is a calendar-week statement, not a rolling window: the round-2 rule
  tests EVERY rolling window of M days, which is stricter than the firm states (open question 6).
- a conflict alternative of `absent` - unused. No second official page says a declared rule does not
  exist; the near-candidates were checked and are consistent rather than contradictory. The Rapid
  Daily DLL that "applies by default" (plan pages) is also stated by the customer agreement
  (Futures Challenge Terms 1.2.10), the Rapid Pro DLL exists only with the add-on (terms 1.2.5) and
  the base files carry none, and Direct is named as the 7-calendar-day inactivity exception on the
  inactivity article itself.
- a session-relative `flat_by` (`minutes_before_session_end`) - unused. The firm states a fixed
  clock ("Any open positions at 3:10 PM CT are closed automatically by the system"), not an offset
  from the scheduled session end, and no page states a holiday or early-close behaviour. A
  session-relative reading would be the engine's inference, so `time: 15:10:00` with
  `tz: America/Chicago` stays. No file carried a `holiday_early_close` entry to drop.

## 6. News rules

**There is no news-trading restriction on any FundedNext Futures plan, and none is declared.**

#### `news_trading_unrestricted`
- url: https://fundednext.com/general-rules/futures/what-is-allowed
- snapshot: `20261122_fn_rules_allowed.html`
- sha256: `3653ad4821f3a66bc14e8c1635e31e20b6e65586f552a1769e7ffbd1b68292be`
- section: 1 News Trading
- quote: "News trading is allowed across all account models with no restrictions on timing or news
  event type. No restrictions. Open, close, or hold positions through any scheduled or unscheduled
  news event, including NFP, CPI, FOMC, GDP releases, and geopolitical events."

The plan pages agree: the Flex rules table lists "News Trading: Allowed" and the Rapid page lists
"News Trading: Allowed Allowed" for both paths. So the event types the page names (NFP, CPI, FOMC,
GDP, geopolitical) need no `news_restriction`, there is no pre/post window, no restricted
instrument, no flatten behaviour and no calendar coverage gap: the rule is that nothing is blocked.
A `news_restriction` rule with an empty window would misrepresent that, and a `not_modeled` entry
would suggest something is unmodeled, so the absence is the model. The economic-event calendar is
therefore not needed for FundedNext attempts.

## 7. Compliance and conduct

`crucible.prop.attempt.practical_eligibility` reports `blocked_by_compliance` only when a **critical**
compliance rule applies to the attempt's execution mode, so the materiality below is load-bearing.

**Nothing here blocks an automated strategy.** The firm allows it explicitly:

#### `automated_trading_allowed`
- url: https://fundednext.com/general-rules/futures/what-is-allowed
- section: 2 Automated Systems (EAs and Bots)
- quote: "EAs and bots are allowed on both the Challenge and FundedNext Account. Use automated
  strategies through any platform integration that connects to Tradovate. Setup, configuration, and
  troubleshooting are not supported by FundedNext."

That quote is the reason no automation `compliance` rule exists on any of these files. It is the
opposite of Apex's ban, and a reviewer coming from the Apex rulesets should expect no blocker here.

Every file declares two `compliance` rules in **each phase** (the forbidden-strategies page says
"Applies in both Challenge and FundedNext Account Phases"):

| rule | restriction | materiality | why this materiality |
|---|---|---|---|
| `*_compliance_copy_and_group_trading` | `copy_and_group_trading` | material | the stated exception is copying between accounts all registered to the trader; a single simulated account cannot use it, and a strategy that copies a third party is not eligible. Not critical, because a non-copying strategy (the normal case) is unaffected |
| `*_compliance_account_sharing` | `account_sharing` | immaterial | a mechanical single-account attempt cannot let someone else trade or trade someone else's account; recorded so the published surface is complete |

Conduct clauses that are **not** expressible as a compliance rule (a single simulated account cannot
be screened for them) stay `not_modeled` with materiality: sub-minute holding and micro-scalping,
cross-account and correlated hedging, the 2% price-limit entry ban and the remaining qualitative
prohibited-strategy families (section 8). None of them is `critical`, so an attempt stays `eligible`
in `practical_eligibility` and the coverage says `conditional_on_modeled_rules` instead: the report
must not read as "practically valid" for a strategy that grids, scalps sub-minute or hedges.

## 8. `not_modeled` by materiality (all fifteen files)

**MATERIAL** (each of these can change a mechanical outcome or a payout decision, so a report that carries it is `conditional` at best):

- `cme_price_limit_2pct_entry_ban` (all fifteen files): No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here.
  - source, quoted per file from that plan's own page: <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies
- `commission_table_not_published_per_root` (all fifteen files): The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied.
  - source, quoted per file from that plan's own page: <https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?
- `cross_account_hedging` (all fifteen files): Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it.
  - source, quoted per file from that plan's own page: <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies
- `prohibited_strategy_clauses` (all fifteen files): Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible.
  - source, quoted per file from that plan's own page: <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies
- `sub_minute_holding_and_micro_scalping` (all fifteen files): Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise.
  - source, quoted per file from that plan's own page: <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What is the Micro-Scalping policy for the FundedNext Futures Direct Account?

**IMMATERIAL** (recorded for completeness; the modelled result is not measurably different):

- `excess_contract_penalty` (all fifteen files): Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely.
  - source, quoted per file from that plan's own page: <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §Contract limits
- `reward_request_same_day_trade_rule` (all fifteen files): A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow.
  - source, quoted per file from that plan's own page: <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §How do I request my Performance Reward from the FundedNext Futures Direct Account?

## 9. Open questions for the owner

1. **The first-withdrawal MLL reset is now enforced (Flex, Direct).** The trailing rule declares
   `lock.on: [hwm, first_payout]`, so the first withdrawal freezes the floor at the lock point
   (initial + $100) whether or not the high-water mark had reached it; the payout rule's
   `threshold_after_payout: lock_on_first_payout` names the same event. Confirm two things: that the
   reset applies to the withdrawal taken FIRST even when it happens before the MLL ever locked, and
   that LATER withdrawals do not move the floor again (the lock fires once, on the first payout).
2. **Commission table per platform.** Only NQ has a published all-in rate (2.88 USD per side, an
   example). The other roots and the per-platform differences (Tradovate vs NinjaTrader vs
   TradingView) are not on any FundedNext page. Decision needed: read the three platform pricing
   pages and split each ruleset per platform (which changes the ruleset id), or keep `status: known`
   with NQ only and accept `commissions unknown` on ES/MES/MNQ.
3. **The MLL lock reading.** Every Flex/Rapid Pro/Rapid Daily file resolves the contradiction
   between "MLL Locks At $50,100" (a table of levels) and "locks once your BALANCE reaches the lock
   point" (the same page's note) in favour of the level reading, the more restrictive one. The note's
   reading is kept as a sensitivity scenario, `mll_lock_point_<phase>#0`, and is simulated beside
   the primary. Confirm the level reading.
4. **Rapid Pro's 3-day reward cadence unit.** The article says rewards "can be withdrawn every 3
   days" without naming the unit; `payout.min_days_since_last` counts trading days, so the model
   requires 3 trading days since the previous withdrawal. Confirm, or switch to calendar days with
   an engine change.
5. **Rapid Pro's consistency window.** The funded 40% rule compares "your highest profit in a single
   day" with "your total profit" without saying whether the total is all-time or the current cycle.
   `window: since_last_payout` is the more restrictive reading and is declared; `all_time` is the
   alternative.
6. **Direct's inactivity window.** The inactivity article gives 7 consecutive calendar days for
   Direct; the Direct page says "at least one trade per week (Monday through Friday)" and "if you
   don't place any trade during a trading week, your account will be breached". The article's number
   is modelled (7 `calendar_days`, `observed: eod`); the trading-week phrasing would be 5
   `trading_days`. Both are official; the article is the operative count.
7. **Direct has no cycle-profit floor.** Its eligibility table lists only the buffer, the perpetual
   consistency rule, the min/max withdrawal and the 90% share, so `min_profit_since_last_usd: 0` and
   `min_days_since_last: 0`. Confirm the absence rather than a missing number.
8. **Whether a Challenge pass requires a flat book.** Not stated on any page; `require_flat: false`
   with `basis: balance` (the target is defined on closed-position P&L). The rule is
   `evidence: assumption` because the pages are silent on when the target is tested: a pass
   condition is evaluated at the end of the trade date on the closed balance
   (`unspecified_target_frequency_is_eod`), the conservative reading, since the trader then passes
   no earlier than the close and a later same-day breach still counts. The intraday default applies
   to failure thresholds only.
9. **Legacy.** Still in the help centre, still in the general tables, absent from the purchase
   chooser and undated. Draft it, or record a discontinuation date, if the firm publishes one.
10. **Discount prices.** Every fee is the current list price from the reset-fee table; the site also
    advertises first-purchase discounts (for example $74.99 for Flex 50K with code FNFLEX) and the
    add-on bundles price Rapid Pro *below* the base model. Discounts are checkout variables, not
    rules.
11. **Direct's perpetual consistency denominator.** The rule is declared with
    `numerator_window: all_time` and `denominator_window: current_cycle`, so the cycle's profit is
    the balance less the balance the cycle opened at. The page says "your current cycle's total
    profit", which is the same thing for a balance that moves only by trading P&L; confirm that
    balance reading (it is also what makes the best day "carry forward" after a withdrawal). The
    numerator is the best RULE-DAY's profit, not the best single trade's.
12. **The reward-request same-day rule** (a trade on the day removes the transfer-to-wallet option)
    is modelled as immaterial: the payout rule evaluates at every rule-day close, so a payout can be
    taken a day earlier than the firm would allow.

## 10. Quote index - values whose provenance is a second page

`PayoutRule` carries one attribution, so each plan's payout quote was chosen to cover **every**
declared payout value. The pages that support values quoted in more than one rule:

#### `all models: session hours 17:00 -> 15:10 CT`
- url: https://fundednext.com/general-rules/futures/trading-platforms
- snapshot: `20261122_fn_rules_platforms.html`
- sha256: `79415d4a3efa3d7b2b11cac3b727501a4605e1e528d750c5a0e3a4d9ae90c6ee`
- quote: "Trading runs every day from ⁦5:00⁩ PM CT to ⁦3:10⁩ PM CT the following day. The market stays
  closed from ⁦3:10⁩ PM CT to ⁦5:00⁩ PM CT. Any open positions at ⁦3:10⁩ PM CT are closed automatically by
  the system."

#### `all models: rule-day boundary 5:00 PM CT (the top-level reset clock)`
- url: https://fundednext.com/general-rules/futures/trading-objectives
- snapshot: `20261122_fn_rules_objectives.html`
- sha256: `e903fbb58fe67481c98c1924bdd160f23662bd0d9ebdbf2c5aecb576a86e8845`
- quote: "On Rapid and Direct, breaching the DLL is a soft breach — trading pauses for the rest of
  the session and resumes the next day. Resets daily at ⁦⁦5:00⁩ PM CT.."

#### `all models: profit target on closed-position P&L`
- url: https://fundednext.com/general-rules/futures/trading-objectives
- section: 1 Profit Target
- quote: "A required profit target to complete the Challenge. Calculated on closed-position P&L."

#### `all models: MLL marked on the highest end-of-day balance`
- url: https://fundednext.com/general-rules/futures/trading-objectives
- section: 3 Maximum Loss Limit
- quote: "The MLL is calculated on the highest end-of-day balance. It trails up as the account hits
  new closing highs, locks once it reaches the initial balance, and does not decrease during
  losses."

The funded phases quote their own MLL table ("The Maximum Loss Limit (MLL) continues to apply on
your funded account, using the same Trailing End-of-Day (EOD) system as the Challenge") and that
sentence is what carries the end-of-day-balance basis into the funded rule; Direct's page states it
outright ("using the Trailing End-of-Day (EOD) system that updates once per day based on your
highest balance that day").

## 11. Values the pages do NOT state

- **Minimum trading days in any Challenge**: none is stated ("There are no Benchmark Day requirements
  during the Challenge Phase for any Challenge Account"), so no `min_trading_days` rule is drafted
  and no `not_modeled` entry is needed.
- **Time limit**: absent by statement ("There is no time limit"), so `max_calendar_days: null` and
  `phase.max_trading_days: null` with no rule.
- **Effective date**: no page states when these rules took effect; `effective_from` is 2026-11-22
  (the Flex rules article is dated October 13, 2026, a publication date, not an effective date).
- **Instruments beyond the four named roots**: the symbols page names NQ, MNQ, ES and MES and ends
  with "and more". YM, RTY, NKD, MYM and M2K are never named on any FundedNext Futures page read
  here, so they are **not** in `instruments`, and no commission is declared for them.
- **Whether a Challenge pass requires a flat book**: not stated; `require_flat: false` (open
  question 8).
- **Commissions** other than the NQ example (section 5).
- **Add-on menu**: the Flex funnel advertises "13" add-ons but only the Rapid Pro daily-loss add-on
  changes a rule value and has published numbers; `addons: []` elsewhere.

## 12. UNREADABLE / unusable URLs

None. Every page used returned HTTP 200 with its rule text in the raw bytes: `fundednext.com` is a
Next.js app whose rule content is server-rendered, and the Intercom help centre renders each article
body into the HTML (no JSON API or JS execution needed). No value was read from an image or a
JS-only widget. One page was fetched for this migration (the commission article,
`20261122_fn_a_commissions.html`); its sha256 is in section 5 and in every file.

## 13. Every file in detail (generated from the YAML)

### `fundednext-futures-direct-100k`

- account: 100000 USD (100K), program `Futures Direct`, platform Tradovate / NinjaTrader / TradingView, addons none, as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `fundednext_account` (funded, start 100000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=3500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm, first_payout], at_offset_usd: 3600, locked_offset_usd: 100}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What is the Maximum Loss Limit on the FundedNext Futures Direct Account? |
| `funded_daily_loss` | `daily_loss` | `amount_usd=2000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §Is there a daily loss limit on the FundedNext Futures Direct Account? |
| `funded_contract_limit` | `max_contracts` | `limit=6`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What are the contract limits on the FundedNext Futures Direct Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_performance_reward` | `payout` | `min_days_since_last=0`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=3600`, `split=0.90`, `min_usd=1500`, `max_usd=2000`, `min_profit_since_last_usd=0`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=lock_on_first_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What are the Performance Reward eligibility criteria for the FundedNext Futures Direct Account? |
| `funded_perpetual_consistency` | `consistency` | `max_day_share=0.20`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=all_time`, `numerator_window=all_time`, `denominator_window=current_cycle`, `comparison=<=`, `action=block_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §Is there a Consistency Rule on the FundedNext Futures Direct Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=7`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Fees (attempt cost accounting, never in the ledger):

- `account_purchase_fee`: evaluation 584.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What account sizes and prices are available?

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What is the Micro-Scalping policy for the FundedNext Futures Direct Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §How do I request my Performance Reward from the FundedNext Futures Direct Account?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=3500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm, first_payout], at_offset_usd: 3600, locked_offset_usd: 100}`
- [ ] `funded_daily_loss` (fundednext_account): `amount_usd=2000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=6`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_perpetual_consistency` (fundednext_account): `max_day_share=0.20`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=all_time`, `numerator_window=all_time`, `denominator_window=current_cycle`, `comparison=<=`, `action=block_payout`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=7`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=0`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=3600`, `split=0.90`, `min_usd=1500`, `max_usd=2000`, `min_profit_since_last_usd=0`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=lock_on_first_payout`

fees and commissions:

- [ ] `account_purchase_fee` (fundednext_account): `fee_kind=evaluation`, `amount_usd=584.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

### `fundednext-futures-direct-150k`

- account: 150000 USD (150K), program `Futures Direct`, platform Tradovate / NinjaTrader / TradingView, addons none, as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `fundednext_account` (funded, start 150000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=5000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm, first_payout], at_offset_usd: 5100, locked_offset_usd: 100}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What is the Maximum Loss Limit on the FundedNext Futures Direct Account? |
| `funded_daily_loss` | `daily_loss` | `amount_usd=3000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §Is there a daily loss limit on the FundedNext Futures Direct Account? |
| `funded_contract_limit` | `max_contracts` | `limit=8`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What are the contract limits on the FundedNext Futures Direct Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_performance_reward` | `payout` | `min_days_since_last=0`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=5100`, `split=0.90`, `min_usd=2000`, `max_usd=2500`, `min_profit_since_last_usd=0`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=lock_on_first_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What are the Performance Reward eligibility criteria for the FundedNext Futures Direct Account? |
| `funded_perpetual_consistency` | `consistency` | `max_day_share=0.20`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=all_time`, `numerator_window=all_time`, `denominator_window=current_cycle`, `comparison=<=`, `action=block_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §Is there a Consistency Rule on the FundedNext Futures Direct Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=7`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Fees (attempt cost accounting, never in the ledger):

- `account_purchase_fee`: evaluation 754.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What account sizes and prices are available?

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What is the Micro-Scalping policy for the FundedNext Futures Direct Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §How do I request my Performance Reward from the FundedNext Futures Direct Account?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=5000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm, first_payout], at_offset_usd: 5100, locked_offset_usd: 100}`
- [ ] `funded_daily_loss` (fundednext_account): `amount_usd=3000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=8`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_perpetual_consistency` (fundednext_account): `max_day_share=0.20`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=all_time`, `numerator_window=all_time`, `denominator_window=current_cycle`, `comparison=<=`, `action=block_payout`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=7`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=0`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=5100`, `split=0.90`, `min_usd=2000`, `max_usd=2500`, `min_profit_since_last_usd=0`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=lock_on_first_payout`

fees and commissions:

- [ ] `account_purchase_fee` (fundednext_account): `fee_kind=evaluation`, `amount_usd=754.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

### `fundednext-futures-direct-50k`

- account: 50000 USD (50K), program `Futures Direct`, platform Tradovate / NinjaTrader / TradingView, addons none, as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `fundednext_account` (funded, start 50000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm, first_payout], at_offset_usd: 2100, locked_offset_usd: 100}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What is the Maximum Loss Limit on the FundedNext Futures Direct Account? |
| `funded_daily_loss` | `daily_loss` | `amount_usd=1000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §Is there a daily loss limit on the FundedNext Futures Direct Account? |
| `funded_contract_limit` | `max_contracts` | `limit=3`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What are the contract limits on the FundedNext Futures Direct Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_performance_reward` | `payout` | `min_days_since_last=0`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=2100`, `split=0.90`, `min_usd=800`, `max_usd=1200`, `min_profit_since_last_usd=0`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=lock_on_first_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What are the Performance Reward eligibility criteria for the FundedNext Futures Direct Account? |
| `funded_perpetual_consistency` | `consistency` | `max_day_share=0.20`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=all_time`, `numerator_window=all_time`, `denominator_window=current_cycle`, `comparison=<=`, `action=block_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §Is there a Consistency Rule on the FundedNext Futures Direct Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=7`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Fees (attempt cost accounting, never in the ledger):

- `account_purchase_fee`: evaluation 284.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What account sizes and prices are available?

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §What is the Micro-Scalping policy for the FundedNext Futures Direct Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17430065-fundednext-futures-direct-account-all-rules> §How do I request my Performance Reward from the FundedNext Futures Direct Account?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm, first_payout], at_offset_usd: 2100, locked_offset_usd: 100}`
- [ ] `funded_daily_loss` (fundednext_account): `amount_usd=1000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=3`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_perpetual_consistency` (fundednext_account): `max_day_share=0.20`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=all_time`, `numerator_window=all_time`, `denominator_window=current_cycle`, `comparison=<=`, `action=block_payout`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=7`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=0`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=2100`, `split=0.90`, `min_usd=800`, `max_usd=1200`, `min_profit_since_last_usd=0`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=lock_on_first_payout`

fees and commissions:

- [ ] `account_purchase_fee` (fundednext_account): `fee_kind=evaluation`, `amount_usd=284.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

### `fundednext-futures-flex-100k`

- account: 100000 USD (100K), program `Futures Flex`, platform Tradovate / NinjaTrader / TradingView, addons none, as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `challenge` (evaluation, start 100000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_max_loss_limit` | `trailing_drawdown` | `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §What is the Maximum Loss Limit in the Flex Challenge? |
| `challenge_contract_limit` | `max_contracts` | `limit=5`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §What are the contract limits in the Flex Challenge? |
| `challenge_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `challenge_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Pass conditions:

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_profit_target` | `profit_target` | `amount_usd=5000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False` | `assumption` | <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §What are the available account sizes in the Flex Challenge? |
| `challenge_consistency` | `consistency` | `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=pass`, `window=all_time`, `comparison=<=`, `action=promote_phase` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §Is there a Consistency Rule in the Flex Challenge? |

Fees (attempt cost accounting, never in the ledger):

- `challenge_entry_fee`: evaluation 273.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge
- `challenge_reset_fee`: reset 157.99 USD `when=on_reset` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge

#### phase `fundednext_account` (funded, start 100000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm, first_payout], at_offset_usd: 2600, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Flex FundedNext Account? |
| `funded_contract_limit` | `max_contracts` | `limit=5`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What are the contract limits on the Flex FundedNext Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_performance_reward` | `payout` | `min_days_since_last=0`, `min_profitable_days=5`, `min_traded_days=0`, `min_day_profit_usd=200`, `window=since_last_payout`, `buffer_usd=0`, `split=0.95`, `min_usd=250`, `max_usd=2500`, `max_share_of_withdrawable=0.5`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=lock_on_first_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What are the Performance Reward eligibility criteria for the Flex FundedNext Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

#### conflicts (both sources)

- `mll_lock_point_challenge` on `challenge_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §What is the Maximum Loss Limit in the Flex Challenge?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}` from <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §Important notes -> scenario `mll_lock_point_challenge#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($100,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $100,100, which would freeze the floor at $97,600. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.
- `mll_lock_point_funded` on `funded_max_loss_limit` field `lock`: SELECTED `{on: [hwm, first_payout], at_offset_usd: 2600, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Flex FundedNext Account?
  - alternative `#0` `{on: [hwm, first_payout], at_offset_usd: 100, locked_threshold_usd: 97600}` from <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §Important notes -> scenario `mll_lock_point_funded#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($100,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $100,100, which would freeze the floor at $97,600. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.

#### assumptions

- `challenge_profit_target`: `unspecified_target_frequency_is_eod` — The profit target is quoted on closed-position P&L, but no page says when it is tested. The intraday default belongs to failure thresholds, where it makes enforcement stricter; for a pass condition the conservative reading is the end of the trade date on the closed balance, because the trader then passes no earlier than the close and a later same-day breach still counts against the attempt. The same silence covers require_flat, which stays false because the target is defined on closed positions.

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What is the Micro-Scalping policy for the Flex FundedNext Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §How do I request my Performance Reward?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `challenge_max_loss_limit` (challenge): `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}`
- [ ] `challenge_contract_limit` (challenge): `limit=5`, `comparison=<=`, `action=clip`
- [ ] `challenge_flat_by` (challenge): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `challenge_inactivity` (challenge): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`
- [ ] `challenge_profit_target` (challenge): `amount_usd=5000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False`
- [ ] `challenge_consistency` (challenge): `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=pass`, `window=all_time`, `comparison=<=`, `action=promote_phase`
- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm, first_payout], at_offset_usd: 2600, locked_offset_usd: 100}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=5`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=0`, `min_profitable_days=5`, `min_traded_days=0`, `min_day_profit_usd=200`, `window=since_last_payout`, `buffer_usd=0`, `split=0.95`, `min_usd=250`, `max_usd=2500`, `max_share_of_withdrawable=0.5`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=lock_on_first_payout`

fees and commissions:

- [ ] `challenge_entry_fee` (challenge): `fee_kind=evaluation`, `amount_usd=273.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] `challenge_reset_fee` (challenge): `fee_kind=reset`, `amount_usd=157.99`, `when=on_reset`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `challenge_compliance_copy_and_group_trading` (challenge): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `challenge_compliance_account_sharing` (challenge): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

assumptions:

- [ ] `challenge_profit_target`: `unspecified_target_frequency_is_eod`

conflicts:

- [ ] `mll_lock_point_challenge`: {on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}
- [ ] `mll_lock_point_funded`: {on: [hwm, first_payout], at_offset_usd: 2600, locked_offset_usd: 100} selected over {on: [hwm, first_payout], at_offset_usd: 100, locked_threshold_usd: 97600}

### `fundednext-futures-flex-150k`

- account: 150000 USD (150K), program `Futures Flex`, platform Tradovate / NinjaTrader / TradingView, addons none, as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `challenge` (evaluation, start 150000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_max_loss_limit` | `trailing_drawdown` | `amount_usd=4000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 4100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §What is the Maximum Loss Limit in the Flex Challenge? |
| `challenge_contract_limit` | `max_contracts` | `limit=8`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §What are the contract limits in the Flex Challenge? |
| `challenge_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `challenge_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Pass conditions:

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_profit_target` | `profit_target` | `amount_usd=8000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False` | `assumption` | <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §What are the available account sizes in the Flex Challenge? |
| `challenge_consistency` | `consistency` | `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=pass`, `window=all_time`, `comparison=<=`, `action=promote_phase` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §Is there a Consistency Rule in the Flex Challenge? |

Fees (attempt cost accounting, never in the ledger):

- `challenge_entry_fee`: evaluation 490.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge
- `challenge_reset_fee`: reset 284.99 USD `when=on_reset` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge

#### phase `fundednext_account` (funded, start 150000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=4000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm, first_payout], at_offset_usd: 4100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Flex FundedNext Account? |
| `funded_contract_limit` | `max_contracts` | `limit=8`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What are the contract limits on the Flex FundedNext Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_performance_reward` | `payout` | `min_days_since_last=0`, `min_profitable_days=5`, `min_traded_days=0`, `min_day_profit_usd=250`, `window=since_last_payout`, `buffer_usd=0`, `split=0.95`, `min_usd=250`, `max_usd=4000`, `max_share_of_withdrawable=0.5`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=lock_on_first_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What are the Performance Reward eligibility criteria for the Flex FundedNext Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

#### conflicts (both sources)

- `mll_lock_point_challenge` on `challenge_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 4100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §What is the Maximum Loss Limit in the Flex Challenge?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 146100}` from <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §Important notes -> scenario `mll_lock_point_challenge#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($150,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $150,100, which would freeze the floor at $146,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.
- `mll_lock_point_funded` on `funded_max_loss_limit` field `lock`: SELECTED `{on: [hwm, first_payout], at_offset_usd: 4100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Flex FundedNext Account?
  - alternative `#0` `{on: [hwm, first_payout], at_offset_usd: 100, locked_threshold_usd: 146100}` from <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §Important notes -> scenario `mll_lock_point_funded#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($150,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $150,100, which would freeze the floor at $146,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.

#### assumptions

- `challenge_profit_target`: `unspecified_target_frequency_is_eod` — The profit target is quoted on closed-position P&L, but no page says when it is tested. The intraday default belongs to failure thresholds, where it makes enforcement stricter; for a pass condition the conservative reading is the end of the trade date on the closed balance, because the trader then passes no earlier than the close and a later same-day breach still counts against the attempt. The same silence covers require_flat, which stays false because the target is defined on closed positions.

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What is the Micro-Scalping policy for the Flex FundedNext Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §How do I request my Performance Reward?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `challenge_max_loss_limit` (challenge): `amount_usd=4000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 4100, locked_offset_usd: 100}`
- [ ] `challenge_contract_limit` (challenge): `limit=8`, `comparison=<=`, `action=clip`
- [ ] `challenge_flat_by` (challenge): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `challenge_inactivity` (challenge): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`
- [ ] `challenge_profit_target` (challenge): `amount_usd=8000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False`
- [ ] `challenge_consistency` (challenge): `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=pass`, `window=all_time`, `comparison=<=`, `action=promote_phase`
- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=4000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm, first_payout], at_offset_usd: 4100, locked_offset_usd: 100}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=8`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=0`, `min_profitable_days=5`, `min_traded_days=0`, `min_day_profit_usd=250`, `window=since_last_payout`, `buffer_usd=0`, `split=0.95`, `min_usd=250`, `max_usd=4000`, `max_share_of_withdrawable=0.5`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=lock_on_first_payout`

fees and commissions:

- [ ] `challenge_entry_fee` (challenge): `fee_kind=evaluation`, `amount_usd=490.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] `challenge_reset_fee` (challenge): `fee_kind=reset`, `amount_usd=284.99`, `when=on_reset`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `challenge_compliance_copy_and_group_trading` (challenge): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `challenge_compliance_account_sharing` (challenge): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

assumptions:

- [ ] `challenge_profit_target`: `unspecified_target_frequency_is_eod`

conflicts:

- [ ] `mll_lock_point_challenge`: {on: [hwm], at_offset_usd: 4100, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 146100}
- [ ] `mll_lock_point_funded`: {on: [hwm, first_payout], at_offset_usd: 4100, locked_offset_usd: 100} selected over {on: [hwm, first_payout], at_offset_usd: 100, locked_threshold_usd: 146100}

### `fundednext-futures-flex-50k`

- account: 50000 USD (50K), program `Futures Flex`, platform Tradovate / NinjaTrader / TradingView, addons none, as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `challenge` (evaluation, start 50000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_max_loss_limit` | `trailing_drawdown` | `amount_usd=1500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1600, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §What is the Maximum Loss Limit in the Flex Challenge? |
| `challenge_contract_limit` | `max_contracts` | `limit=3`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §What are the contract limits in the Flex Challenge? |
| `challenge_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `challenge_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Pass conditions:

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_profit_target` | `profit_target` | `amount_usd=2500`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False` | `assumption` | <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §What are the available account sizes in the Flex Challenge? |
| `challenge_consistency` | `consistency` | `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=pass`, `window=all_time`, `comparison=<=`, `action=promote_phase` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §Is there a Consistency Rule in the Flex Challenge? |

Fees (attempt cost accounting, never in the ledger):

- `challenge_entry_fee`: evaluation 141.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge
- `challenge_reset_fee`: reset 82.99 USD `when=on_reset` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge

#### phase `fundednext_account` (funded, start 50000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=1500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm, first_payout], at_offset_usd: 1600, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Flex FundedNext Account? |
| `funded_contract_limit` | `max_contracts` | `limit=3`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What are the contract limits on the Flex FundedNext Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_performance_reward` | `payout` | `min_days_since_last=0`, `min_profitable_days=5`, `min_traded_days=0`, `min_day_profit_usd=200`, `window=since_last_payout`, `buffer_usd=0`, `split=0.95`, `min_usd=250`, `max_usd=1500`, `max_share_of_withdrawable=0.5`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=lock_on_first_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What are the Performance Reward eligibility criteria for the Flex FundedNext Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

#### conflicts (both sources)

- `mll_lock_point_challenge` on `challenge_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 1600, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §What is the Maximum Loss Limit in the Flex Challenge?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48600}` from <https://helpfutures.fundednext.com/en/articles/17229829-fundednext-futures-flex-challenge-all-rules> §Important notes -> scenario `mll_lock_point_challenge#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($50,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $50,100, which would freeze the floor at $48,600. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.
- `mll_lock_point_funded` on `funded_max_loss_limit` field `lock`: SELECTED `{on: [hwm, first_payout], at_offset_usd: 1600, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Flex FundedNext Account?
  - alternative `#0` `{on: [hwm, first_payout], at_offset_usd: 100, locked_threshold_usd: 48600}` from <https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §Important notes -> scenario `mll_lock_point_funded#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($50,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $50,100, which would freeze the floor at $48,600. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.

#### assumptions

- `challenge_profit_target`: `unspecified_target_frequency_is_eod` — The profit target is quoted on closed-position P&L, but no page says when it is tested. The intraday default belongs to failure thresholds, where it makes enforcement stricter; for a pass condition the conservative reading is the end of the trade date on the closed balance, because the trader then passes no earlier than the close and a later same-day breach still counts against the attempt. The same silence covers require_flat, which stays false because the target is defined on closed positions.

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §What is the Micro-Scalping policy for the Flex FundedNext Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17229848-fundednext-futures-flex-fundednext-account-all-rules> §How do I request my Performance Reward?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `challenge_max_loss_limit` (challenge): `amount_usd=1500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1600, locked_offset_usd: 100}`
- [ ] `challenge_contract_limit` (challenge): `limit=3`, `comparison=<=`, `action=clip`
- [ ] `challenge_flat_by` (challenge): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `challenge_inactivity` (challenge): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`
- [ ] `challenge_profit_target` (challenge): `amount_usd=2500`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False`
- [ ] `challenge_consistency` (challenge): `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=pass`, `window=all_time`, `comparison=<=`, `action=promote_phase`
- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=1500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm, first_payout], at_offset_usd: 1600, locked_offset_usd: 100}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=3`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=0`, `min_profitable_days=5`, `min_traded_days=0`, `min_day_profit_usd=200`, `window=since_last_payout`, `buffer_usd=0`, `split=0.95`, `min_usd=250`, `max_usd=1500`, `max_share_of_withdrawable=0.5`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=lock_on_first_payout`

fees and commissions:

- [ ] `challenge_entry_fee` (challenge): `fee_kind=evaluation`, `amount_usd=141.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] `challenge_reset_fee` (challenge): `fee_kind=reset`, `amount_usd=82.99`, `when=on_reset`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `challenge_compliance_copy_and_group_trading` (challenge): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `challenge_compliance_account_sharing` (challenge): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

assumptions:

- [ ] `challenge_profit_target`: `unspecified_target_frequency_is_eod`

conflicts:

- [ ] `mll_lock_point_challenge`: {on: [hwm], at_offset_usd: 1600, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48600}
- [ ] `mll_lock_point_funded`: {on: [hwm, first_payout], at_offset_usd: 1600, locked_offset_usd: 100} selected over {on: [hwm, first_payout], at_offset_usd: 100, locked_threshold_usd: 48600}

### `fundednext-futures-rapiddaily-100k`

- account: 100000 USD (100K), program `Futures Rapid Daily`, platform Tradovate / NinjaTrader / TradingView, addons none, as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `challenge` (evaluation, start 100000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_daily_loss` | `daily_loss` | `amount_usd=1250`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §Is there a daily loss limit in the Rapid Daily Challenge? |
| `challenge_max_loss_limit` | `trailing_drawdown` | `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Daily Challenge? |
| `challenge_contract_limit` | `max_contracts` | `limit=6`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §What are the contract limits in the Rapid Daily Challenge? |
| `challenge_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `challenge_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Pass conditions:

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_profit_target` | `profit_target` | `amount_usd=5000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False` | `assumption` | <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §What are the available account sizes in the Rapid Daily Challenge? |

Fees (attempt cost accounting, never in the ledger):

- `challenge_entry_fee`: evaluation 483.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge
- `challenge_reset_fee`: reset 287.99 USD `when=on_reset` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge

#### phase `fundednext_account` (funded, start 100000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Daily FundedNext Account? |
| `funded_daily_loss` | `daily_loss` | `amount_usd=1250`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §Is there a daily loss limit on the Rapid Daily FundedNext Account? |
| `funded_contract_limit` | `max_contracts` | `limit=6`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §What are the contract limits on the Rapid Daily FundedNext Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_performance_reward` | `payout` | `min_days_since_last=0`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=2600`, `split=0.90`, `min_usd=250`, `max_usd=2000`, `max_usd_by_payout=[2000, 2000, 2000, 2500, 2500]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §How much can I withdraw, and how often, from the Rapid Daily FundedNext Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

#### conflicts (both sources)

- `mll_lock_point_challenge` on `challenge_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Daily Challenge?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}` from <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §Important notes -> scenario `mll_lock_point_challenge#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($100,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $100,100, which would freeze the floor at $97,600. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.
- `mll_lock_point_funded` on `funded_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Daily FundedNext Account?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}` from <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §Important notes -> scenario `mll_lock_point_funded#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($100,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $100,100, which would freeze the floor at $97,600. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.

#### assumptions

- `challenge_profit_target`: `unspecified_target_frequency_is_eod` — The profit target is quoted on closed-position P&L, but no page says when it is tested. The intraday default belongs to failure thresholds, where it makes enforcement stricter; for a pass condition the conservative reading is the end of the trade date on the closed balance, because the trader then passes no earlier than the close and a later same-day breach still counts against the attempt. The same silence covers require_flat, which stays false because the target is defined on closed positions.

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §What is the Micro-Scalping policy for the Rapid Daily FundedNext Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §How do I request my Performance Reward?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `challenge_daily_loss` (challenge): `amount_usd=1250`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `challenge_max_loss_limit` (challenge): `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}`
- [ ] `challenge_contract_limit` (challenge): `limit=6`, `comparison=<=`, `action=clip`
- [ ] `challenge_flat_by` (challenge): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `challenge_inactivity` (challenge): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`
- [ ] `challenge_profit_target` (challenge): `amount_usd=5000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False`
- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}`
- [ ] `funded_daily_loss` (fundednext_account): `amount_usd=1250`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=6`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=0`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=2600`, `split=0.90`, `min_usd=250`, `max_usd=2000`, `max_usd_by_payout=[2000, 2000, 2000, 2500, 2500]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged`

fees and commissions:

- [ ] `challenge_entry_fee` (challenge): `fee_kind=evaluation`, `amount_usd=483.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] `challenge_reset_fee` (challenge): `fee_kind=reset`, `amount_usd=287.99`, `when=on_reset`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `challenge_compliance_copy_and_group_trading` (challenge): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `challenge_compliance_account_sharing` (challenge): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

assumptions:

- [ ] `challenge_profit_target`: `unspecified_target_frequency_is_eod`

conflicts:

- [ ] `mll_lock_point_challenge`: {on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}
- [ ] `mll_lock_point_funded`: {on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}

### `fundednext-futures-rapiddaily-25k`

- account: 25000 USD (25K), program `Futures Rapid Daily`, platform Tradovate / NinjaTrader / TradingView, addons none, as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `challenge` (evaluation, start 25000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_daily_loss` | `daily_loss` | `amount_usd=500`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §Is there a daily loss limit in the Rapid Daily Challenge? |
| `challenge_max_loss_limit` | `trailing_drawdown` | `amount_usd=1000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Daily Challenge? |
| `challenge_contract_limit` | `max_contracts` | `limit=2`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §What are the contract limits in the Rapid Daily Challenge? |
| `challenge_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `challenge_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Pass conditions:

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_profit_target` | `profit_target` | `amount_usd=1500`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False` | `assumption` | <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §What are the available account sizes in the Rapid Daily Challenge? |

Fees (attempt cost accounting, never in the ledger):

- `challenge_entry_fee`: evaluation 125.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge
- `challenge_reset_fee`: reset 72.99 USD `when=on_reset` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge

#### phase `fundednext_account` (funded, start 25000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=1000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Daily FundedNext Account? |
| `funded_daily_loss` | `daily_loss` | `amount_usd=500`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §Is there a daily loss limit on the Rapid Daily FundedNext Account? |
| `funded_contract_limit` | `max_contracts` | `limit=2`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §What are the contract limits on the Rapid Daily FundedNext Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_performance_reward` | `payout` | `min_days_since_last=0`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=1100`, `split=0.90`, `min_usd=250`, `max_usd=600`, `max_usd_by_payout=[600, 600, 600, 850, 850]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §How much can I withdraw, and how often, from the Rapid Daily FundedNext Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

#### conflicts (both sources)

- `mll_lock_point_challenge` on `challenge_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Daily Challenge?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 24100}` from <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §Important notes -> scenario `mll_lock_point_challenge#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($25,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $25,100, which would freeze the floor at $24,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.
- `mll_lock_point_funded` on `funded_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Daily FundedNext Account?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 24100}` from <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §Important notes -> scenario `mll_lock_point_funded#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($25,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $25,100, which would freeze the floor at $24,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.

#### assumptions

- `challenge_profit_target`: `unspecified_target_frequency_is_eod` — The profit target is quoted on closed-position P&L, but no page says when it is tested. The intraday default belongs to failure thresholds, where it makes enforcement stricter; for a pass condition the conservative reading is the end of the trade date on the closed balance, because the trader then passes no earlier than the close and a later same-day breach still counts against the attempt. The same silence covers require_flat, which stays false because the target is defined on closed positions.

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §What is the Micro-Scalping policy for the Rapid Daily FundedNext Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §How do I request my Performance Reward?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `challenge_daily_loss` (challenge): `amount_usd=500`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `challenge_max_loss_limit` (challenge): `amount_usd=1000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}`
- [ ] `challenge_contract_limit` (challenge): `limit=2`, `comparison=<=`, `action=clip`
- [ ] `challenge_flat_by` (challenge): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `challenge_inactivity` (challenge): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`
- [ ] `challenge_profit_target` (challenge): `amount_usd=1500`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False`
- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=1000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}`
- [ ] `funded_daily_loss` (fundednext_account): `amount_usd=500`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=2`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=0`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=1100`, `split=0.90`, `min_usd=250`, `max_usd=600`, `max_usd_by_payout=[600, 600, 600, 850, 850]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged`

fees and commissions:

- [ ] `challenge_entry_fee` (challenge): `fee_kind=evaluation`, `amount_usd=125.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] `challenge_reset_fee` (challenge): `fee_kind=reset`, `amount_usd=72.99`, `when=on_reset`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `challenge_compliance_copy_and_group_trading` (challenge): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `challenge_compliance_account_sharing` (challenge): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

assumptions:

- [ ] `challenge_profit_target`: `unspecified_target_frequency_is_eod`

conflicts:

- [ ] `mll_lock_point_challenge`: {on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 24100}
- [ ] `mll_lock_point_funded`: {on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 24100}

### `fundednext-futures-rapiddaily-50k`

- account: 50000 USD (50K), program `Futures Rapid Daily`, platform Tradovate / NinjaTrader / TradingView, addons none, as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `challenge` (evaluation, start 50000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_daily_loss` | `daily_loss` | `amount_usd=1000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §Is there a daily loss limit in the Rapid Daily Challenge? |
| `challenge_max_loss_limit` | `trailing_drawdown` | `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Daily Challenge? |
| `challenge_contract_limit` | `max_contracts` | `limit=4`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §What are the contract limits in the Rapid Daily Challenge? |
| `challenge_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `challenge_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Pass conditions:

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_profit_target` | `profit_target` | `amount_usd=3000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False` | `assumption` | <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §What are the available account sizes in the Rapid Daily Challenge? |

Fees (attempt cost accounting, never in the ledger):

- `challenge_entry_fee`: evaluation 299.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge
- `challenge_reset_fee`: reset 177.99 USD `when=on_reset` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge

#### phase `fundednext_account` (funded, start 50000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Daily FundedNext Account? |
| `funded_daily_loss` | `daily_loss` | `amount_usd=1000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §Is there a daily loss limit on the Rapid Daily FundedNext Account? |
| `funded_contract_limit` | `max_contracts` | `limit=4`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §What are the contract limits on the Rapid Daily FundedNext Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_performance_reward` | `payout` | `min_days_since_last=0`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=2100`, `split=0.90`, `min_usd=250`, `max_usd=1000`, `max_usd_by_payout=[1000, 1000, 1000, 1250, 1250]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §How much can I withdraw, and how often, from the Rapid Daily FundedNext Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

#### conflicts (both sources)

- `mll_lock_point_challenge` on `challenge_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Daily Challenge?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48100}` from <https://helpfutures.fundednext.com/en/articles/17229762-fundednext-futures-rapid-daily-challenge-all-rules> §Important notes -> scenario `mll_lock_point_challenge#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($50,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $50,100, which would freeze the floor at $48,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.
- `mll_lock_point_funded` on `funded_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Daily FundedNext Account?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48100}` from <https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §Important notes -> scenario `mll_lock_point_funded#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($50,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $50,100, which would freeze the floor at $48,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.

#### assumptions

- `challenge_profit_target`: `unspecified_target_frequency_is_eod` — The profit target is quoted on closed-position P&L, but no page says when it is tested. The intraday default belongs to failure thresholds, where it makes enforcement stricter; for a pass condition the conservative reading is the end of the trade date on the closed balance, because the trader then passes no earlier than the close and a later same-day breach still counts against the attempt. The same silence covers require_flat, which stays false because the target is defined on closed positions.

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §What is the Micro-Scalping policy for the Rapid Daily FundedNext Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17229779-fundednext-futures-rapid-daily-fundednext-account-all-rules> §How do I request my Performance Reward?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `challenge_daily_loss` (challenge): `amount_usd=1000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `challenge_max_loss_limit` (challenge): `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}`
- [ ] `challenge_contract_limit` (challenge): `limit=4`, `comparison=<=`, `action=clip`
- [ ] `challenge_flat_by` (challenge): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `challenge_inactivity` (challenge): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`
- [ ] `challenge_profit_target` (challenge): `amount_usd=3000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False`
- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}`
- [ ] `funded_daily_loss` (fundednext_account): `amount_usd=1000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=4`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=0`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=2100`, `split=0.90`, `min_usd=250`, `max_usd=1000`, `max_usd_by_payout=[1000, 1000, 1000, 1250, 1250]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged`

fees and commissions:

- [ ] `challenge_entry_fee` (challenge): `fee_kind=evaluation`, `amount_usd=299.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] `challenge_reset_fee` (challenge): `fee_kind=reset`, `amount_usd=177.99`, `when=on_reset`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `challenge_compliance_copy_and_group_trading` (challenge): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `challenge_compliance_account_sharing` (challenge): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

assumptions:

- [ ] `challenge_profit_target`: `unspecified_target_frequency_is_eod`

conflicts:

- [ ] `mll_lock_point_challenge`: {on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48100}
- [ ] `mll_lock_point_funded`: {on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48100}

### `fundednext-futures-rapidpro-100k-dlladdon`

- account: 100000 USD (100K), program `Futures Rapid Pro + DLL add-on`, platform Tradovate / NinjaTrader / TradingView, addons ['daily_loss_limit'], as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `challenge` (evaluation, start 100000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_daily_loss` | `daily_loss` | `amount_usd=1250`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §Is there a daily loss limit in the Rapid Pro Challenge? |
| `challenge_max_loss_limit` | `trailing_drawdown` | `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Pro Challenge? |
| `challenge_contract_limit` | `max_contracts` | `limit=6`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What are the contract limits in the Rapid Pro Challenge? |
| `challenge_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `challenge_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Pass conditions:

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_profit_target` | `profit_target` | `amount_usd=5000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False` | `assumption` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What are the available account sizes in the Rapid Pro Challenge? |

Fees (attempt cost accounting, never in the ledger):

- `challenge_entry_fee`: evaluation 433.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge
- `challenge_reset_fee`: reset 237.99 USD `when=on_reset` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge

#### phase `fundednext_account` (funded, start 100000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Pro FundedNext Account? |
| `funded_daily_loss` | `daily_loss` | `amount_usd=1250`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Is there a daily loss limit on the Rapid Pro FundedNext Account? |
| `funded_contract_limit` | `max_contracts` | `limit=6`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What are the contract limits on the Rapid Pro FundedNext Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_consistency` | `consistency` | `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=since_last_payout`, `comparison=<=`, `action=block_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Is there a Consistency Rule on the Rapid Pro FundedNext Account? |
| `funded_performance_reward` | `payout` | `min_days_since_last=3`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=0`, `split=0.90`, `min_usd=250`, `max_usd=2000`, `max_usd_by_payout=[2000, 2000, 2000, 2500, 2500]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §How much can I withdraw, and how often, from the Rapid Pro FundedNext Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

#### conflicts (both sources)

- `mll_lock_point_challenge` on `challenge_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Pro Challenge?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}` from <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §Important notes -> scenario `mll_lock_point_challenge#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($100,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $100,100, which would freeze the floor at $97,600. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.
- `mll_lock_point_funded` on `funded_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Pro FundedNext Account?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}` from <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Important notes -> scenario `mll_lock_point_funded#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($100,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $100,100, which would freeze the floor at $97,600. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.

#### assumptions

- `challenge_profit_target`: `unspecified_target_frequency_is_eod` — The profit target is quoted on closed-position P&L, but no page says when it is tested. The intraday default belongs to failure thresholds, where it makes enforcement stricter; for a pass condition the conservative reading is the end of the trade date on the closed balance, because the trader then passes no earlier than the close and a later same-day breach still counts against the attempt. The same silence covers require_flat, which stays false because the target is defined on closed positions.

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Micro-Scalping policy for the Rapid Pro FundedNext Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §How do I request my Performance Reward?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `challenge_daily_loss` (challenge): `amount_usd=1250`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `challenge_max_loss_limit` (challenge): `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}`
- [ ] `challenge_contract_limit` (challenge): `limit=6`, `comparison=<=`, `action=clip`
- [ ] `challenge_flat_by` (challenge): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `challenge_inactivity` (challenge): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`
- [ ] `challenge_profit_target` (challenge): `amount_usd=5000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False`
- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}`
- [ ] `funded_daily_loss` (fundednext_account): `amount_usd=1250`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=6`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_consistency` (fundednext_account): `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=since_last_payout`, `comparison=<=`, `action=block_payout`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=3`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=0`, `split=0.90`, `min_usd=250`, `max_usd=2000`, `max_usd_by_payout=[2000, 2000, 2000, 2500, 2500]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged`

fees and commissions:

- [ ] `challenge_entry_fee` (challenge): `fee_kind=evaluation`, `amount_usd=433.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] `challenge_reset_fee` (challenge): `fee_kind=reset`, `amount_usd=237.99`, `when=on_reset`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `challenge_compliance_copy_and_group_trading` (challenge): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `challenge_compliance_account_sharing` (challenge): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

assumptions:

- [ ] `challenge_profit_target`: `unspecified_target_frequency_is_eod`

conflicts:

- [ ] `mll_lock_point_challenge`: {on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}
- [ ] `mll_lock_point_funded`: {on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}

### `fundednext-futures-rapidpro-100k`

- account: 100000 USD (100K), program `Futures Rapid Pro`, platform Tradovate / NinjaTrader / TradingView, addons none, as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `challenge` (evaluation, start 100000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_max_loss_limit` | `trailing_drawdown` | `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Pro Challenge? |
| `challenge_contract_limit` | `max_contracts` | `limit=6`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What are the contract limits in the Rapid Pro Challenge? |
| `challenge_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `challenge_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Pass conditions:

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_profit_target` | `profit_target` | `amount_usd=5000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False` | `assumption` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What are the available account sizes in the Rapid Pro Challenge? |

Fees (attempt cost accounting, never in the ledger):

- `challenge_entry_fee`: evaluation 483.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge
- `challenge_reset_fee`: reset 287.99 USD `when=on_reset` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge

#### phase `fundednext_account` (funded, start 100000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Pro FundedNext Account? |
| `funded_contract_limit` | `max_contracts` | `limit=6`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What are the contract limits on the Rapid Pro FundedNext Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_consistency` | `consistency` | `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=since_last_payout`, `comparison=<=`, `action=block_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Is there a Consistency Rule on the Rapid Pro FundedNext Account? |
| `funded_performance_reward` | `payout` | `min_days_since_last=3`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=0`, `split=0.90`, `min_usd=250`, `max_usd=2000`, `max_usd_by_payout=[2000, 2000, 2000, 2500, 2500]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §How much can I withdraw, and how often, from the Rapid Pro FundedNext Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

#### conflicts (both sources)

- `mll_lock_point_challenge` on `challenge_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Pro Challenge?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}` from <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §Important notes -> scenario `mll_lock_point_challenge#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($100,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $100,100, which would freeze the floor at $97,600. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.
- `mll_lock_point_funded` on `funded_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Pro FundedNext Account?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}` from <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Important notes -> scenario `mll_lock_point_funded#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($100,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $100,100, which would freeze the floor at $97,600. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.

#### assumptions

- `challenge_profit_target`: `unspecified_target_frequency_is_eod` — The profit target is quoted on closed-position P&L, but no page says when it is tested. The intraday default belongs to failure thresholds, where it makes enforcement stricter; for a pass condition the conservative reading is the end of the trade date on the closed balance, because the trader then passes no earlier than the close and a later same-day breach still counts against the attempt. The same silence covers require_flat, which stays false because the target is defined on closed positions.

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Micro-Scalping policy for the Rapid Pro FundedNext Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §How do I request my Performance Reward?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `challenge_max_loss_limit` (challenge): `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}`
- [ ] `challenge_contract_limit` (challenge): `limit=6`, `comparison=<=`, `action=clip`
- [ ] `challenge_flat_by` (challenge): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `challenge_inactivity` (challenge): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`
- [ ] `challenge_profit_target` (challenge): `amount_usd=5000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False`
- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=2500`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=6`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_consistency` (fundednext_account): `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=since_last_payout`, `comparison=<=`, `action=block_payout`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=3`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=0`, `split=0.90`, `min_usd=250`, `max_usd=2000`, `max_usd_by_payout=[2000, 2000, 2000, 2500, 2500]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged`

fees and commissions:

- [ ] `challenge_entry_fee` (challenge): `fee_kind=evaluation`, `amount_usd=483.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] `challenge_reset_fee` (challenge): `fee_kind=reset`, `amount_usd=287.99`, `when=on_reset`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `challenge_compliance_copy_and_group_trading` (challenge): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `challenge_compliance_account_sharing` (challenge): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

assumptions:

- [ ] `challenge_profit_target`: `unspecified_target_frequency_is_eod`

conflicts:

- [ ] `mll_lock_point_challenge`: {on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}
- [ ] `mll_lock_point_funded`: {on: [hwm], at_offset_usd: 2600, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 97600}

### `fundednext-futures-rapidpro-25k-dlladdon`

- account: 25000 USD (25K), program `Futures Rapid Pro + DLL add-on`, platform Tradovate / NinjaTrader / TradingView, addons ['daily_loss_limit'], as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `challenge` (evaluation, start 25000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_daily_loss` | `daily_loss` | `amount_usd=500`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §Is there a daily loss limit in the Rapid Pro Challenge? |
| `challenge_max_loss_limit` | `trailing_drawdown` | `amount_usd=1000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Pro Challenge? |
| `challenge_contract_limit` | `max_contracts` | `limit=2`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What are the contract limits in the Rapid Pro Challenge? |
| `challenge_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `challenge_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Pass conditions:

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_profit_target` | `profit_target` | `amount_usd=1500`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False` | `assumption` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What are the available account sizes in the Rapid Pro Challenge? |

Fees (attempt cost accounting, never in the ledger):

- `challenge_entry_fee`: evaluation 105.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge
- `challenge_reset_fee`: reset 52.99 USD `when=on_reset` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge

#### phase `fundednext_account` (funded, start 25000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=1000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Pro FundedNext Account? |
| `funded_daily_loss` | `daily_loss` | `amount_usd=500`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Is there a daily loss limit on the Rapid Pro FundedNext Account? |
| `funded_contract_limit` | `max_contracts` | `limit=2`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What are the contract limits on the Rapid Pro FundedNext Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_consistency` | `consistency` | `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=since_last_payout`, `comparison=<=`, `action=block_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Is there a Consistency Rule on the Rapid Pro FundedNext Account? |
| `funded_performance_reward` | `payout` | `min_days_since_last=3`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=0`, `split=0.90`, `min_usd=250`, `max_usd=600`, `max_usd_by_payout=[600, 600, 600, 850, 850]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §How much can I withdraw, and how often, from the Rapid Pro FundedNext Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

#### conflicts (both sources)

- `mll_lock_point_challenge` on `challenge_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Pro Challenge?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 24100}` from <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §Important notes -> scenario `mll_lock_point_challenge#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($25,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $25,100, which would freeze the floor at $24,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.
- `mll_lock_point_funded` on `funded_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Pro FundedNext Account?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 24100}` from <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Important notes -> scenario `mll_lock_point_funded#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($25,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $25,100, which would freeze the floor at $24,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.

#### assumptions

- `challenge_profit_target`: `unspecified_target_frequency_is_eod` — The profit target is quoted on closed-position P&L, but no page says when it is tested. The intraday default belongs to failure thresholds, where it makes enforcement stricter; for a pass condition the conservative reading is the end of the trade date on the closed balance, because the trader then passes no earlier than the close and a later same-day breach still counts against the attempt. The same silence covers require_flat, which stays false because the target is defined on closed positions.

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Micro-Scalping policy for the Rapid Pro FundedNext Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §How do I request my Performance Reward?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `challenge_daily_loss` (challenge): `amount_usd=500`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `challenge_max_loss_limit` (challenge): `amount_usd=1000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}`
- [ ] `challenge_contract_limit` (challenge): `limit=2`, `comparison=<=`, `action=clip`
- [ ] `challenge_flat_by` (challenge): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `challenge_inactivity` (challenge): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`
- [ ] `challenge_profit_target` (challenge): `amount_usd=1500`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False`
- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=1000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}`
- [ ] `funded_daily_loss` (fundednext_account): `amount_usd=500`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=2`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_consistency` (fundednext_account): `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=since_last_payout`, `comparison=<=`, `action=block_payout`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=3`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=0`, `split=0.90`, `min_usd=250`, `max_usd=600`, `max_usd_by_payout=[600, 600, 600, 850, 850]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged`

fees and commissions:

- [ ] `challenge_entry_fee` (challenge): `fee_kind=evaluation`, `amount_usd=105.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] `challenge_reset_fee` (challenge): `fee_kind=reset`, `amount_usd=52.99`, `when=on_reset`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `challenge_compliance_copy_and_group_trading` (challenge): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `challenge_compliance_account_sharing` (challenge): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

assumptions:

- [ ] `challenge_profit_target`: `unspecified_target_frequency_is_eod`

conflicts:

- [ ] `mll_lock_point_challenge`: {on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 24100}
- [ ] `mll_lock_point_funded`: {on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 24100}

### `fundednext-futures-rapidpro-25k`

- account: 25000 USD (25K), program `Futures Rapid Pro`, platform Tradovate / NinjaTrader / TradingView, addons none, as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `challenge` (evaluation, start 25000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_max_loss_limit` | `trailing_drawdown` | `amount_usd=1000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Pro Challenge? |
| `challenge_contract_limit` | `max_contracts` | `limit=2`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What are the contract limits in the Rapid Pro Challenge? |
| `challenge_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `challenge_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Pass conditions:

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_profit_target` | `profit_target` | `amount_usd=1500`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False` | `assumption` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What are the available account sizes in the Rapid Pro Challenge? |

Fees (attempt cost accounting, never in the ledger):

- `challenge_entry_fee`: evaluation 125.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge
- `challenge_reset_fee`: reset 72.99 USD `when=on_reset` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge

#### phase `fundednext_account` (funded, start 25000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=1000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Pro FundedNext Account? |
| `funded_contract_limit` | `max_contracts` | `limit=2`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What are the contract limits on the Rapid Pro FundedNext Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_consistency` | `consistency` | `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=since_last_payout`, `comparison=<=`, `action=block_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Is there a Consistency Rule on the Rapid Pro FundedNext Account? |
| `funded_performance_reward` | `payout` | `min_days_since_last=3`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=0`, `split=0.90`, `min_usd=250`, `max_usd=600`, `max_usd_by_payout=[600, 600, 600, 850, 850]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §How much can I withdraw, and how often, from the Rapid Pro FundedNext Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

#### conflicts (both sources)

- `mll_lock_point_challenge` on `challenge_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Pro Challenge?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 24100}` from <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §Important notes -> scenario `mll_lock_point_challenge#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($25,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $25,100, which would freeze the floor at $24,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.
- `mll_lock_point_funded` on `funded_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Pro FundedNext Account?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 24100}` from <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Important notes -> scenario `mll_lock_point_funded#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($25,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $25,100, which would freeze the floor at $24,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.

#### assumptions

- `challenge_profit_target`: `unspecified_target_frequency_is_eod` — The profit target is quoted on closed-position P&L, but no page says when it is tested. The intraday default belongs to failure thresholds, where it makes enforcement stricter; for a pass condition the conservative reading is the end of the trade date on the closed balance, because the trader then passes no earlier than the close and a later same-day breach still counts against the attempt. The same silence covers require_flat, which stays false because the target is defined on closed positions.

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Micro-Scalping policy for the Rapid Pro FundedNext Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §How do I request my Performance Reward?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `challenge_max_loss_limit` (challenge): `amount_usd=1000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}`
- [ ] `challenge_contract_limit` (challenge): `limit=2`, `comparison=<=`, `action=clip`
- [ ] `challenge_flat_by` (challenge): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `challenge_inactivity` (challenge): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`
- [ ] `challenge_profit_target` (challenge): `amount_usd=1500`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False`
- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=1000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=2`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_consistency` (fundednext_account): `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=since_last_payout`, `comparison=<=`, `action=block_payout`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=3`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=0`, `split=0.90`, `min_usd=250`, `max_usd=600`, `max_usd_by_payout=[600, 600, 600, 850, 850]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged`

fees and commissions:

- [ ] `challenge_entry_fee` (challenge): `fee_kind=evaluation`, `amount_usd=125.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] `challenge_reset_fee` (challenge): `fee_kind=reset`, `amount_usd=72.99`, `when=on_reset`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `challenge_compliance_copy_and_group_trading` (challenge): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `challenge_compliance_account_sharing` (challenge): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

assumptions:

- [ ] `challenge_profit_target`: `unspecified_target_frequency_is_eod`

conflicts:

- [ ] `mll_lock_point_challenge`: {on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 24100}
- [ ] `mll_lock_point_funded`: {on: [hwm], at_offset_usd: 1100, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 24100}

### `fundednext-futures-rapidpro-50k-dlladdon`

- account: 50000 USD (50K), program `Futures Rapid Pro + DLL add-on`, platform Tradovate / NinjaTrader / TradingView, addons ['daily_loss_limit'], as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `challenge` (evaluation, start 50000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_daily_loss` | `daily_loss` | `amount_usd=1000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §Is there a daily loss limit in the Rapid Pro Challenge? |
| `challenge_max_loss_limit` | `trailing_drawdown` | `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Pro Challenge? |
| `challenge_contract_limit` | `max_contracts` | `limit=4`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What are the contract limits in the Rapid Pro Challenge? |
| `challenge_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `challenge_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Pass conditions:

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_profit_target` | `profit_target` | `amount_usd=3000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False` | `assumption` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What are the available account sizes in the Rapid Pro Challenge? |

Fees (attempt cost accounting, never in the ledger):

- `challenge_entry_fee`: evaluation 259.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge
- `challenge_reset_fee`: reset 132.99 USD `when=on_reset` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge

#### phase `fundednext_account` (funded, start 50000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Pro FundedNext Account? |
| `funded_daily_loss` | `daily_loss` | `amount_usd=1000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Is there a daily loss limit on the Rapid Pro FundedNext Account? |
| `funded_contract_limit` | `max_contracts` | `limit=4`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What are the contract limits on the Rapid Pro FundedNext Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_consistency` | `consistency` | `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=since_last_payout`, `comparison=<=`, `action=block_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Is there a Consistency Rule on the Rapid Pro FundedNext Account? |
| `funded_performance_reward` | `payout` | `min_days_since_last=3`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=0`, `split=0.90`, `min_usd=250`, `max_usd=1000`, `max_usd_by_payout=[1000, 1000, 1000, 1250, 1250]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §How much can I withdraw, and how often, from the Rapid Pro FundedNext Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

#### conflicts (both sources)

- `mll_lock_point_challenge` on `challenge_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Pro Challenge?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48100}` from <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §Important notes -> scenario `mll_lock_point_challenge#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($50,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $50,100, which would freeze the floor at $48,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.
- `mll_lock_point_funded` on `funded_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Pro FundedNext Account?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48100}` from <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Important notes -> scenario `mll_lock_point_funded#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($50,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $50,100, which would freeze the floor at $48,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.

#### assumptions

- `challenge_profit_target`: `unspecified_target_frequency_is_eod` — The profit target is quoted on closed-position P&L, but no page says when it is tested. The intraday default belongs to failure thresholds, where it makes enforcement stricter; for a pass condition the conservative reading is the end of the trade date on the closed balance, because the trader then passes no earlier than the close and a later same-day breach still counts against the attempt. The same silence covers require_flat, which stays false because the target is defined on closed positions.

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Micro-Scalping policy for the Rapid Pro FundedNext Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §How do I request my Performance Reward?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `challenge_daily_loss` (challenge): `amount_usd=1000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `challenge_max_loss_limit` (challenge): `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}`
- [ ] `challenge_contract_limit` (challenge): `limit=4`, `comparison=<=`, `action=clip`
- [ ] `challenge_flat_by` (challenge): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `challenge_inactivity` (challenge): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`
- [ ] `challenge_profit_target` (challenge): `amount_usd=3000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False`
- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}`
- [ ] `funded_daily_loss` (fundednext_account): `amount_usd=1000`, `reference=day_start_balance`, `basis=equity`, `evaluated=intraday`, `comparison=<=`, `action=soft_lock_until_reset`, `reset={time: 17:00:00, tz: America/Chicago}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=4`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_consistency` (fundednext_account): `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=since_last_payout`, `comparison=<=`, `action=block_payout`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=3`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=0`, `split=0.90`, `min_usd=250`, `max_usd=1000`, `max_usd_by_payout=[1000, 1000, 1000, 1250, 1250]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged`

fees and commissions:

- [ ] `challenge_entry_fee` (challenge): `fee_kind=evaluation`, `amount_usd=259.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] `challenge_reset_fee` (challenge): `fee_kind=reset`, `amount_usd=132.99`, `when=on_reset`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `challenge_compliance_copy_and_group_trading` (challenge): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `challenge_compliance_account_sharing` (challenge): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

assumptions:

- [ ] `challenge_profit_target`: `unspecified_target_frequency_is_eod`

conflicts:

- [ ] `mll_lock_point_challenge`: {on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48100}
- [ ] `mll_lock_point_funded`: {on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48100}

### `fundednext-futures-rapidpro-50k`

- account: 50000 USD (50K), program `Futures Rapid Pro`, platform Tradovate / NinjaTrader / TradingView, addons none, as_of 2026-11-22, effective_from 2026-11-22.
- instruments: ES (weight 1), NQ (weight 1), MES (weight 0.1), MNQ (weight 0.1).
- commissions: status `known`, `includes_exchange_and_regulatory_fees: true`; NQ 2.88 USD per side; not published: ES, MES, MNQ (see section 5).
- reset clock (rule-day boundary): 17:00:00 America/Chicago.

#### phase `challenge` (evaluation, start 50000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_max_loss_limit` | `trailing_drawdown` | `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Pro Challenge? |
| `challenge_contract_limit` | `max_contracts` | `limit=4`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What are the contract limits in the Rapid Pro Challenge? |
| `challenge_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `challenge_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `challenge_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

Pass conditions:

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `challenge_profit_target` | `profit_target` | `amount_usd=3000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False` | `assumption` | <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What are the available account sizes in the Rapid Pro Challenge? |

Fees (attempt cost accounting, never in the ledger):

- `challenge_entry_fee`: evaluation 299.99 USD `when=at_start` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge
- `challenge_reset_fee`: reset 172.99 USD `when=on_reset` — <https://helpfutures.fundednext.com/en/articles/17228852-what-are-the-reset-conditions-and-fees-at-fundednext-futures> §Reset Fees for FundedNext Futures Challenge

#### phase `fundednext_account` (funded, start 50000 USD)

| rule | kind | values | evidence | source |
|---|---|---|---|---|
| `funded_max_loss_limit` | `trailing_drawdown` | `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}` | `conflict_resolution` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Pro FundedNext Account? |
| `funded_contract_limit` | `max_contracts` | `limit=4`, `comparison=<=`, `action=clip` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What are the contract limits on the Rapid Pro FundedNext Account? |
| `funded_flat_by` | `flat_by` | `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate` | `official_quote` | <https://fundednext.com/general-rules/futures/trading-platforms> §2 Market Hours |
| `funded_consistency` | `consistency` | `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=since_last_payout`, `comparison=<=`, `action=block_payout` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Is there a Consistency Rule on the Rapid Pro FundedNext Account? |
| `funded_performance_reward` | `payout` | `min_days_since_last=3`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=0`, `split=0.90`, `min_usd=250`, `max_usd=1000`, `max_usd_by_payout=[1000, 1000, 1000, 1250, 1250]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §How much can I withdraw, and how often, from the Rapid Pro FundedNext Account? |
| `funded_compliance_copy_and_group_trading` | `compliance` | `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_compliance_account_sharing` | `compliance` | `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block` | `official_quote` | <https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies |
| `funded_inactivity` | `inactivity` | `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail` | `official_quote` | <https://helpfutures.fundednext.com/en/articles/17228935-is-there-any-inactivity-period-in-fundednext-futures> §How is the inactivity counted? |

#### conflicts (both sources)

- `mll_lock_point_challenge` on `challenge_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §What is the Maximum Loss Limit in the Rapid Pro Challenge?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48100}` from <https://helpfutures.fundednext.com/en/articles/17229677-fundednext-futures-rapid-pro-challenge-all-rules> §Important notes -> scenario `mll_lock_point_challenge#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($50,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $50,100, which would freeze the floor at $48,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.
- `mll_lock_point_funded` on `funded_max_loss_limit` field `lock`: SELECTED `{on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}` from <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Maximum Loss Limit on the Rapid Pro FundedNext Account?
  - alternative `#0` `{on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48100}` from <https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Important notes -> scenario `mll_lock_point_funded#0`
  - why: The table column 'MLL Locks At' gives the level the Maximum Loss Limit freezes at ($50,100), which is the reading the firm-wide loss-limit article states (it locks at the initial balance plus $100) and the one the first-withdrawal reset repeats; the same page's note says the lock happens when the BALANCE reaches $50,100, which would freeze the floor at $48,100. Both passages cover the same firm, plan, size and phase, so they are a genuine conflict; the higher, trader-restrictive floor is selected and the other reading is a sensitivity scenario.
  - the rule as declared carries `evidence=conflict_resolution`; sensitivity scenarios are generated by `crucible.prop.scenarios` and reported beside the primary, never as a plan.

#### assumptions

- `challenge_profit_target`: `unspecified_target_frequency_is_eod` — The profit target is quoted on closed-position P&L, but no page says when it is tested. The intraday default belongs to failure thresholds, where it makes enforcement stricter; for a pass condition the conservative reading is the end of the trade date on the closed balance, because the trader then passes no earlier than the close and a later same-day breach still counts against the attempt. The same silence covers require_flat, which stays false because the target is defined on closed positions.

#### not_modeled by materiality

MATERIAL:

- `cme_price_limit_2pct_entry_ban` — No new position may be opened within 2% of the CME daily price limit; there is no entry-distance rule kind and the ruleset carries no price-limit series, so an entry in that band is filled here. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `commission_table_not_published_per_root` — The firm publishes one all-in rate as an example (NQ, 2.88 USD per side) and defers every other instrument to each platform's own pricing page, so ES, MES and MNQ have no known per-side commission and the firm's platform list (Tradovate, NinjaTrader, TradingView) is not separated into per-platform tables. A run on an unpublished root has no known commission: its cost-dependent statistics stay unavailable unless a named cost assumption is supplied. [<https://helpfutures.fundednext.com/en/articles/17230203-how-do-commissions-work-in-futures-trading> §What makes up the all-in rate?]
- `cross_account_hedging` — Reverse hedges between accounts and hedging across highly correlated instruments are prohibited in both phases. A single simulated account cannot show a cross-account or a correlated hedge, and no rule kind screens for one, so a hedged strategy is reported as practically eligible when the firm would refuse it. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `prohibited_strategy_clauses` — Exploiting platform errors, account rolling and flipping, multi-order spam, slow-feed or latency advantage, spoofing, order-book layering, bracket, grid and wash strategies and trading gapped or illiquid markets are prohibited in both phases. These clauses are qualitative; a single simulated account cannot be screened for them, so a strategy that uses one is still reported as practically eligible. [<https://fundednext.com/general-rules/futures/what-is-forbidden> §1 Prohibited Strategies]
- `sub_minute_holding_and_micro_scalping` — Trades closed within 10 seconds are measured as a share of the cycle's recorded profit: 30% draws a warning, and at 40% a Challenge holds advancement while a funded account deducts that share of the profit. No rule kind measures a trade's holding time, so a sub-minute strategy is neither held nor deducted here and can pass that the firm would penalise. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §What is the Micro-Scalping policy for the Rapid Pro FundedNext Account?]

IMMATERIAL:

- `excess_contract_penalty` — Above the contract limit only the excess contracts are violations: their profit is deducted while their losses still count; max_contracts clips the order at admission instead, which keeps the excess contracts out of the book entirely. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §Contract limits]
- `reward_request_same_day_trade_rule` — A trade placed on the same day removes the transfer-to-wallet option for that day, so a request must be made on a day with no new trade; the payout rule evaluates at every rule-day close regardless of that day's trading, so a payout can be taken a day earlier than the firm would allow. [<https://helpfutures.fundednext.com/en/articles/17229713-fundednext-futures-rapid-pro-fundednext-account-all-rules> §How do I request my Performance Reward?]

#### OWNER REVIEW CHECKLIST

account and thresholds:

- [ ] `challenge_max_loss_limit` (challenge): `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}`
- [ ] `challenge_contract_limit` (challenge): `limit=4`, `comparison=<=`, `action=clip`
- [ ] `challenge_flat_by` (challenge): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `challenge_inactivity` (challenge): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`
- [ ] `challenge_profit_target` (challenge): `amount_usd=3000`, `basis=balance`, `evaluated=eod`, `comparison=>=`, `action=promote_phase`, `require_flat=False`
- [ ] `funded_max_loss_limit` (fundednext_account): `amount_usd=2000`, `mode=eod`, `evaluated=intraday`, `basis=equity`, `hwm_basis=balance`, `comparison=<=`, `action=fail`, `lock={on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100}`
- [ ] `funded_contract_limit` (fundednext_account): `limit=4`, `comparison=<=`, `action=clip`
- [ ] `funded_flat_by` (fundednext_account): `time=15:10:00`, `tz=America/Chicago`, `reopen=17:00:00`, `comparison=>=`, `action=auto_liquidate`
- [ ] `funded_consistency` (fundednext_account): `max_day_share=0.4`, `measure=best_day_profit/total_profit`, `applies_to=payout`, `window=since_last_payout`, `comparison=<=`, `action=block_payout`
- [ ] `funded_inactivity` (fundednext_account): `max_gap=30`, `unit=calendar_days`, `rolling_window=True`, `observed=eod`, `comparison=>=`, `action=fail`

payouts:

- [ ] `funded_performance_reward` (fundednext_account): `min_days_since_last=3`, `min_profitable_days=0`, `min_traded_days=0`, `min_day_profit_usd=0`, `window=since_last_payout`, `buffer_usd=0`, `split=0.90`, `min_usd=250`, `max_usd=1000`, `max_usd_by_payout=[1000, 1000, 1000, 1250, 1250]`, `min_profit_since_last_usd=500`, `max_payouts=5`, `comparison=>=`, `action=withdraw`, `threshold_after_payout=unchanged`

fees and commissions:

- [ ] `challenge_entry_fee` (challenge): `fee_kind=evaluation`, `amount_usd=299.99`, `when=at_start`, `comparison=>=`, `action=charge`
- [ ] `challenge_reset_fee` (challenge): `fee_kind=reset`, `amount_usd=172.99`, `when=on_reset`, `comparison=>=`, `action=charge`
- [ ] commissions: NQ 2.88 per side, all-in (includes_exchange_and_regulatory_fees: true) — confirm before any cost-dependent statistic is reported

news, compliance and conduct:

- [ ] `challenge_compliance_copy_and_group_trading` (challenge): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `challenge_compliance_account_sharing` (challenge): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_copy_and_group_trading` (fundednext_account): `restriction=copy_and_group_trading`, `applies_to_execution=[automated, manual]`, `materiality=material`, `comparison=>=`, `action=block`
- [ ] `funded_compliance_account_sharing` (fundednext_account): `restriction=account_sharing`, `applies_to_execution=[automated, manual]`, `materiality=immaterial`, `comparison=>=`, `action=block`
- [ ] unmodeled rules to accept or reject: `cme_price_limit_2pct_entry_ban`, `commission_table_not_published_per_root`, `cross_account_hedging`, `prohibited_strategy_clauses`, `sub_minute_holding_and_micro_scalping`

assumptions:

- [ ] `challenge_profit_target`: `unspecified_target_frequency_is_eod`

conflicts:

- [ ] `mll_lock_point_challenge`: {on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48100}
- [ ] `mll_lock_point_funded`: {on: [hwm], at_offset_usd: 2100, locked_offset_usd: 100} selected over {on: [hwm], at_offset_usd: 100, locked_threshold_usd: 48100}
