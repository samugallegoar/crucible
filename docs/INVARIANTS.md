# Invariants

Identities the engine must hold at every mark. Violations raise
`InvariantViolation` — never a warning. Mirrors `crucible/core/invariants.py`
and the inline enforcement sites named below; each row must be **enforced in
code** and **exercised by a test**, and this table tracks that honestly.

Two enforcement styles, both code (never convention):
- **registry**: registered in `crucible.core.invariants` and re-checked from
  the ledger fold at every mark (`crucible.accounting.invariants.check_mark`; the fold is
  incremental since ADR-0054, with `_fold_full` as the test oracle).
- **inline**: raised at the single code path where the violation could occur.

| # | Identity | Tolerance | Enforced | Tested |
|---|---|---|---|---|
| I1 | `Equity(base) = Σ_ccy FX(ccy→base)·Cash(ccy) + Σ_i Value_i·FX(symbol_i's ccy→base)` where `Value_i = Qty_i·Mark_i` for an equity or `(Mark_i - AvgCost_i)·Qty_i·Multiplier_i` for a futures symbol (multi-currency, ADR-0009/0025; futures, ADR-0033 — a futures position contributes only unsettled variation margin, never the full notional) | exact (Decimal) | registry `I1.equity_identity` | `tests/unit/test_ledger.py`, `tests/unit/test_accounting_fx.py`, `tests/integration/test_multi_currency_accounting.py`, `tests/integration/test_futures.py`, every mark of every engine test |
| I2 | `Equity(base) = InitialCash + PnL_realized + PnL_unrealized − Fees_paid + OtherIncome` (dividends + borrow + financing, converted at the mark's mid) | exact (Decimal) up to the rounding of the weighted average cost at the Decimal context's 28 significant digits (cash and equity are exact; only the realized/unrealized split carries it, a residue around 1e-27 per position) | registry `I2.pnl_reconciliation` (every mark) | `tests/unit/test_ledger.py::test_equity_and_pnl_identity_at_mark`, `tests/property/test_pnl_reconciliation.py` (random fills, commissions, partial closes and reversals; ADR-0070) |
| I3 | `Cash(t) = Cash(t0) + Σ ledger cash deltas ≤ t` (per currency) | exact | registry `I3.cash_identity` | unit + `tests/property/test_ledger_invariants.py` |
| I4 | `Qty_i(t) = Σ signed fills_i ≤ t` | exact | registry `I4.qty_identity` | unit + property |
| I5 | ∀ fill: `low ≤ fill_price ≤ high` (bar data), where `[low, high]` is widened to the bar's bid/ask quotes when it carries them (`BarEvent.fill_range()`, ADR-0060) | exact | inline `execution/ladder.py::validate_fill_within_bar` | `tests/property/test_fills_within_bar.py` |
| I6 | aggregate fills per symbol-bar ≤ `max_bar_vol · bar_volume` (Level ≥ 3) | exact (Decimal budget) | inline `execution/ladder.py::LadderExecutionSimulator._apply` (shared bar budget + hard-cap assert) | `tests/property/test_participation_caps.py`, unit aggregate/partial tests |
| I7 | ∀ order state transition ∈ allowed set | exact | inline `orders/state.py::validate_transition` | unit + `tests/property/test_order_state_machine.py` |
| I8 | ∀ data access: `available_at ≤ as_of ≤ clock.now` | exact | inline `data/pit.py::StorePITAccessor._guard` + store-level `available_at` filter | `tests/property/test_pit_never_future.py`, lookahead harness |
| I9 | Event queue and feed: timestamps non-decreasing; ties by `seq` | exact | inline `core/queue.py::DeterministicEventQueue.pop` + `live/feed.py::PeekableFeed._check_order` + `core/clock.py` monotonicity | `tests/property/test_event_queue.py`, `tests/unit/test_events_clock.py`, `tests/unit/test_peekable_feed.py` |
| I10 | Margin: `Equity ≥ Maintenance` or liquidation event exists | exact | not enforced as a hard invariant — closest available is the opt-in `risk.limits.MarginCallLimit` (ADR-0031), which reacts to a breach at the next mark rather than guaranteeing one never occurs | `tests/integration/test_margin.py` (for the opt-in limit, not this invariant) |
| I11 | ∀ `Split` yielded by any `Splitter`: `train`, `validate`, `test` index ranges are pairwise disjoint | exact | inline `validation/splits.py::_assert_disjoint` | `tests/property/test_split_disjointness.py` |
| I12 | `AvailableCash(ccy, t) ≤ Cash(ccy, t)` (settlement lag, ADR-0028; only unsettled sale proceeds can create a gap) | exact | registry `I12.available_cash_bound` | `tests/unit/test_ledger_settlement_lag.py`, `tests/property/test_ledger_invariants.py::test_available_cash_never_exceeds_cash` |
| I13 | Resume equivalence: a run checkpointed at any session boundary and resumed equals the uninterrupted run | exact | `crucible/core/checkpoint.py` codec + `BacktestEngine.resume_from` verification (test-enforced identity, not a per-mark check) | `tests/integration/test_checkpoint_resume_equivalence.py`, `tests/integration/test_engine_checkpoint.py` |
| I14 | Live parity: the same strategy, config and data give identical orders, fills, ledger amounts and equity under `LiveRuntime` (simulated venue) and the backtest at Levels 1-2 (ledger `refs` that name an event id, e.g. dividends, differ because a lazy feed numbers events in yield order; a risk FLATTEN is refused under the venue backend) | exact | test-enforced identity, not a per-mark check | `tests/integration/test_live_parity.py`, `tests/integration/test_live_checkpoint_resume.py` |

Rules for this file:
- Adding an identity requires: a row here, an enforcement site in code
  (registry or a named inline function), and a test.
- Tolerances are stated here, not scattered in code as magic numbers. 
  is exact everywhere because cash math is Decimal end-to-end.
- "not enforced" next to an implemented feature that could violate the
  identity is a release blocker.
