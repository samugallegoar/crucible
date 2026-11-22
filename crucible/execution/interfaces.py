"""Execution Protocols: the realism ladder's pluggable pieces.

Pessimism assumptions (cross-cutting, enforced in code once implemented):
- Fills never occur outside the bar's ``[low, high]``; violations raise.
- Intrabar ambiguity resolves against the strategy; configurable only toward
  *more* pessimism.
- Nothing fills before the order could have reached the market (latency).

Every stochastic component takes an explicit ``numpy.random.Generator``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

import numpy as np

from crucible.core.interfaces import MarketEvent
from crucible.core.types import FillId, OrderId, TimestampNs
from crucible.orders.interfaces import Order


@dataclass(frozen=True, slots=True)
class ProposedFill:
    """A fill a model proposes; the simulator validates it against bar bounds
    and participation caps before it becomes a ``FillEvent``.

    ``passive`` marks a resting limit executed at its own limit price
    (maker); aggressive fills (market, or limits filled at a better opening
    price) are takers. Commission schedules may price the two differently.
    """

    order_id: OrderId
    fill_id: FillId
    ts: TimestampNs
    qty: Decimal
    price: float
    passive: bool = False


class FillModel(Protocol):
    """Decides whether/how an order fills against a market event."""

    def propose(
        self,
        order: Order,
        market: MarketEvent,
        rng: np.random.Generator,
    ) -> list[ProposedFill]:
        """Zero or more fills, each within the event's price bounds.

        Timing: proposed ``ts`` must be >= the time the order reached the
        market (submission + latency).
        """
        ...


class SpreadModel(Protocol):
    """Half-spread in price terms at a moment (static or vol/time-of-day dynamic)."""

    def half_spread(self, market: MarketEvent, rng: np.random.Generator) -> float: ...


class SlippageModel(Protocol):
    """Adverse price adjustment applied to a reference price."""

    def adjusted_price(
        self,
        reference_price: float,
        order: Order,
        market: MarketEvent,
        rng: np.random.Generator,
    ) -> float:
        """Always weakly worse for the order's side than ``reference_price``."""
        ...


class LatencyModel(Protocol):
    """Delay between a component emitting an event and it taking effect."""

    def latency_ns(self, rng: np.random.Generator) -> int:
        """Non-negative delay in nanoseconds; seeded, never wall-clock derived."""
        ...


class CommissionModel(Protocol):
    """Commission on a fill; ``Decimal`` because it lands on the ledger."""

    def commission(self, fill: ProposedFill) -> Decimal: ...


# ---------------------------------------------------------------------------------------------
# account overlay: a prop-firm account wrapped around the futures simulation (ADR-0106)


@dataclass(frozen=True, slots=True)
class AccountMarks:
    """The account as the futures simulator sees it at one bar (ADR-0106 section 3).

    Everything is exact integer arithmetic: prices in ticks, money in micro-dollars, a tick's
    value per contract in micro-dollars. The book is one-sided (FIFO closes opposing lots
    first), so equity is linear in price::

        equity(p) = balance_micro + (position * p - cost_basis_ticks) * tick_micro

    with ``cost_basis_ticks = sum(lot.qty * lot.entry)`` over the open lots. ``open/high/low/
    close_ticks`` are the OHLC of the bar the overlay is acting on (bar ``bar``), never of a
    later bar; a bar's interval is known from the schedule, so seeing its own extremes is not
    look-ahead. ``tradable`` is false when nothing could execute in the bar (off schedule, or
    the held contract did not print).
    """

    bar: int
    open_time_ns: TimestampNs
    close_time_ns: TimestampNs
    open_ticks: int
    high_ticks: int
    low_ticks: int
    close_ticks: int
    position: int
    balance_micro: int
    cost_basis_ticks: int
    tick_micro: int
    tradable: bool = True

    def equity_micro(self, price_ticks: int) -> int:
        """Equity in micro-dollars at ``price_ticks``: the exact, linear mark-to-market."""
        return self.balance_micro + (self.position * price_ticks - self.cost_basis_ticks) * (
            self.tick_micro
        )

    @property
    def favorable_ticks(self) -> int:
        """The price at which the open position is worth most: the high for a long, the low
        for a short (the close when flat, where every price gives the same equity)."""
        if self.position > 0:
            return self.high_ticks
        if self.position < 0:
            return self.low_ticks
        return self.close_ticks

    @property
    def adverse_ticks(self) -> int:
        """The price at which the open position is worth least: the low for a long, the high
        for a short (the close when flat)."""
        if self.position > 0:
            return self.low_ticks
        if self.position < 0:
            return self.high_ticks
        return self.close_ticks


