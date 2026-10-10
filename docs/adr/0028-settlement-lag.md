# ADR-0028: Settlement lag and available cash (Phase 4 priority 4)

- **Status**: accepted
- **Date**: 2026-09-19

## Context

The original requirements ask for T+N settlement: sale proceeds shouldn't be spendable
until they settle (T+1/T+2 in most equity markets), even though they
belong to the strategy's net worth (equity) the instant the sale fills.
Before this priority, `PortfolioBalances.cash` was the only cash concept
— a sell's proceeds joined `cash` at the fill's own timestamp, exactly
like every other transaction, with no way to model a broker's settlement
delay.

The prior session's the roadmap entry noted the reason this priority was
reordered behind the risk engine (ADR-0027, done first): settlement lag
has no observable consumer on its own — nothing in the engine reads
"available cash" instead of "cash" anywhere. It needed a pre-trade limit
to make the distinction meaningful, which is why `InsufficientCashLimit`
ships in the same priority as the ledger mechanics, not as a follow-up.

## Decision

**A second cash balance, not a delayed transaction.** `TransactionRecord`
gains `settled_at: TimestampNs | None` (`None` means "settles at `ts`" —
unset by every transaction that doesn't model lag, so every existing
transaction type is unaffected with zero migration). `InMemoryLedger.fold`
computes two balances from the same transaction list: `cash` accumulates
every transaction's `amounts` as before (unconditional), and the new
`available_cash` accumulates only transactions whose `settled_at <= up_to`
(or all of them, when `fold()` is called unbounded). This reuses the
append-ordering, time-travel (`up_to`), and multi-currency machinery
`fold` already has — no second ledger, no new transaction type, no change
to `TransactionRecord.ts` semantics (still "when this happened," never
"when it settles").

The alternative — pushing a second, future-dated "proceeds become
spendable" transaction onto the event queue at fill time, mirroring the
two-stage dividend design (ADR-0026) — was rejected. Dividends need two
*events* because entitlement must be resolved from the position at one
time and paid at another (the amount itself changes between those times
under some designs). Settlement lag doesn't change the *amount* at all,
only which bucket of an already-fixed number of dollars it can be spent
from — a fold-time filter is the direct expression of that, and avoids
doubling the event volume for every fill in every run.

**Asymmetric by design: only incoming cash lags.** `BacktestEngine.
_settled_at(ts, amount)` returns `None` (immediate) for `amount <= 0` or
zero configured lag, else `ts + lag`. A purchase (`amount < 0`, cash
leaving) reduces buying power the instant it fills — this matches real
brokerage margin/buying-power mechanics, where a debit is immediate and
only a credit (sale proceeds) is provisional until settlement. Modeling
purchases as *also* lagged (e.g., "buying power frees up T+N after you
sell, and is consumed T+N after you buy" — some real "T+1 cash + margin"
systems do lag both sides) was considered and rejected as the *less*
conservative choice for the default: it would let a strategy re-spend
cash sooner than a pure-cash (non-margin) account actually allows.
AGENTS.md §10's "assume the worse outcome for the strategy" resolves the
choice — immediate debit, delayed credit is strictly more pessimistic
than the alternative for any strategy that both buys and sells.

**Dividends do not additionally lag.** `_handle_dividend`'s pay-date
transaction posts with `settled_at=None` (immediate at `pay_at`).
`pay_at` already models the one real-world delay a dividend has (ex-date
to pay-date); settlement lag is specifically a *trading* friction
(broker-mediated sale proceeds clearing), and stacking a second delay on
top of `pay_at` has no the original requirements basis and no real-world analogue documented
here — a dividend payment is cash landing in the account directly, not a
brokered trade settling.

**`available_cash` never enters `equity()` or I1.** Settlement lag is
purely a liquidity/spending constraint; net worth is unaffected the
instant a sale fills, matching real accounting (unsettled proceeds are
still an asset). `PortfolioView.available_cash(currency)` /
`PortfolioSnapshot.available_cash` are new, separate accessors;
`equity()`'s implementation is untouched — the identity I1 protects
continues to check exactly what it checked before this priority.

