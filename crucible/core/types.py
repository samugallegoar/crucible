"""Core value types: timestamps, identifiers, currency, enums.

Units and timing semantics
--------------------------
- All internal timestamps are UTC epoch nanoseconds as ``int64`` (``TimestampNs``).
  Timezones exist only at I/O boundaries and inside calendars (ADR-0004).
- Money amounts on the ledger are ``decimal.Decimal``; prices/returns/analytics
  are floats. The boundary is documented in ``crucible/accounting``.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Final, NewType

# --------------------------------------------------------------------------- time

TimestampNs = NewType("TimestampNs", int)
"""UTC epoch nanoseconds. The only internal representation of time."""

NS_PER_US: Final[int] = 1_000
NS_PER_MS: Final[int] = 1_000_000
NS_PER_S: Final[int] = 1_000_000_000


def to_timestamp_ns(dt: datetime) -> TimestampNs:
    """Convert a timezone-aware datetime to internal UTC nanoseconds.

    Raises ``ValueError`` on naive datetimes: naive wall-clock time is exactly
    the ambiguity this codebase refuses to tolerate. Use only at I/O boundaries.
    """
    if dt.tzinfo is None:
        msg = f"naive datetime {dt!r}: internal time is UTC ns; attach a timezone at the boundary"
        raise ValueError(msg)
    return TimestampNs(int(dt.timestamp() * NS_PER_S))


# --------------------------------------------------------------------- identifiers

Symbol = NewType("Symbol", str)
Currency = NewType("Currency", str)
OrderId = NewType("OrderId", str)
TradeId = NewType("TradeId", str)
FillId = NewType("FillId", str)
EventId = NewType("EventId", str)
ExperimentId = NewType("ExperimentId", str)
DatasetId = NewType("DatasetId", str)
StrategyId = NewType("StrategyId", str)

# --------------------------------------------------------------------------- enums


class OrderSide(enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(enum.Enum):
    """Order types."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"
    BRACKET = "bracket"
    OCO = "oco"
    OTO = "oto"
    TWAP = "twap"
    VWAP = "vwap"
    PARTICIPATION = "participation"


class TimeInForce(enum.Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"
    GTD = "gtd"


class OrderState(enum.Enum):
    """Order lifecycle; legal transitions live in ``crucible.orders``."""

    CREATED = "created"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class RealismLevel(enum.IntEnum):
    """The realism ladder. Results carry their level as metadata."""

    FRICTIONLESS = 0
    BASIC_FRICTION = 1
    SPREAD_LATENCY = 2
    LIQUIDITY = 3
    IMPACT = 4
    MICROSTRUCTURE = 5


class RunMode(enum.Enum):
    """Optimization/evaluation separation."""

    OPTIMIZATION = "optimization"
    EVALUATION = "evaluation"


class MissingReason(enum.Enum):
    """Typed missingness. Scheme decided in ADR-0005."""

    MEASURED_EMPTY = "measured_empty"  # NaN: measured but empty
    UNAVAILABLE = "unavailable"  # not yet published as of `as_of`
    DELISTED = "delisted"
    MARKET_CLOSED = "market_closed"
    NO_LIQUIDITY = "no_liquidity"


class TransactionType(enum.Enum):
    """Ledger transaction types."""

    FILL = "fill"
    FEE = "fee"
    DIVIDEND = "dividend"
    BORROW = "borrow"
    FINANCING = "financing"
    FX = "fx"
    FUNDING = "funding"
    MARGIN_CALL = "margin_call"
    SETTLEMENT = "settlement"
    CORPORATE_ACTION = "corporate_action"


class CorporateActionType(enum.Enum):
    """Corporate actions the engine applies at ``effective_at``."""

    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    CASH_DIVIDEND = "cash_dividend"
    STOCK_DIVIDEND = "stock_dividend"
    SPINOFF = "spinoff"
    MERGER = "merger"
    SYMBOL_CHANGE = "symbol_change"
    DELISTING = "delisting"
