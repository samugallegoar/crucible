"""Portfolio-construction Protocols: signals in, target positions out.

Alpha (strategy) and sizing (constructor) are separate concerns.
Constructors never see the future: they receive only what is knowable at the
construction timestamp via the PIT accessor.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from crucible.accounting.interfaces import PortfolioView
from crucible.core.types import StrategyId, Symbol, TimestampNs


class TargetSetter(Protocol):
    """The strategy-facing target API (``ctx.targets``): declarative weights
    that a constructor turns into orders. Weights are fractions of equity."""

    def with_strategy_id(self, strategy_id: StrategyId) -> TargetSetter:
        """A target setter that stamps every order it resolves with
        ``strategy_id`` (ADR-0030) -- mirrors
        ``OrderSubmitter.with_strategy_id``."""
        ...

    def set(self, symbol: Symbol, weight: float) -> None: ...

    def set_all(self, weights: Mapping[Symbol, float]) -> None:
        """Replaces the full target book; symbols absent mean weight 0."""
        ...


class PortfolioConstructor(Protocol):
    """Maps signal scores/expected returns to target weights (ADR-0029). Built-ins:
    ``EqualWeightConstructor``,
    ``FixedFractionalConstructor``, ``VolTargetConstructor``,
    ``RiskParityConstructor``, ``FractionalKellyConstructor``,
    ``MeanVarianceConstructor`` (``crucible/portfolio/constructors.py``).

    Convention (constructors are long-only): ``signals[symbol]
    > 0`` marks a symbol as a long candidate; its magnitude is read as an
    expected-return estimate by size-aware constructors and ignored
    (beyond ranking) by ``EqualWeightConstructor``. A symbol absent from
    ``signals`` or with a non-positive value is never selected.

    A constructor never reads the data layer itself -- it only sees
    values the *strategy* already pulled through the PIT accessor
    (``signals``, and optionally ``history``), so nothing here can leak
    the future on its own.
    """

    def construct(
        self,
        signals: Mapping[Symbol, float],
        portfolio: PortfolioView,
        as_of: TimestampNs,
        history: Mapping[Symbol, Sequence[float]] | None = None,
    ) -> Mapping[Symbol, float]:
        """Target weights per symbol. Uses only data available at ``as_of``.

        ``history`` is each candidate symbol's recent return series, as
        of ``as_of``, computed by the strategy (e.g. via
        ``ctx.data.history``) -- required by constructors that need a
        volatility/covariance estimate (vol targeting, risk parity,
        Kelly, mean-variance); ``None``/unused by ``EqualWeightConstructor``
        and ``FixedFractionalConstructor``. A constructor that needs it
        and doesn't receive it raises ``ConfigurationError``.
        """
        ...
