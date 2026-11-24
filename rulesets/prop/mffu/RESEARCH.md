# MyFundedFutures - prop-firm research notes (C7b, `firm_slug: mffu`, schema v2, vocabulary round 2)

20 rulesets, all `verification.status: unverified`: only the owner confirms a ruleset (`crucible prop confirm`, an interactive TTY step). Every value below is quoted from an official public page saved byte-for-byte under `D:\proyectos\crucible-notes\internal\prop_snapshots\mffu\`; a value the page does not state is either a named `assumption` or a `not_modeled` entry, never a guess.

## 0. What changed, and in which pass

The schema-v2 migration:

- Every rule declares `evidence`, `comparison`, `action`, its `basis`/`hwm_basis`, its `evaluated`/`mode`/`observed` frequency and its own day unit; the C7a implicit forms (`severity`, `consequence`, `on_excess`) are gone.
- `commissions` is present in every file: per side, per root, in USD (section 2).
- `reset: {time: 18:00:00, tz: America/New_York}` is the rule-day boundary everywhere: the firm's own Globex open (`Trades may be placed beginning at 6:00 PM EST when the Globex session opens`) and, on Rapid EOD, its own DLL reset (`The Daily Loss Limit resets daily at 6:00 PM ET`). No page states a different session boundary.
- News, compliance, daily-profit caps, inactivity, payout ceilings and the payouts' since-last-payout windows moved from `not_modeled` prose into typed rules (section 8).

Vocabulary round 2 (the count of files it touched is in each bullet):

- `commissions.components`: **round 2 declared every component `unknown`**; the owner review of 2026-11-24 settled the reading (section 12, F.1-F.5): the instrument list's subtitle is an explicit statement of what the Total Cost Round Trip column contains, so `exchange` and `nfa` are `included` on that subtitle (the treatment Topstep's included components get) and `clearing` and `other` stay `unknown` because it does not name them. Under the owner's upper bound one ES side is therefore 2.34 + 0.50 + 0.50 = 3.34 USD, not 5.36 (section 2).
- `news_restriction.effect: block` in the 12 files that carry a news rule, and `FOMC_MINUTES` added to their `event_types`: all four T1 types the firm names are now in the economic calendar (section 3).
- `lock.on` is a list everywhere (`['hwm']`, `['first_payout']`), including the conflict values that override a lock, because a bare `on: hwm` is refused by schema version 2.
- `payout.max_usd: unknown` in the 4 Rapid intraday files: the ceiling is unpublished, and `unknown` is never `unlimited`. The `unspecified_rapid_per_request_payout_ceiling_is_unlimited` assumption and the `payout_ceiling_not_published` entry are gone; the payout and the cash statistics report `upper_bound` instead (section 8).
- `flat_by` is session-relative in all 20 files (`minutes_before_session_end: 50`): 17:00 ET is the session end the CME table gives, so the firm's 4:10 PM ET is 50 minutes before it, and a half day's 13:15 ET close moves the flat to 12:25 ET. The fixed 4:10 PM clock and its 6:00 PM reopen are gone: the session-relative form now blocks new entries from the flat instant until the scheduled session close, so the firm's "trading hours are between 6:00pm EST through 4:10pm EST" stays enforced and the `holiday_early_close` entry changed shape (sections 7 and 8).
- `consistency` in the 5 Builder files declares the numerator and denominator windows separately (`numerator_window: since_last_payout`, `denominator_window: current_cycle`), because the firm states the best day and the total profit both "in the cycle".
- Not used, and why: `activity_requirement` (no MFFU page requires N qualifying days in a rolling window: the firm has an inactivity rule and a minimum trading days rule instead); `payout.min_new_profit_share_of_request` (no page bounds a request by a share of new profit); `payout.threshold_after_payout: set_threshold` (the `lock.on: first_payout` lock already freezes the threshold at the explicit level the pages state, and declaring both would say the same thing twice); a conflict alternative of `absent` (no MFFU conflict has a reading under which the rule does not exist - each one is a value both pages state, section 5); `news_restriction.effect: contract_cap` (MFFU bans the position outright, it never sizes it down).


## 1. Snapshots used

Every file below is the raw HTTP response, saved unchanged under `D:\proyectos\crucible-notes\internal\prop_snapshots\mffu\`; `sha256` is of those bytes. Pages fetched for this pass (marked `(fetched this pass)`): the EOD and intraday drawdown articles and the payout policy overview, at 05:46Z on 2026-11-22, because the earlier pass saved their text without recording a fetch instant. Every other page is the first pass's bytes, unchanged.

| snapshot | url | sha256 |
|---|---|---|
| `20261122_art_activation.html` | https://help.myfundedfutures.com/en/articles/12398151-does-myfundedfutures-charge-activation-fees | `7fa012bd73c93736c5440c3fe57720d168dc8efb8a07c7c698f9e03e82ca1263` |
| `20261122_art_builder100k.html` | https://help.myfundedfutures.com/en/articles/17005296-builder-plan-100k-comprehensive-guide | `973496a3d63082466f05d9667d7f252caf1d08f2aff7fe9bee17cd5da7b35bca` |
| `20261122_art_builder150k.html` | https://help.myfundedfutures.com/en/articles/17035331-builder-plan-150k-comprehensive-guide | `4f20f4d6d27d8c8f8b0d750d23b9338881c63e987289ba8dd7ddbf90c7a975fd` |
| `20261122_art_builder25k.html` | https://help.myfundedfutures.com/en/articles/17036130-builder-plan-25k-a-comprehensive-look | `cbec3d8f1d900fc6b2b82633725c1863c01419d7558261eba98f658cdba396b4` |
| `20261122_art_builder50k.html` | https://help.myfundedfutures.com/en/articles/14290805-builder-plan-50k-a-comprehensive-guide | `d90f19870009262260721a1b650bbc6d0d191c07bc3947a4f0a214ae0d9864c2` |
| `20261122_art_consistency.html` | https://help.myfundedfutures.com/en/articles/11994562-consistency-rule-at-my-fundedfutures | `50d6e06b972c6766aeb0814d41e488c30c6fca6132b49957bf8a4ee48eca6d40` |
| `20261122_art_cross.html` | https://help.myfundedfutures.com/en/articles/10244682-cross-instrument-policy | `d13d3e63aa20ba76987bea8ad5d4a12fac64c34ecdd1e70c2e726d716d305238` |
| `20261122_art_eval_params.html` | https://help.myfundedfutures.com/en/articles/8528339-understanding-evaluation-parameters-at-myfundedfutures | `89d443e8cb7b6603f98f353b27ed95e4260c86ff075986e42862566036df5703` |
| `20261122_art_fairplay.html` | https://help.myfundedfutures.com/en/articles/8444599-fair-play-and-prohibited-trading-practices | `29dac8bf2f268f5a1959ae5d612a9c17aeb51c0fb2d11074d22f3d92c8c8e9d9` |
| `20261122_art_hedging.html` | https://help.myfundedfutures.com/en/articles/12011241-hedging-what-you-should-know | `671a46f7f3849afe15ae3a98179acb2234a804da88b0838a1225c6fb6d851139` |
| `20261122_art_inactivity.html` | https://help.myfundedfutures.com/en/articles/16596524-inactivity-rule-one-time-payment-model | `c6d23e74eb62033bfdd8cd6508458aac8b5c9a8ae771e27318fdb6e881f91598` |
| `20261122_art_instruments_b.html` | https://help.myfundedfutures.com/en/articles/9735811-futures-instrument-list | `61a15116c3e36c1daead0587c59d2a558f34a74f42172f40728eac85aae60901` |
| `20261122_art_intraday_dd_b.html` | https://help.myfundedfutures.com/en/articles/12802721-intraday-drawdown-explained | `4739236e145f82adbc50d4af37b118bb466eaa0d604c2bb2bc39c18a434f1302` |
| `20261122_art_news.html` | https://help.myfundedfutures.com/en/articles/8230009-news-trading-policy | `661236c1900074748970098a9bf681db14d0e5dc4e31119a6e54ca32f091ee4c` |
| `20261122_art_payout_policy_b.html` | https://help.myfundedfutures.com/en/articles/13745661-payout-policy-overview-best-and-fastest-prop-firm-payouts | `3a5efb0be5289b1cea751ee3dc0e5b7dabe103236e14c34a868f0396f4d8b037` |
| `20261122_art_pricelimit.html` | https://help.myfundedfutures.com/en/articles/9698984-2-price-limit-rule | `57a9706131ad161e9d151fbf10dd2012292d1c64960349dbb742e60593363370` |
| `20261122_art_pro_comprehensive.html` | https://help.myfundedfutures.com/en/articles/17573707-comprehensive-look-into-redesigned-pro-plan | `3103fcc4ad149e15f561deddf01e6310282d572e29e09b63d03d58558ae3b220` |
| `20261122_art_rapid100k.html` | https://help.myfundedfutures.com/en/articles/13286542-rapid-plan-100k-a-comprehensive-look | `946888f0fa272ba7d7b54485b89c5ccc6ef17d8070685d0423c517ba781ad561` |
| `20261122_art_rapid150k.html` | https://help.myfundedfutures.com/en/articles/13286582-rapid-plan-150k-a-comprehensive-look | `d86108738654727a8c584530f6cc2646e4a443d91da67967316598f05b7e9b7e` |
| `20261122_art_rapid25k.html` | https://help.myfundedfutures.com/en/articles/14116402-rapid-plan-25k-a-comprehensive-look | `1bcfa513ac6d70c2cac3270ffd9632453cf16836d4110f4faae15829a47f128f` |
| `20261122_art_rapid50k.html` | https://help.myfundedfutures.com/en/articles/13134709-rapid-plan-50k-a-comprehensive-look | `1f3b45eb01e8ed72f26b1c202716fc7086baecc89c5b1f49c4c3394f7b2ad94c` |
| `20261122_art_rapid_live.html` | https://help.myfundedfutures.com/en/articles/13134718-understanding-rapid-live | `cef8f971f85772d14fdffd25f505f3a79d4e0b620b4d60b7b3c332b230e1ef2b` |
| `20261122_art_rapideod25k.html` | https://help.myfundedfutures.com/en/articles/16727601-rapid-eod-25k-a-comprehensive-look | `987bcc978b78b7795be4621d7916542972da1d6ebe871f664837ffdde4a37caa` |
| `20261122_art_rapideod50k.html` | https://help.myfundedfutures.com/en/articles/16158363-rapid-eod-50k-a-comprehensive-look | `15a07710881f58bb6bc2ebf3057ca9e516ce26286c3203bce7e7e8b622e521f6` |
| `20261122_art_rapideod_dll.html` | https://help.myfundedfutures.com/en/articles/18337038-rapid-eod-with-dll-a-detailed-look | `286280ff888bd5754ae4f4fc440904b5c75a1fbfc82888cc4472b22c8c23e9e5` |
| `20261122_art_studio_guide.html` | https://help.myfundedfutures.com/en/articles/17589665-studio-plans-a-comprehensive-guide | `2269cede593644d2af3d513aeb16c6a88bec3cf05410d0015fcb7bb41ef42b2f` |
| `20261122_art_times.html` | https://help.myfundedfutures.com/en/articles/9558251-permitted-times-to-trade | `7a945cf52a94820af413c95e6fcdb381fe51b4e8039bae4f7d46e63bc13e2b98` |
| `20261122_plans_builder_b.html` | https://myfundedfutures.com/plans/builder | `72fa484fecb11be45b25da987df47d45ec77780c07c282a54f2697f94263aa75` |
| `20261122_plans_pro_b.html` | https://myfundedfutures.com/plans/pro | `d182befccacf0d95187509762ec637cd524d70b91b69cd46e807f23ad8f7bdeb` |
| `20261122_plans_rapid.html` | https://myfundedfutures.com/plans/rapid | `27ba198fe6b350e4929b8bc471cf3661315ae9324ddc7698c514451c6229f569` |
| `20261122_plans_rapid_eod_b.html` | https://myfundedfutures.com/plans/rapid-eod | `4461f54888ee4a59bd1e9fbafed780412531d2b77fb3709e12c30451bbb0173b` |






## 2. Commissions

MFFU publishes **no commission-only schedule and no platform-specific commission page**. What it does publish, on the official futures instrument list, is a **Total Cost Round Trip** column per contract, and the article's own subtitle describes the list as one that "Includes Contract Specifications, Commissions, and Trading Fees". One round trip is two sides, so `per_side_usd` is that figure divided by two:

| root | Total Cost Round Trip | per side (USD) |
|---|---|---|
| ES | $4.68 | 2.34 |
| NQ | $4.68 | 2.34 |
| RTY | $4.68 | 2.34 |
| YM | $5.76 | 2.88 |
| NKD | $6.22 | 3.11 |
| MES | $1.90 | 0.95 |
| MNQ | $1.90 | 0.95 |
| MYM | $1.90 | 0.95 |
| M2K | $1.90 | 0.95 |

**The components (owner decision, F.1-F.5, delegated to the coordinator 2026-11-24).** The subtitle is an explicit firm statement of what the column includes: "Includes Contract Specifications, Commissions, and Trading Fees". "Trading Fees" standardly denotes the exchange fee and the NFA assessment, so the two are declared `included` on that subtitle, exactly as Topstep's included components are (`exchange` and `nfa`, `evidence: official_quote`, with the subtitle as their `text`). The subtitle does not name clearing, so `clearing` and `other` stay `unknown` - the conservative reading, never a zero cost:

| component | status | evidence | what the page says |
|---|---|---|---|
| commission | known (the per-side table above) | `official_quote` | `Total Cost Round Trip`, subtitle "Includes Contract Specifications, Commissions, and Trading Fees" |
| `exchange` | `included` | `official_quote` | "Trading Fees" in that subtitle, read as the exchange fee |
| `nfa` | `included` | `official_quote` | the same sentence, read as the NFA assessment |
| `clearing` | `unknown` | `not_stated` | the subtitle never names clearing |
| `other` | `unknown` | `not_stated` | the subtitle names no other per-side charge |

**The per-side bound.** With `exchange` and `nfa` inside the firm's own figure and two gaps left, `rulesets/prop/cost_assumptions/upper_bound_v1.yaml` fills only clearing and other: an ES side is **2.34 + 0.50 + 0.50 = 3.34 USD** (MES 0.95 + 0.25 + 0.25 = 1.45). The earlier reading, all four components `unknown`, charged 5.36 per side, i.e. 2.3x the firm's own 4.68 round trip. `tests/unit/test_prop_mffu_rulesets.py` pins the 3.34 against the committed bound file, and the reference run of section 12.1 reports it.

Source: `https://help.myfundedfutures.com/en/articles/9735811-futures-instrument-list`, snapshot `20261122_art_instruments_b.html`, sha256 `61a15116c3e36c1daead0587c59d2a558f34a74f42172f40728eac85aae60901`, retrieved 2026-11-22T01:59:33Z. The quotation carried by every file is the table's CME, COMEX and CBOT rows from the E-mini NASDAQ row through the Micro E-mini Dow row, verbatim; the all-in reading, the owner decision and the 3.34 arithmetic are stated in each file's `section` note and comment. No page states a platform-dependent difference (the schedule is per instrument, not per platform), so `commissions.platform` is null in every file; separate platform licence or data fees are the platform's, not MFFU's, and are not modeled.

## 3. News rules

The news policy (`https://help.myfundedfutures.com/en/articles/8230009-news-trading-policy`, snapshot `20261122_art_news.html`, sha256 `661236c1900074748970098a9bf681db14d0e5dc4e31119a6e54ca32f091ee4c`) prohibits, on **Rapid Sim Funded** and **Pro Sim Funded** accounts, any open position or order from 2 minutes before to 2 minutes after a Tier 1 release, and requires positions to be flattened at least two minutes before it ("positions must be closed by 8:28:00 or earlier, and may only be reopened after 8:32:00"). Evaluations and Builder plans are unrestricted; Rapid EOD Sim Funded accounts are restricted too (every Rapid EOD page states `T1 News Trading No` / `News Trading Not Allowed`), and Studio allows news outright.

