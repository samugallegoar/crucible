# ADR-0087: CME trade date from the Chicago wall clock, not a fixed UTC shift

Status: accepted (2026-11-15). It corrects the trade-date rule of ADR-0086 (which stays in force
otherwise) and changes the output of the continuous builder, so the datasets move from `v1` to `v2`.
The change is a correction of a measured defect, with no new modelling choice.

## Context

ADR-0086 defined the Globex trade date as `date(open + 2h)` in UTC and noted that the CME-calendar
milestone "must agree with it". Checking the rule against the 16.4 years of ES bars (`es_1m_cont_v1`,
5,745,344 bars) and the `CMES` calendar of `exchange_calendars` found it does not:

- **49 trade dates are Saturdays**, from 2012-12-01 to 2015-03-07, each with 13-15 bars. They are the
  last minutes of a Friday: in that period the equity-index session ended at **16:15** Chicago, not
  16:00, which is 22:15 UTC in winter. A bar opening at 22:00-22:14 UTC plus 2 h is after midnight
  UTC, so the rule sent it to Saturday. (Holiday stubs such as 2013-01-01 are the same defect on the
  evening before.) ADR-0086 assumed the session closed at 16:00 and the shift was exact "in both
  standard and daylight time"; the 15 minutes of the older schedule break that claim.
- A fixed UTC shift can only be right in one of the two UTC offsets: the trade date changes at 17:00
  Chicago, which is 22:00 UTC in summer and 23:00 UTC in winter. `+2 h` is exact in summer; in winter
  it puts the date boundary at 22:00 UTC, one hour before the real one, and works only because the
  maintenance break is empty.
- `CMES` in `exchange_calendars` models a 24-hour session (open and close both 23:00 UTC in winter, no
  maintenance break) and none of the half-day schedule seen in the data. Against the `+2 h` dates it
  has no session on 59 days where the data has bars (the Saturday and holiday-eve stubs above) and a
  session on 12 days where the data has none (holidays such as 2013-01-21 and 2013-07-04). It is not a
  source of truth for minute-level coverage; the integrity report of this milestone works from the
  observed minutes and uses `CMES` only for session dates.

## Decision

1. **The trade date of a bar is the Chicago date of `open wall clock + 7 h`**: convert the bar's
   open (UTC) to `America/Chicago`, drop the zone, add 7 hours, take the date. 17:00 + 7 h is midnight,
   so a bar opening at or after 17:00 Chicago belongs to the next date, in every season and across both
   daylight-saving transitions, because the arithmetic is on the wall clock. It lives in
   `crucible/data/calendars.py` (`cme_trade_date_expr`), the one place timezone logic is allowed
   (ADR-0004); `continuous.trade_date_expr` calls it.
2. **The continuous datasets are versioned `v2`** (`{root}_1m_cont_v2`, `_cont_ratio_v2`,
   `_rolls_v2`; `continuous.DATASET_VERSION`). The `v1` datasets are superseded and kept only so an
   artifact that already references one stays reproducible. They must not be used for new work.
3. The roll rule, parameters and adjustment of ADR-0086 are unchanged.

## Effect on the real data

Rebuilding ES, NQ, YM, RTY and NKD with the new rule leaves the roll *sequence* of ES, NQ, YM and RTY
identical (same contracts, same `volume` reason) and moves a few effective trade dates: ES 5, NQ 4,
YM 4, RTY 0, NKD 4 (rolls whose first or last session was one of the stubs). NKD's reasons move from 58
backstop + 8 volume to 62 backstop + 4 volume: a Saturday stub was counting as the held contract's
last session. The 49 Saturday stubs are now part of their Friday.

## Alternatives considered

- **Keep `+2 h` and drop the stubs.** Dropping real bars is data loss decided by a heuristic;
  rejected.
- **Use `CMES` sessions for the assignment.** Its session is a 24 h block with the wrong boundary in
  winter and no early closes; it would trade one approximation for another. Rejected as the
  assignment rule (kept as a cross-check of session dates).
- **Shift by 3 h UTC in winter and 2 h in summer by month.** This is the Chicago rule written
  by hand, and wrong on the transition weekends. Rejected.

## Consequences

- `docs/data/glbx-futures-1m.md`, `docs/modules/data.md` and the CHANGELOG say `v2` and the Chicago
  rule; ADR-0086 carries a pointer to this one.
- A strategy that keyed on `trade_date` from `v1` metadata sees different dates for the affected
  rolls; `v1` is flagged superseded, not deleted.
- Compatibility class (`docs/COMPATIBILITY.md` §6): a behaviour change of a data builder, with the
  dataset id bumped; no golden fixture changed (none uses these datasets).
