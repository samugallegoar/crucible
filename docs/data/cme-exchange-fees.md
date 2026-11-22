# Execution fees: per component, per side, per contract (owner-sourced; exchange and clearing pending)

Dataset `exchange_fees_v1`. The per-side, per-contract USD amounts a retail customer of a prop
firm's clearing chain pays **on top of a commission that excludes them**, split into the components
a firm's commission may or may not contain:

| `fee_type` | Component | Who states it |
|---|---|---|
| `exchange` | the exchange's own trading fee | only an owner file: CME Group publishes product buckets, not root tickers |
| `clearing` | the clearing fee | only an owner file |
| `nfa` | the NFA assessment fee | the official bylaw page, fetched and parsed |
| `other` | any other per-side charge the source states | only an owner file |

Built by `crucible/data/exchange_fees.py`. This page records one uncomfortable fact first: the
dataset holds **the NFA fee only**. No exchange, clearing or other row is stored, because CME Group
refuses automated access and its published schedule does not name a root ticker, so a per-root rate
cannot be read off it without guessing. `fee_rows_as_of` therefore prices **only the root and the
components it has rows for** and returns nothing for the rest — an unpriced component is a gap the
caller reports, never a zero. The decision, and the alternatives considered, are recorded in
`docs/adr/0107-firm-rulesets-and-attempt-statistics.md` (section 10 and its amendment); nothing here
was fetched from `cmegroup.com` or copied from an archive of it.