Every file also declares `discretionary_news_trading_practices` (material): the policy prohibits straddles/strangles around an immediate news burst and masking a news trade as a standard strategy "for all news releases", which is a judgement about intent and cannot be enforced from bars or from a calendar window.

Modeled as `news_restriction` in the funded phase of the 12 Rapid, Rapid EOD and Pro files: `event_types: [FOMC_STATEMENT, FOMC_MINUTES, CPI, NFP]`, `pre_minutes: 2`, `post_minutes: 2`, `scope: all_trading`, `flatten: before_window`, `effect: block`, `action: flatten_and_block`, all instruments. Round 2 closed the old gap: the firm's Tier 1 list names **FOMC Meetings**, **FOMC Minutes**, the **Employment Report** and **CPI**, and `docs/data/econ-events.md` now carries `FOMC_STATEMENT`, `FOMC_MINUTES`, `NFP`, `CPI`, `PPI` and `FOMC_PRESS_CONFERENCE`, so all four named types are enforced. `FOMC_MINUTES` is enforced with the calendar's own `time_known` discipline: a minutes row whose hour no source states gets no invented window, its trade date is reported as outside news coverage, and the attempt's estimate becomes `partial` (never "no news"). The firm's EIA (energy traders) and Agricultural Reports windows stay in `not_modeled` as immaterial, because this ruleset's instrument set is equity index only. `PPI` and `FOMC_PRESS_CONFERENCE` are in the calendar but are not on the firm's Tier 1 list, so they are not restricted here. The Builder and Studio files carry no news rule: their own pages say news trading is allowed, and the policy's softer "Standard Trading Protocols" explicitly allow trading through non-Tier-1 releases.


## 4. Compliance rules

Every file carries five `compliance` rules from the fair play / prohibited practices article (`https://help.myfundedfutures.com/en/articles/8444599-...`, snapshot `20261122_art_fairplay.html`, sha256 `29dac8bf2f268f5a1959ae5d612a9c17aeb51c0fb2d11074d22f3d92c8c8e9d9`) and the hedging article: no high-frequency trading, automation only where it does not exploit the simulated fills, no fill/quote exploitation, no copy trading or account sharing, no hedging. **Automation is PERMITTED at MFFU**, so no compliance rule is `critical` and an automated strategy is `practical_eligibility: eligible` today - the opposite of Apex. The materiality is `material` on all five because a real submission has to survive them.

**Automation eligibility (F.6).** The automation rule is `material` with `action: block` on `[automated]` and **no `effect: condition`**, so `practical_eligibility(automated)` returns plain `eligible` and an automated run is indistinguishable from a manual one. The cross-firm Lucid decision (a `material` + `block` rule on automated execution makes automated eligibility `eligible_conditional`) is an ENGINE change that lands in a separate PR; until it merges, every MFFU automated run reports `eligible` and this round adds no `effect: condition` of its own (section 12, F.6).

**Copy trading (F.30).** The copy-trading article (`https://help.myfundedfutures.com/en/articles/10771500-copy-trading-at-myfundedfutures`, snapshot `20261124_copy-trading-at-myfundedfutures.html`, sha256 `b3c301571dc5d129f243e4102bf3e07109586c08f9fffd11ae115a5b1871f77c`) permits "copy trading across all account types" and names Tradesyncer and a group copier. It is a `supporting_source` on `compliance_no_copy_trading_or_account_sharing` in all 20 files, and it is what tells the two pages apart: copying ANOTHER trader is banned, a copier across the trader's own accounts is not, and that is what the `becomes_immaterial_if` of `cross_account_hedging` turns on.


## 5. Conflicts (both sources, the selected value, the alternative)

Applicability was checked in every case: same firm, plan, account size, phase, platform and effective period (all pages are live in the same retrieval window and no MFFU page states an effective date; `as_of`/`effective_from` are the retrieval date in every file). No recorded conflict has an `absent` reading: every one is a value two pages both state, so none of them drops a rule in its sensitivity scenario (ADR-0107 section 7).

- `mffu-builder-150k` - `builder_150k_payout_cap` (`payout`, field `max_usd`): selected `3500` from https://myfundedfutures.com/plans/builder, quoted: "Maximum Payout Per Cycle $1,000 $2,000 $3,000 $3,500"; alternative(s): `4500` from https://help.myfundedfutures.com/en/articles/17035331-builder-plan-150k-comprehensive-guide, quoted: "Maximum Payout Per Cycle $4,500". Same firm, plan (Builder), size (150k), phase (Sim Funded) and retrieval date. The plan page's full rules table gives $3,500 per payout cycle, and the 150K size guide's own worked example requests a $3,500 payout "within the $4,500 max" even though its table says $4,500. The selected value is the stricter one ($3,500); the guide's $4,500 is the sensitivity scenario builder_150k_payout_cap#0.
- `mffu-rapid-100k` - `rapid_funded_lock_level` (`funded_intraday_trailing_drawdown`, field `lock`): selected `{'on': [hwm], 'at_offset_usd': 3100, 'locked_offset_usd': 100}` from https://help.myfundedfutures.com/en/articles/13286542-rapid-plan-100k-a-comprehensive-look, quoted: "Max Loss Lock at $100 Once your trailing Max Loss reaches $100 , it locks there . From that point on, it does not trail anymore . You must always keep at least $100 in the account. If your balance goes below $100 → the account is breached ."; alternative(s): `{'on': [hwm], 'at_offset_usd': 3100, 'locked_offset_usd': 0}` from https://help.myfundedfutures.com/en/articles/12802721-intraday-drawdown-explained, quoted: "The drawdown will adjust with your account as you experience gains, but it will not exceed the starting balance.". Same firm, plan (Rapid), phase (Sim Funded) and retrieval date, all four sizes. The Rapid plan pages lock the trailing Max Loss at $100 above the starting balance ("Once your trailing Max Loss reaches $100 , it locks there") and the firm's EOD drawdown article repeats the $100 lock, while the intraday drawdown article says the threshold "will not exceed the starting balance". The selected value is the stricter one (a threshold $100 higher breaches sooner); the alternative stops the threshold at the starting balance and is the sensitivity scenario rapid_funded_lock_level#0.
- `mffu-rapid-150k` - `rapid_funded_lock_level` (`funded_intraday_trailing_drawdown`, field `lock`): selected `{'on': [hwm], 'at_offset_usd': 4600, 'locked_offset_usd': 100}` from https://help.myfundedfutures.com/en/articles/13286582-rapid-plan-150k-a-comprehensive-look, quoted: "Max Loss Lock at $100 Once your trailing Max Loss reaches $100 , it locks there . From that point on, it does not trail anymore . You must always keep at least $100 in the account. If your balance goes below $100 → the account is breached ."; alternative(s): `{'on': [hwm], 'at_offset_usd': 4600, 'locked_offset_usd': 0}` from https://help.myfundedfutures.com/en/articles/12802721-intraday-drawdown-explained, quoted: "The drawdown will adjust with your account as you experience gains, but it will not exceed the starting balance.". Same firm, plan (Rapid), phase (Sim Funded) and retrieval date, all four sizes. The Rapid plan pages lock the trailing Max Loss at $100 above the starting balance ("Once your trailing Max Loss reaches $100 , it locks there") and the firm's EOD drawdown article repeats the $100 lock, while the intraday drawdown article says the threshold "will not exceed the starting balance". The selected value is the stricter one (a threshold $100 higher breaches sooner); the alternative stops the threshold at the starting balance and is the sensitivity scenario rapid_funded_lock_level#0.
- `mffu-rapid-25k` - `rapid_funded_lock_level` (`funded_intraday_trailing_drawdown`, field `lock`): selected `{'on': [hwm], 'at_offset_usd': 1100, 'locked_offset_usd': 100}` from https://help.myfundedfutures.com/en/articles/14116402-rapid-plan-25k-a-comprehensive-look, quoted: "Max Loss Lock at $100 Once your trailing Max Loss reaches $100 , it locks there . From that point on, it does not trail anymore . You must always keep at least $100 in the account. If your balance goes below $100 → the account is breached ."; alternative(s): `{'on': [hwm], 'at_offset_usd': 1100, 'locked_offset_usd': 0}` from https://help.myfundedfutures.com/en/articles/12802721-intraday-drawdown-explained, quoted: "The drawdown will adjust with your account as you experience gains, but it will not exceed the starting balance.". Same firm, plan (Rapid), phase (Sim Funded) and retrieval date, all four sizes. The Rapid plan pages lock the trailing Max Loss at $100 above the starting balance ("Once your trailing Max Loss reaches $100 , it locks there") and the firm's EOD drawdown article repeats the $100 lock, while the intraday drawdown article says the threshold "will not exceed the starting balance". The selected value is the stricter one (a threshold $100 higher breaches sooner); the alternative stops the threshold at the starting balance and is the sensitivity scenario rapid_funded_lock_level#0.
- `mffu-rapid-50k` - `rapid_funded_lock_level` (`funded_intraday_trailing_drawdown`, field `lock`): selected `{'on': [hwm], 'at_offset_usd': 2100, 'locked_offset_usd': 100}` from https://help.myfundedfutures.com/en/articles/13134709-rapid-plan-50k-a-comprehensive-look, quoted: "Max Loss Lock at $100 Once your trailing Max Loss reaches $100 , it locks there . From that point on, it does not trail anymore . You must always keep at least $100 in the account. If your balance goes below $100 → the account is breached ."; alternative(s): `{'on': [hwm], 'at_offset_usd': 2100, 'locked_offset_usd': 0}` from https://help.myfundedfutures.com/en/articles/12802721-intraday-drawdown-explained, quoted: "The drawdown will adjust with your account as you experience gains, but it will not exceed the starting balance.". Same firm, plan (Rapid), phase (Sim Funded) and retrieval date, all four sizes. The Rapid plan pages lock the trailing Max Loss at $100 above the starting balance ("Once your trailing Max Loss reaches $100 , it locks there") and the firm's EOD drawdown article repeats the $100 lock, while the intraday drawdown article says the threshold "will not exceed the starting balance". The selected value is the stricter one (a threshold $100 higher breaches sooner); the alternative stops the threshold at the starting balance and is the sensitivity scenario rapid_funded_lock_level#0.
- `mffu-rapid-50k` - `rapid_funded_contract_limit` (`funded_max_contracts`, field `limit`): selected `2` from https://help.myfundedfutures.com/en/articles/10244682-cross-instrument-policy, quoted: "As an example, if you are trading a Rapid 50k sim funded plan, you start off with 2 contracts (2 minis OR 20 micros) due to the scaling plan."; alternative(s): `5` from https://help.myfundedfutures.com/en/articles/13134709-rapid-plan-50k-a-comprehensive-look, quoted: "Rapid Plan Evaluation Stage Account Parameters Parameters Rapid - $50,000 Profit Target $3,000 Maximum Loss Limit (EOD) $2,000 Daily Loss Limit None Max Contract 5 mini / 50 micro Consistency 50% (Eval Only) Minimum Trading Days 2 Days T1 News Trading Yes". Same firm, plan (Rapid 50k), phase (Sim Funded), same retrieval date. The Cross Instrument Policy says a Rapid 50k sim funded account starts with 2 contracts "due to the scaling plan"; the plan page and its product payload state 5 minis / 50 micros and publish no scaling fields. The selected value is the stricter one (2) and the plan-page value (5) is the sensitivity scenario rapid_funded_contract_limit#0. No step schedule is published, so the limit is held at 2 for the whole funded phase and that gap is in not_modeled.


## 6. Assumptions (named, each with its rationale)

Only the ADR-0107 section 7 defaults, each declared where the firm is silent, plus the readings the review round declared. There is no assumption of an unlimited payout cap any more (round 2): a cap the sources do not state is `unknown`, which labels the payout and the cash statistics `upper_bound`.

`assumption_kind` (ADR-0107, 2026-11-23 amendment) says what kind of default each one is. The review round of 2026-11-24 relabelled the two that are not section-7 defaults and added two readings (section 12):

- `daily_loss_basis_and_reference_are_not_published` (7 files) is `provisional_conservative`, not `section7_default`: ADR-0107 section 7 documents no default for the reference balance or the basis, only for the intraday observation (F.11).
- `pro_funded_micro_limit_read_as_mini_equivalence` (4 files) is `provisional_conservative`: reading the funded "3 mini / 3 micro" as mini-equivalents is a firm-specific reading no default covers (F.12).
- `session_relative_flat_follows_the_cme_early_close` (both `flat_by` rules of every file) is `owner_decision`: the firm states a fixed 4:10 PM ET clock and the model keeps the 50 minutes fixed against the CME session close, so a half day closes at 12:25 ET (F.31).
- `inactivity_closure_is_a_fail` (both inactivity rules of every file) is `provisional_conservative`: the page says the account "could be closed", its purchase-date condition (the one-time payment model effective 2026-08-25) is met by the new account this review simulates, and a Sim Funded breach forfeits the profits (F.27).
- `trading_day_is_a_trade_date_with_at_least_one_trade`, `unspecified_failure_frequency_is_intraday` and `unspecified_target_frequency_is_eod` are unchanged (F.13, F.14, F.15 accepted as they stand).

| assumption | files | rationale |
|---|---|---|
| `daily_loss_basis_and_reference_are_not_published` | 7 (mffu-builder-100k, mffu-builder-150k, mffu-builder-25k, mffu-builder-50k, ...) | The pages state the Daily Loss Limit amount, that hitting it is a soft pause and not a breach, and (Rapid EOD) that it resets daily at 6:00 PM ET. They state neither the reference balance nor the basis. Modeled on the rule-day's opening balance and on equity (open losses counted), the stricter combination, consistent with the firm's EOD drawdown article that counts open equity losses. Where no page states the reset clock (Builder) the rule-day boundary is the Globex open the firm states, 6:00 PM ET. |
| `pro_funded_micro_limit_read_as_mini_equivalence` | 4 (mffu-pro-100k, mffu-pro-150k, mffu-pro-50k, mffu-pro-50k-1day) | The Pro Sim-Funded table prints the micro cap equal to the mini cap (3 mini / 3 micro, 6 mini / 6 micro, 9 mini / 9 micro) while the Pro evaluation table prints 3 mini / 30 micro, and the firm states the 1:10 mini/micro equivalence everywhere. Modeled as 3, 6 and 9 mini-equivalents (so 30, 60 and 90 micros): a literal reading would forbid a funded Pro account from trading more than three micros, which no MFFU product does. |
| `trading_day_is_a_trade_date_with_at_least_one_trade` | 17 (mffu-builder-100k, mffu-builder-150k, mffu-builder-25k, mffu-builder-50k, ...) | No MFFU page defines a trading day. ADR-0107 section 7 default: a trading day is a trade date with at least one executed trade, so a rule-day with no fill does not count toward the minimum. |
| `unspecified_failure_frequency_is_intraday` | 3 (mffu-studio001-10k, mffu-studio002-20k, mffu-studio003-5k) | The Studio pages state the maximum loss as static and never state when it is tested. ADR-0107 section 7 default for a failure threshold: intraday, on equity, so an open position deep underwater breaches even if the account recovers by the close. |
| `unspecified_target_frequency_is_eod` | 20 (mffu-builder-100k, mffu-builder-150k, mffu-builder-25k, mffu-builder-50k, ...) | No MFFU page states when the profit target is judged. Recorded default for a pass condition whose frequency the firm does not state: tested at the rule-day close on the closed balance, so the trader passes no earlier than the end of the trade date and a same-day breach after the target was touched still counts. The intraday alternative would pass the phase the moment equity touched the target and would hide that later breach. |


## 7. `not_modeled`, by materiality

190 instances over 17 distinct names after the review round of 2026-11-24 (102 material, 88
immaterial, 0 critical; 24 instances carry `becomes_immaterial_if`).

