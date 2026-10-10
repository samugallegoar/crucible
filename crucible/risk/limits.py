"""Concrete risk limits (ADR-0027): each is one small checkable
unit; a `RiskEngine` composes a list of them (`CompositeRiskEngine`,
`crucible/risk/engine.py`). Pre-trade limits never restrict a
risk-*reducing* order (closing/shrinking a position is always allowed,
regardless of how over any limit the book already is) -- the pessimism
rule (AGENTS.md §10) cuts toward letting risk *leave* the book freely,
never trapping a strategy in an over-limit position it's trying to exit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING, Literal

from crucible.core import checkpoint as ckpt
from crucible.core.errors import ConfigurationError
from crucible.core.types import OrderSide
from crucible.risk.interfaces import RiskAction, RiskDecision

if TYPE_CHECKING:
    from crucible.accounting.interfaces import PortfolioView
    from crucible.core.types import Currency, Symbol, TimestampNs
    from crucible.orders.interfaces import Order

DAY_NS = 86_400 * 10**9


@dataclass(frozen=True, slots=True)
class MaxOrderNotionalLimit:
    """Caps a single order's own notional value (``qty`` times the
    base-currency notional of one unit: FX-converted and multiplier-scaled,
    ADR-0045),
    independent of any existing position -- the simplest RESIZE-capable
    limit: no current-position or direction-flip math to get wrong."""

    max_notional: Decimal

    @property
    def name(self) -> str:
        return "max_order_notional"

    def check(
        self, order: Order, portfolio: PortfolioView, base_currency: Currency
    ) -> RiskDecision:
        unit = portfolio.notional(order.symbol, Decimal(1))
        if unit is None:
            return RiskDecision(
                RiskAction.ALLOW, f"no mark yet for {order.symbol}; deferring check"
            )
        notional = order.qty * unit
        if notional <= self.max_notional:
            return RiskDecision(RiskAction.ALLOW, "within max order notional")
        resized_qty = (self.max_notional / unit).quantize(Decimal("1"), rounding=ROUND_DOWN)
        if resized_qty <= 0:
            msg = f"order notional {notional} exceeds max {self.max_notional} even at qty=1"
            return RiskDecision(RiskAction.REJECT, msg)
        msg = f"order notional {notional} exceeds max {self.max_notional}; resized to {resized_qty}"
        return RiskDecision(RiskAction.RESIZE, msg, resized_qty=resized_qty)


@dataclass(frozen=True, slots=True)
class InsufficientCashLimit:
    """REJECTs/RESIZEs a BUY whose cost would exceed *available* (settled)
    cash (ADR-0028) -- the
    natural first consumer of settlement lag: a strategy cannot spend
    sale proceeds that haven't settled yet, even though `equity` already
    reflects them. SELL orders are never restricted (reduces risk, never
    needs cash). Buying power is the total available cash across currencies
    converted to base (ADR-0049), compared with the order's base-currency
    notional. A futures BUY is never blocked here: no cash is paid to open one
    (ADR-0033), the margin limits handle it."""

    @property
    def name(self) -> str:
        return "insufficient_cash"

    def check(
        self, order: Order, portfolio: PortfolioView, base_currency: Currency
    ) -> RiskDecision:
        if order.side is not OrderSide.BUY:
            return RiskDecision(RiskAction.ALLOW, "not a buy order")
        if portfolio.is_future(order.symbol):
            return RiskDecision(
                RiskAction.ALLOW, "no cash is paid to open a futures position (see margin limits)"
            )
        unit = portfolio.notional(order.symbol, Decimal(1))
        if unit is None:
            return RiskDecision(
                RiskAction.ALLOW, f"no mark yet for {order.symbol}; deferring check"
            )
        cost = order.qty * unit
        available = portfolio.available_cash_total(base_currency)
        if cost <= available:
            return RiskDecision(RiskAction.ALLOW, "sufficient available cash")
        resized_qty = (available / unit).quantize(Decimal("1"), rounding=ROUND_DOWN)
        if resized_qty <= 0:
            msg = f"available cash {available} insufficient for even 1 share at {unit}"
            return RiskDecision(RiskAction.REJECT, msg)
        msg = f"order cost {cost} exceeds available cash {available}; resized to {resized_qty}"
        return RiskDecision(RiskAction.RESIZE, msg, resized_qty=resized_qty)


@dataclass(frozen=True, slots=True)
class MaxGrossExposureLimit:
    """Rejects an order that would push gross exposure (Σ|position
    value|) above ``max_ratio * equity``. REJECT only -- computing a safe
    RESIZE here would need to handle direction flips against an existing
    position correctly; `MaxOrderNotionalLimit` is the RESIZE-capable
    limit (ADR-0027)."""

    max_ratio: float

    @property
    def name(self) -> str:
        return "max_gross_exposure"

    def check(
        self, order: Order, portfolio: PortfolioView, base_currency: Currency
    ) -> RiskDecision:
        unit = portfolio.notional(order.symbol, Decimal(1))
        if unit is None:
            return RiskDecision(
                RiskAction.ALLOW, f"no mark yet for {order.symbol}; deferring check"
            )
        equity = portfolio.equity(base_currency)
        if equity <= 0:
            return RiskDecision(RiskAction.REJECT, f"equity {equity} is non-positive")

        positions = portfolio.positions()
        current = positions.get(order.symbol)
        current_qty = current.qty if current is not None else Decimal("0")
        other_gross = sum(
            (
                _held_notional(portfolio, symbol)
                for symbol, position in positions.items()
                if symbol != order.symbol
            ),
            Decimal("0"),
        )
        delta = order.qty if order.side is OrderSide.BUY else -order.qty
        resulting_qty = current_qty + delta
        if abs(resulting_qty) <= abs(current_qty):
            return RiskDecision(RiskAction.ALLOW, "reduces this symbol's exposure")
        resulting_gross = other_gross + abs(resulting_qty) * unit
        max_gross = Decimal(str(self.max_ratio)) * equity
        if resulting_gross <= max_gross:
            return RiskDecision(RiskAction.ALLOW, "within max gross exposure")
        msg = (
            f"gross exposure {resulting_gross} would exceed {self.max_ratio}x equity ({max_gross})"
        )
        return RiskDecision(RiskAction.REJECT, msg)


def _held_notional(portfolio: PortfolioView, symbol: Symbol) -> Decimal:
    """Base-currency notional of a held position. ``portfolio.equity()`` has
    already refused if any held position lacks a mark (pessimism rule), so a
    mark is guaranteed here; margin requirements are mark-to-market, never
    cost-based (ADR-0031, ADR-0045)."""
    value = portfolio.notional(symbol)
    assert value is not None, f"{symbol} held with no mark after equity() succeeded"
    return value


def _futures_margin(
    portfolio: PortfolioView,
    symbol: Symbol,
    qty: Decimal | None,
    kind: Literal["initial", "maintenance"],
    limit: str,
    where: str,
) -> Decimal:
    """Base-currency futures margin, or a refusal when the symbol has no margins
    configured (ADR-0050)."""
    required = portfolio.margin_required(symbol, qty, kind)
    if required is None:
        msg = (
            f"{limit} needs initial_margin and maintenance_margin for futures symbol "
            f"{symbol} ({where}); set data.futures_margins for it or remove the limit "
            "(ADR-0050)"
        )
        raise ConfigurationError(msg)
    return required


class DrawdownHaltLimit:
    """HALT (no further orders accepted for the rest of the run) once
    equity falls more than ``max_drawdown`` from its all-time peak. Peak
    tracking is internal, mutable state -- this limit is stateful across
    marks by design, unlike the pre-trade limits above."""

    def __init__(self, max_drawdown: float) -> None:
        if not 0.0 < max_drawdown < 1.0:
            msg = f"max_drawdown must be in (0, 1), got {max_drawdown}"
            raise ConfigurationError(msg)
        self._max_drawdown = max_drawdown
        self._peak: Decimal | None = None

    @property
    def name(self) -> str:
        return "drawdown_halt"

    def check(
        self, portfolio: PortfolioView, ts: TimestampNs, base_currency: Currency
    ) -> RiskDecision:
        equity = portfolio.equity(base_currency)
        if self._peak is None or equity > self._peak:
            self._peak = equity
        if self._peak <= 0:
            return RiskDecision(RiskAction.ALLOW, "peak equity non-positive; skipping check")
        drawdown = float((self._peak - equity) / self._peak)
        if drawdown > self._max_drawdown:
            msg = (
                f"drawdown {drawdown:.2%} exceeds max {self._max_drawdown:.2%} "
                f"(peak={self._peak}, equity={equity})"
            )
            return RiskDecision(RiskAction.HALT, msg)
        return RiskDecision(RiskAction.ALLOW, f"drawdown {drawdown:.2%} within limit")

    def snapshot(self) -> dict[str, object]:
        """The equity peak seen so far (``None`` before the first mark)."""
        return {"peak": self._peak}

    def restore(self, state: Mapping[str, object]) -> None:
        """Restores the peak in place."""
        self._peak = ckpt.optional_field(state, "peak", Decimal)


@dataclass(frozen=True, slots=True)
class MarginRequirementLimit:
    """REJECTs an order that would open or increase a short position
    beyond what current equity can support (simplified Reg-T
    model, ADR-0031): collateral required for the book's total short
    exposure = Σ|short qty · mark| · ``initial_margin_rate`` (default
    1.5 = 150% of short notional, the standard Reg-T initial margin).
    Never restricts covering/reducing a short, or a long order --
    leveraged-long buying power is already gated by
    ``InsufficientCashLimit``'s available-cash check (ADR-0028), and a
    short-reducing order is never blocked (pessimism rule, this module's
    docstring). REJECT-only, same precedent as `MaxGrossExposureLimit`:
    a safe RESIZE would need to handle direction flips against an
    existing position, judged not worth the complexity."""

    initial_margin_rate: float = 1.5

    def __post_init__(self) -> None:
        if self.initial_margin_rate < 1.0:
            msg = f"initial_margin_rate must be >= 1.0 (100%), got {self.initial_margin_rate}"
            raise ConfigurationError(msg)

    @property
    def name(self) -> str:
        return "margin_requirement"

    def check(
        self, order: Order, portfolio: PortfolioView, base_currency: Currency
    ) -> RiskDecision:
        unit = portfolio.notional(order.symbol, Decimal(1))
        if unit is None:
            return RiskDecision(
                RiskAction.ALLOW, f"no mark yet for {order.symbol}; deferring check"
            )
        positions = portfolio.positions()
        current = positions.get(order.symbol)
        current_qty = current.qty if current is not None else Decimal("0")
        delta = order.qty if order.side is OrderSide.BUY else -order.qty
        resulting_qty = current_qty + delta
        order_is_future = portfolio.is_future(order.symbol)
        if order_is_future:
            increases_risk = abs(resulting_qty) > abs(current_qty)
        else:
            increases_risk = resulting_qty < 0 and abs(resulting_qty) > abs(current_qty)
        if not increases_risk:
            return RiskDecision(RiskAction.ALLOW, "not increasing margin exposure")
        # equity() refuses if any held position lacks a mark (pessimism rule) --
        # once it succeeds, every other position's mark below is guaranteed present.
        equity = portfolio.equity(base_currency)
        short_notional = Decimal("0")
        futures_margin = Decimal("0")
        for symbol, position in positions.items():
            if symbol == order.symbol:
                continue
            if portfolio.is_future(symbol):
                futures_margin += _futures_margin(
                    portfolio, symbol, None, "initial", self.name, "held position"
                )
            elif position.qty < 0:
                short_notional += _held_notional(portfolio, symbol)
        if order_is_future:
            futures_margin += _futures_margin(
                portfolio, order.symbol, resulting_qty, "initial", self.name, f"order {order.id}"
            )
        else:
            short_notional += abs(resulting_qty) * unit
        required = Decimal(str(self.initial_margin_rate)) * short_notional + futures_margin
        if equity >= required:
            return RiskDecision(RiskAction.ALLOW, "within initial margin requirement")
        msg = (
            f"equity {equity} insufficient for initial margin: short notional {short_notional} "
            f"at rate {self.initial_margin_rate} plus futures margin {futures_margin} "
            f"(needs {required})"
        )
        return RiskDecision(RiskAction.REJECT, msg)


class MarginCallLimit:
    """FLATTEN (close every position, ADR-0031)
    when equity falls below the book's total maintenance margin
    requirement on short positions: Σ|short qty · mark| ·
    ``maintenance_margin_rate`` (default 1.3 = 130% of short notional).
    No short exposure means no requirement, and this limit ALLOWs.
    FLATTEN closes the *whole* book, not just the short side that
    triggered the call -- real brokers may liquidate only the minimum
    needed to restore compliance, but computing that minimum is a harder
    optimization problem (which positions, how much, accounting for the
    equity impact of each partial close); reusing the existing,
    already-tested FLATTEN mechanism (ADR-0027) is the conservative
    choice (AGENTS.md §10) and a documented simplification, not an
    oversight. Unlike `DrawdownHaltLimit`, a margin call does not halt
    future trading -- a strategy may reopen positions afterward."""

    def __init__(self, maintenance_margin_rate: float = 1.3) -> None:
        if maintenance_margin_rate < 1.0:
            msg = f"maintenance_margin_rate must be >= 1.0 (100%), got {maintenance_margin_rate}"
            raise ConfigurationError(msg)
        self._rate = maintenance_margin_rate

    @property
    def name(self) -> str:
        return "margin_call"

    def check(
        self, portfolio: PortfolioView, ts: TimestampNs, base_currency: Currency
    ) -> RiskDecision:
        equity = portfolio.equity(base_currency)  # refuses if any held position lacks a mark
        positions = portfolio.positions()
        short_notional = Decimal("0")
        futures_margin = Decimal("0")
        for symbol, position in positions.items():
            if portfolio.is_future(symbol):
                futures_margin += _futures_margin(
                    portfolio, symbol, None, "maintenance", self.name, f"position at ts={ts}"
                )
            elif position.qty < 0:
                short_notional += _held_notional(portfolio, symbol)
        if short_notional == 0 and futures_margin == 0:
            return RiskDecision(RiskAction.ALLOW, "no margin exposure")
        required = Decimal(str(self._rate)) * short_notional + futures_margin
        if equity >= required:
            return RiskDecision(RiskAction.ALLOW, f"equity {equity} meets maintenance margin")
        msg = (
            f"margin call: equity {equity} below maintenance requirement {required} "
            f"(short notional {short_notional} at rate {self._rate}, futures margin "
            f"{futures_margin})"
        )
        return RiskDecision(RiskAction.FLATTEN, msg)


class DailyLossFlattenLimit:
    """FLATTEN (close every position once, via market orders) when
    equity falls more than ``max_daily_loss`` from the first equity seen
    on the current UTC calendar day (``ts // DAY_NS`` -- a simple,
    deterministic day boundary; not exchange-session-aware, a documented
    simplification, ADR-0027). Unlike `DrawdownHaltLimit`, this does not
    stop *future* trading -- a strategy may reopen positions afterward;
    if the loss recurs, it flattens again."""

    def __init__(self, max_daily_loss: float) -> None:
        if not 0.0 < max_daily_loss < 1.0:
            msg = f"max_daily_loss must be in (0, 1), got {max_daily_loss}"
            raise ConfigurationError(msg)
        self._max_daily_loss = max_daily_loss
        self._day: int | None = None
        self._day_start_equity: Decimal | None = None

    @property
    def name(self) -> str:
        return "daily_loss_flatten"

    def check(
        self, portfolio: PortfolioView, ts: TimestampNs, base_currency: Currency
    ) -> RiskDecision:
        equity = portfolio.equity(base_currency)
        day = int(ts) // DAY_NS
        if self._day != day:
            self._day = day
            self._day_start_equity = equity
            return RiskDecision(RiskAction.ALLOW, "new day; loss tracking reset")
        assert self._day_start_equity is not None
        if self._day_start_equity <= 0:
            return RiskDecision(RiskAction.ALLOW, "day-start equity non-positive; skipping check")
        loss = float((self._day_start_equity - equity) / self._day_start_equity)
        if loss > self._max_daily_loss:
            msg = (
                f"daily loss {loss:.2%} exceeds max {self._max_daily_loss:.2%} "
                f"(day_start={self._day_start_equity}, equity={equity})"
            )
            return RiskDecision(RiskAction.FLATTEN, msg)
        return RiskDecision(RiskAction.ALLOW, f"daily loss {loss:.2%} within limit")

    def snapshot(self) -> dict[str, object]:
        """The current UTC day and its starting equity."""
        return {"day": self._day, "day_start_equity": self._day_start_equity}

    def restore(self, state: Mapping[str, object]) -> None:
        """Restores the day and its starting equity in place."""
        self._day = ckpt.optional_field(state, "day", int)
        self._day_start_equity = ckpt.optional_field(state, "day_start_equity", Decimal)
