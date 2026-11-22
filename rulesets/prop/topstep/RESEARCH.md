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
  every file (last run: **759 attributions, 759 hashes matched, 0 quotes missing**).
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
| `20261122_hc_what-is-the-scaling-plan.html` | https://help.topstep.com/en/articles/8284223-what-is-the-scaling-plan | `90a50f76af9363f786e18104d8612998a62a1fba54f027d3da48cee13e50c2ce` | 2026-11-22T01:36:34Z |
| `20261122_hc_when-and-what-products-can-i-trade.html` | https://help.topstep.com/en/articles/8284206-when-and-what-products-can-i-trade | `9e4331b99755e8feceb5bbfde851c7d7f081fa7a5e09c50eec8f464aecb90b24` | 2026-11-22T01:36:35Z |
| `20261122_labs.html` | https://www.topstep.com/labs | `16651d0ab93044e1ba504088dddc5494ffc309432adef35a0b040fa1e8744960` | 2026-11-22T01:53:08Z |
| `20261122_live_funded_rules.html` | https://www.topstep.com/live-funded-account-rules | `e4e401323d6ffe45784eb6e7f23ca6568c9d30968649cea3bd7d8dcb3bfdaf7f` | 2026-11-22T01:35:39Z |
| `20261122_our_program.html` | https://www.topstep.com/our-program | `a59e010934573b2a6e5029fefdb7ee00c478bb39e975faa161de5be039843b8a` | 2026-11-22T01:35:38Z |
| `20261122_topstep_prop.html` | https://www.topstep.com/topstep-prop | `3821e4b3decdb7e79da48689b95e9d1b175bfaa10ffd4e0ea0f86cd915fb6d7e` | 2026-11-22T01:35:38Z |
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
| `topstep-labs-daily-payouts-plus-50k.v1.yaml` | $50,000 | yes | $3,000 | $2,000 eod, no lock | 5 | - | 0.55 pass | $2,000 lock@ 2000 -> 0 (hwm, first_payout) | daily+five_winning_days | 0d>=$0 buf $2,000 | 5d>=$150 buf $0 | $1,500 / $4,000 | 0.9 | $149 at_start |
| `topstep-labs-daily-payouts-plus-50k-static.v1.yaml` | $50,000 | yes | $4,000 | static $2,000 | 5 | - | 0.55 pass | $2,000 lock@ 2000 -> 0 (hwm, first_payout) | daily+five_winning_days | 0d>=$0 buf $2,000 | 5d>=$150 buf $0 | $1,500 / $8,000 | 0.9 | $149 at_start |
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
2. **The public `/express-funded-account-rules` page (last updated 2025-06-26)** still says "Request
   up to 50% of your account balance, up to $6,000" and "a max of $5,000 (Standard) or $6,000
   (Consistency XFA) per payout", flat across sizes, and adds "After the first payout, a Minimum
   Payout Balance must be met". That is a **different effective period** from the 2026 payout policy
   page ("Updated this week", the doubling offer added) and from the current product page, which both
   price the caps per size. Treated as an **inapplicable source**: dropped for the caps and the
   minimum-payout-balance rule, noted here, not modeled.
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
   `labs_daily_payout_minimum#0`. Both sources stay in the file.

## 8. Assumptions applied (ADR-0107 section 7 defaults)

Only the defaults the owner fixed, each recorded as `evidence: assumption` with its name:

