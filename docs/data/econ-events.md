# Economic events: FOMC statements, press conferences and minutes, CPI, PPI and Employment Situation (official sources)

Datasets `econ_events_v2` (current) and `econ_events_v1` (superseded, kept as built). The release
instants of the events a `news_restriction` (ADR-0107 section 12) needs: every FOMC policy statement
the Federal Reserve publishes, the Chair's press conference after a meeting, the release of each
meeting's minutes, and the BLS Consumer Price Index (CPI), Producer Price Index (PPI) and Employment
Situation ("nonfarm payrolls") releases.

Built by `crucible/data/econ_events.py` from raw page snapshots; nothing is hand-entered and there
are no hardcoded dates. Time span: **2010-01-01 to the last date the sources publish**
(2028-01-26, the first FOMC meeting of 2028 that the current calendar announces), with future
scheduled dates included and flagged `status: scheduled`.

| Dataset | Rows | `dataset_version` | Content hash | Built from |
|---|---|---|---|---|
| `econ_events_v2` | 1,028 | `2` (Int64) | `2d5bcdb38e35fc70…` | 269 snapshots, 23.2 MB |
| `econ_events_v1` | 581 | `"econ_events_v1"` (String) | `859415e983c31552…` | the same folder's first 173 snapshots |

`econ_events_v2` is `econ_events_v1` **plus** three event types, not a revision of it: every v1 row
appears in v2 with the same id, the same instants, the same status, the same source and the same
snapshot hash — only `dataset_version` (and the `record_sha256` that covers it) differ
(`tests/bench/test_econ_events_real.py::test_the_v1_rows_are_untouched_by_the_v2_build`). A consumer
that pinned v1 keeps its verdicts.

This is **not futures market data**: the futures holdout vault (`docs/modules/data.md`,
ADR-0105) does not cover it, and it is read structurally, not as a point-in-time market series
(see "How `available_at` is set" below).

## Sources (official only)

Retrieved **2026-11-22T02:33:44Z – 06:30:23Z** (plus one Internet Archive capture from
2025-09-12T15:08:17Z). 269 pages, 23.2 MB of raw bytes, unchanged and never re-fetched
(`load_snapshots` refuses a byte whose SHA-256 no longer matches `MANIFEST.json`).

| Source | Pages | What it states |
|---|---|---|
| `federalreserve.gov/monetarypolicy/fomccalendars.htm` | 1 | the scheduled meetings of 2021-2027 (statement, press-conference and minutes links, meeting ranges) and the 2028 note |
| `federalreserve.gov/monetarypolicy/fomchistorical<YEAR>.htm` | 11 (2010-2020) | every meeting of those years, including the `(unscheduled)`, `(cancelled)` and `(notation vote)` panels; the press-conference link of each meeting that had one; the minutes link with its **release date** |
| `federalreserve.gov/newsevents/pressreleases/monetary<YYYYMMDD>a.htm` | 142 | **the release time of each statement** ("For release at 2:00 p.m. EDT", or "For immediate release" before 2016) and the release date |
| `federalreserve.gov/monetarypolicy/fomcpresconf<YYYYMMDD>.htm` (or `fomcpressconf…`) | 96 (2011-2026) | **which meetings had a press conference** (the page exists only for those), the meeting it belongs to, and — in its *Related Information* block — the release instant of each document, **including the minutes**: "(Released February 18, 2026 at 2:00 p.m.)" |
| `bls.gov/schedule/<YEAR>/home.htm` | 18 (2010-2027) | "Schedule of Selected Releases": date, time (08:30 AM) and reference period of every CPI, PPI and Employment Situation release |
| `web.archive.org/web/20250912150817/bls.gov/schedule/2025/home.htm` | 1 | the same 2025 schedule **before** the autumn 2025 shutdown moved and cancelled releases |

`docs/data/cme-globex-sessions.md` sets the precedent for reading an archived copy when the
publisher serves only the current page: the archive is a read path to the official bytes, and both
the archive URL and the capture instant are in `MANIFEST.json`.

