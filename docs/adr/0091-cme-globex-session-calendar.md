# ADR-0091: A versioned CME Globex session calendar transcribed from published schedules

Status: accepted (2026-11-17). The owner set the requirements (milestone C3b, refinement A); this
ADR records how they are met. It adds a module and a table; no engine, config, artifact or golden
fixture changes. The futures run that consumes it is a later step of C3b.

## Context

Intraday futures rules (`flat_by_close`, `exit_at`, an entry window) need to know when each Globex
session opens, closes and halts. What existed does not say:

- `CMES` (`exchange_calendars`) models each session as one 24 h block. It has no maintenance break,
  no 15:15-15:30 halt, no early closes and no historical changes (ADR-0087, ADR-0088).
- `cme_trade_date_expr` (ADR-0087) assigns trade dates with one rule: the trade date changes at
  17:00 Chicago. That rule is wrong before trade date 2012-11-19, when the equity session opened at
  15:30 (see "Findings").
- Inferring a schedule from the bars is not allowed. Missing bars do not prove a market was
  closed (owner, refinement A).

## Decision

1. **One table, transcribed from documents.** `crucible/data/cme_session_table.py` holds:
   - **Regimes**: the regular week of a period. A weekday trade date D opens on D-1 (Monday: Sunday
     17:00) and closes on D. Daily closed windows apply on every calendar day the session spans.
   - **Overrides**: a trade date's open, close and halts.
   - **No-trade dates**: weekdays without a trade date.
   - **Unsourced windows**: dates no transcribed document covers.
   - **Unscheduled events**: interruptions recorded after the fact.
   - **Sources**: title, URL, archive URL, publication date, retrieval date and the SHA-256 of the
     bytes read.

   Times are `America/Chicago` wall clock. They are converted to UTC int64 ns at the
   `calendars.py` boundary (ADR-0004), which refuses a time that falls inside a DST transition. The
   table has a version (`cme-equity-sessions-1`) and a hash of its canonical JSON (`table_summary`),
   which a run records.

2. **The regimes, by trade date:**

   | Trade dates | ES/NQ/YM(/RTY) | NKD | Source |
   |---|---|---|---|
   | 2010-06-07 to 2012-11-16 | opens D-1 15:30, closes 15:15, maintenance 16:30-17:00 | not covered | CME education sheet "current arrangement" |
   | 2012-11-19 to 2015-09-18 | opens D-1 17:00, closes 16:15, halt 15:15-15:30 | the same until 2013-03-01, then no halt | SER-6465 (2012-11-14), SER-6554R (2013-02-21) |
   | 2015-09-21 to 2021-06-25 | closes 16:00, halt 15:15-15:30 | closes 16:00, no halt | CME Globex notice 2015-09-07 |
   | from 2021-06-28 | closes 16:00, no halt | closes 16:00, no halt | CME Submission 20-244 (filed 2021-06-11) |

3. **Holidays and special closures, per document:**

   | Years | Source |
   |---|---|
   | 2010-2022 | The annual holiday-calendar zips. The PDF is used where published, the XLS otherwise; 2014 MLK, Presidents and Good Friday come from the XLS because those PDFs are unreadable. |
   | 2023 New Year | The 2023 New Year XLS. |
   | 2023-09 to 2025-09 | Wayback captures of CME's trading-hours service (ES only). |
   | 2025-11-17 to 2027-12-31 | The live service, retrieved 2026-11-17, covering all five products. |
   | Special closures | Hurricane Sandy (2012-10-29/30), CME press releases. Bush mourning day (2018-12-05), SER-8289. Carter mourning day (2025-01-09), CME press release. The mourning days close U.S. equity at 08:30; SER-8289 keeps international equity, including NKD, at normal hours. |

4. **The table refuses contradictions.** These are refused:
   - more than one regime for a trade date;
   - a trade date following a closed weekday with no explicit open (the default rule is never
     assumed after a holiday);
   - a close at or before its open;
   - overlapping sessions;
   - two overrides for one root and trade date;
   - an entry that cites an unknown source;
   - a date outside the root's coverage.

   A test builds every covered session of every root.

5. **Coverage and verification.**
   - **Coverage:** ES, NQ and YM from trade date 2010-06-07; RTY from 2017-07-10; NKD from
     2012-11-19; all to 2027-12-31. The 2010 Presidents Day schedule carries an NKD-specific
     exception, and NKD is not asserted before the first document that names it.
   - **Unverified sessions:** a session that touches an unsourced window is built from its regime
     and flagged `verified=False`. The unsourced windows are:
     - 2023: MLK, Presidents, Good Friday (the clearing advisory confirms an abbreviated session
       but not its close), Memorial, Juneteenth, July 4 and Thanksgiving;
     - MLK 2024;
     - NKD on the 2023-2025 dates taken from ES-only captures. NKD trades past the U.S. early
       closes of July 3, 2024 and July 3, 2025.

   A strict caller refuses unverified sessions; the run that uses them must say so.

