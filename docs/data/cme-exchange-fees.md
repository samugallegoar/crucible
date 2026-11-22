# Exchange and NFA fees: per side, per contract (regulatory fee sourced; exchange fee pending)

Dataset `exchange_fees_v1`. The per-side, per-contract USD amounts a retail customer of a prop
firm's clearing chain pays **on top of a commission that excludes them**: the CME Group exchange
fee and the NFA assessment fee, for ES, NQ, YM, RTY, NKD, MES, MNQ, MYM and M2K.

Built by `crucible/data/exchange_fees.py`. This page records one uncomfortable fact first: the
dataset holds **the NFA fee only**. No CME exchange fee is stored, because CME Group refuses
automated access and its published schedule does not name a root ticker, so a per-root rate
cannot be read off it without guessing. `fee_table_as_of` therefore **refuses** instead of
pricing an unknown fee at zero, and an exchange fee enters the dataset only from a file the
owner supplies (below). The decision, and the alternatives considered, are recorded in the
task's report; nothing here was fetched from `cmegroup.com` or copied from an archive of it.

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

Two conversions, both stated by the text and neither inferred:

- **Per side = half the round-turn amount.** The bylaw assesses a *round turn* ($.02), so a side
  is $0.01 through 2027-06-30 and $0.02 from 2027-07-01. Both rows are written: the sentence
  states the second amount and its start, so the later rate is a fact, not a projection.
- **The FCM member pays it, the customer sees it passed through.** `fee_class` is
  `fcm_member_assessment` for NFA rows: the bylaw assesses the *FCM member* per contract. It is a
  fee a customer pays through the FCM, which is why the prop-firm fee table adds it to the
  exchange fee rather than treating it differently.

### CME Group exchange fee — **not sourced, on purpose**

Two independent blockers, both of which would have to be lifted to store a CME rate:

1. **`cmegroup.com` refuses automated access from the machine this was built on.** Every text URL
   — including `/robots.txt` — answers HTTP 403 with:

   > This IP address is blocked due to suspected web scraping activity associated with it on this
   > CMEgroup.com page. Use of scripts, software, spiders, robots, avatars, agents, tools or other
   > scraping mechanisms is strictly prohibited by CME Group's website Data Terms of Use.

   The project does not work around a publisher's refusal: no archived copy of a CME Group file is
   fetched, kept or read as a substitute, and nothing from one is stored in this dataset or its
   raw folder. (The raw folder holds exactly one file: the NFA page.)
2. **Even with the document in hand, the fee is not attributable to a root.** CME's schedule names
   product *buckets* — "Equity Index", "Nikkei/TOPIX", "E-mini Equity Index", "Micro E-mini
   Index", "E-nano Index" — never a ticker such as `ES`, `MES` or `NKD`, and the column geometry
   of the published layout does not tie a bucket to a single column unambiguously (buckets span
   one to three columns under merged headers, and the fee-class label column does not align with
   the value rows). Which column is ES and which is MES would be an inference, and inferring a
   money amount is the one thing this dataset may not do (AGENTS.md §1.2, §1.5).

The observable consequence is deliberate and tested (`test_fee_table_refuses_while_the_exchange_fee_is_unknown`):
`build_exchange_fees` writes **zero** `fee_type = exchange` rows, `BuildReport.exchange_roots_missing`
names all nine roots, and `fee_table_as_of(store, date)` raises until they are priced.

### Owner-provided fee file — how the CME rows get in

A person who holds the exchange fee schedule supplies a CSV; the loader records who supplied it,
the file's own SHA-256, and the exact cell text as the row's evidence. That is the only route an
exchange fee has into this dataset. Header (order is free, extra columns are refused):

```csv
root,fee_type,fee_class,per_side_usd,effective_from,effective_to,venue,quote,source_url
ES,exchange,non_member_customer,0.00,2026-01-01,,CME,"<the exact cell text, e.g. the product row and the Non-Members column>",<document name>
```

| Column | Meaning |
|---|---|
| `root` | one of ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K |
| `fee_type` | `exchange` (an owner file may also state `nfa`, e.g. for an earlier period) |
| `fee_class` | the rate class the source states; **`non_member_customer`** is the class a prop firm's customer accounts are assumed to be in — see "Assumptions" |
| `per_side_usd` | USD per contract per side, a decimal string (parsed as `Decimal`, never a float); the `0.00` above is a placeholder, no rate is implied |
| `effective_from` | `YYYY-MM-DD`, the first date the rate applies |
| `effective_to` | `YYYY-MM-DD`, the last date; empty = open-ended |
| `venue` | optional; defaults from `VENUE_OF[root]` and must agree with it (ES/NQ/RTY/NKD/MES/MNQ/M2K = CME, YM/MYM = CBOT) |
| `quote` | **mandatory**: the exact text the rate was read from (the cell, the row, the sentence) |
| `source_url` | optional: the document the cell came from |