### critical (0 rules)

### material (9 rules)

**`discretionary_news_trading_practices`** - 20 file(s): `mffu-builder-100k`, `mffu-builder-150k`, `mffu-builder-25k`, `mffu-builder-50k-addon`, `mffu-builder-50k`, `mffu-pro-100k`, `mffu-pro-150k`, `mffu-pro-50k-1day`, `mffu-pro-50k`, `mffu-rapid-100k`, `mffu-rapid-150k`, `mffu-rapid-25k`, `mffu-rapid-50k`, `mffu-rapideod-25k-dll`, `mffu-rapideod-25k`, `mffu-rapideod-50k-dll`, `mffu-rapideod-50k`, `mffu-studio001-10k`, `mffu-studio002-20k`, `mffu-studio003-5k`

> Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.

**`funded_scaling_schedule_unpublished`** - 4 file(s): `mffu-rapid-100k`, `mffu-rapid-150k`, `mffu-rapid-25k`, `mffu-rapid-50k`

> Material. The funded contract limit is held at its starting value for the whole phase, but the Cross Instrument Policy says a sim funded Rapid account starts lower "due to the scaling plan" and publishes no step schedule. If the real limit rises with profits the model understates the contracts a funded account may trade.

**`holiday_early_close_is_the_traders_job`** - 20 file(s): `mffu-builder-100k`, `mffu-builder-150k`, `mffu-builder-25k`, `mffu-builder-50k-addon`, `mffu-builder-50k`, `mffu-pro-100k`, `mffu-pro-150k`, `mffu-pro-50k-1day`, `mffu-pro-50k`, `mffu-rapid-100k`, `mffu-rapid-150k`, `mffu-rapid-25k`, `mffu-rapid-50k`, `mffu-rapideod-25k-dll`, `mffu-rapideod-25k`, `mffu-rapideod-50k-dll`, `mffu-rapideod-50k`, `mffu-studio001-10k`, `mffu-studio002-20k`, `mffu-studio003-5k`

> Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.

**`lifetime_payout_cap_100000`** - 4 file(s): `mffu-pro-100k`, `mffu-pro-150k`, `mffu-pro-50k-1day`, `mffu-pro-50k`

> Material. The $100,000 figure is stated both as a per-request cap ("Maximum Request in Sim-Funded stage: $100,000") and as a per-user lifetime cap whose excess is forfeited ("Maximum Payout (per user) $100,000", "Profits above $100,000 are forfeited"). Only the per-withdrawal cap is modeled; there is no lifetime cap in the engine, so a long funded attempt can report more net cash than the firm would pay, and the stricter per-user reading is the one a reader should apply.

**`payout_cadence_14_calendar_days`** - 4 file(s): `mffu-pro-100k`, `mffu-pro-150k`, `mffu-pro-50k-1day`, `mffu-pro-50k`

> Material. The Pro payout policy says "Request a payout every 14 calendar days from your first trade" while the plan article states the 14-day qualification only for the first payout. The first-payout gate is modeled (first_payout_after_calendar_days 14); a recurring calendar-day cadence is not expressible (min_days_since_last counts rule-days), so a simulated attempt can take a payout at every rule-day close after the first while the firm would require 14 calendar days between them.

> Review round 2026-11-24 (F.25): the cadence stays `not_modeled` material.

**`pro_buffer_withdrawal_while_in_buffer`** - 4 file(s): `mffu-pro-100k`, `mffu-pro-150k`, `mffu-pro-50k-1day`, `mffu-pro-50k`

> Material. The Pro payout policy allows a withdrawal BEFORE the buffer is fully cleared, up to 60% of the profits made. The payout vocabulary cannot express it: `withdrawable` is the balance minus the buffer and a non-positive withdrawable pays nothing, so every Pro file requires the whole buffer before any payout, and `max_share_of_withdrawable` applies a share to the post-buffer amount rather than to the profit while the buffer is uncleared. A trader who takes the 60% early holds less capital and a shorter distance to the drawdown threshold than this model (F.25).

**`consistency_target_over_two_max_daily_profit`** - 16 file(s): `mffu-builder-100k`, `mffu-builder-150k`, `mffu-builder-25k`, `mffu-builder-50k-addon`, `mffu-builder-50k`, `mffu-pro-100k`, `mffu-pro-150k`, `mffu-pro-50k`, `mffu-rapid-100k`, `mffu-rapid-150k`, `mffu-rapid-25k`, `mffu-rapid-50k`, `mffu-rapideod-25k-dll`, `mffu-rapideod-25k`, `mffu-rapideod-50k-dll`, `mffu-rapideod-50k`

