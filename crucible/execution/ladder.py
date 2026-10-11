"""The realism-ladder execution simulator, Levels 0-4 (ADR-0012).

One simulator, composed from pluggable models:

- ``SpreadModel``: buy at ask / sell at bid around the reference price.
- ``LatencyModel``: seeded per-order delay; an order interacts with a bar
  only per the arrival rules below.
- slippage/impact model: adverse price adjustment on aggressive fills.
- ``CommissionModel``: fee per fill (maker/taker aware via ``passive``).
- participation caps (Level 3+): aggregate fills per symbol-bar capped at
  ``max_bar_vol * volume`` (invariant I6) and per-order at ``max_adv * ADV``;
  remainders rest and carry.

Arrival rules (ADR-0012): with ``effective_at = created_at + latency``,
- a bar with ``ts <= created_at`` is in the order's past: never interacts;
- ``effective_at >= bar.ts``: still in flight, skipped;
- ``effective_at <= bar.open_time``: full-bar interaction (open-referenced
  fills, through-limit checks over the whole bar);
- otherwise (mid-bar arrival): MARKET fills at the close side-adjusted (no
  intrabar benefit); path-dependent types (limits, stops) wait for the next
  bar because their trigger cannot be verified after arrival.

Pessimism rules enforced here:
- every aggressive fill is adverse-adjusted (spread then slippage/impact)
  and clamped into the bar's fill range, ``[low, high]`` widened to its quotes when it
  carries them (I5 raises on model bugs, ADR-0060);
- limits fill only when traded *through* (strictly; plus ``queue_bps`` at
  Level 3+); passive fills happen at the limit price, never better;
- stop-limits arm on the trigger bar and act from the next bar;
- trailing stops trail on *closed* extremes only (no intrabar credit);
- when both legs of an OCO pair could fill in one bar, the leg with the
  worse outcome for the strategy executes and the other is dropped;
- models lacking history reject the order (``InsufficientHistory``), they
  never guess.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING, Protocol

from crucible.accounting.ledger import price_to_decimal
from crucible.core import checkpoint as ckpt
from crucible.core.errors import CheckpointError, ConfigurationError, InvariantViolation
from crucible.core.interfaces import Snapshottable
from crucible.core.types import (
    FillId,
    OrderId,
    OrderSide,
    OrderState,
    OrderType,
    RealismLevel,
    TimeInForce,
    TimestampNs,
)
from crucible.execution.interfaces import ProposedFill
from crucible.execution.models import (
    BpsCommission,
    FixedBpsSlippage,
    InsufficientHistory,
    MarketStats,
    NoCommission,
    NoSlippage,
    NoSpread,
    ZeroLatency,
)
from crucible.orders.interfaces import MOC_CUTOFF_NS

if TYPE_CHECKING:
    from collections.abc import Mapping

    import numpy as np

    from crucible.core.events import BarEvent
    from crucible.core.types import Symbol
    from crucible.orders.manager import InMemoryOrderManager, ManagedOrder

# ------------------------------------------------------------- model slots


class SpreadModelLike(Protocol):
    """Bar-typed spread slot (the interfaces.py Protocols are event-generic;
    the ladder works on bars, so its slots are bar-typed)."""

    def half_spread(self, market: BarEvent, rng: np.random.Generator) -> float: ...


class LatencyModelLike(Protocol):
    def latency_ns(self, rng: np.random.Generator) -> int: ...


class PriceAdjusterLike(Protocol):
    def adjusted_price(
        self,
        reference_price: float,
        order: ManagedOrder,
        market: BarEvent,
        rng: np.random.Generator,
    ) -> float: ...


class CommissionModelLike(Protocol):
    def commission(self, fill: ProposedFill) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class ParticipationLimits:
    """Level 3+ liquidity constraints. ``max_bar_vol`` caps the *aggregate*
    quantity all orders may take from one bar; ``max_adv`` caps each order's
    per-bar quantity against trailing ADV. ``queue_bps`` is how far through a
    limit price the bar must trade before a resting order fills."""

    max_bar_vol: float | None = None
    max_adv: float | None = None
    queue_bps: float = 0.0

    def __post_init__(self) -> None:
        if self.max_bar_vol is not None and not 0 < self.max_bar_vol <= 1:
            msg = f"max_bar_vol must be in (0, 1], got {self.max_bar_vol}"
            raise ConfigurationError(msg)
        if self.max_adv is not None and not 0 < self.max_adv <= 1:
            msg = f"max_adv must be in (0, 1], got {self.max_adv}"
            raise ConfigurationError(msg)
        if self.queue_bps < 0:
            msg = f"queue_bps must be >= 0, got {self.queue_bps}"
            raise ConfigurationError(msg)


@dataclass(frozen=True, slots=True)
class ExecutionSetup:
    """The model bundle a run executes with. Built by the runner from config
    (via ``execution/registry.py``) or by :meth:`legacy` from the Level 0/1
    bps shorthand.

    ``stats`` is the *shared* trailing-history instance: impact models read
    from it and the simulator writes to it — they must be the same object.
    """

    spread: SpreadModelLike
    latency: LatencyModelLike
    slippage: PriceAdjusterLike
    commission: CommissionModelLike
    participation: ParticipationLimits | None
    stats: MarketStats

    @classmethod
    def legacy(
        cls, level: RealismLevel, slippage_bps: float, commission_bps: float
    ) -> ExecutionSetup:
        if level is RealismLevel.FRICTIONLESS and (slippage_bps or commission_bps):
            msg = "Level 0 is frictionless; set slippage_bps and commission_bps to 0"
            raise ConfigurationError(msg)
        return cls(
            spread=NoSpread(),
            latency=ZeroLatency(),
            slippage=FixedBpsSlippage(slippage_bps) if slippage_bps else NoSlippage(),
            commission=BpsCommission(commission_bps) if commission_bps else NoCommission(),
            participation=None,
            stats=MarketStats(),
        )


def validate_fill_within_bar(price: float, bar: BarEvent, order_id: OrderId) -> None:
    """Invariant I5: no fill outside the bar's fill range: ``[low, high]``, widened to the bar's
    quotes when it carries them (ADR-0060)."""
    low, high = bar.fill_range()
    if not (low <= price <= high):
        msg = (
            f"I5 violated: fill price {price} outside bar range "
            f"[{low}, {high}] (quote-widened when the bar carries quotes; "
            f"order_id={order_id}, symbol={bar.symbol}, "
            f"ts={bar.ts}). Fix the fill model; do not widen the bar."
        )
        raise InvariantViolation(msg)


# ----------------------------------------------------------------- results


@dataclass(frozen=True, slots=True)
class ExecutedFill:
    order_id: OrderId
    symbol: Symbol
    side: OrderSide
    qty: Decimal
    price: float
    commission: Decimal
    passive: bool = False


@dataclass(frozen=True, slots=True)
class OrderClosed:
    """A pending order that reached a terminal state without (fully) filling."""

    order_id: OrderId
    state: OrderState
    reason: str


@dataclass(slots=True)
class _Pending:
    effective_at: TimestampNs
    full_bars_rested: int = 0
    stop_armed: bool = False  # STOP_LIMIT: trigger seen, limit acts next bar
    trail_stop: float | None = None
    trail_extreme: float | None = None
    slices_done: int = 0


@dataclass(slots=True)
class _Candidate:
    order: ManagedOrder
    qty: Decimal
    price: float
    passive: bool
    # lower = worse for the strategy's counterparty-free PnL; used for OCO
    # adverse selection (computed as signed proceeds impact)
    adversity: float = 0.0
    exhausts_order: bool = True


class LadderExecutionSimulator:
    """Deterministic Level 0-4 execution against bar data."""

    supports_composite_orders = True

    def __init__(
        self,
        *,
        level: RealismLevel,
        order_manager: InMemoryOrderManager,
        spread: SpreadModelLike,
        latency: LatencyModelLike,
        slippage: PriceAdjusterLike,
        commission: CommissionModelLike,
        participation: ParticipationLimits | None,
        stats: MarketStats,
        rng: np.random.Generator,
    ) -> None:
        if level is RealismLevel.MICROSTRUCTURE:
            msg = "Level 5 (order-book replay) is not supported"
            raise ConfigurationError(msg)
        if participation is not None and level < RealismLevel.LIQUIDITY:
            msg = (
                f"participation caps are Level 3+; configured level is {level.name}. "
                "Raise realism_level or drop the participation block."
            )
            raise ConfigurationError(msg)
        self._level = level
        self._manager = order_manager
        self._spread = spread
        self._latency = latency
        self._slippage = slippage
        self._commission = commission
        self._participation = participation
        self._stats = stats
        self._rng = rng
        self._pending: dict[OrderId, _Pending] = {}
        self._reasons: dict[OrderId, list[tuple[int, str]]] = {}

    # ------------------------------------------------------------- helpers

    def _note(self, order_id: OrderId, ts: TimestampNs, reason: str) -> None:
        self._reasons.setdefault(order_id, []).append((int(ts), reason))

    def why_not_filled(self, order_id: OrderId) -> list[tuple[int, str]]:
        """Structured (ts, reason) trail for an order."""
        return list(self._reasons.get(order_id, []))

    def remove_pending(self, order_id: OrderId) -> None:
        self._pending.pop(order_id, None)

    def has_pending(self, order_id: OrderId) -> bool:
        return order_id in self._pending

    def _models(self) -> dict[str, object]:
        """The pluggable models by slot name; an unset optional slot is omitted."""
        slots: dict[str, object] = {
            "spread": self._spread,
            "latency": self._latency,
            "slippage": self._slippage,
            "commission": self._commission,
        }
        if self._participation is not None:
            slots["participation"] = self._participation
        return slots

    def _models_snapshot(self) -> dict[str, object]:
        return {
            name: model.snapshot() if isinstance(model, Snapshottable) else None
            for name, model in self._models().items()
        }

    def _restore_models(self, saved: Mapping[str, object]) -> None:
        """Restores every ``Snapshottable`` model in place; all-or-nothing (ADR-0048 pattern)."""
        models = self._models()
        if set(saved) != set(models):
            msg = (
                f"checkpoint has execution model states for {sorted(saved)} but this run "
                f"configures {sorted(models)}; resume with the same execution configuration"
            )
            raise CheckpointError(msg)
        # deep copy: a model's snapshot() may hand out live state that its restore() rewrites in
        # place, which would make an uncopied backup useless
        backup = copy.deepcopy(self._models_snapshot())
        try:
            self._apply_models(models, saved)
        except Exception:
            # any failure, not only CheckpointError: a model's restore may raise anything; a
            # failing rollback propagates with the original error as its context
            self._apply_models(models, backup)
            raise

    @staticmethod
    def _apply_models(models: Mapping[str, object], saved: Mapping[str, object]) -> None:
        for name, model in models.items():
            entry = saved[name]
            if isinstance(model, Snapshottable):
                model.restore(ckpt.expect(entry, dict, f"execution model {name} state"))
            elif entry is not None:
                msg = f"checkpoint has state for a stateless execution model ({name})"
                raise CheckpointError(msg)

    def snapshot(self) -> dict[str, object]:
        """Resting-order state, the ``why_not_filled`` trail and the state of every
        ``Snapshottable`` model (spread, latency, slippage, commission, participation;
        ADR-0056). The rng and ``MarketStats`` are engine-owned and snapshotted there."""
        return {
            "pending": {
                str(order_id): {
                    "effective_at": int(p.effective_at),
                    "full_bars_rested": p.full_bars_rested,
                    "stop_armed": p.stop_armed,
                    "trail_stop": p.trail_stop,
                    "trail_extreme": p.trail_extreme,
                    "slices_done": p.slices_done,
                }
                for order_id, p in self._pending.items()  # insertion order is state
            },
            "reasons": {str(order_id): list(trail) for order_id, trail in self._reasons.items()},
            "models": self._models_snapshot(),
        }

    def restore(self, state: Mapping[str, object]) -> None:
        """Rebuilds resting orders and the why-not-filled trail in place."""
        pending: dict[OrderId, _Pending] = {}
        for order_id, entry in ckpt.field_dict(state, "pending").items():
            raw = ckpt.expect(entry, dict, f"pending[{order_id}]")
            pending[OrderId(order_id)] = _Pending(
                effective_at=TimestampNs(ckpt.field(raw, "effective_at", int)),
                full_bars_rested=ckpt.field(raw, "full_bars_rested", int),
                stop_armed=ckpt.field(raw, "stop_armed", bool),
                trail_stop=ckpt.optional_number(raw, "trail_stop"),
                trail_extreme=ckpt.optional_number(raw, "trail_extreme"),
                slices_done=ckpt.field(raw, "slices_done", int),
            )
        reasons: dict[OrderId, list[tuple[int, str]]] = {}
        for order_id, trail in ckpt.field_dict(state, "reasons").items():
            entries: list[tuple[int, str]] = []
            for item in ckpt.expect(trail, list, f"reasons[{order_id}]"):
                pair = ckpt.expect(item, tuple, f"reasons[{order_id}] item")
                if len(pair) != 2 or not isinstance(pair[0], int) or not isinstance(pair[1], str):
                    msg = f"checkpoint reasons[{order_id}] items must be (ts, reason), got {pair!r}"
                    raise CheckpointError(msg)
                entries.append((pair[0], pair[1]))
            reasons[OrderId(order_id)] = entries
        self._restore_models(ckpt.field_dict(state, "models"))
        self._pending = pending
        self._reasons = reasons

    def _adjust_aggressive(self, reference: float, order: ManagedOrder, bar: BarEvent) -> float:
        half = self._spread.half_spread(bar, self._rng)
        at_touch = reference + half if order.side is OrderSide.BUY else reference - half
        adjusted = self._slippage.adjusted_price(at_touch, order, bar, self._rng)
        low, high = bar.fill_range()
        clamped = min(max(adjusted, low), high)
        validate_fill_within_bar(clamped, bar, order.id)
        return clamped

    def _adversity(self, order: ManagedOrder, price: float, qty: Decimal) -> float:
        """Signed cash impact of the fill; lower = worse for the strategy."""
        signed = float(qty) if order.side is OrderSide.SELL else -float(qty)
        return signed * price

    # ------------------------------------------------------------ lifecycle

    def on_order_submitted(
        self, order: ManagedOrder, current_bar: BarEvent | None
    ) -> list[ExecutedFill]:
        """Level 0: instant fill at the current close. Level 1+: rest with a
        seeded latency until the arrival rules admit a bar."""
        if self._level is RealismLevel.FRICTIONLESS:
            if current_bar is None or current_bar.symbol != order.symbol:
                msg = (
                    f"Level 0 instant fill needs the current bar of {order.symbol} "
                    f"(order_id={order.id}); submit orders from on_market of that symbol"
                )
                raise ConfigurationError(msg)
            if order.type is not OrderType.MARKET:
                msg = (
                    f"Level 0 supports MARKET orders only (order_id={order.id}); "
                    "path-dependent types need at least Level 1"
                )
                raise ConfigurationError(msg)
            price = current_bar.close
            validate_fill_within_bar(price, current_bar, order.id)
            qty = order.remaining_qty
            self._manager.apply_fill(order.id, qty, current_bar.ts)
            return [
                ExecutedFill(
                    order_id=order.id,
                    symbol=order.symbol,
                    side=order.side,
                    qty=qty,
                    price=price,
                    commission=Decimal("0"),
                )
            ]
        self.activate(order, order.created_at)
        return []

    def activate(self, order: ManagedOrder, at: TimestampNs) -> None:
        """Registers an order as resting; latency is drawn here, once."""
        effective = TimestampNs(int(at) + self._latency.latency_ns(self._rng))
        state = _Pending(effective_at=effective)
        if order.type is OrderType.TRAILING_STOP and order.stop_price is not None:
            state.trail_stop = order.stop_price
        self._pending[order.id] = state

    # ---------------------------------------------------------------- bars

    def on_bar(self, bar: BarEvent) -> tuple[list[ExecutedFill], list[OrderClosed]]:
        candidates: list[_Candidate] = []
        closed: list[OrderClosed] = []

        for order_id in list(self._pending):
            order = self._manager.get(order_id)
            if order.symbol != bar.symbol:
                continue
            pending = self._pending[order_id]
            if bar.ts <= order.created_at:
                self._note(order_id, bar.ts, "bar predates order (no time travel)")
                continue
            if order.type is OrderType.MARKET_ON_CLOSE:
                moc = self._evaluate_moc(order, pending, bar, closed)
                if moc is not None:
                    candidates.append(moc)
                continue
            if pending.effective_at >= bar.ts:
                self._note(order_id, bar.ts, "in flight: latency not yet elapsed")
                continue
            full_bar = pending.effective_at <= bar.open_time
            try:
                candidate = self._evaluate(order, pending, bar, full_bar)
            except InsufficientHistory as exc:
                self._manager.transition(order_id, OrderState.REJECTED, bar.ts)
                del self._pending[order_id]
                self._note(order_id, bar.ts, f"rejected: {exc}")
                closed.append(
                    OrderClosed(order_id=order_id, state=OrderState.REJECTED, reason=str(exc))
                )
                continue
            if candidate is not None:
                candidates.append(candidate)
            elif full_bar:
                pending.full_bars_rested += 1
                if order.tif is TimeInForce.DAY and pending.full_bars_rested >= 2:
                    self._manager.transition(order_id, OrderState.EXPIRED, bar.ts)
                    del self._pending[order_id]
                    reason = "DAY order rested one full bar without executing"
                    self._note(order_id, bar.ts, reason)
                    closed.append(
                        OrderClosed(order_id=order_id, state=OrderState.EXPIRED, reason=reason)
                    )

        survivors = self._resolve_oco(candidates, bar)
        fills = self._apply(survivors, bar, closed)
        # stats update comes last: fills in this bar only ever saw history
        # up to the previous bar
        self._stats.update(bar.symbol, bar.close, bar.volume)
        return fills, closed

    # ----------------------------------------------------------- evaluation

    def _evaluate(
        self, order: ManagedOrder, pending: _Pending, bar: BarEvent, full_bar: bool
    ) -> _Candidate | None:
        kind = order.type
        if kind is OrderType.MARKET:
            reference = bar.open if full_bar else bar.close
            price = self._adjust_aggressive(reference, order, bar)
            return _Candidate(
                order=order,
                qty=order.remaining_qty,
                price=price,
                passive=False,
                adversity=self._adversity(order, price, order.remaining_qty),
            )
        if not full_bar:
            self._note(
                order.id,
                bar.ts,
                "mid-bar arrival: path-dependent order waits for the next bar",
            )
            return None
        if kind is OrderType.LIMIT:
            return self._evaluate_limit(order, bar)
        if kind is OrderType.STOP:
            return self._evaluate_stop(order, bar, order.stop_price)
        if kind is OrderType.STOP_LIMIT:
            if not pending.stop_armed:
                if self._stop_triggered(order, bar, order.stop_price):
                    pending.stop_armed = True
                    self._note(
                        order.id,
                        bar.ts,
                        "stop triggered; limit leg acts from the next bar (ADR-0012)",
                    )
                else:
                    self._note(order.id, bar.ts, "stop not triggered")
                return None
            return self._evaluate_limit(order, bar)
        if kind is OrderType.TRAILING_STOP:
            return self._evaluate_trailing(order, pending, bar)
        if kind in (OrderType.TWAP, OrderType.VWAP, OrderType.PARTICIPATION):
            return self._evaluate_algo(order, pending, bar)
        msg = (
            f"order type {kind.name} is not simulated at Level {int(self._level)} "
            f"(order_id={order.id})"
        )
        raise ConfigurationError(msg)

    def _evaluate_moc(
        self, order: ManagedOrder, pending: _Pending, bar: BarEvent, closed: list[OrderClosed]
    ) -> _Candidate | None:
        """MARKET_ON_CLOSE (ADR-0074): waits for the bar that ends at ``close_at`` and fills at
        its close (the closing auction), adjusted adversely like any aggressive fill and clamped
        into the bar (I5). The order must have reached the market by ``close_at -
        MOC_CUTOFF_NS`` (the exchanges' cutoff); arriving later, or no bar ending at ``close_at``
        (a halt, a missing bar), ends it without a fill."""
        close_at = order.close_at
        assert close_at is not None  # enforced at creation
        if int(bar.event_time) < int(close_at):
            self._note(order.id, bar.ts, "market-on-close: waiting for the closing bar")
            return None
        if int(bar.event_time) > int(close_at):
            self._end(order, OrderState.EXPIRED, bar, closed, "no bar ended at the session close")
            return None
        if int(pending.effective_at) > int(close_at) - MOC_CUTOFF_NS:
            self._end(
                order,
                OrderState.REJECTED,
                bar,
                closed,
                "market-on-close arrived after the cutoff ten minutes before the close "
                "(missed the cutoff)",
            )
            return None
        price = self._adjust_aggressive(bar.close, order, bar)
        return _Candidate(
            order=order,
            qty=order.remaining_qty,
            price=price,
            passive=False,
            adversity=self._adversity(order, price, order.remaining_qty),
        )

    def _end(
        self,
        order: ManagedOrder,
        state: OrderState,
        bar: BarEvent,
        closed: list[OrderClosed],
        reason: str,
    ) -> None:
        self._manager.transition(order.id, state, bar.ts)
        del self._pending[order.id]
        self._note(order.id, bar.ts, reason)
        closed.append(OrderClosed(order_id=order.id, state=state, reason=reason))

    def _queue_threshold(self, limit: float, side: OrderSide) -> float:
        queue_bps = self._participation.queue_bps if self._participation else 0.0
        factor = queue_bps / 10_000.0
        return limit * (1.0 - factor) if side is OrderSide.BUY else limit * (1.0 + factor)

    @staticmethod
    def _limit_touch(order: ManagedOrder, bar: BarEvent) -> tuple[float, float]:
        """The open price and the best extreme a limit order is measured against: the traded
        prices, or, when the bar carries quotes, the side a taker would meet (the ask for a buy,
        the bid for a sell), so a limit between the mid and the quote does not fill as if the mid
        were tradable (ADR-0060)."""
        if bar.has_quotes():
            assert bar.ask_open is not None
            assert bar.ask_close is not None
            assert bar.bid_open is not None
            assert bar.bid_close is not None
            if order.side is OrderSide.BUY:
                return bar.ask_open, min(bar.ask_open, bar.ask_close)
            return bar.bid_open, max(bar.bid_open, bar.bid_close)
        return bar.open, bar.low if order.side is OrderSide.BUY else bar.high

    def _evaluate_limit(self, order: ManagedOrder, bar: BarEvent) -> _Candidate | None:
        limit = order.limit_price
        assert limit is not None  # enforced at creation
        open_price, extreme = self._limit_touch(order, bar)
        if order.side is OrderSide.BUY:
            if open_price < limit:
                # crossing at the open: aggressive, but never worse than the limit
                price = min(self._adjust_aggressive(bar.open, order, bar), limit)
                return _Candidate(
                    order=order,
                    qty=order.remaining_qty,
                    price=price,
                    passive=False,
                    adversity=self._adversity(order, price, order.remaining_qty),
                )
            if extreme < self._queue_threshold(limit, order.side):
                validate_fill_within_bar(limit, bar, order.id)
                return _Candidate(
                    order=order,
                    qty=order.remaining_qty,
                    price=limit,
                    passive=True,
                    adversity=self._adversity(order, limit, order.remaining_qty),
                )
            self._note(order.id, bar.ts, "price never traded through the limit")
            return None
        if open_price > limit:
            price = max(self._adjust_aggressive(bar.open, order, bar), limit)
            return _Candidate(
                order=order,
                qty=order.remaining_qty,
                price=price,
                passive=False,
                adversity=self._adversity(order, price, order.remaining_qty),
            )
        if extreme > self._queue_threshold(limit, order.side):
            validate_fill_within_bar(limit, bar, order.id)
            return _Candidate(
                order=order,
                qty=order.remaining_qty,
                price=limit,
                passive=True,
                adversity=self._adversity(order, limit, order.remaining_qty),
            )
        self._note(order.id, bar.ts, "price never traded through the limit")
        return None

    def _stop_triggered(self, order: ManagedOrder, bar: BarEvent, stop: float | None) -> bool:
        assert stop is not None  # enforced at creation
        if order.side is OrderSide.BUY:
            return bar.open >= stop or bar.high > stop
        return bar.open <= stop or bar.low < stop

    def _evaluate_stop(
        self, order: ManagedOrder, bar: BarEvent, stop: float | None
    ) -> _Candidate | None:
        assert stop is not None
        if order.side is OrderSide.BUY:
            if bar.open >= stop:
                reference = bar.open
            elif bar.high > stop:
                reference = stop
            else:
                self._note(order.id, bar.ts, "stop not triggered")
                return None
        elif bar.open <= stop:
            reference = bar.open
        elif bar.low < stop:
            reference = stop
        else:
            self._note(order.id, bar.ts, "stop not triggered")
            return None
        price = self._adjust_aggressive(reference, order, bar)
        return _Candidate(
            order=order,
            qty=order.remaining_qty,
            price=price,
            passive=False,
            adversity=self._adversity(order, price, order.remaining_qty),
        )

    def _evaluate_trailing(
        self, order: ManagedOrder, pending: _Pending, bar: BarEvent
    ) -> _Candidate | None:
        trail = (order.trail_bps or 0.0) / 10_000.0
        if pending.trail_stop is None:
            # first eligible bar: trail from its open; no intrabar credit
            pending.trail_stop = (
                bar.open * (1.0 + trail)
                if order.side is OrderSide.BUY
                else bar.open * (1.0 - trail)
            )
        candidate = self._evaluate_stop(order, bar, pending.trail_stop)
        if candidate is None and order.trail_bps is not None:
            # tighten from the *closed* bar's extreme, effective next bar
            if order.side is OrderSide.BUY:
                extreme = (
                    bar.low
                    if pending.trail_extreme is None
                    else min(pending.trail_extreme, bar.low)
                )
                pending.trail_extreme = extreme
                pending.trail_stop = min(pending.trail_stop, extreme * (1.0 + trail))
            else:
                extreme = (
                    bar.high
                    if pending.trail_extreme is None
                    else max(pending.trail_extreme, bar.high)
                )
                pending.trail_extreme = extreme
                pending.trail_stop = max(pending.trail_stop, extreme * (1.0 - trail))
            self._note(order.id, bar.ts, f"trailing stop now {pending.trail_stop:.6g}")
        return candidate

    def _evaluate_algo(
        self, order: ManagedOrder, pending: _Pending, bar: BarEvent
    ) -> _Candidate | None:
        if order.type is OrderType.PARTICIPATION:
            assert order.algo_rate is not None  # enforced at creation
            cap = price_to_decimal(order.algo_rate * bar.volume)
            qty = min(order.remaining_qty, cap)
            if qty <= 0:
                self._note(order.id, bar.ts, "participation slice is zero (no volume)")
                return None
            reference = (bar.high + bar.low + bar.close) / 3.0
            exhausts = qty == order.remaining_qty
        else:
            assert order.algo_bars is not None  # enforced at creation
            slices_left = order.algo_bars - pending.slices_done
            if slices_left <= 1:
                qty = order.remaining_qty
            else:
                qty = (order.remaining_qty / slices_left).quantize(
                    Decimal("0.000001"), rounding=ROUND_DOWN
                )
            if qty <= 0:
                qty = order.remaining_qty
            pending.slices_done += 1
            reference = (
                (bar.open + bar.high + bar.low + bar.close) / 4.0
                if order.type is OrderType.TWAP
                else (bar.high + bar.low + bar.close) / 3.0
            )
            exhausts = qty == order.remaining_qty
        price = self._adjust_aggressive(reference, order, bar)
        return _Candidate(
            order=order,
            qty=qty,
            price=price,
            passive=False,
            adversity=self._adversity(order, price, qty),
            exhausts_order=exhausts,
        )

    # ------------------------------------------------------ OCO resolution

    def _resolve_oco(self, candidates: list[_Candidate], bar: BarEvent) -> list[_Candidate]:
        by_id = {c.order.id: c for c in candidates}
        survivors: list[_Candidate] = []
        resolved: set[OrderId] = set()  # already appended or dropped
        for candidate in candidates:
            oid = candidate.order.id
            if oid in resolved:
                continue
            sibling_id = candidate.order.oco_with
            if sibling_id is not None and sibling_id in by_id and sibling_id not in resolved:
                sibling = by_id[sibling_id]
                # both legs could fill this bar: the adverse one executes
                loser = candidate if candidate.adversity <= sibling.adversity else sibling
                winner = sibling if loser is candidate else candidate
                resolved.add(winner.order.id)
                resolved.add(loser.order.id)
                self._note(
                    winner.order.id,
                    bar.ts,
                    "OCO ambiguity: both legs triggered in one bar; the adverse "
                    f"leg {loser.order.id} executes (pessimistic intrabar)",
                )
                survivors.append(loser)
            else:
                resolved.add(oid)
                survivors.append(candidate)
        return survivors

    # ------------------------------------------------------------ applying

    def _apply(
        self, candidates: list[_Candidate], bar: BarEvent, closed: list[OrderClosed]
    ) -> list[ExecutedFill]:
        fills: list[ExecutedFill] = []
        bar_budget: Decimal | None = None
        if self._participation is not None and self._participation.max_bar_vol is not None:
            bar_budget = price_to_decimal(self._participation.max_bar_vol * bar.volume)

        for candidate in candidates:
            order = candidate.order
            qty = candidate.qty
            if self._participation is not None and self._participation.max_adv is not None:
                adv_cap = price_to_decimal(self._participation.max_adv) * price_to_decimal(
                    self._stats.adv(order.symbol)
                )
                qty = min(qty, adv_cap)
            if bar_budget is not None:
                qty = min(qty, bar_budget)
            if qty <= 0:
                self._note(order.id, bar.ts, "participation cap exhausted for this bar")
                continue
            if bar_budget is not None:
                if self._participation is not None and self._participation.max_bar_vol:
                    hard_cap = price_to_decimal(self._participation.max_bar_vol * bar.volume)
                    if qty > hard_cap:  # pragma: no cover - guarded by construction
                        msg = (
                            f"I6 violated: fill qty {qty} > participation cap {hard_cap} "
                            f"(order_id={order.id}, symbol={bar.symbol}, ts={bar.ts})"
                        )
                        raise InvariantViolation(msg)
                bar_budget -= qty

            self._manager.apply_fill(order.id, qty, bar.ts)
            proposed = ProposedFill(
                order_id=order.id,
                fill_id=FillId("pending"),
                ts=bar.ts,
                qty=qty,
                price=candidate.price,
                passive=candidate.passive,
            )
            fee = self._commission.commission(proposed)
            fills.append(
                ExecutedFill(
                    order_id=order.id,
                    symbol=order.symbol,
                    side=order.side,
                    qty=qty,
                    price=candidate.price,
                    commission=fee,
                    passive=candidate.passive,
                )
            )
            if order.state is OrderState.FILLED:
                del self._pending[order.id]
                self._on_full_fill(order, bar, closed)
            else:
                self._note(
                    order.id,
                    bar.ts,
                    f"partial fill {qty} (remaining {order.remaining_qty}): "
                    "liquidity/participation constrained",
                )
        return fills

    def _on_full_fill(self, order: ManagedOrder, bar: BarEvent, closed: list[OrderClosed]) -> None:
        # OCO: a fully filled leg cancels its sibling
        if order.oco_with is not None:
            sibling = self._manager.get(order.oco_with)
            if sibling.state not in (
                OrderState.FILLED,
                OrderState.CANCELLED,
                OrderState.REJECTED,
                OrderState.EXPIRED,
            ):
                self._manager.transition(sibling.id, OrderState.CANCELLED, bar.ts)
                self.remove_pending(sibling.id)
                reason = f"OCO sibling {order.id} filled"
                self._note(sibling.id, bar.ts, reason)
                closed.append(
                    OrderClosed(order_id=sibling.id, state=OrderState.CANCELLED, reason=reason)
                )
        # OTO/bracket: children waiting on this parent go live now
        for child in self._manager.all_orders():
            if child.parent_id == order.id and child.state is OrderState.CREATED:
                self._manager.transition(child.id, OrderState.SUBMITTED, bar.ts)
                self._manager.transition(child.id, OrderState.ACCEPTED, bar.ts)
                self.activate(child, bar.ts)
                self._note(child.id, bar.ts, f"activated by parent {order.id} fill")

    def parent_died(self, parent_id: OrderId, ts: TimestampNs) -> list[OrderClosed]:
        """Cancels CREATED children whose parent reached a terminal state
        without filling (bracket/OTO cleanup)."""
        closed: list[OrderClosed] = []
        for child in self._manager.all_orders():
            if child.parent_id == parent_id and child.state is OrderState.CREATED:
                self._manager.transition(child.id, OrderState.CANCELLED, ts)
                reason = f"parent {parent_id} terminated unfilled"
                self._note(child.id, ts, reason)
                closed.append(
                    OrderClosed(order_id=child.id, state=OrderState.CANCELLED, reason=reason)
                )
        return closed
