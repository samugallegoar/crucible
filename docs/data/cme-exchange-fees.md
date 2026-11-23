# Execution fees: per component, per side, per contract (owner-sourced; exchange and clearing pending)

Dataset `exchange_fees_v1`. The per-side, per-contract USD amounts a retail customer of a prop
firm's clearing chain pays **on top of a commission that excludes them**, split into the components
a firm's commission may or may not contain:

| `fee_type` | Component | Who states it |
|---|---|---|
| `exchange` | the exchange's own trading fee | only an owner file: CME Group publishes product buckets, not root tickers |
| `clearing` | the clearing fee | only an owner file |
| `nfa` | the NFA assessment fee | the official bylaw page, fetched and parsed |
| `other` | any other NAMED per-side charge the source states | only an owner file, with the charge's own evidence |

Built by `crucible/data/exchange_fees.py`. This page records one uncomfortable fact first: the
dataset holds **the NFA fee only**. No exchange, clearing or other row is stored, because CME Group
refuses automated access and its published schedule does not name a root ticker, so a per-root rate
cannot be read off it without guessing. `fee_rows_as_of` therefore prices **only the root and the
components it has rows for** and returns nothing for the rest — an unpriced component is a gap the
caller reports, never a zero. The decision, and the alternatives considered, are recorded in
`docs/adr/0107-firm-rulesets-and-attempt-statistics.md` (section 10 and its amendment); nothing here
was fetched from `cmegroup.com` or copied from an archive of it.

**No universal fee, and no extrapolation.** A row prices exactly its `root` and date range, for the
CLASSIFICATION it declares. It states which components its amount covers (`covers`). There is no
product-bucket to root mapping anywhere in this repository, and no fee is carried across roots,
products or classifications: the engine never invents one.

## Classification: a dimension and a value per row, resolved against the run's profile

A row does not carry a participant type. It carries **the one classification dimension it needs**
(`classification_dimension`) and the value it is written for (`classification_value`):

| Row | `classification_dimension` | `classification_value` | Why that dimension |
|---|---|---|---|
| `exchange` | `cme_membership_status` | `non_member` | CME's schedule prints a Non-Members column; the owner file says which column it read |
| `clearing` | `cme_membership_status` | `non_member` | the same schedule, the same column |
| `nfa` | `nfa_assessment_eligibility` | `fcm_member` | Bylaw 1301(b)(i)(A) assesses the **FCM member** per contract; a customer sees it passed through |
| `other` | `none` / `all`, or a dimension the source states | `all`, or the stated value | a charge the source says is the same for everyone needs no profile entry |

Dimension names are not an enum: each row brings its own, and every name must match
`^[a-z][a-z0-9_]*$`. A run declares a **participant profile** — a flat mapping from dimension to
value, e.g. `cme_membership_status: non_member` and `nfa_assessment_eligibility: fcm_member` — and
`fee_rows_as_of` resolves **each component** through it:

1. take the rows that cover the component, for the exact root, with the date inside their
   effective range;
2. for each, look its dimension up in the profile:
   - missing, or the value `unknown` → the component is a **gap** whose reason is
     `classification <dim> not declared`;
   - a different value → the row does not apply;
   - the same value, or `none`/`all` → the row applies;
3. exactly one applicable row prices the component; **two are refused as ambiguous**; none is a gap.

There is **never a default classification**, and never a fallback to "the only row there is". The
`nfa` component therefore needs `nfa_assessment_eligibility` in the profile: the former
"an NFA row prices any participant type" pass-through is gone, because it was a classification the
run never declared.

**`other` is the one exception, and it sums.** Two `` other `` rows with **different**
`charge_name`s covering one date are two distinct charges, each with its own evidence, and both are
charged: the `other` component is their sum. Two `other` rows with the **same** `charge_name`, root
and classification that overlap in dates are refused — that is one charge written twice.

## Sources

### NFA assessment fee — official, fetched

| Source | What it states |
|---|---|
| `nfa.futures.org/rulebooksql/rules.aspx?Section=3&SubSection=13` (NFA Manual, Chapter 13, **Bylaw 1301**) | the assessment fee per commodity futures contract, the period it applies to, and the higher amount that applies after that period |

