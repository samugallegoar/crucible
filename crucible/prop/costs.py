"""Per-component execution costs as the prop engine sees them (ADR-0107 section 10).

A firm's per-side commission is not one number but five components, and a ruleset declares what the
firm says about each of them (``exchange``, ``clearing``, ``nfa``, ``other``):

- ``included`` — the firm's per-side commission contains the component: nothing is added;
- ``excluded`` — the firm charges it on top: the amount comes from the fee dataset, for the run's
  participant type, on the attempt's date;
- ``unknown`` — the sources do not say: a gap, never a zero cost.

**Unknown is never zero.** A component with no stated status, or an excluded one the dataset cannot
price, is a named gap. With any gap left the attempt's cash statistic is ``unavailable``; the only
way to a number is a ``CostAssumption`` FILE the user passes explicitly, which prices the exact
root and component it names (see :func:`load_cost_assumption`). The assumption is unverified by
construction and the estimate stays ``conditional``.

**No universal fee, no extrapolation.** :class:`ComponentFeeRow` and the stored
``exchange_fees_v1`` dataset price exactly their root, participant type and date range; a row that
covers several components is charged once. The engine never maps a CME product bucket to a root,
and the participant type used for ``excluded`` components is a run parameter, never a ruleset value.

Amounts are per contract per side in USD, like ``CostSchedule.exchange_fee``. This module is
deterministic: no clock, no network, no global RNG.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import yaml

from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.prop.rules_schema import COST_COMPONENTS, CostComponents

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from crucible.data.interfaces import DataStore
    from crucible.execution.futures_sim import CostSchedule

COMPONENTS_WITH_COMMISSION: tuple[str, ...] = ("commission", *COST_COMPONENTS)
"""Every per-side cost a prop-firm account pays: the firm's commission plus the four components.

A ``cost_assumption`` file may price any of them; a ruleset declares the commission and the four
component statuses."""

SCHEDULE_FIELD: dict[str, str] = {
    "commission": "commission",
    "exchange": "exchange_fee",
    "clearing": "clearing_fee",
    "nfa": "regulatory_fee",
    "other": "other_fee",
}
"""Which ``CostSchedule`` field a component is charged through."""

FEE_SOURCE_DATASET = "exchange_fees_v1"
"""The dataset a :class:`StoreComponentFees` reads by default."""

_ASSUMPTION_KEYS: tuple[str, ...] = (
    "name",
    "description",
    "provided_by",
    "status",
    "evidence",
    "amounts",
)
"""The exact keys a cost-assumption file carries; any other key is refused."""

_HEX64 = 64
_COVERS_SEPARATOR = ";"


# ----------------------------------------------------------------------------- the fee dataset


@dataclass(frozen=True, slots=True)
class FeeRow:
    """One component's per-side amount, with the hash of the stored row it came from."""

    component: str
    per_side_usd: Decimal
    record_sha256: str

    def __post_init__(self) -> None:
        if self.component not in COST_COMPONENTS:
            msg = f"fee row component {self.component!r} is not one of {list(COST_COMPONENTS)}"
            raise ConfigurationError(msg)
        if not self.per_side_usd.is_finite() or self.per_side_usd < 0:
            msg = f"fee row {self.component} amount {self.per_side_usd} must be a finite USD >= 0"
            raise ConfigurationError(msg)
        if len(self.record_sha256) != _HEX64:
            msg = (
                f"fee row {self.component} needs the record_sha256 of the row it was read from, "
                f"got {len(self.record_sha256)} characters"
            )
            raise ConfigurationError(msg)