**No universal fee, and no extrapolation.** A row prices exactly its `root`, `participant_type` and
date range, and it states which components its amount covers (`covers`). There is no product-bucket
to root mapping anywhere in this repository, and no fee is carried across roots, products or
participant types: the engine never invents one.

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
- **`participant_type = fcm_member_assessment`.** The bylaw assesses the *FCM member* per contract;
  a customer sees it passed through. It is therefore not a customer rate class, and
  `fee_rows_as_of` prices an `nfa` row for **any requested participant type** (that is the one
  stated exception to the exact-match rule, and it is why a run's `--fee-participant-type
  non_member_customer` can price the NFA component while a member row cannot price a customer's
  exchange fee).

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

### Owner-provided fee file — how the CME rows get in

A person who holds the exchange fee schedule supplies a CSV; the loader records who supplied it,
the file's own SHA-256, and the exact cell text as the row's evidence. That is the only route an
exchange or clearing fee has into this dataset. Header (order is free, extra columns are refused):

```csv
root,fee_type,participant_type,covers,per_side_usd,effective_from,source_url,quote,venue,effective_to
ES,exchange,non_member_customer,exchange;clearing,0.00,2026-01-01,https://www.cmegroup.com/company/clearing-fees/historical-fees.html,"SYNTHETIC EXAMPLE: the exact cell text for ES, e.g. the product row and the Non-Members column",CME,
MES,nfa,non_member_customer,nfa,0.00,2026-01-01,https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=3&SubSection=13,"SYNTHETIC EXAMPLE: the bylaw sentence",CME,
```

Every value above is an **obviously synthetic placeholder**: `0.00` and the words
`SYNTHETIC EXAMPLE` mark a cell a person must fill from the document they downloaded. No real CME
rate appears anywhere in this repository (a test enforces it).

| Column | Meaning |
|---|---|
| `root` | one of ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K |
| `fee_type` | `exchange`, `clearing`, `nfa` or `other`: the component the amount is typed as. **It must appear in `covers`** |
| `participant_type` | who the rate is for: `non_member_customer`, `member`, `fcm_member_assessment`, … No extrapolation: a row prices its own type only |
| `covers` | **mandatory**: the components the amount covers, `;`-separated. A CME "Exchange Fees for Clearing & Trading" cell is `fee_type=exchange`, `covers=exchange;clearing`, and it is charged ONCE for both |
| `per_side_usd` | USD per contract per side, a decimal string (parsed as `Decimal`, never a float) |
| `effective_from` | `YYYY-MM-DD`, the first date the rate applies |
| `effective_to` | optional, `YYYY-MM-DD`, the last date; empty = open-ended |
| `venue` | optional; defaults from `VENUE_OF[root]` and must agree with it (ES/NQ/RTY/NKD/MES/MNQ/M2K = CME, YM/MYM = CBOT) |
| `source_url` | **mandatory**: the document the cell came from — one of the two CME pages above, or the NFA bylaw page |
| `quote` | **mandatory**: the exact text the rate was read from (the cell, the row, the sentence) |

Refusals, each with a message that says what to fix:

- an empty `quote` (a rate nobody can point at), a missing `source_url`, a missing supplier, an
  unknown or misspelled column, a root outside `ROOTS`, a `venue` that disagrees with `VENUE_OF`,
  a non-numeric or negative amount, `effective_to` before `effective_from`;
- **a `covers` list that does not contain the row's own `fee_type`** (a row prices the component it
  is typed as), an empty `covers`, or a `covers` name that is not a component;
- **two rows that start on the same date for one `(root, participant_type, component)`**, and
- **overlapping rows for the same `(root, participant_type, component)`** — a component covered
  twice on one date by different rows, including one row that covers `exchange;clearing` and
  another that covers `clearing` alone. A date must map to one amount per component, never to a
  row order.

## Schema

`crucible/data/exchange_fees.py::EXCHANGE_FEE_SCHEMA`, stored sort order `root`, `participant_type`,
`fee_type`, `effective_from`, `covers` (columns in `docs/SCHEMAS.md` §1.7).

## Lookup

```python
fee_rows_as_of(store, "ES", dt.date(2024, 7, 1),
               participant_type="non_member_customer",
               components=("exchange", "clearing", "nfa", "other"))
# -> {"exchange": (Decimal("0.77"), "<record sha256>"), "clearing": (...), "nfa": (Decimal("0.01"), ...)}
```

- **Only the root asked for is priced.** An owner file that prices ES alone is usable; the nine
  roots are no longer demanded at once.
- A component with no covering row is **absent** from the result: the caller reports it as a gap,
  never as zero.
- A row that covers several components is charged once (the attempt's pricing groups the components
  by the row's record hash, and the first component in report order carries the amount while the
  others say they are inside it).
- `participant_type` matches exactly — with the one stated exception of `nfa` rows, which are the
  FCM member's pass-through assessment and price any requested type.
- Two rows covering one component on one date raise, by name: no amount is chosen from a
  contradiction.
- A root outside `ROOTS` raises. The engine never maps a CME product bucket to a root.

## Assumptions

- **`participant_type`.** CME's schedule does not say which class a prop firm's customer accounts
  fall into, and a ruleset never states one either. The run passes the participant type
  (`--fee-participant-type`, MCP `fee_participant_type`) and the estimate becomes `conditional`
  with the reason `participant type assumed: <x>`. `non_member_customer` is the class the exchange
  rows of an owner file normally carry — **confirm it against the firm's clearing agreement**
  before a fee-driven result is relied on; an owner file that states another class wins, because it
  says so in `participant_type`.
- **Per side.** Every component is stored per side (`per_side_usd`): a round trip is
  `2 × per_side_usd`. The NFA figure is halved from the bylaw's round-turn amount for exactly this
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

# 3. read the components one root has for one date
uv run python -c "import datetime as dt; from pathlib import Path; \
    from crucible.data.store import ParquetDataStore; from crucible.data.exchange_fees import \
    fee_rows_as_of; print(fee_rows_as_of(ParquetDataStore( \
    Path('D:/proyectos/crucible/data/processed')), 'ES', dt.date(2026, 11, 21), \
    participant_type='non_member_customer', components=('exchange', 'nfa')))"
```

Step 3 prints only `nfa` for this build: the exchange component is absent, and the caller reports it
as a gap.