**Unreadable pages: none.** bls.gov answers a bare `curl` with 403 and a browser-shaped request
with the page; `_BROWSER_HEADERS` in `crucible/data/econ_events.py` carries the headers that work
(User-Agent, Accept, Accept-Language, `Upgrade-Insecure-Requests`, `Sec-Fetch-*`), and
`docs/data/README.md` notes it. No BLS page stayed unreadable, so no period is a coverage gap for
that reason. The Fed's press-conference pages all answered (the two spellings and the absolute URL
the 2022 calendar uses are all in the table above — see "Known issues" for why the spelling is
never rewritten).

## Sources the dataset deliberately does **not** read

- **The minutes pages themselves** (`/monetarypolicy/fomcminutes<YYYYMMDD>.htm`). They state no
  release instant — only the meeting they record and a "Last Update" date — so nothing cites them.
  The minutes *release* is stated by the calendar ("Minutes (Released February 18, 2026)") and its
  *hour* by the meeting's press-conference page.
- **The press-conference transcripts** (`…/files/FOMCpresconf<YYYYMMDD>.pdf`,
  `FOMCpresconf<YYYYMMDD>.htm` for the older years). The transcript's first page states the hour the
  conference began, but reading a PDF would add a dependency, and the HTML page the Fed publishes
  beside it states no hour. So no press-conference row claims one (below).
- **The statement PDFs**, for the same reason (the HTML page is the accessible version).

## Schema

`crucible/data/econ_events.py::ECON_EVENT_SCHEMA`, stored sort order
`event_time`, `event_type`, `event_id` (columns in `docs/SCHEMAS.md` §1.6).

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

How each of the three new types is dated:

