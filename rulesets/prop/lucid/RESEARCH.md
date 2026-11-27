# Lucid Trading (firm_slug `lucid`) — sourced research, schema version 2

Status: **unverified**. Only the owner can flip `verification.status` (`crucible prop confirm`,
a TTY step). Nothing in this file is a confirmed firm rule until that sidecar exists.

- **44 rulesets** under `rulesets/prop/lucid/`, all on schema version 2, version 1: LucidPro 8,
  LucidFlex 16, LucidDaily 16, LucidDirect 4.
- **Retrieval**: 2026-11-22, 01:35Z-02:00Z UTC, `curl` with a desktop user agent. Raw bytes in
  `D:\proyectos\crucible-notes\internal\prop_snapshots\lucid\` (59 files); every quotation below
  names its snapshot hash, and the self-check in section 12 re-verifies all of them.
- `as_of` and `effective_from` are 2026-11-22 in every file: no page states a general effective
  date. The one dated rule change is the LucidPro funded consistency (35% -> 40% for accounts
  purchased or reset on or after 11/28/2025, 3:00 PM EST); section 9.
- Only public pages were read: no login, no form, no purchase, no account. The ruleset carries
  `jurisdiction: null`: the restricted-country list is a purchase-eligibility list, not a trading
  rule of the account.

## 1. What changed from the v1 drafts

The drafts were rewritten in place as schema version 2, and then again for the schema's round-2
fields (the next section records that pass). The ruleset version stays 1 and the file
name stays `<ruleset_id>.v1.yaml`, because the numbering is the ruleset version, not the schema
version, and nothing was committed yet.

Every rule now declares `evidence`, every listing has explicit day units, `commissions` are
carried per side and per root, and the new vocabulary replaced several `not_modeled` entries:

| Was `not_modeled` | Now modelled as |
|---|---|
| `direct_payout_profit_goal` | `payout.cycle_goal_usd` (first-cycle goal, stricter) |
| `direct_payout_cap_schedule`, `payout_cap_schedule` | `payout.max_usd_by_payout` |
| `daily_maximum_daily_profit` | `daily_profit_cap` with `action: promote_phase` |
| `daily_news_trading_ban_funded` | `news_restriction` (FOMC statements, CPI, NFP) |
| `flex_mll_locks_on_first_payout` | `payout.threshold_after_payout: lock_on_first_payout` |
| `flex_payout_half_of_profit` | `payout.max_share_of_withdrawable` + `max_pct_of_balance` |
| `inactivity_30_calendar_days` | `inactivity` (30 calendar days, rolling) |
| `hft` conduct ban (inside the v1 `discretionary_prohibited_strategies`) | `compliance` rule with materiality |
| LucidDaily payout `max_usd: 1000000` sentinel | `max_usd: unlimited` (the page states the cap) |

Corrected values (the v1 drafts were wrong or incomplete):

- **LucidPro payouts** carry a per-size minimum profit goal per cycle ($250/$500/$750/$1,000)
  and a maximum by payout number ($1,000/$1,500 for the $25,000 size up to $3,000/$3,500 for
  $150,000). The v1 drafts had neither.
- **LucidFlex** payouts need 5 profitable days per cycle at a per-size minimum daily profit
  ($100-$250) and a positive net profit in the cycle; v1 carried none of those gates.
- **LucidPro $25,000, DLL on**: the funded page states a $600 fixed limit and the DLL page
  states `None` for the same size and phase. The stricter $600 is carried (section 7).
- **LucidDirect $100,000/$150,000** max loss is $3,500/$5,000 (EOD trail to $103,600/$155,100),
  not the $3,000/$4,500 pattern of the other programmes.
- **LucidDaily evaluation consistency is 40%** (30% for the all-EOD configuration), not the
  blanket 50% the evaluation table states; the contradiction is a recorded conflict (section 7).
- **Commissions are known**: the help centre publishes the per-contract table (section 6). The
  v1 drafts carried no commission at all.
- **The five-payout ceiling** (`max_payouts: 5`) for LucidPro, LucidFlex and LucidDirect comes
  from the live-structure page ('Payout 5 represents the maximum payout level, not a guaranteed
  minimum for live eligibility. This maximum payout level applies to Flex, Pro, and Direct
  plans.'), not from each programme's payout page; the LucidFlex payout page states the same
  ('up to 5 payouts from each LucidFlex account after which they will be moved live').

## Round 2 changes (the C7b round-2 vocabulary)

This section was added when the schema's round-2 fields became required. Nothing was inferred: every
change below is either a now-required declaration, a rule the sources already stated and the earlier
vocabulary could not express, or a removal of a `not_modeled` entry that a round-2 field now covers.

| Required / now expressible | What was done | Files |
|---|---|---|
| `commissions.components` (REQUIRED, all four keys, no default) | `unknown` in every file: no page says whether the per-side commission includes the exchange and NFA fees (section 6). Source is the commissions page (which states the amounts and no fee basis). | 44 |
| `trailing_drawdown.lock.on` is a LIST | `on: [hwm]` (was the bare string `hwm`). | 84 rules |
| `news_restriction.effect` (no default) | `block`, with the new event types and a description that says why (a cap is not what the page states) | 16 |
| `news_restriction` event types now in the calendar | `PPI`, `FOMC_PRESS_CONFERENCE` and `FOMC_MINUTES` added beside `FOMC_STATEMENT`, `CPI` and `NFP` (section 10) | 16 |
| trailing lock with several triggers | LucidFlex **funded** `lock.on: [hwm, first_payout]`: the drawdown page states both triggers (the trail, and a payout request), and `on_first_payout` is only reached when the trigger is declared. Before, the payout-side lock lived only in `payout.threshold_after_payout: lock_on_first_payout`, which the engine does not use to freeze a threshold | 16 |
| `consistency` with separate numerator/denominator windows | LucidPro and LucidDirect funded consistency: `numerator_window: since_last_payout`, `denominator_window: current_cycle`, because each page states the ratio's two sides and the reset separately | 12 |
| conflict alternative `absent` | `pro_25k_funded_dll_alternative` moved from `not_modeled` to `conflicts`, the alternative being `absent` (the daily-loss page's `None` = the rule does not exist), which yields a real sensitivity scenario | 1 |
| `flat_by` relative to the scheduled session end | every phase keeps the fixed 4:45 PM ET clock with the 6:00 PM ET reopen AND adds `*_flat_by_close_early_close` (`minutes_before_session_end: 15`) for the holiday sentence; the per-file `holiday_early_close` `not_modeled` entry is gone (section 4, section 15 question 11) | 84 rules, 44 entries |

Considered and **not** used, because a Lucid page does not state the rule exactly:

- `payout.max_usd: unknown` — every `unlimited` here is sourced: the Pro and Direct funded pages
  state "No simulated payout caps" and the Daily payout page states "Payout maximum is the amount of
  sim profits built above the buffer", which is exactly the engine's `withdrawable` term with
  `buffer_usd`. No `unlimited` is an assumption of no cap, so no cap was made `unknown`.
- `payout.set_threshold_to` — no page states a level the max loss is set to after a payout; LucidFlex
  locks at the locked balance (a lock trigger, not a set level), the other plans leave it unchanged.
- `payout.min_new_profit_share_of_request` — the pages state a minimum profit goal per cycle and
  "positive net profit (even just $1)", never a share of the request.
- `activity_requirement` — the Active Status Policy page states "You are not required to trade daily
  or weekly"; the only activity gate is the 30-calendar-day abandonment rule, already carried as
  `inactivity`. Writing an `activity_requirement` would invent a rule the firm denies.
- `news_restriction.effect: contract_cap` / `cap_contracts` — LucidDaily forbids holding and opening
  inside the window and says "Your funded account will be breached"; nothing is merely capped.
- `daily_loss.pct_of_peak_profit` for the LucidScale ratchet — one `daily_loss` rule takes one amount
  source, and the ratchet only replaces the fixed limit above the trail, which no rule field can
  gate; it stays `lucidscale_dll_ratchet` (immaterial).

## 2. Programme matrix (generated from the 44 files)

`DD` is the max-loss trailing mode, `DLL` the daily loss limit, `cons` the consistency rule,
`nm` the count of `not_modeled` entries and `cf` the count of conflicts.

| file | program | size | target | eval DD | eval DLL | funded DD | funded DLL | max size | cons | payout | nm | cf |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lucid-lucidpro-100k-dll-off | LucidPro | 100K | $6,000 | $3,000 EOD trail, locks at +$3,100 (floor start+$100) | none | $3,000 EOD trail, locks at +$3,100 (floor start+$100) | none | 6 mini | 40% payout | no lifetime cap, per-request caps by payout number | 6 | 0 |
| lucid-lucidpro-100k-dll-on | LucidPro | 100K | $6,000 | $3,000 EOD trail, locks at +$3,100 (floor start+$100) | $1,800 soft | $3,000 EOD trail, locks at +$3,100 (floor start+$100) | $1,800 soft | 6 mini | 40% payout | no lifetime cap, per-request caps by payout number | 8 | 0 |
| lucid-lucidpro-150k-dll-off | LucidPro | 150K | $9,000 | $4,500 EOD trail, locks at +$4,600 (floor start+$100) | none | $4,500 EOD trail, locks at +$4,600 (floor start+$100) | none | 10 mini | 40% payout | no lifetime cap, per-request caps by payout number | 6 | 0 |
| lucid-lucidpro-150k-dll-on | LucidPro | 150K | $9,000 | $4,500 EOD trail, locks at +$4,600 (floor start+$100) | $2,700 soft | $4,500 EOD trail, locks at +$4,600 (floor start+$100) | $2,700 soft | 10 mini | 40% payout | no lifetime cap, per-request caps by payout number | 8 | 0 |
| lucid-lucidpro-25k-dll-off | LucidPro | 25K | $1,250 | $1,000 EOD trail, locks at +$1,100 (floor start+$100) | none | $1,000 EOD trail, locks at +$1,100 (floor start+$100) | none | 2 mini | 40% payout | no lifetime cap, per-request caps by payout number | 6 | 0 |
| lucid-lucidpro-25k-dll-on | LucidPro | 25K | $1,250 | $1,000 EOD trail, locks at +$1,100 (floor start+$100) | none | $1,000 EOD trail, locks at +$1,100 (floor start+$100) | $600 soft | 2 mini | 40% payout | no lifetime cap, per-request caps by payout number | 8 | 1 |
| lucid-lucidpro-50k-dll-off | LucidPro | 50K | $3,000 | $2,000 EOD trail, locks at +$2,100 (floor start+$100) | none | $2,000 EOD trail, locks at +$2,100 (floor start+$100) | none | 4 mini | 40% payout | no lifetime cap, per-request caps by payout number | 6 | 0 |
| lucid-lucidpro-50k-dll-on | LucidPro | 50K | $3,000 | $2,000 EOD trail, locks at +$2,100 (floor start+$100) | $1,200 soft | $2,000 EOD trail, locks at +$2,100 (floor start+$100) | $1,200 soft | 4 mini | 40% payout | no lifetime cap, per-request caps by payout number | 8 | 0 |
| lucid-lucidflex-100k-dll-off-cons40 | LucidFlex | 100K | $6,000 | $3,000 EOD trail, locks at +$3,100 (floor start+$100) | none | $3,000 EOD trail, locks at +$3,100 (floor start+$100, or at the first payout) | none | scaling 3/4/5/6 | 40% pass | $2,500 per request, no lifetime cap | 7 | 0 |
| lucid-lucidflex-100k-dll-off-cons50 | LucidFlex | 100K | $6,000 | $3,000 EOD trail, locks at +$3,100 (floor start+$100) | none | $3,000 EOD trail, locks at +$3,100 (floor start+$100, or at the first payout) | none | scaling 3/4/5/6 | 50% pass | $2,500 per request, no lifetime cap | 7 | 0 |
| lucid-lucidflex-100k-dll-on-cons40 | LucidFlex | 100K | $6,000 | $3,000 EOD trail, locks at +$3,100 (floor start+$100) | none | $3,000 EOD trail, locks at +$3,100 (floor start+$100, or at the first payout) | none | scaling 3/4/5/6 | 40% pass | $2,500 per request, no lifetime cap | 9 | 0 |
| lucid-lucidflex-100k-dll-on-cons50 | LucidFlex | 100K | $6,000 | $3,000 EOD trail, locks at +$3,100 (floor start+$100) | none | $3,000 EOD trail, locks at +$3,100 (floor start+$100, or at the first payout) | none | scaling 3/4/5/6 | 50% pass | $2,500 per request, no lifetime cap | 9 | 0 |
| lucid-lucidflex-150k-dll-off-cons40 | LucidFlex | 150K | $9,000 | $4,500 EOD trail, locks at +$4,600 (floor start+$100) | none | $4,500 EOD trail, locks at +$4,600 (floor start+$100, or at the first payout) | none | scaling 4/5/6/8/10 | 40% pass | $3,000 per request, no lifetime cap | 7 | 0 |
| lucid-lucidflex-150k-dll-off-cons50 | LucidFlex | 150K | $9,000 | $4,500 EOD trail, locks at +$4,600 (floor start+$100) | none | $4,500 EOD trail, locks at +$4,600 (floor start+$100, or at the first payout) | none | scaling 4/5/6/8/10 | 50% pass | $3,000 per request, no lifetime cap | 7 | 0 |
| lucid-lucidflex-150k-dll-on-cons40 | LucidFlex | 150K | $9,000 | $4,500 EOD trail, locks at +$4,600 (floor start+$100) | none | $4,500 EOD trail, locks at +$4,600 (floor start+$100, or at the first payout) | none | scaling 4/5/6/8/10 | 40% pass | $3,000 per request, no lifetime cap | 9 | 0 |
| lucid-lucidflex-150k-dll-on-cons50 | LucidFlex | 150K | $9,000 | $4,500 EOD trail, locks at +$4,600 (floor start+$100) | none | $4,500 EOD trail, locks at +$4,600 (floor start+$100, or at the first payout) | none | scaling 4/5/6/8/10 | 50% pass | $3,000 per request, no lifetime cap | 9 | 0 |
| lucid-lucidflex-25k-dll-off-cons40 | LucidFlex | 25K | $1,250 | $1,000 EOD trail, locks at +$1,100 (floor start+$100) | none | $1,000 EOD trail, locks at +$1,100 (floor start+$100, or at the first payout) | none | scaling 1/2 | 40% pass | $1,000 per request, no lifetime cap | 7 | 0 |
| lucid-lucidflex-25k-dll-off-cons50 | LucidFlex | 25K | $1,250 | $1,000 EOD trail, locks at +$1,100 (floor start+$100) | none | $1,000 EOD trail, locks at +$1,100 (floor start+$100, or at the first payout) | none | scaling 1/2 | 50% pass | $1,000 per request, no lifetime cap | 7 | 0 |
| lucid-lucidflex-25k-dll-on-cons40 | LucidFlex | 25K | $1,250 | $1,000 EOD trail, locks at +$1,100 (floor start+$100) | none | $1,000 EOD trail, locks at +$1,100 (floor start+$100, or at the first payout) | none | scaling 1/2 | 40% pass | $1,000 per request, no lifetime cap | 9 | 0 |
| lucid-lucidflex-25k-dll-on-cons50 | LucidFlex | 25K | $1,250 | $1,000 EOD trail, locks at +$1,100 (floor start+$100) | none | $1,000 EOD trail, locks at +$1,100 (floor start+$100, or at the first payout) | none | scaling 1/2 | 50% pass | $1,000 per request, no lifetime cap | 9 | 0 |
| lucid-lucidflex-50k-dll-off-cons40 | LucidFlex | 50K | $3,000 | $2,000 EOD trail, locks at +$2,100 (floor start+$100) | none | $2,000 EOD trail, locks at +$2,100 (floor start+$100, or at the first payout) | none | scaling 2/3/4 | 40% pass | $2,000 per request, no lifetime cap | 7 | 0 |
| lucid-lucidflex-50k-dll-off-cons50 | LucidFlex | 50K | $3,000 | $2,000 EOD trail, locks at +$2,100 (floor start+$100) | none | $2,000 EOD trail, locks at +$2,100 (floor start+$100, or at the first payout) | none | scaling 2/3/4 | 50% pass | $2,000 per request, no lifetime cap | 7 | 0 |
| lucid-lucidflex-50k-dll-on-cons40 | LucidFlex | 50K | $3,000 | $2,000 EOD trail, locks at +$2,100 (floor start+$100) | none | $2,000 EOD trail, locks at +$2,100 (floor start+$100, or at the first payout) | none | scaling 2/3/4 | 40% pass | $2,000 per request, no lifetime cap | 9 | 0 |
| lucid-lucidflex-50k-dll-on-cons50 | LucidFlex | 50K | $3,000 | $2,000 EOD trail, locks at +$2,100 (floor start+$100) | none | $2,000 EOD trail, locks at +$2,100 (floor start+$100, or at the first payout) | none | scaling 2/3/4 | 50% pass | $2,000 per request, no lifetime cap | 9 | 0 |
| lucid-luciddaily-100k-dlloff-evaleod-fundedeod-cons30 | LucidDaily | 100K | $6,000 | $3,000 EOD trail, locks at +$3,100 (floor start+$100) | none | $3,000 EOD trail, locks at +$3,100 (floor start+$100) | none | 6 mini | 30% pass | uncapped (the withdrawable profit is the cap) | 8 | 1 |
| lucid-luciddaily-100k-dlloff-evalintraday-cons40 | LucidDaily | 100K | $6,000 | $3,000 intraday trail, locks at +$3,100 (floor start+$100) | none | $3,000 intraday trail, locks at +$3,100 (floor start+$100) | none | 6 mini | 40% pass | uncapped (the withdrawable profit is the cap) | 8 | 1 |
| lucid-luciddaily-100k-dllon-evaleod-fundedintraday-cons40 | LucidDaily | 100K | $6,000 | $3,000 EOD trail, locks at +$3,100 (floor start+$100) | $1,800 soft | $3,000 intraday trail, locks at +$3,100 (floor start+$100) | $1,800 soft | 6 mini | 40% pass | uncapped (the withdrawable profit is the cap) | 9 | 1 |
| lucid-luciddaily-100k-dllon-evalintraday-cons40 | LucidDaily | 100K | $6,000 | $3,000 intraday trail, locks at +$3,100 (floor start+$100) | $1,800 soft | $3,000 intraday trail, locks at +$3,100 (floor start+$100) | $1,800 soft | 6 mini | 40% pass | uncapped (the withdrawable profit is the cap) | 9 | 1 |
| lucid-luciddaily-150k-dlloff-evaleod-fundedeod-cons30 | LucidDaily | 150K | $9,000 | $4,500 EOD trail, locks at +$4,600 (floor start+$100) | none | $4,500 EOD trail, locks at +$4,600 (floor start+$100) | none | 10 mini | 30% pass | uncapped (the withdrawable profit is the cap) | 8 | 1 |
| lucid-luciddaily-150k-dlloff-evalintraday-cons40 | LucidDaily | 150K | $9,000 | $4,500 intraday trail, locks at +$4,600 (floor start+$100) | none | $4,500 intraday trail, locks at +$4,600 (floor start+$100) | none | 10 mini | 40% pass | uncapped (the withdrawable profit is the cap) | 8 | 1 |
| lucid-luciddaily-150k-dllon-evaleod-fundedintraday-cons40 | LucidDaily | 150K | $9,000 | $4,500 EOD trail, locks at +$4,600 (floor start+$100) | $2,700 soft | $4,500 intraday trail, locks at +$4,600 (floor start+$100) | $2,700 soft | 10 mini | 40% pass | uncapped (the withdrawable profit is the cap) | 9 | 1 |
| lucid-luciddaily-150k-dllon-evalintraday-cons40 | LucidDaily | 150K | $9,000 | $4,500 intraday trail, locks at +$4,600 (floor start+$100) | $2,700 soft | $4,500 intraday trail, locks at +$4,600 (floor start+$100) | $2,700 soft | 10 mini | 40% pass | uncapped (the withdrawable profit is the cap) | 9 | 1 |
| lucid-luciddaily-25k-dlloff-evaleod-fundedeod-cons30 | LucidDaily | 25K | $1,250 | $1,000 EOD trail, locks at +$1,100 (floor start+$100) | none | $1,000 EOD trail, locks at +$1,100 (floor start+$100) | none | 2 mini | 30% pass | uncapped (the withdrawable profit is the cap) | 8 | 1 |
| lucid-luciddaily-25k-dlloff-evalintraday-cons40 | LucidDaily | 25K | $1,250 | $1,000 intraday trail, locks at +$1,100 (floor start+$100) | none | $1,000 intraday trail, locks at +$1,100 (floor start+$100) | none | 2 mini | 40% pass | uncapped (the withdrawable profit is the cap) | 8 | 1 |
| lucid-luciddaily-25k-dllon-evaleod-fundedintraday-cons40 | LucidDaily | 25K | $1,250 | $1,000 EOD trail, locks at +$1,100 (floor start+$100) | $600 soft | $1,000 intraday trail, locks at +$1,100 (floor start+$100) | $600 soft | 2 mini | 40% pass | uncapped (the withdrawable profit is the cap) | 9 | 1 |
| lucid-luciddaily-25k-dllon-evalintraday-cons40 | LucidDaily | 25K | $1,250 | $1,000 intraday trail, locks at +$1,100 (floor start+$100) | $600 soft | $1,000 intraday trail, locks at +$1,100 (floor start+$100) | $600 soft | 2 mini | 40% pass | uncapped (the withdrawable profit is the cap) | 9 | 1 |
| lucid-luciddaily-50k-dlloff-evaleod-fundedeod-cons30 | LucidDaily | 50K | $3,000 | $2,000 EOD trail, locks at +$2,100 (floor start+$100) | none | $2,000 EOD trail, locks at +$2,100 (floor start+$100) | none | 4 mini | 30% pass | uncapped (the withdrawable profit is the cap) | 8 | 1 |
| lucid-luciddaily-50k-dlloff-evalintraday-cons40 | LucidDaily | 50K | $3,000 | $2,000 intraday trail, locks at +$2,100 (floor start+$100) | none | $2,000 intraday trail, locks at +$2,100 (floor start+$100) | none | 4 mini | 40% pass | uncapped (the withdrawable profit is the cap) | 8 | 1 |
| lucid-luciddaily-50k-dllon-evaleod-fundedintraday-cons40 | LucidDaily | 50K | $3,000 | $2,000 EOD trail, locks at +$2,100 (floor start+$100) | $1,200 soft | $2,000 intraday trail, locks at +$2,100 (floor start+$100) | $1,200 soft | 4 mini | 40% pass | uncapped (the withdrawable profit is the cap) | 9 | 1 |
| lucid-luciddaily-50k-dllon-evalintraday-cons40 | LucidDaily | 50K | $3,000 | $2,000 intraday trail, locks at +$2,100 (floor start+$100) | $1,200 soft | $2,000 intraday trail, locks at +$2,100 (floor start+$100) | $1,200 soft | 4 mini | 40% pass | uncapped (the withdrawable profit is the cap) | 9 | 1 |
| lucid-luciddirect-100k | LucidDirect | 100K | - | - | none | $3,500 EOD trail, locks at +$3,600 (floor start+$100) | $2,100 soft | 6 mini | 20% payout | no lifetime cap, per-request caps by payout number | 9 | 0 |
| lucid-luciddirect-150k | LucidDirect | 150K | - | - | none | $5,000 EOD trail, locks at +$5,100 (floor start+$100) | $3,000 soft | 10 mini | 20% payout | no lifetime cap, per-request caps by payout number | 9 | 0 |
| lucid-luciddirect-25k | LucidDirect | 25K | - | - | none | $1,000 EOD trail, locks at +$1,100 (floor start+$100) | none | 2 mini | 20% payout | no lifetime cap, per-request caps by payout number | 8 | 0 |
| lucid-luciddirect-50k | LucidDirect | 50K | - | - | none | $2,000 EOD trail, locks at +$2,100 (floor start+$100) | $1,200 soft | 4 mini | 20% payout | no lifetime cap, per-request caps by payout number | 9 | 0 |

## 3. Files and what each one is

- **LucidPro**, 8 files = 4 sizes x daily loss limit on/off. The DLL exists or not, in the
  evaluation and the funded account; DLL on also gets on-demand payouts. EOD trailing max loss in
  both phases, no scaling plan, funded consistency 40% per payout cycle.
- **LucidFlex**, 16 files = 4 sizes x DLL on/off x evaluation consistency 40/50. The DLL amount is
  unpublished (so the DLL-on files carry no `daily_loss` rule) and the evaluation consistency
  tier changes. Funded: scaling plan, no consistency rule, 5 profitable days per payout cycle.
- **LucidDaily**, 16 files = 4 sizes x the four checkout options: DLL on/intraday-eval,
  DLL on/EOD-eval/funded-intraday, DLL off/intraday, DLL off/EOD both with the 30% tier. Funded
  news ban and a maximum daily profit that ends the stage.
- **LucidDirect**, 4 files = 4 sizes. Straight to funded; the max loss and the DLL are set by size.

## 4. Assumptions (ADR-0107 section 7 defaults, named on the rule)

Every assumption below is a value the firm is silent on, recorded as `evidence: assumption` with
its name and rationale. No other gap was filled.

| assumption | rules | rationale |
|---|---|---|
| `unspecified_failure_frequency_is_intraday` | 64 | The firm states the max-loss amount and the mark it trails from, and never says whether open equity is tested against the threshold between closes. ADR-0107 section 7 reads an unspecified observation frequency of a failure threshold as intraday, which is the stricter reading. |
| `unspecified_target_frequency_is_eod` | 56 | The firm states the profit target amount and never says when it is measured. A target tested no earlier than the end of the trade date on closed balance is the conservative reading: the trader passes no earlier, and a later same-day breach still counts. |
| `est_means_america_new_york` | 52 | The page writes the cutoff in 'EST'. ADR-0107 section 7 reads a bare US Eastern label as America/New_York including daylight saving, which keeps the 4:45 PM ET close at 4:45 PM local all year; a literal UTC-5 clock would shift the cutoff an hour in summer. |
| `session_close_taken_from_firm_wide_page` | 32 | taken from Allowed Trading Times (section 'LucidPro, LucidFlex and LucidDirect Accounts') for LucidDaily, which that page does not name: the firm-wide 4:45 PM ET close with a 6:00 PM ET reopen is the only session clock the firm publishes. |
| `dll_reset_at_6pm_et_session_reopen` | 26 | The DLL page says trading is restricted 'until the next trading session' and never gives the reset instant. Allowed Trading Times states 'Trading resumes at 6:00 PM EST, Sunday through Thursday', so the rule-day boundary is 18:00 America/New_York (ADR-0107 section 7 reads EST as US Eastern time with DST). |

The ruleset-level rule-day boundary (`reset: 18:00 America/New_York`) has no attribution field in
the schema; it is the same derivation as `dll_reset_at_6pm_et_session_reopen`: the firm states
trading resumes at 6:00 PM EST and never states its own rule-day clock, so the session reopen is
the boundary. `trading_day_is_a_trade_date_with_one_trade` is **not** applied: it only matters for
a minimum-trading-day or payout-day condition stated in trade dates, and every day gate here
counts *profitable* days with a stated dollar floor.

The round-2 session-relative flat (`**/*_flat_by_close_early_close`, `minutes_before_session_end:
15`) adds **no** assumption: the firm states its 4:45 PM ET cutoff as a year-round clock and states
that on an altered-close holiday all positions must be closed before the market closes, and the
scheduled close (5:00 PM ET / 16:00 Chicago in the current regime) is the CME calendar's, not
ours. The fifteen minutes is the firm's own offset between its cutoff and that close, applied to
the altered close; the owner is asked to confirm it below. The engine closes the other half too:
`FlatBy.flat_and_reopen` reopens a session-relative clock at the scheduled session close, so no
entry is admitted between the flat instant and that close, on a half session as on a full one.

## 5. `not_modeled`, by materiality

- **critical**: none
- **material**: `cross_account_hedging` (44 files), `evaluation_and_reset_fees` (44 files), `flex_dll_amount` (8 files), `microscalping_ban` (44 files), `other_us_high_impact_events` (16 files)
- **immaterial**: `daily_consistency_tiers` (16 files), `direct_25k_no_dll` (1 files), `discretionary_prohibited_strategies` (44 files), `flex_consistency_tiers` (16 files), `live_transition_discretionary` (44 files), `lucidscale_dll_ratchet` (7 files), `max_accounts_per_household` (44 files), `on_demand_intraday_payouts` (23 files), `payout_profit_goal_by_cycle` (4 files)

Owner-mandated entries that stay unmodelled: sub-minute holding / micro-scalping
(`microscalping_ban`), cross-account hedging (`cross_account_hedging`). The 2% price-limit
restriction is **not** carried: no Lucid page states it (the backed-out snapshot set was searched
for `price limit` and `2%`), so adding it would be an invented rule.

`flex_dll_amount` is the material gap that makes the LucidFlex DLL-on files optimistic: the option
is sold and enforced, but no page gives an amount per size, so no `daily_loss` rule is carried.

## 6. Commissions (ADR-0107 section 10)

Source: the official help centre page **Approved Products and Commissions**,
`https://support.lucidtrading.com/en/articles/11508978-approved-products-and-commissions`,
snapshot `20261122_art_products_b.html`,
sha256 `9d718a1af98a3ec955ac99b662501e2c59cb687108f68221227b7659b8306220`, read
2026-11-22T01:59:34Z, section 'Approved Products and Commissions'. The table is titled
'Commission (Per Side)' in USD; the quotation carried in every file is the nine-row block for the
roots the rulesets trade.

| root | contract | per side (USD) |
|---|---|---|
| ES | E-mini S&P 500 | 1.75 |
| MES | Micro E-mini S&P 500 | 0.50 |
| NQ | E-mini Nasdaq-100 | 1.75 |
| MNQ | Micro E-mini Nasdaq-100 | 0.50 |
| RTY | E-mini Russell 2000 | 1.75 |
| M2K | Micro E-mini Russell 2000 | 0.50 |
| NKD | Nikkei/USD | 1.75 |
| YM | E-mini Dow ($5) | 1.75 |
| MYM | Micro E-mini Dow | 0.50 |

The owner also supplied the same table as pasted text
(`D:\proyectos\crucible-notes\internal\prop_snapshots\lucid\20261122_owner_provided_commissions.txt`,
sha256 `3b916be88679db0d0d3820be9667e6337cf2feae30aaee007fd600038a702ea0`). It agrees line for line
with the official page, so the attribution uses the readable official page rather than the
owner-provided copy; the two hashes are both recorded here so the agreement is auditable.

Commissions do **not** vary by platform (the page gives one rate per contract), so
`commissions.platform` is null. Evaluation and reset fees stay unknown -> section 5.

**All-in or ex-fees: `unknown` (required field, round 2).** The commissions page states a
"Commission (Per Side)" per contract and a venue column (CME/CBOT). It never says whether the amount
includes the exchange and NFA assessment fees or excludes them: the whole snapshot set was searched
for `all-in`, `all in`, `exchange fee`, `NFA` and `regulatory`, and no page answers the question.
Every file therefore declares `commissions.components`: every component `unknown`, which is what the
schema makes mandatory and refuses to default (ADR-0107 section 8). The consequence is deliberate:
the cash statistics of every Lucid attempt stay conditional (or unavailable) until the owner says
whether the commission is all-in, and the engine never charges (or waives) a fee on a guess.

## 7. Conflicts (both sources kept, ADR-0107 section 7)

`daily_eval_consistency_tier` — 16 LucidDaily files, rule `eval_consistency`, field
`max_day_share`:

- Selected (stricter): the customization page's tier for the configuration
  (`20261122_art_daily_custom.html`, sha256
  `7519176da938e518fbe0d624ffab76c5bb1b754c26ba19292868582d285ba08b`): 40% standard (30% for
  the all-EOD option).
- Alternative: 50%, stated by the evaluation table (`20261122_art_daily_eval.html`, sha256
  `744098659f05516488a7416c46e41d65406c779ccd0e192ec63b1a445ad30e35`) and by the consistency
  page (`20261122_art_daily_cons.html`, sha256
  `145993af3a0343f3b2b35d2794d3f720d0ea8aa1f5632cee48691ba4064feb6c`).
- Applicability checked: same firm, plan, account size, phase and period; the customization page
  enumerates exactly these configurations, so the two statements describe one requirement.
- Each alternative is a sensitivity scenario (`daily_eval_consistency_tier#0`, `#1` on the 30%
  files), never an official plan.

`pro_25k_funded_dll_alternative` — 1 file (`lucid-lucidpro-25k-dll-on`), now a **conflict** with an
`absent` alternative (round 2): the funded account page states a $600 fixed daily loss limit for the
$25,000 size (`20261122_art_pro_funded.html`, sha256
`92b78b95368d1da19883aa12163933349ecff1c18969c09127656ec181b2b269`) and the daily-loss page's
funded table states `None` (`20261122_art_pro_dll.html`, sha256
`b39ee2a32d422a3201e012329a83f7351d834017c983ab0b3b0b00f87b1cb3e4`). Both describe the same firm,
plan, account size and phase, so they contradict; the stricter $600 is selected. The `daily_loss`
kind cannot say "no limit", but the round-2 `value: absent` alternative can: the scenario built
from it drops the rule instead of switching its amount, so a former `not_modeled` entry is now a
real sensitivity scenario (`pro_25k_funded_dll_alternative#0`).

### Checked and found **not** contradictory (the applicability test)

- **'No simulated payout caps' vs the payout tables** (LucidPro, LucidDirect): both hold. The
  page means no cap on the lifetime total; the tables cap each request by payout number, which is
  what `max_usd_by_payout` carries next to `max_usd: unlimited`.
- **LucidFlex '50% of their account balance' vs '50% of Profit up to $1,000'**: both are caps and
  both are carried (`max_pct_of_balance: 50` and `max_share_of_withdrawable: 0.5`); the engine
  applies the smaller, so the restrictive reading is what binds and no sensitivity is needed.
- **4:45 PM forced flat vs the 3:45 PM intraday payout window**: different rules (a trading
  restriction vs a payout window), not two values for one field. The payout window is declared
  unmodelled (`on_demand_intraday_payouts`).
- **LucidPro consistency 35% vs 40%**: different effective periods (accounts bought or reset
  before/after 11/28/2025, 3:00 PM EST), so they are not one requirement. This file describes an
  account bought after the change.
- **LucidFlex MLL 'locks once the trail is reached' vs 'adjusts when a payout is requested'**:
  two triggers for the same locked level (starting balance plus $100), and both are modelled in the
  funded trailing rule (`lock.on: [hwm, first_payout]`, the first one to fire wins); the payout rule
  keeps `threshold_after_payout: lock_on_first_payout` as well.
- **LucidDirect $25,000 'Initial Trail Balance None' on the DLL page vs $26,100 on the drawdown
  page**: the DLL page's column says when the DLL changes, and for this size there is no DLL to
  change; the drawdown page's trail governs the max loss and is what the file uses.
- **LucidPro/Flex/Direct evaluation pages vs the drawdown pages on the max loss**: identical
  tables.

## 8. Fees and the cost side

Evaluation and reset fees are genuinely unpublished: the help centre says 'one-time fee' and
'resets are not automatic or free' and never an amount, and the price list is on the
Cloudflare-blocked `lucidtrading.com`. No `fee` rule is carried, so `fees_usd` is zero and any
cost-dependent statistic is conditional. The fees page does state, for LucidPro, that there is
**no activation fee** and **no subscription or automatic rebilling**; those are modelled by the
absence of a charge, and the owner is asked below whether a zero-amount `fee` rule should be
written for them anyway.

## 9. Dated changes

- **LucidPro funded consistency 35% -> 40%**, for accounts purchased or reset on or after
  11/28/2025 at 3:00 PM EST (`20261122_art_pro_consistency.html`). The files carry 40%.
- **LucidDirect payout maximums** now have a `Payouts 4-5` tier; the v1 draft only had one cap.
- **LucidDaily** is a newer product (pages updated August 2026) and is not named in Allowed
  Trading Times, which is why its `flat_by` rule is an assumption (section 4).

## 10. News rules

- **LucidDaily funded**: no trading of U.S. high-impact ('red folder') news. Modelled as
  `news_restriction` with `effect: block`, no instrument filter, `pre_minutes: 1`, `post_minutes: 1`,
  `scope: all_trading` (the page forbids holding *and* opening inside the window),
  `flatten: before_window`, `action: fail` (a hard breach). The firm names no event type, so from
  round 2 the rule carries **every** U.S. high-impact type the calendar holds (`FOMC_STATEMENT`,
  `FOMC_PRESS_CONFERENCE`, `FOMC_MINUTES`, `CPI`, `NFP`, `PPI`): the direction of the rule is a
  restriction, so covering more types restricts the strategy more, and the alternative (carrying
  three types) would silently leave releases the firm bans unenforced. A press-conference or minutes
  date whose release hour no source states is reported by the engine as an uncovered event for that
  day (never as "no news"), which makes such an attempt's estimate `partial`. A U.S. high-impact
  release outside those six types (retail sales, GDP, ISM, ...) stays `other_us_high_impact_events`
  (material). The 16 LucidDaily files each carry it in the funded phase only, which is the phase the
  page names.
- **LucidPro, LucidFlex, LucidDirect**: 'Traders may enter or exit positions around scheduled or
  unscheduled news events on these plans without it being a breach', so no `news_restriction`
  rule is written. The absence is sourced (`20261122_art_other_b.html`), not silent.
- A news-trading violation also suspends on-demand payouts for 30 calendar days; that
  consequence lives in `on_demand_intraday_payouts` because on-demand payouts are unmodelled.

## 11. Compliance and execution

- **Automated trading and trade copiers are permitted** on every Lucid account type, so an
  automated strategy is *not* blocked by compliance here (unlike Apex). Recorded as a
  `compliance` rule with `action: none` so the absence of a ban is a sourced statement.
- **High-frequency trading is prohibited** with no quantitative threshold: `compliance` with
  `applies_to_execution: [automated]`, `materiality: material`, `action: block`. It gates
  practical eligibility for an HFT-like strategy, not the mechanical account.
- **Scaling into trades, DCA, genuine scalping and flipping are explicitly allowed**; recorded
  here rather than as rules, because a permission with no constraint models nothing.

## 12. How every quotation was verified

`uv run python` over all 44 files: for every attribution in the file (rules, pass conditions,
fees, `not_modeled`, conflicts, commissions) the snapshot named by `snapshot_sha256` is located
in the private snapshot directory, its sha256 recomputed and compared, and the quote searched
for in the file's bytes after (a) replacing every HTML tag with a space, (b) unescaping HTML
entities and (c) collapsing whitespace. Result at handback: see section 14.

## 13. Owner review checklist, per file

Grouped by what the owner must confirm. `assumptions` lists the ADR-0107 defaults the file
relies on; `conflicts` names the sensitivity scenarios.

### `lucid-lucidpro-100k-dll-off.v1.yaml`

- **Account / thresholds:** evaluation target $6,000; eval max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100); eval DLL none; max 6 mini / 60 micro; funded max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100); funded DLL none; max 6 mini / 60 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $3,100; min request $500; profit goal $750 since the last payout; no numeric per-request cap; caps by payout $2,500/$3,000; split 0.9; at most 5 payouts; threshold after a payout: unchanged; consistency 40% of the cycle's profit, gates the payout, best day since the last payout over the profit of the cycle (numerator and denominator windows declared separately).
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidpro-100k-dll-on.v1.yaml`

- **Account / thresholds:** evaluation target $6,000; eval max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100); eval DLL $1,800 soft; max 6 mini / 60 micro; funded max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100); funded DLL $1,800 soft; max 6 mini / 60 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $3,100; min request $500; profit goal $750 since the last payout; no numeric per-request cap; caps by payout $2,500/$3,000; split 0.9; at most 5 payouts; threshold after a payout: unchanged; consistency 40% of the cycle's profit, gates the payout, best day since the last payout over the profit of the cycle (numerator and denominator windows declared separately).
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidpro-150k-dll-off.v1.yaml`

- **Account / thresholds:** evaluation target $9,000; eval max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100); eval DLL none; max 10 mini / 100 micro; funded max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100); funded DLL none; max 10 mini / 100 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $4,600; min request $500; profit goal $1,000 since the last payout; no numeric per-request cap; caps by payout $3,000/$3,500; split 0.9; at most 5 payouts; threshold after a payout: unchanged; consistency 40% of the cycle's profit, gates the payout, best day since the last payout over the profit of the cycle (numerator and denominator windows declared separately).
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidpro-150k-dll-on.v1.yaml`

- **Account / thresholds:** evaluation target $9,000; eval max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100); eval DLL $2,700 soft; max 10 mini / 100 micro; funded max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100); funded DLL $2,700 soft; max 10 mini / 100 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $4,600; min request $500; profit goal $1,000 since the last payout; no numeric per-request cap; caps by payout $3,000/$3,500; split 0.9; at most 5 payouts; threshold after a payout: unchanged; consistency 40% of the cycle's profit, gates the payout, best day since the last payout over the profit of the cycle (numerator and denominator windows declared separately).
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidpro-25k-dll-off.v1.yaml`

- **Account / thresholds:** evaluation target $1,250; eval max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100); eval DLL none; max 2 mini / 20 micro; funded max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100); funded DLL none; max 2 mini / 20 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $1,100; min request $500; profit goal $250 since the last payout; no numeric per-request cap; caps by payout $1,000/$1,500; split 0.9; at most 5 payouts; threshold after a payout: unchanged; consistency 40% of the cycle's profit, gates the payout, best day since the last payout over the profit of the cycle (numerator and denominator windows declared separately).
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidpro-25k-dll-on.v1.yaml`

- **Account / thresholds:** evaluation target $1,250; eval max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100); eval DLL none; max 2 mini / 20 micro; funded max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100); funded DLL $600 soft; max 2 mini / 20 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $1,100; min request $500; profit goal $250 since the last payout; no numeric per-request cap; caps by payout $1,000/$1,500; split 0.9; at most 5 payouts; threshold after a payout: unchanged; consistency 40% of the cycle's profit, gates the payout, best day since the last payout over the profit of the cycle (numerator and denominator windows declared separately).
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `pro_25k_funded_dll_alternative` selects `600` USD on `funded_fixed_dll` with one alternative, `absent` (the daily-loss page's funded table shows `None` for this size): the sensitivity scenario drops the daily loss rule entirely, so confirm which page governs this size.

### `lucid-lucidpro-50k-dll-off.v1.yaml`

- **Account / thresholds:** evaluation target $3,000; eval max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100); eval DLL none; max 4 mini / 40 micro; funded max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100); funded DLL none; max 4 mini / 40 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $2,100; min request $500; profit goal $500 since the last payout; no numeric per-request cap; caps by payout $2,000/$2,500; split 0.9; at most 5 payouts; threshold after a payout: unchanged; consistency 40% of the cycle's profit, gates the payout, best day since the last payout over the profit of the cycle (numerator and denominator windows declared separately).
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidpro-50k-dll-on.v1.yaml`

- **Account / thresholds:** evaluation target $3,000; eval max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100); eval DLL $1,200 soft; max 4 mini / 40 micro; funded max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100); funded DLL $1,200 soft; max 4 mini / 40 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $2,100; min request $500; profit goal $500 since the last payout; no numeric per-request cap; caps by payout $2,000/$2,500; split 0.9; at most 5 payouts; threshold after a payout: unchanged; consistency 40% of the cycle's profit, gates the payout, best day since the last payout over the profit of the cycle (numerator and denominator windows declared separately).
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-100k-dll-off-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $6,000; eval max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100); eval DLL none; max 6 mini / 60 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 3 mini, $1,000+ -> 4 mini, $2,000+ -> 5 mini, $3,000+ -> 6 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $200; per-request max $2,500; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-100k-dll-off-cons50.v1.yaml`

- **Account / thresholds:** evaluation target $6,000; eval max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100); eval DLL none; max 6 mini / 60 micro; eval consistency 50% of total profit, gates the pass, window all time; funded max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 3 mini, $1,000+ -> 4 mini, $2,000+ -> 5 mini, $3,000+ -> 6 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $200; per-request max $2,500; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-100k-dll-on-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $6,000; eval max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100); eval DLL none; max 6 mini / 60 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 3 mini, $1,000+ -> 4 mini, $2,000+ -> 5 mini, $3,000+ -> 6 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $200; per-request max $2,500; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-100k-dll-on-cons50.v1.yaml`

- **Account / thresholds:** evaluation target $6,000; eval max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100); eval DLL none; max 6 mini / 60 micro; eval consistency 50% of total profit, gates the pass, window all time; funded max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 3 mini, $1,000+ -> 4 mini, $2,000+ -> 5 mini, $3,000+ -> 6 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $200; per-request max $2,500; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-150k-dll-off-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $9,000; eval max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100); eval DLL none; max 10 mini / 100 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 4 mini, $1,000+ -> 5 mini, $2,000+ -> 6 mini, $3,000+ -> 8 mini, $4,500+ -> 10 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $250; per-request max $3,000; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-150k-dll-off-cons50.v1.yaml`

- **Account / thresholds:** evaluation target $9,000; eval max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100); eval DLL none; max 10 mini / 100 micro; eval consistency 50% of total profit, gates the pass, window all time; funded max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 4 mini, $1,000+ -> 5 mini, $2,000+ -> 6 mini, $3,000+ -> 8 mini, $4,500+ -> 10 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $250; per-request max $3,000; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-150k-dll-on-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $9,000; eval max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100); eval DLL none; max 10 mini / 100 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 4 mini, $1,000+ -> 5 mini, $2,000+ -> 6 mini, $3,000+ -> 8 mini, $4,500+ -> 10 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $250; per-request max $3,000; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-150k-dll-on-cons50.v1.yaml`

- **Account / thresholds:** evaluation target $9,000; eval max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100); eval DLL none; max 10 mini / 100 micro; eval consistency 50% of total profit, gates the pass, window all time; funded max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 4 mini, $1,000+ -> 5 mini, $2,000+ -> 6 mini, $3,000+ -> 8 mini, $4,500+ -> 10 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $250; per-request max $3,000; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-25k-dll-off-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $1,250; eval max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100); eval DLL none; max 2 mini / 20 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 1 mini, $1,000+ -> 2 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $100; per-request max $1,000; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-25k-dll-off-cons50.v1.yaml`

- **Account / thresholds:** evaluation target $1,250; eval max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100); eval DLL none; max 2 mini / 20 micro; eval consistency 50% of total profit, gates the pass, window all time; funded max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 1 mini, $1,000+ -> 2 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $100; per-request max $1,000; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-25k-dll-on-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $1,250; eval max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100); eval DLL none; max 2 mini / 20 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 1 mini, $1,000+ -> 2 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $100; per-request max $1,000; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-25k-dll-on-cons50.v1.yaml`

- **Account / thresholds:** evaluation target $1,250; eval max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100); eval DLL none; max 2 mini / 20 micro; eval consistency 50% of total profit, gates the pass, window all time; funded max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 1 mini, $1,000+ -> 2 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $100; per-request max $1,000; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-50k-dll-off-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $3,000; eval max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100); eval DLL none; max 4 mini / 40 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 2 mini, $1,000+ -> 3 mini, $2,000+ -> 4 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $150; per-request max $2,000; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-50k-dll-off-cons50.v1.yaml`

- **Account / thresholds:** evaluation target $3,000; eval max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100); eval DLL none; max 4 mini / 40 micro; eval consistency 50% of total profit, gates the pass, window all time; funded max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 2 mini, $1,000+ -> 3 mini, $2,000+ -> 4 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $150; per-request max $2,000; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-50k-dll-on-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $3,000; eval max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100); eval DLL none; max 4 mini / 40 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 2 mini, $1,000+ -> 3 mini, $2,000+ -> 4 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $150; per-request max $2,000; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-lucidflex-50k-dll-on-cons50.v1.yaml`

- **Account / thresholds:** evaluation target $3,000; eval max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100); eval DLL none; max 4 mini / 40 micro; eval consistency 50% of total profit, gates the pass, window all time; funded max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100; the lock fires at the trail or at the first payout, whichever comes first); funded DLL none; funded scaling $0+ -> 2 mini, $1,000+ -> 3 mini, $2,000+ -> 4 mini; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; profit goal $1 since the last payout; 5 profitable days of at least $150; per-request max $2,000; at most 50% of the balance; at most 50% of the withdrawable profit; split 0.9; at most 5 payouts; threshold after a payout: lock_on_first_payout.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-luciddaily-100k-dlloff-evaleod-fundedeod-cons30.v1.yaml`

- **Account / thresholds:** evaluation target $6,000; eval max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100); eval DLL none; max 6 mini / 60 micro; eval consistency 30% of total profit, gates the pass, window all time; funded max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100); funded DLL none; max 6 mini / 60 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $10,000 -> moved live.
- **Payouts:** buffer $3,100; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `session_close_taken_from_firm_wide_page`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.30` on `max_day_share` with 2 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-100k-dlloff-evalintraday-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $6,000; eval max loss $3,000 intraday trail, locks at +$3,100 (floor start+$100); eval DLL none; max 6 mini / 60 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $3,000 intraday trail, locks at +$3,100 (floor start+$100); funded DLL none; max 6 mini / 60 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $10,000 -> moved live.
- **Payouts:** buffer $3,100; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `session_close_taken_from_firm_wide_page`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.40` on `max_day_share` with 1 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-100k-dllon-evaleod-fundedintraday-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $6,000; eval max loss $3,000 EOD trail, locks at +$3,100 (floor start+$100); eval DLL $1,800 soft; max 6 mini / 60 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $3,000 intraday trail, locks at +$3,100 (floor start+$100); funded DLL $1,800 soft; max 6 mini / 60 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $10,000 -> moved live.
- **Payouts:** buffer $3,100; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `session_close_taken_from_firm_wide_page`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.40` on `max_day_share` with 1 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-100k-dllon-evalintraday-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $6,000; eval max loss $3,000 intraday trail, locks at +$3,100 (floor start+$100); eval DLL $1,800 soft; max 6 mini / 60 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $3,000 intraday trail, locks at +$3,100 (floor start+$100); funded DLL $1,800 soft; max 6 mini / 60 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $10,000 -> moved live.
- **Payouts:** buffer $3,100; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `session_close_taken_from_firm_wide_page`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.40` on `max_day_share` with 1 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-150k-dlloff-evaleod-fundedeod-cons30.v1.yaml`

- **Account / thresholds:** evaluation target $9,000; eval max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100); eval DLL none; max 10 mini / 100 micro; eval consistency 30% of total profit, gates the pass, window all time; funded max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100); funded DLL none; max 10 mini / 100 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $12,000 -> moved live.
- **Payouts:** buffer $4,600; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `session_close_taken_from_firm_wide_page`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.30` on `max_day_share` with 2 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-150k-dlloff-evalintraday-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $9,000; eval max loss $4,500 intraday trail, locks at +$4,600 (floor start+$100); eval DLL none; max 10 mini / 100 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $4,500 intraday trail, locks at +$4,600 (floor start+$100); funded DLL none; max 10 mini / 100 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $12,000 -> moved live.
- **Payouts:** buffer $4,600; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `session_close_taken_from_firm_wide_page`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.40` on `max_day_share` with 1 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-150k-dllon-evaleod-fundedintraday-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $9,000; eval max loss $4,500 EOD trail, locks at +$4,600 (floor start+$100); eval DLL $2,700 soft; max 10 mini / 100 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $4,500 intraday trail, locks at +$4,600 (floor start+$100); funded DLL $2,700 soft; max 10 mini / 100 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $12,000 -> moved live.
- **Payouts:** buffer $4,600; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `session_close_taken_from_firm_wide_page`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.40` on `max_day_share` with 1 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-150k-dllon-evalintraday-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $9,000; eval max loss $4,500 intraday trail, locks at +$4,600 (floor start+$100); eval DLL $2,700 soft; max 10 mini / 100 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $4,500 intraday trail, locks at +$4,600 (floor start+$100); funded DLL $2,700 soft; max 10 mini / 100 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $12,000 -> moved live.
- **Payouts:** buffer $4,600; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `session_close_taken_from_firm_wide_page`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.40` on `max_day_share` with 1 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-25k-dlloff-evaleod-fundedeod-cons30.v1.yaml`

- **Account / thresholds:** evaluation target $1,250; eval max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100); eval DLL none; max 2 mini / 20 micro; eval consistency 30% of total profit, gates the pass, window all time; funded max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100); funded DLL none; max 2 mini / 20 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $6,000 -> moved live.
- **Payouts:** buffer $1,100; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `session_close_taken_from_firm_wide_page`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.30` on `max_day_share` with 2 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-25k-dlloff-evalintraday-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $1,250; eval max loss $1,000 intraday trail, locks at +$1,100 (floor start+$100); eval DLL none; max 2 mini / 20 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $1,000 intraday trail, locks at +$1,100 (floor start+$100); funded DLL none; max 2 mini / 20 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $6,000 -> moved live.
- **Payouts:** buffer $1,100; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `session_close_taken_from_firm_wide_page`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.40` on `max_day_share` with 1 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-25k-dllon-evaleod-fundedintraday-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $1,250; eval max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100); eval DLL $600 soft; max 2 mini / 20 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $1,000 intraday trail, locks at +$1,100 (floor start+$100); funded DLL $600 soft; max 2 mini / 20 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $6,000 -> moved live.
- **Payouts:** buffer $1,100; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `session_close_taken_from_firm_wide_page`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.40` on `max_day_share` with 1 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-25k-dllon-evalintraday-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $1,250; eval max loss $1,000 intraday trail, locks at +$1,100 (floor start+$100); eval DLL $600 soft; max 2 mini / 20 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $1,000 intraday trail, locks at +$1,100 (floor start+$100); funded DLL $600 soft; max 2 mini / 20 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $6,000 -> moved live.
- **Payouts:** buffer $1,100; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `session_close_taken_from_firm_wide_page`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.40` on `max_day_share` with 1 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-50k-dlloff-evaleod-fundedeod-cons30.v1.yaml`

- **Account / thresholds:** evaluation target $3,000; eval max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100); eval DLL none; max 4 mini / 40 micro; eval consistency 30% of total profit, gates the pass, window all time; funded max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100); funded DLL none; max 4 mini / 40 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $8,000 -> moved live.
- **Payouts:** buffer $2,100; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `session_close_taken_from_firm_wide_page`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.30` on `max_day_share` with 2 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-50k-dlloff-evalintraday-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $3,000; eval max loss $2,000 intraday trail, locks at +$2,100 (floor start+$100); eval DLL none; max 4 mini / 40 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $2,000 intraday trail, locks at +$2,100 (floor start+$100); funded DLL none; max 4 mini / 40 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $8,000 -> moved live.
- **Payouts:** buffer $2,100; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `session_close_taken_from_firm_wide_page`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.40` on `max_day_share` with 1 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-50k-dllon-evaleod-fundedintraday-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $3,000; eval max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100); eval DLL $1,200 soft; max 4 mini / 40 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $2,000 intraday trail, locks at +$2,100 (floor start+$100); funded DLL $1,200 soft; max 4 mini / 40 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $8,000 -> moved live.
- **Payouts:** buffer $2,100; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `session_close_taken_from_firm_wide_page`, `unspecified_failure_frequency_is_intraday`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.40` on `max_day_share` with 1 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddaily-50k-dllon-evalintraday-cons40.v1.yaml`

- **Account / thresholds:** evaluation target $3,000; eval max loss $2,000 intraday trail, locks at +$2,100 (floor start+$100); eval DLL $1,200 soft; max 4 mini / 40 micro; eval consistency 40% of total profit, gates the pass, window all time; funded max loss $2,000 intraday trail, locks at +$2,100 (floor start+$100); funded DLL $1,200 soft; max 4 mini / 40 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar); max daily profit $8,000 -> moved live.
- **Payouts:** buffer $2,100; min request $500; profit goal $1 since the last payout; no numeric per-request cap; split 0.9; no maximum number of payouts; threshold after a payout: unchanged.
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news: flat 1 min before to 1 min after any of FOMC_STATEMENT/FOMC_PRESS_CONFERENCE/FOMC_MINUTES/CPI/NFP/PPI (all_trading, block, fail); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `session_close_taken_from_firm_wide_page`, `unspecified_target_frequency_is_eod`.
- **Conflicts:** `daily_eval_consistency_tier` selects `0.40` on `max_day_share` with 1 alternative(s) (sensitivity scenarios; confirm the stricter reading).

### `lucid-luciddirect-100k.v1.yaml`

- **Account / thresholds:** funded max loss $3,500 EOD trail, locks at +$3,600 (floor start+$100); funded DLL $2,100 soft; max 6 mini / 60 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; cycle goal $6,000; no numeric per-request cap; caps by payout $2,500/$2,500/$2,500/$3,000; split 0.9; at most 5 payouts; threshold after a payout: unchanged; consistency 20% of the cycle's profit, gates the payout, best day since the last payout over the profit of the cycle (numerator and denominator windows declared separately).
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-luciddirect-150k.v1.yaml`

- **Account / thresholds:** funded max loss $5,000 EOD trail, locks at +$5,100 (floor start+$100); funded DLL $3,000 soft; max 10 mini / 100 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; cycle goal $9,000; no numeric per-request cap; caps by payout $3,000/$3,000/$3,000/$3,500; split 0.9; at most 5 payouts; threshold after a payout: unchanged; consistency 20% of the cycle's profit, gates the payout, best day since the last payout over the profit of the cycle (numerator and denominator windows declared separately).
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-luciddirect-25k.v1.yaml`

- **Account / thresholds:** funded max loss $1,000 EOD trail, locks at +$1,100 (floor start+$100); funded DLL none; max 2 mini / 20 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; cycle goal $1,500; no numeric per-request cap; caps by payout $1,000/$1,000/$1,000/$1,000; split 0.9; at most 5 payouts; threshold after a payout: unchanged; consistency 20% of the cycle's profit, gates the payout, best day since the last payout over the profit of the cycle (numerator and denominator windows declared separately).
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

### `lucid-luciddirect-50k.v1.yaml`

- **Account / thresholds:** funded max loss $2,000 EOD trail, locks at +$2,100 (floor start+$100); funded DLL $1,200 soft; max 4 mini / 40 micro, no scaling; forced flat 4:45 PM ET, no entry before 6:00 PM ET, plus a session-relative flat 15 minutes before the scheduled session close (which is how an altered holiday close comes from the CME calendar).
- **Payouts:** buffer $0; min request $500; cycle goal $3,000; no numeric per-request cap; caps by payout $2,000/$2,000/$2,000/$2,500; split 0.9; at most 5 payouts; threshold after a payout: unchanged; consistency 20% of the cycle's profit, gates the payout, best day since the last payout over the profit of the cycle (numerator and denominator windows declared separately).
- **Fees / commissions:** evaluation and reset fee amounts unknown (no fee rule); commissions per side: ES/NQ/RTY/NKD/YM $1.75, MES/MNQ/M2K/MYM $0.50; whether that amount is all-in or excludes the exchange and NFA fees is **unknown** (no page says), declared as `commissions.components`: every component `unknown`, so the cash statistics stay conditional.
- **News / compliance:** news trading allowed (no restriction); automation permitted; HFT prohibited (material).
- **Assumptions:** `dll_reset_at_6pm_et_session_reopen`, `est_means_america_new_york`, `unspecified_failure_frequency_is_intraday`.
- **Conflicts:** none recorded (section 7 lists what was checked and found consistent).

## 14. Self-check at handback

Run on the 44 files at handback (round 2, 2026-11-22):

- `uv run crucible prop validate <file> --json` for every one of the 44 files: **44/44 pass**.
- The sweep of section 12: **44 files, 1047 attributions, 1047/1047 snapshot hashes matched,
  1047/1047 quotes found verbatim, RESULT: PASS**.
- `uv run crucible prop list --firm lucid --json`: 44 rulesets, `count: 44`, every one
  `unverified`, schema version 2, version 1, 44 distinct content hashes, and every one
  `evaluation_status: conditional_on_modeled_rules` (material unmodelled rules remain, section 5).
- Every file declares `schema_version: 2`; `rulesets/prop/INDEX.json` is regenerated by
  `tools.docgen` and is not touched by this migration.

## 15. Open questions for the owner

### Per-component costs (C7b fix, 2026-11-22)

`commissions.includes_exchange_and_regulatory_fees` is gone. The ruleset now declares, for each of the four components, whether the firm's per-side commission CONTAINS it (`included`), EXCLUDES it (`excluded`, so the run adds the dataset's amount for its participant type) or does not say (`unknown`, which is never a zero cost). All four keys are required, and no component may be inferred from another firm's page, another product or another participant type (ADR-0107 section 10 as amended).

| Component | Status in the files | Evidence kind | Evidence |
|---|---|---|---|
| `exchange` | `unknown` | `not_stated` | per-side table provided by the owner, pending independent verification; not stated to be all-in |
| `clearing` | `unknown` | `not_stated` | the same: the approved-products page names no clearing fee |
| `nfa` | `unknown` | `not_stated` | the same: the page names no NFA assessment |
| `other` | `unknown` | `not_stated` | the same: no other per-side charge is named |

An `excluded` component needs the run's participant PROFILE (`--participant-profile`): each fee row names the one classification dimension it needs (`cme_membership_status`, `nfa_assessment_eligibility`, ...), a dimension the profile leaves out makes that component a gap, and using the profile makes the cost `conditional`. An `unknown` component is a gap, and the only way to a number is a cost-assumption FILE the user passes, which prices exactly the root and component it names and is recorded by its SHA-256. The unverified owner reference in `docs/data/cme-exchange-fees.md` ("Estimated fee per side") is documentation only: the engine never reads it.

Owner questions, one per component the files declare `unknown`:

1. **exchange**: Does the per-side commission already contain the exchange fee, or is the exchange fee charged on top of it?
2. **clearing**: Does the per-side commission already contain the clearing fee, or is the clearing fee charged on top of it?
3. **nfa**: Does the per-side commission already contain the NFA assessment, or is it charged on top of it?
4. **other**: Is there any other per-side charge beside the commission, the exchange fee, the clearing fee and the NFA assessment?


1. The DLL page and the funded page disagree on the LucidPro $25,000 daily loss limit ($600 vs
   `None`). The file carries $600; confirm, or say that size has no DLL.
2. Is the LucidDaily evaluation consistency 40% (customization page, carried) or 50% (evaluation
   table)? The 50% reading is one sensitivity scenario.
3. What is the **LucidFlex DLL amount** per size? Until it is published the DLL-on Flex files
   cannot model the daily lock and are optimistic.
4. Evaluation and reset prices are needed before any net-cash claim. Should the stated zero
   activation and monthly fees be written as zero-amount `fee` rules?
5. Is the max-loss threshold tested intrabar on equity (carried) or only on the closing balance?
6. Is the DLL's reset clock the 6:00 PM ET session reopen (carried) or the calendar day?
7. Does 'EST' on every page mean US Eastern time with daylight saving (carried) or a fixed UTC-5
   clock?
8. Should the LucidDaily all-EOD configuration be the 30% tier (carried) when the page allows
   30% or 40%?
9. Which LucidPro configuration is canonical if only one may be the default: DLL on (the
   cheapest, with on-demand payouts) or DLL off?
10. **Are the commissions all-in?** No Lucid page says whether the per-side commission includes
    the CME exchange fee and the NFA assessment (section 6). Every file declares
    `commissions.components`: every component `unknown`, so net-cash statistics stay conditional.
    Confirm all-in (one number per side) or ex-fees (the exchange table is added), and the flag can
    become `true` or `false`.
11. **Is a holiday early close flat fifteen minutes before the altered close?** The session-relative
    rule takes the firm's own 15-minute offset between 4:45 PM ET and the 5:00 PM ET close and
    applies it to an earlier holiday close (`minutes_before_session_end: 15`). A firm that instead
    wants the position flat at the altered close itself, or earlier, changes one number.
12. **Does the LucidDaily news ban cover FOMC minutes, the FOMC press conference and PPI?** The
    firm names no release type ("U.S high impact red folder news"), so all six calendar types are
    enforced (section 10). If the firm means a narrower list, the extra types are one line each.
    The press-conference and some minutes dates state no hour, so an attempt through them reports a
    named coverage gap and a `partial` estimate rather than a window.

## 16. Unreadable pages

`lucidtrading.com` and its subdomains answer with a Cloudflare interstitial, not content: `/`
and `/pricing` returned HTTP 403 with `<title>Just a moment...</title>` (`20261122_blocked_home_
cloudflare.html`, `20261122_blocked_pricing_cloudflare.html`), as did `sitemap.xml` and
`robots.txt`. Nothing in any ruleset comes from that host, and it is why the evaluation and reset
fees are unmodelled. The help centre `support.lucidtrading.com` was fully readable, including the
commission table.


## 17. Owner review round (2026-11-24) and the reference run under the upper bound

The owner delegated questions F1-F33 of the review packet (`internal/reviews/lucid.md`) to the
coordinator on **2026-11-24**, and this round applied every decision to the 44 files. The files stay
`unverified`: no `crucible prop confirm` was run, no `*.verification.yaml` exists, no
`verification.status` was touched, and every decision line in the packet carries the coordinator's
recommendation and still waits for the owner. Nothing was re-sourced from a new page except the
Inactivity Policy snapshot of section 17.2, which the round fetched because a rule was added.

Every `assumption_kind: owner_decision` in the files names its question and the delegation ("The
owner review of 2026-11-24 (F<n>, delegated to the coordinator 2026-11-24)"), so a reviewer can check
one claim at a time.

| # | question | decision (delegated 2026-11-24) | what the files now declare |
|---|---|---|---|
| F1-F4 | `exchange`, `clearing`, `nfa`, `other` costs | stay `unknown`; the preliminary cross-firm analysis uses `rulesets/prop/cost_assumptions/upper_bound_v1.yaml` | unchanged: four `unknown` components with `evidence: not_stated` in 44/44 files |
| F5 | is the max loss tested intrabar? | yes, the more restrictive reading, as an owner decision | `assumption_kind: owner_decision` on the 64 `unspecified_failure_frequency_is_intraday` assumptions |
| F6 | EOD for the targets, and for the LucidDaily cap? | EOD stays `provisional_conservative` for both | the 16 `funded_daily_profit_cap` assumptions move from `section7_default` to `provisional_conservative`; the 40 profit targets already were |
| F7 | does "EST" mean a fixed UTC-5 clock? | no: `America/New_York` with daylight saving, owner decision | `est_means_america_new_york` is `owner_decision` in 52 rules, the rationale carrying the arithmetic of 17.1 |
| F8 | LucidDaily's close and reopen | the firm-wide 4:45 PM ET close and 6:00 PM ET reopen, owner decision | `session_close_taken_from_firm_wide_page` is `owner_decision` in 32 rules |
| F9 | when does the DLL reset? | at the 18:00 ET session reopen, owner decision, now sourced | `dll_reset_at_6pm_et_session_reopen` is `owner_decision` in 26 rules, each with the reopen sentence as a `supporting_source` |
| F10 | the LucidDaily consistency tier | the stricter tier stays primary, the existing scenarios unchanged | unchanged (`0.30` primary, `daily_eval_consistency_tier#0/#1`) |
| F11 | the 25K funded DLL (600 vs `None`) | 600 stays primary, the `None` scenario stays | unchanged (`pro_25k_funded_dll_alternative#0`) |
| F12 | `microscalping_ban` materiality | stays `material` | unchanged |
| F13 | evaluation and reset prices | stay OPEN: the owner question stands and net cash stays a `lower_bound` | unchanged (no `fee` rule; the question is repeated below) |
| F14 | the Flex DLL amount | stays OPEN; the 8 dll-on files say they are OPTIMISTIC and must NOT be confirmed until it is sourced | `flex_dll_amount` stays `material`, its description now leads with OPTIMISTIC and names the delegation |
| F15 | the six enforced news types | kept; every other U.S. high-impact release stays a declared material gap | unchanged: six `event_types` on 16 rules, `other_us_high_impact_events` (material) in 16 files |
| F16 | `cross_account_hedging` | `immaterial`, with the fact that would make it bind (Apex F10, O17) | `materiality: immaterial` plus `becomes_immaterial_if` in 44 files |
| F17 | the commission evidence label | stays `owner_provided`; the owner moves it to `official_quote` at confirmation | unchanged, with this note: section C of the packet checked the page's nine numbers against its sha256 and they agree line for line |
| F18 | the consistency boundary | "or less" / "at most" / "up to" -> `<=`; wording with no boundary -> strict `<` as `provisional_conservative`, quoting the words that decided it | the 12 LucidPro/LucidDirect payout rules move to `<` with the "below 40%/20%" sentence as a `supporting_source`; the 32 "or less"/"up to" rules keep `<=` |
| F19 | the two unattributed flat-by sentences | add both as `supporting_sources` | the automatic-close and no-failure sentences on the 84 flat-by-close rules |
| F20 | a material HFT ban that is not a condition | ENGINE CHANGE: a `material` + `action: block` rule on `automated` makes an automated run `eligible_conditional` and is listed among the conditions; a `critical` rule still blocks | no file change (the rule itself is unchanged); automated runs on all 44 files now report `eligible_conditional` with one condition |
| F21 | is the price-limit search the audit? | yes; the search terms and its result are recorded and no `not_modeled` entry is added | unchanged (no price-limit rule anywhere) |
| F22 | the 30-calendar-day inactivity rule | the page states it verbatim, so the rule is ADDED (30 calendar days, executed trades only, as for Topstep) | `eval_inactivity` / `funded_inactivity` in both phases of all 44 files, sourced to the Inactivity Policy page |
| F23 | is the Flex ladder keyed on profit? | yes; the basis is declared and a value on a rung follows the printed band | `funded_scaling_plan` gains the `flex_scaling_ladder_is_read_on_simulated_profit` `owner_decision` assumption and two `supporting_sources` |
| F24 | `promote_phase` with no next phase | it ENDS the attempt as a non-failure terminal outcome; checked in the engine and pinned by a test | no file change; documented in `docs/modules/prop.md` |
| F25 | `max_payouts: 5` | a lifetime count per account, the more restrictive reading | `max_payouts_is_a_lifetime_count_per_account` (`owner_decision`) on the 28 payout rules that carry it |
| F26 | the Direct first-cycle goal | the full goal stays primary; a "$1 net profit" scenario is not expressible (no source states $1 for Direct) | `direct_first_payout_needs_the_full_cycle_goal` (`owner_decision`) on the 4 Direct payout rules |
| F27 | the unused round-5 vocabulary | no action beyond F16, F19 and F20 | reported, not edited |
| F28 | do Lucid evaluations expire? | no: a sourced absence, and H stays the analyst's horizon | unchanged (`max_calendar_days: null`, `max_trading_days: null`), see 17.1 |
| F29 | `partial` versus excluding dates | `partial` is right; never exclude dates | unchanged |
| F30 | is the Flex payout floor per day? | per day, and the words that show it are quoted | `flex_payout_day_floor_is_per_day` (`owner_decision`) plus the "5 separate days" sentence as a `supporting_source` on 16 rules |
| F31 | the entry-block note's clock | render it in the rule's own timezone, with a test | engine fix (`until 17:00 ET`, not `until 21:00`); no file change |
| F32 | the rules the run never reaches | no action (C7c) | reported, not edited |
| F33 | the three unattributed bases | (a) and (b) become `supporting_sources`; (c) the 15-minute offset stays an explicit derivation note | the reopen sentence on the 26 DLL rules and the 84 flat-by-close rules; the offset is stated in the early-close rule's description and in section 4, unchanged |

### 17.1 What the round answered that was not a file edit

- **F7, the arithmetic.** "4:45 PM EST" read as a fixed UTC-5 offset is 21:45 UTC all year. The CME
  equity-index session closes at 17:00 ET, which is 22:00 UTC in winter and 21:00 UTC in summer, so
  the fixed offset is 15 minutes before the close in winter and **45 minutes after it** in summer:
  the firm would be flattening accounts whose session had already ended. The cutoff is therefore read
  as `America/New_York`, 4:45 PM local all year. A sensitivity scenario for the fixed clock is NOT
  expressible: `scenarios()` builds one scenario per `conflicts` alternative and switches ONE field on
  ONE rule, while the alternative is a different `time` **and** `tz` on 52 rules at once. It stays an
  owner question, not a modelled scenario.
- **F21, the price-limit audit.** The search accepted as the audit: every saved page under
  `internal/prop_snapshots/lucid/` (94 `.html`/`.txt` files: the 2026-11-22 set, the 2026-11-24
  re-fetch of the 34 cited URLs and the new inactivity page) was searched case-insensitively for
  `price limit`, `2%`, `2 %`, `percent price`, `price band` and `volatility`. **Result:
  `price limit`, `2 %`, `percent price`, `price band` and `volatility` do not occur at all, and
  every `2%` hit (7 per page, 630 in all) is a CSS colour value — `hsl(221, 49%, 62%)` in the
  page's own stylesheet — never rule text.** No page states a price limit or a volatility
  restriction, so no `not_modeled` entry is added: a declared gap would assert the firm has one.
- **F24, `promote_phase` with no next phase.** Checked in the engine: `PropAccountOverlay` sets the
  phase's outcome to `pass`, records the event, transitions the lifecycle to `passed_terminal` and
  reports the account closed, so `simulate_attempt` ends the attempt there and never enters a phase
  that does not exist. A position still open is flattened at that close. Reaching the LucidDaily cap
  is therefore a PASS (a non-failure terminal class), never a fail, and the attempt never continues
  past it. Documented in `docs/modules/prop.md` and pinned by
  `test_a_profit_cap_on_the_last_phase_ends_the_attempt_as_a_pass_never_a_fail`. No fix was needed.
- **F28, no expiry.** The absence is sourced by what the pages say and do not say: the LucidPro,
  LucidFlex and LucidDaily evaluation pages state the target, the max loss, the DLL and the size and
  name **no access period**, no end date and no timer. The only dated limit on any cited page is the
  LucidPro consistency change (an effective date, not an expiry), and the one 30-day clock is the
  inactivity rule now modelled. Every evaluation phase therefore keeps `max_calendar_days: null` and
  `max_trading_days: null`, and the reference run uses the analyst's **H = 20** trade dates.
- **F29, `partial`.** Accepted as the right answer for a cross-firm comparison: excluding the dates
  whose news coverage is incomplete would silently narrow the window and bias the estimate, while
  `partial` states what is unmodelled and leaves the number honest. No date is excluded.
- **F26, the "$1 net profit" scenario.** Not expressible for the same reason as F7: a sensitivity
  scenario is a `conflicts` alternative with its own `source`, and no LucidDirect page states "$1"
  (that wording is LucidFlex's positive-net-profit gate). Declaring one would invent a citation, so
  the full first-cycle goal stays primary and the reading sits in the rule's own `owner_decision`
  assumption.
- **F14, the estimate status.** Checked, not assumed: a LucidFlex dll-on file reports
  `estimate_status: partial`, because the material `flex_dll_amount` gap is declared and does reach
  the label a reader sees. Such a file is therefore never `complete` or plain `conditional`, and the
  8 dll-on files must not be confirmed until the amount is sourced.
- **F17, the commission label.** The blocked host is why the label cannot move on its own: the
  evaluation and reset prices live on the Cloudflare-blocked `lucidtrading.com`, and the label is the
  owner's statement about the whole commission block. Section C of the packet checked the nine
  per-side numbers against the official page's sha256 and found them identical, so the only thing
  missing is the owner's own `crucible prop confirm`, at which point the label moves to
  `official_quote` and no number changes.
- **F33c, the 15-minute offset.** It stays a DERIVATION, never a quote: 4:45 PM ET is the firm's own
  fifteen minutes before the scheduled 5:00 PM ET (16:00 Chicago) equity-index close, and the same
  fifteen minutes is applied to an earlier holiday close. It is stated in the early-close rule's
  description and in section 4, and it is the owner's to change (one number).

### 17.2 A new snapshot, and the self-check after the round

The Inactivity Policy page was cited by no file before this round, so it had no snapshot in the
2026-11-22 set. The round fetched it once from the public help centre with `curl`, a descriptive user
agent and the crawl delay honoured:

| url | snapshot | sha256 | retrieved_at | http |
|---|---|---|---|---|
| `https://support.lucidtrading.com/en/articles/11404632-inactivity-policy` | `20261124_art_11404632-inactivity-policy.html` | `4c693383bf9ed3e9c5407819abe0fff958d8d6ed4411438426102e2a8871833a` | 2026-11-24T15:56:33Z | 200 |

The self-check after the round, run the way section 12 describes:

- `uv run crucible prop validate <file> --json` for every one of the 44 files: **44/44 pass**.
- The sweep of section 12 (`crucible.prop.sources.check_sources`, snapshot root
  `D:\proyectos\crucible-notes\internal\prop_snapshots\lucid`): **44 files, 1469 attributions (1047
  before the round), 1469/1469 snapshot hashes matched, 1469/1469 quotes found verbatim, 0 synthetic,
  RESULT: PASS**.
- `uv run crucible prop list --firm lucid --json`: 44 rulesets, every one `unverified`, schema
  version 2, version 1, 44 distinct content hashes, every one
  `evaluation_status: conditional_on_modeled_rules` (the material entries of section 5 remain).

### 17.3 The ES 2024 reference run under the upper bound (H = 20), both modes

`crucible futures prop` on `examples/futures/es_sma_cross.yaml`, prepared exactly as section E.1 of
the packet prepared it (window 2024-01-02 .. 2024-12-31, warmup 5 trade dates, `flat_by_close: false`,
`allow_unverified_sessions: true`), with `--cost-assumption
rulesets/prop/cost_assumptions/upper_bound_v1.yaml`, `payout_policy: max_eligible`,
`CRUCIBLE_DATA_STORE=D:/proyectos/crucible/data/processed`, a temporary `CRUCIBLE_HOME` and a
temporary artifacts root per mode. Nothing was written to the user's Crucible home.

The ruleset is the packet's own file, `lucid-luciddaily-50k-dlloff-evaleod-fundedeod-cons30`, whose
content hash is now `8385927baa038f8788eeff9e01a2a61cdc6b64237c0622a20995ee953f4abb0b` (the packet ran
`23223760ebe1dbdd7580b28208ba7acff79f1d62c42d3e6bd4d6d05b980a518b`, the file before this round).

| measure | `automated` | `manual` |
|---|---|---|
| artifact / evaluation id | `PRP-704ce7f71358c2b5` | `PRP-3d2790d639bc0a88` |
| starts / complete | 253 / 234 | 253 / 234 |
| outcomes | fail 253, pass 0, timeout 0, horizon 0, censored 0 | identical |
| `breached_rule` | `eval_trailing_drawdown` 253 | identical |
| probability field | `conditional_pass_probability`, `definitive: false` | identical |
| value (bounds) | 0.0 (0.0 .. 0.0) | identical |
| interval | `available`, 0.0 .. 0.0 (block bootstrap, 1000 resamples, 95%, block 20, 234 observations) | identical |
| effective independent attempts | 11.7 | identical |
| estimate status | `partial` | identical |
| `cost_bound` / `cost_status` | `upper` / `conditional`, no gaps | identical |
| commission / bound per side | 1.75 + 3.02 (exchange 2.00, clearing 0.50, NFA 0.02, other 0.50) = 4.77 | identical |
| cash status / mean net cash | `lower_bound` / 0.000000 USD | identical |
| `min_buffer_usd` over the 253 starts | -35.88 .. -0.02 | identical |
| coverage gaps | `coverage_gap_starts` 183 of 253 starts | identical |
| **practical eligibility** | **`eligible_conditional`**, 1 condition, 0 mechanical passes | **`eligible`**, 0 conditions |

**The only column that differs between the two modes is `practical_eligibility`, and the only column
that differs from the packet is its value for `automated`.** The packet reported `eligible` with zero
conditions in both modes; the material HFT ban is now listed as the condition
`compliance_hft_prohibited: High-frequency trading (a high volume of orders submitted and executed
within extremely short time frames) is prohibited: ...`, which is the engine change of F20. Every other
number reproduces the packet's run: 253 starts, 234 complete, 253 failures on the evaluation's
trailing max loss, a pass probability of 0.0 under the upper-bound cost file, the `partial` and
`lower_bound` labels, and 0.000000 USD of net cash because no fee is modelled. Neither mode produced a
pass, so `conditionally_valid_passes` and `practically_valid_passes` are both 0 (F32: this run says
nothing about the pass path).

The two runs differ in exactly one column of `attempts.parquet`
(`practical_eligibility`/`practical_eligibility_conditions`), which is the difference the engine
change was meant to produce, and in nothing else.

One label also moved because of the round's DECLARATIONS rather than the engine: the estimate
reasons no longer list `cross_account_hedging` among the material unmodeled rules. F16 made it
`immaterial`, so it is still reported with its `becomes_immaterial_if`, but it no longer weakens the
estimate and is no longer one of the material rules named in the reason sentence. The packet's
material list for this file therefore loses one name and gains none.
