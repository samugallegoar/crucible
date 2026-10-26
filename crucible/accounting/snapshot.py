"""Read-only portfolio snapshot at a mark: ledger fold + market marks.

A snapshot is a cache of the fold, never the source of truth; the mark-time
invariants (``crucible.accounting.invariants``) verify it against a fresh
fold on every mark.

Multi-currency (ADR-0009): each symbol's own currency comes from
``symbol_currency`` (unlisted symbols default to ``base_currency`` --
every caller that never set this stays single-currency with no
behavior change). ``equity`` converts every non-base cash balance and
position value at the mid rate (``accounting.fx.convert_at_mid``, the
marking role) -- a real trade never happens here, only valuation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from crucible.accounting.fx import convert_at_mid
from crucible.core.errors import CrucibleError
from crucible.core.types import Currency, Symbol, TimestampNs

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crucible.accounting.ledger import PortfolioBalances
    from crucible.core.instruments import FuturesSpec


class SnapshotPosition:
    """Satisfies ``crucible.accounting.interfaces.Position``."""

    def __init__(self, symbol: Symbol, qty: Decimal, avg_cost: Decimal, currency: Currency) -> None:
        self.symbol = symbol
        self.qty = qty
        self.avg_cost = avg_cost
        self.currency = currency


class PortfolioSnapshot:
    """Satisfies ``PortfolioView``. ``equity`` only accepts the currency
    the run is denominated in (``base_currency``) -- reporting in an
    arbitrary third currency is not supported (the equity
    formula reports in "base")."""

    def __init__(
        self,
        balances: PortfolioBalances,
        marks: Mapping[Symbol, Decimal],
        base_currency: Currency,
        ts: TimestampNs,
        *,
        symbol_currency: Mapping[Symbol, Currency] | None = None,
        fx_mid_rates: Mapping[Currency, Decimal] | None = None,
        futures_specs: Mapping[Symbol, FuturesSpec] | None = None,
    ) -> None:
        self._balances = balances
        self._marks = dict(marks)
        self._base = base_currency
        self._ts = ts
        self._symbol_currency = dict(symbol_currency or {})
        self._fx_mid_rates = dict(fx_mid_rates or {})
        self._futures_specs = dict(futures_specs or {})

    @property
    def ts(self) -> TimestampNs:
        return self._ts

    def _currency_of(self, symbol: Symbol) -> Currency:
        return self._symbol_currency.get(symbol, self._base)

    def cash(self, currency: Currency) -> Decimal:
        return self._balances.cash.get(currency, Decimal("0"))

    def available_cash(self, currency: Currency) -> Decimal:
        """The settlement-lag-aware subset of ``cash`` (ADR-0028): sale
        proceeds not yet settled are excluded. Never used by ``equity``."""
        return self._balances.available_cash.get(currency, Decimal("0"))

    def available_cash_total(self, base_currency: Currency) -> Decimal:
        """See ``PortfolioView.available_cash_total`` (ADR-0049)."""
        if base_currency != self._base:
            msg = (
                f"this run is denominated in {self._base}; available cash can only be "
                f"totalled in that currency, not {base_currency}"
            )
            raise CrucibleError(msg)
        total = Decimal("0")
        for ccy, amount in self._balances.available_cash.items():
            total += convert_at_mid(amount, ccy, self._base, self._fx_mid_rates)
        return total

    def cash_total(self, base_currency: Currency) -> Decimal:
        """Every currency's cash valued in the base at the mid rate (the ``equity.parquet.cash``
        column).

        ``cash(base)`` is only the base-currency wallet: reporting it as the portfolio's cash
        made ``cash + positions`` disagree with equity by the foreign wallet's converted value
        (2026-10 audit). Uses the same marking rates as ``equity``.
        """
        if base_currency != self._base:
            msg = (
                f"this run is denominated in {self._base}; cash can only be totalled in that "
                f"currency, not {base_currency}"
            )
            raise CrucibleError(msg)
        total = Decimal("0")
        for ccy, amount in self._balances.cash.items():
            total += convert_at_mid(amount, ccy, self._base, self._fx_mid_rates)
        return total

    def position(self, symbol: Symbol) -> SnapshotPosition | None:
        state = self._balances.positions.get(symbol)
        if state is None or state.qty == 0:
            return None
        return SnapshotPosition(symbol, state.qty, state.avg_cost, self._currency_of(symbol))

    def positions(self) -> dict[Symbol, SnapshotPosition]:
        return {
            symbol: SnapshotPosition(symbol, state.qty, state.avg_cost, self._currency_of(symbol))
            for symbol, state in self._balances.positions.items()
            if state.qty != 0
        }

    def mark(self, symbol: Symbol) -> Decimal | None:
        return self._marks.get(symbol)

    def margin_required(
        self,
        symbol: Symbol,
        qty: Decimal | None = None,
        kind: Literal["initial", "maintenance"] = "initial",
    ) -> Decimal | None:
        """See ``PortfolioView.margin_required`` (ADR-0050)."""
        spec = self._futures_specs.get(symbol)
        if spec is None:
            return None
        per_contract = spec.initial_margin if kind == "initial" else spec.maintenance_margin
        if per_contract is None:
            return None
        if qty is None:
            state = self._balances.positions.get(symbol)
            qty = state.qty if state is not None else Decimal("0")
        currency = self._currency_of(symbol)
        try:
            return convert_at_mid(abs(qty) * per_contract, currency, self._base, self._fx_mid_rates)
        except CrucibleError as exc:
            msg = (
                f"cannot value the {kind} margin of {symbol} ({currency}) in {self._base} at "
                f"ts={self._ts}: {exc}. Give the engine an fx_dataset covering "
                f"{currency}/{self._base} and map the symbol with symbol_currency"
            )
            raise CrucibleError(msg) from exc

    def is_future(self, symbol: Symbol) -> bool:
        return symbol in self._futures_specs

    def notional(self, symbol: Symbol, qty: Decimal | None = None) -> Decimal | None:
        """See ``PortfolioView.notional`` (ADR-0045): shares the FX and
        multiplier treatment of ``equity()`` and ``realized_pnl``."""
        mark = self._marks.get(symbol)
        if mark is None:
            return None
        if qty is None:
            state = self._balances.positions.get(symbol)
            qty = state.qty if state is not None else Decimal("0")
        spec = self._futures_specs.get(symbol)
        multiplier = spec.multiplier if spec is not None else Decimal(1)
        try:
            return convert_at_mid(
                abs(qty) * mark * multiplier,
                self._currency_of(symbol),
                self._base,
                self._fx_mid_rates,
            )
        except CrucibleError as exc:
            msg = (
                f"cannot value {symbol} ({self._currency_of(symbol)}) in {self._base} at "
                f"ts={self._ts}: {exc}. Give the engine an fx_dataset covering "
                f"{self._currency_of(symbol)}/{self._base} and map the symbol with "
                "symbol_currency"
            )
            raise CrucibleError(msg) from exc

    def equity(self, base_currency: Currency) -> Decimal:
        """Σ FX(ccy→base)·Cash(ccy) + Σ qty·mark·FX(symbol's ccy→base)
        (the equity identity). A held position without a mark is a
        refusal: the engine will not invent a price (pessimism rule).

        A futures position (ADR-0033) contributes only its
        *unsettled* variation margin since the last mark-to-market
        settlement -- ``(mark - avg_cost) · qty · multiplier`` -- never
        the full notional the way an owned equity position does: no
        cash ever paid for that notional, so adding it would invent
        equity that isn't there. Right after a mark (once
        `BacktestEngine._settle_futures_mtm` has run and rebased
        `avg_cost` to that mark), this is exactly zero -- the position's
        entire economics are already in cash by then."""
        if base_currency != self._base:
            msg = (
                f"this run is denominated in {self._base}; equity can only be "
                f"reported in that currency, not {base_currency}"
            )
            raise CrucibleError(msg)
        total = Decimal("0")
        for ccy, amount in self._balances.cash.items():
            total += convert_at_mid(amount, ccy, self._base, self._fx_mid_rates)
        for symbol, state in self._balances.positions.items():
            if state.qty == 0:
                continue
            mark = self._marks.get(symbol)
            if mark is None:
                msg = (
                    f"no mark for held position {symbol} at ts={self._ts}; "
                    "cannot compute equity. Ensure the data feed covers every held symbol."
                )
                raise CrucibleError(msg)
            futures_spec = self._futures_specs.get(symbol)
            position_value = (
                (mark - state.avg_cost) * state.qty * futures_spec.multiplier
                if futures_spec is not None
                else state.qty * mark
            )
            total += convert_at_mid(
                position_value, self._currency_of(symbol), self._base, self._fx_mid_rates
            )
        return total

    @property
    def realized_pnl(self) -> Decimal:
        """Raw ``PositionState.realized_pnl`` per symbol, scaled by that
        symbol's futures multiplier if it has one (1 otherwise) --
        `PositionState.apply` has no multiplier awareness (it's shared
        with every equity position), so this is the one place that
        scaling must happen for the aggregate to be in real currency
        units -- then converted to the run's base currency at the mid
        rate (ADR-0009's marking role), exactly like ``equity()``: a
        symbol's own realized PnL is booked in its own currency, and
        summing raw amounts across currencies without conversion would
        silently misreport the base-currency total (a bug this fix
        closes; ``equity()`` was always correct here, this property
        wasn't)."""
        total = Decimal("0")
        for symbol, position in self._balances.positions.items():
            futures_spec = self._futures_specs.get(symbol)
            multiplier = futures_spec.multiplier if futures_spec is not None else Decimal(1)
            total += convert_at_mid(
                position.realized_pnl * multiplier,
                self._currency_of(symbol),
                self._base,
                self._fx_mid_rates,
            )
        return total

    @property
    def fees_paid(self) -> Decimal:
        """Cumulative fees in the base currency, each currency converted at the snapshot's mid.

        The ledger keeps fees per currency; adding the raw amounts (the old behaviour) added
        dollars to euros. The conversion values a past fee at the current rate, so an FX move
        after the fee was paid changes this figure -- the cash impact at posting time is not
        tracked separately (2026-10 audit, H5)."""
        total = Decimal("0")
        for ccy, amount in self._balances.fees_by_currency.items():
            total += convert_at_mid(amount, ccy, self._base, self._fx_mid_rates)
        return total
