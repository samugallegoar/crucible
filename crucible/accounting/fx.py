"""FX conversion helpers (ADR-0009).

Two roles, two rates, never mixed:
- **Marking** (equity, exposures, reporting): the mid rate. A valuation,
  not a trade -- never moves ledger cash.
- **Trading** (an actual currency conversion that moves ledger cash): the
  adverse side of the quoted spread for the direction converted. Pessimism
  rule (AGENTS.md §10): money that actually moves is never priced
  favorably to the party initiating the move.

A currency-conversion transaction itself needs no new ledger machinery:
``TransactionRecord.amounts`` is already ``Mapping[Currency, Decimal]``,
and ``InMemoryLedger.fold`` already applies every currency's delta
generically. Converting currency is just a transaction with two amounts
(negative in the currency sold, positive in the currency bought) computed
via :func:`convert_at_adverse`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from crucible.core.errors import CrucibleError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crucible.core.types import Currency


def _checked_rate(rate: Decimal | None, ccy: Currency, base: Currency, direction: str) -> Decimal:
    """A marking rate must be finite and strictly positive: a zero or negative mid silently
    zeroed or inverted equity while every accounting identity still passed (2026-10 audit)."""
    if rate is None:
        msg = f"no FX mid rate available to convert {direction}"
        raise CrucibleError(msg)
    if not rate.is_finite() or rate <= 0:
        msg = (
            f"FX mid rate {ccy}->{base} is {rate}, which is not a usable price: a marking rate "
            "must be finite and strictly positive. Fix the fx_rates dataset row "
            "(or the symbol's pair) before running"
        )
        raise CrucibleError(msg)
    return rate


def convert_at_mid(
    amount: Decimal, ccy: Currency, base: Currency, mid_rates: Mapping[Currency, Decimal]
) -> Decimal:
    """Marking role: ``amount`` (in ``ccy``) valued in ``base`` at the mid
    rate. Identity when ``ccy == base`` -- no rate lookup needed for a
    single-currency portfolio."""
    if ccy == base or amount == 0:
        return amount
    rate = _checked_rate(mid_rates.get(ccy), ccy, base, f"{ccy} into {base}")
    return amount * rate


def convert_from_base_at_mid(
    amount: Decimal, base: Currency, ccy: Currency, mid_rates: Mapping[Currency, Decimal]
) -> Decimal:
    """Marking role, inverse direction of :func:`convert_at_mid`: ``amount``
    (in ``base``) valued in ``ccy`` at the mid rate -- used to size a
    target position denominated in ``ccy`` from a weight expressed as a
    fraction of base-currency equity (ADR-0029). Identity when
    ``ccy == base``. ``mid_rates`` is still keyed ``ccy -> base`` (ADR-0009's
    one direction), so this divides rather than multiplies."""
    if ccy == base or amount == 0:
        return amount
    rate = _checked_rate(mid_rates.get(ccy), ccy, base, f"{base} into {ccy}")
    return amount / rate


def convert_at_adverse(amount: Decimal, *, bid: Decimal, ask: Decimal, buying: bool) -> Decimal:
    """Trading role: a real conversion that moves ledger cash always gets
    the adverse side. ``buying=True`` acquires the quoted currency (pay
    the higher ``ask``); ``buying=False`` sells it (receive the lower
    ``bid``). Refuses a crossed or inverted quote (``bid > ask``) rather
    than silently computing a nonsensical amount."""
    if bid > ask:
        msg = f"invalid FX quote: bid={bid} > ask={ask}"
        raise CrucibleError(msg)
    return amount * (ask if buying else bid)
