# Topstep — prop-firm research notes (C7b, `firm_slug: topstep`)

26 rulesets, all at **schema version 2** (ADR-0107 sections 7-13) and all `unverified`: only the
owner can confirm one (`crucible prop confirm`, interactive TTY). Version 1 of each file was the
first draft of this research pass; it was rewritten in place in schema 2 (no version number was
reused because none had been committed with a content hash).

Official sources only (topstep.com, help.topstep.com). No affiliate, review or social page was used.
Nothing on the site was logged into, submitted or purchased.

- Retrieval date: **2026-11-22** (UTC).
- Every page below was saved byte-for-byte under
  `D:\proyectos\crucible-notes\internal\prop_snapshots\topstep\`; `sha256` is the hash of the saved
  bytes and `retrieved_at` the UTC fetch time.
- Quote verification: decode the saved bytes as UTF-8, unescape HTML entities, collapse all
  whitespace, search for the quote normalised the same way; a value that lives in a table row is
  found after also stripping tags. `check_quotes2.py` performs both passes over every attribution of
  every file (last run, 2026-11-23, round 4: **928 attributions, 928 hashes matched, 0 quotes
  missing** — 497 strict, 431 found after stripping tags).
- No value is taken from a page that was not saved. No number is guessed: a value the pages do not
  state is `not_modeled`, never a default that looks like a rule.

## 1. Programs found

Topstep is a futures-only day-trading prop firm (no forex, no CFDs).

| Program | Phases | Sizes | Platform | Notes |
|---|---|---|---|---|
| **Trading Combine®** | 1 evaluation | 50K / 100K / 150K | TopstepX | Monthly subscription, no time limit; two purchase paths (Standard, No Activation Fee); the optional Daily Loss Limit is bought at checkout and carries into the funded account. |
| **Express Funded Account® (XFA)** | funded | matches the Combine passed | TopstepX | Balance starts at $0; two payout paths, Standard (5 winning days of $150+) and Consistency (3 traded days, 40%); the per-request cap depends on size, path and whether a DLL was bought. |
| **Live Funded Account® (LFA)** | live funded | up to $150,000 | live | Out of scope: real capital, not a simulated evaluation (see section 12). |
| **Topstep Labs** | evaluation + funded | $50K drop | TopstepX | Limited drops; the live one is the `$50K Daily Payouts+ Trading Combine®` in an End-of-Day Trailing and a Static drawdown form, one-time $149, free activation, both payout paths included. |

Jurisdiction: eligibility is by citizenship and permanent residency; OFAC-sanctioned and
partner-restricted countries are excluded and some countries may hold an XFA but not an LFA
(`https://help.topstep.com/en/articles/8284116-am-i-eligible-to-trade-with-topstep`, paraphrase; the
list is a table of country names and carries no rule value). `jurisdiction: null` in every file.

None of this is in `crucible/`; the rulesets are data.

### Round 2 changes (the C7b vocabulary pass)

The files were written against the first cut of schema version 2, which did not yet require or
express everything the vocabulary does now. This pass (same retrieval set, no new page fetched):

1. **`commissions.components` (exchange and NFA `included`, clearing and other `unknown`)** in all 26 files. It is now REQUIRED
   with no default, and Topstep states it: the commission page's round-turn breakdown is "NFA &
   Regulatory Fees $0.02 + Exchange Fee $2.76 + Commissions $1.00 = Total $3.78" for ES, so the
   per-side figure each file carries is the true cost per side and no exchange-fee table is added.