Refusals, each with a message that says what to fix: an empty `quote` (a rate nobody can point at),
a missing supplier, an unknown or misspelled column, a root outside `ROOTS`, a `venue` that
disagrees with `VENUE_OF`, a non-numeric or negative amount, `effective_to` before
`effective_from`, two rows starting on the same date for one `(root, fee_type)`, and two rows that
overlap in time (a date must map to one rate, never to a row order).

## Schema

`crucible/data/exchange_fees.py::EXCHANGE_FEE_SCHEMA`, stored sort order `root`, `fee_type`,
`effective_from` (columns in `docs/SCHEMAS.md` §1.7).

## Assumptions

- **`fee_class`.** CME's schedule does not say which class a prop firm's customer accounts fall
  into. Exchange rows must carry an explicit class; the class this dataset assumes and documents is
  `non_member_customer` — the rate a retail customer of an FCM pays, not a member, lessee or
  clearing-member rate. **Confirm this against the firm's clearing agreement** before a fee-driven
  result is relied on; an owner file that states another class wins, because it says so in
  `fee_class` and in `quote`.
- **Per side.** Both fee types are stored per side (`per_side_usd`): a round trip is
  `2 × per_side_usd`. The NFA figure is halved from the bylaw's round-turn amount for exactly this
  reason, and the halving is stated in the module docstring of `parse_nfa_assessment`.
- **`available_at = event_time = 00:00 UTC of effective_from`.** Neither source states when its
  rate became public (NFA names the last amendment date of the bylaw, not of the rate), so the row
  records the weaker, provable claim: the rate is visible only from the day it applies. A
  backtest's point-in-time read can therefore never see a future rate, and cannot see a rate on the
  day it was published but not yet effective.

## Coverage (rows in this build)

| Fee | Roots | effective_from | effective_to | per side |
|---|---|---|---|---|
| NFA assessment | all nine | 2026-07-01 | 2027-06-30 | $0.01 |
| NFA assessment | all nine | 2027-07-01 | — (open) | $0.02 |
| exchange | — | — | — | **none stored** |

This build: 18 rows (2 per root), content hash `90282b6d8ce6f7c7…`, 1 snapshot,
`rows_by_type = {exchange: 0, nfa: 18}`, `rows_by_source = {official_page: 18, owner_provided: 0}`,
`exchange_roots_missing = (ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K)`.

## Gaps

- **Every exchange fee is missing** (all nine roots, all dates). The consequence is a refusal, not a
  zero: `fee_table_as_of` raises for every date, so any attempt that excluded exchange fees stays
  conditional/unavailable until an owner file is supplied.
- **Dates before 2026-07-01 have no NFA row.** The bylaw page states the current rate and the
  amendment dates of Bylaw 1301, but not the rate each amendment set; reconstructing earlier rates
  would be a guess (their own archived copies would be needed, and the earlier period is not what
  this dataset was asked for). A fee table for 2025-08 dates therefore also refuses.
- **The NFA row says nothing about options.** The bylaw's option clause (`(B)`, per trade) is a
  different instrument; this dataset covers futures only. `M2K`, `MES`, `MNQ` and `MYM` rows refer
  to the futures contracts.
- **No commission, no exchange regulatory fee, no clearing fee, no market-data fee.** Only the two
  fees named above; a commission that already includes the exchange fee must not also add these.
- **The `fee_class` assumption is unconfirmed** (above). It is an assumption the coordinator must
  confirm with the firm, not a fact read from a source.

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

# 3. read it as the fee table a run would use
uv run python -c "import datetime as dt; from pathlib import Path; \
    from crucible.data.store import ParquetDataStore; from crucible.data.exchange_fees import \
    fee_table_as_of; fee_table_as_of(ParquetDataStore( \
    Path('D:/proyectos/crucible/data/processed')), dt.date(2026, 11, 21))"
```

Step 3 raising `ConfigurationError` is the expected state of this build; it names each unpriced
root and points at the owner file.
