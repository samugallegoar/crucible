"""Execution model implementations for realism Levels 1-4.

Every model is deterministic given its inputs and the injected seeded
``numpy.random.Generator``. Models that need market history (ADV, trailing
volatility) read it from :class:`MarketStats`, which only ever contains bars
that have already closed — backward-looking by construction.

Pessimism: spreads and impact always move the price against the order's
side; latencies are non-negative; a model that lacks the history it needs
raises :class:`InsufficientHistory` and the simulator rejects the order with
that reason (refuse, don't guess).
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np

from crucible.accounting.ledger import price_to_decimal
from crucible.core import checkpoint as ckpt
from crucible.core.errors import (
    CheckpointError,
    ConfigurationError,
    CrucibleError,
    DataQualityError,
)
from crucible.core.types import OrderSide, Symbol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crucible.core.events import BarEvent
    from crucible.execution.interfaces import ProposedFill
    from crucible.orders.interfaces import Order


class InsufficientHistory(CrucibleError):
    """A model needed trailing history (ADV, vol) that does not exist yet."""


# ------------------------------------------------------------------ stats


class MarketStats:
    """Trailing per-symbol close/volume window. Updated once per closed bar,
    *after* that bar's fills are simulated, so fills only ever see statistics
    knowable before the bar they execute in."""

    def __init__(self, window: int = 20) -> None:
        if window < 2:
            msg = f"MarketStats window must be >= 2, got {window}"
            raise ConfigurationError(msg)
        self.window = window
        self._closes: dict[Symbol, deque[float]] = {}
        self._volumes: dict[Symbol, deque[float]] = {}

    def update(self, symbol: Symbol, close: float, volume: float) -> None:
        self._closes.setdefault(symbol, deque(maxlen=self.window)).append(close)
        self._volumes.setdefault(symbol, deque(maxlen=self.window)).append(volume)

    def n_bars(self, symbol: Symbol) -> int:
        return len(self._closes.get(symbol, ()))

    def adv(self, symbol: Symbol) -> float:
        """Trailing mean volume. Requires >= 2 closed bars."""
        volumes = self._volumes.get(symbol)
        if volumes is None or len(volumes) < 2:
            msg = (
                f"no ADV for {symbol}: {0 if volumes is None else len(volumes)} closed "
                f"bars, need >= 2. The order is rejected until history exists."
            )
            raise InsufficientHistory(msg)
        return float(np.mean(volumes))

    def daily_vol(self, symbol: Symbol) -> float:
        """Trailing std of log close-to-close returns. Requires >= 3 closes."""
        closes = self._closes.get(symbol)
        if closes is None or len(closes) < 3:
            msg = (
                f"no trailing vol for {symbol}: {0 if closes is None else len(closes)} "
                f"closed bars, need >= 3. The order is rejected until history exists."
            )
            raise InsufficientHistory(msg)
        arr = np.asarray(closes, dtype=np.float64)
        returns = np.diff(np.log(arr))
        return float(returns.std(ddof=1))

    def snapshot(self) -> dict[str, object]:
        """The window and the per-symbol close/volume histories."""
        return {
            "window": self.window,
            "closes": {str(sym): list(values) for sym, values in self._closes.items()},
            "volumes": {str(sym): list(values) for sym, values in self._volumes.items()},
        }

    def restore(self, state: Mapping[str, object]) -> None:
        """Replaces the histories in place; refuses a different window."""
        window = ckpt.field(state, "window", int)
        if window != self.window:
            msg = (
                f"MarketStats window mismatch: the checkpoint used {window}, this run uses "
                f"{self.window}; resume with the same execution.stats_window"
            )
            raise CheckpointError(msg)
        self._closes = {
            Symbol(sym): deque(ckpt.as_floats(values, f"stats closes[{sym}]"), maxlen=self.window)
            for sym, values in ckpt.field_dict(state, "closes").items()
        }
        self._volumes = {
            Symbol(sym): deque(ckpt.as_floats(values, f"stats volumes[{sym}]"), maxlen=self.window)
            for sym, values in ckpt.field_dict(state, "volumes").items()
        }


# ----------------------------------------------------------------- spread


class NoSpread:
    """Level 0/1: trades at the reference price itself."""

    def half_spread(self, market: BarEvent, rng: np.random.Generator) -> float:
        return 0.0


class StaticSpread:
    """Constant half-spread in bps of the bar's close."""

    def __init__(self, half_spread_bps: float) -> None:
        if half_spread_bps < 0:
            msg = f"half_spread_bps must be >= 0, got {half_spread_bps}"
            raise ConfigurationError(msg)
        self.half_spread_bps = half_spread_bps

    def half_spread(self, market: BarEvent, rng: np.random.Generator) -> float:
        return market.close * self.half_spread_bps / 10_000.0