Raw bytes, never modified and never re-fetched: `nfa/20261122_nfa-bylaw-1301.html`, 260,160
bytes, SHA-256 `f03b3678ba6e0d66…`, retrieved **2026-11-22T06:33:22Z**, under
`D:/proyectos/databases/exchange_fees/raw/` with `MANIFEST.json` (url, retrieval instant, sha256,
bytes). `load_snapshots` refuses a byte whose SHA-256 no longer matches the manifest.

The row's evidence is the bylaw's own sentence, quoted verbatim in `quote`:

> (A) $.02 for each commodity futures contract traded on or entered into subject to the rules of a
> contract market (other than an option contract) on a round-turn basis during the period of
> July 1, 2026, through June 30, 2027, after which time the assessment will be equal to $.04 for
> each commodity futures contract traded on or entered into subject to the rules of a contract
> market (other than an option contract) on a round-turn basis;

Three things the row states, and nothing inferred:

- **Per side = half the round-turn amount.** The bylaw assesses a *round turn* ($.02), so a side is
  $0.01 through 2027-06-30 and $0.02 from 2027-07-01. Both rows are written: the sentence states the
  second amount and its start.
- **`covers = nfa`.** The assessment is the regulatory component and nothing else.
- **`classification_dimension = nfa_assessment_eligibility`, `classification_value =
  fcm_member`.** The bylaw assesses the *FCM member* per contract; a customer sees it passed
  through. The dimension and the value are the bylaw's own subject, so the row states them and the
  run's profile has to declare them: a profile without `nfa_assessment_eligibility` leaves the
  `nfa` component a gap (`classification nfa_assessment_eligibility not declared`), never a priced
  pass-through and never a fallback.

### CME Group exchange and clearing fees — **not sourced, on purpose**

Two independent blockers, both of which the owner file below removes:

1. **`cmegroup.com` refuses automated access from the machine this was built on.** Every text URL
   — including `/robots.txt` — answers HTTP 403 with:

   > This IP address is blocked due to suspected web scraping activity associated with it on this
   > CMEgroup.com page. Use of scripts, software, spiders, robots, avatars, agents, tools or other
   > scraping mechanisms is strictly prohibited by CME Group's website Data Terms of Use.

   The project does not work around a publisher's refusal: no archived copy of a CME Group file is
   fetched, kept or read as a substitute, and nothing from one is stored in this dataset or its
   raw folder. (The raw folder holds exactly one file: the NFA page.) **Automated retrieval stays
   refused.**
2. **Even with the document in hand, the fee is not attributable to a root.** CME's schedule names
   product *buckets* — "Equity Index", "Nikkei/TOPIX", "E-mini Equity Index", "Micro E-mini
   Index", "E-nano Index" — never a ticker such as `ES`, `MES` or `NKD`, and the column geometry
   of the published layout does not tie a bucket to a single column unambiguously (buckets span
   one to three columns under merged headers, and the fee-class label column does not align with
   the value rows). Which column is ES and which is MES would be an inference, and inferring a
   money amount is the one thing this dataset may not do (AGENTS.md §1.2, §1.5).

The two pages the **owner** downloads, by hand, in a browser:

- current fees: <https://www.cmegroup.com/company/clearing-fees.html>
- historical fees: <https://www.cmegroup.com/company/clearing-fees/historical-fees.html>

**The historical page is required for pre-2025 data.** Market data stays strictly before
2025-01-01 (ADR-0105), so a backtest of a 2023 or 2024 attempt needs the fee that was in force
*then*, and the current schedule states today's rate. A row carries its own `effective_from` and
`effective_to`, and a date picks its own row: the historical rows are data, not a single current
rate.

The observable consequence is deliberate and tested
(`test_build_writes_the_contract_and_prices_no_exchange_component`): `build_exchange_fees` writes
**zero** `exchange`, `clearing` or `other` rows, `BuildReport.unpriced_components` names all three,
and `fee_rows_as_of` returns no amount for them.

### Owner-provided fee file - how the CME rows get in

A person who holds the exchange fee schedule supplies a CSV; the loader records who supplied it,
the file's own SHA-256, and the exact cell text as the row's evidence. That is the only route an
exchange or clearing fee has into this dataset. Header (order is free, extra columns are refused):

