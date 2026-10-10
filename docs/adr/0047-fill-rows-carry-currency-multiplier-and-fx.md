# ADR-0047: Fill rows carry currency, multiplier and FX; attribution values them

- **Status**: accepted
- **Date**: 2026-09-25

## Context

ADR-0034 confirmed and deferred a gap in `per_strategy_pnl_deltas`. It derived
each fill's cash flow as `qty * price - commission` from fill rows that carried
neither currency nor futures multiplier, so a EUR fill was left unconverted and
a futures fill was unscaled.

## Decision

1. Each fill row gains `currency` (the symbol's currency), `multiplier`
   (Decimal text; `"1"` for non-futures) and `fx_to_base` (Decimal text; the
   mid rate at the fill's timestamp read through the PIT accessor, `"1"` in base
   currency). The runner's `fills.parquet` schema includes them.
2. Attribution values a fill as
   `(±qty * price * multiplier - commission) * fx_to_base`. Fill rows without
   `multiplier` or `fx_to_base` are refused with a message naming the missing
   columns.
3. What "realized" means for futures here: the full notional times the
   multiplier, so a round trip sums to `(exit - entry) * qty * multiplier`, the
   realized PnL, and equals the ledger's total. The per-period timing differs
   from the ledger: the ledger books an opening futures fill at zero and settles
   marks as untagged variation margin (ADR-0033), so reading its booked amounts
   would attribute almost nothing to a futures strategy.
4. FX PnL is not separated from price PnL (already a known gap, the original requirements 4.10); each
   fill is valued at its own fill-time mid rate.

## Alternatives considered

- **Refuse attribution for FX and futures runs.** No schema change, but
  multi-currency and futures multi-strategy runs would get no attribution.
- **Add the columns only for such runs.** Avoids touching the golden hash, but
  the fill schema would vary by run type.
- **Read the ledger's booked amounts.** Correct for FX, but loses futures
  variation margin, as above.

## Consequences

- `fills.parquet` gained three String columns, so its golden hash was
  regenerated under the guarded procedure: only that hash moved, every other
  artifact was byte-identical (recorded in `tests/golden/fixtures/README.md`).
- Fill rows from runs or checkpoints written before this change cannot be
  attributed; the refusal says to re-run.
- Attribution stays realized-cash-flow-only (ADR-0030); unrealized PnL is not
  attributed.
