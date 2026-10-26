# ADR-0080: Register invariant I2 — PnL reconciliation at every mark

Status: accepted (2026-10-25)

## Context

`docs/INVARIANTS.md` listed I2 (`PnL_total = realized + unrealized − costs`) as "derived:
asserted from I1+I3+I4 components", and `accounting/invariants.py` registered only I1, I3, I4
and I12. The 2026-10 audit found the claim false in three ways:

- **It is not derivable.** I1 checks that equity equals cash plus marked positions, I3 that cash
  equals the ledger's deltas, I4 that quantities equal the signed fills. All three compare the
  snapshot with a fold of the *same* ledger, so a wrong but internally consistent posting passes
  all of them. The audit's critical defect — a futures delisting that credited the whole notional
  (equity +9,040, realized +2,000) — passed I1, I3 and I4.
- **Dividends, borrow and financing break the stated identity.** They move cash (and equity) with
  no realized or unrealized PnL, so equity ≠ initial + realized + unrealized − fees at any mark
  after a dividend.
- **Multi-currency fees broke it as well** (fees were summed across currencies; fixed separately
  in H5).

## Decision

Register `I2.pnl_reconciliation` and check it at every mark, against a fresh fold:

```
equity(base) = initial_cash + realized + unrealized − fees + other_income
```

- Every term is derived from the fold and converted at the mark's mid rate: `realized` and
  `unrealized` from `PositionState` (multiplier-scaled for futures), `fees` from
  `PortfolioBalances.fees_by_currency`, `other_income` from the new
  `PortfolioBalances.income_by_currency`.
- `other_income` accumulates exactly the transaction types that move cash without moving PnL:
  `DIVIDEND`, `BORROW`, `FINANCING` (signed amounts, per currency). A `DELISTING` liquidation is
  **not** income: it is position-bearing, so its realized part is already in `realized`.
- **Tolerance 1e-9 relative.** Cash and equity are exact Decimals; the average-cost split divides
  (`PositionState.apply`), so `realized + unrealized` can carry a last-digit residue. An exact
  comparison would refuse valid runs on that dust, which is a worse failure than a 1e-9 window: a
  posting error is orders of magnitude larger (the audit's was 8,040 on 102,000).

## Alternatives considered

- **Keep I2 "derived".** Rejected: the claim was false and the missing check let a critical
  misposting through three invariants that all looked green.
- **Exact equality.** Rejected for the Decimal-division residue above; the tolerance is stated in
  the code, the invariant table and this ADR rather than hidden.
- **Check only at the end of the run.** Rejected: the audit needed the mark at which the wrong
  posting happened; a final check would pass after a later compensating flow, and every mark
  already has the context it needs.
- **Track income as a single base-currency number in the fold.** Rejected: the fold is
  currency-generic everywhere else, and converting at posting time would need the FX rate in the
  transaction; converting at the mark's mid matches how fees and equity are already valued.

## Consequences

- `PortfolioBalances` gains `income_by_currency` (additive; defaulted, so existing constructors
  keep working), and the fold tracks it incrementally and in `_fold_full` identically.
- A wrong dividend sign, a missed borrow accrual, a fee booked in the wrong currency or a
  mispriced liquidation now raises `InvariantViolation` at the next mark.
- The identity is documented in `docs/INVARIANTS.md`, `docs/modules/accounting.md` and
  `docs/TIMING.md`; `tests/unit/test_ledger.py` covers a violating posting, and the dividend,
  borrow/financing, futures, settlement-lag, checkpoint and multi-currency suites exercise the
  passing case.
