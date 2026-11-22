# Economic events: FOMC statements, CPI and Employment Situation releases (official sources)

Dataset `econ_events_v1`. The release instants of the three events a `news_restriction`
(ADR-0107 section 12) needs: every FOMC policy statement the Federal Reserve publishes, the BLS
Consumer Price Index release, and the BLS Employment Situation release ("nonfarm payrolls").

Built by `crucible/data/econ_events.py` from raw page snapshots; nothing is hand-entered and there
are no hardcoded dates. Time span: **2010-01-01 to the last date the sources publish**
(2028-01-26, the first FOMC meeting of 2028 that the current calendar announces), with future
scheduled dates included and flagged `status: scheduled`.

This is **not futures market data**: the futures holdout vault (`docs/modules/data.md`,
ADR-0105) does not cover it, and it is read structurally, not as a point-in-time market series
(see "How `available_at` is set" below).

## Sources (official only)

Retrieved **2026-11-22T02:33:44Z – 02:43:16Z** (plus one Internet Archive capture from
2025-09-12T15:08:17Z). 173 pages, 15.2 MB of raw bytes, unchanged and never re-fetched
(`load_snapshots` refuses a byte whose SHA-256 no longer matches `MANIFEST.json`).

| Source | Pages | What it states |
|---|---|---|
| `federalreserve.gov/monetarypolicy/fomccalendars.htm` | 1 | the scheduled meetings of 2021-2027 (statement links, meeting ranges) and the 2028 note |
| `federalreserve.gov/monetarypolicy/fomchistorical<YEAR>.htm` | 11 (2010-2020) | every meeting of those years, including the `(unscheduled)`, `(cancelled)` and `(notation vote)` panels |
| `federalreserve.gov/newsevents/pressreleases/monetary<YYYYMMDD>a.htm` | 142 | **the release time of each statement** ("For release at 2:00 p.m. EDT", or "For immediate release" before 2016) and the release date |
| `bls.gov/schedule/<YEAR>/home.htm` | 18 (2010-2027) | "Schedule of Selected Releases": date, time (08:30 AM) and reference period of every CPI and Employment Situation release |
| `web.archive.org/web/20250912150817/bls.gov/schedule/2025/home.htm` | 1 | the same 2025 schedule **before** the autumn 2025 shutdown moved and cancelled releases |

`docs/data/cme-globex-sessions.md` sets the precedent for reading an archived copy when the
publisher serves only the current page: the archive is a read path to the official bytes, and both
the archive URL and the capture instant are in `MANIFEST.json`.

**Unreadable pages: none.** bls.gov answers a bare `curl` with 403 and a browser-shaped request
with the page; `_BROWSER_HEADERS` in `crucible/data/econ_events.py` carries the headers that work
(User-Agent, Accept, Accept-Language, `Upgrade-Insecure-Requests`, `Sec-Fetch-*`), and
`docs/data/README.md` notes it. No BLS page stayed unreadable, so no period is a coverage gap for
that reason.

## Schema

`crucible/data/econ_events.py::ECON_EVENT_SCHEMA`, stored sort order
`event_time`, `event_type`, `event_id` (columns in `docs/SCHEMAS.md` §1.2).

- `event_id` — `<event_type>-<YYYYMMDD>`, dated by the **scheduled** release date (the original one
  for a rescheduled release); a `-2`, `-3` suffix only if two events of one type share a date
  (never happens today).
- `scheduled_local` — the release instant as the source states it, ISO 8601 **with the UTC offset
  of that date** in `America/New_York` (`2026-03-11T08:30:00-04:00`, `2026-11-10T08:30:00-05:00`).
- `event_time` — the release instant that materialised (UTC ns). For a rescheduled release this is
  the instant it *actually* happened; `scheduled_local` keeps the earlier date.
- `time_known` / `scheduled_time_source` — whether the source stated the hour
  (`fed_stated`, `bls_stated`) or only the day (`not_stated`), in which case `event_time` is
  **00:00 local on that day**, a marker for the day, not a claim about the minute.