2. **`lock.on` is a list** everywhere, and every funded Maximum Loss Limit lists **both** triggers:
   `[hwm, first_payout]`. Topstep states both ("locks permanently once it reaches your starting
   balance"; "After each Payout: Your Maximum Loss Limit (MLL) resets to $0 permanently"), and the
   round-2 schema lets one lock carry several. This removes
   `xfa_mll_set_to_zero_by_first_payout`, which the previous cut had to declare because a lock
   carried one trigger.
3. **`news_restriction.effect`** is now required: `block` on the minis, and a **second**
   `news_restriction` per phase with `effect: contract_cap` and `cap_contracts` 0.3 / 0.6 / 0.9 (3 /
   6 / 9 micros at a micro's 0.1 weight) for the micros. This removes
   `tier1_news_micro_contract_caps`.
4. **Event types the calendar now carries**: `PPI` and `FOMC_PRESS_CONFERENCE` join `CPI`,
   `FOMC_STATEMENT` and `NFP`. This removes `tier1_news_event_types_outside_the_calendar`. The
   firm's Tier 1 table does **not** name the FOMC minutes, so `FOMC_MINUTES` is not declared: a
   window the firm does not state would be invented.
5. **The Labs drops' payout paths**: the second path (5 Winning Days) is now declared from the Labs
   help article ($4,000 EOD / $8,000 Static per payout, no buffer, 50% of balance, five $150+ days)
   with `payout_group: labs_xfa_payout_paths`, so at most one path pays per close — "you pick at each
   Payout request". The `fifth_winning_days_payout_path` gap is gone.
6. **One recorded conflict** (the Labs files): the Daily Payout path's minimum is $250 on the drop
   page and $125 on the firm-wide payout policy. Both sources are kept and the more restrictive
   $250 is selected (sensitivity scenario `labs_daily_payout_minimum#0`).
7. The static Labs drop's funded drawdown is re-sourced: the help article states the XFA MLL
   ("$2,000 static"), so the previous "the page does not say" entry became a declared conservative
   substitution (`static_xfa_drawdown_taken_as_trailing`).

### Round 3 — the owner's decisions (2026-11-23, binding)

The owner reviewed the C7b packet (`internal/reviews/topstep.md`, questions F1-F21) and ruled on
2026-11-23. The rulings below are applied to the files; every file stays `unverified`, no sidecar
exists, and each ruling is recorded as an `assumption` (`assumption_kind: owner_decision` or
`provisional_conservative`) or as a `conflict_resolution`, never as a quote of a value the page does
not state.

**Scope (owner decision, D7).**

- **Platform: TopstepX only.** No per-side commission table is published for another platform, so a
  ruleset for one would be a new file, not a different value here.
- **The current data universe, with metals excluded**: ES, NQ, YM, RTY, NKD at weight 1 and MES,
  MNQ, MYM, M2K at weight 0.1. GC, SI, HG, PL and their micros are outside the set and stay
  unmodelled, as the news rules' own descriptions say.
- **Ruleset as of 2026-11-22**, keeping the URLs, the verbatim quotes, the snapshot `sha256` and the
  retrieval times exactly as cited.
- **Not a historical reproduction of the 2024 conditions** of any Topstep program: the files model
  the pages as they read at that `as_of`, nothing else.

**The rules that changed (D1-D5).**

1. **Clearing and other stay `unknown`** in all 26 files (D1): not inferred to sit inside the
   commission, not filled with a generic value. Both remain declared gaps, so the cash statistic
   stays `unavailable` unless a cost-assumption file prices them.
2. **The doubled DLL payout cap is a `promotion` on the standard cap** (D2). `max_usd` returns to the
   STANDARD cap of its size and path (2,000/3,000/5,000 standard, 3,000/4,000/6,000 consistency) and
   `promotions: [dll_doubled_payout_cap]` states `field: max_usd`, `multiplier: 2`, `starts_on`
   2026-06-02 (the offer began at 3:30 PM CT that day), `purchase_on_or_after` 2026-06-02,
   `ends_on: unknown` (no end date is published as of 2026-11-22, and the promotion is never assumed
   to continue past the ruleset's `as_of`) and `requires: {account_purchase: new,
   dll_selected_at_purchase: 'true'}` plus the profile's `purchase_date`. The source quote is the
   payout page's own answer: "Yes! All Traders who make a new Trading Combine purchase and add a
   Daily Loss Limit (DLL) at checkout will receive the increased Payout cap, during this limited time
   offering beginning at 3:30 PM CT on Tuesday, June 2nd.", with "No. Only if you already added the
   DLL when you purchased your Trading Combine. Adding it at the XFA stage doesn't unlock the higher
   cap." A run that cannot show those facts keeps the standard cap and records
   `promotion dll_doubled_payout_cap not applied: <reason>`.
3. **The profit target stays EOD on the closed balance** as `provisional_conservative` (D3), never
   intraday, and its separation from the intraday MLL treatment stays.
4. **`minimum_trading_days` counts a day with at least one EXECUTED trade** (D3). Checked rather than
   changed: `unit: trading_days` counts the 17:00 America/Chicago rule-day and `day_counts_if:
   min_trades: 1` counts executed fills, never a submitted order and never a roll leg
   (`crucible/prop/overlay.py` step 7); the rule-day and the Topstep session (5:00 PM CT to 3:10 PM
   CT) span the same tradable hours because nothing may trade between 15:10 and 17:00 CT. Payout
   qualifying days keep their own gates (`min_profitable_days`, `min_traded_days`,
   `min_day_profit_usd`) and never read `day_counts_if`.
5. **XFA inactivity is now an assumption entry** (D3): `xfa_inactivity_may_be_closed_on_day_31`,
   `assumption_kind: provisional_conservative`, with the page's own "may be closed" quoted in the
   rationale. The close happens at the start of the 31st calendar day after the last trade date, and
   the description no longer reads as a guaranteed automatic close. **The two Labs files do not
   borrow it**: their own drop page states the closure ("If there are no trades placed for 30 days,
   the account will close."), so those two close at the start of day 31 on that quote instead.
6. **The static Labs drop's funded drawdown is `not_modeled` critical** (D4). The trailing
   substitution and its assumption are REMOVED: the page states "$2,000 static, non-trailing" AND
   "After first Payout, MLL sets to $0", and `static_drawdown` has no post-payout reset or lock, so
   the funded phase declares no loss limit rather than an approximation. The evaluation phase's
   static $2,000 stays exact.
7. **The Labs payout minimum conflict stands** (D5): $250 primary, $125 as sensitivity scenario
   `labs_daily_payout_minimum#0`, both sources kept, nothing verified.

8. **The FOMC press conference** keeps its coverage gap (D6): the 5-minute window applies wherever a
   reliable timestamp exists, and a missing time gaps only its own trade date, never a whole-day
   block.

### Round 4 — owner decisions F10-F21 (2026-11-23, binding)

The owner answered the questions round 3 left open. Every file stays `unverified`, no sidecar
exists, and each ruling is carried by a quotation, an `assumption_kind: owner_decision` note or a
declared condition, never by a value the page does not state.

**F21 — practical eligibility is `eligible_conditional` for an automated strategy.** Six
`compliance` rules with `effect: condition` sit in the evaluation phase of every file, each quoted
from the TopstepX API Access article (snapshot `20261123_hc_topstepx-api-access.html`, sha256
`876d2214d867d09136fa4dd6ff3abf97a91f575a582aa0afe5470f0c8dc3788e`, retrieved 2026-11-23T05:32:44Z):

| rule_id | condition the trader must meet | quote |
|---|---|---|
| `automated_trading_through_the_api` | trades only through a linked TopstepX / ProjectX API subscription, in a Combine or an XFA | "Custom automated strategies and bots are allowed via the TopstepX / ProjectX API, subject to standard platform rules and our prohibition on highfrequency trading (HFT)." |
| `no_api_trading_in_the_live_funded_account` | never pointed at a Live Funded Account, where the API does not exist | "No, Live funded accounts are not allowed to trade through the ProjectX API. The API Gateway is built for the simulated environment and isn't available on Live." |
| `high_frequency_trading_prohibited` | no HFT; no page states a threshold, so the boundary is Topstep's judgement | the same API answer ("... our prohibition on highfrequency trading (HFT)") |
| `orders_originate_on_the_personal_device` | every order transmitted from the trader's own device | "All trading activity must originate from your personal device." |
| `no_order_entry_from_a_vps_vpn_or_remote_server` | no VPS, VPN or remote server places, modifies or cancels an order | "The use of VPS, VPNs, and remote servers is prohibited by Topstep's Terms of Use." |
| `the_algorithm_remains_subject_to_every_rule` | the algorithm obeys every rule exactly as manual trading does | "All trading activity remains subject to Topstep's Trading Guidelines regardless of which platform executes the trades. A rule violation is treated the same whether it originates from manual trading or third-party automation." |

HFT has **no stated threshold** in any saved Topstep page (the article prohibits it by name and
nothing more), so it is a condition, never a modeled limit. The not-allowed half of the VPS table is
worth quoting in the report: placing, modifying, or cancelling orders from a server, any automated
trigger that can reach the order endpoints, and routing or relaying orders on the trader's behalf;
"your server can watch and record, but it cannot trade". **Authorization is not compliance:** an
API key and a subscription are what Topstep grants the trader, and the page itself says orders via
the API are final and that a rule violation counts the same for a bot.

**F11 — the XFA scaling plan stays `material` and stops reading as a limit that does not exist.**
The entry is re-quoted to the article's own statement that the plan IS an XFA objective ("The
Scaling Plan is an Express Funded Account® (XFA) objective. It sets your Maximum Position Size —
the max contracts you can hold at one time — based on your current account balance"), names the
saved ladder image and its sha256, and says plainly that the funded phase's own contract limit is
NOT declared because the ladder is image-only — never that an XFA has no limit, and never the
Combine's maximum. Every file's text was checked for the old "declares no contract limit" wording.

**F12/F13 — the materialities, each with the condition that would change it.**

- `news_full_position_size_prohibited`: `material`, discretionary, no invented window.
- `sub_minute_holding_and_micro_scalping`: `material` for one-minute granularity. The published ban
  is on algorithmic scalping that exploits unrealistic SIM fills; the page's "average durations
  measured in seconds, not minutes" describes that pattern, so the seconds are an example and never
  a universal threshold. No file fails an account for holding under 60 seconds.
- `cross_account_hedging`: `immaterial` for one isolated account, `becomes_immaterial_if`:
  "becomes material if multiple accounts, copy trading or coordinated strategies are simulated".
- `two_percent_price_limit_restriction`: `material`, `becomes_immaterial_if`: "an audit of the
  instruments and dates shows it never affected a trade".
- `volatility_position_limit_tightening`: `material`, `becomes_immaterial_if`: "shown not to affect
  the evaluated universe, dates and sizes", quoting "Trading on mini-sized contracts or larger may
  be temporarily halted for affected products" (the page's own "Micro Contract Limits / Mini
  Contract Restrictions" adjustments).

**F10 — the Labs drops.** The 90/10 split is re-sourced to the drop page itself ("Profit Split
90/10", in the `Choose your Payout path` columns), which also states min, max, 50% of balance and
frequency in one contiguous run; the `payout_split_taken_from_firm_payout_policy` assumption is
gone. The Daily Payout path keeps the $250 minimum as the primary reading with $125 as sensitivity
scenario `labs_daily_payout_minimum#0`; the 5 Winning Days path keeps its own **$125** as an
`owner_decision` assumption over the firm-wide policy's general minimum, and the Daily path's $250
is never used there. Each variant keeps its own maxima ($1,500 daily; $4,000 EOD / $8,000 Static on
the 5 Winning Days path).

**Labs lifespan and inactivity, from the drop's own page only.** The Challenge table publishes
`Lifespan 90 days` and `Inactivity 30 days`, and the drop's FAQ states "The account will expire and
close after 90 days." and "If there are no trades placed for 30 days, the account will close." The
evaluation phase therefore declares a `time_limit` of 90 calendar days from the attempt start and
an `inactivity` rule of 30 calendar days that only an EXECUTED trade resets (an unfilled order does
not). The Phase 2 Express Funded Account table publishes no inactivity of its own, so the funded
phase declares none: the old funded `xfa_inactivity` moved to the evaluation phase rather than being
repeated, and nothing here is extrapolated to a standard Topstep product.

**F16 — the current payout policy, and the superseded page.** See section 7.

## 2. Snapshots used

All saved bytes in the private snapshot folder, with the hash every attribution cites:

| file | url | sha256 | retrieved_at |
|---|---|---|---|
| `20261122_express_funded_rules.html` | https://www.topstep.com/express-funded-account-rules | `10f18414b60468d7f1a4730b23aba5303e6deb6a85764992c316c2cb15892431` | 2026-11-22T01:35:39Z |
| `20261122_hc_commissions.html` | https://help.topstep.com/en/articles/8284213-what-are-the-commissions-and-fees-in-the-trading-combine-and-express-funded-account | `eb810a535fa0abe221c6ee2ab610521bde316882d3dd24917cd64cfb8d1478c1` | 2026-11-22T03:54:40Z |
| `20261122_hc_consistency-at-topstep.html` | https://help.topstep.com/en/articles/8284208-consistency-at-topstep | `c5b4685f734af577f0debe0fa98cf3ab9ee806a63c223db425c16f394b510cda` | 2026-11-22T01:36:33Z |
| `20261122_hc_daily_loss_limit.html` | https://help.topstep.com/en/articles/10490293-daily-loss-limit-in-the-trading-combine-and-express-funded-account | `c30070bcd003638072c7784cdd3206a903849ab816c84fc348000611f36b2a3d` | 2026-11-22T01:36:15Z |
| `20261122_hc_economic-releases.html` | https://help.topstep.com/en/articles/8284211-economic-releases | `764ea76e2011763de5bc9e1d1405f7ad07c6f3398709da4325bd8153cfc3986d` | 2026-11-22T01:37:23Z |
| `20261122_hc_eligibility.html` | https://help.topstep.com/en/articles/8284116-am-i-eligible-to-trade-with-topstep | `4a3ffdb09764432477861f8620761013e10d4db8498c8f77dea76aadac3bd695` | 2026-11-22T01:45:53Z |
| `20261122_hc_express-funded-account-activation.html` | https://help.topstep.com/en/articles/8284217-express-funded-account-activation | `d3befe57e254ac12343de26996d83e8621820e6ac316cb949b528d5f833ab287` | 2026-11-22T01:36:32Z |
| `20261122_hc_express-funded-account-parameters.html` | https://help.topstep.com/en/articles/8284215-express-funded-account-parameters | `147e7624b6b96fdfba83cc3a20e79ad394c7857a289610b0632b7af62989ba79` | 2026-11-22T01:36:31Z |
| `20261122_hc_labs.html` | https://help.topstep.com/en/articles/15520357-topstep-labs | `3eeff491464260ca00802775549db9a203644e81d726396227d1eaa1c191c9b1` | 2026-11-22T01:53:10Z |
| `20261122_hc_maximum_loss_limit.html` | https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit | `572b4fdded98cacc5c791cdf0dc905b82e6f06401de92f8919d240751b3695f1` | 2026-11-22T01:36:14Z |
| `20261122_hc_pricing-and-payment-questions.html` | https://help.topstep.com/en/articles/14289835-topstep-pricing-and-payment-questions | `b6dc3bb6d4d7c27078d5324e05e6e22090ce8c8be67eced31e7d654eb8d9fbd9` | 2026-11-22T01:37:21Z |
| `20261122_hc_prohibited-conduct.html` | https://help.topstep.com/en/articles/10296582-prohibited-conduct | `e40fa8e3c14e7137540bbe0eb2ae384d1bbb9c0410bf72ed8bac2f2edf0b15c7` | 2026-11-22T01:37:22Z |
| `20261122_hc_prohibited-trading-strategies.html` | https://help.topstep.com/en/articles/10305426-prohibited-trading-strategies-at-topstep | `04b662b2c733165c448a92ffafdad79232a7a3c1b8777e699098fd9f4ea19be2` | 2026-11-22T01:37:23Z |
| `20261122_hc_risk-adjustments.html` | https://help.topstep.com/en/articles/13613539-risk-adjustments-high-risk-high-volatility | `8b56d11af75c1e8cc26ba265357ce5ff9d085b6c163ef5985c65c2314a10b2fc` | 2026-11-22T01:37:25Z |
| `20261122_hc_topstep-payout-policy.html` | https://help.topstep.com/en/articles/8284233-topstep-payout-policy | `22aa745f92b0aa44947e8f0521ad7b7a55bdb7a2175c525e78fc5b2e9d0ad1f6` | 2026-11-22T01:36:32Z |
| `20261122_hc_topstep-program-overview.html` | https://help.topstep.com/en/articles/8284099-topstep-program-overview | `9e18376afe837295cd444c475a7e8e29b0cee5431d61f7455f6e7a2856cfce03` | 2026-11-22T01:37:26Z |
| `20261122_hc_trading-combine-subscriptions.html` | https://help.topstep.com/en/articles/8284121-trading-combine-subscriptions | `36eac6f0ca51dff01b685218b4f063c2e0c3f4deb3f7772306e997a93b8d6ed6` | 2026-11-22T01:37:19Z |
| `20261122_hc_trading_combine_parameters.html` | https://help.topstep.com/en/articles/8284197-trading-combine-parameters | `d1a55343b8d97e05866c1e9e7b1ba476dd94dfb3c3e449199974710ec1f12143` | 2026-11-22T01:36:12Z |
| `20261122_hc_what-is-a-reset.html` | https://help.topstep.com/en/articles/8284128-what-is-a-reset | `608a9157ca9fca1211940b762a93a8d3aa276b662c2da87fb37a42deadde93f9` | 2026-11-22T01:37:21Z |
| `20261123_hc_topstepx-api-access.html` | https://help.topstep.com/en/articles/11187768-topstepx-api-access | `876d2214d867d09136fa4dd6ff3abf97a91f575a582aa0afe5470f0c8dc3788e` | 2026-11-23T05:32:44Z |
| `20261122_hc_what-is-the-scaling-plan.html` | https://help.topstep.com/en/articles/8284223-what-is-the-scaling-plan | `90a50f76af9363f786e18104d8612998a62a1fba54f027d3da48cee13e50c2ce` | 2026-11-22T01:36:34Z |
| `20261122_hc_when-and-what-products-can-i-trade.html` | https://help.topstep.com/en/articles/8284206-when-and-what-products-can-i-trade | `9e4331b99755e8feceb5bbfde851c7d7f081fa7a5e09c50eec8f464aecb90b24` | 2026-11-22T01:36:35Z |
| `20261122_labs.html` | https://www.topstep.com/labs | `16651d0ab93044e1ba504088dddc5494ffc309432adef35a0b040fa1e8744960` | 2026-11-22T01:53:08Z |
| `20261122_live_funded_rules.html` | https://www.topstep.com/live-funded-account-rules | `e4e401323d6ffe45784eb6e7f23ca6568c9d30968649cea3bd7d8dcb3bfdaf7f` | 2026-11-22T01:35:39Z |
| `20261122_our_program.html` | https://www.topstep.com/our-program | `a59e010934573b2a6e5029fefdb7ee00c478bb39e975faa161de5be039843b8a` | 2026-11-22T01:35:38Z |
| `20261122_topstep_prop.html` | https://www.topstep.com/topstep-prop | `3821e4b3decdb7e79da48689b95e9d1b175bfaa10ffd4e0ea0f86cd915fb6d7e` | 2026-11-22T01:35:38Z |
The scaling plan's ladder is published as an image, saved byte-for-byte beside the pages:
`20261123_hc_scaling-plan-xfa-charts.png` (PNG, 5515x2474, sha256
`55ec76b4b293822849c9bf8a8ac2de362fa895010d39ce9c0d00f4ed275e6cbd`, from
`https://help.topstep.com/en/articles/8284223-what-is-the-scaling-plan`, the `XFA charts - hc.png` the
page serves). It is **not transcribed here**: the images are the owner's to read, and no contract
number in a ruleset may come from a reading of them.

The commissions page (`8284213`) was fetched in this pass; it was not in the first draft's snapshot
set, which is why the drafts carried no commission table.

## 3. Product matrix (generated from the YAML)

Regenerate with `topstep/write_research.py`; every number below is read back from the files, so the
table cannot drift from them.

| file | size | DLL | target | evaluation MLL | contracts | min days | consistency | funded MLL | payout | gates | cap | split | fees |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `topstep-trading-combine-50k.v1.yaml` | $50,000 | - | $3,000 | $2,000 lock 52000->50000 | 5 | 2 | 0.55 pass | $2,000 lock@ 2000 -> 0 (hwm, first_payout) | standard | 5d>=$150 / 0 traded, buf $0 | $2,000 and 50% of balance | 0.9 | $49 per_month; $149 at_pass |
| `topstep-trading-combine-50k-daily-loss-limit.v1.yaml` | $50,000 | yes | $3,000 | $2,000 lock 52000->50000 | 5 | 2 | 0.55 pass | $2,000 lock@ 2000 -> 0 (hwm, first_payout) | standard | 5d>=$150 / 0 traded, buf $0 | $4,000 and 50% of balance | 0.9 | $49 per_month; $149 at_pass |
| `topstep-trading-combine-50k-consistency-payout.v1.yaml` | $50,000 | - | $3,000 | $2,000 lock 52000->50000 | 5 | 2 | 0.55 pass | $2,000 lock@ 2000 -> 0 (hwm, first_payout) | consistency | 0d>=$0 / 3 traded, buf $0 | $3,000 and 50% of balance | 0.9 | $49 per_month; $149 at_pass |
| `topstep-trading-combine-50k-consistency-payout-daily-loss-limit.v1.yaml` | $50,000 | yes | $3,000 | $2,000 lock 52000->50000 | 5 | 2 | 0.55 pass | $2,000 lock@ 2000 -> 0 (hwm, first_payout) | consistency | 0d>=$0 / 3 traded, buf $0 | $6,000 and 50% of balance | 0.9 | $49 per_month; $149 at_pass |
| `topstep-trading-combine-50k-no-activation-fee.v1.yaml` | $50,000 | - | $3,000 | $2,000 lock 52000->50000 | 5 | 2 | 0.55 pass | $2,000 lock@ 2000 -> 0 (hwm, first_payout) | standard | 5d>=$150 / 0 traded, buf $0 | $2,000 and 50% of balance | 0.9 | $95 per_month |
| `topstep-trading-combine-50k-no-activation-fee-daily-loss-limit.v1.yaml` | $50,000 | yes | $3,000 | $2,000 lock 52000->50000 | 5 | 2 | 0.55 pass | $2,000 lock@ 2000 -> 0 (hwm, first_payout) | standard | 5d>=$150 / 0 traded, buf $0 | $4,000 and 50% of balance | 0.9 | $95 per_month |
| `topstep-trading-combine-50k-no-activation-fee-consistency-payout.v1.yaml` | $50,000 | - | $3,000 | $2,000 lock 52000->50000 | 5 | 2 | 0.55 pass | $2,000 lock@ 2000 -> 0 (hwm, first_payout) | consistency | 0d>=$0 / 3 traded, buf $0 | $3,000 and 50% of balance | 0.9 | $95 per_month |
| `topstep-trading-combine-50k-no-activation-fee-consistency-payout-daily-loss-limit.v1.yaml` | $50,000 | yes | $3,000 | $2,000 lock 52000->50000 | 5 | 2 | 0.55 pass | $2,000 lock@ 2000 -> 0 (hwm, first_payout) | consistency | 0d>=$0 / 3 traded, buf $0 | $6,000 and 50% of balance | 0.9 | $95 per_month |
| `topstep-trading-combine-100k.v1.yaml` | $100,000 | - | $6,000 | $3,000 lock 103000->100000 | 10 | 2 | 0.55 pass | $3,000 lock@ 3000 -> 0 (hwm, first_payout) | standard | 5d>=$150 / 0 traded, buf $0 | $3,000 and 50% of balance | 0.9 | $99 per_month; $149 at_pass |
| `topstep-trading-combine-100k-daily-loss-limit.v1.yaml` | $100,000 | yes | $6,000 | $3,000 lock 103000->100000 | 10 | 2 | 0.55 pass | $3,000 lock@ 3000 -> 0 (hwm, first_payout) | standard | 5d>=$150 / 0 traded, buf $0 | $6,000 and 50% of balance | 0.9 | $99 per_month; $149 at_pass |
| `topstep-trading-combine-100k-consistency-payout.v1.yaml` | $100,000 | - | $6,000 | $3,000 lock 103000->100000 | 10 | 2 | 0.55 pass | $3,000 lock@ 3000 -> 0 (hwm, first_payout) | consistency | 0d>=$0 / 3 traded, buf $0 | $4,000 and 50% of balance | 0.9 | $99 per_month; $149 at_pass |
| `topstep-trading-combine-100k-consistency-payout-daily-loss-limit.v1.yaml` | $100,000 | yes | $6,000 | $3,000 lock 103000->100000 | 10 | 2 | 0.55 pass | $3,000 lock@ 3000 -> 0 (hwm, first_payout) | consistency | 0d>=$0 / 3 traded, buf $0 | $8,000 and 50% of balance | 0.9 | $99 per_month; $149 at_pass |
| `topstep-trading-combine-100k-no-activation-fee.v1.yaml` | $100,000 | - | $6,000 | $3,000 lock 103000->100000 | 10 | 2 | 0.55 pass | $3,000 lock@ 3000 -> 0 (hwm, first_payout) | standard | 5d>=$150 / 0 traded, buf $0 | $3,000 and 50% of balance | 0.9 | $149 per_month |
| `topstep-trading-combine-100k-no-activation-fee-daily-loss-limit.v1.yaml` | $100,000 | yes | $6,000 | $3,000 lock 103000->100000 | 10 | 2 | 0.55 pass | $3,000 lock@ 3000 -> 0 (hwm, first_payout) | standard | 5d>=$150 / 0 traded, buf $0 | $6,000 and 50% of balance | 0.9 | $149 per_month |
| `topstep-trading-combine-100k-no-activation-fee-consistency-payout.v1.yaml` | $100,000 | - | $6,000 | $3,000 lock 103000->100000 | 10 | 2 | 0.55 pass | $3,000 lock@ 3000 -> 0 (hwm, first_payout) | consistency | 0d>=$0 / 3 traded, buf $0 | $4,000 and 50% of balance | 0.9 | $149 per_month |
| `topstep-trading-combine-100k-no-activation-fee-consistency-payout-daily-loss-limit.v1.yaml` | $100,000 | yes | $6,000 | $3,000 lock 103000->100000 | 10 | 2 | 0.55 pass | $3,000 lock@ 3000 -> 0 (hwm, first_payout) | consistency | 0d>=$0 / 3 traded, buf $0 | $8,000 and 50% of balance | 0.9 | $149 per_month |
| `topstep-trading-combine-150k.v1.yaml` | $150,000 | - | $9,000 | $4,500 lock 154500->150000 | 15 | 2 | 0.55 pass | $4,500 lock@ 4500 -> 0 (hwm, first_payout) | standard | 5d>=$150 / 0 traded, buf $0 | $5,000 and 50% of balance | 0.9 | $199 per_month; $149 at_pass |
| `topstep-trading-combine-150k-daily-loss-limit.v1.yaml` | $150,000 | yes | $9,000 | $4,500 lock 154500->150000 | 15 | 2 | 0.55 pass | $4,500 lock@ 4500 -> 0 (hwm, first_payout) | standard | 5d>=$150 / 0 traded, buf $0 | $10,000 and 50% of balance | 0.9 | $199 per_month; $149 at_pass |
| `topstep-trading-combine-150k-consistency-payout.v1.yaml` | $150,000 | - | $9,000 | $4,500 lock 154500->150000 | 15 | 2 | 0.55 pass | $4,500 lock@ 4500 -> 0 (hwm, first_payout) | consistency | 0d>=$0 / 3 traded, buf $0 | $6,000 and 50% of balance | 0.9 | $199 per_month; $149 at_pass |
| `topstep-trading-combine-150k-consistency-payout-daily-loss-limit.v1.yaml` | $150,000 | yes | $9,000 | $4,500 lock 154500->150000 | 15 | 2 | 0.55 pass | $4,500 lock@ 4500 -> 0 (hwm, first_payout) | consistency | 0d>=$0 / 3 traded, buf $0 | $12,000 and 50% of balance | 0.9 | $199 per_month; $149 at_pass |
| `topstep-trading-combine-150k-no-activation-fee.v1.yaml` | $150,000 | - | $9,000 | $4,500 lock 154500->150000 | 15 | 2 | 0.55 pass | $4,500 lock@ 4500 -> 0 (hwm, first_payout) | standard | 5d>=$150 / 0 traded, buf $0 | $5,000 and 50% of balance | 0.9 | $229 per_month |
| `topstep-trading-combine-150k-no-activation-fee-daily-loss-limit.v1.yaml` | $150,000 | yes | $9,000 | $4,500 lock 154500->150000 | 15 | 2 | 0.55 pass | $4,500 lock@ 4500 -> 0 (hwm, first_payout) | standard | 5d>=$150 / 0 traded, buf $0 | $10,000 and 50% of balance | 0.9 | $229 per_month |
| `topstep-trading-combine-150k-no-activation-fee-consistency-payout.v1.yaml` | $150,000 | - | $9,000 | $4,500 lock 154500->150000 | 15 | 2 | 0.55 pass | $4,500 lock@ 4500 -> 0 (hwm, first_payout) | consistency | 0d>=$0 / 3 traded, buf $0 | $6,000 and 50% of balance | 0.9 | $229 per_month |
| `topstep-trading-combine-150k-no-activation-fee-consistency-payout-daily-loss-limit.v1.yaml` | $150,000 | yes | $9,000 | $4,500 lock 154500->150000 | 15 | 2 | 0.55 pass | $4,500 lock@ 4500 -> 0 (hwm, first_payout) | consistency | 0d>=$0 / 3 traded, buf $0 | $12,000 and 50% of balance | 0.9 | $229 per_month |
| `topstep-labs-daily-payouts-plus-50k.v1.yaml` | $50,000 | yes | $3,000 | $2,000 eod, no lock | 5 | - | 0.55 pass | $2,000 lock@ 2000 -> 0 (hwm, first_payout) | daily+five_winning_days | $250..$1,500, buf $2,000, >=$0.01 since last | 5d>=$150, $125..$4,000, 50% of balance | $1,500 / $4,000 | 0.9 | $149 at_start; lifespan 90d; inactivity 30d |
| `topstep-labs-daily-payouts-plus-50k-static.v1.yaml` | $50,000 | yes | $4,000 | static $2,000 | 5 | - | 0.55 pass | none (`not_modeled` critical) | daily+five_winning_days | $250..$1,500, buf $2,000, >=$0.01 since last | 5d>=$150, $125..$8,000, 50% of balance | $1,500 / $8,000 | 0.9 | $149 at_start; lifespan 90d; inactivity 30d |
Every funded `payout` rule declares `min_profit_since_last_usd: '0.01'` where the gate can
bind (24 Trading Combine files and the Labs Daily Payout path). The 5 Winning Days path states no
such gate and needs none: five winning days of $150 already imply positive net profit since the last
payout, so the gate is inert there and its description says so.

The Labs files carry `addons: []` because the $1,000 Daily Loss Limit is part of the drop's bundle
rather than a checkout add-on; the rule is present in both phases all the same.

## 4. Commissions (ADR-0107 section 10)

`commissions.status: known`, `platform: TopstepX`, one set for every file (all 26 rulesets are
TopstepX accounts).

Source: `https://help.topstep.com/en/articles/8284213-what-are-the-commissions-and-fees-in-the-trading-combine-and-express-funded-account`
("TopstepX™ — Commissions and Fees", September 30, 2026), sha256 `eb810a53…8c1`. The page gives a
**round-turn total per product** and says each side pays half: "Round-Turn (RT) cost: charged when
you complete both sides of a trade. Each side (Buy or Sell) incurs half the total, also called a
'per side' fee." The per-side figure in each ruleset is that total / 2:

| root | round turn | per side | quote (product table) |
|---|---|---|---|
| ES | $3.78 | **$1.89** | `E-mini S&P 500 (ES) $3.78` |
| NQ | $3.78 | **$1.89** | `E-mini NASDAQ 100 (NQ) $3.78` |
| YM | $3.78 | **$1.89** | `Mini-DOW (YM) $3.78` |
| RTY | $3.78 | **$1.89** | `E-mini Russell 2000 (RTY) $3.78` |
| NKD | $5.32 | **$2.66** | `Nikkei (NKD) $5.32` |
| MES | $1.22 | **$0.61** | `Micro E-mini S&P 500 (MES) $1.22` |
| MNQ | $1.22 | **$0.61** | `Micro E-mini NASDAQ 100 (MNQ) $1.22` |
| MYM | $1.22 | **$0.61** | `Micro Mini-DOW (MYM) $1.22` |
| M2K | $1.22 | **$0.61** | `Micro E-mini Russell 2000 (M2K) $1.22` |

The total includes the exchange fee and the $0.02 NFA regulatory fee, so it is the true cost per
side, not the $0.50/$0.25 commission line alone. "These fees apply when trading the Trading Combine,
Express Funded Account, and Live Funded Account." — one table for every TopstepX product, so no
per-plan variant is needed. **Other platforms are not modeled**: the files are `platform: TopstepX`,
and no page states their per-side table (the funded-account page only says that accounts on other
platforms also carry a Daily Loss Limit). A ruleset for another platform is a new file, not a
different value here.

## 5. News restrictions (ADR-0107 section 12)

**Two** `news_restriction` rules in **both** phases of every file, because the firm blocks the minis
and caps the micros in the same window:

| rule_id | instruments | effect | what it does |
|---|---|---|---|
| `tier1_news_equity_index_minis` | ES, NQ, RTY, YM, NKD | `block` | no new opening transaction inside the window |
| `tier1_news_micro_contract_caps` | MES, MNQ, MYM, M2K | `contract_cap`, `cap_contracts` 0.3 / 0.6 / 0.9 | the size is clipped to 3 / 6 / 9 micros inside the window (a micro weighs 0.1) |

Both carry:

- `event_types: [CPI, FOMC_STATEMENT, FOMC_PRESS_CONFERENCE, NFP, PPI]` — every event the page's
  Tier 1 table names, each with a 5-minute window either side (CPI 7:30 AM CT, the FOMC rate
  decision 1:00 PM CT, the FOMC press conference 1:30 PM CT, NFP 7:30 AM CT, PPI 7:30 AM CT). The
  table does **not** name the FOMC minutes, so `FOMC_MINUTES` is not declared;
- `pre_minutes: 5`, `post_minutes: 5` (the "10-minute window surrounding the release");
- `scope: new_entries`, `flatten: none` — "Traders holding existing positions in equity index
  products and metals prior to 5 minutes before the news event may keep them open and manage them
  through the Tier 1 News Events window";
- `comparison: >=`, `action: block_entries`.

Sources: `https://help.topstep.com/en/articles/13613539-risk-adjustments-high-risk-high-volatility`,
section "Tier 1 News Events Restrictions" — "Minis (ES, RTY, YM, NQ, NKD, GC, SI, HG, PL): No new
opening transactions permitted during the 10-minute window surrounding the release (5 minutes
before, 5 minutes after)." and "Micros (MES, M2K, MYM, MNQ, MGC): Opening transactions limited to 1,
3, 6, 9, and 15 contracts for the $25K, $50K, $100K, $150K, and $250K account sizes, respectively,
during the window".

Two consequences the report carries:

- The **FOMC press conference** is the one Tier 1 event whose hour no Topstep or Federal Reserve HTML
  page states (`docs/data/econ-events.md`: `time_known = false`). An event with no stated time is
  NOT widened to its whole local day: it is a **coverage gap for that trade date**. Its whole trade
  date is outside news coverage, the `news_restriction` rules are `not_modeled` for that attempt,
  the estimate becomes `partial` and the event ids are reported
  (`crucible/prop/news.py::unknown_time_gaps`, `crucible/prop/overlay.py::_news_windows`). What the
  simulation does on an FOMC day is therefore *nothing* about the press conference, stated as a gap,
  never a silent block and never "no news". A whole-day blackout around the press conference is a
  defensible *owner-chosen sensitivity scenario* (it needs the hour, or that decision, from the
  owner); it is not what is simulated.
- The metals (GC, SI, HG, PL minis; MGC, MHG, SIL micros) the same section restricts are **not in any
  file's instrument set**, so they are neither blocked nor capped: an account that cannot hold them
  has nothing to restrict.

And a discretionary news rule, `news_full_position_size_prohibited` (material): "Purposefully trading
your full Maximum Position Size directly into a scheduled major news event" has no numeric
threshold, so no rule can decide it.

The `news_restriction` evaluator receives its events from the calendar; an attempt window the
calendar does not cover marks the rule `not_modeled` for that attempt (material) and never "no news".

## 6. Compliance rules (ADR-0107 section 11)

Five `compliance` rules sit in the evaluation phase of every file (declared once per plan; the
funded account is the same purchase). None is `critical`, so **none blocks practical eligibility**:
Topstep has no blanket ban on automated trading, unlike Apex.

| rule_id | restriction (verbatim source) | execution mode | materiality | action |
|---|---|---|---|---|
| `unfair_technology` | "Unfair technology — using software, AI, ultra-high speed systems, or mass data entry to gain an unfair advantage" | automated | material | none |
| `sim_fill_exploitation` | "Running scalping algorithms designed to exploit unrealistic SIM fills" | automated | material | none |
| `trade_outside_best_bid_offer` | "Trading Outside the Best Bid or Offer" | automated, manual | material | none |
| `coordinated_and_copy_trading` | "Coordinated trading — performing trades in concert with others ... to pool risk, hedge aggregate positions, or trade the same or opposite strategy simultaneously" | automated, manual | material | none |
| `account_stacking` | "Account stacking — repeatedly hitting the Maximum Loss Limit in one account and switching to another to repeat high-risk attempts" | automated, manual | material | none |

Sources: `.../10296582-prohibited-conduct` ("What Is Prohibited Conduct?") and
`.../10305426-prohibited-trading-strategies-at-topstep`. `action: none` is deliberate: these are
conduct judgements ("an unfair advantage", "a discretionary determination by Topstep's Risk Team"),
so they are declared with their materiality and left to the report rather than pretending a
mechanically passing account is a practically valid one. Cross-account hedging stays a
`not_modeled` entry, as the owner ruled (a single simulated account cannot hedge itself).

**The six `effect: condition` rules (owner decision F21, 2026-11-23).** Automated trading is
permitted, but only under obligations no bar-by-bar simulation can see. Each is a `compliance` rule
with `effect: condition`, `applies_to_execution: [automated]`, `materiality: material`,
`action: none`, quoted from `20261123_hc_topstepx-api-access.html` (sha256 `876d2214…788e`):

| rule_id | condition (listed verbatim in the report) |
|---|---|
| `automated_trading_through_the_api` | the algorithm trades only through a linked TopstepX / ProjectX API subscription, in a Combine or an XFA |
| `no_api_trading_in_the_live_funded_account` | it is never pointed at a Live Funded Account, where the API does not exist |
| `high_frequency_trading_prohibited` | no high-frequency trading: no page states a threshold, so the boundary is Topstep's judgement |
| `orders_originate_on_the_personal_device` | every order is transmitted from the trader's own personal device |
| `no_order_entry_from_a_vps_vpn_or_remote_server` | no VPS, VPN or remote server places, modifies or cancels an order |
| `the_algorithm_remains_subject_to_every_rule` | the algorithm obeys every trading rule and policy exactly as manual trading does |

Practical eligibility for `automated` is therefore `eligible_conditional` (no critical rule blocks,
six conditions apply) and a mechanical pass is a `conditionally_valid_passes`, never a
`practically_valid_passes`. Authorization is no guarantee of compliance: an API key is what Topstep
grants, and the page says API orders are final and that a rule violation counts the same for a bot.
`execution_mode: manual` is unaffected by all six (they apply to `automated` only), so a manual run
of the same ruleset stays `eligible`.

## 7. Conflicts

**Genuine conflicts recorded in the files: 1** — `labs_daily_payout_minimum` in each of the two
Labs files (item 5). The other four candidates below were examined and each failed the
same-conditions test of ADR-0107 section 7:

1. **The payout cap: a flat figure vs the per-size table.** The payout policy page shows path cards
   ("Request 50% of the account balance up to $5000*" for Standard, "$6,000*" for Consistency) next
   to a per-size table ($50K Standard $2,000 ... $150K Standard $5,000). The cards are not a
   size-independent cap: they are exactly the **$150K row** ($5,000 and $6,000), and the product
   page prints a per-size pair on every size card ($2,000/$4,000 for 50K, $3,000/$6,000 for 100K,
   $5,000/$10,000 for 150K). Same firm, plan, size, phase, platform and effective period, and the
   numbers agree once the card is read as the top of the range. Not a conflict; the per-size value is
   selected and the card is not cited as a value.
2. **The public `/express-funded-account-rules` page (last updated 2025-06-26) is SUPERSEDED**
   (owner decision F16, 2026-11-23). It still says "Request up to 50% of your account balance, up to
   $6,000" and "a max of $5,000 (Standard) or $6,000 (Consistency XFA) per payout", flat across
   sizes, and adds "After the first payout, a Minimum Payout Balance must be met". That is a
   different effective period from the 2026 payout policy page and the current product page, which
   both price the caps per size. The page is **kept as a historical source only and is never an
   authority for the 2026-11-22 rules**: it supplies no value to these files, and its
   minimum-balance requirement is **not a rule** here (it is not modeled, not quoted and not
   assumed). The snapshot stays in the set so the record of why it was dropped survives.
3. **The XFA Maximum Loss Limit: two triggers.** "Your MLL starts at -$2,000 and trails upward. Once
   your balance reaches $2,000, the MLL locks at $0 permanently" and "After your first Payout: Your
   MLL is set to $0 regardless of where it was before." Not contradictory (both are true, on
   different paths), and no longer a gap: the round-2 lock takes a trigger list, so every funded MLL
   declares `lock.on: [hwm, first_payout]` and freezes at $0 at whichever fires first.
4. **The doubled payout cap (Daily Loss Limit).** The payout policy page ("Traders who voluntarily add
   a Daily Loss Limit to their account unlock double per-request payout caps") and the product page
   ("$2,000 / $4,000" on the 50K card, "DOUBLE Payout Caps: Included") agree, on the same effective
   period. This is a variant, not a conflict: the twelve files that carry `addons:
   [daily_loss_limit]` **and the doubled cap**, and the other files carry the base cap. This is a
   value change from the v1 draft, which used the base cap for the DLL variants too — flagged for the
   owner below, because the offer is described as a limited-time offering with an unpublished end
   date while the pages still show it as live.
5. **The Labs Daily Payout minimum: $250 or $125 — recorded as a conflict.** Same firm, plan, size,
   phase, platform and effective period, and the two live pages disagree: the Labs help article's
   "Choose your Payout path" table gives the Daily Payout column "Amount $250 minimum, $1,500
   maximum", while the firm-wide payout policy states "Minimum Payout: $125". The drop page is the
   more specific statement and $250 is the more restrictive reading (fewer and larger payouts), so
   `selected_value: '250'` with the $125 reading kept as sensitivity scenario
   `labs_daily_payout_minimum#0`. Both sources stay in the file. **Owner decision
   (2026-11-23):** confirmed - $250 stays the primary reading because it is the more
   restrictive one, $125 stays the sensitivity scenario, and the conflict stays: the value is
   a `conflict_resolution`, never a verification.

### The payout-policy check (owner decision F16, 2026-11-23)

Every file was checked against the CURRENT payout policy page (snapshot
`20261123_hc_topstep-payout-policy.html`, sha256 `22aa745f…ad1f6`), whose terms are:

| term | the page's words | declared in the files |
|---|---|---|
| Standard path | "5 winning days of $150+ Net P&L. Days don't need to be consecutive. A day locks in at 4:00 PM CT." | `min_profitable_days: 5`, `min_day_profit_usd: 150`, `window: since_last_payout` — 12 Standard files, already correct |
| Standard, net profit | "Positive net profit since your last Payout. You must have earned at least $0.01 since your last Payout. Your first Payout is exempt." | **was missing** in all 24 Trading Combine files (see below) |
| Consistency path | "3 trading days with at least 1 trade per day." and "Stay at or below the 40% Consistency Objective." | `min_traded_days: 3` + a `consistency` rule `max_day_share: 0.4` on the payout — 12 Consistency files |
| Maximum request | "Payout caps by account size Max Payout per request: 50% of your account balance up to the cap below." | `max_pct_of_balance: 50` + `max_usd` per size and path — all 26 files |
| General minimum | "Minimum Payout: $125" | `min_usd: 125` — all 26 files (the Labs Daily path's own $250 stays the primary reading of its recorded conflict) |
| Split | "90/10 profit split — you keep 90%" | `split: 0.9` — all 26 files (the Labs files now quote their own page's "Profit Split 90/10") |

**Mismatches found: one, and it was fixed where the page supports it.**

1. **The $0.01 net-profit-since-last-Payout gate was declared nowhere.** `min_profit_since_last_usd`
   was absent (0) in all 26 files, which lets a later payout go out at a LOWER balance than the
   previous one as long as the balance is above the starting balance — the policy allows that only
   after a payout, never on the first one, and only with "at least $0.01" earned since the last.
   **Fixed:** `min_profit_since_last_usd: '0.01'` on every funded `payout` rule of the 24 Trading
   Combine files (quoted, with the description carrying the sentence) and on the Labs Daily Payout
   path, whose own page states "After your first Payout, you must be net positive since your last
   Payout." The first payout needs no exemption mechanism: its balance requirement already implies
   a profit, and the gate is measured from the last payout's balance.
2. **The Labs 5 Winning Days path declares no such gate, on purpose.** The drop page states none,
   and five winning days of $150 already imply positive net profit since the last payout, so the
   gate could never bind there. Reported, not declared, and the rule's description says so.
3. **Nothing else moved.** The caps, the 50%, the $125 minimum, the 3 traded days and the 40%
   consistency objective were already declared and match; the Labs Daily path's $250 remains the
   primary reading of the recorded conflict with the general $125, with $125 as sensitivity
   scenario `labs_daily_payout_minimum#0` (owner decision, F10).

## 8. Assumptions applied (ADR-0107 section 7 defaults)

Only the defaults the owner fixed, each recorded as `evidence: assumption` with its name:

| assumption name | rule(s) | files | rationale |
|---|---|---|---|
| `unspecified_target_frequency_is_eod` | `profit_target` | 26 (every file) | The pages state the target amount but never its observation frequency. A target is a pass condition, so the conservative default is the opposite of the failure-threshold one: the target is tested at the end of the trade date on the closed balance, because the trader passes no earlier than the end of the trade date and a later same-day breach still counts. Never intraday for a target the firm does not date. |
| `trading_day_is_a_trade_date_with_at_least_one_trade` | `minimum_trading_days` | 24 (the Trading Combine files; the Labs drop states no minimum) | The pages state a two-day minimum but never define a qualifying day. ADR-0107 section 7 default: a trading day is a trade date with at least one executed trade. **Owner decision (2026-11-23): confirmed** - an EXECUTED trade (an unfilled order does not count, a roll leg is not a trade) inside the Topstep session, 5:00 PM CT to 3:10 PM CT, which is the 17:00 America/Chicago rule-day the files declare (`crucible/prop/overlay.py` step 7). Payout qualifying days keep their own gates and never read this default. || `xfa_inactivity_may_be_closed_on_day_31` | funded `xfa_inactivity` | 24 (the Trading Combine files) | The page says an XFA with no activity for more than 30 days **may** be closed, a soft statement. The pessimistic reading closes it at the start of the 31st calendar day after the last trade date (30 full days of silence), the rule-day transition the overlay counts inactivity on, and never describes a guaranteed automatic close. `assumption_kind: provisional_conservative` (owner decision, 2026-11-23). The 2 Labs files carry no such assumption: their drop page states the closure itself, and it is declared as an `inactivity` rule of the EVALUATION phase (the phase whose table publishes it), with no funded-phase inactivity at all. |
| `labs_five_winning_days_minimum_from_firm_policy` | `payout_five_winning_days` | 2 (the Labs files) | The drop page states the five-day eligibility, the buffer (none), the per-payout cap ($4,000 EOD / $8,000 Static), 50% of balance and the 90/10 split, but no minimum for that path. The firm-wide Express Funded Account minimum (`Minimum Payout: $125`) is used, and the owner ruled on 2026-11-23 that this general minimum is the 5 Winning Days path's minimum: `assumption_kind: owner_decision`, never a quote of the drop page. |

The 90/10 split is no longer an assumption: `payout_split_taken_from_firm_payout_policy` is gone
because the drop page states the split itself ("Profit Split 90/10", in its `Choose your Payout
path` columns), and both Labs payout rules now quote that page (owner decision F10, 2026-11-23). The
`min_profit_since_last_usd: '0.01'` gate is quoted from the firm-wide policy and the drop's own
net-positive sentence, not assumed (see section 7).

The static Labs substitution that this table carried until 2026-11-23 (`static_xfa_drawdown_taken_as_the_trailing_firm_form`) is **gone**: the owner refused it (F8) because the drop states a post-first-payout reset on the static floor, which no vocabulary expresses, so the funded rule is `not_modeled` critical instead of approximated.

No other default was needed. "CT" is quoted by the firm, so the time zone is `America/Chicago`
directly (an ADR default of `America/New_York` would have been wrong). Every **failure** threshold's
observation frequency is stated and stays `intraday` (MLL "monitored in real time throughout the
session", DLL "during the trading day (5 PM CT - 3:10 PM CT)"), and the only unstated frequency is
the profit target's, which is why it carries the `unspecified_target_frequency_is_eod` assumption.
The payout day is stated ("A day locks in at 4:00 PM CT"), so the payout rules carry no default.

## 9. What is not modeled, by materiality

Six entries in the 24 Trading Combine files, six in the trailing Labs drop, seven in the static one
(three material everywhere; the static drop adds its drawdown substitution).

**Material** (the evaluation status is `conditional_on_modeled_rules` because of these), with the
condition an audit would have to establish before the materiality could change:

| rule | why | `becomes_immaterial_if` |
|---|---|---|
| `xfa_scaling_plan_ladder` | The XFA's contract limit follows the Scaling Plan, which the article calls "an Express Funded Account® (XFA) objective" setting the maximum position size by balance. The ladder exists **only as an image**, saved at `prop_snapshots/topstep/20261123_hc_scaling-plan-xfa-charts.png` (sha256 `55ec76b4…6cbd`), so no contract number is quoted and the funded phase's own limit is NOT declared — not "no limit", and never the Combine's maximum. | — (an owner transcription of the ladder is what would model it; until then the entry stands) |
| `news_full_position_size_prohibited` | Discretionary news rule, no threshold, no invented window. | — (never self-service: the owner must decide) |
| `sub_minute_holding_and_micro_scalping` | Material for one-minute granularity: the ban is on algorithmic scalping that exploits unrealistic SIM fills, and the page's seconds are an example, not a universal threshold. Never an automatic ban on holds under 60 s. | — (needs intra-bar data) |
| `two_percent_price_limit_restriction` | A hard prohibition the engine cannot test: no CME price-limit band is carried. | an audit of the instruments and dates shows it never affected a trade |
| `volatility_position_limit_tightening` | The firm may tighten limits by announcement ("Trading on mini-sized contracts or larger may be temporarily halted for affected products"); the published restrictions cover energies, metals and Micro Bitcoin only, none of the nine roots here. | shown not to affect the evaluated universe, dates and sizes |

**Critical** (the estimate is `unavailable` because of it):

| rule | why |
|---|---|
| `static_xfa_drawdown_post_payout_reset` | Static Labs drop only: the page states "$2,000 static, non-trailing" **and** "After first Payout, MLL sets to $0". `static_drawdown` has no post-payout reset or lock and the trailing form is not this rule, so the funded phase declares no loss limit at all rather than an approximation (owner decision 2026-11-23, F8). |

**Immaterial** (declared and warned, and it does not weaken the status):

| rule | why | `becomes_immaterial_if` |
|---|---|---|
| `cross_account_hedging` | A single simulated account cannot hedge itself: the rule constrains how many accounts a person runs. | "becomes material if multiple accounts, copy trading or coordinated strategies are simulated" (the field states the fact that would make it bind) |

`two_percent_price_limit_restriction` and `volatility_position_limit_tightening` moved from
immaterial to material (owner decision F13, 2026-11-23): both were immaterial by an argument about
what the data probably never touches, which is exactly what an audit has to establish and the
declaration may not assume. Every entry above declares the fact an audit would need, and the
declared materiality itself never changes until that audit exists.

## 10. Vocabulary now used, and what it replaced

The C7b vocabulary expresses these rules exactly, so their `not_modeled` entries are **gone**:

| removed entry | what models it now |
|---|---|
| `payout_capped_at_half_the_balance` | `payout.max_pct_of_balance: 50` ("Max Payout per request: 50% of your account balance up to the cap below.") |
| `payout_window_resets_after_each_payout` | `payout.window: since_last_payout` (+ `consistency.window: since_last_payout`) — "your 5-day count restarts", "The trading day your Payout is requested doesn't count toward your next 5", "your consistency calculation resets". The MLL half of the entry is `lock.on: [hwm, first_payout]` above (round 2). |
| `tier1_news_event_position_restrictions` | the two `news_restriction` rules (minis blocked, micros capped). |
| `xfa_mll_set_to_zero_by_first_payout` (round 2) | `lock.on: [hwm, first_payout]` on every funded MLL. |
| `tier1_news_micro_contract_caps` (round 2) | `news_restriction.effect: contract_cap` with `cap_contracts` 0.3 / 0.6 / 0.9. |
| `tier1_news_event_types_outside_the_calendar` (round 2) | the calendar now carries `PPI` and `FOMC_PRESS_CONFERENCE`, so both are declared event types. |
| `fifth_winning_days_payout_path` (round 2) | a second `payout` rule with `payout_group: labs_xfa_payout_paths` ($4,000 EOD / $8,000 Static, no buffer, 50% of balance). |
| `static_funded_drawdown_not_stated` (round 2) | re-sourced from the Labs help article and replaced by `static_xfa_drawdown_taken_as_trailing` (a declared substitution, not a missing value). |
| `xfa_inactivity_closure` | `inactivity` {max_gap 30, calendar_days, rolling} — "XFAs with no trading activity for more than 30 days may be closed." |
| `prohibited_strategies_and_compliance_review` | the five `compliance` rules (section 6). |
| `activation_fee_waiver` | the waiver **is** the absence of the activation fee rule on the No Activation Fee path; a fee the file does not charge needed no `not_modeled` row. |
| `xfa_contract_limit_not_stated` (Labs) | folded into `xfa_scaling_plan_ladder`, which is the same root cause. |

Vocabulary used elsewhere: `hwm_basis: balance` (the mark moves on the end-of-day balance while the
threshold is tested intrabar on equity — the two statements of the MLL page, now both declared),
`lock.on: [hwm]` (a list, one trigger) with `locked_threshold_usd`, `day_counts_if`,
`min_traded_days: 3` on the Consistency
payout path ("Trade at least three (3) days with at least one (1) trade per day" replaces the v1
approximation `min_profitable_days: 3` with a zero profit floor), `max_usd` as a number (no
sentinel), `fee.when: per_month` / `at_pass` / `at_start`, and the explicit day units every rule now
carries (`calendar_days` for inactivity, `trading_days` for the 2-day minimum).

Vocabulary that does **not** fit these products and is therefore unused: `daily_profit_cap` (Topstep
has none), `scaling_plan` `steps` (the XFA ladder is image-only, so declaring steps would be
inventing them), `daily_loss.amount_by_balance_tier` / `pct_of_peak_profit` (the DLL is a flat
amount by size), `max_usd_by_payout`, `max_share_of_withdrawable`,
`first_payout_after_calendar_days`, `cycle_goal_usd`, `activity_requirement` (no page states a
minimum number of qualifying days in a rolling window; the only activity rule is the 30-day
`inactivity` close), `min_new_profit_share_of_request` (the firm states a minimum balance and a
minimum profit of one cent, not a share of the request), `consistency.numerator_window` /
`denominator_window` (both windows are the same payout window: "your consistency calculation resets"
and "applies only to profits earned afterward"), `flat_by.minutes_before_session_end` (Topstep's
3:10 PM CT is a fixed clock, not a session offset, and the day-trading rule is not defined relative
to the CME session), `fee.on_reset` (a Reset is attempt policy, not a phase fee), `time_limit` (there
is no time limit: "no time limit for passing"), `payout.threshold_after_payout: set_threshold` with
`set_threshold_to` (the firm's post-payout level is $0, which `lock.on: first_payout` already
declares, and no page states a non-zero level).

## 11. Modeling notes (decisions inside the files)

- **The rule-day clock is 17:00 America/Chicago**: "The trading day runs from 5:00 PM CT to 3:10 PM
  CT the next calendar day." Every reset clock in every file is that boundary, and it is a firm
  declaration, not the engine's default.
- **The MLL basis split.** Topstep marks the MLL from the *end-of-day balance* ("Rises as your
  end-of-day balance grows") and tests it on *equity* including unrealized P&L ("monitored in real
  time throughout the session. Both realized and unrealized P&L count toward it"). `hwm_basis:
  balance` + `mode: eod` + `evaluated: intraday` + `basis: equity` states both. The v1 draft had to
  use `basis: equity` for both and argue that the two coincide; with `hwm_basis` they are separate
  declarations and no assumption is needed.
- **The lock point.** "Locks permanently once it reaches your starting balance": for a Combine the
  threshold reaches $50,000 when the end-of-day balance reaches $52,000, so `at_balance_usd` is
  size + MLL; for an XFA the starting balance is $0, so the lock triggers at a balance equal to the
  MLL amount ($2,000 / $3,000 / $4,500).
- **Two triggers, one lock.** Every funded MLL declares `lock.on: [hwm, first_payout]`: the firm
  states both ("locks permanently once it reaches your starting balance"; "After each Payout: Your
  Maximum Loss Limit (MLL) resets to $0 permanently", and "Your MLL is set to $0 after your first
  Payout. If it's already at $0, it stays there."). Either trigger freezes the threshold at $0, which
  is the same level on both paths, and the engine takes the first one that fires.
- **The Labs drops' two payout paths** are declared together with `payout_group:
  labs_xfa_payout_paths`, because the drop lets the trader pick at each request ("you pick at each
  Payout request, not at activation ... you can switch every Payout"): at most one path pays at a
  close, and the attempt policy takes the larger net.
- **Consistency equivalence.** "Best day at or below 55% of the profit target, else the target rises
  to best day / 0.55" is arithmetically `max_day_share: 0.55` on total profit. The pages state it
  both ways ("stay below 55% of total profits").
- **The 3:10 PM CT flat and the 4:00 PM CT day lock.** The engine closes a rule-day at 17:00 CT.
  Between 15:10 and 17:00 CT no position can exist and nothing can trade, so the best-day mark at
  3:10 PM and the payout day lock at 4:00 PM cannot differ from the 17:00 close. No value changes.
- **The Daily Loss Limit is a soft breach**: "Triggering it is not a rule violation — it's a forced
  break for the rest of that session" — `action: soft_lock_until_reset`, not `fail`, and it carries
  into the XFA ("Applies to your Express Funded Account after you pass").
- **The Labs funded account** is an Express Funded Account, so it carries the firm-wide XFA MLL, the
  firm's day-trading window and the 90/10 split; the drop adds its own caps, buffer and price.
- **Promotions carry the limited offer, not the ruleset's value.** The twelve `addons: [daily_loss_limit]` files state the STANDARD per-request cap and declare the doubling as `promotions: [dll_doubled_payout_cap]` (`multiplier: 2` on `max_usd`, `starts_on` 2026-06-02, `purchase_on_or_after` 2026-06-02, `ends_on: unknown`, `requires` `account_purchase: new` and `dll_selected_at_purchase: 'true'`, and the profile's `purchase_date`). The rule's own quote is the per-size row (`$50K Standard $2,000 $4,000`), so an ineligible run gets the standard cap with the reason recorded, and a promoted value never changes the file's hash (ADR-0107, amendment of 2026-11-23).
- **Inactivity, where each page publishes it.** The 24 Trading Combine files take the XFA page's soft "may be closed" and declare the pessimistic close in the FUNDED phase as `xfa_inactivity_may_be_closed_on_day_31` (`provisional_conservative`). The 2 Labs files quote their own drop page, which states the closure itself ("If there are no trades placed for 30 days, the account will close."), and declare it in the EVALUATION phase, where the drop's Challenge table publishes "Inactivity 30 days": no assumption, and no funded-phase inactivity, because the drop's Phase 2 table publishes none. The same table publishes "Lifespan 90 days", declared as a `time_limit` of 90 calendar days in the evaluation phase; neither reading is extrapolated to a standard Topstep product.
- **The Labs daily path's 50%-of-balance cap is not declared** because it cannot bind: with a $2,000
  buffer, the withdrawable amount is at or below 50% of the balance for any balance a $1,500 cap
  could reach (balance/2 >= balance - 2,000 for every balance <= 4,000, and above that the $1,500
  cap is already the binding one).

## 12. Products not drafted, and why

| product | status | why |
|---|---|---|
| Live Funded Account (all sizes) | **out of scope** | Live capital, not a simulated evaluation program (`https://www.topstep.com/live-funded-account-rules`, snapshotted). |
| Past Topstep Labs drops ($25K Static, $250K Freedom Funded, $1.5K/$3K/$6K Challenges, $50K Static, Powered Up, Undead, Slasher) | **legacy, not drafted** | The Labs page states past drops are no longer on sale; their values live on their own drop pages and only fragments (the static MLL table, per-product caps in the risk article) are in the saved text. |
| Back2Funded reactivation | **not a product** | Reactivates a lost XFA for a fee ($599 / $699 / $829 by size); it sells no account. Attempt policy, not a rule. |
| Any non-TopstepX platform | **not drafted** | The files are TopstepX; no per-side commission table is published for the other platforms. |

## 13. Per-file OWNER REVIEW CHECKLIST

Everything below is what the owner confirms before `crucible prop confirm` may verify a file. The
values come from the YAML, grouped as asked: account/thresholds, payouts, fees/commissions,
news/compliance, assumptions, conflicts.

### `topstep-trading-combine-50k.v1.yaml` — Trading Combine (Standard path, 50K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $2,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $49 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-50k-daily-loss-limit.v1.yaml` — Trading Combine (Standard path, 50K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $1,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $2,000 per request and 50% of the balance (the promotion `dll_doubled_payout_cap` doubles it to $4,000 for a new purchase with the DLL at checkout on or after 2026-06-02); minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $49 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-50k-consistency-payout.v1.yaml` — Trading Combine (Standard path, 50K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $3,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $49 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-50k-consistency-payout-daily-loss-limit.v1.yaml` — Trading Combine (Standard path, 50K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $1,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $3,000 per request and 50% of the balance (the promotion `dll_doubled_payout_cap` doubles it to $6,000 for a new purchase with the DLL at checkout on or after 2026-06-02); minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $49 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-50k-no-activation-fee.v1.yaml` — Trading Combine (No Activation Fee path, 50K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $2,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $95 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-50k-no-activation-fee-daily-loss-limit.v1.yaml` — Trading Combine (No Activation Fee path, 50K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $1,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $2,000 per request and 50% of the balance (the promotion `dll_doubled_payout_cap` doubles it to $4,000 for a new purchase with the DLL at checkout on or after 2026-06-02); minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $95 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-50k-no-activation-fee-consistency-payout.v1.yaml` — Trading Combine (No Activation Fee path, 50K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $3,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $95 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-50k-no-activation-fee-consistency-payout-daily-loss-limit.v1.yaml` — Trading Combine (No Activation Fee path, 50K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $1,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $3,000 per request and 50% of the balance (the promotion `dll_doubled_payout_cap` doubles it to $6,000 for a new purchase with the DLL at checkout on or after 2026-06-02); minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $95 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-100k.v1.yaml` — Trading Combine (Standard path, 100K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $3,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $99 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-100k-daily-loss-limit.v1.yaml` — Trading Combine (Standard path, 100K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $2,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $3,000 per request and 50% of the balance (the promotion `dll_doubled_payout_cap` doubles it to $6,000 for a new purchase with the DLL at checkout on or after 2026-06-02); minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $99 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-100k-consistency-payout.v1.yaml` — Trading Combine (Standard path, 100K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $4,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $99 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-100k-consistency-payout-daily-loss-limit.v1.yaml` — Trading Combine (Standard path, 100K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $2,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $4,000 per request and 50% of the balance (the promotion `dll_doubled_payout_cap` doubles it to $8,000 for a new purchase with the DLL at checkout on or after 2026-06-02); minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $99 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-100k-no-activation-fee.v1.yaml` — Trading Combine (No Activation Fee path, 100K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $3,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $149 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-100k-no-activation-fee-daily-loss-limit.v1.yaml` — Trading Combine (No Activation Fee path, 100K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $2,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $3,000 per request and 50% of the balance (the promotion `dll_doubled_payout_cap` doubles it to $6,000 for a new purchase with the DLL at checkout on or after 2026-06-02); minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $149 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-100k-no-activation-fee-consistency-payout.v1.yaml` — Trading Combine (No Activation Fee path, 100K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $4,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $149 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-100k-no-activation-fee-consistency-payout-daily-loss-limit.v1.yaml` — Trading Combine (No Activation Fee path, 100K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $2,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $4,000 per request and 50% of the balance (the promotion `dll_doubled_payout_cap` doubles it to $8,000 for a new purchase with the DLL at checkout on or after 2026-06-02); minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $149 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-150k.v1.yaml` — Trading Combine (Standard path, 150K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $5,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $199 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-150k-daily-loss-limit.v1.yaml` — Trading Combine (Standard path, 150K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $3,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $5,000 per request and 50% of the balance (the promotion `dll_doubled_payout_cap` doubles it to $10,000 for a new purchase with the DLL at checkout on or after 2026-06-02); minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $199 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-150k-consistency-payout.v1.yaml` — Trading Combine (Standard path, 150K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $6,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $199 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-150k-consistency-payout-daily-loss-limit.v1.yaml` — Trading Combine (Standard path, 150K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $3,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $6,000 per request and 50% of the balance (the promotion `dll_doubled_payout_cap` doubles it to $12,000 for a new purchase with the DLL at checkout on or after 2026-06-02); minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $199 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-150k-no-activation-fee.v1.yaml` — Trading Combine (No Activation Fee path, 150K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $5,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $229 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-150k-no-activation-fee-daily-loss-limit.v1.yaml` — Trading Combine (No Activation Fee path, 150K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $3,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $5,000 per request and 50% of the balance (the promotion `dll_doubled_payout_cap` doubles it to $10,000 for a new purchase with the DLL at checkout on or after 2026-06-02); minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $229 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-150k-no-activation-fee-consistency-payout.v1.yaml` — Trading Combine (No Activation Fee path, 150K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $6,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $229 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-trading-combine-150k-no-activation-fee-consistency-payout-daily-loss-limit.v1.yaml` — Trading Combine (No Activation Fee path, 150K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $3,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $6,000 per request and 50% of the balance (the promotion `dll_doubled_payout_cap` doubles it to $12,000 for a new purchase with the DLL at checkout on or after 2026-06-02); minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $229 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); funded account closed at the start of the 31st calendar day without a trade (the page says the account may be closed: assumption `xfa_inactivity_may_be_closed_on_day_31`).
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`; `xfa_inactivity_may_be_closed_on_day_31` on `xfa_inactivity`. The payout policy's `>= $0.01 since your last Payout` gate is quoted rather than assumed (`min_profit_since_last_usd: '0.01'`).
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-labs-daily-payouts-plus-50k.v1.yaml` — Labs Daily Payouts+ Trading Combine (50K, End-of-Day Trailing drawdown) -> Express Funded Account

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, NO lock (the drop states none); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); no minimum trading days; consistency 55% of the target; Daily Loss Limit $1,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago; lifespan 90 calendar days and inactivity 30 calendar days (executed trades only), both from the drop's own Challenge table and FAQ; the drop page also says 'XFA matches the standard $50K XFA scaling plan', which is why the scaling-plan entry applies to this account.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_daily: no day-count gate, counted since the last payout; cap $1,500 per request; minimum $250 (primary; $125 is sensitivity scenario labs_daily_payout_minimum#0); split 0.9 (`Profit Split 90/10`, the drop page's own table); buffer $2,000; min_profit_since_last_usd $0.01 (the drop's net-positive-since-last-Payout sentence); payout_group labs_xfa_payout_paths; payout_five_winning_days: 5 profitable days >= $150, counted since the last payout; cap $4,000 per request and 50% of the balance; minimum $125 (owner decision 2026-11-23); split 0.9; buffer $0; payout_group labs_xfa_payout_paths; every payout resets the day counts.
- **Fees / commissions:** $149 at_start; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); evaluation phase closed after 90 calendar days (a `time_limit`, the drop's own lifespan) and after 30 calendar days without an EXECUTED trade (an `inactivity` rule; an unfilled order does not count). The funded phase declares no inactivity: the drop's Phase 2 table publishes none, and the firm-wide XFA reading is not borrowed.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `labs_five_winning_days_minimum_from_firm_policy` on `payout_five_winning_days`, `assumption_kind: owner_decision` (the $125 general minimum, ruled on 2026-11-23). The 90/10 split is no longer an assumption: the drop page states it.
- **Conflicts:** `labs_daily_payout_minimum` on `payout_daily.min_usd`: selected '250' (https://help.topstep.com/en/articles/15520357-topstep-labs), alternative(s) '125' (https://help.topstep.com/en/articles/8284233-topstep-payout-policy).
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

### `topstep-labs-daily-payouts-plus-50k-static.v1.yaml` — Labs Daily Payouts+ Trading Combine (50K, Static drawdown) -> Express Funded Account

- **Account / thresholds:** starting balance $50,000; MLL $2,000 static; profit target $4,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); no minimum trading days; consistency 55% of the target; Daily Loss Limit $1,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago; lifespan 90 calendar days and inactivity 30 calendar days (executed trades only), both from the drop's own Challenge table and FAQ; the drop page also says 'XFA matches the standard $50K XFA scaling plan', which is why the scaling-plan entry applies to this account.
- **Payouts:** funded MLL **not modelled (critical)**: the static $2,000 floor plus its post-first-payout reset to $0 has no vocabulary, so no loss limit is declared; payout_daily: no day-count gate, counted since the last payout; cap $1,500 per request; minimum $250 (primary; $125 is sensitivity scenario labs_daily_payout_minimum#0); split 0.9 (`Profit Split 90/10`, the drop page's own table); buffer $2,000; min_profit_since_last_usd $0.01 (the drop's net-positive-since-last-Payout sentence); payout_group labs_xfa_payout_paths; payout_five_winning_days: 5 profitable days >= $150, counted since the last payout; cap $8,000 per request and 50% of the balance; minimum $125 (owner decision 2026-11-23); split 0.9; buffer $0; payout_group labs_xfa_payout_paths; every payout resets the day counts.
- **Fees / commissions:** $149 at_start; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); six `effect: condition` rules make automated execution `eligible_conditional` (section 6); evaluation phase closed after 90 calendar days (a `time_limit`, the drop's own lifespan) and after 30 calendar days without an EXECUTED trade (an `inactivity` rule; an unfilled order does not count). The funded phase declares no inactivity: the drop's Phase 2 table publishes none, and the firm-wide XFA reading is not borrowed.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `labs_five_winning_days_minimum_from_firm_policy` on `payout_five_winning_days`, `assumption_kind: owner_decision` (the $125 general minimum, ruled on 2026-11-23). The 90/10 split is no longer an assumption: the drop page states it.
- **Conflicts:** `labs_daily_payout_minimum` on `payout_daily.min_usd`: selected '250' (https://help.topstep.com/en/articles/15520357-topstep-labs), alternative(s) '125' (https://help.topstep.com/en/articles/8284233-topstep-payout-policy).
- **Not modeled (critical):** `static_xfa_drawdown_post_payout_reset`.
- **Not modeled (material, with what would change it):** `xfa_scaling_plan_ladder` (the funded phase's own contract limit is NOT declared — the ladder is image-only, saved with its sha256, and the Combine's maximum is never substituted), `news_full_position_size_prohibited` (discretionary), `sub_minute_holding_and_micro_scalping` (one-minute bars; the page's seconds are an example, not a threshold), `two_percent_price_limit_restriction` (`becomes_immaterial_if`: an audit of the instruments and dates shows it never affected a trade), `volatility_position_limit_tightening` (`becomes_immaterial_if`: shown not to affect the evaluated universe, dates and sizes).
- **Not modeled (immaterial, with what would make it bind):** `cross_account_hedging` (`becomes_immaterial_if`: becomes material if multiple accounts, copy trading or coordinated strategies are simulated).

## 14. Open questions for the owner

### Per-component costs (C7b fix, 2026-11-22)

`commissions.includes_exchange_and_regulatory_fees` is gone. The ruleset now declares, for each of the four components, whether the firm's per-side commission CONTAINS it (`included`), EXCLUDES it (`excluded`, so the run adds the dataset's amount for its participant type) or does not say (`unknown`, which is never a zero cost). All four keys are required, and no component may be inferred from another firm's page, another product or another participant type (ADR-0107 section 10 as amended).

| Component | Status in the files | Evidence kind | Evidence |
|---|---|---|---|
| `exchange` | `included` | `official_quote` | "NFA & Regulatory Fees $0.02 $0.02 Exchange Fee $2.76 $0.70 Commissions $1.00 $0.50 Total $3.78 $1.22" |
| `clearing` | `unknown` | `not_stated` | the breakdown itemizes NFA & regulatory fees, the exchange fee and the commission only; no clearing fee is named |
| `nfa` | `included` | `official_quote` | the same breakdown ("NFA & Regulatory Fees $0.02") |
| `other` | `unknown` | `not_stated` | the breakdown names three components and no other per-side charge |

An `excluded` component needs the run's participant PROFILE (`--participant-profile`): each fee row names the one classification dimension it needs (`cme_membership_status`, `nfa_assessment_eligibility`, ...), a dimension the profile leaves out makes that component a gap, and using the profile makes the cost `conditional`. An `unknown` component is a gap, and the only way to a number is a cost-assumption FILE the user passes, which prices exactly the root and component it names and is recorded by its SHA-256. The unverified owner reference in `docs/data/cme-exchange-fees.md` ("Estimated fee per side") is documentation only: the engine never reads it.

Owner questions, one per component the files declare `unknown`:

1. **clearing**: Does the per-side commission already contain the clearing fee, or is the clearing fee charged on top of it?
   **Owner decision (2026-11-23): stays `unknown`** - no inference and no generic value; the gap stands.
2. **other**: Is there any other per-side charge beside the commission, the exchange fee, the clearing fee and the NFA assessment?
   **Owner decision (2026-11-23): stays `unknown`** on the same terms.


1. **The doubled payout cap on the twelve `addons: [daily_loss_limit]` files.** Two pages agree that
   a Combine bought with a DLL at checkout has doubled per-request caps. **Owner decision (2026-11-23):**
   the doubling is a `promotion` (`dll_doubled_payout_cap`, x2 on `max_usd`) on the STANDARD cap, applied
   only to a new Trading Combine purchase with the DLL selected at checkout on or after 2026-06-02,
   with `ends_on: unknown` and never assumed past `as_of`; every other run keeps the standard cap. Applied
   to the 12 files.
2. **The XFA Scaling Plan ladder** has to be transcribed from the article's images by the owner before
   a funded phase can carry a contract limit. Until then the funded account is unconstrained in size.
   **Owner decision (2026-11-23, F11):** the ladder stays `not_modeled` **material**, quoted to the
   article's own statement that the plan is an XFA objective, and the texts no longer read as "no
   contract limit". The ladder images are saved (`20261123_hc_scaling-plan-xfa-charts.png`, sha256
   `55ec76b4…6cbd`); the coordinator transcribes them, not this packet.
3. **The FOMC press conference has no stated hour, so its trade date is a coverage gap.** The
   engine does not invent a window: on those days the news rules are `not_modeled`, the estimate is
   `partial` and the event ids are reported (see section 5). Supply the hour (the transcript PDF
   states it, and reading it is out of scope here) to make the window enforceable; alternatively
   say that a whole-day blackout should be carried as an owner-chosen sensitivity scenario. It is
   not simulated today and was never simulated as a whole-day block.
   **Owner decision (2026-11-23):** the 5-minute window applies wherever a reliable timestamp
   exists, and a missing time stays a reported coverage gap for its own trade date, never a
   whole-day block. Checked, no change: the files and `crucible/prop/news.py` already do exactly
   that (`time_known` required, unknown-time events gap their own date only).
4. **The micro cap inside the window** is declared for *new entries* only, like the block: the page
   speaks of "Opening transactions" and says existing positions may be managed through the window.
   Confirm a held micro position above the cap is not a breach.
5. **The Labs Daily Payout minimum is a recorded conflict** ($250 on the drop page, $125 on the
   firm-wide policy; scenario `labs_daily_payout_minimum#0` is the $125 reading). **Owner decision
   (2026-11-23):** confirmed - $250 primary, $125 sensitivity, both sources kept, nothing verified.
6. **The 5 Winning Days path on the Labs drops** carries the firm-wide $125 minimum as a named
   assumption, because the drop states no minimum for it. Confirm, or say that path pays no minimum.
   **Owner decision (2026-11-23, F10):** confirmed - $125 general minimum, `assumption_kind:
   owner_decision`; the Daily Payout path keeps $250 primary with $125 as sensitivity, and the two
   paths never share a minimum. The 90/10 split is re-sourced to the drop page's own table.
7. **"Avoid opening new positions after 3:08 PM CT. Risk Managers begin flattening then."** (Trading
   Combine parameters) is advisory and two minutes before the modeled 3:10 PM CT `flat_by`, so it is
   not declared. A separate 15:08 no-entry clock would be a rule the page only advises.
8. **Is the Reset fee ($49 / $99 / $199) and the Back2Funded reactivation fee ($599 / $699 / $829)
   part of attempt cost accounting?** They are not phase fees; a reset restarts the attempt, which is
   a C7b attempt policy question.
9. **The static Labs drawdown (F8): the conservative trailing substitution is withdrawn.**
   **Owner decision (2026-11-23):** the substitution is REMOVED - the static $2,000 floor plus its
   post-first-payout reset to $0 is `not_modeled` critical, and the funded phase declares no loss
   limit rather than an approximation.
10. **`unfair_technology` is `material`, not `critical`.** Topstep sells an API and does not ban
   automated trading, so no automated attempt is `blocked_by_compliance`. Confirm that reading (the
   contrast is Apex, whose automation ban the owner made critical). **Owner decision (2026-11-23,
   F21):** confirmed and sharpened - automated execution is `eligible_conditional` under six
   conditions quoted from the API Access article, never `blocked_by_compliance`.

## 15. Reproduction and self-check

```bash
# snapshots (private, outside the repository)
cd /d/proyectos/crucible-notes/internal/prop_snapshots
python fetch2.py topstep <short_name> <url>       # saves raw bytes + sha256 + retrieved_at
python dump_text.py topstep                       # text dumps for grepping
uv run python check_quotes2.py <repo>/rulesets/prop/topstep/*.yaml   # quotes + sha256
# the rulesets
for f in rulesets/prop/topstep/*.yaml; do uv run crucible prop validate "$f" --json ">/dev/null"; done
uv run crucible prop list --firm topstep --json
```

Generation: `topstep/migrate_v2.py` rewrote the drafts in schema 2 from the quoted values,
`topstep/round2.py` applied the round-2 declarations and `topstep/round4.py` the round-4 owner
decisions of 2026-11-23 (all abort if a quotation cannot be found in
the saved bytes); `topstep/write_research.py` composes this page from the emitted YAML, so the matrix
and the per-file checklist cannot drift from the files.

`rulesets/prop/INDEX.json` still lists these 26 files as `pending_migration`; it is regenerated by
`uv run python -m tools.docgen --write` at the merge, which is where the content hashes enter the
append-only lock.