```csv
root,fee_type,classification_dimension,classification_value,covers,per_side_usd,unit,effective_from,source_url,quote,venue,effective_to,charge_name,applies_quote,distinct_from
ES,exchange,cme_membership_status,non_member,exchange;clearing,0.00,per_contract_per_side,2026-01-01,https://www.cmegroup.com/company/clearing-fees/historical-fees.html,"SYNTHETIC EXAMPLE: the exact cell text for ES, e.g. the product row and the Non-Members column",CME,,,,
NQ,nfa,nfa_assessment_eligibility,fcm_member,nfa,0.00,per_contract_per_side,2026-01-01,https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=3&SubSection=13,"SYNTHETIC EXAMPLE: the bylaw sentence",CME,,,,
MES,other,none,all,other,0.00,per_contract_per_side,2026-01-01,https://www.cmegroup.com/company/clearing-fees.html,"SYNTHETIC EXAMPLE: the line naming the charge and its amount",CME,,SYNTHETIC EXAMPLE: the charge's own name,SYNTHETIC EXAMPLE: the text showing it applies per contract per side to this product,SYNTHETIC EXAMPLE: what it is if it is not the exchange, clearing or NFA fee
```

Every value above is an **obviously synthetic placeholder**: `0.00` and the words
`SYNTHETIC EXAMPLE` mark a cell a person must fill from the document they downloaded. No real CME
rate appears anywhere in this repository (a test enforces it).

| Column | Meaning |
|---|---|
| `root` | one of ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K |
| `fee_type` | `exchange`, `clearing`, `nfa` or `other`: the component the amount is typed as. **It must appear in `covers`** |
| `classification_dimension` | **mandatory**: the one participant-profile dimension this row needs (`cme_membership_status`, `nfa_assessment_eligibility`, ...), matching `^[a-z][a-z0-9_]*$`; `none` for a charge that is the same for every participant |
| `classification_value` | **mandatory**: the value that dimension must have (`non_member`, `fcm_member`, ...); `all` with dimension `none` |
| `covers` | **mandatory**: the components the amount covers, `;`-separated. A CME "Exchange Fees for Clearing & Trading" cell is `fee_type=exchange`, `covers=exchange;clearing`, and it is charged ONCE for both. An `other` row's `covers` is exactly `other` |
| `unit` | **mandatory on every row type**: exactly `per_contract_per_side`. This table is a per-side execution cost, so a monthly, platform, subscription or account charge is refused |
| `per_side_usd` | USD per contract per side, a decimal string (parsed as `Decimal`, never a float) |
| `effective_from` | `YYYY-MM-DD`, the first date the rate applies |
| `effective_to` | optional, `YYYY-MM-DD`, the last date; empty = open-ended |
| `venue` | optional; defaults from `VENUE_OF[root]` and must agree with it (ES/NQ/RTY/NKD/MES/MNQ/M2K = CME, YM/MYM = CBOT) |
| `source_url` | **mandatory**: the document the cell came from - one of the two CME pages above, or the NFA bylaw page. An `other` row's host must be `www.cmegroup.com` |
| `quote` | **mandatory**: the exact text the rate was read from (the cell, the row, the sentence) |
| `charge_name` | **required on an `other` row**: the charge's specific name or identifier |
| `applies_quote` | **required on an `other` row**: the exact text showing the charge applies to this execution (product and participant) |
| `distinct_from` | **required on an `other` row**: the text stating why the charge is not part of the exchange, clearing or NFA fee |

### What an `other` row must prove

A row typed `other` may not be a catch-all. It is refused, with a message that says what to fix,
when any of the following is missing or empty:

- `charge_name` - a specific name. Generic names are refused case-insensitively after punctuation
  is stripped: `other`, `others`, `misc`, `miscellaneous`, `fees`, `other fees`, `cme other fees`,
  `additional fees`, `charges`, and any name made only of those words plus `cme`, `exchange` or
  `fee`/`fees` (so `Other`, `misc.`, `CME other fees` and `exchange fees` are all refused);
- `unit` - must be exactly `per_contract_per_side`; monthly, platform, subscription and account
  charges are refused, and the message says a fixed charge belongs in the ruleset's fee schedule,
  separate from execution costs;
- `source_url` - an official source, on `www.cmegroup.com` for a CME Group root;
- `quote`, `applies_quote`, `distinct_from`, `root`, `effective_from`,
  `classification_dimension` and `classification_value`. The classification is required unless the
  source states the charge is the same for every participant; then it is
  `classification_dimension=none`, `classification_value=all`, which needs no profile entry.