> Material. The consistency page states the share measure these files model and, in its worked example, a second and stricter reading: the maximum profit a trader should achieve is the profit target divided by two. The share measure stays primary; the target/2 cap binds whenever total profit exceeds the target, and no field of the vocabulary expresses it exactly (`consistency.measure` is fixed to `best_day_profit/total_profit` and no rule kind compares one day's profit with the profit target), so it is declared instead of modelled - it produces NO sensitivity scenario (F.28).

> Review round 2026-11-24 (F.25): the cadence stays `not_modeled` material.

**`price_limit_2pct_prohibition`** - 20 file(s): `mffu-builder-100k`, `mffu-builder-150k`, `mffu-builder-25k`, `mffu-builder-50k-addon`, `mffu-builder-50k`, `mffu-pro-100k`, `mffu-pro-150k`, `mffu-pro-50k-1day`, `mffu-pro-50k`, `mffu-rapid-100k`, `mffu-rapid-150k`, `mffu-rapid-25k`, `mffu-rapid-50k`, `mffu-rapideod-25k-dll`, `mffu-rapideod-25k`, `mffu-rapideod-50k-dll`, `mffu-rapideod-50k`, `mffu-studio001-10k`, `mffu-studio002-20k`, `mffu-studio003-5k`

> Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.

**`sub_minute_holding_and_micro_scalping`** - 20 file(s): `mffu-builder-100k`, `mffu-builder-150k`, `mffu-builder-25k`, `mffu-builder-50k-addon`, `mffu-builder-50k`, `mffu-pro-100k`, `mffu-pro-150k`, `mffu-pro-50k-1day`, `mffu-pro-50k`, `mffu-rapid-100k`, `mffu-rapid-150k`, `mffu-rapid-25k`, `mffu-rapid-50k`, `mffu-rapideod-25k-dll`, `mffu-rapideod-25k`, `mffu-rapideod-50k-dll`, `mffu-rapideod-50k`, `mffu-studio001-10k`, `mffu-studio002-20k`, `mffu-studio003-5k`

> Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.

### immaterial (8 rules)

**`active_account_count_limit`** - 18 file(s): `mffu-builder-25k`, `mffu-builder-50k-addon`, `mffu-builder-50k`, `mffu-pro-100k`, `mffu-pro-150k`, `mffu-pro-50k`, `mffu-pro-50k-1day`, `mffu-rapid-100k`, `mffu-rapid-150k`, `mffu-rapid-25k`, `mffu-rapid-50k`, `mffu-rapideod-25k-dll`, `mffu-rapideod-25k`, `mffu-rapideod-50k-dll`, `mffu-rapideod-50k`, `mffu-studio001-10k`, `mffu-studio002-20k`, `mffu-studio003-5k`

> Immaterial. 2 Builder accounts per user. A single simulated attempt is one account, so the cap cannot change its outcome.

> Immaterial. 1 Builder account per user. A single simulated attempt is one account, so the cap cannot change its outcome.

> Immaterial. At most five active sim funded accounts for $25K/$50K and three across all plans for $100K/$150K. A single simulated attempt is one account, so the cap cannot change its outcome.

> Immaterial. At most three active Sim Funded accounts per trader. A single simulated attempt is one account, so the cap cannot change its outcome.

> Immaterial. One active Studio account at a time, evaluation or Sim Funded. A single simulated attempt is one account, so the cap cannot change its outcome.

> Immaterial. The Pro article states, effective 2026-11-23, one active Sim Funded Pro account at each size (50K, 100K, 150K), all three active at the same time. `becomes_immaterial_if`: becomes material if several accounts are simulated at once, since the cap decides how many Pro accounts one trader may hold (F.26, delegated to the coordinator 2026-11-24).

**`cross_account_hedging`** - 20 file(s): `mffu-builder-100k`, `mffu-builder-150k`, `mffu-builder-25k`, `mffu-builder-50k-addon`, `mffu-builder-50k`, `mffu-pro-100k`, `mffu-pro-150k`, `mffu-pro-50k-1day`, `mffu-pro-50k`, `mffu-rapid-100k`, `mffu-rapid-150k`, `mffu-rapid-25k`, `mffu-rapid-50k`, `mffu-rapideod-25k-dll`, `mffu-rapideod-25k`, `mffu-rapideod-50k-dll`, `mffu-rapideod-50k`, `mffu-studio001-10k`, `mffu-studio002-20k`, `mffu-studio003-5k`

> Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.

> `becomes_immaterial_if` (F.9, F.30): becomes material if several accounts, copy trading or coordinated strategies are simulated - a trade copier that mirrors one of the trader's own accounts onto another can hold opposite exposure on the same underlying across the two, which is exactly the cross-account hedge this entry does not model.

**`energy_and_agricultural_report_news_types`** - 12 file(s): `mffu-pro-100k`, `mffu-pro-150k`, `mffu-pro-50k-1day`, `mffu-pro-50k`, `mffu-rapid-100k`, `mffu-rapid-150k`, `mffu-rapid-25k`, `mffu-rapid-50k`, `mffu-rapideod-25k-dll`, `mffu-rapideod-25k`, `mffu-rapideod-50k-dll`, `mffu-rapideod-50k`

> Immaterial. The firm's Tier 1 list names FOMC Meetings, FOMC Minutes, the Employment Report and CPI for every trader, plus EIA (energy traders) and Agricultural Reports (agricultural traders). The four types for every trader are in the economic calendar and are enforced; EIA and the agricultural reports are not, and they cannot apply here because this ruleset's instrument set is equity index only.

**`five_payout_ladder_to_live`** - 5 file(s): `mffu-builder-100k`, `mffu-builder-150k`, `mffu-builder-25k`, `mffu-builder-50k-addon`, `mffu-builder-50k`

> Immaterial. After the 5th approved sim payout the account is promoted to a live brokerage seat, and a live breach triggers a 21-day cooldown. max_payouts 5 stops further sim payouts, but no rule kind promotes a phase on a payout count, so the ladder and the cooldown are not modeled.

**`live_eligibility_after_five_payouts`** - 3 file(s): `mffu-studio001-10k`, `mffu-studio002-20k`, `mffu-studio003-5k`

> Immaterial. A live account becomes available after 5 approved payouts or $5,000 requested, at 40% of the requested total capped at $2,000. That transition ends the simulated stage and is not a pass condition, so no rule kind expresses it.

**`live_transition_after_three_payouts`** - 4 file(s): `mffu-pro-100k`, `mffu-pro-150k`, `mffu-pro-50k-1day`, `mffu-pro-50k`

> Immaterial. Three consecutive payouts, or reaching the $100,000 payout cap, or a risk team invitation move the account to a live brokerage seat and end the simulated stage. No rule kind promotes a phase on a payout count, so the ladder is not modeled and an attempt that reaches it is reported as a funded survive.

**`live_transition_on_10k_session`** - 8 file(s): `mffu-rapid-100k`, `mffu-rapid-150k`, `mffu-rapid-25k`, `mffu-rapid-50k`, `mffu-rapideod-25k-dll`, `mffu-rapideod-25k`, `mffu-rapideod-50k-dll`, `mffu-rapideod-50k`

> Immaterial. A $10,000 single-session result moves the account to a live brokerage seat, which ends the simulated stage. The per-day cap is modeled (funded_daily_profit_cap_10000); the milestone transition itself has no rule kind, so an attempt that hits it is reported as a funded survive rather than a transition.

> Immaterial. The $10,000 single-session result also moves the account to a live seat, which ends the simulated stage (the Rapid EOD article says it follows the standard Rapid live rules). The per-day cap is modeled; the milestone transition has no rule kind.

**`reset_fee_amount`** - 8 file(s): `mffu-rapid-100k`, `mffu-rapid-150k`, `mffu-rapid-25k`, `mffu-rapid-50k`, `mffu-rapideod-25k-dll`, `mffu-rapideod-25k`, `mffu-rapideod-50k-dll`, `mffu-rapideod-50k`

> Immaterial. A breached Rapid evaluation can be reset for a fee the official pages never quantify, so the ruleset carries no reset fee and attempt cost accounting understates a second attempt bought with a reset.

> Immaterial. A breached Rapid EOD evaluation can be reset for a fee the official pages never quantify, so the ruleset carries no reset fee and attempt cost accounting understates a second attempt bought with a reset.


## 8. `not_modeled` entries removed because the vocabulary models them exactly

The schema-v2 migration:

- `t1_news_blackout_funded` -> the `news_restriction` rule (12 files), now with event types, the 2-minute pre/post window, `all_trading` scope and `flatten: before_window`.
- `inactivity_7_calendar_days` -> `inactivity` (`max_gap: 7`, `unit: calendar_days`, rolling window) in both phases of all 20 files.
- `funded_daily_profit_cap` (Studio) -> `daily_profit_cap` with `forfeit_excess` ($5,000 / $10,000 / $2,500).
- `auto_live_transition_10k_day` -> the forfeit half is now `funded_daily_profit_cap_10000`; only the stage-ending milestone stays `not_modeled`.
- `payout_14_calendar_day_qualification` and `payout_ceiling` facts -> `first_payout_after_calendar_days` (14 Pro / 1 Rapid / 2 Builder), `max_payouts: 5` (Builder), `min_profit_since_last_usd` (Rapid EOD 250/500, Builder 250/500/1,000/1,500), `min_traded_days` (Builder 2, since the last payout), `window: since_last_payout`, `threshold_after_payout: lock_on_first_payout` and `lock.on: [first_payout]` (Pro and Builder).
- `news_trading_allowed` (Builder, Studio) -> removed outright: the firm permits news trading there, so there is no rule to declare.

Vocabulary round 2 (this pass):

- `payout_ceiling_not_published` (4 Rapid intraday files) -> `payout.max_usd: unknown`, removed with the assumption it rested on. The gap is still reported, but by the engine (`upper_bound` on the payout and the cash statistics) instead of by a prose entry.
- `news_event_types_outside_the_calendar` (12 files) -> `FOMC_MINUTES` is enforced, so the entry became `energy_and_agricultural_report_news_types` at **immaterial**: the only T1 types the calendar does not carry are EIA and the agricultural reports, which apply to instrument classes this ruleset cannot trade.
- `holiday_early_close` (20 files) -> renamed `holiday_early_close_is_the_traders_job`, because the flat clock is now session-relative and does follow the calendar's early close; what remains is the other half of the firm's rule, that the firm does not liquidate anyone at a half-day close while `flat_by` liquidates for the trader.
- `no_entry_between_flat_and_the_globex_open` (20 files) was declared in this pass and then **removed**: `FlatBy.flat_and_reopen` now reopens a session-relative clock at the scheduled session close, so no entry is admitted between the flat instant and the close, which is the firm's trading hours ("between 6:00pm EST through 4:10pm EST") enforced without a prose entry.


## 9. Product matrix (regenerated from the YAML)

| file | program | size | target | eval drawdown | funded drawdown | DLL | contracts eval/funded | min days | consistency | buffer | payout min/max | split | daily cap | fee | news (funded) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `mffu-builder-100k.v1.yaml` | Builder | $100,000 | $6,000 @ eod | eod $3,000 (intraday) | eod $3,000 (intraday) | $1,750 soft_lock_until_reset | 6 / 6 | 1 | 50% (payout) | $3,100 | $1,000 / $3,000 | 80% | none | $282 | allowed |
| `mffu-builder-150k.v1.yaml` | Builder | $150,000 | $9,000 @ eod | eod $4,500 (intraday) | eod $4,500 (intraday) | $2,500 soft_lock_until_reset | 9 / 9 | 1 | 50% (payout) | $4,600 | $1,500 / $3,500 | 80% | none | $398 | allowed |
| `mffu-builder-25k.v1.yaml` | Builder | $25,000 | $1,500 @ eod | eod $1,000 (intraday) | eod $1,000 (intraday) | $600 soft_lock_until_reset | 2 / 2 | 1 | 50% (payout) | $1,100 | $250 / $1,000 | 80% | none | $105 | allowed |
| `mffu-builder-50k-addon.v1.yaml` | Builder (Add-On) | $50,000 | $3,000 @ eod | eod $1,500 (intraday) | eod $1,500 (intraday) | $1,000 soft_lock_until_reset | 4 / 4 | 1 | 50% (payout) | $1,600 | $500 / $2,000 | 80% | none | $125 | allowed |
| `mffu-builder-50k.v1.yaml` | Builder | $50,000 | $3,000 @ eod | eod $2,000 (intraday) | eod $2,000 (intraday) | $1,000 soft_lock_until_reset | 4 / 4 | 1 | 50% (payout) | $2,100 | $500 / $2,000 | 80% | none | $153 | allowed |
| `mffu-pro-100k.v1.yaml` | Pro | $100,000 | $6,000 @ eod | eod $3,000 (intraday) | eod $3,000 (intraday) | none | 6 / 6 | 2 | 50% (pass) | $3,100 | $1,000 / $100,000 | 80% | none | $401 | T1 blackout |
| `mffu-pro-150k.v1.yaml` | Pro | $150,000 | $9,000 @ eod | eod $4,500 (intraday) | eod $4,500 (intraday) | none | 9 / 9 | 2 | 50% (pass) | $4,600 | $1,000 / $100,000 | 80% | none | $557 | T1 blackout |
| `mffu-pro-50k-1day.v1.yaml` | Pro (One Day add-on) | $50,000 | $4,000 @ eod | eod $2,000 (intraday) | eod $2,000 (intraday) | none | 3 / 3 | 1 | - | $2,100 | $1,000 / $100,000 | 80% | none | $265 | T1 blackout |
| `mffu-pro-50k.v1.yaml` | Pro | $50,000 | $3,000 @ eod | eod $2,000 (intraday) | eod $2,000 (intraday) | none | 3 / 3 | 2 | 50% (pass) | $2,100 | $1,000 / $100,000 | 80% | none | $265 | T1 blackout |
| `mffu-rapid-100k.v1.yaml` | Rapid | $100,000 | $6,000 @ eod | eod $3,000 (intraday) | intraday $3,000 (intraday) | none | 8 / 8 | 2 | 50% (pass) | $3,100 | $500 / unknown | 90% | $10,000 forfeit_excess | $356 | T1 blackout |
| `mffu-rapid-150k.v1.yaml` | Rapid | $150,000 | $9,000 @ eod | eod $4,500 (intraday) | intraday $4,500 (intraday) | none | 10 / 10 | 2 | 50% (pass) | $4,600 | $500 / unknown | 90% | $10,000 forfeit_excess | $463 | T1 blackout |
| `mffu-rapid-25k.v1.yaml` | Rapid | $25,000 | $1,500 @ eod | eod $1,000 (intraday) | intraday $1,000 (intraday) | none | 3 / 3 | 2 | 50% (pass) | $1,100 | $500 / unknown | 90% | $10,000 forfeit_excess | $145 | T1 blackout |
| `mffu-rapid-50k.v1.yaml` | Rapid | $50,000 | $3,000 @ eod | eod $2,000 (intraday) | intraday $2,000 (intraday) | none | 5 / 2 | 2 | 50% (pass) | $2,100 | $500 / unknown | 90% | $10,000 forfeit_excess | $209 | T1 blackout |
| `mffu-rapideod-25k-dll.v1.yaml` | Rapid EOD (DLL add-on) | $25,000 | $1,500 @ eod | eod $1,000 (intraday) | eod $1,000 (intraday) | $500 soft_lock_until_reset | 2 / 2 | 4 | 30% (pass) | $1,100 | $500 / unlimited | 90% | $10,000 forfeit_excess | $162 | T1 blackout |
| `mffu-rapideod-25k.v1.yaml` | Rapid EOD | $25,000 | $1,500 @ eod | eod $1,000 (intraday) | eod $1,000 (intraday) | none | 2 / 2 | 4 | 30% (pass) | $1,100 | $500 / unlimited | 90% | $10,000 forfeit_excess | $162 | T1 blackout |
| `mffu-rapideod-50k-dll.v1.yaml` | Rapid EOD (DLL add-on) | $50,000 | $3,000 @ eod | eod $2,000 (intraday) | eod $2,000 (intraday) | $1,000 soft_lock_until_reset | 3 / 3 | 4 | 30% (pass) | $2,100 | $500 / unlimited | 90% | $10,000 forfeit_excess | $275 | T1 blackout |
| `mffu-rapideod-50k.v1.yaml` | Rapid EOD | $50,000 | $3,000 @ eod | eod $2,000 (intraday) | eod $2,000 (intraday) | none | 3 / 3 | 4 | 30% (pass) | $2,100 | $500 / unlimited | 90% | $10,000 forfeit_excess | $275 | T1 blackout |
| `mffu-studio001-10k.v1.yaml` | Studio #001 | $10,000 | $1,000 @ eod | static $500 (intraday) | static $500 (intraday) | none | 1 / 1 | none | - | $0 | $250 / unlimited | 80% | $5,000 forfeit_excess | $140 | allowed |
| `mffu-studio002-20k.v1.yaml` | Studio #002 | $20,000 | $2,000 @ eod | static $1,000 (intraday) | static $1,000 (intraday) | none | 2 / 2 | none | - | $0 | $250 / unlimited | 80% | $10,000 forfeit_excess | $280 | allowed |
| `mffu-studio003-5k.v1.yaml` | Studio #003 | $5,000 | $500 @ eod | static $250 (intraday) | static $250 (intraday) | none | 0.5 / 0.5 | none | - | $0 | $100 / unlimited | 80% | $2,500 forfeit_excess | $75 | allowed |

`DLL` is the soft-pause Daily Loss Limit (Rapid EOD DLL add-on, Builder); `consistency` names the phase it gates; `news (funded)` is the Tier 1 blackout, now with FOMC Minutes enforced. Contracts are the weighted limit (1 per mini, 0.1 per micro).

## 10. Owner review checklist, per file

Each file below lists the values the owner must confirm, grouped. `[official_quote]` = a verbatim quotation from an official page; `[assumption <name>]` = a stated default or a declared reading; conflicts and `not_modeled` entries are listed last. Each block now closes with the review round's decision line (2026-11-24, delegated to the coordinator; section 12): the coordinator recommends confirming every file as sourced and still waits for the owner's own `crucible prop confirm`, except the three Studio files, whose only source page answers HTTP 404.

### `mffu-builder-100k` - Builder $100,000

**account / thresholds**
- account size $100,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons none, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $100,000 -> funded $0
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=3000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 3100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.daily_loss_soft_pause` (daily_loss): amount_usd=1750, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `evaluation.eval_max_contracts` (max_contracts): limit=6, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=6000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=1, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_eod_trailing_drawdown` (trailing_drawdown): amount_usd=3000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [first_payout], 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `funded.daily_loss_soft_pause` (daily_loss): amount_usd=1750, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `funded.funded_max_contracts` (max_contracts): limit=6, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=282.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `funded.funded_consistency` (consistency): max_day_share=0.5, measure=best_day_profit/total_profit, applies_to=payout, window=since_last_payout, numerator_window=since_last_payout, denominator_window=current_cycle, comparison <= -> block_payout [official_quote]
- `funded.payout` (payout): min_days_since_last=2, min_profitable_days=0, min_traded_days=2, min_day_profit_usd=0, window=since_last_payout, buffer_usd=3100, split=0.8, min_usd=1000, max_usd=3000, max_payouts=5, min_profit_since_last_usd=1000, first_payout_after_calendar_days=2, threshold_after_payout=lock_on_first_payout, comparison >= -> withdraw [official_quote]

**assumptions**
- `daily_loss_basis_and_reference_are_not_published`
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `five_payout_ladder_to_live`: Immaterial. After the 5th approved sim payout the account is promoted to a live brokerage seat, and a live breach triggers a 21-day cooldown. max_payouts 5 stops further sim payouts, but no rule kind promotes a phase on a payout count, so the ladder and the cooldown are not modeled.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-builder-150k` - Builder $150,000

**account / thresholds**
- account size $150,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons none, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $150,000 -> funded $0
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=4500, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 4600, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.daily_loss_soft_pause` (daily_loss): amount_usd=2500, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `evaluation.eval_max_contracts` (max_contracts): limit=9, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=9000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=1, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_eod_trailing_drawdown` (trailing_drawdown): amount_usd=4500, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [first_payout], 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `funded.daily_loss_soft_pause` (daily_loss): amount_usd=2500, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `funded.funded_max_contracts` (max_contracts): limit=9, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=398.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `funded.funded_consistency` (consistency): max_day_share=0.5, measure=best_day_profit/total_profit, applies_to=payout, window=since_last_payout, numerator_window=since_last_payout, denominator_window=current_cycle, comparison <= -> block_payout [official_quote]
- `funded.payout` (payout): min_days_since_last=2, min_profitable_days=0, min_traded_days=2, min_day_profit_usd=0, window=since_last_payout, buffer_usd=4600, split=0.8, min_usd=1500, max_usd=3500, max_payouts=5, min_profit_since_last_usd=1500, first_payout_after_calendar_days=2, threshold_after_payout=lock_on_first_payout, comparison >= -> withdraw [official_quote]

**assumptions**
- `daily_loss_basis_and_reference_are_not_published`
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- `builder_150k_payout_cap` (`payout`, field `max_usd`): selected 3500, alternative(s) 4500

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `five_payout_ladder_to_live`: Immaterial. After the 5th approved sim payout the account is promoted to a live brokerage seat, and a live breach triggers a 21-day cooldown. max_payouts 5 stops further sim payouts, but no rule kind promotes a phase on a payout count, so the ladder and the cooldown are not modeled.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-builder-25k` - Builder $25,000

**account / thresholds**
- account size $25,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons none, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $25,000 -> funded $0
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=1000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 1100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.daily_loss_soft_pause` (daily_loss): amount_usd=600, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `evaluation.eval_max_contracts` (max_contracts): limit=2, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=1500, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=1, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_eod_trailing_drawdown` (trailing_drawdown): amount_usd=1000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [first_payout], 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `funded.daily_loss_soft_pause` (daily_loss): amount_usd=600, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `funded.funded_max_contracts` (max_contracts): limit=2, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=105.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `funded.funded_consistency` (consistency): max_day_share=0.5, measure=best_day_profit/total_profit, applies_to=payout, window=since_last_payout, numerator_window=since_last_payout, denominator_window=current_cycle, comparison <= -> block_payout [official_quote]
- `funded.payout` (payout): min_days_since_last=2, min_profitable_days=0, min_traded_days=2, min_day_profit_usd=0, window=since_last_payout, buffer_usd=1100, split=0.8, min_usd=250, max_usd=1000, max_payouts=5, min_profit_since_last_usd=250, first_payout_after_calendar_days=2, threshold_after_payout=lock_on_first_payout, comparison >= -> withdraw [official_quote]

**assumptions**
- `daily_loss_basis_and_reference_are_not_published`
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `active_account_count_limit`: Immaterial. 2 Builder accounts per user. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `five_payout_ladder_to_live`: Immaterial. After the 5th approved sim payout the account is promoted to a live brokerage seat, and a live breach triggers a 21-day cooldown. max_payouts 5 stops further sim payouts, but no rule kind promotes a phase on a payout count, so the ladder and the cooldown are not modeled.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-builder-50k-addon` - Builder (Add-On) $50,000

**account / thresholds**
- account size $50,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons smaller_max_loss, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $50,000 -> funded $0
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=1500, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 1600, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.daily_loss_soft_pause` (daily_loss): amount_usd=1000, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `evaluation.eval_max_contracts` (max_contracts): limit=4, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=3000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=1, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_eod_trailing_drawdown` (trailing_drawdown): amount_usd=1500, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [first_payout], 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `funded.daily_loss_soft_pause` (daily_loss): amount_usd=1000, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `funded.funded_max_contracts` (max_contracts): limit=4, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=125.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `funded.funded_consistency` (consistency): max_day_share=0.5, measure=best_day_profit/total_profit, applies_to=payout, window=since_last_payout, numerator_window=since_last_payout, denominator_window=current_cycle, comparison <= -> block_payout [official_quote]
- `funded.payout` (payout): min_days_since_last=2, min_profitable_days=0, min_traded_days=2, min_day_profit_usd=0, window=since_last_payout, buffer_usd=1600, split=0.8, min_usd=500, max_usd=2000, max_payouts=5, min_profit_since_last_usd=500, first_payout_after_calendar_days=2, threshold_after_payout=lock_on_first_payout, comparison >= -> withdraw [official_quote]

**assumptions**
- `daily_loss_basis_and_reference_are_not_published`
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `active_account_count_limit`: Immaterial. 1 Builder account per user. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `five_payout_ladder_to_live`: Immaterial. After the 5th approved sim payout the account is promoted to a live brokerage seat, and a live breach triggers a 21-day cooldown. max_payouts 5 stops further sim payouts, but no rule kind promotes a phase on a payout count, so the ladder and the cooldown are not modeled.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-builder-50k` - Builder $50,000

**account / thresholds**
- account size $50,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons none, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $50,000 -> funded $0
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=2000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 2100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.daily_loss_soft_pause` (daily_loss): amount_usd=1000, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `evaluation.eval_max_contracts` (max_contracts): limit=4, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=3000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=1, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_eod_trailing_drawdown` (trailing_drawdown): amount_usd=2000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [first_payout], 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `funded.daily_loss_soft_pause` (daily_loss): amount_usd=1000, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `funded.funded_max_contracts` (max_contracts): limit=4, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=153.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `funded.funded_consistency` (consistency): max_day_share=0.5, measure=best_day_profit/total_profit, applies_to=payout, window=since_last_payout, numerator_window=since_last_payout, denominator_window=current_cycle, comparison <= -> block_payout [official_quote]
- `funded.payout` (payout): min_days_since_last=2, min_profitable_days=0, min_traded_days=2, min_day_profit_usd=0, window=since_last_payout, buffer_usd=2100, split=0.8, min_usd=500, max_usd=2000, max_payouts=5, min_profit_since_last_usd=500, first_payout_after_calendar_days=2, threshold_after_payout=lock_on_first_payout, comparison >= -> withdraw [official_quote]

**assumptions**
- `daily_loss_basis_and_reference_are_not_published`
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `active_account_count_limit`: Immaterial. 1 Builder account per user. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `five_payout_ladder_to_live`: Immaterial. After the 5th approved sim payout the account is promoted to a live brokerage seat, and a live breach triggers a 21-day cooldown. max_payouts 5 stops further sim payouts, but no rule kind promotes a phase on a payout count, so the ladder and the cooldown are not modeled.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-pro-100k` - Pro $100,000

**account / thresholds**
- account size $100,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons none, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $100,000 -> funded $100,000
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=3000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 3100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.eval_max_contracts` (max_contracts): limit=6, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=6000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=2, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_eod_trailing_drawdown` (trailing_drawdown): amount_usd=3000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [first_payout], 'locked_threshold_usd': 100100}, comparison <= -> fail [official_quote]
- `funded.funded_max_contracts` (max_contracts): limit=6, comparison <= -> clip [assumption `pro_funded_micro_limit_read_as_mini_equivalence`]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `funded.funded_t1_news_blackout` (news_restriction): event_types=[FOMC_STATEMENT, FOMC_MINUTES, CPI, NFP], pre_minutes=2, post_minutes=2, scope=all_trading, flatten=before_window, effect=block, comparison >= -> flatten_and_block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=401.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `evaluation.eval_consistency` (consistency): max_day_share=0.5, measure=best_day_profit/total_profit, applies_to=pass, window=all_time, comparison <= -> promote_phase [official_quote]
- `funded.payout` (payout): min_days_since_last=0, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=all_time, buffer_usd=3100, split=0.8, min_usd=1000, max_usd=100000, max_payouts=None, min_profit_since_last_usd=0, first_payout_after_calendar_days=14, threshold_after_payout=lock_on_first_payout, comparison >= -> withdraw [official_quote]

**assumptions**
- `pro_funded_micro_limit_read_as_mini_equivalence`
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `energy_and_agricultural_report_news_types`: Immaterial. The firm's Tier 1 list names FOMC Meetings, FOMC Minutes, the Employment Report and CPI for every trader, plus EIA (energy traders) and Agricultural Reports (agricultural traders). The four types for every trader are in the economic calendar and are enforced; EIA and the agricultural reports are not, and they cannot apply here because this ruleset's instrument set is equity index only.
- material `payout_cadence_14_calendar_days`: Material. The Pro payout policy says "Request a payout every 14 calendar days from your first trade" while the plan article states the 14-day qualification only for the first payout. The first-payout gate is modeled (first_payout_after_calendar_days 14); a recurring calendar-day cadence is not expressible (min_days_since_last counts rule-days), so a simulated attempt can take a payout at every rule-day close after the first while the firm would require 14 calendar days between them.
- material `lifetime_payout_cap_100000`: Material. The $100,000 figure is stated both as a per-request cap ("Maximum Request in Sim-Funded stage: $100,000") and as a per-user lifetime cap whose excess is forfeited ("Maximum Payout (per user) $100,000", "Profits above $100,000 are forfeited"). Only the per-withdrawal cap is modeled; there is no lifetime cap in the engine, so a long funded attempt can report more net cash than the firm would pay, and the stricter per-user reading is the one a reader should apply.
- immaterial `live_transition_after_three_payouts`: Immaterial. Three consecutive payouts, or reaching the $100,000 payout cap, or a risk team invitation move the account to a live brokerage seat and end the simulated stage. No rule kind promotes a phase on a payout count, so the ladder is not modeled and an attempt that reaches it is reported as a funded survive.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-pro-150k` - Pro $150,000

**account / thresholds**
- account size $150,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons none, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $150,000 -> funded $150,000
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=4500, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 4600, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.eval_max_contracts` (max_contracts): limit=9, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=9000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=2, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_eod_trailing_drawdown` (trailing_drawdown): amount_usd=4500, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [first_payout], 'locked_threshold_usd': 150100}, comparison <= -> fail [official_quote]
- `funded.funded_max_contracts` (max_contracts): limit=9, comparison <= -> clip [assumption `pro_funded_micro_limit_read_as_mini_equivalence`]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `funded.funded_t1_news_blackout` (news_restriction): event_types=[FOMC_STATEMENT, FOMC_MINUTES, CPI, NFP], pre_minutes=2, post_minutes=2, scope=all_trading, flatten=before_window, effect=block, comparison >= -> flatten_and_block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=557.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `evaluation.eval_consistency` (consistency): max_day_share=0.5, measure=best_day_profit/total_profit, applies_to=pass, window=all_time, comparison <= -> promote_phase [official_quote]
- `funded.payout` (payout): min_days_since_last=0, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=all_time, buffer_usd=4600, split=0.8, min_usd=1000, max_usd=100000, max_payouts=None, min_profit_since_last_usd=0, first_payout_after_calendar_days=14, threshold_after_payout=lock_on_first_payout, comparison >= -> withdraw [official_quote]