| assumption name | rule(s) | files | rationale |
|---|---|---|---|
| `unspecified_target_frequency_is_eod` | `profit_target` | 26 (every file) | The pages state the target amount but never its observation frequency. A target is a pass condition, so the conservative default is the opposite of the failure-threshold one: the target is tested at the end of the trade date on the closed balance, because the trader passes no earlier than the end of the trade date and a later same-day breach still counts. Never intraday for a target the firm does not date. |
| `trading_day_is_a_trade_date_with_at_least_one_trade` | `minimum_trading_days` | 24 (the Trading Combine files; the Labs drop states no minimum) | The pages state a two-day minimum but never define a qualifying day. ADR-0107 section 7 default: a trading day is a trade date with at least one executed trade. |
| `static_xfa_drawdown_taken_as_the_trailing_firm_form` | funded `maximum_loss_limit` | 1 (the Static Labs drop) | The help article states the drop's XFA MLL as "$2,000 static", but the engine raises a threshold after a payout only on a trailing rule and the firm's own funded form for a 50K account is the trailing $2,000 MLL locking at $0. The trailing form is the conservative substitution: above a $2,000 balance the two agree (and the first daily payout cannot happen below it, given the $2,000 buffer), and between $0 and $2,000 the trailing floor is the higher, earlier-failing one. |
| `payout_split_taken_from_firm_payout_policy` | `payout_daily` | 2 (the Labs files) | The drop page states the buffer, the $250 minimum and the $1,500 cap but not the 90/10 split; the firm-wide Express Funded Account split is taken from `.../8284233-topstep-payout-policy`. |
| `labs_five_winning_days_minimum_from_firm_policy` | `payout_five_winning_days` | 2 (the Labs files) | The drop page states the five-day eligibility, the buffer (none) and the per-payout cap ($4,000 EOD / $8,000 Static) but no minimum for that path, so the firm-wide Express Funded Account minimum ($125) is used. |

