# ADR-0092: Globex trade dates come from the session calendar (continuous datasets v3)

Status: accepted (2026-11-17). Supersedes the trade-date rule of ADR-0087. The continuous-series
roll rule (ADR-0086) and its parameters do not change; only the trade date each bar belongs to
does, so the continuous datasets get a new version (`v3`). Records the ADR-0091 finding.

## Context

ADR-0087 dated a bar by one rule: the Chicago date of `bar open + 7 h`, so the trade date
changes at 17:00 Chicago. The CME session calendar (ADR-0091), checked against the raw bars,
shows three cases where the rule is wrong:

1. **Before trade date 2012-11-19**, the equity session opened at 15:30 Chicago, not 17:00. The
   bars from 15:30 to 17:00 belong to the next trade date, but the rule gave them the current one.
   With the holiday cases below, 9,700 ES bars were re-dated in 2010 (from June), 17,857
   in 2011 and 15,507 in 2012.
2. **Holiday Mondays and Thanksgiving.** CME books the trading of a holiday Monday (MLK,
   Presidents, Memorial, Labor Day) and of Thanksgiving to the next trade date. The session opens
   Sunday (Wednesday) 17:00 and halts at noon, and its trades are dated Tuesday (Friday). The rule
   made each holiday a separate short session of its own: 87 false trade dates in ES from 2010 to
   2026, out of 4,233, and about 6,800 re-dated bars a year.
3. **A Friday booked to the following Monday.** In July 2014, 2015 and 2020, and on Juneteenth and
   July 3 in 2026, a Friday's trading belongs to Monday's trade date. The rule gave it the Friday,
   a date with no session.

The continuous series uses the trade date to decide the rolls, from the previous session's volume.
It also uses it for the effective date of a switch and for which bars each contract supplies.
The integrity report uses it for its per-session counts.

## Decision

1. **The calendar is the only source of the trade date.**
   - `cme_sessions.session_trade_dates` dates every bar. A bar inside a scheduled segment takes
     that session's trade date.
   - An off-schedule bar takes the trade date of the last session that opened at or before the
     bar's start. Such a bar is a print in the minute after a close, or the one ending at a
     reopen. Its date is never later than the bar, and the bar is flagged `on_schedule=False`, so
     execution never trades on it (ADR-0091, decision 7).
   - `calendars.cme_trade_date_expr` is removed. A rule known to be wrong is not left behind for
     a later caller.
2. **The continuous builder uses the calendar.** `build_continuous` uses the CME calendar of its
   root, or one passed in. It records `calendar=<table version>@<sha256 prefix>` in every
   manifest `source`, so the version that dated the series is pinned. `DATASET_VERSION` becomes
   `v3`, and `v2` is reported as superseded by `crucible data catalog`.
3. **Bars outside the calendar's coverage are refused, never dated by a guess.**
   - `build_continuous` refuses raw bars outside the calendar's coverage.
   - `build_continuous_datasets(trim_to_calendar=True)` (CLI `--trim-to-calendar`) drops them
     and records the count as `trimmed_rows=<n>` in the manifests.
   - Only NKD is affected: 314,040 raw bars from 2010-06 to 2012-11-16. Its pre-2012 schedule is
     not transcribed, because the 2010 holiday PDFs carry NKD-specific exceptions (ADR-0091,
     decision 5). `nkd_*_v3` therefore starts with contract NKDZ2012.
   - Transcribing those years would restore them, with a new `TABLE_VERSION` and `v4`.
4. **The integrity report's `cme` rule uses the calendar.**
   - The root is read from the symbols: `ESH2024` gives ES, `ES` gives ES.
   - A root the calendar does not cover is refused, with the message pointing to `--session utc`.
   - Bars outside coverage get no session. They are counted per symbol in `outside_calendar_bars`
     and left out of the session statistics.
5. **Bug fix in `assign_bars` (ADR-0091).**
   - **The bug:** it loaded sessions only up to the bars' date + 3 days. A session can open four
     days before its trade date (Monday's on the Thursday of a Friday holiday), so a lone bar
     there was left off schedule. It also did not load the session before the first bar, which an
     off-schedule print needs.
   - **The fix:** it now loads a week on both sides. A regression test pins it.
   - **No effect on figures:** the ADR-0091 findings were computed over whole datasets, where the
     window covered every session.

## Consequences (measured 2026-11-17 on the real store)

| Root | Bars | Sessions v2 → v3 | Re-dated bars | Rolls v2 → v3 | Roll dates changed | Oldest-data multiplier |
|---|---|---|---|---|---|---|
| ES | 5,745,346 | 4,233 → 4,146 | 123,953 | 66 → 66 | 0 | 1.0405 |
| NQ | 5,571,600 | 4,233 → 4,146 | 113,915 | 66 → 66 | 0 | 1.1915 |
| YM | 5,537,936 | 4,238 → 4,151 | 106,920 | 66 → 66 | 0 | 0.9687 |
| RTY | 3,096,715 | 2,415 → 2,363 | 52,404 | 37 → 37 | 0 | 1.1607 |
| NKD | 3,650,106 → 3,348,325 | 4,233 → 3,536 | 37,437 | 66 → 56 | 0 of the 56 | 0.9667 → 0.9712 |

- **What changed.** No roll moved. The volume rule never fell on a holiday stub, so the rolls, the
  price gaps and the adjustment factors of the four U.S. roots are identical to `v2`. What changed:
  - the trade date of the moved bars;
  - the session count;
  - a per-session statistic computed downstream;
  - a strategy that uses the trade date, such as a daily ledger or a "first bar of the session"
    rule.
- **NKD has ten fewer rolls**, the 2010-2012 ones.
  - The futures-simulator acceptance figures for NKD (ADR-0090) become 56 rolls, 31 executed after
    the first bar of the effective session, and a mean reference error of $77.23 per contract.
    On `v2` they were 66, 35 and $67.80.
  - The other four roots are unchanged.
- **2023 is barely affected.** Its holidays are unsourced (ADR-0091), so their sessions follow the
  regime, which gives a holiday Monday its own trade date like the old rule did. Sourcing them
  later will re-date those bars.
- **The integrity report shows no weekend sessions.** On `es_1m_cont_v3` it gives 4,146 sessions,
  none on a weekend. On `nkd_1m_raw` it gives 6,009 sessions across 68 contracts, none on a
  weekend, with 314,040 bars outside the calendar.
- **`v2` datasets stay in the store until deleted by hand.** The catalog flags them superseded.
- **Compatibility.** No config field or artifact schema changes, and no golden fixture reads these
  datasets. A run that names a `*_v2` dataset still reads it; a run that wants the correct dates
  names `*_v3`.

## Alternatives considered

- **Keep the 17:00 rule with a 15:30 branch before 2012-11-19.** It would still create the
  holiday stubs and the Friday-to-Monday errors. A second copy of the schedule as a rule is what
  ADR-0091 exists to avoid. Rejected.
- **Date out-of-coverage bars with the old rule.** That uses a rule known to be wrong on exactly
  the days the calendar would correct. Rejected for the same reason.
- **Trim NKD silently.** Rejected because dropping data must be asked for and counted.
- **Drop off-schedule bars from the continuous series.** They are real prints (the minute after a
  close). The series keeps every raw bar of the held contract, and execution refuses them through
  `on_schedule`. Rejected.
