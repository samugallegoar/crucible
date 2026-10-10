"""Non-equity instrument specifications (ADR-0033).

An equity symbol needs no spec: its own quoted price *is* the economics
(buy the shares, own that much notional, pay/receive the full price on
every fill). A futures symbol needs one: PnL per unit of price movement
is the contract's ``multiplier``, not 1, and — unlike an equity — no
cash changes hands to open a position at all; only daily mark-to-market
variation margin moves cash (``core/engine.py::BacktestEngine.
_settle_futures_mtm``, `docs/modules/core.md`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crucible.core.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class FuturesSpec:
    """``multiplier``: dollars of real P&L per 1.0 of quoted price
    movement, per contract (e.g. a $50 multiplier on a contract quoted
    at 4500.00 means a 1.00 quote move is $50, not $1).

    ``initial_margin``/``maintenance_margin``: optional per-contract margin in
    the contract's currency (ADR-0050); both or neither, ``initial >=
    maintenance > 0``."""

    multiplier: Decimal
    initial_margin: Decimal | None = None
    maintenance_margin: Decimal | None = None

    def __post_init__(self) -> None:
        if self.multiplier <= 0:
            msg = f"futures multiplier must be > 0, got {self.multiplier}"
            raise ConfigurationError(msg)
        if (self.initial_margin is None) != (self.maintenance_margin is None):
            msg = "futures margins need both initial_margin and maintenance_margin, or neither"
            raise ConfigurationError(msg)
        if self.initial_margin is not None and self.maintenance_margin is not None:
            if self.maintenance_margin <= 0:
                msg = f"futures maintenance_margin must be > 0, got {self.maintenance_margin}"
                raise ConfigurationError(msg)
            if self.initial_margin < self.maintenance_margin:
                msg = (
                    f"futures initial_margin {self.initial_margin} must be >= "
                    f"maintenance_margin {self.maintenance_margin}"
                )
                raise ConfigurationError(msg)