@runtime_checkable
class ComponentFeeSource(Protocol):
    """What the attempt's pricing needs: the amounts in force for a root on a date.

    ``rows_for`` returns only the components the source can price: a component it has no row for is
    ABSENT from the result, never returned as a zero. An implementation must be deterministic (no
    clock, no network) and must refuse (raise ``CrucibleError``) rather than choose between two rows
    that cover the same component on the same date.
    """

    def rows_for(
        self,
        root: str,
        when: dt.date,
        *,
        participant_type: str,
        components: Sequence[str],
    ) -> dict[str, FeeRow]:
        """``{component: FeeRow}`` for the components this source can price."""
        ...

    @property
    def source_sha256(self) -> str:
        """The hash of the table the amounts came from (dataset content hash or file hash)."""
        ...


@dataclass(frozen=True, slots=True)
class ComponentFeeRow:
    """One row of a fee table written down in code (a test, or a firm's own schedule).

    ``covers`` lists the components the amount covers and must contain ``fee_type``: a CME
    "Exchange Fees for Clearing & Trading" cell is ``fee_type="exchange"`` with
    ``covers=("exchange", "clearing")``, and it is charged once for both.
    """

    root: str
    fee_type: str
    participant_type: str
    covers: tuple[str, ...]
    per_side_usd: Decimal
    effective_from: dt.date
    effective_to: dt.date | None = None

    def __post_init__(self) -> None:
        if not self.root or self.root != self.root.upper():
            msg = f"fee row root {self.root!r} must be a non-empty upper-case root"
            raise ConfigurationError(msg)
        if self.fee_type not in COST_COMPONENTS:
            msg = f"fee row fee_type {self.fee_type!r} is not one of {list(COST_COMPONENTS)}"
            raise ConfigurationError(msg)
        if not self.covers:
            msg = f"fee row {self.root} {self.fee_type}: covers is empty; list its components"
            raise ConfigurationError(msg)
        unknown = [name for name in self.covers if name not in COST_COMPONENTS]
        if unknown:
            msg = f"fee row {self.root} {self.fee_type}: covers names {unknown}, not a component"
            raise ConfigurationError(msg)
        if self.fee_type not in self.covers:
            msg = (
                f"fee row {self.root} {self.fee_type}: covers {list(self.covers)} does not contain "
                "its own fee_type; a row prices the component it is typed as"
            )
            raise ConfigurationError(msg)
        if not self.participant_type.strip():
            msg = f"fee row {self.root} {self.fee_type}: participant_type is empty"
            raise ConfigurationError(msg)
        if not self.per_side_usd.is_finite() or self.per_side_usd < 0:
            msg = (
                f"fee row {self.root} {self.fee_type}: per_side_usd = {self.per_side_usd} USD per "
                "side must be >= 0"
            )
            raise ConfigurationError(msg)
        if self.effective_to is not None and self.effective_to < self.effective_from:
            msg = (
                f"fee row {self.root} {self.fee_type}: effective_to {self.effective_to} is before "
                f"effective_from {self.effective_from}"
            )
            raise ConfigurationError(msg)

    def covers_date(self, when: dt.date) -> bool:
        """Whether this row's date range contains ``when`` (both ends inclusive)."""
        return self.effective_from <= when and (
            self.effective_to is None or when <= self.effective_to
        )

    @property
    def record_sha256(self) -> str:
        """The row's own identity hash: two components one row covers share it, two rows never do.

        It is what lets the pricing charge ONE row once for every component it covers, without
        splitting an amount the source states as a single cell.
        """
        payload = {
            "root": self.root,
            "fee_type": self.fee_type,
            "participant_type": self.participant_type,
            "covers": list(self.covers),
            "per_side_usd": str(self.per_side_usd),
            "effective_from": self.effective_from.isoformat(),
            "effective_to": None if self.effective_to is None else self.effective_to.isoformat(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ComponentFeeTable:
    """A table of :class:`ComponentFeeRow` with the hash of the document it came from.

    Two rows may not cover the same component of the same key on the same date: an ambiguous fee is
    refused, never resolved by row order. ``nfa`` is keyed without the participant type, because it
    is the FCM member's pass-through assessment and prices any requested type.
    """

    rows: tuple[ComponentFeeRow, ...]
    source_sha256: str

    def __post_init__(self) -> None:
        if len(self.source_sha256) != _HEX64:
            msg = (
                f"fee table source_sha256 must be {_HEX64} hex characters, got "
                f"{len(self.source_sha256)}: a fee without its source cannot be checked"
            )
            raise ConfigurationError(msg)
        if not self.rows:
            msg = "fee table needs at least one row"
            raise ConfigurationError(msg)
        grouped: dict[tuple[str, str, str], list[ComponentFeeRow]] = {}
        for row in self.rows:
            for component in row.covers:
                key = (
                    (row.root, "*", component)
                    if component == "nfa"
                    else (row.root, row.participant_type, component)
                )
                grouped.setdefault(key, []).append(row)
        for (root, participant_type, component), group in sorted(grouped.items()):
            ordered = sorted(group, key=lambda row: row.effective_from)
            for earlier, later in itertools.pairwise(ordered):
                if earlier.effective_to is None or later.effective_from <= earlier.effective_to:
                    label = (
                        f"{root} {component}"
                        if participant_type == "*"
                        else f"{root} {participant_type} {component}"
                    )
                    msg = (
                        f"fee table rows for {label} overlap at {later.effective_from}: one row "
                        "per key per period, otherwise the fee is ambiguous"
                    )
                    raise ConfigurationError(msg)

    def rows_for(
        self,
        root: str,
        when: dt.date,
        *,
        participant_type: str,
        components: Sequence[str],
    ) -> dict[str, FeeRow]:
        """``{component: FeeRow}`` from the rows in force on ``when`` for this key."""
        out: dict[str, FeeRow] = {}
        for component in components:
            found = [
                row
                for row in self.rows
                if row.root == root
                and component in row.covers
                and row.covers_date(when)
                and (component == "nfa" or row.participant_type == participant_type)
            ]
            if found:
                out[component] = FeeRow(
                    component=component,
                    per_side_usd=found[0].per_side_usd,
                    record_sha256=found[0].record_sha256,
                )
        return out


@dataclass(frozen=True, slots=True)
class StoreComponentFees:
    """``ComponentFeeSource`` over the stored ``exchange_fees_v1`` dataset.

    Every component read goes through ``crucible.data.exchange_fees.fee_rows_as_of``, which prices
    ONE root for ONE participant type on ONE date: an owner file that prices ES alone is usable, and
    a component it does not cover is absent (a gap for the caller), never a zero.

    The dataset's own content hash is the source hash the result records, so an attempt can be
    traced to the exact table it priced with.
    """

    store: DataStore
    content_hash: str
    dataset: str | None = None
    """The dataset name to read instead of the default ``exchange_fees_v1`` (``None``: default)."""

    def rows_for(
        self,
        root: str,
        when: dt.date,
        *,
        participant_type: str,
        components: Sequence[str],
    ) -> dict[str, FeeRow]:
        """``{component: FeeRow}`` the stored table prices for ``root`` on ``when``."""
        from crucible.core.types import DatasetId
        from crucible.data.exchange_fees import fee_rows_as_of

        priced = fee_rows_as_of(
            self.store,
            root,
            when,
            participant_type=participant_type,
            components=components,
            dataset=None if self.dataset is None else DatasetId(self.dataset),
        )
        return {
            component: FeeRow(component=component, per_side_usd=amount, record_sha256=record_sha256)
            for component, (amount, record_sha256) in priced.items()
        }

    @property
    def source_sha256(self) -> str:
        """The dataset's content hash: the table an attempt cites is the one it priced with."""
        return self.content_hash


def store_component_fees(store: DataStore, *, dataset: str | None = None) -> StoreComponentFees:
    """The ``ComponentFeeSource`` over ``store``'s fee dataset, citing its content hash.

    A store without the dataset is refused here, by name: an attempt that would price no excluded
    component must say so, not proceed with zero. ``dataset`` reads another built version.
    """
    from crucible.core.types import DatasetId
    from crucible.data.exchange_fees import DATASET

    name = DATASET if dataset is None else DatasetId(dataset)
    try:
        manifest = store.manifest(name)
    except (CrucibleError, KeyError, OSError) as exc:
        msg = (
            f"cannot read dataset {DATASET} from this store: {exc}. Build it with "
            "crucible.data.exchange_fees.build_exchange_fees, or pass a ComponentFeeSource"
        )
        raise ConfigurationError(msg) from exc
    return StoreComponentFees(store=store, content_hash=manifest.content_hash, dataset=dataset)


# ------------------------------------------------------------------------ the cost assumption


@dataclass(frozen=True, slots=True)
class AssumptionAmount:
    """One amount of a cost-assumption file: what it covers, for the root it sits under."""

    covers: tuple[str, ...]
    per_side_usd: Decimal

    def __post_init__(self) -> None:
        if not self.covers:
            msg = "a cost-assumption amount needs a non-empty covers list"
            raise ConfigurationError(msg)
        unknown = [name for name in self.covers if name not in COMPONENTS_WITH_COMMISSION]
        if unknown:
            msg = (
                f"a cost-assumption amount covers {unknown}, which is not one of "
                f"{list(COMPONENTS_WITH_COMMISSION)}"
            )
            raise ConfigurationError(msg)
        if len(set(self.covers)) != len(self.covers):
            msg = f"a cost-assumption amount repeats a component in {list(self.covers)}"
            raise ConfigurationError(msg)
        if not self.per_side_usd.is_finite() or self.per_side_usd < 0:
            msg = (
                f"a cost-assumption amount of {self.per_side_usd} USD per side must be a finite "
                "USD >= 0"
            )
            raise ConfigurationError(msg)


@dataclass(frozen=True, slots=True)
class CostAssumption:
    """An unverified, owner-provided per-side cost estimate for named roots and components.

    It exists so a gap can become a NUMBER rather than a silence, and it is never a firm value: the
    file says who supplied it, what its evidence is, and that its status is ``unverified``. An
    entry applies only to the root and component it lists (there is no extrapolation to another
    root), it may not override a component the ruleset declares ``included`` or one the dataset
    already priced, and an ``unknown`` component it prices is ADDED — worse for the strategy, which
    is the pessimistic direction.
    """

    name: str
    description: str
    provided_by: str
    status: str
    evidence: str
    amounts: Mapping[str, tuple[AssumptionAmount, ...]]
    sha256: str
    source_path: str

    def __post_init__(self) -> None:
        if self.status != "unverified":
            msg = (
                f"cost assumption {self.name!r}: status must be 'unverified' (a file cannot "
                f"verify a cost), got {self.status!r}"
            )
            raise ConfigurationError(msg)
        if len(self.sha256) != _HEX64:
            msg = (
                f"cost assumption {self.name!r} needs the SHA-256 of its file, got "
                f"{len(self.sha256)} characters"
            )
            raise ConfigurationError(msg)
        if not self.amounts:
            msg = f"cost assumption {self.name!r} declares no root: it prices nothing"
            raise ConfigurationError(msg)

    def amount_for(self, root: str, component: str) -> AssumptionAmount | None:
        """The entry pricing ``root``'s ``component``, or ``None`` when the file does not."""
        for entry in self.amounts.get(root, ()):
            if component in entry.covers:
                return entry
        return None

    @property
    def roots(self) -> tuple[str, ...]:
        """The roots the file prices, in file order."""
        return tuple(self.amounts)

    def unused_roots(self, roots: Sequence[str]) -> tuple[str, ...]:
        """The file's roots the run does not trade: allowed, and reported rather than dropped."""
        run = set(roots)
        return tuple(root for root in self.amounts if root not in run)


def _assumption_decimal(value: object, *, where: str) -> Decimal:
    """A money amount from the file, as a ``Decimal``; refuses anything that is not one."""
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        msg = f"{where}: per_side_usd must be a decimal string such as '1.07', got {value!r}"
        raise ConfigurationError(msg)
    text = str(value).strip().replace("$", "")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        msg = f"{where}: cannot read per_side_usd {value!r} as a money amount"
        raise ConfigurationError(msg) from exc
    return amount


def load_cost_assumption(path: Path) -> CostAssumption:
    """Load a cost-assumption YAML file, with the SHA-256 of its own bytes.

    The file is the user's explicit statement that they accept a cost they cannot source:

    .. code-block:: yaml

        name: owner-estimate-2026-11-22
        description: the owner's working all-in figure, composition unknown
        provided_by: owner
        status: unverified
        evidence: the owner's note of 2026-11-22; no document states the split
        amounts:
          ES:
            - covers: [commission]
              per_side_usd: "0.77"
            - covers: [exchange, clearing]
              per_side_usd: "0.41"

    Every key is required and no other key is accepted, ``status`` must be ``unverified``, the
    roots are upper-case and the ``covers`` names are cost components. An amount applies only to
    its own root and components: an assumption never extrapolates to another root, and it is never
    reported as a firm value or as a complete cost.
    """
    if not path.is_file():
        msg = f"cost assumption {path} does not exist: pass the YAML file, or omit the assumption"
        raise ConfigurationError(msg)
    body = path.read_bytes()
    sha = hashlib.sha256(body).hexdigest()
    try:
        document = yaml.safe_load(body.decode("utf-8"))
    except yaml.YAMLError as exc:
        msg = f"cost assumption {path} is not valid YAML: {exc}"
        raise ConfigurationError(msg) from exc
    if not isinstance(document, dict):
        msg = f"cost assumption {path}: the file must be a mapping with {list(_ASSUMPTION_KEYS)}"
        raise ConfigurationError(msg)
    missing = [key for key in _ASSUMPTION_KEYS if key not in document]
    if missing:
        msg = f"cost assumption {path}: missing key(s) {missing}; it needs {list(_ASSUMPTION_KEYS)}"
        raise ConfigurationError(msg)
    unknown = [key for key in document if key not in _ASSUMPTION_KEYS]
    if unknown:
        msg = (
            f"cost assumption {path}: unknown key(s) {unknown}; it may only carry "
            f"{list(_ASSUMPTION_KEYS)}"
        )
        raise ConfigurationError(msg)
    for key in ("name", "description", "provided_by", "evidence"):
        if not str(document[key]).strip():
            msg = f"cost assumption {path}: {key} is empty; a cost nobody states is not a cost"
            raise ConfigurationError(msg)
    raw_amounts = document["amounts"]
    if not isinstance(raw_amounts, dict):
        msg = f"cost assumption {path}: amounts must be a mapping root -> list of entries"
        raise ConfigurationError(msg)
    amounts: dict[str, tuple[AssumptionAmount, ...]] = {}
    for root, entries in raw_amounts.items():
        root_text = str(root).strip()
        if not root_text or root_text != root_text.upper():
            msg = f"cost assumption {path}: root {root!r} must be a non-empty upper-case root"
            raise ConfigurationError(msg)
        if not isinstance(entries, list) or not entries:
            msg = (
                f"cost assumption {path}: root {root_text} needs a non-empty list of "
                "{covers, per_side_usd} entries"
            )
            raise ConfigurationError(msg)
        parsed: list[AssumptionAmount] = []
        for index, entry in enumerate(entries, start=1):
            where = f"{path.name}: {root_text} entry {index}"
            if not isinstance(entry, dict):
                msg = f"{where}: an entry must be {{covers, per_side_usd}}"
                raise ConfigurationError(msg)
            extra = [key for key in entry if key not in ("covers", "per_side_usd")]
            if extra:
                msg = f"{where}: unknown key(s) {extra}; an entry is {{covers, per_side_usd}}"
                raise ConfigurationError(msg)
            covers = entry.get("covers")
            if isinstance(covers, str):
                covers = [part.strip() for part in covers.split(_COVERS_SEPARATOR) if part.strip()]
            if not isinstance(covers, list) or not covers:
                msg = f"{where}: covers must be a non-empty list of component names"
                raise ConfigurationError(msg)
            parsed.append(
                AssumptionAmount(
                    covers=tuple(str(name).strip() for name in covers),
                    per_side_usd=_assumption_decimal(entry.get("per_side_usd"), where=where),
                )
            )
        seen: dict[str, int] = {}
        for index, entry in enumerate(parsed, start=1):
            for name in entry.covers:
                if name in seen:
                    msg = (
                        f"{path.name}: {root_text} {name} is priced twice (entry {seen[name]} and "
                        f"entry {index}): one amount per root and component"
                    )
                    raise ConfigurationError(msg)
                seen[name] = index
        amounts[root_text] = tuple(parsed)
    return CostAssumption(
        name=str(document["name"]).strip(),
        description=str(document["description"]).strip(),
        provided_by=str(document["provided_by"]).strip(),
        status=str(document["status"]).strip(),
        evidence=str(document["evidence"]).strip(),
        amounts=amounts,
        sha256=sha,
        source_path=str(path),
    )


# ------------------------------------------------------------------------------ the pricing


@dataclass(frozen=True, slots=True)
class ComponentCharge:
    """One component's status and the USD per side it adds on top of the commission.

    ``status`` is ``included`` (inside the commission, nothing added), ``excluded_priced`` (added
    from the fee dataset), ``covered_by_row`` (a row that covers several components is charged
    once: its other components carry this status and add nothing), ``excluded_unpriced`` (excluded
    but the dataset has no row: a gap), ``unknown`` (the sources are silent: a gap) and
    ``assumption`` (a gap the cost-assumption file priced) — and for the commission itself
    ``known``, ``unknown`` or ``assumption``.

    ``usd`` is the amount CHARGED for the component: ``0`` for an included component (it is inside
    the commission), the dataset or assumption amount for a priced one, and ``None`` for a gap.
    """

    component: str
    status: str
    usd: Decimal | None
    detail: str

    @property
    def gap(self) -> bool:
        """Whether this component is a gap (no amount may be charged for it)."""
        return self.usd is None


@dataclass(frozen=True, slots=True)
class CostPricing:
    """The attempt's per-side cost: every component, the schedule and what is still missing."""

    charges: tuple[ComponentCharge, ...]
    schedule: CostSchedule
    gaps: tuple[str, ...]
    status: str
    assumption: CostAssumption | None = None
    priced_by_assumption: tuple[str, ...] = ()
    participant_type: str | None = None

    def component_charge(self, component: str) -> ComponentCharge:
        """One component's charge: the commission, exchange, clearing, nfa or other."""
        for item in self.charges:
            if item.component == component:
                return item
        msg = f"no charge recorded for component {component!r}"
        raise ConfigurationError(msg)

    @property
    def gap_text(self) -> str | None:
        """The gaps as one sentence naming each component and why it is a gap, or ``None``."""
        if not self.gaps:
            return None
        return "; ".join(f"{item.component}: {item.detail}" for item in self.charges if item.gap)

    @property
    def fees_per_side(self) -> Decimal:
        """Every known component's per-side amount, which is what the simulator charges."""
        return self.schedule.fees_per_side

    @property
    def reasons(self) -> tuple[str, ...]:
        """Why the cost is not exact, in the vocabulary of the attempt's cash statistic."""
        out: list[str] = []
        if self.gaps:
            for item in self.charges:
                if item.gap:
                    out.append(f"{item.component}: {item.detail}")
        if self.assumption is not None:
            label = (
                f"cost assumption {self.assumption.name!r} "
                f"(sha256 {self.assumption.sha256[:12]}...) priced "
                + ", ".join(self.priced_by_assumption)
                if self.priced_by_assumption
                else f"cost assumption {self.assumption.name!r} was used"
            )
            out.append(label)
        if self.participant_type is not None:
            out.append(f"participant type assumed: {self.participant_type}")
        return tuple(out)


def price_components(
    *,
    components: CostComponents,
    commission_status: str,
    commission_per_side: Decimal | None,
    root: str,
    when: dt.date,
    costs: CostSchedule,
    fee_source: ComponentFeeSource | None = None,
    participant_type: str | None = None,
    assumption: CostAssumption | None = None,
) -> CostPricing:
    """Price one root's per-side cost on ``when``, component by component (ADR-0107 s10).

    The order is fixed, and it is the order the report reads:

    1. the commission: ``known`` with its per-side amount, or a gap when the ruleset says
       ``unknown``;
    2. each component, by its declared status — ``included`` adds nothing, ``excluded`` adds the
       fee dataset's amount for the run's participant type (a gap when there is no row),
       ``unknown`` is a gap;
    3. the cost-assumption file, which prices the exact gaps it names for this exact root.

    ``status`` is ``complete`` when nothing is a gap and no assumption or participant type was
    needed, ``conditional`` when an assumption or the participant type supplied a value, and
    ``unavailable`` when any gap remains. ``excluded`` components need ``participant_type``: it is
    refused when missing, because the dataset prices a rate class and the ruleset never states one.

    A gap is never charged as zero: the returned schedule keeps no amount for it, and the caller
    must not present the total as complete.
    """
    excluded = components.of_status("excluded")
    if excluded and participant_type is None:
        raise ConfigurationError(
            f"the commission for {root} declares {list(excluded)} excluded, so the dataset must "
            "price them for a participant type: pass fee_participant_type "
            "(--fee-participant-type) — the ruleset never states one, and a member rate is not a "
            "customer rate"
        )
    charges: dict[str, ComponentCharge] = {}
    gaps: list[str] = []
    if commission_status == "known" and commission_per_side is not None:
        charges["commission"] = ComponentCharge(
            component="commission",
            status="known",
            usd=commission_per_side,
            detail="the firm's per-side commission",
        )
    else:
        charges["commission"] = ComponentCharge(
            component="commission",
            status="unknown",
            usd=None,
            detail=(
                "the ruleset's per-side commission is unknown"
                if commission_status == "unknown"
                else f"the ruleset declares no per-side commission for {root}"
            ),
        )
        gaps.append("commission")
    priced: dict[str, FeeRow] = {}
    if excluded and fee_source is not None:
        priced = fee_source.rows_for(
            root, when, participant_type=participant_type or "", components=excluded
        )
    # a row that covers several components is charged ONCE: the components it prices share its
    # record hash, so the row is the group and the first component in report order carries the
    # amount while the others say they are inside it. Splitting the amount across them would be a
    # number the source never stated.
    groups: dict[str, list[str]] = {}
    for component in COST_COMPONENTS:
        if component in priced:
            groups.setdefault(priced[component].record_sha256, []).append(component)
    carriers = {members[0]: members[0] for members in groups.values()}
    carried_by: dict[str, str] = {}
    for members in groups.values():
        for member in members[1:]:
            carried_by[member] = members[0]
    for name in COST_COMPONENTS:
        declaration = components.declaration(name)
        if declaration.status == "included":
            charges[name] = ComponentCharge(
                component=name,
                status="included",
                usd=Decimal(0),
                detail="inside the firm's per-side commission, so nothing is added",
            )
        elif declaration.status == "excluded":
            if fee_source is None:
                charges[name] = ComponentCharge(
                    component=name,
                    status="excluded_unpriced",
                    usd=None,
                    detail=("the commission excludes it and no fee dataset was given"),
                )
                gaps.append(name)
            elif name not in priced:
                charges[name] = ComponentCharge(
                    component=name,
                    status="excluded_unpriced",
                    usd=None,
                    detail=(
                        f"the commission excludes it and the fee dataset has no {name} row for "
                        f"{root} on {when.isoformat()} for participant type {participant_type!r}"
                    ),
                )
                gaps.append(name)
            elif name in carried_by:
                carrier = carried_by[name]
                charges[name] = ComponentCharge(
                    component=name,
                    status="covered_by_row",
                    usd=Decimal(0),
                    detail=(
                        f"inside the {carrier} row {priced[name].record_sha256[:12]}..., which is "
                        "charged once for both components"
                    ),
                )
            else:
                row = priced[name]
                assert name in carriers
                charges[name] = ComponentCharge(
                    component=name,
                    status="excluded_priced",
                    usd=row.per_side_usd,
                    detail=(
                        f"charged from the fee dataset, row {row.record_sha256[:12]}... "
                        f"(participant type {participant_type})"
                    ),
                )
        else:
            charges[name] = ComponentCharge(
                component=name,
                status="unknown",
                usd=None,
                detail="the sources do not state whether the commission contains it",
            )
            gaps.append(name)
    priced_by_assumption: list[str] = []
    if assumption is not None:
        for gap_name in list(gaps):
            entry = assumption.amount_for(root, gap_name)
            if entry is None:
                continue
            charges[gap_name] = ComponentCharge(
                component=gap_name,
                status="assumption",
                usd=entry.per_side_usd,
                detail=(
                    f"cost assumption {assumption.name!r} (sha256 {assumption.sha256[:12]}...) "
                    f"prices {root} {gap_name}"
                ),
            )
            gaps.remove(gap_name)
            priced_by_assumption.append(gap_name)
        for declared in assumption.amounts.get(root, ()):
            for covered in declared.covers:
                charge = charges.get(covered)
                if charge is None:
                    continue
                if charge.status in ("included", "excluded_priced", "known"):
                    msg = (
                        f"cost assumption {assumption.name!r} prices {root} {covered}, but the "
                        f"ruleset already has it ({charge.status}: {charge.detail}). An "
                        "assumption may not override a declared or dataset-priced cost"
                    )
                    raise ConfigurationError(msg)

    def _amount(component: str) -> Decimal:
        """What the component adds; the run's own commission is the unknown placeholder."""
        amount = charges[component].usd
        if amount is not None:
            return amount
        return costs.commission if component == "commission" else Decimal(0)

    schedule = replace(
        costs,
        commission=_amount("commission"),
        exchange_fee=_amount("exchange"),
        clearing_fee=_amount("clearing"),
        regulatory_fee=_amount("nfa"),
        other_fee=_amount("other"),
    )
    # the participant type is "assumed" only when it actually priced a component: a run that
    # supplies one for a ruleset whose commission is all-in has assumed nothing
    used_participant = any(
        charge.status in ("excluded_priced", "covered_by_row") for charge in charges.values()
    )
    recorded_participant = participant_type if used_participant else None
    if gaps:
        status = "unavailable"
    elif priced_by_assumption or recorded_participant is not None:
        status = "conditional"
    else:
        status = "complete"
    return CostPricing(
        charges=tuple(charges[name] for name in COMPONENTS_WITH_COMMISSION),
        schedule=schedule,
        gaps=tuple(gaps),
        status=status,
        assumption=assumption,
        priced_by_assumption=tuple(priced_by_assumption),
        participant_type=recorded_participant,
    )


__all__ = [
    "COMPONENTS_WITH_COMMISSION",
    "FEE_SOURCE_DATASET",
    "SCHEDULE_FIELD",
    "AssumptionAmount",
    "ComponentCharge",
    "ComponentFeeRow",
    "ComponentFeeSource",
    "ComponentFeeTable",
    "CostAssumption",
    "CostPricing",
    "FeeRow",
    "StoreComponentFees",
    "load_cost_assumption",
    "price_components",
    "store_component_fees",
]