6. **Observed bars validate, never define.** `schedule_report` reports:
   - bars outside every scheduled segment (a table error or a data defect);
   - scheduled bars with no data (a data gap, never a closure).

   It never changes the table.

   **Unscheduled events.** The CME outage of 2025-11-28 is an unscheduled event. The scheduled
   session is kept, and its missing bars are a gap.

7. **Session rules run on the trade-date clock** (`session_rule_masks`):
   - **`flat_by_close`:** the exit is decided at the close of the penultimate scheduled bar and
     fills at the open of the final scheduled bar.
     - If the penultimate bar is missing, the last observed bar before it decides. That is
       earlier, never later.
     - If the final bar is missing, the trade date is listed in `missing_final`. A strict run
       refuses rather than fill at another bar or after the session.
   - **`exit_at` and `entry_window`:** clock times on the trade date. A time at or after the
     regime's evening open belongs to the evening before; any other time belongs to the trade
     date. So `("18:00", "10:00")` spans midnight, and on a Monday it starts on Sunday.
     - An `exit_at` later than an early close falls back to the flat-by-close rule.
     - A window that ends before it starts is refused.
   - **Off-schedule bars:** a print in the minute after a close or before a reopen is not
     tradable. Nothing is decided at its close, nothing fills at its open, and it never forces a
     position flat.

## Findings (2026-11-17, `schedule_report` on the five `*_1m_raw` datasets)

- **Off-schedule bars.**
  - Counts: 313 for ES, 128 for NQ, 122 for YM, 118 for RTY, 6 for NKD.
  - Every one ends in the minute after a close or halt start (08:16, 12:01, 12:16, 15:16, 16:01,
    16:16, 16:31), or ends exactly at a reopen (15:30, 17:00).
  - None sits inside a closed window, so the table agrees with sixteen years of bars.
  - Before the NKD restriction (decision 5), NKD had 176 more off-schedule bars, on 2024-07-03,
    2025-07-03 and 2025-01-09.
- **Data gaps that the schedule exposes.**
  - The nine holidays from Thanksgiving 2012 to Presidents Day 2014 have no bars between the
    Sunday (or eve) 17:00 open and the 10:30 halt, although every published schedule lists that
    segment.
  - ES has no bars at all on 2014-06-12/13, 2014-09-23..25 and 2014-12-31.
  - These are gaps in the Databento batch, not closures.
- **The ADR-0087 rule mis-assigns trade dates in two cases.**
  - Before 2012-11-19, bars from 15:30 to 17:00 Chicago belong to the next trade date. The
    17:00 rule gives them the same date.
  - In the sessions where a Friday belongs to Monday's trade date (July 4 2014, 2015 and 2020;
    Juneteenth and July 3, 2026), the rule gives the Friday bars to a weekday that is not a trade
    date.
  - The continuous series and the integrity report use that rule. Fixing them changes the
    continuous datasets (version `v3`), so the fix is a separate decision.
- **Feed artefact.** The live service lists Saturday "open 05:00 / closed 17:00" events for
  2026-06-20, 2026-07-04 and 2027-06-19. No Saturday session exists, and they are recorded as a
  conflict and ignored.
- **Source conflict.** For MLK 2013, a draft schedule says the close is 15:15; the published PDF
  says 16:15, and the PDF is used.

## Alternatives considered

- **`CMES` / `exchange_calendars`, or `pandas_market_calendars`.** No maintenance breaks or
  historical regimes in the first; no sources and no per-document provenance in either, and a new
  dependency for the second. Rejected.
- **Infer early closes and halts from the bars.** Forbidden by the owner, and wrong in practice:
  the 2012-2014 holiday gaps would be read as closures.
- **Fetch the schedule from CME at run time.** CME refuses automated access. A run would depend on
  the network, and the past would not be reproducible. Rejected.
- **Assume the regular rule for holidays without a source.** Rejected. The 2023 holidays are
  flagged unverified instead.

## Consequences

- **Explicit, auditable schedule.** Futures session rules can be evaluated against an explicit,
  cited, hashed schedule. A run names the table version and hash.
- **Changes require a new version.** Adding a year, or correcting an entry, requires its source
  and a new `TABLE_VERSION`. A test pins that every cited source exists.
- **Unverified sessions are refused.** Strict callers refuse the 2023 unsourced holidays.
  Sourcing them later lifts the restriction without code changes.
- **Coverage limits.** The calendar covers the five equity-index roots only. Other products need
  their own regimes and holiday rows.
