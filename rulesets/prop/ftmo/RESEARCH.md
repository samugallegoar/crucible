# FTMO Futures - ruleset research (six rulesets, schema version 2)

- Firm slug: `ftmo`. Files: `rulesets/prop/ftmo/ftmo-futures-{growth,pro}-{50k,100k,150k}.v1.yaml`,
  version 1 each, **schema version 2** (ADR-0107 section 7). The version number stays 1 because
  these drafts were never committed; the migration rewrote them in place, and so did the round-2
  update described below.
- Firm, program, size: FTMO, Futures Growth and Futures Pro, 50K / 100K / 150K. Six rulesets, which
  is every product x size FTMO Futures sells today.
- `verification.status: unverified` on all six. Only the owner can confirm a ruleset, from a TTY,
  with `crucible prop confirm` (ADR-0107 section 2). No result computed from these files may be
  presented as confirmed firm rules.
- Retrieval: 2026-11-22 (UTC), official public pages only, no login, no form, no purchase. This
  update re-read the same snapshots; **no page was fetched again** and no snapshot changed.
- Raw snapshots: `D:/proyectos/crucible-notes/internal/prop_snapshots/ftmo/` (the fetched bytes; the
  `sha256` quoted everywhere below is the hash of those bytes, and every attribution in every
  ruleset carries it).
- Quote normalisation (what the self-check does, and what the spaces before punctuation below are):
  UTF-8 decode, drop `<script>/<style>/<noscript>/<svg>`, replace every tag with one space,
  unescape HTML entities, collapse whitespace. `Amount .` is the page's own `<strong>` boundary,
  not a typo.
- Self-check commands (both pass on all six files; see section 15):
  - `uv run crucible prop validate <file> --json` per file;
  - a quote/hash self-check that normalises each snapshot, asserts each rule's `quote` occurs in it
    verbatim and asserts the `sha256` of that snapshot file (165 attributions over the six files,
    0 failures).

## Round 2 changes (the C7b vocabulary update, 2026-11-22)

Round 2 (ADR-0107 sections 7-13: the nine additions in the schema docstring, plus the session
coverage gaps and the exchange-fee table) changed these six files as follows. Every file now
validates; each file's `ruleset_sha256` changed, and the hashes in section 11 are the new ones.

| Round-2 addition | Applied? | What changed, and why |
|---|---|---|
| `commissions.includes_exchange_and_regulatory_fees` (now REQUIRED) | **yes: `false`** | FTMO states the total cost is three parts (exchange fees, NFA fees, "Our commission"), so its own $0.50/$0.20 per side is **not** all-in. The commissions source quote now spans the amounts *and* the exclusion sentence. The material `not_modeled:exchange_and_nfa_fees_not_published` entry was **removed**: the declaration carries it, and the engine now adds the fees from an `ExchangeFeeSource` or reports `exchange fees unknown: ...` and leaves the cash statistic `unavailable`. Section 5. |
| `payout.max_usd` (and `max_usd_by_payout`) accepting `unknown` | **no** | every Sim-Funded payout cap is printed per size ($2,500 / $3,000 / $4,000 Growth, $5,000 / $6,000 / $8,000 Pro). No cap on these six files is `unknown`, none is `unlimited`, and no sentinel number is used (`PropRuleset._refuse_numeric_sentinels` would refuse one). |
| `trailing_drawdown.lock.on` as a LIST | **yes: `[hwm]`** | shape only. The lock still fires on the high-water mark at `at_offset_usd` = the drawdown amount and freezes the threshold at the initial capital (`locked_offset_usd: '0'`), which is the page's "locks permanently at that figure" wording. No second trigger fits FTMO: nothing says a payout moves the limit. |
| `payout.threshold_after_payout: set_threshold` + `set_threshold_to` | **no** | the funded trailing drawdown is unchanged by a payout (`threshold_after_payout: unchanged`), and no page states a post-payout level. The Live Funded "Safety Net" (a buffer cleared once, then daily uncapped payouts) belongs to a stage that stays `not_modeled`. |
| `news_restriction.effect: block\|contract_cap` (now REQUIRED on that kind) | **no rule exists** | FTMO forbids no news trading: "News trading is allowed with FTMO Futures during any phase, with no special news restrictions". There is no `news_restriction` rule on any of the six files, so there is no effect to declare; inventing a window would be a rule the firm does not have. Section 6. |
| calendar event types `PPI`, `FOMC_PRESS_CONFERENCE`, `FOMC_MINUTES` | **no effect** | no rule reads the economic calendar (above). The only news-adjacent rule is the discretionary `news_event_concentration`, which names no event type, window or instrument, so the new calendar coverage does not model it. |
| `activity_requirement` (N qualifying days per rolling window) | **no** | FTMO has no minimum-trading-days objective in the evaluation and no rolling-window activity rule. The payout gate ("Minimum number of Qualifying Days: 4 trading days, $150+ per Qualifying Day", per payout cycle) is a payout term and stays on `funded_payout` (`window: since_last_payout`, `min_profitable_days`, `min_day_profit_usd`). The only activity rule FTMO has is `inactivity` (60 consecutive calendar days). |
| `payout.min_new_profit_share_of_request` | **yes: `'0.5'`** | "at least 50% of the requested amount must represent new profit generated during the current payout cycle" is exactly this field, so the material `not_modeled:min_new_profit_50_pct_of_request` entry was **removed**. A request is now also bounded by twice the new profit since the previous payout. Section 8. |
| `consistency` with separate `numerator_window` / `denominator_window` | **no** | FTMO defines both sides over the whole Evaluation: "The total profit is the cumulative sum of closed profits and losses across all trading days in the Evaluation phase. The Best Day is defined as the single day on which the highest closed profit was achieved, measured at the end of the trading day." `window: all_time` already means both, so no separate window is declared. |
| conflict alternative `absent` | **no** | no genuine conflict exists on FTMO (section 9), so `conflicts: []` and `scenarios()` returns only `primary`; there is no reading in which one of these rules does not exist. |
| `flat_by.minutes_before_session_end` (session-relative close) | **yes: 50** | both `flat_by` rules (`eval_flat_by`, `funded_flat_by`) moved from an absolute `time: '16:10:00'` + `tz` + `reopen` to `minutes_before_session_end: 50`. 4:10 pm ET is fifty minutes before the 5:00 pm ET / 4:00 pm CT close of a regular CME equity-index session, so on every regular session the instant is identical, and on a holiday early close it now follows the calendar instead of a fixed clock. Section 4 and section 13. |

Nothing else moved: the matrix, every threshold, every fee, the not-modeled set (except the two
entries listed above), the compliance rules and the verification status are unchanged.

## 1. Evidence, and the defaults this firm did and did not need

Every rule is `evidence: official_quote`: 16 rules on each Growth file and 17 on each Pro file (Pro
carries the evaluation `daily_loss` rule), plus the `commissions` block and the ten `not_modeled`
entries, which is 27 attributions on a Growth file and 28 on a Pro file. **No `assumption` block is
needed on any of the six files**, and no `conflict_resolution` either (section 9). The reason is
that FTMO states, on the page, each thing the ADR-0107 section 7 defaults exist to cover:

| Default (ADR-0107 section 7) | What FTMO states instead | Where |
|---|---|---|
| "EST" means `America/New_York` with DST | "US Eastern Time (ET)", and the trading day is defined 6:00 p.m. ET - 4:10 p.m. ET, so the reset clock is `18:00 America/New_York` | TOR "trading day" definition, instruments FAQ "trading hours" |
| an unspecified frequency means intraday (and a profit target is tested at the end of day) | every threshold names its frequency: "equity ... cannot hit at any point" (max drawdown, daily loss, and "If the equity hits this limit"), "end-of-day trailing limit" (the mark), "each time your end-of-day (EOD) Profit ... reaches a defined threshold" (scaling), and "Accounts are assessed for eligibility to pass after the end of the trading day" (the target: `evaluated: eod`) | TOR panels |
| a profit target is tested on closed balance | "once your account balance exceeds the Initial Simulated Capital by the required Profit Target, with all positions closed" | TOR profit-target panel |
| a trading day is a trade date with at least one executed trade | the firm defines the trading day itself (6:00 p.m. ET - 4:10 p.m. ET) and measures qualifying days on "the end-of-day P&L of Day 3 ... in the closed P&L" | TOR panels |