@dataclass(frozen=True, slots=True)
class BreachPrice:
    """A price at which an active rule's threshold is touched, already rounded against the
    strategy (floor for a long, ceiling for a short) so it sits on the tick grid."""

    price_ticks: int
    rule_id: str
    hard: bool
    """``hard`` ends the account; a soft rule liquidates and locks until it resets."""


@dataclass(frozen=True, slots=True)
class OverlayAction:
    """What the simulator must do to the book. ``price_ticks`` None means the bar's open.

    ``kind``: ``liquidate`` flattens the position and keeps the account running (or locked);
    ``lock`` is the same flatten on a soft rule that also refuses entries until it resets;
    ``close_account`` flattens and ends the account for good; ``phase_flatten`` flattens because
    the phase passed and the next phase starts a fresh, flat account. Every kind is a market
    order paying the bar's open (or close) spread and slippage, plus the liquidation extra ticks
    charged as money at the trigger price (never by moving the price outside the bar).
    """

    kind: Literal["liquidate", "lock", "close_account", "phase_flatten"]
    rule_id: str
    hard: bool
    price_ticks: int | None = None


@dataclass(frozen=True, slots=True)
class OverlayEvent:
    """One thing the overlay did or refused, with its bar and time (ADR-0106 section 5)."""

    kind: str
    bar: int
    time_ns: TimestampNs
    rule_id: str
    requested: int | None = None
    allowed: int | None = None
    note: str = ""


class AccountOverlay(Protocol):
    """A trading account wrapped around the futures simulation (ADR-0106).

    The simulator calls these methods at fixed points of every bar, in this order:

    1. ``begin_bar(i, marks)``: the rule-day transition (each rule's reset time and time zone,
       with the previous rule-day's end-of-day processing of its EOD rules), then the gap test
       at the bar's open. A returned action liquidates at the open and nothing else happens in
       the bar.
    2. ``forced_flat(i, marks)``: a rule's flat-by clock time reached by this bar; a returned
       action liquidates at the bar's open and no entry is admitted until the reopen time.
    3. ``admit(i, marks, requested)``: the whole-contract target the account allows (contract
       limit, scaling plan, lock, closed account, forced-flat window). A resize is an event.
    4. ``favorable(i, marks, price_ticks)``: the bar's favourable extreme, before the adverse
       one, so intraday high-water marks update first (``high_before_low_conservative``).
    5. ``breach_prices(i, marks)``: every active failure threshold's breach price, recomputed
       after each fill on the adverse walk.
    6. ``breach_filled(i, marks, price_ticks, rule_id, hard)``: after the simulator liquidates
       at a breach price (``marks`` are the pre-fill marks).
    7. ``fill(i, marks, quantity, price_ticks, kind)``: after every fill the simulator books
       (not roll legs), so a rule that counts trades can count them.
    8. ``end_bar(i, marks) -> action | None``: the close mark, the rule-day's last-bar end-of-day
       rules (known from the calendar's scheduled session end) and the pass conditions. An
       action is executed AT THIS BAR'S CLOSE with the close cost tables: an EOD-evaluated breach
       liquidates there, and a pass with a position still open flattens it there as
       ``phase_flatten`` (the next phase starts fresh and flat).
    9. ``finish(marks)``: the end of the data; the last rule-day's EOD applies only when the day
       is complete per the calendar, otherwise an unresolved attempt is censored.

    ``closed`` is true once the account may not trade again (a hard breach, a failed phase, or
    an ended attempt); ``events`` is the append-only record of what happened.
    """

    @property
    def closed(self) -> bool: ...

    @property
    def events(self) -> list[OverlayEvent]: ...

    def begin_bar(self, i: int, marks: AccountMarks) -> OverlayAction | None: ...

    def forced_flat(self, i: int, marks: AccountMarks) -> OverlayAction | None: ...

    def admit(self, i: int, marks: AccountMarks, requested: int) -> int: ...

    def favorable(self, i: int, marks: AccountMarks, price_ticks: int) -> None: ...

    def breach_prices(self, i: int, marks: AccountMarks) -> list[BreachPrice]: ...

    def breach_filled(
        self, i: int, marks: AccountMarks, price_ticks: int, rule_id: str, hard: bool
    ) -> None: ...

    def fill(
        self, i: int, marks: AccountMarks, quantity: int, price_ticks: int, kind: str
    ) -> None: ...

    def end_bar(self, i: int, marks: AccountMarks) -> OverlayAction | None: ...

    def finish(self, marks: AccountMarks) -> None: ...
