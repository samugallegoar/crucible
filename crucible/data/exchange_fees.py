"""Per-side fees a customer of a prop firm's clearing chain pays on top of commission.

``exchange_fees_v1``: per contract, per side, in USD, keyed by the component the amount covers —

- ``exchange`` — the exchange's own trading fee (CME Group, for an equity-index root);
- ``clearing`` — the clearing fee;
- ``nfa`` — the NFA regulatory assessment;
- ``other`` — any other per-side charge the source states;

and for the roots ES, NQ, YM, RTY, NKD, MES, MNQ, MYM, M2K. **No exchange, clearing or other row is
written by this build.** CME Group's site refuses automated access from the environment this was
built in (HTTP 403, "This IP address is blocked due to suspected web scraping activity ... Use of
scripts, software, spiders, robots, avatars, agents, tools or other scraping mechanisms is
strictly prohibited by CME Group's website Data Terms of Use"), and its published fee schedules
name product *buckets* ("E-mini Equity Index", "Micro E-mini Index", "Nikkei/TOPIX"), never a root
ticker, so a rate cannot be attached to a root from the published document without guessing. Both
are recorded in ``docs/data/cme-exchange-fees.md``: those rows are added from an **owner-provided**
file (:func:`load_owner_provided_csv`), which carries the supplier, the file's SHA-256 and the
exact cell text as evidence. Until such a file is supplied, :func:`fee_rows_as_of` prices nothing
for the missing components: an unresolved fee is unknown, not zero (AGENTS.md section 1.5, "refuse,
don't warn").

**No universal fee, and no extrapolation.** A row prices only its exact root and date range and,
for the *classification* it declares, the participant it is written for. It states which components
(``covers``) its amount covers, and a row covering several components is charged once. There is no
product-bucket-to-root mapping here: the engine never invents one.

**Classification, resolved per component.** A row does not carry a participant type; it carries
the one dimension of the run's :class:`ParticipantProfile` it needs
(``classification_dimension``) and the value it states (``classification_value``). A row that is
the same for every participant uses ``classification_dimension=none`` /
``classification_value=all``, which needs no profile entry. :func:`fee_rows_as_of` looks each
covering row's dimension up in the profile: a dimension the profile does not declare (or declares
``unknown``) makes the component a GAP whose reason names the dimension, a value that differs
makes the row inapplicable, exactly one applicable row prices the component, two are refused as
ambiguous, and none is a gap. There is never a default classification and never a fallback to the
only row available. The NFA row keeps its own dimension (``nfa_assessment_eligibility =
fcm_member``, the assessment Bylaw 1301 makes on the FCM member), so a profile that does not
declare it leaves the ``nfa`` component a gap rather than silently pricing it.

**``other`` rows need evidence of their own.** A row typed ``other`` may not be a catch-all: it
must name the charge (``charge_name``, never a generic word such as ``misc`` or ``CME other
fees``), state ``unit = per_contract_per_side`` (fixed monthly, platform or subscription charges
belong in the ruleset's fee schedule, not here), give ``applies_quote`` (the source text showing
the charge applies to this execution) and ``distinct_from`` (why it is not exchange, clearing or
NFA), and cite an official ``source_url`` on ``www.cmegroup.com``. An ``other`` row's ``covers``
is exactly ``other``; no row of another type may list ``other`` in its ``covers``.

Rows:

- ``nfa`` — the NFA assessment fee the FCM member pays per contract for each side
  (nfa.futures.org, NFA Bylaw 1301(b)(i)(A)). Fetched from the official page and parsed in
  :func:`parse_nfa_assessment`; the bylaw states the rate *and* the period it applies to, so the
  ``effective_from``/``effective_to`` of a row are stated by the source, not inferred.

Not market data: rows are keyed by a calendar date range, not by an instant, and the futures
holdout vault (ADR-0105) does not cover this dataset.

Timing semantics: ``event_time``/``available_at`` are the first instant of ``effective_from``
(UTC ns) for both row kinds. A fee schedule is normally published some days *before* it takes
effect and the sources state no publication instant, so ``available_at = event_time`` is the
weaker, provable bound — the same convention as ``econ_events_v1``
(:mod:`crucible.data.econ_events`). A point-in-time read therefore never sees a future rate, and
a consumer that needs "the rate that will apply tomorrow" must read the table with a later
``as_of``.

Determinism: a row is a pure function of the raw bytes it was read from. ``record_sha256`` is the
SHA-256 of the row's other fields in canonical JSON, ``snapshot_sha256`` names the bytes (the
page or the owner's file), so a row cites its evidence and a row that changes under a stable key
is detectable.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import polars as pl
import yaml

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.store import build_dataset

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from pathlib import Path

    from crucible.data.interfaces import DataStore

DATASET: DatasetId = DatasetId("exchange_fees_v1")
"""The dataset id this module builds: ``<store root>/exchange_fees_v1``."""

DATASET_VERSION = "exchange_fees_v1"
"""Version of the *rows* (not of the Parquet layout): bump it when a parsing rule changes what a
row says, so a stale copy in a store can be told from a current one."""

ROOTS: tuple[str, ...] = ("ES", "NQ", "YM", "RTY", "NKD", "MES", "MNQ", "MYM", "M2K")
"""The roots a prop firm's equity-index book holds, in report order: the CME minis and micros
(ES, NQ, RTY, MES, MNQ, M2K), the CME Nikkei (NKD) and the CBOT Dow pair (YM, MYM)."""

VENUE_OF: dict[str, str] = {
    "ES": "CME",
    "NQ": "CME",
    "RTY": "CME",
    "NKD": "CME",
    "MES": "CME",
    "MNQ": "CME",
    "M2K": "CME",
    "YM": "CBOT",
    "MYM": "CBOT",
}
"""The exchange each root trades on: CME Group publishes one fee schedule per exchange, so the
venue decides which document a root's exchange fee must come from."""

FEE_TYPES: tuple[str, ...] = ("exchange", "clearing", "nfa", "other")
"""``fee_type`` values: the exchange's own fee, the clearing fee, the NFA regulatory assessment,
and any other per-side charge. A row's ``fee_type`` must be one of the components its ``covers``
column lists."""

UNITS: tuple[str, ...] = ("per_contract_per_side",)
"""The only unit this per-side table holds. A monthly, platform, subscription or account charge
is refused BY NAME (``unit`` must be exactly ``per_contract_per_side``): a fixed charge belongs in
the ruleset's fee schedule, separate from execution costs (ADR-0107, second 2026-11-22
amendment)."""

UNIT_PER_CONTRACT_PER_SIDE = UNITS[0]
"""The accepted ``unit`` value."""

EXCHANGE_CLASSIFICATION_DIMENSION = "cme_membership_status"
"""``classification_dimension`` an exchange row declares: whether the account is a CME member."""

EXCHANGE_CLASSIFICATION_VALUE = "non_member"
"""``classification_value`` of the exchange row this dataset's owner files normally carry: the
rate a **non-member** account pays. CME's schedule does not say which class a prop firm's accounts
fall in, so the run's participant profile declares the value, and an owner file that states
another one says so in its own row (``docs/data/cme-exchange-fees.md``)."""

NFA_CLASSIFICATION_DIMENSION = "nfa_assessment_eligibility"
"""``classification_dimension`` of an NFA row: the assessment Bylaw 1301(b)(i)(A) makes on the
FCM member, which a customer sees passed through. A profile must declare it — there is no
pass-through to "any participant" — or the ``nfa`` component is a gap."""

NFA_CLASSIFICATION_VALUE = "fcm_member"
"""``classification_value`` of an NFA row: the bylaw's own subject, the FCM member."""

CLASSIFICATION_DIMENSION_NONE = "none"
"""``classification_dimension`` of a row that is the same for every participant. It needs no
profile entry, and its ``classification_value`` must be :data:`CLASSIFICATION_VALUE_ALL`."""

