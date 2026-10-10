"""Risk-engine Protocols.

Every action (reject, resize, flatten, halt) is a logged ``RiskEvent`` — risk
decisions are part of the audit trail, never silent.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from crucible.accounting.interfaces import PortfolioView
from crucible.core.types import TimestampNs
from crucible.orders.interfaces import Order


class RiskAction(enum.Enum):
    ALLOW = "allow"
    REJECT = "reject"
    RESIZE = "resize"
    FLATTEN = "flatten"
    HALT = "halt"


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Outcome of a risk check. ``resized_qty`` is set only for RESIZE."""

    action: RiskAction
    reason: str
    resized_qty: Decimal | None = None


class RiskEngine(Protocol):
    """Pre-trade gate for every order plus continuous checks on every mark."""

    def pre_trade(self, order: Order, portfolio: PortfolioView) -> RiskDecision:
        """Checks an order before it reaches execution. Never mutates anything."""
        ...

    def on_mark(self, portfolio: PortfolioView, ts: TimestampNs) -> RiskDecision:
        """Continuous limits (drawdown halt, daily loss, exposure) at a mark."""
        ...
