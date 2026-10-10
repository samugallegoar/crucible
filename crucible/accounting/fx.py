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


def convert_at_mid(
    amount: Decimal, ccy: Currency, base: Currency, mid_rates: Mapping[Currency, Decimal]
) -> Decimal:
    """Marking role: ``amount`` (in ``ccy``) valued in ``base`` at the mid
    rate. Identity when ``ccy == base`` -- no rate lookup needed for a
    single-currency portfolio."""
    if ccy == base:
        return amount
    rate = mid_rates.get(ccy)
    if rate is None:
        msg = f"no FX mid rate available to convert {ccy} into {base}"
        raise CrucibleError(msg)
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
    if ccy == base:
        return amount
    rate = mid_rates.get(ccy)
    if rate is None:
        msg = f"no FX mid rate available to convert {base} into {ccy}"
        raise CrucibleError(msg)
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
