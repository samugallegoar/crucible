# ADR-0102: Futures cross-run metrics and descriptive daily P&L correlation against the artifact pool

- **Status**: accepted
- **Date**: 2026-11-19

## Context

C5c is the last of the three C5 stages (ADR-0100, ADR-0101). The owner asked it to report:

- dollar performance, drawdown, trades, turnover and window stability;
- descriptive daily P&L correlations against the artifact pool.

The correlations come with three conditions:

- the execution configurations must be compatible;
- there must be enough overlapping trade dates;
- a missing observation is never treated as zero P&L.

The statistical boundary is unchanged. C5c reports no Sharpe, IC, PSR, DSR, p-values, confidence
intervals or statistical edge claims. A correlation is reported as a descriptive number of the
overlap, with null intervals and no significance attached. Pool members are never ranked by it.
C6 is the first stage that may add inference.

## Decision

1. **Members.** A comparison has a *target* and a *pool*. Two kinds of artifact can be either one:
   - a sealed futures run (`FUT-`, ADR-0095), whose series is the daily ledger;
   - a walk-forward (`WFA-`, ADR-0101), whose series is its concatenated OOS series (`oos_daily`).
     Its training runs are never members by this route; they enter the pool only as ordinary
     `FUT-` runs.

   The pool is every such artifact under the artifacts root, except the target and the walk-forward's
   own runs. A run whose seal does not verify is listed as `unverified` with no value; it is never
   dropped silently.
2. **Daily P&L.** A member's daily P&L on a trade date is its marked P&L for that date:
   `closing_equity_usd − opening_equity_usd` for a run, and `net_pnl_usd` for a walk-forward.
   - A trade date absent from a member's series is **missing**, not zero.
   - A walk-forward's flat fold contributes real zero rows. They are zeros because being flat was a
     decision.
3. **Per-member metrics** (descriptive, `ci_low`/`ci_high` null, all in USD unless stated):
   - P&L, under two keys with distinct meanings:
     - `marked_pnl_usd`, the sum of daily marked P&L (final closing equity minus capital);
     - `realized_pnl_usd`, the run's own `net_pnl_usd` (final balance minus capital), null for a
       walk-forward.

     The run's key `net_pnl_usd` is never reused with another meaning;
   - total costs;
   - maximum closing drawdown, peak to trough on the daily closing equity;
   - maximum intraday drawdown, from marks, for runs;
   - trades: position episodes from flat to non-flat and back to flat, counting a still-open
     episode;
   - fills;
   - turnover: the sum of |Δposition| in contracts, in total and per trade date;
   - trade dates, and days in market.

   **Window stability** gives each calendar month's net P&L (by trade date) and the counts of
   positive, negative and flat months. A walk-forward also gives its per-fold OOS P&L. These are
   counts and lists only; there is no dispersion statistic and no test.
4. **Compatibility.** Two members are compatible when their *comparison key* is equal. The key is:
   - `simulator_version`;
   - `fidelity` (resolution, cost_detail, table_version);
   - the execution section (fill timing, roll execution, strictness, brackets policy);
   - the session section (flatten rules, entry window, unverified-session policy);
   - the signal input (raw or ratio-adjusted).

   Root, contract count, cost amounts, strategy, window, family and capital are **not** part of the
   key. A correlation of USD daily P&L does not depend on scale, and cross-asset pools are the
   point. An incompatible pair gets status `incompatible`, lists the differing key paths, and has a
   null value.
5. **Correlation.**
   - It is Pearson's correlation of the two daily P&L series over the **intersection** of their
     trade dates (an inner join). Nothing is filled, so a date missing from either series is
     excluded.
   - With fewer overlapping dates than `min_overlap_trade_dates` (default 20, never below 10) the
     status is `insufficient_overlap` and the value is null.
   - If either series is constant on the overlap, the status is `constant_series` and the value is
     null.
   - Otherwise the status is `ok`. The value is reported with the overlap's size, first date and
     last date, `assessment: "descriptive"` and null intervals.
6. **Outputs** (`CMP-<16 hex>`, a hash of the target id, the sorted ids of the verified pool and the
   options).
   - `cross_run.json` (`schema_version` 1) goes under `artifacts_root / CMP-…`, outside every sealed
     run. It holds:
     - `target` (metrics, window stability);
     - `pool`, sorted by id and never by correlation, where each member has its kind, status,
       overlap, correlation, metrics and differing keys;
     - `summary`, with the counts per status and `max_abs_correlation` (the descriptive maximum with
       its member id, or null);
     - `verdict`, which is `not_assessed`.
   - Entry points: `crucible futures compare --target ID [--home|--artifacts] [--min-overlap N]
     [--json]`, the MCP tool `crucible_futures_compare` and `crucible schema --kind
     futures-compare`.

## Alternatives considered

- **Outer join with zero-filled missing dates.** The owner ruled it out. It invents flat days and
  biases the correlation towards zero.
- **Reindexing to the union of dates and forward-filling equity.** This is the same invention, in
  equity terms. Rejected.
- **Spearman or a shrunk correlation, or a p-value on it.** These are inference choices that belong
  to C6. Rejected.
- **Requiring the same root.** That would forbid the cross-asset comparisons the pool exists for.
  Rejected; scale-free daily USD P&L is comparable across roots under the same execution rules.
- **Sorting the pool by correlation.** That is a ranking by a statistic. Rejected.

## Consequences

- **Fathom can check how close a new candidate is to what it already has.** It does this in dollars
  and on overlapping days only, without implying significance.
- **The comparison key is conservative.** Two runs that differ only in fill timing are not
  correlated. Loosening the key is a later decision.