| Type | Dated by | Hour |
|---|---|---|
| `PPI` | the BLS "Schedule of Selected Releases" row for that period (`Producer Price Index for December 2009`) | the row's own `08:30 AM`, `bls_stated` |
| `FOMC_PRESS_CONFERENCE` | the day the Fed files the press-conference page under, which is the day of the meeting's statement (checked against it; a disagreement is refused) | **none**: no page states a press conference's hour in HTML, so `time_known = false` and the row marks the local day |
| `FOMC_MINUTES` | the **release** date the meeting panel states ("Minutes (Released February 16, 2011)" on a yearly page, "(Released February 18, 2026)" beside the calendar's link) — not the date of the meeting | the meeting's press-conference page's "(Released … at 2:00 p.m.)" where it states one; otherwise `time_known = false`. Two pages stating different days is refused |

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

## Cleaning steps (v2 build, counts from this build)

Nothing was dropped silently; each line is a rule in the code:

| Step | Count |
|---|---|
| Fed index pages read (calendar + yearly historical) | 12 pages, 101 meeting panels, 57 calendar meeting rows |
| FOMC statement pages fetched and parsed | 142 |
| Press-conference pages fetched and parsed | 96 (2011-2026; one per meeting that had one) |
| Press-conference pages that state the minutes release **day** / the **hour** | 95 / 92 (the three 2011 pages state the day only; the hour appears from the 2012-01-25 page on) |
| Press-conference pages with **no** minutes entry at all | 1 (2024-11-07) |
| Meeting panels whose minutes cell says "See end of minutes of <another meeting>" | 8 (the intermeeting actions, e.g. 2019-10-11 and 2020-03-03 — no separate set of minutes exists, so no row) |
| Meeting panels with a minutes link and a stated release date | 135 (88 on the yearly pages 2010-2020, 47 on the 2021-2026 calendar) |
| BLS schedule pages read | 18 (2010-2027) |
| BLS table rows read (rows with three cells) | 3,233 |
| CPI + PPI + Employment Situation rows kept | 681 — 645 from the live pages, 36 from the earlier 2025 capture (3 name a release the current page moved, 3 a release it dropped, the rest repeat a row the current page still lists) |
| "Employment Situation of Veterans" rows ignored (a different report) | 19 |
| Other BLS rows ignored (other releases, holidays) | 2,533 |
| Rows written | 1,028 — `FOMC_STATEMENT` 149, `FOMC_PRESS_CONFERENCE` 96, `FOMC_MINUTES` 135, `CPI` 216, `NFP` 216, `PPI` 216 |
| … by status | `released` 970, `rescheduled` 6, `scheduled` 49, `cancelled` 3 |
| Rows whose hour no source stated (`time_known = false`) | 198 — 58 FOMC statements (48 from 2010-2015, 10 announced-but-unreleased meetings), **96 press conferences**, 44 minutes releases |
| Dataset | 1,028 rows, content hash `2d5bcdb38e35fc70…`, 264 distinct snapshot hashes cited |

Five parsing rules worth spelling out:

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
   neighbours, and every one of the 681 kept rows states a time. A row with no time would be kept
   with `time_known = false` (none occurs).
4. **No page states the hour of a press conference**, so none is claimed: the row is the meeting's
   statement day at 00:00 local with `time_known = false`. The hour the Fed held the conference
   appears only in the transcript PDF (above), 2:00/2:15/2:30 p.m. depending on the era — three
   different "usual" hours is exactly why "usual" is not stored.
5. **The minutes are dated by their release, and its hour from the press-conference page.** The
   panel states the day; the press-conference page of the same meeting states the day *and* the
   hour from 2012 on. Where both state a day they must agree (`_minutes_event` refuses otherwise);
   where the press-conference page states none, the row keeps the day and `time_known = false`.
   The minutes page is never cited: it states no release instant.

## Coverage table (events found vs the count the source states)

Expected counts: FOMC 8 scheduled meetings a year (each with a press conference and, later, a set
of minutes — the Fed's calendar states one of each per meeting); CPI 12, PPI 12, NFP 12 (one a
month). `PPI` and `FOMC_MINUTES` count by **release** day, which is why a December meeting's
minutes are counted in January.

| Year | FOMC | PC | Minutes | CPI | NFP | PPI | Notes |
|---|---|---|---|---|---|---|---|
| 2010 | 9 | — | 7 | 12 | 12 | 12 | 8 meetings + the 2010-05-09 conference-call statement; Bernanke's press conferences start in 2011; December's minutes released 2011-01-04 |
| 2011 | 8 | 3 | 8 | 12 | 12 | 12 | the first press conferences (April, June, November) |
| 2012 | 8 | 5 | 8 | 12 | 12 | 12 | + the January and December conferences |
| 2013 | 8 | 4 | 8 | 12 | 12 | 12 | October 2013 shutdown: the schedule states only the final (moved) dates |
| 2014 | 8 | 4 | 8 | 12 | 12 | 12 | |
| 2015 | 8 | 4 | 8 | 12 | 12 | 12 | |
| 2016 | 8 | 4 | 8 | 12 | 12 | 12 | the Fed starts stating the statement release hour |
| 2017 | 8 | 4 | 8 | 12 | 12 | 12 | |
| 2018 | 8 | 4 | 8 | 12 | 12 | 12 | |
| 2019 | 9 | 8 | 8 | 12 | 12 | 12 | + the 2019-10-11 unscheduled statement; a press conference at every meeting |
| 2020 | 10 | 9 | 8 | 12 | 12 | 12 | 7 meetings + 2020-03-03, -03-15, -03-23; the March 17-18 meeting was cancelled; the two emergency actions held conferences |
| 2021 | 8 | 8 | 8 | 12 | 12 | 12 | |
| 2022 | 8 | 8 | 8 | 12 | 12 | 12 | |
| 2023 | 8 | 8 | 8 | 12 | 12 | 12 | |
| 2024 | 8 | 8 | 8 | 12 | 12 | 12 | the 2024-11-07 conference page omits its minutes entry, so that row states the day only |
| 2025 | 8 | 8 | 9 | 12 | 12 | 11 | shutdown: 2 rescheduled + 1 cancelled each for CPI and NFP; PPI 1 rescheduled + 1 cancelled and one release moved onto the 2026 page (below) |
| 2026 | 8 | 7 | 7 | 12 | 12 | 13 | 7 released, 2026-12-09 still `scheduled` (no conference or minutes linked yet); the 2025 PPI release the shutdown moved landed here on 2026-01-14 |
| 2027 | 8 | — | — | 12 | 12 | 12 | all `scheduled`; the Fed links no press conference or minutes for a meeting it has not held |
| 2028 | 1 | — | — | — | — | — | the 2028-01-26 meeting the 2027 calendar announces |

A year is "short" only where the source says so. `FOMC_PRESS_CONFERENCE` is 3-5 a year in
2011-2012 and 4 a year in 2013-2018 because the Fed held press conferences only after *some*
meetings then (the "projection meetings"); from 2019 every meeting has one. 2026 and 2027 are
short because the meetings have not happened: the Fed publishes a press-conference page, and links
the minutes, only after the meeting.

### Gaps and moved releases

`coverage(store)` reports three gaps, all three from the autumn 2025 shutdown:

| Type | Gap | Why |
|---|---|---|
| `NFP` | 2025-10-01 → 2025-11-01 | the "Employment Situation for September 2025" moved to 2025-11-20, so October 2025 holds no NFP event |
| `PPI` | 2025-10-01 → 2025-11-01 | the "Producer Price Index for September 2025" moved to 2025-11-25, so October 2025 holds no PPI event |
| `PPI` | 2025-12-01 → 2026-01-01 | the "Producer Price Index for November 2025" moved from 2025-12-11 to 2026-01-14, so December 2025 holds no PPI event |

A `news_restriction` on NFP or PPI cannot be evaluated for those months. Everything else is
covered; a `cancelled` row still marks its month as covered, because the calendar *did* say
something about it. `FOMC_STATEMENT`, `FOMC_PRESS_CONFERENCE`, `FOMC_MINUTES` and `CPI` have no
gap at all.

The 2025 releases the shutdown moved or cancelled (the earlier capture of 2025-09-12 versus the
current page):

| Release | Was | Became | Status |
|---|---|---|---|
| Employment Situation for September 2025 | 2025-10-03 | 2025-11-20 | `rescheduled` |
| Consumer Price Index for September 2025 | 2025-10-15 | 2025-10-24 | `rescheduled` |
| Producer Price Index for September 2025 | 2025-10-16 | 2025-11-25 | `rescheduled` |
| Employment Situation for October 2025 | 2025-11-07 | — | `cancelled` |
| Consumer Price Index for October 2025 | 2025-11-13 | — | `cancelled` |
| Producer Price Index for October 2025 | 2025-11-14 | — | `cancelled` |
| Employment Situation for November 2025 | 2025-12-05 | 2025-12-16 | `rescheduled` |
| Consumer Price Index for November 2025 | 2025-12-10 | 2025-12-18 | `rescheduled` |
| Producer Price Index for November 2025 | 2025-12-11 | 2026-01-14 | `rescheduled` — onto the **2026** schedule page |

Both dates are kept: `scheduled_local` is the earlier one, `actual_publication_date` the one that
materialised (null for `cancelled`). Nothing is guessed — the earlier date comes from an official
snapshot of the same page.

The last line is why the BLS releases are matched **across the yearly pages**: a release is
identified by its reference period ("November 2025"), which carries its own year, so moving from
the 2025 page onto the 2026 page is one `rescheduled` row (`PPI-20251211`, actual 2026-01-14) and
not a `cancelled` row *plus* a second, released one for the same report.

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
- **No press-conference row states an hour** (all 96, `time_known = false`). The Fed's page for a
  meeting states the instant of every document *except* the press conference itself; the hour is
  in the transcript PDF only. So a rule that restricts trading around a press conference must
  widen to the whole local day — the pessimistic reading, and the only one the sources support.
- **44 minutes rows state a day but no hour**: 2010 and 2011 (no press-conference page states an
  hour before 2012, and 2010 had no press conference at all), the 2013-2018 meetings without a
  conference, and 2024-11-07 (whose conference page omits the minutes entry).
- **10 announced meetings state a date but no hour** (2026-12-09, the eight 2027 meetings and
  2028-01-26), and their dates are "tentative until confirmed at the meeting immediately preceding
  it". No press-conference or minutes row exists for them until the Fed links one.
- **A press conference is dated by the Fed's own file name, and its spelling is never rewritten.**
  The Fed is inconsistent: `fomcpresconf<YYYYMMDD>.htm` for most years, `fomcpressconf20260128.htm`
  for 2026-01-28, and the 2022 calendar links 2022-03-16 as an absolute URL. Each date exists under
  one spelling only — the other spelling is a 404 — so the loader keeps the file name the link uses
  and only fills in scheme and host.
- **Notation-vote statements are mostly excluded.** A `(notation vote)` panel is read only when
  its link is labelled exactly "Statement" (2020-03-23, an intermeeting policy action). The two
  "Statement on Longer-Run Goals and Monetary Policy Strategy" pages (2020-08-27, 2025-08-22) and
  the procedural press releases are not FOMC policy statements. If a firm's rule anchors on one of
  those, it needs its own source.
- **Two policy statements are in neither list:** the joint Treasury/Fed announcements (e.g.
  2023-03-12 on SVB) are not FOMC statements and do not appear on the pages read.
- **`available_at` is weaker than the truth** (above). Do not use this dataset as a signal.
- **One event per release.** The reference period a release covers ("for December 2009") is not a
  column: it is only the key that matches a release across two snapshots (and, for the minutes and
  press conferences, the key that matches a meeting's pages to it). A consumer that needs the
  period must read it from the source.
- The Fed's meeting statement date is taken from the **statement page**, not from the meeting
  range, whenever the statement exists (so 2020-03-02 released on 2020-03-03 is one event on
  03-03). For a meeting without a statement page, the statement day is the last day of the range.
- **`dataset_version` changed type.** `econ_events_v1` stores the dataset *name* in a `String`
  column; `econ_events_v2` stores the integer `2` in an `Int64` column, and a `version=1` rebuild
  stores `1`. The column was introduced as a row-version marker and is now one (nothing else
  changed: a v1 rebuild's rows equal the stored v1's in every other column).

## Rebuild

The raw snapshots are the source of truth. Re-fetching (only when the sources publish more) and
rebuilding:

```bash
# 1. fetch (idempotent: an existing file is never re-fetched or rewritten). It discovers the
#    statement pages *and* the press-conference pages from the Fed's own index pages.
uv run python -c "from pathlib import Path; from crucible.data.econ_events import fetch_raw; \
    fetch_raw(Path('D:/proyectos/databases/econ_events/raw'))"

# 2. build v2 into the store (refuses to overwrite an existing econ_events_v2)
uv run python -c "from pathlib import Path; from crucible.data.econ_events import build_econ_events; \
    r = build_econ_events(Path('D:/proyectos/databases/econ_events/raw'), \
    Path('D:/proyectos/crucible/data/processed')); print(r.rows, r.content_hash, r.events_by_type)"

# 2b. and, beside it, a v1 rebuild to show the v1 rows did not move (version=1)
uv run python -c "from pathlib import Path; from crucible.data.econ_events import build_econ_events; \
    build_econ_events(Path('D:/proyectos/databases/econ_events/raw'), \
    Path('D:/proyectos/crucible/data/processed'), version=1)"

# 3. the real-data checks (per-year table, the two March 2020 actions, the v1/v2 row identity)
CRUCIBLE_DATA_STORE=D:/proyectos/crucible/data/processed uv run pytest -m bench \
    tests/bench/test_econ_events_real.py -q
```

A re-fetch on a later date writes a new `<YYYYMMDD>_*` snapshot set beside the old one; the
build then refuses (`exactly one current BLS schedule for <year>`), so move the superseded
set out of the folder — or into an archive subfolder — before rebuilding.

`fetch_raw` discovers the statement and press-conference pages **from the Fed's own calendar and
historical pages**, so a year the Fed adds is picked up without a code change;
`FOMC_HISTORICAL_YEARS`, `BLS_SCHEDULE_YEARS` and `ARCHIVED_SCHEDULES` (the archived earlier
readings) are the only lists in the code. Keep the raw folder: a rebuild without it is impossible
(the dataset cites the SHA-256 of each page it was read from).