- `status` — `released`, `scheduled`, `rescheduled`, `cancelled`.
- `actual_publication_date`, `unscheduled`.
- `source_url`, `snapshot_sha256` — the page a row was read from and its byte hash, so every row
  cites its evidence; `record_sha256` is the SHA-256 of the row's other fields in canonical JSON.
- `available_at`, `availability_basis`, `dataset_version`.

### How `available_at` is set

`available_at` is the instant the *schedule entry* was publicly known. **No page we read states
when its own entries were first published**: the Fed's footer says "Last Update: November 18, 2026"
and a BLS yearly schedule page carries month-block "Last Modified Date"s — page maintenance, not
the publication of an entry, and years after the event for a historical page. So every row of this
build is `availability_basis: schedule_publication_unknown` and `available_at = event_time`
(`schedule_page_stated_date` exists in the code for a source that does state a publication date,
and is covered by a unit test, but no page here does).

Consequences, which the consumer has to respect:

- a point-in-time read at a strategy's `as_of` **hides an event before it happens**, i.e. hides it
  in the optimistic direction. Using this dataset as a *signal* would let the strategy trade
  through the event. ADR-0107 section 12 is explicit that the calendar constrains through a *firm
  rule* (`news_restriction`), which is a fixed constraint rather than a signal, and
  `load_econ_events` therefore reads it with the open-ended `as_of` sentinel by default and says
  so in its docstring; a caller that wants the point-in-time view passes `as_of=` and gets the
  strict reading;
- conversely a *future* release is knowable before it happens, so `available_at` is a lower bound
  on knowledge, never an upper bound. The safer claim (nothing before the event) is what is
  stored.

## Cleaning steps (counts from this build)

Nothing was dropped silently; each line is a rule in the code:

| Step | Count |
|---|---|
| Fed pages read (calendar + yearly historical) | 12 pages, 101 meeting panels, 57 calendar meeting rows |
| FOMC statement pages fetched and parsed | 142 |
| FOMC rows written | 149 |
| … of which from a statement page / from the calendar for a future meeting | 139 / 10 |
| FOMC statement pages **not** used | 3 — `monetary20200331a` (labelled "Press Release"), `monetary20200827a` and `monetary20250822a` ("Statement on Longer-Run Goals") |
| `(cancelled)` panels (no statement, produce no row) | 2 — the 2020-03-17/18 meeting, and the 2013-10-16 panel has no statement link |
| `(notation vote)` calendar rows skipped | 1 (2025-08-22) |
| `(notation vote)` panels whose link is labelled "Statement" **kept** | 1 (2020-03-23, an intermeeting policy action) |
| Intermeeting actions flagged `unscheduled` | 5 — 2010-05-09 (conference call), 2019-10-11, 2020-03-03, 2020-03-15, 2020-03-23 |
| BLS schedule pages read | 18 (2010-2027) |
| BLS table rows read | 3,052 |
| CPI + Employment Situation rows kept | 430 (live pages) + 4 (2025 earlier capture) |
| "Employment Situation of Veterans" rows ignored (a different report) | 18 |
| Other BLS rows ignored (other releases, holidays) | the rest (2,604) |
| Rows written | 581 — `FOMC_STATEMENT` 149, `CPI` 216, `NFP` 216 |
| … by status | `released` 539, `rescheduled` 4, `scheduled` 36, `cancelled` 2 |
| Rows whose hour no source stated (`time_known = false`) | 58 — the 2010-2015 FOMC statements (48) and the 10 announced-but-not-yet-released meetings |
| Dataset | 581 rows, content hash `859415e983c31552…`, 159 distinct snapshot hashes cited |

Three parsing rules worth spelling out:

