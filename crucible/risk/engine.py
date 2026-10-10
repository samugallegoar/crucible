"""Composes small risk limits into a `RiskEngine` (ADR-0027).

Each limit is checked in the order given; the first non-ALLOW decision
wins and short-circuits the rest -- put the most severe/important limits
first. Limits are Protocol-shaped (see `crucible/risk/limits.py`), not a
`RiskEngine` themselves, so new limits never need to touch this class.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

from crucible.core import checkpoint as ckpt
from crucible.core.errors import CheckpointError
from crucible.core.interfaces import Snapshottable
from crucible.risk.interfaces import RiskAction, RiskDecision

if TYPE_CHECKING:
    from collections.abc import Sequence

    from crucible.accounting.interfaces import PortfolioView
    from crucible.core.types import Currency, TimestampNs
    from crucible.orders.interfaces import Order


class PreTradeLimit(Protocol):
    @property
    def name(self) -> str: ...

    def check(
        self, order: Order, portfolio: PortfolioView, base_currency: Currency
    ) -> RiskDecision: ...


class MarkLimit(Protocol):
    @property
    def name(self) -> str: ...

    def check(
        self, portfolio: PortfolioView, ts: TimestampNs, base_currency: Currency
    ) -> RiskDecision: ...


class CompositeRiskEngine:
    """Satisfies `crucible.risk.interfaces.RiskEngine`."""

    def __init__(
        self,
        base_currency: Currency,
        *,
        pre_trade_limits: Sequence[PreTradeLimit] = (),
        mark_limits: Sequence[MarkLimit] = (),
    ) -> None:
        self._base = base_currency
        self._pre_trade_limits = list(pre_trade_limits)
        self._mark_limits = list(mark_limits)

    @property
    def pre_trade_limits(self) -> tuple[PreTradeLimit, ...]:
        """The configured pre-trade limits, in evaluation order (read-only)."""
        return tuple(self._pre_trade_limits)

    @property
    def mark_limits(self) -> tuple[MarkLimit, ...]:
        """The configured mark limits, in evaluation order (read-only)."""
        return tuple(self._mark_limits)

    def pre_trade(self, order: Order, portfolio: PortfolioView) -> RiskDecision:
        for limit in self._pre_trade_limits:
            decision = limit.check(order, portfolio, self._base)
            if decision.action is not RiskAction.ALLOW:
                return decision
        return RiskDecision(RiskAction.ALLOW, "passed all pre-trade limits")

    def on_mark(self, portfolio: PortfolioView, ts: TimestampNs) -> RiskDecision:
        for limit in self._mark_limits:
            decision = limit.check(portfolio, ts, self._base)
            if decision.action is not RiskAction.ALLOW:
                return decision
        return RiskDecision(RiskAction.ALLOW, "passed all mark limits")

    def snapshot(self) -> dict[str, object]:
        """Index-aligned with the configured limit lists; ``None`` marks a
        stateless limit. Limit configuration is setup, verified by the
        engine's setup fingerprint, not stored here."""
        return {
            "pre_trade": [
                limit.snapshot() if isinstance(limit, Snapshottable) else None
                for limit in self._pre_trade_limits
            ],
            "mark": [
                limit.snapshot() if isinstance(limit, Snapshottable) else None
                for limit in self._mark_limits
            ],
        }

    def restore(self, state: Mapping[str, object]) -> None:
        """Restores each stateful limit in place; refuses a different limit count.
        A refusal leaves every limit exactly as it was (ADR-0048)."""
        backup = self.snapshot()
        try:
            self._apply_state(state)
        except CheckpointError:
            self._apply_state(backup)
            raise

    def _apply_state(self, state: Mapping[str, object]) -> None:
        pre_trade_saved = ckpt.field_list(state, "pre_trade")
        if len(pre_trade_saved) != len(self._pre_trade_limits):
            msg = (
                f"checkpoint has {len(pre_trade_saved)} pre_trade limit states but this run "
                f"configures {len(self._pre_trade_limits)}; resume with the same risk configuration"
            )
            raise CheckpointError(msg)
        for i, entry in enumerate(pre_trade_saved):
            limit = self._pre_trade_limits[i]
            if isinstance(limit, Snapshottable):
                limit.restore(ckpt.expect(entry, dict, "pre_trade limit state"))
            elif entry is not None:
                msg = f"checkpoint has state for a stateless pre_trade limit ({limit.name})"
                raise CheckpointError(msg)

        mark_saved = ckpt.field_list(state, "mark")
        if len(mark_saved) != len(self._mark_limits):
            msg = (
                f"checkpoint has {len(mark_saved)} mark limit states but this run configures "
                f"{len(self._mark_limits)}; resume with the same risk configuration"
            )
            raise CheckpointError(msg)
        for i, entry in enumerate(mark_saved):
            mark_limit = self._mark_limits[i]
            if isinstance(mark_limit, Snapshottable):
                mark_limit.restore(ckpt.expect(entry, dict, "mark limit state"))
            elif entry is not None:
                msg = f"checkpoint has state for a stateless mark limit ({mark_limit.name})"
                raise CheckpointError(msg)
