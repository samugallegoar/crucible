# ADR-0025: Multi-currency FX handling (Phase 4 priority 1)

- **Status**: accepted
- **Date**: 2026-09-19

## Context

Phase 4 needs multi-currency portfolios: positions held
in a symbol's own local currency, equity reported in base currency via
an `as_of` FX rate, FX PnL attributed separately. ADR-0009 (Phase 3-era)
already pinned the rate convention — mid for marking, adverse side for
trading — but nothing implemented it: `PortfolioSnapshot.equity()`
explicitly refused any currency but the run's base
(`"multi-currency equity not implemented until Phase 4"`), every fill/fee/
delisting transaction hardcoded the run's base currency regardless of
which symbol traded, and no FX rate data concept existed anywhere in the
codebase.

## Decision

**A symbol's currency is a config-level mapping, not a bar-schema
field.** `DataConfig.symbol_currency: dict[str, str]` (validated 3-letter
ISO codes) maps symbols to their trading currency; symbols absent from
it trade in `base_currency` — the existing, unchanged behavior for every
Phase 1-3 example, none of which ever sets this field. Extending
`BAR_SCHEMA` with a per-row currency column was the alternative (see
below) and was rejected: a symbol's currency is a static identity fact,
not a time-varying PIT-disciplined observation like price, so it doesn't
belong in the bar contract.

**FX rates are PIT data like any other, reusing the existing generic
accessor.** `FX_RATE_SCHEMA` (`data/contracts.py`) shapes an FX rate
dataset exactly like `BAR_SCHEMA` (`symbol`/`event_time`/`available_at`
plus `mid`/`bid`/`ask`), with `symbol` holding a pair code (`"EURUSD"`
means "1 EUR = `mid` USD"). This needed zero new Protocol or accessor
code: `StorePITAccessor.get`/`history` already filter generically on a
`symbol` column, so an FX rate lookup is just
`self._pit.get(fx_dataset, ["mid"], [Symbol(f"{ccy}{base}")], as_of)` —
the same call shape a strategy already uses for bars. `DataConfig
.fx_rates: str | None` names the dataset; required (refused at
`BacktestEngine.__init__`, fail-fast) whenever `symbol_currency` names
any non-base currency.

**A fill in a foreign-currency symbol debits/credits cash in *that
symbol's own currency* — no automatic conversion.** Buying a EUR-priced
stock consumes EUR cash, going negative if the portfolio doesn't already
hold enough (exactly like base-currency cash can already go negative
today — no buying-power/margin check exists anywhere in this codebase
yet; margin is explicitly Phase 5). This is the minimal, correct
behavior for what the original requirements' Phase 4 acceptance bar actually asks
("invariants hold under multi-currency") without inventing an
unrequested auto-sweep/settlement mechanism. `BacktestEngine._book_fill`/
delisting-liquidation now resolve each transaction's currency via
`_currency_of(symbol)` instead of hardcoding `self._base` (three call
sites changed).

**Marking (equity, I1) converts every held currency at the mid rate;
trading (an explicit FX conversion) needed no new ledger machinery.**
`accounting/fx.py::convert_at_mid` is the marking-role conversion,
threaded through `PortfolioSnapshot.equity()` and the rewritten I1 check
(`check_equity_identity`, no longer "single-currency form" — see
`docs/INVARIANTS.md`... *the module docstring*, updated). `accounting/fx
.py::convert_at_adverse` is the trading-role conversion (pays the ask
when buying the quoted currency, receives the bid when selling it,
refuses a crossed quote). A currency conversion transaction is simply a
`TransactionRecord` with two amounts (negative in the currency sold,
positive in the currency bought, computed via `convert_at_adverse`) —
`InMemoryLedger.fold`'s existing per-currency loop over
`amounts: Mapping[Currency, Decimal]` already handles it with no change,
proven by `tests/unit/test_accounting_fx.py
::test_fx_conversion_transaction_moves_cash_in_both_currencies`. No
strategy-facing API constructs one yet (known gap, below) — this ADR
proves the accounting math is correct and ready for that surface, not
that the surface exists.

**`PortfolioSnapshot`/`MarkContext` gain `symbol_currency`/
`fx_mid_rates` as optional, default-empty parameters** — every Phase 1-3
call site (both production code and every existing test) is unaffected
byte-for-byte: with no foreign currencies, every symbol resolves to
`base_currency` and `convert_at_mid` is an identity, so the multi-currency
code path and the old single-currency path compute the exact same
number. Confirmed by the full existing test suite passing unchanged and
by the golden fixture's *only* change being `config.yaml`'s hash (two new
`DataConfig` fields with default values now appear in the canonical
YAML dump) — every actual simulation artifact (ledger/fills/equity
Parquet) stayed byte-identical, regenerated and documented here per
AGENTS.md §1.6/§7.

**Hand-computed test, per ADR-0009's own commitment.**
`tests/integration/test_multi_currency_accounting.py` runs a real
`BacktestEngine` (base USD, one USD symbol, one EUR symbol, an FX rate
that moves between marks) and asserts an independently hand-computed
equity value at two different marks — AGENTS.md §7's rule that money
edge cases are never engine-derived.

## Alternatives considered

- **Per-row currency column on `BAR_SCHEMA`**: rejected (see Decision) —
  currency is a static per-symbol fact in this codebase's scope (no
  redenomination/dual-listing modeling), not a PIT-timed observation;
  putting it in config keeps every dataset schema and every existing
  bar-building script untouched.
- **Auto-convert on fill** (spend base currency, engine silently buys
  the foreign currency at execution time to fund the trade): rejected —
  invents an unrequested "auto-FX-sweep" policy the original requirements doesn't specify, and
  would hide a real economic decision (when and at what rate to convert)
  inside fill mechanics instead of leaving it as an explicit, auditable
  ledger transaction. Letting foreign cash go negative is the more
  conservative, minimal choice, consistent with margin already being
  unimplemented everywhere else in this codebase.
- **A separate FX Protocol/accessor** instead of reusing `PITAccessor`:
  rejected — an FX rate has the exact same PIT shape as a bar; a new
  Protocol would duplicate `get`/`history`'s filtering logic for no
  behavioral difference.

## Consequences

No strategy-facing API exists yet to *initiate* a currency conversion
(`ctx.fx.convert(...)` or similar) — only automatic per-symbol-currency
fills and mid-rate mark-time valuation are wired into the engine today.
A strategy that wants to proactively manage its currency exposure has no
lever yet; this is a known gap, deferred until a real use case (e.g. a
multi-currency portfolio constructor) needs it. FX PnL is not yet
attributed separately from price PnL in the reported metrics (the original requirements:
"FX PnL is attributed separately") — `equity()` folds both into one
number today; separating them is an analytics-layer follow-up, not an
accounting correctness gap (the total is right; the breakdown isn't
shown yet). Dividends and settlement lag (the other two Phase 4
"FX handling, dividends, settlement lag" bullet items) are separate,
independent priorities, not started by this ADR.