1. **A 2010-2015 FOMC statement has no stated hour.** The Fed published those press releases as
   "For immediate release"; the page states the date but not the time. They are kept with
   `time_known = false`, never with an invented 14:00. From 2016 on every statement states
   "For release at 2:00 p.m. EST/EDT" and the abbreviation is checked against New York's actual
   offset on that date (a page printing EDT in January is refused).
2. **A meeting that has not happened yet has no hour.** The calendar states the meeting range
   (e.g. `26-27`), so the statement day is the last day of the range and the hour is `not_stated`.
   The calendar itself warns that "each meeting date is tentative until confirmed at the meeting
   immediately preceding it".
3. **The BLS times are Eastern.** 17 of the 18 pages print "NOTE: All times on calendar are
   Eastern Time"; the 2017 page omits the note but is the same table at the same 08:30 AM as its
   neighbours, and every one of the 430 rows states 08:30 AM. A row with no time would be kept
   with `time_known = false` (none occurs).

## Coverage table (events found vs the count the source states)

Expected counts: FOMC 8 scheduled meetings a year; CPI 12; NFP 12 (one a month).

| Year | FOMC | CPI | NFP | Notes |
|---|---|---|---|---|
| 2010 | 9 | 12 | 12 | 8 meetings + the 2010-05-09 conference-call statement |
| 2011 | 8 | 12 | 12 | |
| 2012 | 8 | 12 | 12 | |
| 2013 | 8 | 12 | 12 | October 2013 shutdown: the schedule states only the final (moved) dates |
| 2014 | 8 | 12 | 12 | |
| 2015 | 8 | 12 | 12 | |
| 2016 | 8 | 12 | 12 | the Fed starts stating the release hour |
| 2017 | 8 | 12 | 12 | |
| 2018 | 8 | 12 | 12 | |
| 2019 | 9 | 12 | 12 | + the 2019-10-11 unscheduled statement |
| 2020 | 10 | 12 | 12 | 7 meetings + 2020-03-03, 2020-03-15, 2020-03-23; the March 17-18 meeting was cancelled |
| 2021 | 8 | 12 | 12 | |
| 2022 | 8 | 12 | 12 | |
| 2023 | 8 | 12 | 12 | |
| 2024 | 8 | 12 | 12 | |
| 2025 | 8 | 12 | 12 | shutdown: 2 rescheduled + 1 cancelled each for CPI and NFP (below) |
| 2026 | 8 | 12 | 12 | 7 released, 2026-12-09 still `scheduled` |
| 2027 | 8 | 12 | 12 | all `scheduled` |
| 2028 | 1 | — | — | the 2028-01-26 meeting the 2027 calendar announces |

A year is "short" only where the source says so: 2010 (8 meetings + 1 conference call, 9 rows is
*more* than 8), 2019 and 2020 are over the 8-meeting baseline for the same reason.

### Gaps and moved releases

`coverage(store)` reports one gap: **NFP, 2025-10-01 → 2025-11-01**. The 2025 shutdown moved the
"Employment Situation for September 2025" release from 2025-10-03 to 2025-11-20, so October 2025
holds no NFP event at all — a `news_restriction` on NFP cannot be evaluated for that month.
Everything else is covered; a `cancelled` row still marks its month as covered, because the
calendar *did* say something about it.

The 2025 releases the shutdown moved or cancelled (the earlier capture of 2025-09-12 versus the
current page):

| Release | Was | Became | Status |
|---|---|---|---|
| Employment Situation for September 2025 | 2025-10-03 | 2025-11-20 | `rescheduled` |
| Consumer Price Index for September 2025 | 2025-10-15 | 2025-10-24 | `rescheduled` |
| Employment Situation for October 2025 | 2025-11-07 | — | `cancelled` |
| Consumer Price Index for October 2025 | 2025-11-13 | — | `cancelled` |
| Employment Situation for November 2025 | 2025-12-05 | 2025-12-16 | `rescheduled` |
| Consumer Price Index for November 2025 | 2025-12-10 | 2025-12-18 | `rescheduled` |