**assumptions**
- `pro_funded_micro_limit_read_as_mini_equivalence`
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `energy_and_agricultural_report_news_types`: Immaterial. The firm's Tier 1 list names FOMC Meetings, FOMC Minutes, the Employment Report and CPI for every trader, plus EIA (energy traders) and Agricultural Reports (agricultural traders). The four types for every trader are in the economic calendar and are enforced; EIA and the agricultural reports are not, and they cannot apply here because this ruleset's instrument set is equity index only.
- material `payout_cadence_14_calendar_days`: Material. The Pro payout policy says "Request a payout every 14 calendar days from your first trade" while the plan article states the 14-day qualification only for the first payout. The first-payout gate is modeled (first_payout_after_calendar_days 14); a recurring calendar-day cadence is not expressible (min_days_since_last counts rule-days), so a simulated attempt can take a payout at every rule-day close after the first while the firm would require 14 calendar days between them.
- material `lifetime_payout_cap_100000`: Material. The $100,000 figure is stated both as a per-request cap ("Maximum Request in Sim-Funded stage: $100,000") and as a per-user lifetime cap whose excess is forfeited ("Maximum Payout (per user) $100,000", "Profits above $100,000 are forfeited"). Only the per-withdrawal cap is modeled; there is no lifetime cap in the engine, so a long funded attempt can report more net cash than the firm would pay, and the stricter per-user reading is the one a reader should apply.
- immaterial `live_transition_after_three_payouts`: Immaterial. Three consecutive payouts, or reaching the $100,000 payout cap, or a risk team invitation move the account to a live brokerage seat and end the simulated stage. No rule kind promotes a phase on a payout count, so the ladder is not modeled and an attempt that reaches it is reported as a funded survive.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-pro-50k-1day` - Pro (One Day add-on) $50,000

**account / thresholds**
- account size $50,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons one_day_pass, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $50,000 -> funded $50,000
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=2000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 2100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.eval_max_contracts` (max_contracts): limit=3, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=4000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=1, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_eod_trailing_drawdown` (trailing_drawdown): amount_usd=2000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [first_payout], 'locked_threshold_usd': 50100}, comparison <= -> fail [official_quote]
- `funded.funded_max_contracts` (max_contracts): limit=3, comparison <= -> clip [assumption `pro_funded_micro_limit_read_as_mini_equivalence`]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `funded.funded_t1_news_blackout` (news_restriction): event_types=[FOMC_STATEMENT, FOMC_MINUTES, CPI, NFP], pre_minutes=2, post_minutes=2, scope=all_trading, flatten=before_window, effect=block, comparison >= -> flatten_and_block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=265.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `funded.payout` (payout): min_days_since_last=0, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=all_time, buffer_usd=2100, split=0.8, min_usd=1000, max_usd=100000, max_payouts=None, min_profit_since_last_usd=0, first_payout_after_calendar_days=14, threshold_after_payout=lock_on_first_payout, comparison >= -> withdraw [official_quote]

**assumptions**
- `pro_funded_micro_limit_read_as_mini_equivalence`
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `energy_and_agricultural_report_news_types`: Immaterial. The firm's Tier 1 list names FOMC Meetings, FOMC Minutes, the Employment Report and CPI for every trader, plus EIA (energy traders) and Agricultural Reports (agricultural traders). The four types for every trader are in the economic calendar and are enforced; EIA and the agricultural reports are not, and they cannot apply here because this ruleset's instrument set is equity index only.
- material `payout_cadence_14_calendar_days`: Material. The Pro payout policy says "Request a payout every 14 calendar days from your first trade" while the plan article states the 14-day qualification only for the first payout. The first-payout gate is modeled (first_payout_after_calendar_days 14); a recurring calendar-day cadence is not expressible (min_days_since_last counts rule-days), so a simulated attempt can take a payout at every rule-day close after the first while the firm would require 14 calendar days between them.
- material `lifetime_payout_cap_100000`: Material. The $100,000 figure is stated both as a per-request cap ("Maximum Request in Sim-Funded stage: $100,000") and as a per-user lifetime cap whose excess is forfeited ("Maximum Payout (per user) $100,000", "Profits above $100,000 are forfeited"). Only the per-withdrawal cap is modeled; there is no lifetime cap in the engine, so a long funded attempt can report more net cash than the firm would pay, and the stricter per-user reading is the one a reader should apply.
- immaterial `live_transition_after_three_payouts`: Immaterial. Three consecutive payouts, or reaching the $100,000 payout cap, or a risk team invitation move the account to a live brokerage seat and end the simulated stage. No rule kind promotes a phase on a payout count, so the ladder is not modeled and an attempt that reaches it is reported as a funded survive.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-pro-50k` - Pro $50,000

**account / thresholds**
- account size $50,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons none, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $50,000 -> funded $50,000
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=2000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 2100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.eval_max_contracts` (max_contracts): limit=3, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=3000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=2, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_eod_trailing_drawdown` (trailing_drawdown): amount_usd=2000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [first_payout], 'locked_threshold_usd': 50100}, comparison <= -> fail [official_quote]
- `funded.funded_max_contracts` (max_contracts): limit=3, comparison <= -> clip [assumption `pro_funded_micro_limit_read_as_mini_equivalence`]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `funded.funded_t1_news_blackout` (news_restriction): event_types=[FOMC_STATEMENT, FOMC_MINUTES, CPI, NFP], pre_minutes=2, post_minutes=2, scope=all_trading, flatten=before_window, effect=block, comparison >= -> flatten_and_block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=265.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `evaluation.eval_consistency` (consistency): max_day_share=0.5, measure=best_day_profit/total_profit, applies_to=pass, window=all_time, comparison <= -> promote_phase [official_quote]
- `funded.payout` (payout): min_days_since_last=0, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=all_time, buffer_usd=2100, split=0.8, min_usd=1000, max_usd=100000, max_payouts=None, min_profit_since_last_usd=0, first_payout_after_calendar_days=14, threshold_after_payout=lock_on_first_payout, comparison >= -> withdraw [official_quote]

**assumptions**
- `pro_funded_micro_limit_read_as_mini_equivalence`
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `energy_and_agricultural_report_news_types`: Immaterial. The firm's Tier 1 list names FOMC Meetings, FOMC Minutes, the Employment Report and CPI for every trader, plus EIA (energy traders) and Agricultural Reports (agricultural traders). The four types for every trader are in the economic calendar and are enforced; EIA and the agricultural reports are not, and they cannot apply here because this ruleset's instrument set is equity index only.
- material `payout_cadence_14_calendar_days`: Material. The Pro payout policy says "Request a payout every 14 calendar days from your first trade" while the plan article states the 14-day qualification only for the first payout. The first-payout gate is modeled (first_payout_after_calendar_days 14); a recurring calendar-day cadence is not expressible (min_days_since_last counts rule-days), so a simulated attempt can take a payout at every rule-day close after the first while the firm would require 14 calendar days between them.
- material `lifetime_payout_cap_100000`: Material. The $100,000 figure is stated both as a per-request cap ("Maximum Request in Sim-Funded stage: $100,000") and as a per-user lifetime cap whose excess is forfeited ("Maximum Payout (per user) $100,000", "Profits above $100,000 are forfeited"). Only the per-withdrawal cap is modeled; there is no lifetime cap in the engine, so a long funded attempt can report more net cash than the firm would pay, and the stricter per-user reading is the one a reader should apply.
- immaterial `live_transition_after_three_payouts`: Immaterial. Three consecutive payouts, or reaching the $100,000 payout cap, or a risk team invitation move the account to a live brokerage seat and end the simulated stage. No rule kind promotes a phase on a payout count, so the ladder is not modeled and an attempt that reaches it is reported as a funded survive.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-rapid-100k` - Rapid $100,000

**account / thresholds**
- account size $100,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons none, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $100,000 -> funded $0
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=3000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 3100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.eval_max_contracts` (max_contracts): limit=8, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=6000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=2, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_intraday_trailing_drawdown` (trailing_drawdown): amount_usd=3000, mode=intraday, evaluated=intraday, basis=equity, hwm_basis=equity, lock={'on': [hwm], 'at_offset_usd': 3100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `funded.funded_max_contracts` (max_contracts): limit=8, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `funded.funded_t1_news_blackout` (news_restriction): event_types=[FOMC_STATEMENT, FOMC_MINUTES, CPI, NFP], pre_minutes=2, post_minutes=2, scope=all_trading, flatten=before_window, effect=block, comparison >= -> flatten_and_block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=356.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `evaluation.eval_consistency` (consistency): max_day_share=0.5, measure=best_day_profit/total_profit, applies_to=pass, window=all_time, comparison <= -> promote_phase [official_quote]
- `funded.funded_daily_profit_cap_10000` (daily_profit_cap): amount_usd=10000, basis=balance, evaluated=eod, comparison >= -> forfeit_excess [official_quote]
- `funded.payout` (payout): min_days_since_last=1, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=all_time, buffer_usd=3100, split=0.9, min_usd=500, max_usd=unknown, max_payouts=None, min_profit_since_last_usd=0, first_payout_after_calendar_days=1, threshold_after_payout=unchanged, comparison >= -> withdraw [official_quote]

**assumptions**
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- `rapid_funded_lock_level` (`funded_intraday_trailing_drawdown`, field `lock`): selected {'on': [hwm], 'at_offset_usd': 3100, 'locked_offset_usd': 100}, alternative(s) {'on': [hwm], 'at_offset_usd': 3100, 'locked_offset_usd': 0}

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `energy_and_agricultural_report_news_types`: Immaterial. The firm's Tier 1 list names FOMC Meetings, FOMC Minutes, the Employment Report and CPI for every trader, plus EIA (energy traders) and Agricultural Reports (agricultural traders). The four types for every trader are in the economic calendar and are enforced; EIA and the agricultural reports are not, and they cannot apply here because this ruleset's instrument set is equity index only.
- material `funded_scaling_schedule_unpublished`: Material. The funded contract limit is held at its starting value for the whole phase, but the Cross Instrument Policy says a sim funded Rapid account starts lower "due to the scaling plan" and publishes no step schedule. If the real limit rises with profits the model understates the contracts a funded account may trade.
- immaterial `active_account_count_limit`: Immaterial. At most five active sim funded accounts for $25K/$50K and three across all plans for $100K/$150K. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `reset_fee_amount`: Immaterial. A breached Rapid evaluation can be reset for a fee the official pages never quantify, so the ruleset carries no reset fee and attempt cost accounting understates a second attempt bought with a reset.
- immaterial `live_transition_on_10k_session`: Immaterial. A $10,000 single-session result moves the account to a live brokerage seat, which ends the simulated stage. The per-day cap is modeled (funded_daily_profit_cap_10000); the milestone transition itself has no rule kind, so an attempt that hits it is reported as a funded survive rather than a transition.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-rapid-150k` - Rapid $150,000