Further rules for `other`:

- `covers` must be exactly `other` for an `other` row;
- a row whose `fee_type` is `exchange`, `clearing` or `nfa` may **not** list `other` in `covers`
  (the message is *an exchange fee cannot cover other components*) - an `exchange` row may still
  cover `exchange;clearing` when the owner's source names both;
- two `other` rows with the same `charge_name`, root and classification that overlap in dates are
  refused (one charge written twice);
- two `other` rows with **different** names covering the same date are both charged: they are
  distinct charges, each with its own evidence, and the `other` component is their sum.

Refusals common to every row type, each with a message that says what to fix:

- an empty `quote` (a rate nobody can point at), a missing `source_url`, a missing supplier, an
  unknown or misspelled column, a root outside `ROOTS`, a `venue` that disagrees with `VENUE_OF`,
  a non-numeric or negative amount, `effective_to` before `effective_from`;
- a `unit` that is not `per_contract_per_side`;
- **a `covers` list that does not contain the row's own `fee_type`** (a row prices the component it
  is typed as), an empty `covers`, or a `covers` name that is not a component;
- a `classification_dimension` that is not an identifier, an empty `classification_value`, `none`
  without `all`, or `all` with a real dimension;
- **two rows that start on the same date for one `(root, classification_dimension,
  classification_value, component)`**, and
- **overlapping rows for the same key** - a component covered twice on one date by rows of the same
  classification, including one row that covers `exchange;clearing` and another that covers
  `clearing` alone. A date must map to one amount per component, never to a row order. (The one
  exception is `other`, which sums distinct names; the same name twice is the refusal above.)

## Schema

`crucible/data/exchange_fees.py::EXCHANGE_FEE_SCHEMA`, stored sort order `root`,
`classification_dimension`, `classification_value`, `fee_type`, `effective_from`, `covers` (columns
in `docs/SCHEMAS.md` section 1.7).

## Lookup

```python
profile = ParticipantProfile.from_mapping({
    "cme_membership_status": "non_member",
    "nfa_assessment_eligibility": "fcm_member",
})
found = fee_rows_as_of(store, "ES", dt.date(2026, 8, 3),
                       profile=profile,
                       components=("exchange", "clearing", "nfa", "other"))
# -> FeeLookup(priced={"nfa": (Decimal("0.01"), "<record sha256>")},
#              gaps={"exchange": "no fee row covers ES exchange on 2026-08-03",
#                    "clearing": "no fee row covers ES clearing on 2026-08-03",
#                    "other": "no fee row covers ES other on 2026-08-03"})
```

- **Only the root asked for is priced.** An owner file that prices ES alone is usable; the nine
  roots are no longer demanded at once.
- Every requested component comes back in **exactly one** of `priced` and `gaps`: an unpriced
  component is a gap with its reason, never a zero.
- A row that covers several components is charged once (the attempt's pricing groups the components
  by the row's record hash, and the first component in report order carries the amount while the
  others say they are inside it).
- The classification is resolved per component against the profile: an undeclared (or `unknown`)
  dimension is `classification <dim> not declared`; a different value is `no fee row for <root>
  <component> on <date> matches the declared classification (...)`; and `none`/`all` rows apply to
  every participant.
- Two rows that both apply to one component on one date raise, by name: no amount is chosen from a
  contradiction. (`other` is the exception: distinct named charges sum.)
- A root outside `ROOTS` raises. The engine never maps a CME product bucket to a root.

## Assumptions

- **The participant profile.** CME's schedule does not say which class a prop firm's customer
  accounts fall into, and a ruleset never states one either, so the run declares a profile
  (`--participant-profile FILE`, MCP `participant_profile`) and the estimate becomes `conditional`
  with the reason `participant profile declared by the run, not stated by the firm`. The profile is
  recorded by its canonical SHA-256 in the manifest, the summary and every `attempts.parquet` row,
  and it is part of the evaluation id, so two profiles are two artifacts. `non_member` is the value
  the exchange rows of an owner file normally carry - **confirm it against the firm's clearing
  agreement** before a fee-driven result is relied on; an owner file that states another value wins,
  because it says so in `classification_value`.
- **Per side.** Every component is stored per side (`per_side_usd`): a round trip is
  `2 x per_side_usd`. The NFA figure is halved from the bylaw's round-turn amount for exactly this
  reason.
