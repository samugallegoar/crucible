# CME Globex session calendar (equity-index futures)

Not a dataset in `data/processed/`: a versioned table in code, `crucible/data/cme_session_table.py`,
read by `crucible/data/cme_sessions.py` (ADR-0091). Version `cme-equity-sessions-1`.

## Source

Every entry cites a document in the table's `SOURCES`, with URL, archive URL and SHA-256. The
documents were retrieved on 2026-11-17. CME refuses automated access, so they were read from these
copies:

- **Regimes**:
  - the CME education sheet on equity trading hours;
  - SER-6465 (2012-11-14);
  - SER-6554R (2013-02-21);
  - the CME Globex notice of 2015-09-07;
  - CME Submission 20-244 (CFTC filing, 2021-06-11).
- **Holidays 2010-2022**: CME's annual holiday-calendar zips
  (`tools-information/holiday-calendar/files/<year>-holiday-calendars.zip`). For 2012 and 2022,
  the individual files. One record per PDF or XLS.
- **2023 New Year**: `2023-new-years-holiday-schedule.xls`.
- **2023-09 to 2025-09**: Wayback captures of `services/trading-hours-by-product` (ES only).
- **2025-11-17 to 2027-12-31**: the live service, all five products, captured 2026-11-17T22:10:06Z.
- **Special closures**:
  - CME press releases for Hurricane Sandy (2012-10-28/29/30);
  - SER-8289 (2018-12-05);
  - the CME press release of 2024-12-30 (2025-01-09).

## Schema

Every time is `America/Chicago` wall clock, converted to UTC int64 ns at the boundary.

- `SessionRegime`: roots, first and last trade date, evening open, close, daily breaks.
- `SessionOverride`: trade date, roots, open, close and halts.
- `NoTradeDate`, `UnsourcedWindow`, `UnscheduledEvent`, `ScheduleSource`.

## Known issues

- **Unsourced holidays.** These are flagged as unverified sessions:
  - 2023: MLK, Presidents Day, Good Friday, Memorial Day, Juneteenth, July 4 and Thanksgiving;
  - MLK 2024;
  - NKD on the 2023-2025 dates taken from the ES-only captures. NKD traded past the U.S. early
    closes of 2024-07-03 and 2025-07-03.
- **NKD before 2012-11-19 is not covered.** The 2010 holiday PDFs carry NKD-specific exceptions.
- **The 2025-11-28 outage** is an unscheduled event. The scheduled session is kept.
- **Saturday events in the live service.** On 2026-06-20, 2026-07-04 and 2027-06-19 the service
  lists "open 05:00 / closed 17:00". These are a feed artefact and are ignored.
- **MLK 2013 draft vs published PDF.** The draft gives a 15:15 close, the published PDF 16:15.
  The PDF is used.

## Validation against the raw bars (`schedule_report`, 2026-11-17)

- **Off-schedule bars:**

  | Root | Off-schedule bars |
  |---|---|
  | ES | 313 |
  | NQ | 128 |
  | YM | 122 |
  | RTY | 118 |
  | NKD | 6 |

  All of them sit in the minute after a close or end exactly at a reopen.
- **Data gaps in the Databento batch.** The schedule exposes gaps that are not closures:
  - the nine holidays from Thanksgiving 2012 to Presidents Day 2014 have no bars before their
    10:30 halt;
  - ES has no bars at all on 2014-06-12/13, 2014-09-23..25 and 2014-12-31.

## Re-run the check

```python
import polars as pl
from crucible.data.cme_session_table import cme_session_table
from crucible.data.cme_sessions import SessionCalendar, schedule_report

cal = SessionCalendar(cme_session_table(), "ES")
ends = pl.read_parquet("data/processed/es_1m_raw/data.parquet", columns=["event_time"])
ends = ends["event_time"].unique().sort().to_numpy()
print(schedule_report(cal, ends[ends - 60_000_000_000 >= cal.session(cal.first).open_ns]))
```

To add a year or correct an entry:

1. Transcribe it from a document.
2. Add the document to the table's sources, with its SHA-256.
3. Bump `TABLE_VERSION`.