CLASSIFICATION_VALUE_ALL = "all"
"""``classification_value`` of a :data:`CLASSIFICATION_DIMENSION_NONE` row."""

CLASSIFICATION_VALUE_UNKNOWN = "unknown"
"""The profile value that means *not known*: a component whose row names that dimension is a gap,
never priced from the row (unknown is never a value an owner may be assumed to match)."""

CLASSIFICATION_DIMENSION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
"""A dimension name is an identifier, not a fixed enum: lower-case, digits and underscores."""

CME_GROUP_HOST = "www.cmegroup.com"
"""The host an ``other`` row's ``source_url`` must be on: CME Group's own site. Every root this
table prices is a CME Group market, so an ``other`` charge has to come from CME Group's schedule."""

GENERIC_CHARGE_WORDS: frozenset[str] = frozenset(
    {
        "other",
        "others",
        "misc",
        "miscellaneous",
        "fees",
        "fee",
        "charges",
        "charge",
        "additional",
        "cme",
        "exchange",
    }
)
"""Words that name no charge on their own. A ``charge_name`` made only of these (after stripping
punctuation and case) is refused: it is a catch-all, and a catch-all cannot be charged as a
specific per-side cost."""

SOURCE_KIND_OFFICIAL = "official_page"
"""``source_kind`` of a row read from an official publisher's own page (the NFA bylaw)."""

SOURCE_KIND_OWNER = "owner_provided"
"""``source_kind`` of a row read from a file the owner supplied (the exchange fee schedules, and
any future root CME's published document cannot support)."""

MANIFEST_NAME = "MANIFEST.json"
"""Index of the raw folder: one entry per fetched page (see :func:`fetch_raw`)."""

NFA_BYLAW_URL = "https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=3&SubSection=13"
"""NFA Manual, Chapter 13 "Schedule of Dues and Assessments", Bylaw 1301 — the official page that
states the assessment fee, its period and the date the period ends. Read 2026-11-22."""

EXCHANGE_FEE_SCHEMA: dict[str, pl.DataType] = {
    "root": pl.String(),  # product root: ES, NQ, YM, RTY, NKD, MES, MNQ, MYM or M2K
    "venue": pl.String(),  # the exchange the root trades on: CME or CBOT
    "fee_type": pl.String(),  # exchange, clearing, nfa or other: the component the row prices
    "classification_dimension": pl.String(),  # profile dimension the row needs, or 'none'
    "classification_value": pl.String(),  # the value that dimension must have, or 'all'
    "covers": pl.String(),  # ';'-separated components the amount covers; contains fee_type
    "charge_name": pl.String(),  # nullable: the specific name of an 'other' charge
    "unit": pl.String(),  # 'per_contract_per_side': the only unit this table holds
    "per_side_usd": pl.String(),  # Decimal string: USD per contract per side (a float would round)
    "effective_from": pl.Date(),  # first calendar date the rate applies to
    "effective_to": pl.Date(),  # nullable: last date it applies to; null = open-ended
    "source_kind": pl.String(),  # official_page (a publisher's page) or owner_provided (a file)
    "provided_by": pl.String(),  # nullable: who supplied the file (owner); null if official_page
    "source_url": pl.String(),  # the page fetched or the owner file's document: never invented
    "snapshot_sha256": pl.String(),  # SHA-256 of the bytes the row was read from (MANIFEST.json)
    "quote": pl.String(),  # the exact text the rate was read from: a bylaw sentence or a cell
    "applies_quote": pl.String(),  # nullable: 'other' only, text showing it applies to this side
    "distinct_from": pl.String(),  # nullable: 'other' only, why it is not exchange/clearing/NFA
    "event_time": pl.Int64(),  # UTC ns: first instant of effective_from; the rate's own start
    "available_at": pl.Int64(),  # UTC ns the rate was knowable; equals event_time
    "record_sha256": pl.String(),  # SHA-256 of this row's other fields in canonical JSON
    "dataset_version": pl.String(),  # DATASET_VERSION the row was built by
}
EXCHANGE_FEE_SORT_KEYS = [
    "root",
    "classification_dimension",
    "classification_value",
    "fee_type",
    "effective_from",
    "covers",
]
"""Stored order: by root, classification, fee type, effective date and coverage, so identical
inputs rebuild to identical bytes (ADR-0011) and a root's history reads top to bottom."""

_NS_PER_S = 1_000_000_000
_DAY_NS = 86_400 * _NS_PER_S

_MONTHS: dict[str, int] = {
    name: number
    for number, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}

# --------------------------------------------------------------------- the participant profile