Both dates are kept: `scheduled_local` is the earlier one, `actual_publication_date` the one that
materialised (null for `cancelled`). Nothing is guessed — the earlier date comes from an official
snapshot of the same page.

## Known issues

- **The 2013 shutdown's original dates are not recorded.** The current schedule page states only
  the final dates (2013-10-22 NFP, 2013-10-30 CPI, 2013-11-08, 2013-11-20, ...), and the Internet
  Archive holds **no** capture of `bls.gov/schedule/2013/home.htm` before 2016 (checked with its
  CDX API), so the October 2013 releases are `released` on the dates the source states, not
  `rescheduled`. Using the unit's own memory of the original dates would be a guess.
- **2010-2015 FOMC statements have no stated hour** (48 rows, `time_known = false`). A consumer
  must widen a window to the whole local day for those rows; `day_only_events(frame)` returns them.
  Reading a time from the statement's PDF was not attempted (a PDF text extraction would add a
  dependency, and the HTML page is what the Fed publishes as the accessible version).
- **10 announced meetings state a date but no hour** (2026-12-09, the eight 2027 meetings and
  2028-01-26), and their dates are "tentative until confirmed at the meeting immediately
  preceding it".
- **Notation-vote statements are mostly excluded.** A `(notation vote)` panel is read only when
  its link is labelled exactly "Statement" (2020-03-23, an intermeeting policy action). The two
  "Statement on Longer-Run Goals and Monetary Policy Strategy" pages (2020-08-27, 2025-08-22) and
  the procedural press releases are not FOMC policy statements. If a firm's rule anchors on one of
  those, it needs its own source.
- **Two policy statements are in neither list:** the joint Treasury/Fed announcements (e.g.
  2023-03-12 on SVB) are not FOMC statements and do not appear on the pages read.
- **`available_at` is weaker than the truth** (above). Do not use this dataset as a signal.
- **One event per release.** The reference period a release covers ("for December 2009") is not a
  column: it is only the key that matches a release across two snapshots. A consumer that needs
  the period must read it from the source.
- The Fed's meeting statement date is taken from the **statement page**, not from the meeting
  range, whenever the statement exists (so 2020-03-02 released on 2020-03-03 is one event on
  03-03). For a meeting without a statement page, the statement day is the last day of the range.

## Rebuild

The raw snapshots are the source of truth. Re-fetching (only when the sources publish more) and
rebuilding:

```bash
# 1. fetch (idempotent: an existing file is never re-fetched or rewritten)
uv run python -c "from pathlib import Path; from crucible.data.econ_events import fetch_raw; \
    fetch_raw(Path('D:/proyectos/databases/econ_events/raw'))"

# 2. build into the store (refuses to overwrite an existing econ_events_v1)
uv run python -c "from pathlib import Path; from crucible.data.econ_events import build_econ_events; \
    r = build_econ_events(Path('D:/proyectos/databases/econ_events/raw'), \
    Path('D:/proyectos/crucible/data/processed')); print(r.rows, r.content_hash, r.events_by_type)"

# 3. the real-data checks (per-year table, the two March 2020 actions, no duplicate id)
CRUCIBLE_DATA_STORE=D:/proyectos/crucible/data/processed uv run pytest -m bench \
    tests/bench/test_econ_events_real.py -q
```

A re-fetch on a later date writes a new `<YYYYMMDD>_*` snapshot set beside the old one; the
build then refuses (`exactly one current BLS schedule for <year>`), so move the superseded
set out of the folder — or into an archive subfolder — before rebuilding.

`fetch_raw` discovers the statement pages **from the Fed's own calendar and historical pages**, so
a year the Fed adds is picked up without a code change; `FOMC_HISTORICAL_YEARS`,
`BLS_SCHEDULE_YEARS` and `ARCHIVED_SCHEDULES` (the archived earlier readings) are the only lists
in the code. Keep the raw folder: a rebuild without it is impossible (the dataset cites the
SHA-256 of each page it was read from).