**account / thresholds**
- account size $150,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons none, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $150,000 -> funded $0
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=4500, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 4600, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.eval_max_contracts` (max_contracts): limit=10, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=9000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=2, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_intraday_trailing_drawdown` (trailing_drawdown): amount_usd=4500, mode=intraday, evaluated=intraday, basis=equity, hwm_basis=equity, lock={'on': [hwm], 'at_offset_usd': 4600, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `funded.funded_max_contracts` (max_contracts): limit=10, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `funded.funded_t1_news_blackout` (news_restriction): event_types=[FOMC_STATEMENT, FOMC_MINUTES, CPI, NFP], pre_minutes=2, post_minutes=2, scope=all_trading, flatten=before_window, effect=block, comparison >= -> flatten_and_block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=463.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `evaluation.eval_consistency` (consistency): max_day_share=0.5, measure=best_day_profit/total_profit, applies_to=pass, window=all_time, comparison <= -> promote_phase [official_quote]
- `funded.funded_daily_profit_cap_10000` (daily_profit_cap): amount_usd=10000, basis=balance, evaluated=eod, comparison >= -> forfeit_excess [official_quote]
- `funded.payout` (payout): min_days_since_last=1, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=all_time, buffer_usd=4600, split=0.9, min_usd=500, max_usd=unknown, max_payouts=None, min_profit_since_last_usd=0, first_payout_after_calendar_days=1, threshold_after_payout=unchanged, comparison >= -> withdraw [official_quote]

**assumptions**
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- `rapid_funded_lock_level` (`funded_intraday_trailing_drawdown`, field `lock`): selected {'on': [hwm], 'at_offset_usd': 4600, 'locked_offset_usd': 100}, alternative(s) {'on': [hwm], 'at_offset_usd': 4600, 'locked_offset_usd': 0}

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `energy_and_agricultural_report_news_types`: Immaterial. The firm's Tier 1 list names FOMC Meetings, FOMC Minutes, the Employment Report and CPI for every trader, plus EIA (energy traders) and Agricultural Reports (agricultural traders). The four types for every trader are in the economic calendar and are enforced; EIA and the agricultural reports are not, and they cannot apply here because this ruleset's instrument set is equity index only.
- material `funded_scaling_schedule_unpublished`: Material. The funded contract limit is held at its starting value for the whole phase, but the Cross Instrument Policy says a sim funded Rapid account starts lower "due to the scaling plan" and publishes no step schedule. If the real limit rises with profits the model understates the contracts a funded account may trade.
- immaterial `active_account_count_limit`: Immaterial. At most five active sim funded accounts for $25K/$50K and three across all plans for $100K/$150K. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `reset_fee_amount`: Immaterial. A breached Rapid evaluation can be reset for a fee the official pages never quantify, so the ruleset carries no reset fee and attempt cost accounting understates a second attempt bought with a reset.
- immaterial `live_transition_on_10k_session`: Immaterial. A $10,000 single-session result moves the account to a live brokerage seat, which ends the simulated stage. The per-day cap is modeled (funded_daily_profit_cap_10000); the milestone transition itself has no rule kind, so an attempt that hits it is reported as a funded survive rather than a transition.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-rapid-25k` - Rapid $25,000

**account / thresholds**
- account size $25,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons none, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $25,000 -> funded $0
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=1000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 1100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.eval_max_contracts` (max_contracts): limit=3, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=1500, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=2, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_intraday_trailing_drawdown` (trailing_drawdown): amount_usd=1000, mode=intraday, evaluated=intraday, basis=equity, hwm_basis=equity, lock={'on': [hwm], 'at_offset_usd': 1100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `funded.funded_max_contracts` (max_contracts): limit=3, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `funded.funded_t1_news_blackout` (news_restriction): event_types=[FOMC_STATEMENT, FOMC_MINUTES, CPI, NFP], pre_minutes=2, post_minutes=2, scope=all_trading, flatten=before_window, effect=block, comparison >= -> flatten_and_block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=145.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `evaluation.eval_consistency` (consistency): max_day_share=0.5, measure=best_day_profit/total_profit, applies_to=pass, window=all_time, comparison <= -> promote_phase [official_quote]
- `funded.funded_daily_profit_cap_10000` (daily_profit_cap): amount_usd=10000, basis=balance, evaluated=eod, comparison >= -> forfeit_excess [official_quote]
- `funded.payout` (payout): min_days_since_last=1, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=all_time, buffer_usd=1100, split=0.9, min_usd=500, max_usd=unknown, max_payouts=None, min_profit_since_last_usd=0, first_payout_after_calendar_days=1, threshold_after_payout=unchanged, comparison >= -> withdraw [official_quote]

**assumptions**
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- `rapid_funded_lock_level` (`funded_intraday_trailing_drawdown`, field `lock`): selected {'on': [hwm], 'at_offset_usd': 1100, 'locked_offset_usd': 100}, alternative(s) {'on': [hwm], 'at_offset_usd': 1100, 'locked_offset_usd': 0}

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `energy_and_agricultural_report_news_types`: Immaterial. The firm's Tier 1 list names FOMC Meetings, FOMC Minutes, the Employment Report and CPI for every trader, plus EIA (energy traders) and Agricultural Reports (agricultural traders). The four types for every trader are in the economic calendar and are enforced; EIA and the agricultural reports are not, and they cannot apply here because this ruleset's instrument set is equity index only.
- material `funded_scaling_schedule_unpublished`: Material. The funded contract limit is held at its starting value for the whole phase, but the Cross Instrument Policy says a sim funded Rapid account starts lower "due to the scaling plan" and publishes no step schedule. If the real limit rises with profits the model understates the contracts a funded account may trade.
- immaterial `active_account_count_limit`: Immaterial. At most five active sim funded accounts for $25K/$50K and three across all plans for $100K/$150K. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `reset_fee_amount`: Immaterial. A breached Rapid evaluation can be reset for a fee the official pages never quantify, so the ruleset carries no reset fee and attempt cost accounting understates a second attempt bought with a reset.
- immaterial `live_transition_on_10k_session`: Immaterial. A $10,000 single-session result moves the account to a live brokerage seat, which ends the simulated stage. The per-day cap is modeled (funded_daily_profit_cap_10000); the milestone transition itself has no rule kind, so an attempt that hits it is reported as a funded survive rather than a transition.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-rapid-50k` - Rapid $50,000

**account / thresholds**
- account size $50,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons none, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $50,000 -> funded $0
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=2000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 2100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.eval_max_contracts` (max_contracts): limit=5, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=3000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=2, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_intraday_trailing_drawdown` (trailing_drawdown): amount_usd=2000, mode=intraday, evaluated=intraday, basis=equity, hwm_basis=equity, lock={'on': [hwm], 'at_offset_usd': 2100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `funded.funded_max_contracts` (max_contracts): limit=2, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `funded.funded_t1_news_blackout` (news_restriction): event_types=[FOMC_STATEMENT, FOMC_MINUTES, CPI, NFP], pre_minutes=2, post_minutes=2, scope=all_trading, flatten=before_window, effect=block, comparison >= -> flatten_and_block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=209.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `evaluation.eval_consistency` (consistency): max_day_share=0.5, measure=best_day_profit/total_profit, applies_to=pass, window=all_time, comparison <= -> promote_phase [official_quote]
- `funded.funded_daily_profit_cap_10000` (daily_profit_cap): amount_usd=10000, basis=balance, evaluated=eod, comparison >= -> forfeit_excess [official_quote]
- `funded.payout` (payout): min_days_since_last=1, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=all_time, buffer_usd=2100, split=0.9, min_usd=500, max_usd=unknown, max_payouts=None, min_profit_since_last_usd=0, first_payout_after_calendar_days=1, threshold_after_payout=unchanged, comparison >= -> withdraw [official_quote]

**assumptions**
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- `rapid_funded_lock_level` (`funded_intraday_trailing_drawdown`, field `lock`): selected {'on': [hwm], 'at_offset_usd': 2100, 'locked_offset_usd': 100}, alternative(s) {'on': [hwm], 'at_offset_usd': 2100, 'locked_offset_usd': 0}
- `rapid_funded_contract_limit` (`funded_max_contracts`, field `limit`): selected 2, alternative(s) 5

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `energy_and_agricultural_report_news_types`: Immaterial. The firm's Tier 1 list names FOMC Meetings, FOMC Minutes, the Employment Report and CPI for every trader, plus EIA (energy traders) and Agricultural Reports (agricultural traders). The four types for every trader are in the economic calendar and are enforced; EIA and the agricultural reports are not, and they cannot apply here because this ruleset's instrument set is equity index only.
- material `funded_scaling_schedule_unpublished`: Material. The funded contract limit is held at its starting value for the whole phase, but the Cross Instrument Policy says a sim funded Rapid account starts lower "due to the scaling plan" and publishes no step schedule. If the real limit rises with profits the model understates the contracts a funded account may trade.
- immaterial `active_account_count_limit`: Immaterial. At most five active sim funded accounts for $25K/$50K and three across all plans for $100K/$150K. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `reset_fee_amount`: Immaterial. A breached Rapid evaluation can be reset for a fee the official pages never quantify, so the ruleset carries no reset fee and attempt cost accounting understates a second attempt bought with a reset.
- immaterial `live_transition_on_10k_session`: Immaterial. A $10,000 single-session result moves the account to a live brokerage seat, which ends the simulated stage. The per-day cap is modeled (funded_daily_profit_cap_10000); the milestone transition itself has no rule kind, so an attempt that hits it is reported as a funded survive rather than a transition.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-rapideod-25k-dll` - Rapid EOD (DLL add-on) $25,000

**account / thresholds**
- account size $25,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons daily_loss_limit, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $25,000 -> funded $0
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=1000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 1100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.eval_daily_loss` (daily_loss): amount_usd=500, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `evaluation.eval_max_contracts` (max_contracts): limit=2, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=1500, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=4, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_eod_trailing_drawdown` (trailing_drawdown): amount_usd=1000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 1100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `funded.funded_daily_loss` (daily_loss): amount_usd=500, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `funded.funded_max_contracts` (max_contracts): limit=2, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `funded.funded_t1_news_blackout` (news_restriction): event_types=[FOMC_STATEMENT, FOMC_MINUTES, CPI, NFP], pre_minutes=2, post_minutes=2, scope=all_trading, flatten=before_window, effect=block, comparison >= -> flatten_and_block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=162.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `evaluation.eval_consistency` (consistency): max_day_share=0.3, measure=best_day_profit/total_profit, applies_to=pass, window=all_time, comparison <= -> promote_phase [official_quote]
- `funded.funded_daily_profit_cap_10000` (daily_profit_cap): amount_usd=10000, basis=balance, evaluated=eod, comparison >= -> forfeit_excess [official_quote]
- `funded.payout` (payout): min_days_since_last=1, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=since_last_payout, buffer_usd=1100, split=0.9, min_usd=500, max_usd=unlimited, max_payouts=None, min_profit_since_last_usd=250, first_payout_after_calendar_days=1, threshold_after_payout=unchanged, comparison >= -> withdraw [official_quote]

**assumptions**
- `daily_loss_basis_and_reference_are_not_published`
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `energy_and_agricultural_report_news_types`: Immaterial. The firm's Tier 1 list names FOMC Meetings, FOMC Minutes, the Employment Report and CPI for every trader, plus EIA (energy traders) and Agricultural Reports (agricultural traders). The four types for every trader are in the economic calendar and are enforced; EIA and the agricultural reports are not, and they cannot apply here because this ruleset's instrument set is equity index only.
- immaterial `active_account_count_limit`: Immaterial. At most three active Sim Funded accounts per trader. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `reset_fee_amount`: Immaterial. A breached Rapid EOD evaluation can be reset for a fee the official pages never quantify, so the ruleset carries no reset fee and attempt cost accounting understates a second attempt bought with a reset.
- immaterial `live_transition_on_10k_session`: Immaterial. The $10,000 single-session result also moves the account to a live seat, which ends the simulated stage (the Rapid EOD article says it follows the standard Rapid live rules). The per-day cap is modeled; the milestone transition has no rule kind.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-rapideod-25k` - Rapid EOD $25,000

**account / thresholds**
- account size $25,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons none, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $25,000 -> funded $0
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=1000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 1100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.eval_max_contracts` (max_contracts): limit=2, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=1500, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=4, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_eod_trailing_drawdown` (trailing_drawdown): amount_usd=1000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 1100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `funded.funded_max_contracts` (max_contracts): limit=2, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `funded.funded_t1_news_blackout` (news_restriction): event_types=[FOMC_STATEMENT, FOMC_MINUTES, CPI, NFP], pre_minutes=2, post_minutes=2, scope=all_trading, flatten=before_window, effect=block, comparison >= -> flatten_and_block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=162.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `evaluation.eval_consistency` (consistency): max_day_share=0.3, measure=best_day_profit/total_profit, applies_to=pass, window=all_time, comparison <= -> promote_phase [official_quote]
- `funded.funded_daily_profit_cap_10000` (daily_profit_cap): amount_usd=10000, basis=balance, evaluated=eod, comparison >= -> forfeit_excess [official_quote]
- `funded.payout` (payout): min_days_since_last=1, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=since_last_payout, buffer_usd=1100, split=0.9, min_usd=500, max_usd=unlimited, max_payouts=None, min_profit_since_last_usd=250, first_payout_after_calendar_days=1, threshold_after_payout=unchanged, comparison >= -> withdraw [official_quote]

**assumptions**
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `energy_and_agricultural_report_news_types`: Immaterial. The firm's Tier 1 list names FOMC Meetings, FOMC Minutes, the Employment Report and CPI for every trader, plus EIA (energy traders) and Agricultural Reports (agricultural traders). The four types for every trader are in the economic calendar and are enforced; EIA and the agricultural reports are not, and they cannot apply here because this ruleset's instrument set is equity index only.
- immaterial `active_account_count_limit`: Immaterial. At most three active Sim Funded accounts per trader. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `reset_fee_amount`: Immaterial. A breached Rapid EOD evaluation can be reset for a fee the official pages never quantify, so the ruleset carries no reset fee and attempt cost accounting understates a second attempt bought with a reset.
- immaterial `live_transition_on_10k_session`: Immaterial. The $10,000 single-session result also moves the account to a live seat, which ends the simulated stage (the Rapid EOD article says it follows the standard Rapid live rules). The per-day cap is modeled; the milestone transition has no rule kind.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-rapideod-50k-dll` - Rapid EOD (DLL add-on) $50,000

**account / thresholds**
- account size $50,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons daily_loss_limit, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $50,000 -> funded $0
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=2000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 2100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.eval_daily_loss` (daily_loss): amount_usd=1000, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `evaluation.eval_max_contracts` (max_contracts): limit=3, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=3000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=4, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_eod_trailing_drawdown` (trailing_drawdown): amount_usd=2000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 2100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `funded.funded_daily_loss` (daily_loss): amount_usd=1000, reference=day_start_balance, basis=equity, evaluated=intraday, reset={'time': 18:00:00, 'tz': America/New_York}, comparison <= -> soft_lock_until_reset [assumption `daily_loss_basis_and_reference_are_not_published`]
- `funded.funded_max_contracts` (max_contracts): limit=3, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `funded.funded_t1_news_blackout` (news_restriction): event_types=[FOMC_STATEMENT, FOMC_MINUTES, CPI, NFP], pre_minutes=2, post_minutes=2, scope=all_trading, flatten=before_window, effect=block, comparison >= -> flatten_and_block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=275.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `evaluation.eval_consistency` (consistency): max_day_share=0.3, measure=best_day_profit/total_profit, applies_to=pass, window=all_time, comparison <= -> promote_phase [official_quote]
- `funded.funded_daily_profit_cap_10000` (daily_profit_cap): amount_usd=10000, basis=balance, evaluated=eod, comparison >= -> forfeit_excess [official_quote]
- `funded.payout` (payout): min_days_since_last=1, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=since_last_payout, buffer_usd=2100, split=0.9, min_usd=500, max_usd=unlimited, max_payouts=None, min_profit_since_last_usd=500, first_payout_after_calendar_days=1, threshold_after_payout=unchanged, comparison >= -> withdraw [official_quote]

**assumptions**
- `daily_loss_basis_and_reference_are_not_published`
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `energy_and_agricultural_report_news_types`: Immaterial. The firm's Tier 1 list names FOMC Meetings, FOMC Minutes, the Employment Report and CPI for every trader, plus EIA (energy traders) and Agricultural Reports (agricultural traders). The four types for every trader are in the economic calendar and are enforced; EIA and the agricultural reports are not, and they cannot apply here because this ruleset's instrument set is equity index only.
- immaterial `active_account_count_limit`: Immaterial. At most three active Sim Funded accounts per trader. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `reset_fee_amount`: Immaterial. A breached Rapid EOD evaluation can be reset for a fee the official pages never quantify, so the ruleset carries no reset fee and attempt cost accounting understates a second attempt bought with a reset.
- immaterial `live_transition_on_10k_session`: Immaterial. The $10,000 single-session result also moves the account to a live seat, which ends the simulated stage (the Rapid EOD article says it follows the standard Rapid live rules). The per-day cap is modeled; the milestone transition has no rule kind.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-rapideod-50k` - Rapid EOD $50,000

**account / thresholds**
- account size $50,000, platform `NinjaTrader, Hyperprop, Tradovate, TradingView, Quantower, Volumetrica, ATAS, DeepChart`, add-ons none, instruments ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K
- starting balances evaluation $50,000 -> funded $0
- `evaluation.eval_eod_trailing_drawdown` (trailing_drawdown): amount_usd=2000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 2100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `evaluation.eval_max_contracts` (max_contracts): limit=3, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=3000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `evaluation.min_trading_days` (min_trading_days): days=4, unit=trading_days, day_counts_if={'min_trades': 1}, comparison >= -> promote_phase [assumption `trading_day_is_a_trade_date_with_at_least_one_trade`]
- `funded.funded_eod_trailing_drawdown` (trailing_drawdown): amount_usd=2000, mode=eod, evaluated=intraday, basis=equity, hwm_basis=balance, lock={'on': [hwm], 'at_offset_usd': 2100, 'locked_offset_usd': 100}, comparison <= -> fail [official_quote]
- `funded.funded_max_contracts` (max_contracts): limit=3, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `funded.funded_t1_news_blackout` (news_restriction): event_types=[FOMC_STATEMENT, FOMC_MINUTES, CPI, NFP], pre_minutes=2, post_minutes=2, scope=all_trading, flatten=before_window, effect=block, comparison >= -> flatten_and_block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=275.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `evaluation.eval_consistency` (consistency): max_day_share=0.3, measure=best_day_profit/total_profit, applies_to=pass, window=all_time, comparison <= -> promote_phase [official_quote]
- `funded.funded_daily_profit_cap_10000` (daily_profit_cap): amount_usd=10000, basis=balance, evaluated=eod, comparison >= -> forfeit_excess [official_quote]
- `funded.payout` (payout): min_days_since_last=1, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=since_last_payout, buffer_usd=2100, split=0.9, min_usd=500, max_usd=unlimited, max_payouts=None, min_profit_since_last_usd=500, first_payout_after_calendar_days=1, threshold_after_payout=unchanged, comparison >= -> withdraw [official_quote]

**assumptions**
- `trading_day_is_a_trade_date_with_at_least_one_trade`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `energy_and_agricultural_report_news_types`: Immaterial. The firm's Tier 1 list names FOMC Meetings, FOMC Minutes, the Employment Report and CPI for every trader, plus EIA (energy traders) and Agricultural Reports (agricultural traders). The four types for every trader are in the economic calendar and are enforced; EIA and the agricultural reports are not, and they cannot apply here because this ruleset's instrument set is equity index only.
- immaterial `active_account_count_limit`: Immaterial. At most three active Sim Funded accounts per trader. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `reset_fee_amount`: Immaterial. A breached Rapid EOD evaluation can be reset for a fee the official pages never quantify, so the ruleset carries no reset fee and attempt cost accounting understates a second attempt bought with a reset.
- immaterial `live_transition_on_10k_session`: Immaterial. The $10,000 single-session result also moves the account to a live seat, which ends the simulated stage (the Rapid EOD article says it follows the standard Rapid live rules). The per-day cap is modeled; the milestone transition has no rule kind.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- coordinator recommendation (owner delegation 2026-11-24): confirm as sourced; pending the owner's `crucible prop confirm`

### `mffu-studio001-10k` - Studio #001 $10,000

**account / thresholds**
- account size $10,000, platform `Hyperprop`, add-ons none, instruments MES, MNQ, MYM, M2K
- starting balances evaluation $10,000 -> funded $0
- `evaluation.static_max_loss_limit` (static_drawdown): amount_usd=500, basis=equity, evaluated=intraday, comparison <= -> fail [assumption `unspecified_failure_frequency_is_intraday`]
- `evaluation.eval_max_contracts` (max_contracts): limit=1, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=1000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `funded.static_max_loss_limit` (static_drawdown): amount_usd=500, basis=equity, evaluated=intraday, comparison <= -> fail [assumption `unspecified_failure_frequency_is_intraday`]
- `funded.funded_max_contracts` (max_contracts): limit=1, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=140.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `funded.funded_daily_profit_cap` (daily_profit_cap): amount_usd=5000, basis=balance, evaluated=eod, comparison >= -> forfeit_excess [official_quote]
- `funded.payout` (payout): min_days_since_last=0, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=all_time, buffer_usd=0, split=0.8, min_usd=250, max_usd=unlimited, max_payouts=None, min_profit_since_last_usd=0, first_payout_after_calendar_days=None, threshold_after_payout=unchanged, comparison >= -> withdraw [official_quote]

**assumptions**
- `unspecified_failure_frequency_is_intraday`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `active_account_count_limit`: Immaterial. One active Studio account at a time, evaluation or Sim Funded. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `live_eligibility_after_five_payouts`: Immaterial. A live account becomes available after 5 approved payouts or $5,000 requested, at 40% of the requested total capped at $2,000. That transition ends the simulated stage and is not a pass condition, so no rule kind expresses it.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- do NOT confirm: the source page is gone (F.10)

### `mffu-studio002-20k` - Studio #002 $20,000

**account / thresholds**
- account size $20,000, platform `Hyperprop`, add-ons none, instruments MES, MNQ, MYM, M2K
- starting balances evaluation $20,000 -> funded $0
- `evaluation.static_max_loss_limit` (static_drawdown): amount_usd=1000, basis=equity, evaluated=intraday, comparison <= -> fail [assumption `unspecified_failure_frequency_is_intraday`]
- `evaluation.eval_max_contracts` (max_contracts): limit=2, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=2000, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `funded.static_max_loss_limit` (static_drawdown): amount_usd=1000, basis=equity, evaluated=intraday, comparison <= -> fail [assumption `unspecified_failure_frequency_is_intraday`]
- `funded.funded_max_contracts` (max_contracts): limit=2, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=280.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `funded.funded_daily_profit_cap` (daily_profit_cap): amount_usd=10000, basis=balance, evaluated=eod, comparison >= -> forfeit_excess [official_quote]
- `funded.payout` (payout): min_days_since_last=0, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=all_time, buffer_usd=0, split=0.8, min_usd=250, max_usd=unlimited, max_payouts=None, min_profit_since_last_usd=0, first_payout_after_calendar_days=None, threshold_after_payout=unchanged, comparison >= -> withdraw [official_quote]

**assumptions**
- `unspecified_failure_frequency_is_intraday`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `active_account_count_limit`: Immaterial. One active Studio account at a time, evaluation or Sim Funded. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `live_eligibility_after_five_payouts`: Immaterial. A live account becomes available after 5 approved payouts or $5,000 requested, at 40% of the requested total capped at $2,000. That transition ends the simulated stage and is not a pass condition, so no rule kind expresses it.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- do NOT confirm: the source page is gone (F.10)

### `mffu-studio003-5k` - Studio #003 $5,000

**account / thresholds**
- account size $5,000, platform `Hyperprop`, add-ons none, instruments MES, MNQ, MYM, M2K
- starting balances evaluation $5,000 -> funded $0
- `evaluation.static_max_loss_limit` (static_drawdown): amount_usd=250, basis=equity, evaluated=intraday, comparison <= -> fail [assumption `unspecified_failure_frequency_is_intraday`]
- `evaluation.eval_max_contracts` (max_contracts): limit=0.5, comparison <= -> clip [official_quote]
- `evaluation.eval_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `evaluation.eval_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]
- `evaluation.profit_target` (profit_target): amount_usd=500, basis=balance, evaluated=eod, require_flat=false, comparison >= -> promote_phase [assumption `unspecified_target_frequency_is_eod`]
- `funded.static_max_loss_limit` (static_drawdown): amount_usd=250, basis=equity, evaluated=intraday, comparison <= -> fail [assumption `unspecified_failure_frequency_is_intraday`]
- `funded.funded_max_contracts` (max_contracts): limit=0.5, comparison <= -> clip [official_quote]
- `funded.funded_flat_by_ny_close` (flat_by): minutes_before_session_end=50, comparison >= -> auto_liquidate [official_quote]
- `funded.funded_inactivity_7_calendar_days` (inactivity): max_gap=7, unit=calendar_days, rolling_window=true, observed=eod, comparison >= -> fail [official_quote]

**news / compliance**
- `evaluation.compliance_no_high_frequency_trading` (compliance): restriction=High-frequency trading is not allowed, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_automation_must_not_exploit_simulated_fills` (compliance): restriction=Automated strategies are allowed only where they do not aim to exploit the favourable fills offered in the simulated environment, applies_to_execution=[automated], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_fill_or_quote_exploitation` (compliance): restriction=Manipulating fills (stacked limit orders, stale or illiquid fills, slippage and bracket exploitation) is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_copy_trading_or_account_sharing` (compliance): restriction=Copy trading another trader, sharing a device or collaborating across unconnected accounts is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]
- `evaluation.compliance_no_hedging` (compliance): restriction=Hedging of any kind is prohibited, applies_to_execution=[automated, manual], materiality=material, comparison >= -> block [official_quote]

**fees / commissions**
- `evaluation.evaluation_fee` (fee): fee_kind=evaluation, amount_usd=75.00, when=at_start, comparison >= -> charge [official_quote]
- `evaluation.activation_fee` (fee): fee_kind=activation, amount_usd=0, when=at_start, comparison >= -> charge [official_quote]
- commissions per side USD: ES 2.34, NQ 2.34, YM 2.88, RTY 2.34, NKD 3.11, MES 0.95, MNQ 0.95, MYM 0.95, M2K 0.95 (the instrument list's Total Cost Round Trip / 2; every cost component unknown)

**payouts**
- `funded.funded_daily_profit_cap` (daily_profit_cap): amount_usd=2500, basis=balance, evaluated=eod, comparison >= -> forfeit_excess [official_quote]
- `funded.payout` (payout): min_days_since_last=0, min_profitable_days=0, min_traded_days=0, min_day_profit_usd=0, window=all_time, buffer_usd=0, split=0.8, min_usd=100, max_usd=unlimited, max_payouts=None, min_profit_since_last_usd=0, first_payout_after_calendar_days=None, threshold_after_payout=unchanged, comparison >= -> withdraw [official_quote]

**assumptions**
- `unspecified_failure_frequency_is_intraday`
- `unspecified_target_frequency_is_eod`

**conflicts**
- none

**not_modeled**
- material `sub_minute_holding_and_micro_scalping`: Material. MFFU prohibits high-frequency trading and any exploitation of the simulated fill engine, which targets holdings shorter than a bar. The simulator reads OHLC bars, so a holding time below the bar cannot be measured and a micro-scalping pattern is invisible: the model can keep an account whose real holding-time would be refused, and it cannot fail a sub-minute rule the firm would enforce.
- material `price_limit_2pct_prohibition`: Material. Trading is prohibited while a product trades within 2% of its CME price limit, on Sim Funded and Live accounts (the firm says equity index price limits are suspended for it in that band). The ruleset holds no price-limit bands, so a bar in a limit move stays tradable here and a strategy that trades a limit day would differ.
- immaterial `cross_account_hedging`: Immaterial. The firm's hedging ban extends to the CME Rule 534 guideline against hedging across accounts. One simulated attempt is one account, so a cross-account hedge cannot exist inside it and the ban cannot change a simulated outcome.
- material `holiday_early_close_is_the_traders_job`: Material. The flat clock now follows the CME calendar's own early close, but the firm does not liquidate anyone at the half-day close - the trader is responsible for being flat and holding past it breaches the account - while flat_by liquidates for the trader. So where a real account that held into a half-day close would be breached, this model closes the position 50 minutes before it and the attempt can survive.
- material `discretionary_news_trading_practices`: Material. Beyond the Tier 1 windows, the firm prohibits news strategies as such: straddles or strangles around an immediate news burst, and masking a news trade as a standard strategy, "for all news releases" on every account. That is a judgement about intent and cannot be decided from OHLC bars or from a calendar window, so it is declared here and never enforced mechanically.
- immaterial `active_account_count_limit`: Immaterial. One active Studio account at a time, evaluation or Sim Funded. A single simulated attempt is one account, so the cap cannot change its outcome.
- immaterial `live_eligibility_after_five_payouts`: Immaterial. A live account becomes available after 5 approved payouts or $5,000 requested, at 40% of the requested total capped at $2,000. That transition ends the simulated stage and is not a pass condition, so no rule kind expresses it.

**decision (review round 2026-11-24)**
- [ ] confirm   [ ] correct: _____   [ ] reject
- do NOT confirm: the source page is gone (F.10)

## 11. Legacy products and open questions for the owner

Every question below was answered by the owner review of 2026-11-24 (delegated to the coordinator): section 12 records the disposition of each packet question F.1-F.35. The questions stay verbatim as the record of what was open.

### Per-component costs (C7b fix, 2026-11-22)

`commissions.includes_exchange_and_regulatory_fees` is gone. The ruleset now declares, for each of the four components, whether the firm's per-side commission CONTAINS it (`included`), EXCLUDES it (`excluded`, so the run adds the dataset's amount for its participant type) or does not say (`unknown`, which is never a zero cost). All four keys are required, and no component may be inferred from another firm's page, another product or another participant type (ADR-0107 section 10 as amended).

| Component | Status in the files | Evidence kind | Evidence |
|---|---|---|---|
| `exchange` | `included` | `official_quote` | "Trading Fees" in the subtitle "Includes Contract Specifications, Commissions, and Trading Fees", read as the exchange fee (owner decision, F.1/F.2) |
| `nfa` | `included` | `official_quote` | the same sentence, read as the NFA assessment (owner decision, F.4) |
| `clearing` | `unknown` | `not_stated` | the subtitle never names clearing (F.3) |
| `other` | `unknown` | `not_stated` | the subtitle names no other per-side charge (F.5) |

An `excluded` component needs the run's participant PROFILE (`--participant-profile`): each fee row names the one classification dimension it needs (`cme_membership_status`, `nfa_assessment_eligibility`, ...), a dimension the profile leaves out makes that component a gap, and using the profile makes the cost `conditional`. An `unknown` component is a gap, and the only way to a number is a cost-assumption FILE the user passes, which prices exactly the root and component it names and is recorded by its SHA-256. The unverified owner reference in `docs/data/cme-exchange-fees.md` ("Estimated fee per side") is documentation only: the engine never reads it.

Owner questions, one per component the files declare `unknown`:

1. **exchange**: Does the per-side commission already contain the exchange fee, or is the exchange fee charged on top of it?
2. **clearing**: Does the per-side commission already contain the clearing fee, or is the clearing fee charged on top of it?
3. **nfa**: Does the per-side commission already contain the NFA assessment, or is it charged on top of it?
4. **other**: Is there any other per-side charge beside the commission, the exchange fee, the clearing fee and the NFA assessment?

Answered 2026-11-24 (F.1-F.5, delegated to the coordinator): `exchange` and `nfa` are `included` on the subtitle's "Trading Fees", `clearing` and `other` stay `unknown`, and the bound charges only those two gaps (ES 2.34 + 0.50 + 0.50 = 3.34 per side).


- **Legacy, not drafted**: Flex ($25K/$50K, filed under Legacy Plans, `/plans/flex` returns the site's 404), Builder 25K Legacy No DLL, Legacy Pro, MyFunded Perps (a separate company). No page dates any current rule set, so `effective_from` is the retrieval date in every file.
- **Pro 50K One Day add-on**: its own article sits in "Pro Legacy Plans" and calls the offer limited, while the current redesigned Pro table still carries the One Day column with a $4,000 target, no consistency rule and a 1-day minimum. Drafted, still unverified: is it sold?
- **Rapid intraday per-request payout ceiling**: no page states a maximum and none denies one (the Pro table states $100,000 per user, the Rapid EOD pages say "There is no cap"). Modeled as `max_usd: unknown` in round 2, so the payout and the cash statistics are `upper_bound`; confirm whether a ceiling exists so they can become exact.
- **Pro micro cap**: the funded table prints "3 mini / 3 micro"; modeled as 3 mini-equivalents (30 micros) under an assumption. Is the page literal?
- **Rapid funded contract limit**: 2 contracts at the start (Cross Instrument Policy) or 5 (plan page)? The stricter value is selected and the other is a sensitivity scenario; the scaling schedule is unpublished.
- **Builder 150K payout cap**: $3,500 (plan page and the guide's own example) vs $4,500 (guide table). The stricter value is selected.
- **EOD drawdown test timing**: modeled intraday on equity (the firm's EOD article says open equity losses are taken into consideration). If MFFU tests only at the close, our failure rate is too high.
- **Trading-day definition**: a trade date with at least one executed trade (ADR-0107 section 7 default). No MFFU page defines it, for the 2-day (Rapid/Pro), 4-day (Rapid EOD) or 1-day (Builder) minimum or for Builder's "2 qualifying days".
- **Is Total Cost Round Trip all-in?** Every component is `unknown`: the column name and the article subtitle ("Includes Contract Specifications, Commissions, and Trading Fees") suggest an all-in figure, but no sentence names exchange, clearing, NFA or other fees, so the cost statistics stay `unavailable` (or `conditional` under a cost-assumption file). For each component, confirm with a source whether it is `included` or `excluded`.
- **Half-day close**: the firm does not liquidate at a half-day close, the trader must; `flat_by` liquidates. Declared as `holiday_early_close_is_the_traders_job`. Model it as `action: fail` if the firm's position (holding past the deadline breaches the account) is the one to enforce.
- **Builder consistency attribution**: the five Builder files source the 50% from the firm-wide consistency article, which names the Rapid EOD, Rapid Intraday and Pro plans rather than Builder, while each Builder plan article states the 50%, the cycle and the reset itself. Round 2 declared the cycle windows; re-sourcing to each plan article would make them quote-sourced per file.
- **No phase time limit**: no MFFU page states an access period or a deadline to pass, so no `time_limit` rule is declared in any file.

## 12. The owner review round (2026-11-24)

The owner delegated the packet's questions F.1-F.35 (`internal/reviews/mffu.md`) to the coordinator
on 2026-11-24 and this round applies every decision to all 20 files. Nothing is verified: no
`crucible prop confirm` was run, no `*.verification.yaml` exists, and every `verification.status` is
still `unverified`, so every decision line in section 10 carries the coordinator's recommendation
and still waits for the owner's own confirmation.

| # | question | decision (delegated 2026-11-24) | what the files now declare |
|---|---|---|---|
| F.1-F.5 | the all-in Total Cost Round Trip, and the four components | the subtitle "Includes Contract Specifications, Commissions, and Trading Fees" is an explicit firm statement of inclusion; "Trading Fees" standardly denotes the exchange fee and the NFA assessment, so those two are `included` and `clearing` and `other` stay `unknown` because the subtitle does not name them | `exchange` and `nfa` are `status: included` with `evidence: official_quote` and the subtitle as their `text`, plus the owner decision and the arithmetic in each file's `commissions.source.section` and comment; `clearing` and `other` stay `unknown` with a note naming what was checked. One ES side under `upper_bound_v1` is 2.34 + 0.50 + 0.50 = **3.34 USD** |
| F.6 | automation is `block` but never a condition | NOT applied here: `practical_eligibility` reads only `effect: condition`, and adding it is an ENGINE change owned by the separate "Lucid rulesets: apply review decisions" PR (branch pushed, PR open, not merged on 2026-11-24) | unchanged (no `effect: condition`): an automated run still reports plain `eligible`, and the reference run of 12.1 says so. Under that PR's rule - a `material` + `block` compliance rule conditions the eligibility - MFFU's five material bans would become the conditions (four for `manual`), because all five declare `action: block` |
| F.7, F.29 | no `supporting_sources` in any file | every rule whose action or timing rests on a sentence outside its own quote carries that sentence as a `supporting_source` | `eval_/funded_flat_by_ny_close` gain the auto-liquidation sentence and the instrument list's own `17:00 - 16:00 CT` session row; the funded drawdown rules gain the "$100 lock" (for Builder, the EOD article's lock sentence together with the funded table); `funded_t1_news_blackout` gains the "8:28:00 / 8:32:00" flatten example; the soft-pause `daily_loss` rules gain the page's soft-pause sentence; the inactivity rules gain the purchase-date sentence; the copy-trading rule gains the copy-trading article (F.30) |
| F.8 | no `promotions` although the firm publishes discounts | every published discount becomes a `promotion` on the fee it discounts, and the list price stays the base | 17 files (all but the 3 Studio ones): `club_40_off_any_plan` (`multiplier: '0.6'`, `requires {account_purchase: new, coupon_applied: CLUB}`, `ends_on: unknown`) and `new_trader_50_off_first_evaluation` (`multiplier: '0.5'`, `requires {account_purchase: new}`), each quoting the file's own plan page; `mffu-builder-50k` and `mffu-builder-50k-addon` also carry `builder_guide_30_off` (107 / 87) and `builder_guide_40_off_two_uses_only` (92 / 75) as the printed VALUES of the guide's pricing rows |
| F.9 | `becomes_immaterial_if` is absent from every entry | the field is declared where the packet requires it; the material entries' audit fact is left to the audit pass | `cross_account_hedging` (20 files) carries "becomes material if several accounts, copy trading or coordinated strategies are simulated", including the copier across the trader's own accounts (F.30); the new `active_account_count_limit` of the 4 Pro files carries its own condition |
| F.10 | the Studio guide answers 404 and the line is now Signature | keep the 3 Studio files unverified, record the 404, do NOT build Signature rulesets | the 3 Studio files keep every value and their decision line reads "do NOT confirm: the source page is gone (F.10)" in section 10 and in the packet; the 404 (re-checked 2026-11-24T16:40Z) and the Signature follow-up are recorded in 12.2 |
| F.11, F.12 | two assumptions labelled `section7_default` that no section-7 default produces | relabel `provisional_conservative` | `daily_loss_basis_and_reference_are_not_published` (7 files) and `pro_funded_micro_limit_read_as_mini_equivalence` (4 files) |
| F.13-F.15 | the target's observation frequency, the trading day, the Studio static MLL test | accepted as they stand (F.15 stays intraday) | unchanged |
| F.16-F.18 | the three conflicts | the stricter reading stays primary and the alternatives stay sensitivity scenarios; F.18 also re-quotes the other three Rapid files | values unchanged ($3,500 over $4,500, the +100 lock over $0, 2 contracts over 5); `funded_max_contracts` of `rapid-25k/100k/150k` now quotes the funded section's own "You may trade up to N minis and/or M micros total." sentence, and the Rapid 50K conflict's alternative does too |
| F.19-F.23 | the material `not_modeled` entries | they stay `material`; F.20 gains the audit note | materiality unchanged; `price_limit_2pct_prohibition` records that the 2024 ES audit is not the firm's band test |
| F.24 | what happens past the $100,000 Sim cap, and the page that changed | model the current page: excess profits go to the Reserve Program, up to $5,000 per account; the lifetime cap stays `not_modeled` material | `lifetime_payout_cap_100000` (4 Pro files) is re-sourced to a fresh 2026-11-24 snapshot with the new wording (sha256 `712754643fe1...`) |
| F.25 | the Pro buffer withdrawal and the 14-day cadence | the vocabulary cannot express "up to 60% of your profits before fully clearing the buffer" (`withdrawable` is the balance minus the buffer and pays nothing when non-positive, and `max_share_of_withdrawable` multiplies the post-buffer amount), so it is `not_modeled` material; the cadence stays `not_modeled` material | new `pro_buffer_withdrawal_while_in_buffer` (material) naming the sentence and why no field fits; `payout_cadence_14_calendar_days` keeps its entry with the decision recorded |
| F.26 | the Pro page's dated account-count rule | `not_modeled` immaterial, with the fact that would make it bind | new `active_account_count_limit` on the 4 Pro files, quoting the dated sentence from the 2026-11-24 Pro snapshot |
| F.27 | inactivity: a soft sentence modelled as a hard `fail` | keep `action: fail` as `provisional_conservative` and declare the purchase-date condition | the named assumption `inactivity_closure_is_a_fail` (`provisional_conservative`) on both inactivity rules of every file, the purchase-date sentence as a `supporting_source`, and the reasoning in the description |
| F.28 | the consistency measure: share of total profit vs the page's `target / 2` | the share measure stays primary; no existing field expresses the target/2 cap (`measure` is fixed and no rule kind compares a day's profit with the target), so it is declared, not modelled | new `consistency_target_over_two_max_daily_profit` (material) in the 16 files that carry a consistency rule, plus a sentence on the rule itself; NO sensitivity scenario is generated |
| F.30 | the copy-trading article is not cited | add it as a `supporting_source` and say how a copier across one's own accounts interacts with the hedging ban | `compliance_no_copy_trading_or_account_sharing` (20 files) cites it and `cross_account_hedging`'s condition names the copier |
| F.31 | the flat clock on a half day | confirm the session-relative reading as `owner_decision` | `session_relative_flat_follows_the_cme_early_close` (`owner_decision`) on both `flat_by` rules of every file, plus the reasoning sentence in each description |
| F.32 | a breach completed by the liquidating fill's own costs | confirm the pessimistic reading as `owner_decision` | recorded here and in the ADR-0107 amendment: it is the engine's own reading (ADR-0106, `docs/TIMING.md`), declared once for every firm because no rule field carries it, and the reference run of 12.1 shows it |
| F.33 | the reference run cannot validate most of the file | no action: a second reference run belongs to C7c | unchanged |
| F.34, F.35 | 25 attributions quote a neighbouring sentence, and the Pro 100K/150K lock quotes the 50K cell | re-quote all of them to spans that carry their own number; no value changes | 8 attributions re-pointed (the Builder and Pro funded drawdown amounts, the Builder funded contract limits, the Builder 150K payout cap, the Studio contract rows) and the rest carried as supporting spans; `pro-100k` and `pro-150k` quote their own `$100,100` / `$150,100` cells. Values unchanged |

**Mechanically.** The 20 files are re-hashed in place (they are unverified and unreleased, so the
INDEX lock rule allows it: no version number disappears and no VERIFIED hash changes),
`rulesets/prop/INDEX.json` is regenerated, and the quote self-check now covers **866 attributions**
(608 before) with 0 mismatches: every quote resolves to a saved page and every hash matches its
bytes.

### 12.1 The ES 2024 reference run under the upper bound (H = 20)

`crucible.experiments.futures_prop.run_prop_evaluation` on `examples/futures/es_sma_cross.yaml`,
prepared exactly as `tests/bench/test_prop_real_data.py` prepares it (window 2024-01-02 ..
2024-12-31, 5 warmup trade dates, `flat_by_close: false`, `allow_unverified_sessions: true`), with
`cost_assumption: rulesets/prop/cost_assumptions/upper_bound_v1.yaml`, `payout_policy: max_eligible`,
`scenarios: primary`, `CRUCIBLE_DATA_STORE=D:/proyectos/crucible/data/processed` and one temporary
Crucible home and artifacts root per mode under `D:/tmp/mffu_review/`. Nothing was written to the
user's Crucible home, the data window ends 2024-12-31 and H = 20 is the analyst's horizon (no MFFU
phase declares a time limit). The file is `mffu-rapid-50k.v1.yaml`, content hash
`2e8b7c78da954346433cfbcb5b973ac9160b053d6cb15f7af2991863424440df`; the packet's run used
`e19ab336...`, the file before this round.

| measure | `automated` | `manual` |
|---|---|---|
| evaluation id | `PRP-60add4884bb3dfe6` | `PRP-905652d3d88ee1d7` |
| run id (same config) | `FUT-7ac5712b884dcdd6` | same |
| ruleset | `mffu-rapid-50k` v1, unverified, content hash `2e8b7c78...` | same |
| window / H | 2024-01-02 .. 2024-12-31, last trade date 2024-12-31, H = 20 | same |
| starts / complete starts | 253 / 234 (the last 19 cannot complete under H = 20) | identical |
| outcomes | pass 0, fail 253, timeout 0, horizon 0, censored 0 | identical |
| breached rule | `eval_eod_trailing_drawdown` 253 of 253 | identical |
| `min_buffer_usd` over the 253 | -33.80 .. -0.07 | identical |
| probability | `conditional_pass_probability` 0.0, interval 0.0 .. 0.0, `definitive: false` | identical |
| effective independent attempts | 11.7 | identical |
| estimate status | `partial` | identical |
| **cost per side (ES)** | **2.34 + 0.50 + 0.50 = 3.34 USD**, `cost_status: conditional`, no gaps, `cost_bound: upper` | identical |
| cash | mean net cash `-209.000000` USD, status `lower_bound`, interval [-209.00 .. -209.00] | identical |
| funded phase | 0 starts reached it (breached 0, survived 0, unresolved 0, payouts 0) | identical |
| **practical eligibility** | **`eligible`**, 0 conditions, 0 blocker | **`eligible`**, 0 conditions |

**Against the packet's run (section E).** The start count, the completeness, every outcome class,
the single breached rule, the 0.0 probability and the -209.00 cash (the evaluation fee alone: no
payout was ever taken) are unchanged. What moved is the COST: the packet charged 5.36 per side
because all four components were `unknown` and the bound priced all four on top of the firm's own
all-in figure; with `exchange` and `nfa` `included` it is 3.34, so a 253-attempt frame pays 2.02 less
per side. **The attempts still fail 253 of 253 on the same rule**, and the deepest breach goes from
the packet's walked -14.52 to -33.80: the cost double count was not what made these attempts fail,
and removing it lets them run longer before the same end. The packet's `estimate_reasons` list keeps
its shape (cost assumption used, payout cap unknown, the unsourced CME session 2024-01-14..2024-01-15,
`FOMC_MINUTES-20241126` without a known time, unverified, and the material unmodeled rules, which now
include `consistency_target_over_two_max_daily_profit`), and `coverage_gap_starts` stays 33.

**The promotions are recorded, not applied.** The manifest's `promotions_not_applied` says
`promotion club_40_off_any_plan not applied: no participant profile was declared` and the same for
`new_trader_50_off_first_evaluation`: a run that does not declare the discount it bought keeps the
list price, which is the pessimistic direction and the one this review's arithmetic uses.

**Automation (F.6).** `practical_eligibility` reads `eligible` in BOTH modes: the automation rule is
`material` + `block` with no `effect: condition`, and adding it is the engine change owned by the
separate Lucid round. This run therefore says nothing about automated eligibility beyond what the
packet already recorded: the two frames are identical in every column except the `execution_mode`
label inside the eligibility block.

**What the run does not exercise.** Exactly as in the packet (its section E.5): 253 breaches on the
evaluation MLL, nothing else. The profit target, the two minimum trading days, the 50% consistency
rule, the 7-day inactivity rule, the contract limit (`clip` never binds at one contract) and the
whole funded phase are never reached, so this run cannot validate them. Read it as one ES strategy
under one unverified ruleset, never as evidence about MFFU.

### 12.2 Studio -> Signature: the page is gone, and what that leaves open

`https://help.myfundedfutures.com/en/articles/17589665-studio-plans-a-comprehensive-guide` answered
HTTP 404 again on 2026-11-24 at 16:40Z (the packet recorded the same on its own pass). It is the only
source of the 30 attributions across the 3 Studio files. Those citations still resolve to the saved
bytes of 2026-11-22, so the self-check passes while the page itself is gone; the decision is therefore
"do NOT confirm".

**Follow-up task (not done in this round, per F.10): draft the Signature rulesets.** `/studio` says
Studio #001-#003 "have moved over to Signature" and `/plans/signature` publishes the successors:
list prices $125 / $233 / $467 with a 50% launch offer ($62.50 / $116.50 / $233.50), minimum trading
days **1** (the old guide said None), and the same static MLL, target, contract cap, split, minimum
payout and daily profit cap. That is 3 new product files with a `promotion` for the launch offer, a
`min_trading_days` rule the Studio files do not carry, and a product rename - a new version (v2),
never an edit of the 3 unverified Studio files.