@dataclass(frozen=True, slots=True)
class ParticipantProfile:
    """Who the run's account is, as far as a fee table's classifications go (ADR-0107).

    A per-side fee row does not state a participant type; it states the one classification
    dimension it needs and the value it is written for (``cme_membership_status = non_member``,
    ``nfa_assessment_eligibility = fcm_member``, …), so a run declares a PROFILE: a flat mapping
    from dimension name to value. The dimension names are not an enum — each row brings its own —
    and every name is an identifier matching ``^[a-z][a-z0-9_]*$``.

    ``unknown`` is an allowed value and means unknown: a component whose row names a dimension the
    profile leaves out, or declares ``unknown``, is a GAP, never priced from that row. Nothing here
    has a default: an absent entry is an absent fact, not a usual one.

    The profile is a RUN input (a ruleset never states one), it is immutable, and its canonical
    SHA-256 identifies it: two profiles give two artifacts.

    .. code-block:: yaml

        cme_membership_status: non_member
        nfa_assessment_eligibility: fcm_member
    """

    values: tuple[tuple[str, str], ...]
    """``(dimension, value)`` pairs, sorted by dimension: the profile's canonical order."""

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> ParticipantProfile:
        """A profile from a flat mapping, validated; refuses what the contract cannot hold."""
        pairs: list[tuple[str, str]] = []
        for dimension, raw in values.items():
            name = str(dimension).strip()
            if not CLASSIFICATION_DIMENSION_PATTERN.match(name):
                msg = (
                    f"participant profile dimension {name!r} is not an identifier matching "
                    "^[a-z][a-z0-9_]*$"
                )
                raise ConfigurationError(msg)
            if name == CLASSIFICATION_DIMENSION_NONE:
                msg = (
                    "participant profile dimension 'none' is reserved for a fee row that is the "
                    "same for every participant: the profile does not declare it"
                )
                raise ConfigurationError(msg)
            if isinstance(raw, bool) or not isinstance(raw, str | int | float):
                msg = f"participant profile value for {name!r} must be a string, got {raw!r}"
                raise ConfigurationError(msg)
            value = str(raw).strip()
            if not value:
                msg = (
                    f"participant profile dimension {name!r} has an empty value; state one (the "
                    "literal 'unknown' is allowed and means unknown)"
                )
                raise ConfigurationError(msg)
            pairs.append((name, value))
        if not pairs:
            msg = (
                "participant profile declares no dimension; leave it out instead of passing an "
                "empty mapping (a profile is only needed when a fee component is excluded)"
            )
            raise ConfigurationError(msg)
        return cls(values=tuple(sorted(pairs)))

    def __post_init__(self) -> None:
        if not self.values:
            msg = "participant profile declares no dimension: it prices nothing"
            raise ConfigurationError(msg)

    def lookup(self, dimension: str) -> str | None:
        """The declared value of ``dimension``, or ``None`` when the profile does not declare it."""
        for name, value in self.values:
            if name == dimension:
                return value
        return None

    def as_mapping(self) -> dict[str, str]:
        """The profile as a plain mapping, in canonical (dimension-sorted) order."""
        return dict(self.values)

    @property
    def dimensions(self) -> tuple[str, ...]:
        """The declared dimensions, sorted."""
        return tuple(name for name, _ in self.values)

    @property
    def sha256(self) -> str:
        """The profile's canonical SHA-256: what the artifact records and the id hashes."""
        canonical = json.dumps(
            self.as_mapping(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_participant_profile(path: Path) -> ParticipantProfile:
    """Load a participant-profile YAML file: a flat mapping from dimension name to value.

    The file is the run's own statement of who the account is. It is required only when a
    component is ``excluded``; when it is given it is recorded by its canonical SHA-256, and using
    it keeps the cost estimate ``conditional`` (a declared profile is not a firm's statement).
    """
    if not path.is_file():
        msg = f"participant profile {path} does not exist: pass the YAML file, or omit it"
        raise ConfigurationError(msg)
    body = path.read_bytes()
    try:
        document = yaml.safe_load(body.decode("utf-8"))
    except yaml.YAMLError as exc:
        msg = f"participant profile {path} is not valid YAML: {exc}"
        raise ConfigurationError(msg) from exc
    if not isinstance(document, dict):
        msg = (
            f"participant profile {path}: the file must be a flat mapping from dimension name to "
            "value (e.g. 'cme_membership_status: non_member')"
        )
        raise ConfigurationError(msg)
    nested = [str(key) for key, value in document.items() if isinstance(value, dict | list)]
    if nested:
        msg = (
            f"participant profile {path}: dimension(s) {nested} hold a nested value; every value "
            "is a plain string"
        )
        raise ConfigurationError(msg)
    return ParticipantProfile.from_mapping(document)


@dataclass(frozen=True, slots=True)
class FeeLookup:
    """What a fee table priced for one root on one date, and why the rest is not priced.

    ``priced`` maps a component to its ``(USD per side, row record_sha256)``; ``gaps`` maps a
    component to the reason it is a gap. A component appears in exactly one of them, and neither
    is ever a zero: an unpriced component is not a free one.
    """

    priced: Mapping[str, tuple[Decimal, str]] = field(default_factory=dict)
    gaps: Mapping[str, str] = field(default_factory=dict)


def resolve_component_rows(
    *,
    where: str,
    classifications: Sequence[tuple[str, str]],
    profile: ParticipantProfile | None,
    labels: Sequence[str] | None = None,
    multiple: bool = False,
) -> tuple[tuple[int, ...], str | None]:
    """Which of the rows covering one component applies, or why none of them does.

    ``classifications`` is one ``(dimension, value)`` pair per covering row, in a deterministic
    order; ``labels`` optionally names each row (a record hash) for the refusal message.

    The rule (ADR-0107, second 2026-11-22 amendment) is applied row by row and never relaxed:

    - ``none``/``all`` rows apply to every participant and need no profile entry;
    - a row whose dimension the profile does not declare, or declares ``unknown``, makes the whole
      component a GAP whose reason names that dimension — the engine may not guess whether that
      row would have applied;
    - a row whose stated value differs from the profile's does not apply;
    - exactly one applicable row prices the component, two are refused as ambiguous, and none is a
      gap.

    ``multiple`` is the one stated exception, and it exists for ``other`` alone: two distinctly
    NAMED ``other`` charges are two charges, each with its own evidence, so every applicable row is
    returned and the caller sums them (a duplicate name is refused when the table is built). Every
    other component takes the first branch: exactly one row.

    Returns ``(indices, None)`` for the rows that apply or ``((), reason)`` for a gap; raises
    :class:`ConfigurationError` when two rows apply to a component that takes one. There is no
    default classification and no fallback to "the only row there is".
    """
    if not classifications:
        return (), f"no fee row covers {where}"
    if labels is not None and len(labels) != len(classifications):
        msg = "resolve_component_rows: labels and classifications must have one entry per row"
        raise ConfigurationError(msg)
    declared: list[int] = []
    undeclared: list[str] = []
    for index, (dimension, value) in enumerate(classifications):
        if dimension == CLASSIFICATION_DIMENSION_NONE:
            declared.append(index)
            continue
        stated = None if profile is None else profile.lookup(dimension)
        if stated is None or stated == CLASSIFICATION_VALUE_UNKNOWN:
            if dimension not in undeclared:
                undeclared.append(dimension)
            continue
        if stated == value:
            declared.append(index)
    if undeclared:
        return (), f"classification {', '.join(undeclared)} not declared"
    if multiple:
        if not declared:
            stated = (
                "no profile"
                if profile is None
                else ", ".join(
                    f"{dimension}={profile.lookup(dimension)}"
                    for dimension, _ in classifications
                    if dimension != CLASSIFICATION_DIMENSION_NONE
                )
            )
            return (), f"no fee row for {where} matches the declared classification ({stated})"
        return tuple(declared), None
    if len(declared) > 1:
        named = (
            sorted(str(labels[index])[:12] for index in declared)
            if labels is not None
            else [str(index) for index in declared]
        )
        msg = (
            f"{where}: {len(declared)} fee rows apply ({', '.join(named)}): the profile matches "
            "more than one classification on the same date, and no amount may be chosen from an "
            "ambiguity (close one row's effective_to, or declare fewer dimensions)"
        )
        raise ConfigurationError(msg)
    if not declared:
        stated = (
            "no profile"
            if profile is None
            else ", ".join(
                f"{dimension}={profile.lookup(dimension)}"
                for dimension, _ in classifications
                if dimension != CLASSIFICATION_DIMENSION_NONE
            )
        )
        return (), f"no fee row for {where} matches the declared classification ({stated})"
    return (declared[0],), None


# ------------------------------------------------------------------------------- the row model


@dataclass(frozen=True, slots=True)
class RawFee:
    """One rate as a source states it, before ids, instants and hashes are attached.

    ``per_side_usd`` is a ``Decimal``: money never goes through a float. ``effective_to`` is
    ``None`` for an open-ended rate, which the source states explicitly (the NFA bylaw says the
    higher rate applies "after which time", with no end). ``classification_dimension`` names the
    one participant-profile dimension the row needs (``none`` for a charge that is the same for
    every participant) and ``classification_value`` the value it states. The ``other`` evidence
    fields are ``None`` on every other row type and REQUIRED on an ``other`` row.
    """

    root: str
    venue: str
    fee_type: str
    classification_dimension: str
    classification_value: str
    covers: tuple[str, ...]
    per_side_usd: Decimal
    effective_from: dt.date
    effective_to: dt.date | None
    source_kind: str
    provided_by: str | None
    source_url: str
    snapshot_sha256: str
    quote: str
    unit: str = UNIT_PER_CONTRACT_PER_SIDE
    charge_name: str | None = None
    applies_quote: str | None = None
    distinct_from: str | None = None

    def __post_init__(self) -> None:
        _check_row(
            root=self.root,
            venue=self.venue,
            fee_type=self.fee_type,
            classification_dimension=self.classification_dimension,
            classification_value=self.classification_value,
            covers=self.covers,
            per_side_usd=self.per_side_usd,
            effective_from=self.effective_from,
            effective_to=self.effective_to,
            source_kind=self.source_kind,
            provided_by=self.provided_by,
            source_url=self.source_url,
            quote=self.quote,
            unit=self.unit,
            charge_name=self.charge_name,
            applies_quote=self.applies_quote,
            distinct_from=self.distinct_from,
        )


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One fetched or supplied file: what was read, where it came from and when."""

    name: str
    source: str
    kind: str
    origin: str
    retrieved_at: str
    sha256: str
    path: Path
    text: str


@dataclass(frozen=True, slots=True)
class BuildReport:
    """What a build wrote, and which roots it could not price."""

    dataset: str
    rows: int
    content_hash: str
    rows_by_type: dict[str, int]
    rows_by_source: dict[str, int]
    roots_priced_by_component: dict[str, tuple[str, ...]]
    unpriced_components: tuple[str, ...]
    exchange_roots_priced: tuple[str, ...]
    exchange_roots_missing: tuple[str, ...]
    snapshots: int


def is_generic_charge_name(name: str) -> bool:
    """Whether a ``charge_name`` names nothing specific, so it cannot be charged.

    Case is stripped and punctuation becomes a space, so ``Other``, ``misc.`` and ``CME other
    fees`` are all catch-alls. A name is generic when every word it has is a
    :data:`GENERIC_CHARGE_WORDS` entry: one real word ("Globex", "connectivity", "storage") is
    enough to make it a name.
    """
    words = [word for word in re.split(r"[^a-z0-9]+", name.lower()) if word]
    return not words or all(word in GENERIC_CHARGE_WORDS for word in words)


def _check_row(
    *,
    root: str,
    venue: str,
    fee_type: str,
    classification_dimension: str,
    classification_value: str,
    covers: Sequence[str],
    per_side_usd: Decimal,
    effective_from: dt.date,
    effective_to: dt.date | None,
    source_kind: str,
    provided_by: str | None,
    source_url: str,
    quote: str,
    unit: str,
    charge_name: str | None = None,
    applies_quote: str | None = None,
    distinct_from: str | None = None,
) -> None:
    """Refuse a row the dataset's contract cannot hold, with a message that says how to fix it."""
    if root not in ROOTS:
        msg = f"root {root!r} is not one of {list(ROOTS)}: add it to ROOTS with its venue"
        raise ConfigurationError(msg)
    if venue != VENUE_OF[root]:
        msg = f"{root} trades on {VENUE_OF[root]}, not {venue!r}: VENUE_OF holds the venue"
        raise ConfigurationError(msg)
    if fee_type not in FEE_TYPES:
        msg = f"fee_type {fee_type!r} is not one of {list(FEE_TYPES)}"
        raise ConfigurationError(msg)
    if unit not in UNITS:
        msg = (
            f"{root} {fee_type}: unit {unit!r} is not accepted; this table holds only "
            f"{' or '.join(UNITS)}. A monthly, platform, subscription or account charge is a fixed "
            "charge and belongs in the ruleset's fee schedule, separate from execution costs"
        )
        raise ConfigurationError(msg)
    if not covers:
        msg = (
            f"{root} {fee_type}: covers is empty; list the components the amount covers "
            f"as a semicolon-separated list, one of {list(FEE_TYPES)}"
        )
        raise ConfigurationError(msg)
    unknown_covers = [name for name in covers if name not in FEE_TYPES]
    if unknown_covers:
        msg = (
            f"{root} {fee_type}: covers names {unknown_covers}, which is not one of "
            f"{list(FEE_TYPES)}"
        )
        raise ConfigurationError(msg)
    if len(set(covers)) != len(covers):
        msg = f"{root} {fee_type}: covers repeats a component in {list(covers)}; list each once"
        raise ConfigurationError(msg)
    if fee_type not in covers:
        msg = (
            f"{root} {fee_type}: covers {list(covers)} does not contain its own fee_type; a row "
            "prices the component it is typed as"
        )
        raise ConfigurationError(msg)
    if "other" in covers and fee_type != "other":
        msg = (
            f"{root} {fee_type}: covers {list(covers)} lists other, but an exchange fee cannot "
            "cover other components: an other charge is its own row, with its own charge_name, "
            "applies_quote and distinct_from evidence"
        )
        raise ConfigurationError(msg)
    if fee_type == "other" and tuple(covers) != ("other",):
        msg = (
            f"{root} other: covers must be exactly ['other'] for an other row, got {list(covers)}; "
            "a charge that is not exchange, clearing or NFA is a single other component"
        )
        raise ConfigurationError(msg)
    _check_classification(
        root=root, fee_type=fee_type, dimension=classification_dimension, value=classification_value
    )
    if not per_side_usd.is_finite() or per_side_usd < 0:
        msg = (
            f"{root} {fee_type}: per_side_usd must be a finite, non-negative Decimal, "
            f"got {per_side_usd}"
        )
        raise ConfigurationError(msg)
    if effective_to is not None and effective_to < effective_from:
        msg = (
            f"{root} {fee_type}: effective_to {effective_to} is before effective_from "
            f"{effective_from}"
        )
        raise ConfigurationError(msg)
    if source_kind not in (SOURCE_KIND_OFFICIAL, SOURCE_KIND_OWNER):
        msg = (
            f"{root} {fee_type}: source_kind {source_kind!r} is neither an official page "
            "nor an owner file"
        )
        raise ConfigurationError(msg)
    if not source_url.strip():
        msg = (
            f"{root} {fee_type}: source_url is required; name the page or the document the rate "
            "was read from (e.g. https://www.cmegroup.com/company/clearing-fees/historical-fees"
            ".html)"
        )
        raise ConfigurationError(msg)
    if source_kind == SOURCE_KIND_OWNER and not provided_by:
        msg = (
            f"{root} {fee_type}: an owner_provided row must name who supplied the file "
            "(provided_by), so a rate nobody published can be told from one that was"
        )
        raise ConfigurationError(msg)
    if not quote.strip():
        msg = f"{root} {fee_type}: quote is empty; store the exact text the rate was read from"
        raise ConfigurationError(msg)
    if fee_type == "other":
        _check_other_evidence(
            root=root,
            source_url=source_url,
            charge_name=charge_name,
            applies_quote=applies_quote,
            distinct_from=distinct_from,
        )


def _check_classification(*, root: str, fee_type: str, dimension: str, value: str) -> None:
    """A row names one profile dimension and the value it needs, or ``none``/``all``."""
    if not CLASSIFICATION_DIMENSION_PATTERN.match(dimension):
        msg = (
            f"{root} {fee_type}: classification_dimension {dimension!r} is not an identifier "
            "matching ^[a-z][a-z0-9_]*$ (use 'none' for a charge that is the same for every "
            "participant)"
        )
        raise ConfigurationError(msg)
    if not value.strip():
        msg = (
            f"{root} {fee_type}: classification_value is empty; state the value the row needs "
            "(or 'all' with classification_dimension 'none')"
        )
        raise ConfigurationError(msg)
    if dimension == CLASSIFICATION_DIMENSION_NONE and value != CLASSIFICATION_VALUE_ALL:
        msg = (
            f"{root} {fee_type}: classification_dimension 'none' needs classification_value "
            f"'all', got {value!r}: a charge the source states is the same for every "
            "participant needs no profile entry"
        )
        raise ConfigurationError(msg)
    if dimension != CLASSIFICATION_DIMENSION_NONE and value == CLASSIFICATION_VALUE_ALL:
        msg = (
            f"{root} {fee_type}: classification_value 'all' is only allowed with "
            "classification_dimension 'none'; name the value the row states"
        )
        raise ConfigurationError(msg)


def _check_other_evidence(
    *,
    root: str,
    source_url: str,
    charge_name: str | None,
    applies_quote: str | None,
    distinct_from: str | None,
) -> None:
    """An ``other`` row is a NAMED, sourced, per-side charge or it is nothing (ADR-0107)."""
    name = "" if charge_name is None else charge_name.strip()
    if not name:
        msg = (
            f"{root} other: charge_name is required; name the charge specifically, so an 'other' "
            "row is not a catch-all (a generic word such as 'misc' or 'CME other fees' is "
            "refused too)"
        )
        raise ConfigurationError(msg)
    if is_generic_charge_name(name):
        msg = (
            f"{root} other: charge_name {name!r} is a generic name, not a charge. Name what is "
            "charged (e.g. 'CME Globex connectivity fee'), or file the amount in the ruleset's "
            "fee schedule if it is not a per-side execution cost"
        )
        raise ConfigurationError(msg)
    host = urllib.parse.urlsplit(source_url.strip()).hostname or ""
    if host != CME_GROUP_HOST:
        msg = (
            f"{root} other: source_url host is {host or '(none)'!r}; an other row must cite an "
            f"official CME Group page on {CME_GROUP_HOST} (the schedule that states the charge "
            "and to whom it applies)"
        )
        raise ConfigurationError(msg)
    if applies_quote is None or not applies_quote.strip():
        msg = (
            f"{root} other: applies_quote is required; quote the source text that shows the "
            "charge applies to this contract and this participant"
        )
        raise ConfigurationError(msg)
    if distinct_from is None or not distinct_from.strip():
        msg = (
            f"{root} other: distinct_from is required; state why the charge is not part of the "
            "exchange, clearing or NFA fee already recorded for this root"
        )
        raise ConfigurationError(msg)


def _day_ns(day: dt.date) -> int:
    """The first instant of ``day`` in UTC ns: what an effective date means as an instant."""
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()) * _NS_PER_S


def _iso_of_ns(value: int) -> str:
    return dt.datetime.fromtimestamp(value / _NS_PER_S, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_amount(text: str, where: str) -> Decimal:
    """A money amount from a source, as a ``Decimal``; refuses anything that is not one."""
    cleaned = text.strip().replace(",", "").replace("$", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        msg = f"{where}: cannot read {text!r} as a money amount"
        raise DataQualityError(msg) from exc
    if not value.is_finite():
        msg = f"{where}: {text!r} is not a finite amount"
        raise DataQualityError(msg)
    return value


def _us_date(text: str, where: str) -> dt.date:
    """A date a source prints in long US form ("July 1, 2026")."""
    match = re.match(r"^([A-Z][a-z]+) (\d{1,2}), (\d{4})$", text.strip())
    if match is None or match.group(1) not in _MONTHS:
        msg = f"{where}: cannot read the date {text!r}; expected e.g. 'July 1, 2026'"
        raise DataQualityError(msg)
    return dt.date(int(match.group(3)), _MONTHS[match.group(1)], int(match.group(2)))


def record_sha256(row: Mapping[str, object]) -> str:
    """SHA-256 of a row's other fields in canonical JSON (sorted keys, no whitespace).

    ``record_sha256`` is excluded so the hash can be recomputed from a stored row: a rate that
    changed under a stable (root, fee_type, effective_from) key is detectable, and two rows that
    differ anywhere (class, evidence, quote, source) never share a hash.
    """
    payload = {
        key: value
        for key, value in row.items()
        if key != "record_sha256" and (value is None or isinstance(value, (bool, int, float, str)))
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------- the NFA bylaw

# "… (A) $.02 for each commodity futures contract traded on or entered into subject to the rules
# of a contract market (other than an option contract) on a round-turn basis during the period of
# July 1, 2026, through June 30, 2027, after which time the assessment will be equal to $.04 for
# each commodity futures contract … on a round-turn basis; (B) $.01 for each option contract …"
_NFA_SENTENCE = re.compile(
    r"\(A\)\s*\$(?P<first>\.?\d+(?:\.\d+)?)\s+for each commodity futures contract\b.*?"
    r"on a round-turn basis during the period of\s+"
    r"(?P<start>[A-Z][a-z]+ \d{1,2}, \d{4}),\s+through\s+(?P<end>[A-Z][a-z]+ \d{1,2}, \d{4}),"
    r"\s+after which time the assessment will be equal to\s+\$(?P<second>\.?\d+(?:\.\d+)?)\s+"
    r"for each commodity futures contract\b[^;]*;",
    re.DOTALL,
)

_TAG = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.DOTALL)


def _page_text(html: str) -> str:
    """The visible text of an HTML page: tags stripped, whitespace collapsed, nothing dropped.

    The bylaw is a plain document; a phrase this build needs (the assessment sentence) is text
    with markup inside it, so the text is read from the stripped form and the *stripped* sentence
    is what a row quotes as evidence.
    """
    return re.sub(r"\s+", " ", _TAG.sub(" ", html)).strip()


def parse_nfa_assessment(html: str, *, url: str = NFA_BYLAW_URL, sha256: str) -> list[RawFee]:
    """The NFA assessment fee a customer pays per side, for every root, from Bylaw 1301.

    The bylaw assesses the FCM member per **round turn**, so the per-side figure is half the
    stated amount: a row's ``quote`` is the sentence itself, and the sentence states both the rate
    and the period, which is why the two rows below carry their own dates instead of an inference
    (``$.02`` per round turn from its start through its end ⇒ ``$0.01`` per side; ``$.04`` after
    that ⇒ ``$0.02`` per side, open-ended).

    Every root gets both rows: the assessment is charged per contract regardless of the product,
    and a first-class row per root keeps :func:`fee_rows_as_of` a plain lookup. Refuses when the
    sentence is not on the page — the layout changed, and a rate that cannot be quoted must not
    be invented.
    """
    text = _page_text(html)
    match = _NFA_SENTENCE.search(text)
    if match is None:
        msg = (
            f"no NFA assessment sentence on {url}: Bylaw 1301(b)(i)(A) is not in the page text "
            "(the publisher changed the page). Re-fetch the page and check the bylaw before "
            "recording a rate."
        )
        raise DataQualityError(msg)
    start = _us_date(match.group("start"), f"{url}: period start")
    end = _us_date(match.group("end"), f"{url}: period end")
    first = _parse_amount(match.group("first"), f"{url}: first assessment amount") / 2
    second = _parse_amount(match.group("second"), f"{url}: second assessment amount") / 2
    quote = text[match.start() : match.end()]
    rows: list[RawFee] = []
    for root in ROOTS:
        rows.append(
            RawFee(
                root=root,
                venue=VENUE_OF[root],
                fee_type="nfa",
                classification_dimension=NFA_CLASSIFICATION_DIMENSION,
                classification_value=NFA_CLASSIFICATION_VALUE,
                covers=("nfa",),
                per_side_usd=first,
                effective_from=start,
                effective_to=end,
                source_kind=SOURCE_KIND_OFFICIAL,
                provided_by=None,
                source_url=url,
                snapshot_sha256=sha256,
                quote=quote,
            )
        )
        rows.append(
            RawFee(
                root=root,
                venue=VENUE_OF[root],
                fee_type="nfa",
                classification_dimension=NFA_CLASSIFICATION_DIMENSION,
                classification_value=NFA_CLASSIFICATION_VALUE,
                covers=("nfa",),
                per_side_usd=second,
                effective_from=end + dt.timedelta(days=1),
                effective_to=None,
                source_kind=SOURCE_KIND_OFFICIAL,
                provided_by=None,
                source_url=url,
                snapshot_sha256=sha256,
                quote=quote,
            )
        )
    return rows


# ------------------------------------------------------------------- owner-provided fee files

OWNER_COLUMNS: tuple[str, ...] = (
    "root",
    "fee_type",
    "classification_dimension",
    "classification_value",
    "covers",
    "per_side_usd",
    "unit",
    "effective_from",
    "source_url",
    "quote",
)
"""Columns an owner-provided fee file must carry.

``classification_dimension``/``classification_value`` are the one participant-profile dimension
and the value the row is written for (``cme_membership_status``/``non_member``), or
``none``/``all`` for a charge the source states is the same for every participant. ``covers`` is a
semicolon-separated list of the components the amount covers and must contain the row's own
``fee_type`` (a CME "Exchange Fees for Clearing & Trading" cell is ``fee_type=exchange``,
``covers=exchange;clearing``). ``unit`` must be ``per_contract_per_side``. ``source_url`` names
the document the cell came from — the CME page the owner downloaded — and is required: a rate
nobody can point at is not a fee."""

OWNER_OPTIONAL: tuple[str, ...] = (
    "venue",
    "effective_to",
    "charge_name",
    "applies_quote",
    "distinct_from",
)
"""Columns an owner-provided file may also carry; any other column is refused, so a typo in a
heading cannot silently drop a rate. ``charge_name``/``applies_quote``/``distinct_from`` carry an
``other`` row's evidence and are REQUIRED on an ``other`` row (refused when missing or empty)."""

_COVERS_SEPARATOR = ";"
"""The separator between component names in a row's ``covers`` value."""


def parse_covers(text: str, *, where: str) -> tuple[str, ...]:
    """The components a ``covers`` cell lists, in the order written, each one once."""
    names = tuple(part.strip() for part in text.split(_COVERS_SEPARATOR) if part.strip())
    if not names:
        msg = (
            f"{where}: covers is empty; list the components the amount covers as a "
            "semicolon-separated list (exchange, clearing, nfa, other)"
        )
        raise ConfigurationError(msg)
    return names


def owner_template() -> str:
    """The header line an owner-provided file starts with, for the docs and the tests."""
    return ",".join((*OWNER_COLUMNS, *OWNER_OPTIONAL))


def _optional_text(value: object) -> str | None:
    """An optional text cell: ``None`` when it is absent or empty, the text otherwise."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_owner_provided_csv(
    path: Path, *, provided_by: str = "owner", dataset_version: str = DATASET_VERSION
) -> tuple[list[RawFee], str]:
    """Rows from a file the **owner supplied**, with the file's SHA-256 as their evidence.

    CME Group refuses automated access and its published schedules name product buckets rather
    than root tickers, so an exchange fee enters this dataset only as a file a person vouches
    for: ``provided_by`` names them, ``snapshot_sha256`` is the SHA-256 of the file's own bytes,
    and every row's ``quote`` is the exact cell text it was read from. A rate nobody can quote is
    refused (``quote`` is mandatory), and so is a row that leaves out the supplier.

    Dates are ISO ``YYYY-MM-DD``; ``per_side_usd`` is a decimal string and is parsed as a
    ``Decimal`` (a float column would round the money). Empty ``effective_to`` means open-ended.
    """
    if not path.is_file():
        msg = f"{path} does not exist: pass the owner's fee file, or omit owner_provided"
        raise ConfigurationError(msg)
    body = path.read_bytes()
    sha = hashlib.sha256(body).hexdigest()
    frame = pl.read_csv(path, infer_schema=False, null_values=[""], truncate_ragged_lines=False)
    columns = tuple(frame.columns)
    missing = [name for name in OWNER_COLUMNS if name not in columns]
    if missing:
        msg = (
            f"{path}: missing column(s) {missing}; the file needs {owner_template()} "
            "(docs/data/cme-exchange-fees.md)"
        )
        raise ConfigurationError(msg)
    unknown = [name for name in columns if name not in OWNER_COLUMNS + OWNER_OPTIONAL]
    if unknown:
        msg = f"{path}: unknown column(s) {unknown}; the file may only carry {owner_template()}"
        raise ConfigurationError(msg)
    rows: list[RawFee] = []
    for index, record in enumerate(frame.iter_rows(named=True), start=2):
        where = f"{path.name} row {index}"
        root = str(record["root"]).strip()
        if root not in ROOTS:
            msg = f"{where}: root {root!r} is not one of {list(ROOTS)}"
            raise ConfigurationError(msg)
        fee_type = str(record["fee_type"]).strip()
        if fee_type not in FEE_TYPES:
            msg = f"{where}: fee_type {fee_type!r} is not one of {list(FEE_TYPES)}"
            raise ConfigurationError(msg)
        venue = record.get("venue")
        raw_venue = None if venue is None else str(venue).strip()
        venue_text = raw_venue if raw_venue else VENUE_OF[root]
        try:
            effective_from = dt.date.fromisoformat(str(record["effective_from"]).strip())
        except ValueError as exc:
            msg = f"{where}: effective_from {record['effective_from']!r} is not YYYY-MM-DD"
            raise DataQualityError(msg) from exc
        raw_to = record.get("effective_to")
        effective_to = None
        if raw_to is not None and str(raw_to).strip() != "":
            try:
                effective_to = dt.date.fromisoformat(str(raw_to).strip())
            except ValueError as exc:
                msg = f"{where}: effective_to {raw_to!r} is not YYYY-MM-DD (or empty)"
                raise DataQualityError(msg) from exc
        source_url = str(record["source_url"] or "").strip()
        rows.append(
            RawFee(
                root=root,
                venue=venue_text,
                fee_type=fee_type,
                classification_dimension=str(record["classification_dimension"]).strip(),
                classification_value=str(record["classification_value"]).strip(),
                covers=parse_covers(str(record["covers"]), where=where),
                per_side_usd=_parse_amount(str(record["per_side_usd"]), where),
                effective_from=effective_from,
                effective_to=effective_to,
                source_kind=SOURCE_KIND_OWNER,
                provided_by=provided_by,
                source_url=source_url,
                snapshot_sha256=sha,
                quote="" if record["quote"] is None else str(record["quote"]),
                unit=str(record["unit"]).strip(),
                charge_name=_optional_text(record.get("charge_name")),
                applies_quote=_optional_text(record.get("applies_quote")),
                distinct_from=_optional_text(record.get("distinct_from")),
            )
        )
    if not rows:
        msg = f"{path}: no data rows; an empty owner fee file prices nothing (remove the argument)"
        raise ConfigurationError(msg)
    return rows, sha


# --------------------------------------------------------------------------------- the ingestion


def _http_get(url: str) -> bytes:
    """Fetch ``url`` with the browser-shaped headers NFA's site answers (a bare urllib request is
    served the same page; the headers keep it that way if the site tightens)."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body: bytes = response.read()
    return body


def fetch_raw(
    raw_dir: Path,
    *,
    transport: Callable[[str], bytes] | None = None,
    now: Callable[[], int] | None = None,
    pause_s: float = 0.0,
) -> list[dict[str, object]]:
    """Fetch every page this dataset needs into ``raw_dir`` and write its ``MANIFEST.json``.

    One page today: NFA's rulebook page for Bylaw 1301. There is deliberately **no** CME Group
    fetch — its site refuses automated access and the project does not work around that
    (``docs/data/cme-exchange-fees.md``), so exchange fees come from an owner-supplied file
    instead of a crawl.

    An existing file is never re-fetched or rewritten: the folder is the immutable source of
    truth, and :func:`load_snapshots` refuses a byte that changed under a manifest entry.
    ``transport(url) -> bytes``, ``now() -> int`` and ``pause_s`` are the seams a test drives
    without a network or a clock.
    """
    clock = now or time.time_ns
    getter = transport or _http_get
    raw_dir.mkdir(parents=True, exist_ok=True)
    day = dt.datetime.fromtimestamp(clock() / _NS_PER_S, tz=dt.UTC).strftime("%Y%m%d")
    name = f"{day}_nfa-bylaw-1301.html"
    path = raw_dir / "nfa" / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(getter(NFA_BYLAW_URL))
        if pause_s:
            time.sleep(pause_s)
    body = path.read_bytes()
    entries: list[dict[str, object]] = [
        {
            "url": NFA_BYLAW_URL,
            "origin_url": NFA_BYLAW_URL,
            "source": "nfa",
            "kind": "bylaw",
            "path": path.relative_to(raw_dir).as_posix(),
            "retrieved_at": _iso_of_ns(int(path.stat().st_mtime_ns)),
            "capture_at": None,
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }
    ]
    manifest = {
        "note": (
            "Raw, unmodified bytes of the pages exchange_fees_v1 was read from. Never edited and "
            "never re-fetched. No CME Group bytes are stored here on purpose: cmegroup.com "
            "refuses automated access under its website Data Terms of Use, and the project does "
            "not work around that (docs/data/cme-exchange-fees.md)."
        ),
        "store": "exchange_fees",
        "entries": entries,
    }
    (raw_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return entries


def load_snapshots(raw_dir: Path) -> list[Snapshot]:
    """The raw pages recorded in ``raw_dir/MANIFEST.json``, each verified against its SHA-256.

    A byte that no longer hashes to what the manifest recorded is refused: the dataset cites
    those hashes, so a modified raw file would make every row's evidence a lie.
    """
    manifest_path = raw_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        msg = (
            f"{raw_dir} has no {MANIFEST_NAME}: it is not a raw folder this dataset was built "
            "from. Run fetch_raw(raw_dir) first."
        )
        raise ConfigurationError(msg)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        msg = f"{manifest_path}: 'entries' is missing or empty; re-run fetch_raw(raw_dir)"
        raise ConfigurationError(msg)
    snapshots: list[Snapshot] = []
    for entry in entries:
        relative = str(entry["path"])
        path = raw_dir / relative
        if not path.is_file():
            msg = f"{manifest_path} lists {relative}, which is not in the folder"
            raise ConfigurationError(msg)
        body = path.read_bytes()
        sha = hashlib.sha256(body).hexdigest()
        if sha != entry["sha256"]:
            msg = (
                f"{relative}: raw bytes changed (sha256 {sha[:12]}… != manifest "
                f"{str(entry['sha256'])[:12]}…). The raw folder is the immutable source of "
                "truth: restore the file instead of editing it."
            )
            raise DataQualityError(msg)
        snapshots.append(
            Snapshot(
                name=relative,
                source=str(entry["source"]),
                kind=str(entry["kind"]),
                origin=str(entry["origin_url"]),
                retrieved_at=str(entry["retrieved_at"]),
                sha256=sha,
                path=path,
                text=body.decode("utf-8", errors="replace"),
            )
        )
    return snapshots


# ----------------------------------------------------------------------------------- the build


def _covers_text(fee: RawFee) -> str:
    """The stored ``covers`` value: the components separated by ``;``, in the row's own order."""
    return _COVERS_SEPARATOR.join(fee.covers)


def _row_dict(fee: RawFee, dataset_version: str) -> dict[str, object]:
    """The stored row: instants, hash and version attached, money as its decimal string."""
    moment = _day_ns(fee.effective_from)
    row: dict[str, object] = {
        "root": fee.root,
        "venue": fee.venue,
        "fee_type": fee.fee_type,
        "classification_dimension": fee.classification_dimension,
        "classification_value": fee.classification_value,
        "covers": _covers_text(fee),
        "charge_name": fee.charge_name,
        "unit": fee.unit,
        "per_side_usd": str(fee.per_side_usd),
        "effective_from": fee.effective_from,
        "effective_to": fee.effective_to,
        "source_kind": fee.source_kind,
        "provided_by": fee.provided_by,
        "source_url": fee.source_url,
        "snapshot_sha256": fee.snapshot_sha256,
        "quote": fee.quote,
        "applies_quote": fee.applies_quote,
        "distinct_from": fee.distinct_from,
        "event_time": moment,
        "available_at": moment,
        "dataset_version": dataset_version,
    }
    row["record_sha256"] = record_sha256(row)
    return row


def _series_key(fee: RawFee, component: str) -> tuple[str, str, str, str]:
    """The key one component of a row is stored under on a date.

    Every component is keyed by ``(root, classification_dimension, classification_value,
    component)``. There is no wildcard: a row that is the same for every participant says so with
    ``none``/``all`` (its own key), and an NFA row is keyed by its own dimension
    (``nfa_assessment_eligibility = fcm_member``) instead of pricing every requested type.
    """
    return (
        fee.root,
        fee.classification_dimension,
        fee.classification_value,
        component,
    )


def _check_series(fees: Sequence[RawFee]) -> None:
    """Refuse a table in which one component has two rows, or two rows overlap in time.

    ``fee_rows_as_of`` has to return *the* amount for a component on a date; two rows covering it
    under one key would make the answer depend on row order, which is never acceptable for money.
    A row that covers several components is checked once per component, because that is how it is
    charged. Two ``other`` rows with the same ``charge_name``, root and classification that
    overlap are refused by name: that is one charge written twice, not two charges.
    """
    named: dict[tuple[str, str, str, str], list[RawFee]] = {}
    for fee in fees:
        if fee.fee_type == "other":
            key = (
                fee.root,
                str(fee.charge_name),
                fee.classification_dimension,
                fee.classification_value,
            )
            named.setdefault(key, []).append(fee)
    for (root, charge_name, dimension, value), rows in sorted(named.items()):
        ordered = sorted(rows, key=lambda row: row.effective_from)
        for earlier, later in itertools.pairwise(ordered):
            if earlier.effective_to is None or earlier.effective_to >= later.effective_from:
                msg = (
                    f"{root} other {charge_name!r} ({dimension}={value}): the row from "
                    f"{earlier.effective_from} (to {earlier.effective_to or 'open'}) overlaps "
                    f"the row from {later.effective_from}; one charge is one row per period, so "
                    "close one (effective_to) or give the second charge its own charge_name"
                )
                raise ConfigurationError(msg)
    grouped: dict[tuple[str, str, str, str], list[RawFee]] = {}
    for fee in fees:
        for component in fee.covers:
            if component == "other":
                # two NAMED other charges on one date are two charges, not a contradiction; the
                # same name twice is checked above, by charge_name
                continue
            grouped.setdefault(_series_key(fee, component), []).append(fee)
    for key, rows in sorted(grouped.items()):
        root, dimension, value, component = key
        label = f"{root} {component} ({dimension}={value})"
        ordered = sorted(rows, key=lambda row: row.effective_from)
        seen: dict[dt.date, str] = {}
        for row in ordered:
            if row.effective_from in seen:
                msg = (
                    f"{label}: two rows start on {row.effective_from} "
                    f"({seen[row.effective_from]} and {row.source_kind}): one key, one rate"
                )
                raise ConfigurationError(msg)
            seen[row.effective_from] = row.source_kind
        for earlier, later in itertools.pairwise(ordered):
            if earlier.effective_to is None or earlier.effective_to >= later.effective_from:
                msg = (
                    f"{label}: the row from {earlier.effective_from} "
                    f"(to {earlier.effective_to or 'open'}) overlaps the row from "
                    f"{later.effective_from}; close one of them (effective_to) before building. "
                    "A component covered twice on one date is ambiguous, and a covering row is "
                    "charged once"
                )
                raise ConfigurationError(msg)


def build_exchange_fees(
    raw_dir: Path,
    store_root: Path,
    *,
    owner_provided: Iterable[Path] = (),
    dataset_version: str = DATASET_VERSION,
) -> BuildReport:
    """Build ``exchange_fees_v1`` from ``raw_dir`` plus any owner-supplied fee files.

    The NFA rows come from the fetched bylaw page; the ``exchange``, ``clearing`` and ``other``
    rows come only from ``owner_provided`` (see :func:`load_owner_provided_csv`) — with none, the
    dataset holds the regulatory fee and no other component, and :func:`fee_rows_as_of` prices
    nothing for the missing components. The report names the roots each component was priced for,
    so a build cannot look complete when it is not.

    Refuses to overwrite an existing dataset: the dataset is a stable, hash-checked artifact and
    silently replacing it would invalidate every attempt that cited it.
    """
    target = store_root / DATASET
    if target.exists():
        msg = (
            f"{target} already exists: this build refuses to overwrite a stored dataset. Move it "
            "aside, or build into another store root, if you mean to replace it"
        )
        raise ConfigurationError(msg)
    snapshots = load_snapshots(raw_dir)
    bylaws = [snapshot for snapshot in snapshots if snapshot.kind == "bylaw"]
    if len(bylaws) != 1:
        msg = (
            f"{raw_dir} holds {len(bylaws)} NFA bylaw page(s); the build needs exactly one "
            "(move a superseded capture into an archive subfolder)"
        )
        raise ConfigurationError(msg)
    fees: list[RawFee] = parse_nfa_assessment(
        bylaws[0].text, url=bylaws[0].origin, sha256=bylaws[0].sha256
    )
    providers: set[str] = set()
    for path in owner_provided:
        supplied, _ = load_owner_provided_csv(path)
        providers.add(supplied[0].provided_by or "")
        fees.extend(supplied)
    _check_series(fees)
    rows = [_row_dict(fee, dataset_version) for fee in fees]
    frame = pl.DataFrame(rows, orient="row", schema=EXCHANGE_FEE_SCHEMA)
    priced_by_component = {
        component: tuple(sorted({fee.root for fee in fees if component in fee.covers}))
        for component in FEE_TYPES
    }
    unpriced = tuple(
        component for component in FEE_TYPES if set(priced_by_component[component]) != set(ROOTS)
    )
    priced = tuple(sorted({fee.root for fee in fees if fee.fee_type == "exchange"}))
    missing = tuple(root for root in ROOTS if root not in priced)
    today = dt.datetime.now(dt.UTC).date().isoformat()
    exchange_source = (
        f"exchange fees from {len(providers)} owner-provided file(s)"
        if providers
        else "no exchange fees (CME Group refuses automated access; owner file not supplied)"
    )
    manifest = build_dataset(
        store_root,
        DATASET,
        frame,
        schema=EXCHANGE_FEE_SCHEMA,
        sort_keys=EXCHANGE_FEE_SORT_KEYS,
        source=(
            "nfa.futures.org Bylaw 1301(b)(i)(A) (assessment fee per contract per side); "
            f"{exchange_source}; dataset_version={dataset_version}; "
            f"snapshots={len(snapshots)}; built={today}"
        ),
    )
    return BuildReport(
        dataset=str(DATASET),
        rows=manifest.row_count,
        content_hash=manifest.content_hash,
        rows_by_type={
            fee_type: sum(1 for fee in fees if fee.fee_type == fee_type) for fee_type in FEE_TYPES
        },
        rows_by_source={
            kind: sum(1 for fee in fees if fee.source_kind == kind)
            for kind in (SOURCE_KIND_OFFICIAL, SOURCE_KIND_OWNER)
        },
        roots_priced_by_component=priced_by_component,
        unpriced_components=unpriced,
        exchange_roots_priced=priced,
        exchange_roots_missing=missing,
        snapshots=len(snapshots),
    )


# ------------------------------------------------------------------------------- the read API


def _read(store: DataStore, as_of_ns: int, dataset: DatasetId | None = None) -> pl.DataFrame:
    name = DATASET if dataset is None else dataset
    return store.read(name, TimestampNs(as_of_ns)).collect()


def _covers_of(value: object) -> tuple[str, ...]:
    """The components a stored ``covers`` cell lists."""
    return tuple(part.strip() for part in str(value).split(_COVERS_SEPARATOR) if part.strip())


def fee_rows_as_of(
    store: DataStore,
    root: str,
    date: dt.date,
    *,
    profile: ParticipantProfile | None,
    components: Sequence[str],
    dataset: DatasetId | None = None,
) -> FeeLookup:
    """``{component: (USD per side, row record_sha256)}`` for ONE root on ``date``.

    The rows are read at the end of ``date`` (UTC), so a rate that starts later is invisible: a
    backtest cannot be handed a fee that had not taken effect. ``date`` is the calendar date the
    fee applies to (a trade date, not an instant).

    **Only the root asked for is priced.** The previous lookup demanded a row for every one of the
    nine roots and refused otherwise, so an owner file that priced ES alone could not be used at
    all; here an unpriced root is the caller's named gap, not the dataset's refusal.

    **Classification is resolved per component**, not per table: each covering row names the one
    :class:`ParticipantProfile` dimension it needs and the value it states, and
    :func:`resolve_component_rows` decides. A dimension the profile leaves out (or declares
    ``unknown``) makes the component a gap whose reason names that dimension — so an NFA row is a
    gap unless the profile says ``nfa_assessment_eligibility`` — and a row whose value differs
    does not apply. There is no default and no fallback.

    A component no row covers, one whose classification is undeclared, and one whose rows all
    state another value come back in ``gaps`` with their reason; a priced component comes back in
    ``priced``. Neither is ever a zero fee (AGENTS.md section 1.5). A row that covers several
    components (a CME "Exchange Fees for Clearing & Trading" cell is ``fee_type=exchange`` with
    ``covers=exchange;clearing``) is charged once, and each component it covers carries that same
    amount and record hash.

    ``dataset`` reads another built version of the table instead of :data:`DATASET`. Two rows that
    both apply to one component on one date are refused: no rate may be chosen from a
    contradiction.
    """
    if root not in ROOTS:
        msg = f"root {root!r} is not one of {list(ROOTS)}: the fee table prices those roots only"
        raise ConfigurationError(msg)
    requested: list[str] = []
    for component in components:
        if component not in FEE_TYPES:
            msg = f"component {component!r} is not one of {list(FEE_TYPES)}"
            raise ConfigurationError(msg)
        if component not in requested:
            requested.append(component)
    if not requested:
        return FeeLookup()
    as_of_ns = _day_ns(date + dt.timedelta(days=1)) - 1
    frame = _read(store, as_of_ns, dataset).filter(
        (pl.col("root") == root)
        & (pl.col("effective_from") <= date)
        & (pl.col("effective_to").is_null() | (pl.col("effective_to") >= date))
    )
    records = sorted(frame.iter_rows(named=True), key=lambda row: str(row["record_sha256"]))
    priced: dict[str, tuple[Decimal, str]] = {}
    gaps: dict[str, str] = {}
    for component in requested:
        covering = [record for record in records if component in _covers_of(record["covers"])]
        indices, reason = resolve_component_rows(
            where=f"{root} {component} on {date.isoformat()}",
            classifications=[
                (str(record["classification_dimension"]), str(record["classification_value"]))
                for record in covering
            ],
            profile=profile,
            labels=[str(record["record_sha256"]) for record in covering],
            multiple=component == "other",
        )
        if not indices:
            assert reason is not None
            gaps[component] = reason
            continue
        if component == "other":
            # distinct NAMED other charges are distinct charges: each is added, and the
            # component's identity is the set of rows that charged it
            chosen = [covering[index] for index in indices]
            total = sum((Decimal(str(record["per_side_usd"])) for record in chosen), Decimal(0))
            joined = ";".join(sorted(str(record["record_sha256"]) for record in chosen))
            priced[component] = (total, hashlib.sha256(joined.encode("utf-8")).hexdigest())
            continue
        record = covering[indices[0]]
        priced[component] = (
            Decimal(str(record["per_side_usd"])),
            str(record["record_sha256"]),
        )
    return FeeLookup(priced=priced, gaps=gaps)


def coverage_of(
    frame: pl.DataFrame,
) -> dict[tuple[str, str, str, str], list[tuple[dt.date, dt.date | None]]]:
    """The covered date intervals per ``(root, dimension, value, component)``.

    No interval is invented: a gap between two rows is a gap, and an open-ended row is reported
    with ``None``. A row that covers several components appears under each of them. Used by the
    docs' coverage table and by a caller that wants to know where :func:`fee_rows_as_of` will
    report a missing component before calling it.
    """
    out: dict[tuple[str, str, str, str], list[tuple[dt.date, dt.date | None]]] = {}
    for record in sorted(
        frame.iter_rows(named=True),
        key=lambda row: (
            row["root"],
            row["classification_dimension"],
            row["classification_value"],
            row["effective_from"],
        ),
    ):
        for component in _covers_of(record["covers"]):
            entry = out.setdefault(
                (
                    str(record["root"]),
                    str(record["classification_dimension"]),
                    str(record["classification_value"]),
                    component,
                ),
                [],
            )
            end = record["effective_to"]
            start = _as_date(record["effective_from"])
            entry.append((start, None if end is None else _as_date(end)))
    return out


def _as_date(value: object) -> dt.date:
    """A date from a stored column: a ``date`` already, or its ISO string."""
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    msg = f"cannot read {value!r} as a date"
    raise DataQualityError(msg)