Engine-level declarations that are not firm semantics and are not evidence of anything FTMO says:

- `comparison` and `action` on the contract rules are `clip`, the admission policy of
  `PropAccountOverlay` (the alternative, `reject`, would throw the run's target away instead of
  sizing it down);
- `observed: eod` on `funded_inactivity`, because a gap in trading activity can only be counted once
  a trading day has ended (the count is identical whether it is checked intrabar or at the close);
- `minutes_before_session_end: 50` on both `flat_by` rules. This is the only value in the six files
  that is arithmetic over a calendar fact rather than a number printed on a page: the firm's own
  clock is 4:10 pm ET, the CME equity-index session closes at 5:00 pm ET (4:00 pm CT) on a regular
  day, and the difference is fifty minutes. On a regular session the flat instant is exactly 16:10
  ET; on a holiday early close the model flattens fifty minutes before the early close, which is
  inside the firm's own "4:10 p.m. ET or the relevant market close, whichever is sooner" deadline,
  i.e. on the conservative side. Each rule's `description` states this.

Each of those three is stated in the affected rule's `description`.

Day units are explicit wherever a unit exists: `funded_inactivity.unit: calendar_days` ("30
consecutive calendar days"), `time_limit` unused (there is none). No value is `unlimited` except
where a page says so - and on these six files nothing is unlimited and nothing is `unknown`: the
Live Funded payout cap ("There is no Payout Cap on the Live Funded Account .") belongs to an
account that is `not_modeled`, and every Sim-Funded cap is printed. No numeric sentinel is used
anywhere; a 1,000,000 cap would be refused by `PropRuleset._refuse_numeric_sentinels`.

## 2. Snapshots (all of them, with what was used)

| snapshot | sha256 | retrieved_at | what it is used for |
|---|---|---|---|
| `20261122_ftmo_futures_tor.html` | `d18fbddf728f67093605e9b0651c640447417038831ce759732c8e299abddcc2` | 2026-11-22T01:35:35Z | the rule book: six hidden per-size panels (`data-futures-trading-objectives-value="growth_50\|growth_100\|growth_150\|pro_50\|pro_100\|pro_150"`), every per-size value below, the consistency definition, the scaling list and the min-new-profit sentence |
| `20261122_ftmo_futures_comparison.html` | `ad69df2d79097741320acd99105886ce1005825f74980c1cdb563cd01d99b7fc` | 2026-11-22T01:35:36Z (saved) | cross-check of every value in section 4 (side-by-side Growth/Pro table) |
| `20261122_ftmo_futures_howitworks.html` | `8e3659d8587843006b15d0eda1599339fa8e3e97fbb65dea7fc3c6cdcf9521e8` | 2026-11-22T01:35:37Z | payout cadence ("every 5 days on Pro, every 4 on Growth"), the Live Funded description and its market data fee |
| `20261122_ftmo_futures.html` | `45bdde355c46ed8c548d043e4018eac8889f84d71bc6aa1bab4c886eef321d5c` | 2026-11-22T01:35:00Z (saved) | the Growth/Pro cards: "No Intraday Trailing", "Payout ratio 90%", "News trading allowed", "No activation fee", "No consistency rule on Sim-Funded" |
| `20261122_ftmo_futures_forbidden.html` | `de1eb1d68e84f734a53caf23cf673043e869213c0adf5b6eb3a15bc5038dd39b` | 2026-11-22T01:35:38Z | the three `compliance` rules, the inactivity rule and eight of the ten `not_modeled` entries |
| `20261122_ftmo_faq_instruments.html` | `e96ed87290cc5aff5cbc2bf2bb4af0c5bd5ec3028b4b09d02f8c5346c6d716a8` | 2026-11-22T01:37:40Z | the trading-day close/reopen (evaluation `flat_by`), the instrument lists (the nine roots), **the commission and the fact that it excludes the exchange and NFA fees** |
| `20261122_ftmo_faq_overnight.html` | `965825eb9b123a6de03877be02464dc148349d0955b389b2a07dea7cac34b606` | 2026-11-22T01:37:43Z | the close of the Sim-Funded session and its "or the relevant market close, whichever is sooner" wording (funded `flat_by`) |
| `20261122_ftmo_faq_news.html` | `43b3aaea7d716cb8bbae1054fe9460cd4f4a42a678f850f9e98bfcf9c5cd6177` | 2026-11-22T01:37:42Z (saved) | "News trading is allowed ... with no special news restrictions" (section 6) |
| `20261122_ftmo_faq_platforms.html` | `2b1e9fcd9742ab2149cf2572127bd7692d3a10943493f829daa0b8018d6dfea9` | 2026-11-22T01:37:44Z | the three platforms, available "in all phases" |
| `20261122_ftmo_faq_account_specs.html` | `c99d5be41884658781ba12eefee47433089b92f6786113b1e9a1c1d7066f89df` | 2026-11-22T01:37:46Z | the sizes (50K/100K/150K) and the USD denomination |
| `20261122_ftmo_faq.html` | `68358f06bdb102fa7d41e2b98d5b4cb1cfaf340ae654456e0cca5e52b543131a` | 2026-11-22T01:35:01Z (saved) | FAQ index only; nothing was taken from it |
| `20261122_ftmo_faq_instruments_strategies.html` | `7a7c7fb640be0c5fa76be943748a2f0e38ed313765f67e8e7796f3accff03a9b` | 2026-11-22T01:37:41Z (saved) | allowed strategies (already covered by the forbidden page); nothing new was taken |
| `20261122_ftmo_instruments.html` | `d17a07f35ffbdfc66429861c067ca5c4fd85ddd836d08e377bd7a7a43b81b8af` | 2026-11-22T01:37:24Z (saved) | the site's **404 page** (`https://ftmo.com/en/instruments/`); nothing was taken from it |
| `20261122_ftmo_platforms.html` | `d8c339707975f5d242af7239bbc07267fb4bfeda0089de804382f0380f6630ba` | 2026-11-22T01:37:25Z (saved) | superseded by the platforms FAQ; nothing was taken from it |

`retrieved_at` in the table is the instant recorded in each rule's attribution where a page
carries one; the `(saved)` rows have no attribution (they are cross-check pages) and show when
the bytes were saved instead.

Pages used (all HTTP 200 and readable as raw bytes; the Trading Objectives panels are
server-rendered, so no JS execution or JSON API was needed):

- `https://ftmo.com/en/futures/trading-objectives-and-rules/`
- `https://ftmo.com/en/futures/comparison-table/`
- `https://ftmo.com/en/futures/how-it-works/`
- `https://ftmo.com/en/futures/`
- `https://ftmo.com/en/futures/forbidden-trading-practices/`
- `https://ftmo.com/en/futures/faq/which-instruments-can-i-trade-with-ftmo-futures`
- `https://ftmo.com/en/futures/faq/ftr-can-i-hold-positions-overnight-or-over-the-weekend`
- `https://ftmo.com/en/futures/faq/ftr-can-i-trade-news`
- `https://ftmo.com/en/futures/faq/ftr-which-platforms-can-i-use-for-trading`
- `https://ftmo.com/en/futures/faq/ftr-what-are-the-account-specifications`

## 3. Why six rulesets and not more

Growth and Pro differ in thresholds, fees and payout terms, and that is the only product split.
For both products: the same three platforms (NinjaTrader, Tradovate, TradingView), no platform
variant, no add-on, no jurisdiction variant, nothing discontinued. The only remaining variant axis
is the account size, which changes the thresholds, the contract limit, the scaling milestones, the
payout cap, the per-day payout threshold and both fees. So the matrix is 2 x 3 = 6 files, and every
file is a complete variant rather than a patch.

The Live Funded account is a third stage, but it is invitation-only, its per-size capital is not
published ("Initial Capital = $3,000" appears only in a worked example on the 100K panel) and it is
not a phase transition the ruleset can enter. It is `not_modeled` (immaterial) on all six files,
with the market data fee it mentions.

## 4. Product matrix (generated from the six YAML files)

Evaluation phase:

| file | size | target | max drawdown | eval daily loss | max contracts | consistency | monthly fee | reset fee |
|---|---|---|---|---|---|---|---|---|
| `ftmo-futures-growth-50k` | 50K | 3,000 | 2,000 (EOD trail, lock at start) | none | 5 | 40% of total profit | 119 | 109 |
| `ftmo-futures-growth-100k` | 100K | 6,000 | 3,000 (EOD trail, lock at start) | none | 10 | 40% | 169 | 159 |
| `ftmo-futures-growth-150k` | 150K | 9,000 | 4,500 (EOD trail, lock at start) | none | 15 | 40% | 229 | 219 |
| `ftmo-futures-pro-50k` | 50K | 3,000 | 3,000 (EOD trail, lock at start) | 1,000 hard | 5 | 50% | 139 | 129 |
| `ftmo-futures-pro-100k` | 100K | 6,000 | 4,500 (EOD trail, lock at start) | 1,500 hard | 10 | 50% | 199 | 189 |
| `ftmo-futures-pro-150k` | 150K | 9,000 | 6,000 (EOD trail, lock at start) | 2,000 hard | 15 | 50% | 269 | 259 |

Sim-Funded phase:

| file | max drawdown | daily loss | scaling milestones (profit above start -> contracts) | payout gate | payout cap | min new profit | withdrawable share | split / min |
|---|---|---|---|---|---|---|---|---|
| `ftmo-futures-growth-50k` | 2,000 | 1,000 soft | 0->2, 1,000->3, 2,000->5, 3,000->5, 4,500->5 | 4 days of 150+ | 2,500 | 50% of the request | 50% of profit above start | 90/10 / 20 |
| `ftmo-futures-growth-100k` | 3,000 | 2,000 soft | 0->4, 1,000->5, 2,000->8, 3,000->10, 4,500->10 | 4 days of 300+ | 3,000 | 50% | 50% | 90/10 / 20 |
| `ftmo-futures-growth-150k` | 4,500 | 3,000 soft | 0->6, 1,000->8, 2,000->10, 3,000->12, 4,500->15 | 4 days of 450+ | 4,000 | 50% | 50% | 90/10 / 20 |
| `ftmo-futures-pro-50k` | 3,000 | 1,000 hard | 0->2, 1,000->3, 2,000->5, 3,000->5, 4,500->5 | 5 days of 200+ | 5,000 | 50% | 100% | 90/10 / 20 |
| `ftmo-futures-pro-100k` | 4,500 | 1,500 hard | 0->4, 1,000->5, 2,000->8, 3,000->10, 4,500->10 | 5 days of 300+ | 6,000 | 50% | 100% | 90/10 / 20 |
| `ftmo-futures-pro-150k` | 6,000 | 2,000 hard | 0->6, 1,000->8, 2,000->10, 3,000->12, 4,500->15 | 5 days of 500+ | 8,000 | 50% | 100% | 90/10 / 20 |

Every file also carries, in both phases: `flat_by` as `minutes_before_session_end: 50` (16:10 ET on
a regular session, fifty minutes before a holiday early close), the 18:00 ET rule-day reset, no time
limit (there is none), no minimum-trading-days condition (there is none), and - on the Sim-Funded
phase - the inactivity rule (60 consecutive calendar days without trading activity closes the
account). The Sim-Funded phase has no profit target and no consistency rule ("No Profit Target and
no Consistency Rule", how-it-works; "No Consistency Rule", comparison table).

Sim-Funded payouts, precisely: the gate is 4 (Growth) or 5 (Pro) qualifying days inside the current
payout cycle, counted since the previous payout, each with a closed P&L of at least 150/200/300/450/
500 USD by size and product; at most one request per 4 (Growth) or 5 (Pro) trading days
(`min_days_since_last`); the request is the smallest of the cap, 50% (Growth) or 100% (Pro) of the
profit above the initial capital, and `min_new_profit_share_of_request` = 0.5 applied to the new
profit since the last payout; it is paid 90/10 with a 20 USD minimum.

Max drawdown, precisely as the TOR panels define it: the high-water mark is the highest **closing
balance** of any preceding trading day (or the initial capital if higher), the limit is
`hwm - amount`, it "can only increase, never decrease", it is tested against **equity** at any point
in the day, and it "locks permanently at the Initial Simulated Capital" once it reaches it. That is
`trailing_drawdown` with `mode: eod`, `hwm_basis: balance`, `basis: equity`, `evaluated: intraday`
and `lock: {on: [hwm], at_offset_usd: <amount>, locked_offset_usd: '0'}` (`on` is a list in schema
version 2; the list has one trigger because FTMO names one).

## 5. Commissions and fees (ADR-0107 section 10)

**Commissions.** The instrument FAQ answers "How much does it cost to trade? What are the
commissions and fees?":

> "The total trading cost per contract is made up of three parts: Exchange fees NFA fees Our
> commission - $0.50 per side for minis and $0.20 per side for micros Exchange and NFA fees are set
> by the exchanges and regulators, not by FTMO."

- snapshot `20261122_ftmo_faq_instruments.html`,
  sha256 `e96ed87290cc5aff5cbc2bf2bb4af0c5bd5ec3028b4b09d02f8c5346c6d716a8`,
  `https://ftmo.com/en/futures/faq/which-instruments-can-i-trade-with-ftmo-futures`,
  section "How much does it cost to trade? What are the commissions and fees?".
- `commissions.status: known`, `platform: null` (FTMO's commission is the firm's own and does not
  differ by platform; NinjaTrader, Tradovate and TradingView are the three platforms, all phases):
  ES 0.50, NQ 0.50, YM 0.50, RTY 0.50, NKD 0.50, MES 0.20, MNQ 0.20, MYM 0.20, M2K 0.20 USD per side.
  Minis and micros are the only split FTMO publishes; there is no per-root table, so every mini
  root carries the mini figure and every micro root the micro figure.
- **`commissions.includes_exchange_and_regulatory_fees: false`, on all six files.** The same answer
  says the total cost has three parts - exchange fees, NFA fees and FTMO's commission - and that
  exchange and NFA fees "are set by the exchanges and regulators, not by FTMO"; it then recommends
  "adding our fixed commission on top". So $0.50/$0.20 per side is the firm's own commission and
  **excludes** the exchange fee and the NFA assessment. The ruleset's `quote` is one contiguous run
  of that answer (it starts at "$0.50 per side" and ends at "not by FTMO."), so a single
  attribution supports both the amounts and the exclusion; the three-part sentence immediately before
  it is the page's own wording for the same fact.
- What happens at attempt time: with the flag `false` the engine adds the per-side amount of the run's
  `ExchangeFeeSource` (an `ExchangeFeeTable`, or the stored `exchange_fees_v1` dataset through
  `store_exchange_fees`) to each fill's commission. The stored dataset today holds **no exchange
  rows** (the NFA rows only, `docs/data/cme-exchange-fees.md`), so `fee_table_as_of` refuses, the
  attempt reports `exchange fees unknown: ...`, and the cash statistic is **unavailable** rather
  than too low. That is why the old `not_modeled:exchange_and_nfa_fees_not_published` entry is gone:
  the gap is now declared in the right place and reported by name, instead of being a silent
  understatement with a materiality label. An owner-supplied CSV of CME rates is what closes it.

**Fees, modeled as `fee` rules** (attempt cost accounting, never the trading ledger):

| rule | kind | when | Growth 50/100/150 | Pro 50/100/150 | source |
|---|---|---|---|---|---|
| `eval_monthly_subscription` | monthly | `per_month` (per started calendar month) | 119 / 169 / 229 | 139 / 199 / 269 | TOR `subscription-fees-monthly-fee`: "The monthly fee is $119/month ." (the amount varies by size) |
| `eval_reset_fee` | reset | `on_reset` | 109 / 159 / 219 | 129 / 189 / 259 | TOR `subscription-fees-reset-fee`: "The Reset Fee returns your account to its original starting conditions. The Reset Fee is $109 ." |

- "There is no activation fee ." (TOR, `subscription-fees-monthly-fee`; also the overview card
  "No activation fee"), so no activation fee rule exists - an absent fee is not a zero-valued rule.
- The evaluation is a subscription, not a one-off: "Your subscription remains active even if the
  Evaluation Account is breached", and a monthly fee is charged per started calendar month of the
  attempt. A reset does not change the billing cycle ("applying a Reset does not alter your monthly
  billing cycle"), which the model reproduces because `threshold_after_payout`/cycles are separate
  from the `monthly` fee's calendar counting.
- The Live Funded stage has a cost the pages state without an amount ("A market data fee applies for
  access to live market data - we cover one exchange for you"), recorded inside the
  `live_funded_account` `not_modeled` entry (immaterial, that stage is not simulated).

## 6. News rules (ADR-0107 section 12)

FTMO has **no news-trading restriction**:

> "News trading is allowed with FTMO Futures during any phase, with no special news restrictions,
> provided you do not engage in any Forbidden Trading Practices ."

- snapshot `20261122_ftmo_faq_news.html`,
  sha256 `43b3aaea7d716cb8bbae1054fe9460cd4f4a42a678f850f9e98bfcf9c5cd6177`,
  `https://ftmo.com/en/futures/faq/ftr-can-i-trade-news`.
- The overview card agrees: "News trading allowed".
- So **no `news_restriction` rule exists on any of the six files**: there are no event types, no
  pre/post minutes, no restricted instruments, no scope, no flatten behaviour and - in round 2 - no
  `effect` to declare (the kind has no default for it, and a file cannot declare a `block` or a
  `contract_cap` the firm does not have). Inventing a window would be a rule FTMO does not have.
- Nothing needs the economic-event calendar either, so neither the new event types the calendar now
  carries (`PPI`, `FOMC_PRESS_CONFERENCE`, `FOMC_MINUTES`) nor a coverage gap can make these
  rulesets `partial` through news. A news rule added later would have to name its types from
  `docs/data/econ-events.md` (`FOMC_STATEMENT`, `CPI`, `NFP`, `PPI`, `FOMC_PRESS_CONFERENCE`,
  `FOMC_MINUTES`).
- The one news-adjacent rule FTMO does have is **discretionary**, under Risk Management Standards:

  > "Concentrating trading activity around scheduled economic events in a pattern that is
  > inconsistent with your overall approach and would not reflect a sustainable strategy in live
  > market conditions"

  It names no event type, no window and no instrument, and it is an unspecified news rule, so it is
  `not_modeled:news_event_concentration` with **material** materiality rather than an approximated
  window. The same page also forbids inconsistent position sizing next to it, which is a separate
  `not_modeled` entry (also material).

## 7. Compliance rules (execution restrictions)

The forbidden page opens its list with "The practices below are prohibited across all account
stages", and the TOR panel repeats "Certain trading behaviours are prohibited across all FTMO
Futures accounts, regardless of phase or account type". Three `compliance` rules carry that on
every file (they sit in the evaluation phase and gate practical eligibility; they never touch the
mechanical account):

| rule_id | restriction | execution modes | materiality | action |
|---|---|---|---|---|
| `compliance_automated_trading_permitted` | automated systems that manipulate, abuse or give an unfair advantage (HFT, latency arbitrage) | `automated` | immaterial | `none` |
| `compliance_no_copy_or_third_party_trading` | replicating/following a third party's decisions, signal services, trade copiers, third-party access | `automated`, `manual` | material | `block` |
| `compliance_exchange_conduct` | CME-prohibited conduct: spoofing, layering, wash trading, manipulation | `automated`, `manual` | immaterial | `none` |

- `Automated trading is permitted.` (first sentence of Prohibited Practice 5) is the opposite of
  Apex's automation ban: an automated strategy at FTMO is **not** blocked, and
  `practical_eligibility` stays `eligible` for `execution_mode: automated`.
- The copy-trading ban would block a strategy that follows someone else's decisions; it is
  `material`, not `critical`, because a self-contained strategy does not fall under it and marking
  it critical would block every automated attempt for no reason. The rule's `restriction` and
  `description` say exactly that.
- The exchange-conduct rule is `immaterial` and `action: none`: a bar-based simulation of a
  rule-following strategy has no order book to spoof.

## 8. `not_modeled`, by materiality (identical ids on all six files)

**Material (4)** - these weaken every claim to `conditional_on_modeled_rules`:

| id | why it is not modeled | source |
|---|---|---|
| `cme_price_limit_2pct_entry_ban` | no new position within 2% of the CME daily price limit; no entry-distance kind and no price-limit series | Forbidden Practices 6 |
| `discretionary_risk_management_clause` | drawdown-as-sole-exit, overleveraging, one-sided bets, account rolling: a discretionary clause cannot be simulated | Forbidden Practices 2 and 8 |
| `inconsistent_position_sizing` | sizing that differs from the trader's wider activity across accounts; one attempt has no wider activity | Risk Management Standards |
| `news_event_concentration` | the discretionary news rule (section 6) | Risk Management Standards |

**Immaterial (6)** - declared, warned about, but they do not change any simulated outcome:

| id | why it is not modeled | source |
|---|---|---|
| `live_funded_account` | invitation-only third stage; per-size capital not published; own buffer, uncapped daily payouts, market data fee; not a pass transition | how-it-works |
| `hedging_and_netting_across_accounts` | the cross-account hedging rule; one simulated account cannot express netting across accounts, and an opposite position inside one account is not netting | Forbidden Practices 3 |
| `evaluation_vs_funded_mismatch` | trading differently in the evaluation than on a funded account; the simulation applies one strategy to both phases | Risk Management Standards |
| `exploit_simulation_artifacts` | exploiting platform errors or quote delays; the engine simulates neither | Forbidden Practices 1 |
| `hft_and_latency_arbitrage_ban` | a bar-based simulation has no order latency to arbitrage | Forbidden Practices 5 |
| `max_concurrent_accounts_3` | three concurrent Sim-Funded accounts; a per-account attempt is not a portfolio | TOR, Max Concurrent Accounts |

**Removed in round 2 (2 material entries, previously 6 material + 6 immaterial):**

| removed id | what models it now | why it is no longer a gap |
|---|---|---|
| `min_new_profit_50_pct_of_request` | `funded_payout.min_new_profit_share_of_request: '0.5'` | the payout kind now has the new-profit-share gate the page describes ("at least 50% of the requested amount must represent new profit generated during the current payout cycle"), so a request is bounded by twice the new profit since the last payout. No assumption and no approximation: the field is the rule. |
| `exchange_and_nfa_fees_not_published` | `commissions.includes_exchange_and_regulatory_fees: false` + the run's `ExchangeFeeSource` | the commissions block now declares that the per-side amounts exclude the exchange and NFA fees, so the engine adds them or refuses to compute cash. The gap stopped being a silent understatement with a materiality label and became a named, reported one (`exchange fees unknown: ...`, cash `unavailable`). The FTMO sentence and the CME dataset's empty exchange-fee coverage are recorded in section 5 and in `docs/data/cme-exchange-fees.md`. |

Owner-flagged items that FTMO does **not** state, and which are therefore not declared at all:
there is no minimum holding time and no micro-scalping ban anywhere on FTMO's pages (the overview
page even showcases "Trading Style Scalper" testimonials), so no such `not_modeled` entry exists.
Cross-account hedging (Forbidden Practice 3) and the 2% price-limit ban (Practice 6) are declared,
as the owner requires.

## 9. Conflicts: none

**There is no genuine conflict on FTMO**, so `conflicts: []` on all six files and `scenarios()`
returns only `primary`. That is also why no conflict carries an `absent` alternative (a reading in
which the rule does not exist): the two places where an "it does not exist" reading could arise -
the Sim-Funded consistency rule and the news restriction - are **stated as absent by both sources**,
so "does not exist" is the only reading and not an alternative to a selected value. Concretely:

- Sim-Funded consistency: TOR "There is no Profit Target or Consistency Rule on the Sim-Funded
  Account" and "No Consistency Rule" on the comparison table, plus the card "No consistency rule on
  Sim-Funded". No rule is declared, so there is nothing to conflict over.
- News: the FAQ ("with no special news restrictions") and the card ("News trading allowed") agree.

The check below was run per file - the per-size panel is the primary source for every value, so each
file was compared on its own rows - and it is shown once because the cross-check is the same for
Growth and Pro. Every value was compared with a second official source and every pair was checked
for the same firm, plan, account size, phase, platform and effective period:

| value | source A (TOR per-size panel) | source B (comparison table) | verdict |
|---|---|---|---|
| profit target 3,000 / 6,000 / 9,000 (both products) | `evaluation-profit-target` | Profit Target row, per size | agree |
| max drawdown 2,000 / 3,000 / 4,500 (Growth), 3,000 / 4,500 / 6,000 (Pro), both phases | `evaluation-max-drawdown`, `sim-funded-max-drawdown` | Max Drawdown (EoD) rows | agree |
| eval daily loss none (Growth), 1,000 / 1,500 / 2,000 hard (Pro) | `evaluation-daily-loss-limit` | Daily Loss row ("None" / "Hard") | agree |
| funded daily loss 1,000 / 2,000 / 3,000 soft (Growth), 1,000 / 1,500 / 2,000 hard (Pro) | `sim-funded-daily-loss-limit` | Daily Loss row ("Soft"/"Hard") | agree |
| max contracts 5 / 10 / 15 (evaluation) | `evaluation-max-contracts` | Max Contracts row | agree |
| consistency 40% (Growth) / 50% (Pro) | `evaluation-consistency-rule` | Consistency Rule row, plus how-it-works "max 50% of total profit on Pro, 40% on Growth" | agree |
| payout eligibility 4 days (Growth) / 5 days (Pro), per-day 150/300/450 and 200/300/500 | `sim-funded-payout-eligibility` | Payout Eligibility rows ("4 days, $150+ each", ...) plus how-it-works "every 5 days on Pro, every 4 on Growth" | agree |
| min new profit 50% of the request (every size, both products) | `sim-funded-min-new-profit-for-request` | "Min New Profit for Request 50% of requested amount" row | agree |
| payout cap 2,500 / 3,000 / 4,000 (Growth), 5,000 / 6,000 / 8,000 (Pro) | `sim-funded-payout-cap` | Payout Cap row, overview cards ("starting at $2,500", "$5,000 and $8,000") | agree |
| withdrawable 50% (Growth) / 100% (Pro) | `sim-funded-withdrawable-amount` | Withdrawable Amount row | agree |
| monthly and reset fees 119/169/229 + 109/159/219, 139/199/269 + 129/189/259 | `subscription-fees-monthly-fee`, `subscription-fees-reset-fee` | Monthly Subscription and Reset Fee rows | agree |
| 90/10 split, $20 minimum, 3 concurrent accounts | `sim-funded-payout-ratio`, `sim-funded-payout-minimum`, `sim-funded-max-concurrent-accounts` | Payout Ratio, Min Withdrawable Amount, Max Concurrent Accounts rows | agree |
| commission 0.50 mini / 0.20 micro per side, ex exchange and NFA fees | instruments FAQ (one answer, three-part cost) | no second source states a commission; the exclusion is the same page's own sentence | single source, not a conflict |

Pairs that **look** contradictory and are not, with the reason:

- **Evaluation max contracts 5/10/15 vs Sim-Funded scaling starting at 2/4/6.** Different phase of
  the same plan; the comparison table's "Max Contracts (scaling) 5 / 10 / 15" is the plateau of the
  staging list, and the TOR panel calls it "2 -> 5", "4 -> 10", "6 -> 15". Both values are modeled,
  in their own phase.
- **Growth has a daily loss limit on the Sim-Funded account but none in the evaluation.** Same plan,
  different phase; both are stated explicitly ("There is no Daily Loss Limit during the Evaluation
  phase for the Growth Account").
- **Trailing mark end-of-day vs "equity ... cannot hit at any point".** Not two limits: `mode: eod`
  is when the mark moves, `evaluated: intraday` is when the threshold is tested. ADR-0107 section 8
  keeps them as separate declarations. The overview card's "No Intraday Trailing" is the same fact
  as `mode: eod`.
- **Payout "every 4 days" (how-it-works) vs "4 trading days within the payout cycle" (TOR).** The
  same gate in two wordings, same plan and phase: four qualifying days per cycle, counted since
  the previous payout (`window: since_last_payout`, `min_profitable_days: 4`,
  `min_days_since_last: 4`).
- **"4:10 pm ET" (instruments FAQ) vs "4:10 p.m. ET or the relevant market close, whichever is
  sooner" (overnight FAQ).** One deadline with a holiday clause attached. The session-relative
  declaration (section 1) reproduces both.
- **Growth drawdown 2,000 on 50K, Pro 3,000 on 50K.** Different products, not a conflict.

## 10. Quotation index (every distinct quote used in the six files)

| used for | page | section | quote |
|---|---|---|---|
| `eval_profit_target` | TOR | `evaluation-profit-target` | "To complete the Profit Target , you must achieve a defined minimum profit above the Initial Simulated Capital on the account. You will meet this objective once your account balance exceeds the Initial Simulated Capital by the required Profit Target, with all positions closed. The Profit Target is $6,000 ." (amount varies by size) |
| `eval_max_drawdown` | TOR | `evaluation-max-drawdown` | "Once the Maximum Drawdown Limit reaches the Initial Simulated Capital , it locks permanently at that figure for the remaining duration of the Evaluation, unless (i) you pay a Reset Fee, or (ii) you breach the Maximum Drawdown Limit and wait for the next monthly subscription. The Maximum Drawdown Amount is $3,000 ." (Pro adds "or Daily Loss Limit") |
| `funded_max_drawdown` | TOR | `sim-funded-max-drawdown` | "Once the Maximum Drawdown Limit reaches the Initial Simulated Capital , it locks permanently at that figure for the remaining life of the account. The Maximum Drawdown Amount is $3,000 ." |
| `eval_daily_loss` | TOR | `evaluation-daily-loss-limit` | "The Daily Loss Limit is calculated at the start of each trading day ... The Daily Loss Limit Amount is $1,500 . On the first day, the account balance used for the limit calculation is the Initial Simulated Capital. The Pro Account applies a Hard Daily Loss Limit in the Evaluation. If the limit is breached, the Evaluation is unsuccessful." |
| `funded_daily_loss` (Pro) | TOR | `sim-funded-daily-loss-limit` | "... The Pro Account applies a Hard Daily Loss Limit on the Sim-Funded Account. If the limit is breached, the account is immediately and permanently terminated." |
| `funded_daily_loss` (Growth) | TOR | `sim-funded-daily-loss-limit` | "If the equity hits this limit, all open positions are automatically closed and trading is suspended for the remainder of that trading day. The account is not terminated, and trading resumes at the start of the next trading day. ... The Daily Loss Limit Amount is $2,000 ." |
| `eval_max_contracts` | TOR | `evaluation-max-contracts` | "The Max Contracts rule limits the maximum number of contracts you may hold simultaneously at any given time, across all instruments. The Max Contracts limit on your Evaluation Account is 10 contracts :" |
| `funded_scaling_plan` | TOR | `sim-funded-max-contracts` | "The following list describes the range of the Profit above the Initial Simulated Capital, together with the number of contracts allowed to be opened: $0-$999 -> 4 minis or standard / 40 micros contracts ... $4,500+ -> 10 minis or standard / 100 micros contracts" (arrows and en dashes rendered as `->` and `-` here; the ruleset carries the exact text) |
| `eval_consistency` | TOR | `evaluation-consistency-rule` | "To pass the Evaluation, the Consistency Rule requires that your single most profitable trading day (the Best Day ) does not represent more than 40% of your total profit ." (50% on Pro) |
| `funded_payout` | TOR | `sim-funded-payout-eligibility` | "To become eligible to request a payout, you must trade on a minimum number of trading days within the payout cycle, each meeting a minimum daily profit threshold. Minimum number of Qualifying Days: 4 trading days Minimum daily P&L required: $300 per Qualifying Day" |
| `eval_monthly_subscription` | TOR | `subscription-fees-monthly-fee` | "The monthly fee is $169/month ." |
| `eval_reset_fee` | TOR | `subscription-fees-reset-fee` | "The Reset Fee returns your account to its original starting conditions. The Reset Fee is $159 ." |
| `eval_flat_by` | instruments FAQ | What are the trading hours? | "FTMO Futures does not allow positions to be held over the market closure. The trading day closes at 4:10 pm US Eastern Time (ET) and reopens at 6:00 pm ET . Any open positions, including pending orders, are automatically liquidated/flattened at the 4:10 pm ET close, so you must close your trades before then." |
| `funded_flat_by` | overnight FAQ | Can I hold positions overnight or over the weekend? | "FTMO Futures does not allow positions to be held over the market close . All positions must be closed, and all resting orders (including stop-loss orders, limit orders, and bracket orders) must be cancelled before 4:10 p.m. ET or the relevant market close, whichever is sooner, on each trading day." |
| `funded_inactivity` | forbidden | Account Access and Personal Use | "Sim funded accounts require ongoing trading activity. Accounts on which no trading activity has been recorded for 30 consecutive calendar days will receive an automated inactivity warning. Accounts remaining inactive for a further 30 days will be closed." |
| `commissions` (amounts **and** the ex-fees declaration) | instruments FAQ | How much does it cost to trade? What are the commissions and fees? | "$0.50 per side for minis and $0.20 per side for micros Exchange and NFA fees are set by the exchanges and regulators, not by FTMO." |
| `compliance_automated_trading_permitted`, `hft_and_latency_arbitrage_ban` | forbidden | Prohibited Trading Practices 5 | "Automated trading is permitted. You must not, however, use software, artificial intelligence, or automated systems that manipulate, abuse, or provide an unfair advantage over the programme, including high-frequency strategies and latency arbitrage." |
| `compliance_no_copy_or_third_party_trading` | forbidden | Prohibited Trading Practices 4 | "You must not replicate, follow, or otherwise incorporate the trading decisions of any third party into your FTMO Futures account. Whether via signal services, master accounts, trade copiers, or any manual or automated arrangement ..." |
| `compliance_exchange_conduct` | forbidden | Exchange Compliance | "Practices prohibited by CME rules, including spoofing, layering, wash trading, and all other forms of market manipulation, are strictly prohibited under these terms, whether or not specifically named here." |
| `not_modeled` ids | forbidden, TOR | see section 8 | each entry's full quote is in its `source` (the ruleset is the authority; this table is the index) |

Facts quoted in this document but not attached to a rule (one attribution per rule, ADR-0106
section 2): "For the purposes of Trading Objectives and other rules and conditions, a trading day is
defined as the period beginning at 6:00 p.m. ET and ending at 4:10 p.m. ET on the following calendar
day." (top-level `reset`), "Accounts are assessed for eligibility to pass after the end of the
trading day." (`evaluated: eod` on the profit target), "FTMO Futures operates on a 90/10 ratio . You
may withdraw 90% of the amount you requested for withdrawal after applying the other applicable
Payout conditions such as the Payout Cap." (`split: 0.9`), "The minimum amount available for payout
is $20 ." (`min_usd`), "The Payout Cap is $3,000 per request." (`max_usd`), "You may request to
withdraw up to 50% of your Profit above the Initial Simulated Capital." (`max_share_of_withdrawable`),
"You may request to withdraw up to 100% of your Profit above the Initial Simulated Capital." (Pro),
"No Consistency Rule" on the Sim-Funded phase (no consistency rule on the funded phase), "To submit a
payout request, at least 50% of the requested amount must represent new profit generated during the
current payout cycle, not carried-over profit from prior cycles." (`min_new_profit_share_of_request`,
the `sim-funded-min-new-profit-for-request` panel: the payout rule's one attribution is the
eligibility panel, section 8's removed entry held this quote before round 2), "The total profit is
the cumulative sum of closed profits and losses across all trading days in the Evaluation phase.
The Best Day is defined as the single day on which the highest closed profit was achieved, measured
at the end of the trading day." (`window: all_time` on both sides of the consistency rule), "One
Standard or Mini contract counts as one contract Ten Micro contracts count as one Standard / Mini
contract" (contract weights), "NQ E-mini NASDAQ 100 ES E-mini S&P 500 YM E-mini Dow Jones RTY E-mini
Russell 2000 NKD Nikkei/USD" and "Micro contracts Symbol Instrument MNQ Micro NASDAQ 100 MES Micro
S&P 500 ... MYM Micro Dow Jones M2K Micro Russell 2000" (the nine roots), "For FTMO Futures, the
following trading platforms are available in all phases. The Evaluation, Sim-Funded, and Live
Funded Account." (`platform`), "There is no activation fee ." (no activation fee rule), "Consistency
Rule: your best day counts for max 50% of total profit on Pro, 40% on Growth." (cross-check).

## 11. Per file

Six files, one section each. Every list that is identical across the six is stated once (section 8
for `not_modeled`, section 9 for conflicts). `ruleset_sha256` is the content hash of the file
without its (absent) verification block - the number the owner types the first 12 characters of.
Every hash changed in round 2; these are the current ones.

### `ftmo-futures-growth-50k`

- `ruleset_sha256`: `58f720d4945987c37caa36642965710a95cb6f6d77718facec08ec650a83a1ce`
- evaluation: `eval_max_drawdown` 2,000 / `eval_max_contracts` 5 / `eval_flat_by` 50 minutes before
  the scheduled close (16:10 ET on a regular day) / three compliance rules / `eval_profit_target`
  3,000 on closed balance at the close / `eval_consistency` 0.40; fees monthly 119, reset 109.
- sim_funded: `funded_max_drawdown` 2,000 / `funded_daily_loss` 1,000 soft / `funded_scaling_plan`
  0->2, 1,000->3, 2,000->5, 3,000->5, 4,500->5 / `funded_flat_by` 50 minutes before the scheduled
  close / `funded_payout` 4 days of 150+, cap 2,500, share 0.5, min new profit 0.5, split 0.9,
  min 20, `threshold_after_payout: unchanged` / `funded_inactivity` 60 calendar days.
- conflicts: none. assumptions: none. `not_modeled`: 4 material + 6 immaterial (section 8).
- **OWNER REVIEW CHECKLIST**
  - account/thresholds: target 3,000; max drawdown 2,000 with the lock at the initial capital and
    the mark on the closing balance (not equity); contract limit 5; consistency 40%;
    `flat_by` fifty minutes before the session close, which is 16:10 ET on a regular day; rule-day
    reset 18:00 ET; no daily loss and no time limit in the evaluation.
  - payouts: 4 qualifying days of 150+ in the cycle; one request per 4 trading days; cap 2,500;
    50% of profit above the start; at least half of the request must be new profit since the last
    payout; 90/10; minimum 20; drawdown unchanged by a payout; funded daily loss 1,000 soft
    (suspend, not terminate); scaling plateau 5.
  - fees/commissions: monthly 119; reset 109; commission 0.50 per side per mini, 0.20 per side per
    micro, all platforms, **excluding the exchange and NFA fees** (`false`), which the attempt adds
    from a fee table or reports as unknown (the stored CME table has no exchange rows yet).
  - news/compliance: no news restriction (news trading allowed), so no `news_restriction` rule and
    no `effect`; automation permitted; copy trading and third-party access prohibited; CME conduct
    rules.
  - assumptions: none - every value above is quoted. conflicts: none.

### `ftmo-futures-growth-100k`

- `ruleset_sha256`: `6391a7dbd336afed7d6c57044853b017c26a5db856d015b1c92d69ab00be8d2d`
- evaluation: `eval_max_drawdown` 3,000 / `eval_max_contracts` 10 / `eval_flat_by` 16:10 ET / three
  compliance rules / `eval_profit_target` 6,000 (balance 106,000, flat) / `eval_consistency` 0.40;
  fees monthly 169, reset 159.
- sim_funded: `funded_max_drawdown` 3,000 / `funded_daily_loss` 2,000 soft / `funded_scaling_plan`
  0->4, 1,000->5, 2,000->8, 3,000->10, 4,500->10 / `funded_flat_by` 16:10 ET / `funded_payout` 4 days
  of 300+, cap 3,000, share 0.5, min new profit 0.5, split 0.9, min 20 / `funded_inactivity` 60
  calendar days.
- conflicts: none. assumptions: none. `not_modeled`: 4 material + 6 immaterial.
- **OWNER REVIEW CHECKLIST**
  - account/thresholds: target 6,000; max drawdown 3,000; contract limit 10; consistency 40%;
    `flat_by` 16:10 ET on a regular day (session-relative); reset 18:00 ET; no evaluation daily
    loss, no time limit.
  - payouts: 4 days of 300+; cap 3,000; share 50%; at least half the request must be new profit;
    90/10; min 20; funded daily loss 2,000 soft; scaling 4 -> 10.
  - fees/commissions: monthly 169; reset 159; commission 0.50 mini / 0.20 micro excluding exchange
    and NFA fees.
  - news/compliance: as above.
  - assumptions: none. conflicts: none.

### `ftmo-futures-growth-150k`

- `ruleset_sha256`: `174dd14cbbe77329f175a52e38e4d772acd5e3e20c6888e9040dfccab6e5c6ff`
- evaluation: `eval_max_drawdown` 4,500 / `eval_max_contracts` 15 / `eval_flat_by` 16:10 ET / three
  compliance rules / `eval_profit_target` 9,000 / `eval_consistency` 0.40; monthly 229, reset 219.
- sim_funded: `funded_max_drawdown` 4,500 / `funded_daily_loss` 3,000 soft / `funded_scaling_plan`
  0->6, 1,000->8, 2,000->10, 3,000->12, 4,500->15 / `funded_flat_by` 16:10 ET / `funded_payout` 4 days
  of 450+, cap 4,000, share 0.5, min new profit 0.5 / `funded_inactivity`.
- conflicts: none. assumptions: none. `not_modeled`: 4 material + 6 immaterial.
- **OWNER REVIEW CHECKLIST**
  - account/thresholds: target 9,000; max drawdown 4,500; contract limit 15; consistency 40%.
  - payouts: 4 days of 450+; cap 4,000; share 50%; at least half the request must be new profit;
    90/10; min 20; funded daily loss 3,000 soft; scaling 6 -> 15.
  - fees/commissions: monthly 229; reset 219; commission as above, excluding exchange and NFA fees.
  - news/compliance: as above. assumptions: none. conflicts: none.

### `ftmo-futures-pro-50k`

- `ruleset_sha256`: `da29ef5ebcee7c1ba87a6bd2e7e1660945dd25066f4d9d3958b5cd4a5c7164ac`
- evaluation: `eval_max_drawdown` 3,000 / `eval_daily_loss` 1,000 hard / `eval_max_contracts` 5 /
  `eval_flat_by` / three compliance rules / `eval_profit_target` 3,000 / `eval_consistency` 0.50;
  monthly 139, reset 129.
- sim_funded: `funded_max_drawdown` 3,000 / `funded_daily_loss` 1,000 hard / `funded_scaling_plan`
  0->2, 1,000->3, 2,000->5, 3,000->5, 4,500->5 / `funded_flat_by` / `funded_payout` 5 days of 200+,
  cap 5,000, share 1.0 (no share constraint), min new profit 0.5 / `funded_inactivity`.
- conflicts: none. assumptions: none. `not_modeled`: 4 material + 6 immaterial.
- **OWNER REVIEW CHECKLIST**
  - account/thresholds: target 3,000; max drawdown 3,000; **daily loss 1,000 hard in the
    evaluation and hard on the Sim-Funded account**; contract limit 5; consistency 50%.
  - payouts: 5 days of 200+; cap 5,000; withdrawable 100% of profit above the start; **but at least
    half of the request must still be new profit since the last payout**, so a request is bounded by
    twice the new profit as well; 90/10; min 20.
  - fees/commissions: monthly 139; reset 129; commission 0.50 mini / 0.20 micro excluding exchange
    and NFA fees.
  - news/compliance: as above. assumptions: none. conflicts: none.

### `ftmo-futures-pro-100k`

- `ruleset_sha256`: `f7689cec4db9adfaa6a1b54f7aad9e6abd5c16371944afb43ec1263469a79003`
- evaluation: `eval_max_drawdown` 4,500 / `eval_daily_loss` 1,500 hard / `eval_max_contracts` 10 /
  `eval_flat_by` / three compliance rules / `eval_profit_target` 6,000 / `eval_consistency` 0.50;
  monthly 199, reset 189.
- sim_funded: `funded_max_drawdown` 4,500 / `funded_daily_loss` 1,500 hard / `funded_scaling_plan`
  0->4, 1,000->5, 2,000->8, 3,000->10, 4,500->10 / `funded_flat_by` / `funded_payout` 5 days of 300+,
  cap 6,000, share 1.0, min new profit 0.5 / `funded_inactivity`.
- conflicts: none. assumptions: none. `not_modeled`: 4 material + 6 immaterial.
- **OWNER REVIEW CHECKLIST**
  - account/thresholds: target 6,000; max drawdown 4,500; daily loss 1,500 hard (both phases);
    contract limit 10; consistency 50%.
  - payouts: 5 days of 300+; cap 6,000; withdrawable 100%; at least half the request must be new
    profit; 90/10; min 20; scaling 4 -> 10.
  - fees/commissions: monthly 199; reset 189; commission excluding exchange and NFA fees.
  - news/compliance: as above. assumptions: none. conflicts: none.

### `ftmo-futures-pro-150k`

- `ruleset_sha256`: `e9be0846e41c255ca7a402e225bf0764effc1ac6ea0d5009699940cf0c2ef1a9`
- evaluation: `eval_max_drawdown` 6,000 / `eval_daily_loss` 2,000 hard / `eval_max_contracts` 15 /
  `eval_flat_by` / three compliance rules / `eval_profit_target` 9,000 / `eval_consistency` 0.50;
  monthly 269, reset 259.
- sim_funded: `funded_max_drawdown` 6,000 / `funded_daily_loss` 2,000 hard / `funded_scaling_plan`
  0->6, 1,000->8, 2,000->10, 3,000->12, 4,500->15 / `funded_flat_by` / `funded_payout` 5 days of 500+,
  cap 8,000, share 1.0, min new profit 0.5 / `funded_inactivity`.
- conflicts: none. assumptions: none. `not_modeled`: 4 material + 6 immaterial.
- **OWNER REVIEW CHECKLIST**
  - account/thresholds: target 9,000; max drawdown 6,000; daily loss 2,000 hard (both phases);
    contract limit 15; consistency 50%.
  - payouts: 5 days of 500+; cap 8,000; withdrawable 100%; at least half the request must be new
    profit; 90/10; min 20; scaling 6 -> 15.
  - fees/commissions: monthly 269; reset 259; commission excluding exchange and NFA fees.
  - news/compliance: as above. assumptions: none. conflicts: none.

## 12. What the pages do NOT state (and what was done about it)

- **Minimum trading days**: no such objective exists for FTMO Futures (the CFD challenge's four-day
  rule is not repeated here), so no `min_trading_days` rule and no `activity_requirement` is
  declared.
- **Time limit**: "There's no time limit." (how-it-works), so `max_calendar_days`/`max_trading_days`
  are null and there is no `time_limit` rule.
- **Effective date**: no page states when these rules took effect. `effective_from` is the retrieval
  date, 2026-11-22, and `as_of` is the same; the rule page's `dateModified` is a modification time,
  not an effective date.
- **Add-ons**: none exist (no add-on step in the funnel), so `addons: []`.
- **Jurisdiction**: FTMO Futures is offered globally to natural persons with exceptions the page
  does not enumerate, so `jurisdiction` stays null rather than guessing.
- **Scaling in the evaluation**: none; the contract limit is fixed for the whole evaluation.
- **Exchange and NFA fees**: deliberately not published (section 5), which is why the commissions
  block declares `includes_exchange_and_regulatory_fees: false`: the cost of those fees has to come
  from the exchange-fee dataset, and until it holds exchange rows the attempt reports the gap
  (`exchange fees unknown: ...`) and leaves the cash statistic unavailable. This is a reported gap
  now, not a `not_modeled` entry.
- **Live Funded capital per size**: only a worked example ("Initial Capital = $3,000") appears, and
  it is an example, not a specification, so the stage is not modeled.
- **Symbol universe**: the instrument FAQ lists 19 mini and 11 micro contracts (metals, energy, FX,
  crypto and the equity indices). The nine equity-index roots (ES, NQ, YM, RTY, NKD and their
  micros) are the ones this ruleset declares, because they are the roots the futures runs and their
  tick data cover; the rest of the universe is allowed by FTMO but not tradable in the simulated
  run, and no rule value changes because of that.

## 13. Vocabulary: what C7b now models, and what is still missing

Modeled exactly (each of these was a `not_modeled` entry or a workaround in the first draft):
`hwm_basis` on `trailing_drawdown`; `lock.on` as a list of triggers with an offset lock
(`[hwm]` here); `max_share_of_withdrawable` on `payout`; `fee_kind: reset` with `when: on_reset`;
the `inactivity` kind with `unit: calendar_days`; `window: since_last_payout` with
`min_profitable_days` and `min_day_profit_usd`; `compliance` rules with `applies_to_execution` and
`materiality`; and, new in round 2, `payout.min_new_profit_share_of_request` (the last material
payout gap) and `commissions.includes_exchange_and_regulatory_fees` (which turns the unpublished
exchange and NFA fees into a declared, reported gap instead of a silently low cost). The
session-relative `flat_by` is now used, so the holiday early close comes from the CME calendar:
these files never carried a per-file holiday entry, and with an absolute 16:10 ET clock an early
close was not covered at all (the clock fell after the session had ended), which is exactly what the
session-relative form fixes.

Not applicable, and why (section "Round 2 changes" has the detail): an `unknown` payout cap (every
cap is printed), a second lock trigger or `set_threshold_to` (the limit is unchanged by a payout),
`news_restriction.effect` (there is no news rule), a news event type from the new calendar coverage
(no rule reads the calendar), `activity_requirement` (FTMO has no rolling-window activity rule),
separate consistency windows (both sides are all-time) and a conflict `absent` reading (there is no
conflict).

Still missing, and therefore still `not_modeled`: an entry ban near a price limit (a per-session
limit series would be needed as well) and a discretionary-clause representation (none exists by
design). Those are two of the four material entries; the other two are the discretionary news rule
and the cross-account sizing comparison (`inconsistent_position_sizing`). The six immaterial ones
are stages and behaviours the simulation does not reach at all (Live Funded, cross-account hedging,
evaluation-vs-funded mismatch, simulation artefacts, HFT detection, concurrent accounts).

## 14. Open questions for the owner

1. **The CME exchange fees.** With `includes_exchange_and_regulatory_fees: false` the attempt now
   needs an `exchange_fees_v1` table that holds CME exchange rows, and the stored dataset has none
   (`docs/data/cme-exchange-fees.md`: CME Group refuses automated access and its schedule names no
   root ticker, so only an owner-supplied CSV can price it, class `non_member_customer`). Until it
   exists every FTMO attempt's cash statistic is `unavailable` with the reason `exchange fees
   unknown`. Is supplying that file the plan, or should the six files carry a named
   `cost_assumption` instead? (The NFA assessment rows are already in the dataset: $0.01 per side
   through 2027-06-30, $0.02 from 2027-07-01.)
2. **The 50-minute session-relative flat.** It is exact on a regular session (16:10 ET) and
   conservative on a holiday early close (fifty minutes *before* the firm's own deadline). The
   alternative would be two `flat_by` clocks (an absolute 16:10 ET plus a zero-minute session-close
   rule) that reproduce "whichever is sooner" exactly. Confirm the single conservative clock is
   preferred.
3. **The payout-vs-drawdown interaction.** The overview warns about "violating the Maximum Drawdown
   on a Pro Sim-Funded Account by requesting a full withdrawal". The model lets a payout take the
   balance down to the locked limit (`withdrawable = balance - starting capital`); should the payout
   cap leave a buffer above the drawdown limit? The pages state no such rule.
4. **Consistency denominator.** FTMO measures total profit as the sum of closed daily P&L; the
   engine uses the rule-day balance change. Positions are flat at the rule-day boundary because of
   `flat_by`, so the two agree for any strategy the firm allows - but a strategy that closed and
   re-opened inside a rule-day would be measured differently.
5. **Rule-day boundary.** `reset` is 18:00 `America/New_York` from the trading-day definition.
   Confirm that the reset should follow the ET open of the traded session (not the 16:10 close) - it
   changes which trading day a late-evening fill belongs to.
6. **Funded daily loss for Growth.** The panel says a breach means "all open positions are
   automatically closed and trading is suspended for the remainder of that trading day", which is
   `soft_lock_until_reset`. Confirm that a suspended day should not count as a qualifying payout day
   (the model does not count it: a suspended day has a loss, not 150+/300+/450+ of profit).
7. **Live Funded.** Nothing is modeled for it. If you ever want it, its per-size capital has to be
   published somewhere official; the 100K worked example is not enough.

## 15. Commands

```bash
for f in rulesets/prop/ftmo/*.v1.yaml; do uv run crucible prop validate "$f" --json > /dev/null; done
uv run crucible prop list --firm ftmo --json   # six rulesets, all unverified
uv run crucible prop confirm rulesets/prop/ftmo/ftmo-futures-pro-100k.v1.yaml   # owner only, TTY
```

`uv run crucible prop validate` re-checks the schema, the content hash, the rule coverage and the
evaluation status; it writes nothing. `rulesets/prop/INDEX.json` is generated separately by
`uv run python -m tools.docgen --write` and a test compares it with the files, so a ruleset that
is not in INDEX.json is not a ruleset the repository has recorded.

The quote/hash self-check used during this migration and again for round 2 normalises each snapshot,
asserts every attribution's `quote` occurs in it verbatim and asserts the `sha256` of that snapshot
file (165 attributions over the six rulesets, 0 failures; it was 177 before the two removed
`not_modeled` entries). It is a local script, not part of the repository; the attributions and
hashes it verified are the ones above.