**`InsufficientCashLimit` (new `PreTradeLimit`) is the first and only
consumer**, capping a BUY's cost at `available_cash(base_currency)`
instead of `cash`. It ALLOWs every SELL unconditionally (a sell never
needs cash) and RESIZEs a BUY down to `floor(available / mark)` shares
when the requested cost exceeds available cash, REJECTing only if even
one share is unaffordable — the same RESIZE-then-REJECT-at-the-floor
shape as `MaxOrderNotionalLimit` (ADR-0027), for consistency. It checks
only the run's base currency (a known gap, see Consequences) since no
other limit or accessor yet resolves "available cash in the symbol's own
trading currency" and inventing that machinery wasn't in scope for this
priority.

**Config**: `ExperimentConfig.settlement_lag_days: int = Field(ge=0,
default=0)`, a top-level field (matching `periods_per_year`'s precedent,
not nested under `DataConfig`/`ExecutionConfig` — it's a portfolio-level
accounting policy, not a data-source or execution-model concern).
`settlement_lag_days=0` is exactly today's behavior (`available_cash ==
cash` always, since every `settled_at` resolves to `None`/immediate).

## Alternatives considered

- **A delayed transaction pushed onto the event queue at fill time**
  (mirroring ADR-0026's two-stage dividend): rejected — doubles event
  volume for every fill and solves a problem (an amount that changes
  between resolution and payment) settlement lag doesn't have; a
  fold-time filter is simpler and reuses existing machinery exactly.
- **Symmetric lag** (buys also delay from spending newly-freed cash):
  rejected as the default — less pessimistic than immediate-debit for
  a strategy that both buys and sells; AGENTS.md §10 resolves it.
- **`available_cash` folded into `equity()`**: rejected — settlement lag
  is a liquidity constraint, not a valuation change; conflating the two
  would make I1 fail to protect the invariant it's meant to protect (an
  unsettled sale's proceeds are still real net worth).
- **`InsufficientCashLimit` resolving each symbol's own trading
  currency**: rejected for this priority — no existing accessor gives
  "available cash in currency X" cheaply without new FX-conversion
  machinery at risk-check time; documented as a known gap instead of
  building it speculatively.

## Consequences

`TransactionRecord` gains `settled_at: TimestampNs | None = None`
(additive, every existing construction site is unaffected).
`PortfolioBalances` gains a required `available_cash: dict[Currency,
Decimal]` field (no default — every call site updated explicitly, so no
call site can silently forget it). `PortfolioView`/`PortfolioSnapshot`
gain `available_cash(currency) -> Decimal`. `BacktestEngine` gains
`settlement_lag_days: int = 0` (validated `>= 0`) and `_settled_at`;
applied at the two places cash currently enters the ledger from a fill or
liquidation (`_book_fill`, the delisting branch) — dividends deliberately
excluded, see Decision. `crucible/risk/limits.py` gains
`InsufficientCashLimit`; registered in `crucible/risk/registry.py` and
`experiments/config.py`'s `PreTradeLimitConfig` union as
`"insufficient_cash"`.

Tests: `tests/unit/test_ledger_settlement_lag.py` (6, hand-computed fold
behavior — cash reflects everything immediately, available_cash excludes
unsettled proceeds up to and including the settlement boundary, purchases
reduce both immediately), `tests/unit/test_risk_limits.py` (+4,
`InsufficientCashLimit` against a real `PortfolioSnapshot`),
`tests/integration/test_settlement_lag.py` (2, real `BacktestEngine`
runs: one proving a buy funded by unsettled proceeds is REJECTED and the
identical buy submitted after settlement lands is ALLOWED and fills; one
proving a purchase reduces available cash immediately).

`ExperimentConfig.settlement_lag_days` (default `0`) serializes into
every `config.yaml`, which shifted the momentum example's golden
`config.yaml` hash and therefore its `experiment_id` (`EXP-39bcac077c21`
→ `EXP-9aac2e4bf730`). Every actual simulation artifact — ledger, orders,
fills, trades, equity, metrics — stayed byte-identical (verified file by
file, not just via the aggregate hash comparison); regenerated with
`--regen-golden` and recorded in CHANGELOG.md, same pattern as
ADR-0025/0026/0027.

Known gaps carried forward: `InsufficientCashLimit` only checks the run's
base currency; no borrow/margin/financing yet (settlement lag is a
liquidity constraint on a pure cash account, not a margin model); no
example config sets `settlement_lag_days` or `risk.insufficient_cash` yet,
so no golden fixture exercises this path end-to-end through the
CLI/runner.
