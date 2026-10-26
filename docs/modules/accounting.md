# Module: accounting

## What exists

Everything derived from the append-only ledger. Detail sections follow.

- `ledger.py` — `TransactionRecord` (frozen; per-currency `amounts`, optional `settled_at`),
  `PositionState` (weighted-average cost, flips through zero), `PortfolioBalances` (the fold
  result), `InMemoryLedger` (append-only, time-ordered; `fold(up_to)` is the source of truth),
  `price_to_decimal` (the single float -> `Decimal` crossing).
- `snapshot.py` — `PortfolioSnapshot` (the read-only `PortfolioView` strategies see: base-currency
  equity, cash, available cash, notional, margin) and `SnapshotPosition`.
- `fx.py` — `convert_at_mid`, `convert_from_base_at_mid`, `convert_at_adverse`.
- `invariants.py` — `check_mark` and the registered identities I1, I3, I4, I12 (`MarkContext`).
- `interfaces.py` — the Protocols `Transaction`, `Position`, `PortfolioView`, `Ledger`.

## Responsibility
The append-only transaction ledger and everything derived from it: cash per
currency, positions (weighted average cost, flips through zero), realized
PnL, fees, equity at marks.

## Money boundary
Ledger amounts are `Decimal`. The single float→Decimal crossing is
`ledger.price_to_decimal` (repr-based, exact and deterministic); it happens
when a priced quantity becomes a cash movement, nowhere else.