class DynamicSpread:
    """Half-spread widening with the bar's own realized range:
    ``close * base_bps/1e4 * (1 + vol_mult * (high - low)/close)``.
    The executing bar's range is the volatility proxy — knowable to the
    simulator (it plays the market), never to the strategy."""

    def __init__(self, base_bps: float, vol_mult: float) -> None:
        if base_bps < 0 or vol_mult < 0:
            msg = f"base_bps and vol_mult must be >= 0, got {base_bps}, {vol_mult}"
            raise ConfigurationError(msg)
        self.base_bps = base_bps
        self.vol_mult = vol_mult

    def half_spread(self, market: BarEvent, rng: np.random.Generator) -> float:
        range_frac = (market.high - market.low) / market.close
        return market.close * self.base_bps / 10_000.0 * (1.0 + self.vol_mult * range_frac)


class QuotedSpread:
    """Half-spread from the executing bar's own top-of-book quotes (ADR-0060).

    ``max(ask_open - bid_open, ask_close - bid_close) / 2`` in price units. The reference price
    (the bar's mid for Polymarket) plus this half-spread is the ask for a buy, minus it the bid
    for a sell. The simulator cannot know which of the bar's two quotes a market order met, so
    it takes the wider one (pessimism). A bar with a missing, partial or crossed quote raises:
    there is no fallback to the mid. Knowable with the bar (``ts`` = ``available_at``); stateless.
    """

    def half_spread(self, market: BarEvent, rng: np.random.Generator) -> float:
        bid_open, ask_open = market.bid_open, market.ask_open
        bid_close, ask_close = market.bid_close, market.ask_close
        where = f"symbol {market.symbol} ts={market.ts}"
        if bid_open is None or ask_open is None or bid_close is None or ask_close is None:
            msg = (
                "quoted spread needs bid_open, ask_open, bid_close and ask_close on every bar "
                f"it prices; {where} has a missing quote. Use a dataset that carries quotes "
                "for this symbol or another spread model"
            )
            raise DataQualityError(msg)
        if bid_open > ask_open or bid_close > ask_close:
            msg = f"crossed quote (bid > ask) at {where}; fix the source data"
            raise DataQualityError(msg)
        return max(ask_open - bid_open, ask_close - bid_close) / 2.0


# ---------------------------------------------------------------- latency


class ZeroLatency:
    def latency_ns(self, rng: np.random.Generator) -> int:
        return 0


class ConstantLatency:
    def __init__(self, latency_ns: int) -> None:
        if latency_ns < 0:
            msg = f"latency must be >= 0 ns, got {latency_ns}"
            raise ConfigurationError(msg)
        self._latency_ns = latency_ns

    def latency_ns(self, rng: np.random.Generator) -> int:
        return self._latency_ns


class NormalLatency:
    """Gaussian latency truncated at zero, drawn per order from the run rng —
    seeded, so identical runs draw identical latencies (R3.3)."""

    def __init__(self, mean_ns: float, std_ns: float) -> None:
        if mean_ns < 0 or std_ns < 0:
            msg = f"mean_ns and std_ns must be >= 0, got {mean_ns}, {std_ns}"
            raise ConfigurationError(msg)
        self.mean_ns = mean_ns
        self.std_ns = std_ns

    def latency_ns(self, rng: np.random.Generator) -> int:
        return max(0, round(float(rng.normal(self.mean_ns, self.std_ns))))


# ------------------------------------------------------- slippage / impact


def _adverse(reference: float, fraction: float, side: OrderSide) -> float:
    """Move ``reference`` against the order by ``fraction`` (>= 0)."""
    if side is OrderSide.BUY:
        return reference * (1.0 + fraction)
    return reference * (1.0 - fraction)


