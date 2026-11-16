# ADR-0088: Minute-level integrity report: observed minutes, gaps are findings, contract violations are errors

Status: accepted (2026-11-15). A new read-only command with no effect on any dataset, backtest or
golden fixture. The one choice that someone might question (gaps do not fail the report) is the
conservative one: the tool states what it sees and the caller decides.

## Context

`crucible data check` (`crucible/data/quality.py`) runs a battery that either passes or raises. Its
`calendar_coverage` check expects one bar per session close, which is a daily-bar notion: for the
28 million Databento minute bars of ADR-0085 it is skipped, so nothing said how complete those
datasets are. Fathom's work order (C2) asks for a minute-level integrity report. Two facts of the real
data shape it:

- **Databento's OHLCV-1m omits a minute with no trade.** A minute with no bar is therefore a minute
  nobody traded in, *or* a minute the source lost; the file cannot tell them apart. On the five
  continuous datasets the share of minutes absent inside a session's own span runs from 1.2% (ES) to
  37% (NKD, a thin contract), which is liquidity, not corruption.
- **`CMES` in `exchange_calendars` is not a minute grid** (a 24 h block, no maintenance break, no
  early closes; ADR-0087), so "expected minutes = calendar minutes" would flag the daily break as a
  hole and miss half days.

## Decision

1. **Observed minutes only.** `crucible data integrity` (`crucible.data.integrity.integrity_report`,
   MCP tool `crucible_data_integrity`) reads a bar dataset and reports, per symbol and per session
   (the Globex trade date of ADR-0087 by default, or the UTC day): bars, minutes absent inside the
   session's own first-to-last span, the largest hole, sessions under half the symbol's median bars
   (half days, holiday stubs), sessions dated on a weekend, and zero-volume bars.
2. **Two classes, one exit code.** *Errors* are rows that break the data contract: duplicate
   `(symbol, event_time)`, nulls, non-positive prices, an OHLC row outside its own bounds,
   `available_at < event_time`, negative volume. Any error sets `ok: false` and exit code 1; the
   report is still printed. *Findings* (gaps, short sessions, weekend sessions, zero volume, calendar
   differences) never change `ok` or the exit code: a halt, an early close and a thin contract are
   real market states, and a threshold would be a guess presented as a rule.
3. **A calendar is optional and compares dates only.** `--calendar CMES` lists the session dates
   present in the data and absent from the calendar, and the reverse, over the data's own range.
4. **The report never repairs, fills or drops anything** and refuses an empty dataset.

## Results on the real data (`*_1m_cont_v2`, `docs/data/glbx-futures-1m.md`)

No error in any of the five datasets. Findings: ES 72,300 absent minutes in 3,089 of 4,233 sessions;
NQ 245,626; YM 284,659; RTY 213,072; NKD 2,114,840 (absent share of the span: ES 1.2%, NQ 4.2%, YM
4.9%, RTY 6.4%, NKD 36.7%). The largest hole is 645 minutes in ES, NQ, YM and RTY and 660 in NKD; in
ES it is Thanksgiving Friday 2025-11-28 (bars stop at 17:01 Chicago Thursday and resume 07:31). Short
sessions: ES 10, NQ 14, YM 15, RTY 33, NKD 316 (half days such as 2012-04-06 and 2025-11-28, the
partial last session 2026-11-11, and the first sessions of RTY's data in 2017-07). One weekend-dated session in
ES, NQ, YM and NKD: **2018-08-05, one bar opening 16:59 Chicago on the Sunday**, a minute before the
reopen (a pre-open trade; kept, not dropped). The 2020-03 limit-down halts show as the worst gaps.

## Alternatives considered

- **Fail on a gap above a threshold.** Rejected: the right threshold differs per contract (ES 1.2% vs
  NKD 37% absent), and failing would force an override flag that everyone sets.
- **Compare against a calendar minute grid.** Rejected for the reasons in Context; the grid would
  have to be written by hand per exchange and per era (the 16:15 close of 2012-2015).
- **Insert zero-volume bars for absent minutes.** Rejected: it invents data and changes row counts and
  hashes of datasets that an artifact already references.
- **Extend `calendar_coverage`.** Rejected: that check is a raise-or-pass gate run at write time on
  every dataset; this one is a report on an existing dataset.

## Consequences

- `docs/modules/data.md`, `docs/modules/cli.md`, `docs/modules/mcp_server.md`, `docs/USAGE.md`, the
  generated `docs/INVENTORY.md` and the CHANGELOG describe the command.
- A caller that wants a hard rule reads the report and applies its own (for example, refuse a window
  whose session has a hole above N minutes); Crucible does not pick N.
- Compatibility class (`docs/COMPATIBILITY.md` §6): a new command and MCP tool, no change to an
  existing contract. The JSON report is versioned by the envelope of `cli/machine`.
