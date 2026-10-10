"""Risk limit registry (AGENTS.md §6, ADR-0027).

Maps the stable string keys used by config (`type:` discriminators in
`experiments/config.py`) to limit factories. The registry deliberately
takes plain keyword params, not config objects -- risk never imports the
experiments layer (mirrors `crucible/execution/registry.py`).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from crucible.core.errors import ConfigurationError
from crucible.risk.limits import (
    DailyLossFlattenLimit,
    DrawdownHaltLimit,
    InsufficientCashLimit,
    MarginCallLimit,
    MarginRequirementLimit,
    MaxGrossExposureLimit,
    MaxOrderNotionalLimit,
)

if TYPE_CHECKING:
    from crucible.risk.engine import MarkLimit, PreTradeLimit

_PRE_TRADE_KEYS = (
    "max_order_notional",
    "max_gross_exposure",
    "insufficient_cash",
    "margin_requirement",
)
_MARK_KEYS = ("drawdown_halt", "daily_loss_flatten", "margin_call")


def build_pre_trade_limit(key: str, **params: object) -> PreTradeLimit:
    if key == "max_order_notional":
        return MaxOrderNotionalLimit(max_notional=Decimal(str(params["max_notional"])))
    if key == "max_gross_exposure":
        return MaxGrossExposureLimit(max_ratio=float(str(params["max_ratio"])))
    if key == "insufficient_cash":
        return InsufficientCashLimit()
    if key == "margin_requirement":
        return MarginRequirementLimit(
            initial_margin_rate=float(str(params.get("initial_margin_rate", 1.5)))
        )
    msg = f"unknown pre-trade limit {key!r}; registered: {list(_PRE_TRADE_KEYS)}"
    raise ConfigurationError(msg)


def build_mark_limit(key: str, **params: object) -> MarkLimit:
    if key == "drawdown_halt":
        return DrawdownHaltLimit(max_drawdown=float(str(params["max_drawdown"])))
    if key == "daily_loss_flatten":
        return DailyLossFlattenLimit(max_daily_loss=float(str(params["max_daily_loss"])))
    if key == "margin_call":
        return MarginCallLimit(
            maintenance_margin_rate=float(str(params.get("maintenance_margin_rate", 1.3)))
        )
    msg = f"unknown mark limit {key!r}; registered: {list(_MARK_KEYS)}"
    raise ConfigurationError(msg)