class NoSlippage:
    def adjusted_price(
        self,
        reference_price: float,
        order: Order,
        market: BarEvent,
        rng: np.random.Generator,
    ) -> float:
        return reference_price


class FixedBpsSlippage:
    """Level 1 friction: fixed adverse bps."""

    def __init__(self, bps: float) -> None:
        if bps < 0:
            msg = f"slippage bps must be >= 0, got {bps}; negative friction is lookahead"
            raise ConfigurationError(msg)
        self.bps = bps

    def adjusted_price(
        self,
        reference_price: float,
        order: Order,
        market: BarEvent,
        rng: np.random.Generator,
    ) -> float:
        return _adverse(reference_price, self.bps / 10_000.0, order.side)


class SqrtImpact:
    """Square-root market impact: ``coef * sigma * sqrt(Q / ADV)`` (Level 4),
    applied adversely. ``sigma`` is trailing daily vol, ``ADV``
    trailing mean volume, both from :class:`MarketStats`."""

    def __init__(self, coef: float, stats: MarketStats) -> None:
        if coef < 0:
            msg = f"impact coef must be >= 0, got {coef}"
            raise ConfigurationError(msg)
        self.coef = coef
        self._stats = stats

    def adjusted_price(
        self,
        reference_price: float,
        order: Order,
        market: BarEvent,
        rng: np.random.Generator,
    ) -> float:
        adv = self._stats.adv(order.symbol)
        sigma = self._stats.daily_vol(order.symbol)
        fraction = self.coef * sigma * float(np.sqrt(float(order.remaining_qty) / adv))
        return _adverse(reference_price, fraction, order.side)


class LinearImpact:
    """Linear impact: ``coef * (Q / ADV)``, applied adversely."""

    def __init__(self, coef: float, stats: MarketStats) -> None:
        if coef < 0:
            msg = f"impact coef must be >= 0, got {coef}"
            raise ConfigurationError(msg)
        self.coef = coef
        self._stats = stats

    def adjusted_price(
        self,
        reference_price: float,
        order: Order,
        market: BarEvent,
        rng: np.random.Generator,
    ) -> float:
        adv = self._stats.adv(order.symbol)
        fraction = self.coef * float(order.remaining_qty) / adv
        return _adverse(reference_price, fraction, order.side)


# ------------------------------------------------------------- commission


class NoCommission:
    def commission(self, fill: ProposedFill) -> Decimal:
        return Decimal("0")


class BpsCommission:
    def __init__(self, bps: float) -> None:
        if bps < 0:
            msg = f"commission bps must be >= 0, got {bps}"
            raise ConfigurationError(msg)
        self.bps = bps

    def commission(self, fill: ProposedFill) -> Decimal:
        return (
            price_to_decimal(fill.price) * fill.qty * price_to_decimal(self.bps) / Decimal(10_000)
        )


class PerShareCommission:
    """Per-share rate with a per-fill minimum (an example schedule)."""

    def __init__(self, rate: str, minimum: str) -> None:
        self.rate = Decimal(rate)
        self.minimum = Decimal(minimum)
        if self.rate < 0 or self.minimum < 0:
            msg = f"per-share rate/min must be >= 0, got {rate}, {minimum}"
            raise ConfigurationError(msg)

    def commission(self, fill: ProposedFill) -> Decimal:
        return max(self.rate * fill.qty, self.minimum)


class MakerTakerCommission:
    """Maker/taker schedule: passive fills (resting limit executed at its
    limit price) pay ``maker_bps``; aggressive fills pay ``taker_bps``.
    A maker *rebate* (negative maker_bps) is allowed — it is a real schedule,
    not negative friction on the price."""

    def __init__(self, maker_bps: float, taker_bps: float) -> None:
        if taker_bps < 0:
            msg = f"taker_bps must be >= 0, got {taker_bps}"
            raise ConfigurationError(msg)
        self.maker_bps = maker_bps
        self.taker_bps = taker_bps

    def commission(self, fill: ProposedFill) -> Decimal:
        bps = self.maker_bps if fill.passive else self.taker_bps
        return price_to_decimal(fill.price) * fill.qty * price_to_decimal(bps) / Decimal(10_000)