No other default was needed. "CT" is quoted by the firm, so the time zone is `America/Chicago`
directly (an ADR default of `America/New_York` would have been wrong). Every **failure** threshold's
observation frequency is stated and stays `intraday` (MLL "monitored in real time throughout the
session", DLL "during the trading day (5 PM CT - 3:10 PM CT)"), and the only unstated frequency is
the profit target's, which is why it carries the `unspecified_target_frequency_is_eod` assumption.
The payout day is stated ("A day locks in at 4:00 PM CT"), so the payout rules carry no default.

## 9. What is not modeled, by materiality

Six entries in the 24 Trading Combine files, six in the trailing Labs drop, seven in the static one
(three material everywhere; the static drop adds its drawdown substitution).

**Material** (the evaluation status is `conditional_on_modeled_rules` because of these):

| rule | why |
|---|---|
| `xfa_scaling_plan_ladder` | The funded account's contract limit follows a balance -> contracts ladder published **only as PNG images**; no contract number can be quoted, so the funded phase declares no contract limit and overstates the size a real XFA may hold. |
| `news_full_position_size_prohibited` | Discretionary news rule, no threshold. |
| `sub_minute_holding_and_micro_scalping` | Owner ruling: sub-minute holding and micro-scalping stay unmodeled on one-minute bars. |
| `static_xfa_drawdown_taken_as_trailing` | Static Labs drop only: "$2,000 static" is modeled as the firm's trailing funded form, because a post-payout threshold on a static rule needs engine support; see the assumption above. |

**Immaterial** (declared and warned, and they do not weaken the status):

| rule | why |
|---|---|
| `volatility_position_limit_tightening` | Discretionary, and the published reductions cover energies, metals and Micro Bitcoin, not this instrument set. |
| `cross_account_hedging` | A single simulated account cannot hedge itself (owner ruling: stays unmodeled). |
| `two_percent_price_limit_restriction` | A hard prohibition, but the engine has no CME price-limit band and the index products' bands sit far outside any one-minute bar the simulation sees (owner ruling: stays unmodeled). |

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
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-50k-daily-loss-limit.v1.yaml` — Trading Combine (Standard path, 50K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $1,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $4,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $49 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-50k-consistency-payout.v1.yaml` — Trading Combine (Standard path, 50K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $3,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $49 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-50k-consistency-payout-daily-loss-limit.v1.yaml` — Trading Combine (Standard path, 50K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $1,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $6,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $49 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-50k-no-activation-fee.v1.yaml` — Trading Combine (No Activation Fee path, 50K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $2,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $95 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-50k-no-activation-fee-daily-loss-limit.v1.yaml` — Trading Combine (No Activation Fee path, 50K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $1,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $4,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $95 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-50k-no-activation-fee-consistency-payout.v1.yaml` — Trading Combine (No Activation Fee path, 50K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $3,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $95 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-50k-no-activation-fee-consistency-payout-daily-loss-limit.v1.yaml` — Trading Combine (No Activation Fee path, 50K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, locking at $50,000 when the balance reaches $52,000 (lock.on ['hwm']); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $1,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $6,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $95 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-100k.v1.yaml` — Trading Combine (Standard path, 100K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $3,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $99 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-100k-daily-loss-limit.v1.yaml` — Trading Combine (Standard path, 100K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $2,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $6,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $99 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-100k-consistency-payout.v1.yaml` — Trading Combine (Standard path, 100K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $4,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $99 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-100k-consistency-payout-daily-loss-limit.v1.yaml` — Trading Combine (Standard path, 100K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $2,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $8,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $99 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-100k-no-activation-fee.v1.yaml` — Trading Combine (No Activation Fee path, 100K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $3,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $149 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-100k-no-activation-fee-daily-loss-limit.v1.yaml` — Trading Combine (No Activation Fee path, 100K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $2,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $6,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $149 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-100k-no-activation-fee-consistency-payout.v1.yaml` — Trading Combine (No Activation Fee path, 100K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $4,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $149 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-100k-no-activation-fee-consistency-payout-daily-loss-limit.v1.yaml` — Trading Combine (No Activation Fee path, 100K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $100,000; MLL $3,000 trailing on the end-of-day balance, locking at $100,000 when the balance reaches $103,000 (lock.on ['hwm']); profit target $6,000 on the closed balance; 10 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $2,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $3,000 trailing, locking at $0 when the balance reaches $3,000 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $8,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $149 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.6-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-150k.v1.yaml` — Trading Combine (Standard path, 150K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $5,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $199 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-150k-daily-loss-limit.v1.yaml` — Trading Combine (Standard path, 150K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $3,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $10,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $199 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-150k-consistency-payout.v1.yaml` — Trading Combine (Standard path, 150K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $6,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $199 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-150k-consistency-payout-daily-loss-limit.v1.yaml` — Trading Combine (Standard path, 150K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $3,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $12,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $199 per_month; $149 at_pass; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-150k-no-activation-fee.v1.yaml` — Trading Combine (No Activation Fee path, 150K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $5,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $229 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-150k-no-activation-fee-daily-loss-limit.v1.yaml` — Trading Combine (No Activation Fee path, 150K) -> Express Funded Account (Standard payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $3,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_standard: 5 profitable days >= $150, counted since the last payout; cap $10,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; every payout resets the day counts.
- **Fees / commissions:** $229 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-150k-no-activation-fee-consistency-payout.v1.yaml` — Trading Combine (No Activation Fee path, 150K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; no Daily Loss Limit; flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $6,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $229 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-trading-combine-150k-no-activation-fee-consistency-payout-daily-loss-limit.v1.yaml` — Trading Combine (No Activation Fee path, 150K) -> Express Funded Account (Consistency payout path)

- **Account / thresholds:** starting balance $150,000; MLL $4,500 trailing on the end-of-day balance, locking at $150,000 when the balance reaches $154,500 (lock.on ['hwm']); profit target $9,000 on the closed balance; 15 contracts (mini weight 1, micro 0.1); minimum 2 trading days; consistency 55% of the target; Daily Loss Limit $3,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $4,500 trailing, locking at $0 when the balance reaches $4,500 (lock.on ['hwm', 'first_payout']); payout_consistency: 3 traded days, counted since the last payout; cap $12,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; consistency 40% on the payout, since the last payout; every payout resets the day counts.
- **Fees / commissions:** $229 per_month; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.9-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `trading_day_is_a_trade_date_with_at_least_one_trade` on `minimum_trading_days`.
- **Conflicts:** none recorded (`conflicts: []`).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-labs-daily-payouts-plus-50k.v1.yaml` — Labs Daily Payouts+ Trading Combine (50K, End-of-Day Trailing drawdown) -> Express Funded Account

- **Account / thresholds:** starting balance $50,000; MLL $2,000 trailing on the end-of-day balance, NO lock (the drop states none); profit target $3,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); no minimum trading days; consistency 55% of the target; Daily Loss Limit $1,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_daily: no day-count gate, counted since the last payout; cap $1,500 per request; minimum $250; split 0.9; buffer $2,000; payout_group labs_xfa_payout_paths; payout_five_winning_days: 5 profitable days >= $150, counted since the last payout; cap $4,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; payout_group labs_xfa_payout_paths; every payout resets the day counts.
- **Fees / commissions:** $149 at_start; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `payout_split_taken_from_firm_payout_policy` on `payout_daily`; `labs_five_winning_days_minimum_from_firm_policy` on `payout_five_winning_days`.
- **Conflicts:** `labs_daily_payout_minimum` on `payout_daily.min_usd`: selected '250' (https://help.topstep.com/en/articles/15520357-topstep-labs), alternative(s) '125' (https://help.topstep.com/en/articles/8284233-topstep-payout-policy).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

### `topstep-labs-daily-payouts-plus-50k-static.v1.yaml` — Labs Daily Payouts+ Trading Combine (50K, Static drawdown) -> Express Funded Account

- **Account / thresholds:** starting balance $50,000; MLL $2,000 static; profit target $4,000 on the closed balance; 5 contracts (mini weight 1, micro 0.1); no minimum trading days; consistency 55% of the target; Daily Loss Limit $1,000 soft (both phases); flat by 15:10 CT, reopen 17:00 CT; rule day rolls at 17:00 America/Chicago.
- **Payouts:** funded MLL $2,000 trailing, locking at $0 when the balance reaches $2,000 (lock.on ['hwm', 'first_payout']); payout_daily: no day-count gate, counted since the last payout; cap $1,500 per request; minimum $250; split 0.9; buffer $2,000; payout_group labs_xfa_payout_paths; payout_five_winning_days: 5 profitable days >= $150, counted since the last payout; cap $8,000 per request and 50% of the balance; minimum $125; split 0.9; buffer $0; payout_group labs_xfa_payout_paths; every payout resets the day counts.
- **Fees / commissions:** $149 at_start; commissions per side ES 1.89, NQ 1.89, YM 1.89, RTY 1.89, NKD 2.66, MES 0.61, MNQ 0.61, MYM 0.61, M2K 0.61 (TopstepX round-turn total / 2).
- **News / compliance:** Tier 1 window 5 min before/after CPI, the FOMC statement, the FOMC press conference, NFP and PPI: no new entry in the minis (ES, NQ, RTY, YM, NKD, effect block) and a 0.3-weight cap on the micros (MES, MNQ, MYM, M2K, effect contract_cap); new entries only, nothing flattened; compliance: unfair_technology (automated, material, action none), sim_fill_exploitation (automated, material, action none), trade_outside_best_bid_offer (automated/manual, material, action none), coordinated_and_copy_trading (automated/manual, material, action none), account_stacking (automated/manual, material, action none); funded account closed after 30 calendar days without a trade.
- **Assumptions:** `unspecified_target_frequency_is_eod` on `profit_target`; `static_xfa_drawdown_taken_as_the_trailing_firm_form` on `maximum_loss_limit`; `payout_split_taken_from_firm_payout_policy` on `payout_daily`; `labs_five_winning_days_minimum_from_firm_policy` on `payout_five_winning_days`.
- **Conflicts:** `labs_daily_payout_minimum` on `payout_daily.min_usd`: selected '250' (https://help.topstep.com/en/articles/15520357-topstep-labs), alternative(s) '125' (https://help.topstep.com/en/articles/8284233-topstep-payout-policy).
- **Not modeled (material):** `xfa_scaling_plan_ladder`, `news_full_position_size_prohibited`, `sub_minute_holding_and_micro_scalping`, `static_xfa_drawdown_taken_as_trailing`.
- **Not modeled (immaterial):** `cross_account_hedging`, `two_percent_price_limit_restriction`, `volatility_position_limit_tightening`.

## 14. Open questions for the owner

### Per-component costs (C7b fix, 2026-11-22)

`commissions.includes_exchange_and_regulatory_fees` is gone. The ruleset now declares, for each of the four components, whether the firm's per-side commission CONTAINS it (`included`), EXCLUDES it (`excluded`, so the run adds the dataset's amount for its participant type) or does not say (`unknown`, which is never a zero cost). All four keys are required, and no component may be inferred from another firm's page, another product or another participant type (ADR-0107 section 10 as amended).

| Component | Status in the files | Evidence kind | Evidence |
|---|---|---|---|
| `exchange` | `included` | `official_quote` | "NFA & Regulatory Fees $0.02 $0.02 Exchange Fee $2.76 $0.70 Commissions $1.00 $0.50 Total $3.78 $1.22" |
| `clearing` | `unknown` | `not_stated` | the breakdown itemizes NFA & regulatory fees, the exchange fee and the commission only; no clearing fee is named |
| `nfa` | `included` | `official_quote` | the same breakdown ("NFA & Regulatory Fees $0.02") |
| `other` | `unknown` | `not_stated` | the breakdown names three components and no other per-side charge |

An `excluded` component needs a participant type at RUN time (`--fee-participant-type`): the ruleset never states one, and using it makes the cost `conditional`. An `unknown` component is a gap, and the only way to a number is a cost-assumption FILE the user passes, which prices exactly the root and component it names and is recorded by its SHA-256. The unverified owner reference in `docs/data/cme-exchange-fees.md` ("Estimated fee per side") is documentation only: the engine never reads it.

Owner questions, one per component the files declare `unknown`:

1. **clearing**: Does the per-side commission already contain the clearing fee, or is the clearing fee charged on top of it?
2. **other**: Is there any other per-side charge beside the commission, the exchange fee, the clearing fee and the NFA assessment?


1. **The doubled payout cap on the twelve `addons: [daily_loss_limit]` files.** Two pages agree that
   a Combine bought with a DLL at checkout has doubled per-request caps, so those files use $4,000 / $6,000 /
   $6,000 / $8,000 / $10,000 / $12,000 where the v1 draft used the base cap. The offer is described
   as a limited-time offering ("beginning at 3:30 PM CT on Tuesday, June 2nd") whose end date is
   unpublished, while both pages still show it as live at retrieval. Confirm it is in force for a
   Combine bought now; if not, every DLL file drops back to its base cap.
2. **The XFA Scaling Plan ladder** has to be transcribed from the article's images by the owner before
   a funded phase can carry a contract limit. Until then the funded account is unconstrained in size.
3. **The FOMC press conference has no stated hour, so its trade date is a coverage gap.** The
   engine does not invent a window: on those days the news rules are `not_modeled`, the estimate is
   `partial` and the event ids are reported (see section 5). Supply the hour (the transcript PDF
   states it, and reading it is out of scope here) to make the window enforceable; alternatively
   say that a whole-day blackout should be carried as an owner-chosen sensitivity scenario. It is
   not simulated today and was never simulated as a whole-day block.
4. **The micro cap inside the window** is declared for *new entries* only, like the block: the page
   speaks of "Opening transactions" and says existing positions may be managed through the window.
   Confirm a held micro position above the cap is not a breach.
5. **The Labs Daily Payout minimum is a recorded conflict** ($250 on the drop page, $125 on the
   firm-wide policy; scenario `labs_daily_payout_minimum#0` is the $125 reading). Confirm the
   conservative selection.
6. **The 5 Winning Days path on the Labs drops** carries the firm-wide $125 minimum as a named
   assumption, because the drop states no minimum for it. Confirm, or say that path pays no minimum.
7. **"Avoid opening new positions after 3:08 PM CT. Risk Managers begin flattening then."** (Trading
   Combine parameters) is advisory and two minutes before the modeled 3:10 PM CT `flat_by`, so it is
   not declared. A separate 15:08 no-entry clock would be a rule the page only advises.
8. **Is the Reset fee ($49 / $99 / $199) and the Back2Funded reactivation fee ($599 / $699 / $829)
   part of attempt cost accounting?** They are not phase fees; a reset restarts the attempt, which is
   a C7b attempt policy question.
9. **`unfair_technology` is `material`, not `critical`.** Topstep sells an API and does not ban
   automated trading, so no automated attempt is `blocked_by_compliance`. Confirm that reading (the
   contrast is Apex, whose automation ban the owner made critical).

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

Generation: `topstep/migrate_v2.py` rewrote the drafts in schema 2 from the quoted values and
`topstep/round2.py` applied the round-2 declarations (both abort if a quotation cannot be found in
the saved bytes); `topstep/write_research.py` composes this page from the emitted YAML, so the matrix
and the per-file checklist cannot drift from the files.

`rulesets/prop/INDEX.json` still lists these 26 files as `pending_migration`; it is regenerated by
`uv run python -m tools.docgen --write` at the merge, which is where the content hashes enter the
append-only lock.