## Implementations (ADR-0025)
- `ledger.py`: `TransactionRecord` (frozen; amounts/refs wrapped read-only),
  `PositionState.apply` (adds, reduces, flips), `InMemoryLedger` — appends
  must be time-ordered (raises otherwise); `fold(up_to)` is the source of
  truth for all state. The fold is incremental (ADR-0054): a running state
  applies only newly appended transactions, an earlier `up_to` or `None`
  replays everything (`_fold_full`, the test oracle), results are fresh
  copies, `restore` resets the cache, and `version` increases on every
  append or restore (the engine keys its snapshot reuse on it). Always multi-currency-generic: `amounts` is
  `Mapping[Currency, Decimal]` and the fold applies every currency's
  delta, so a currency-conversion transaction (two amounts, one negative
  one positive) needs no special-case fold logic. `TransactionRecord.
  settled_at` (ADR-0028) is `None` for "settles at
  `ts`"; `fold` accumulates it into a second balance, `PortfolioBalances.
  available_cash`, separately from `cash` — see "Settlement lag" below.
- `fx.py`: `convert_at_mid` (marking role — valuation only, identity when
  `ccy == base`) and `convert_at_adverse` (trading role — pays the ask
  when buying the quoted currency, receives the bid when selling;
  refuses a crossed quote). ADR-0009's rate convention, ADR-0025's
  implementation. `convert_from_base_at_mid` (ADR-0029): the
  mirror of `convert_at_mid`, converting a base-currency amount *into* a
  symbol's own currency (divides, since `mid_rates` stays keyed
  `ccy → base`) — used to size a target position from a weight expressed
  as a fraction of base equity.
- `snapshot.py`: `PortfolioSnapshot` — read-only view over a fold + marks
  + `symbol_currency`/`fx_mid_rates` +
  `futures_specs`; `equity` refuses when a held position has no mark (no
  invented prices) or when a held non-base currency has no FX mid rate
  available (same pessimism rule). Still refuses reporting in any
  currency other than the run's own base. A futures symbol contributes
  only its *unsettled* variation margin, `(mark - avg_cost) · qty ·
  multiplier`, never the full notional — see "Futures" below.
  `cash_total(base)` values every currency's wallet at the mid rate and is
  what `equity.parquet.cash` reports (2026-10 audit: the base wallet alone
  made `cash + positions ≠ equity` for a multi-currency book); `cash(ccy)`
  remains the single-currency wallet. `fees_paid` likewise converts each
  currency's fees at the mid (the ledger keeps `fees_by_currency`; adding the
  raw amounts mixed dollars and euros). A past fee is valued at the
  snapshot's rate, so a later FX move changes `fees_paid`; the cash impact at
  posting time is not tracked separately. A mid rate that is non-finite or
  `<= 0` is refused by `fx.convert_at_mid` rather than silently zeroing or
  inverting equity, and a zero balance needs no rate at all.
  `realized_pnl` scales each position's raw `PositionState.realized_pnl`
  by its futures multiplier (1 for an equity) *and* converts to base
  currency via `convert_at_mid` (a code-review fix, ADR-0034 — this
  property summed raw per-currency amounts with no FX conversion at all
  before that fix, unlike `equity()` a few lines above,
  which was always correct).
- `invariants.py`: `check_mark` runs I3 (cash), I4 (qty), I1 (equity,
  multi-currency) against a *fresh fold* at every mark;
  registered in the core registry.

## Extension points
New transaction types: extend `TransactionType`, add a fold rule, and ship a
hand-computed expected ledger test (never engine-derived — AGENTS.md §7).

## Dividends (ADR-0026)
Handled in `core/engine.py::BacktestEngine._handle_dividend`, not this
module — see `docs/modules/core.md`. Two `CorporateActionEvent`s from one
dataset row: ex-date resolves entitlement (`qty * per_share`; negative
qty/short pays with no special case) and schedules a pay-date event on
the engine's own queue; pay-date posts the already-resolved amount as a
`TransactionType.DIVIDEND` transaction, currency-resolved the same way a
fill is (ADR-0025's `_currency_of`). Ex-date entitlement is the position held
*before* the ex-date's session opens (`fold(up_to=min(ts - 1, session_open))`
with a calendar, `ts - 1` without, ADR-0046): a fill booked inside the ex-date
session neither earns nor owes the dividend (holder of record); a fill at
exactly the open counts. Event order is unchanged because `DELISTING` needs
the current day's mark (ADR-0010).

## Notional (ADR-0045)
`PortfolioView.notional(symbol, qty=None)` is the base-currency notional of
`abs(qty)` units (default: the held quantity) at the last mark:
`qty * mark * multiplier * fx_mid`, sharing `equity()`'s FX and futures
treatment. `None` while unmarked; a missing FX rate raises instead of assuming
1.0. `PortfolioView.is_future(symbol)` says whether a symbol is a registered
future. Risk limits use both instead of the own-currency `mark`.
`PortfolioView.available_cash_total(base)` sums the settlement-aware available
cash of every held currency in base (ADR-0049); `PortfolioView.margin_required(
symbol, qty, kind)` is a future's per-contract initial/maintenance margin for
`abs(qty)` contracts in base, `None` for a non-future or a spec without
margins (ADR-0050).

## Settlement lag (ADR-0028)
`PortfolioView.available_cash(currency)` / `PortfolioSnapshot.
available_cash` expose the settlement-lag-aware subset of `cash`: sale
proceeds not yet settled (T+N, `BacktestEngine.settlement_lag_days`) are
excluded until `settled_at <= as_of`. Asymmetric by design — only
*incoming* cash (`amount > 0`, i.e. sale proceeds) is delayed; a purchase
debits buying power immediately, matching real broker mechanics. Never
used by `equity()`/I1 — settlement lag changes what a strategy can spend,
never net worth, so the accounting identity is untouched. The natural
first consumer is `risk.limits.InsufficientCashLimit`
(`docs/modules/risk.md`).

## Borrow cost and margin financing (ADR-0032)
`TransactionType.BORROW`/`FINANCING` (scaffolded) are now
used: `core/engine.py::BacktestEngine._accrue_financing` (not this
module — see `docs/modules/core.md`) posts a `BORROW` transaction per
short position (`notional × short_borrow_rate`, Actual/365) and a
`FINANCING` transaction per negative cash balance
(`|cash| × margin_financing_rate`, Actual/365) at every mark, both
end-of-period-balance-based, both `0.0`-rate-default (zero behavior
change). A short *futures* position is excluded from borrow cost
entirely (a code-review fix, ADR-0034 — shorting a future is a
symmetric contract, not a borrowed security; there's nothing to charge
a stock-loan fee against). Neither counts toward `fees_paid` (that
aggregate is commissions only, `TransactionType.FEE`) — they're separate cost
categories by design.

## Futures (ADR-0033)
`PositionState.apply` is reused unchanged for futures — the only
genuinely different things are handled at the call sites in
`core/engine.py` (see `docs/modules/core.md`): no cash moves to open/
increase a futures position (only the realized share on a closing fill,
scaled by the contract's `multiplier`), and a new periodic settlement
(`_settle_futures_mtm`) realizes the *entire* unrealized move to cash at
every mark via a synthetic close-then-reopen transaction pair — both
ordinary, `fold`-replayable transactions, so the I3/I4 fold-is-truth
invariant needed no exception. `avg_cost`/ledger `price` stay in raw
quoted-price units throughout (never multiplier-scaled) for reporting
clarity; only cash amounts, `equity()`'s position contribution, and
`realized_pnl` apply the multiplier. A roll (closing an expiring
contract, opening the next) needs no dedicated mechanism — each
contract month is its own `Symbol`, so it's just two ordinary orders.
A `delisting` on a futures symbol liquidates at `(mark - avg_cost) · qty ·
multiplier`, the same realized-delta rule as a closing fill, with no
settlement lag — it used to book `qty · mark` (the whole notional, 2 ES at
4520 crediting +9040; 2026-10 audit). A `cash_dividend` row on a futures
symbol is refused (`DataQualityError`): a contract has no dividend
entitlement and `qty · per_share` would ignore the multiplier.

## Checkpoint/resume (E7, ADR-0041)
`InMemoryLedger.snapshot()` is the ordered transaction list (`txns`);
balances, positions and available cash are derived by `fold`, so nothing
else is stored. `restore` replaces the list in place after checking every
entry is a `TransactionRecord`.

## Known gaps
No strategy-facing API to *initiate* a currency conversion yet (only
automatic per-symbol-currency fills and mid-rate mark-time valuation are
wired into the engine, ADR-0025) — a strategy can't yet proactively manage
FX exposure. FX PnL is split from price PnL per trade in the trade log
(`pnl_fx`, ADR-0049) but not in reported equity metrics —
`equity()` folds both into one number; the
breakdown is an analytics-layer follow-up. No dividend reinvestment/DRIP.
Cash amounts are exact (unquantized) Decimals; broker-style rounding
rules are an open decision. `InsufficientCashLimit` sums available cash across
currencies in base (ADR-0049). Borrow cost is one flat rate
for every short (no per-symbol/hard-to-borrow schedule); no interest is
earned on a positive cash balance (debit-only financing); the day-count
convention (Actual/365) isn't configurable (ADR-0032). Futures are margined
per contract (ADR-0050); no futures-specific commission model, no tick-size rounding, no forced-close-at-expiry
(ADR-0033).