- **`available_at = event_time = 00:00 UTC of effective_from`.** Neither source states when its
  rate became public (NFA names the last amendment date of the bylaw, not of the rate), so the row
  records the weaker, provable claim: the rate is visible only from the day it applies. A
  point-in-time read can therefore never see a future rate.

## Coverage (rows in this build)

| Component | Roots | effective_from | effective_to | per side |
|---|---|---|---|---|
| `nfa` | all nine | 2026-07-01 | 2027-06-30 | $0.01 |
| `nfa` | all nine | 2027-07-01 | — (open) | $0.02 |
| `exchange` | — | — | — | **none stored** |
| `clearing` | — | — | — | **none stored** |
| `other` | — | — | — | **none stored** |

This build: 18 rows (2 per root), 1 snapshot,
`rows_by_type = {exchange: 0, clearing: 0, nfa: 18, other: 0}`,
`rows_by_source = {official_page: 18, owner_provided: 0}`,
`unpriced_components = (exchange, clearing, other)`.

## Unverified owner references

The owner's own working figure, recorded here **as documentation only**. It is not a fee, it is not
in the dataset, and the engine never reads it: no ruleset, module or fixture carries it, and it
enters a run only through a cost-assumption FILE the user passes explicitly (see
`docs/modules/prop.md`, `CostAssumption`).

| Field | Value |
|---|---|
| Estimated fee per side | **$1.38** |
| Source | the owner, **2026-11-22** |
| Composition (exchange / clearing / NFA / other) | **unknown**: the owner's note does not split it |
| Product | **unknown**: no root is named |
| Participant type | **unknown**: no rate class is named |
| Status | unverified owner reference, not a dataset row |

Because three of those fields are unknown, the figure cannot be stored as a row: a row must state
its root, its participant type and the components it covers, and inventing any of the three is
exactly what this dataset refuses to do. A user who wants an attempt to price with it writes a
cost-assumption file naming the root and the components, and the attempt records that file's
SHA-256 and reports the estimate as `conditional`.

## Gaps

- **Every exchange, clearing and other fee is missing** (all nine roots, all dates). The consequence
  is a gap on each such component, never a zero: a ruleset that says those components are charged on
  top stays `unavailable` until an owner file (or a cost-assumption file) prices them.
- **Dates before 2026-07-01 have no NFA row.** The bylaw page states the current rate and the
  amendment dates of Bylaw 1301, but not the rate each amendment set; reconstructing earlier rates
  would be a guess. A 2025-08 attempt therefore has an `nfa` gap as well.
- **The NFA row says nothing about options.** The bylaw's option clause (`(B)`, per trade) is a
  different instrument; this dataset covers futures only.
- **No commission, no market-data fee.** Only the components above; a commission that already
  includes them must not also add these, which is exactly what `commissions.components` declares.

## Rebuild

```bash
# 1. fetch the NFA page (idempotent: an existing file is never re-fetched or rewritten)
uv run python -c "from pathlib import Path; from crucible.data.exchange_fees import fetch_raw; \
    fetch_raw(Path('D:/proyectos/databases/exchange_fees/raw'))"

# 2. build (refuses to overwrite an existing exchange_fees_v1); add owner_provided=[...] once the
#    firm supplies its exchange fee file
uv run python -c "from pathlib import Path; from crucible.data.exchange_fees import \
    build_exchange_fees; r = build_exchange_fees( \
    Path('D:/proyectos/databases/exchange_fees/raw'), \
    Path('D:/proyectos/crucible/data/processed')); print(r)"

# 3. read the components one root has for one date, through the run's participant profile
uv run python -c "import datetime as dt; from pathlib import Path; \
    from crucible.data.store import ParquetDataStore; from crucible.data.exchange_fees import \
    ParticipantProfile, fee_rows_as_of; \
    profile = ParticipantProfile.from_mapping({'cme_membership_status': 'non_member', \
    'nfa_assessment_eligibility': 'fcm_member'}); print(fee_rows_as_of(ParquetDataStore( \
    Path('D:/proyectos/crucible/data/processed')), 'ES', dt.date(2026, 11, 21), \
    profile=profile, components=('exchange', 'nfa')))"
```

Step 3 prints `nfa` priced and `exchange` in `gaps` for this build: the exchange component is
absent, and the caller reports it as a gap.
