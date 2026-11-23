"""The run's participant profile and the strict evidence an ``other`` fee row needs.

Owner decisions of 2026-11-22 (ADR-0107, "Amendment (2026-11-22, second)"), each pinned by a test
below:

- a run declares an immutable participant PROFILE (dimension -> value), and a fee row declares the
  ONE dimension it needs (``classification_dimension``) and the value it states;
- the classification is resolved PER COMPONENT: a dimension the profile leaves out (or declares
  ``unknown``) is a gap whose reason names it, a different value makes the row inapplicable, exactly
  one applicable row prices a component, two are refused, none is a gap — never a default and never
  a fallback to the only row there is;
- an ``other`` row is a named, sourced, per-side charge with its own evidence, or it is refused;
  two distinctly named charges are two charges and are summed.

Every number is SYNTHETIC (``0.62``, ``0.01``, ``0.03`` and the words ``SYNTHETIC TEST VALUE``),
and every expectation is written out as arithmetic. No real exchange fee appears here.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from crucible.core.errors import ConfigurationError
from crucible.data import exchange_fees as ef
from crucible.data.store import ParquetDataStore
from crucible.execution.futures_sim import CostSchedule
from crucible.prop.attempt import cash_estimate
from crucible.prop.costs import (
    PARTICIPANT_PROFILE_REASON,
    load_cost_assumption,
    price_components,
    store_component_fees,
)
from crucible.prop.rules_schema import Commissions

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

WHEN = dt.date(2026, 8, 3)
"""The attempt date every resolution test prices: the official NFA rows cover it."""

CME_PAGE = "https://www.cmegroup.com/company/clearing-fees/historical-fees.html"
"""The owner's document; nothing here is fetched from it."""

BYLAW_SENTENCE = (
    "(b) FCM Members. (i) Each FCM Member shall pay to NFA an assessment equal to: "
    "(A) $.02 for each commodity futures contract traded on or entered into subject to the rules "
    "of a contract market (other than an option contract) on a round-turn basis during the period "
    "of July 1, 2026, through June 30, 2027, after which time the assessment will be equal to "
    "$.04 for each commodity futures contract traded on or entered into subject to the rules of a "
    "contract market (other than an option contract) on a round-turn basis; "
    "(B) $.01 for each option contract traded on or entered into subject to the rules of a "
    "contract market on a per trade basis during the period of July 1, 2026, through June 30, "
    "2027."
)

COMPONENTS = ("exchange", "clearing", "nfa", "other")


def profile(**values: str) -> ef.ParticipantProfile:
    """The run's participant profile, from dimension -> value pairs."""
    return ef.ParticipantProfile.from_mapping(values)


NON_MEMBER = profile(cme_membership_status="non_member")
"""A profile that declares the exchange dimension and nothing else."""

BOTH = profile(cme_membership_status="non_member", nfa_assessment_eligibility="fcm_member")
"""A profile that declares both dimensions the dataset's rows name."""


def bylaw_page() -> str:
    """The NFA rulebook page carrying Bylaw 1301, in the shape the site serves it."""
    return (
        "<html><body><div id='main-content'><h2>Chapter 13</h2>"
        f"<p><strong>BYLAW 1301.</strong> {BYLAW_SENTENCE}</p></div></body></html>"
    )


def raw_folder(tmp_path: Path) -> Path:
    """A raw folder with the bylaw page in it, written the way ``fetch_raw`` writes it."""
    body = bylaw_page().encode("utf-8")
    ef.fetch_raw(tmp_path / "raw", transport=lambda _url: body, now=lambda: 1_766_000_000 * 10**9)
    return tmp_path / "raw"


def owner_csv(rows: Sequence[Mapping[str, str]]) -> str:
    """An owner-provided fee file: the documented header plus one line per row (CSV-quoted)."""
    fields = ef.owner_template().split(",")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(fields)
    for row in rows:
        writer.writerow([row.get(name, "") for name in fields])
    return buffer.getvalue()


def build(
    tmp_path: Path, rows: Sequence[Mapping[str, str]] = (), *, name: str = "store"
) -> ParquetDataStore:
    """A built fee dataset: the official NFA rows plus the owner rows given."""
    owner = tmp_path / f"{name}-owner.csv"
    owner.write_text(owner_csv(rows), encoding="utf-8", newline="\n")
    ef.build_exchange_fees(
        raw_folder(tmp_path), tmp_path / name, owner_provided=[owner] if rows else []
    )
    return ParquetDataStore(tmp_path / name)


def exchange_row(**overrides: str) -> dict[str, str]:
    """One SYNTHETIC exchange row: ES non-member, 0.62 USD per side from 2026-01-01."""
    row = {
        "root": "ES",
        "fee_type": "exchange",
        "classification_dimension": ef.EXCHANGE_CLASSIFICATION_DIMENSION,
        "classification_value": ef.EXCHANGE_CLASSIFICATION_VALUE,
        "covers": "exchange",
        "per_side_usd": "0.62",
        "unit": ef.UNIT_PER_CONTRACT_PER_SIDE,
        "effective_from": "2026-01-01",
        "source_url": CME_PAGE,
        "quote": "SYNTHETIC TEST VALUE: ES exchange fee 0.62 per side",
    }
    row.update(overrides)
    return row


def other_row(**overrides: str) -> dict[str, str]:
    """One SYNTHETIC ``other`` row: a NAMED, per-side, CME-sourced charge of 0.03 from 2026-01-01.

    It is the same for every participant (``none``/``all``), so it needs no profile entry.
    """
    row = {
        "root": "ES",
        "fee_type": "other",
        "classification_dimension": ef.CLASSIFICATION_DIMENSION_NONE,
        "classification_value": ef.CLASSIFICATION_VALUE_ALL,
        "covers": "other",
        "charge_name": "CME Globex connectivity fee",
        "per_side_usd": "0.03",
        "unit": ef.UNIT_PER_CONTRACT_PER_SIDE,
        "effective_from": "2026-01-01",
        "source_url": CME_PAGE,
        "quote": "SYNTHETIC TEST VALUE: a 0.03 per-contract-saide charge",
        "applies_quote": "SYNTHETIC TEST VALUE: applies to every clearing member firm per side",
        "distinct_from": (
            "SYNTHETIC TEST VALUE: a connectivity charge, not the exchange, clearing or NFA fee"
        ),
    }
    row.update(overrides)
    return row


def components(**statuses: str) -> Commissions:
    """A commission declaring each component, every one not named ``unknown``."""
    documents: dict[str, dict[str, str]] = {}
    for name in COMPONENTS:
        status = statuses.get(name, "unknown")
        if status == "unknown":
            documents[name] = {
                "status": "unknown",
                "evidence": "not_stated",
                "text": "SYNTHETIC TEST VALUE: the sources checked say nothing",
            }
        else:
            documents[name] = {
                "status": status,
                "evidence": "official_quote",
                "text": f"SYNTHETIC TEST VALUE: the commission is {status} for this component",
            }
    return Commissions.model_validate(
        {
            "status": "known",
            "components": documents,
            "per_side_usd": {"ES": "0.50"},
            "platform": None,
            "source": {
                "url": "https://example.invalid/synthetic-commissions",
                "quote": "SYNTHETIC TEST VALUE: a commission invented for a test",
                "snapshot_sha256": "0" * 64,
                "retrieved_at": "2024-01-01T00:00:00Z",
                "synthetic": True,
            },
        }
    )


def cost_schedule() -> CostSchedule:
    """The run's own schedule: every field is a sentinel the pricing must overwrite."""
    return CostSchedule(
        commission=Decimal("9.99"),
        exchange_fee=Decimal("9.99"),
        clearing_fee=Decimal("9.99"),
        regulatory_fee=Decimal("9.99"),
        other_fee=Decimal("9.99"),
    )


def price(
    table: Commissions,
    store: ParquetDataStore,
    *,
    who: ef.ParticipantProfile | None = BOTH,
    assumption: object = None,
):
    """``price_components`` for ES on ``WHEN``, priced from the stored fee dataset."""
    return price_components(
        components=table.components,
        commission_status=table.status,
        commission_per_side=table.per_side("ES"),
        root="ES",
        when=WHEN,
        costs=cost_schedule(),
        fee_source=store_component_fees(store),
        profile=who,
        assumption=assumption,  # type: ignore[arg-type]
    )


# ------------------------------------------------ 1. two components, two dimensions, one profile


def test_the_profile_resolves_two_components_through_two_dimensions(tmp_path: Path) -> None:
    """0.50 commission + 0.62 exchange (cme_membership_status=non_member) + 0.01 NFA = 1.13.

    The exchange row needs ``cme_membership_status = non_member``; the official NFA row needs
    ``nfa_assessment_eligibility = fcm_member``. One profile declares both, so both components are
    priced, each from its own row, and the cost is ``conditional``: the profile is the run's own
    declaration, not the firm's.
    """
    store = build(tmp_path, [exchange_row()])
    pricing = price(
        components(exchange="excluded", clearing="included", nfa="excluded", other="included"),
        store,
    )
    assert pricing.component_charge("exchange").status == "excluded_priced"
    assert pricing.schedule.exchange_fee == Decimal("0.62")
    assert pricing.component_charge("nfa").status == "excluded_priced"
    assert pricing.schedule.regulatory_fee == Decimal("0.01")
    assert pricing.gaps == ()
    assert pricing.fees_per_side == Decimal("0.50") + Decimal("0.62") + Decimal("0.01")
    assert pricing.fees_per_side == Decimal("1.13")
    assert pricing.status == "conditional"
    assert pricing.profile is not None
    assert pricing.profile.sha256 == BOTH.sha256
    assert PARTICIPANT_PROFILE_REASON in pricing.reasons
    status, reasons = cash_estimate(
        payouts_modeled=True,
        payout_cap_unknown=False,
        cost_status=pricing.status,
        cost_assumption=None,
        participant_profile=BOTH.sha256,
    )
    assert status == "conditional"
    assert PARTICIPANT_PROFILE_REASON in reasons


# ------------------------------------------------------------- 2. a dimension the profile lacks


def test_a_missing_nfa_dimension_makes_the_nfa_a_named_gap(tmp_path: Path) -> None:
    """``NON_MEMBER`` declares one dimension: the NFA row's is undeclared, so ``nfa`` is a gap.

    Per side the schedule carries 0.50 + 0.62 + 0 = 1.12, and that is NOT the cost: the cash
    statistic is ``unavailable`` with the reason that names the dimension. There is no
    pass-through from an NFA row to "any participant" any more.
    """
    store = build(tmp_path, [exchange_row()])
    pricing = price(
        components(exchange="excluded", clearing="included", nfa="excluded", other="included"),
        store,
        who=NON_MEMBER,
    )
    assert pricing.schedule.exchange_fee == Decimal("0.62")
    assert pricing.schedule.regulatory_fee == Decimal("0")
    assert pricing.gaps == ("nfa",)
    detail = pricing.component_charge("nfa").detail
    assert "classification nfa_assessment_eligibility not declared" in detail
    assert pricing.status == "unavailable"
    status, reasons = cash_estimate(
        payouts_modeled=True,
        payout_cap_unknown=False,
        cost_status=pricing.status,
        cost_assumption=None,
        fees_incomplete=pricing.gap_text,
    )
    assert status == "unavailable"
    assert any("nfa_assessment_eligibility not declared" in reason for reason in reasons)


# ------------------------------------------------------ 3. a value no row states is not a fallback


def test_a_member_profile_does_not_take_the_only_row_that_is_there(tmp_path: Path) -> None:
    """The dataset holds a ``non_member`` row and the profile says ``member``: a gap, never it.

    The only exchange row on file is not offered as a fallback: the schedule keeps 0 for the
    exchange component and the gap says the row does not match the declared classification.
    """
    store = build(tmp_path, [exchange_row()])
    pricing = price(
        components(exchange="excluded", clearing="included", nfa="excluded", other="included"),
        store,
        who=profile(cme_membership_status="member", nfa_assessment_eligibility="fcm_member"),
    )
    assert pricing.schedule.exchange_fee == Decimal("0")
    assert pricing.gaps == ("exchange",)
    detail = pricing.component_charge("exchange").detail
    assert "no fee row for ES exchange on 2026-08-03" in detail
    assert "cme_membership_status=member" in detail


# ------------------------------------------------------------------ 4. two applicable rows


def test_two_applicable_rows_are_refused_as_ambiguous(tmp_path: Path) -> None:
    """Two rows with DIFFERENT dimensions both match the profile on one date: refused.

    Each row is a valid series on its own (they are different keys), so the build accepts the
    table; the contradiction exists only once a profile matches both, and it is refused by name
    rather than resolved by row order.
    """
    rows = [
        exchange_row(),
        exchange_row(
            classification_dimension="venue_participation",
            classification_value="same_day",
            per_side_usd="0.71",
            quote="SYNTHETIC TEST VALUE: ES exchange fee 0.71 per side under the other reading",
        ),
    ]
    store = build(tmp_path, rows)
    who = profile(cme_membership_status="non_member", venue_participation="same_day")
    with pytest.raises(ConfigurationError, match="fee rows apply"):
        price(
            components(exchange="excluded", clearing="included", nfa="included", other="included"),
            store,
            who=who,
        )


# ---------------------------------------------------------------------- 5. an unknown value


def test_an_unknown_profile_value_is_a_gap_named_by_its_reason(tmp_path: Path) -> None:
    """``unknown`` is allowed and it means unknown: the component is a gap, never priced."""
    store = build(tmp_path, [exchange_row()])
    pricing = price(
        components(exchange="excluded", clearing="included", nfa="included", other="included"),
        store,
        who=profile(cme_membership_status="unknown"),
    )
    assert pricing.gaps == ("exchange",)
    assert pricing.schedule.exchange_fee == Decimal("0")
    assert "classification cme_membership_status not declared" in (
        pricing.component_charge("exchange").detail
    )


# ------------------------------------------------------- 7. the refusals an `other` row earns


@pytest.mark.parametrize(
    "name",
    ["Other", "CME other fees", "misc.", "additional charges", "exchange fees", "MISC"],
)
def test_a_generic_other_name_is_refused(tmp_path: Path, name: str) -> None:
    """A catch-all is not a charge: case and punctuation are stripped before the refusal."""
    path = tmp_path / "generic.csv"
    path.write_text(owner_csv([other_row(charge_name=name)]), encoding="utf-8", newline="\n")
    with pytest.raises(ConfigurationError, match="generic name"):
        ef.load_owner_provided_csv(path)


def test_a_monthly_other_charge_is_refused(tmp_path: Path) -> None:
    """A fixed monthly/platform charge belongs in the ruleset's fee schedule, not here."""
    path = tmp_path / "monthly.csv"
    path.write_text(owner_csv([other_row(unit="monthly")]), encoding="utf-8", newline="\n")
    with pytest.raises(ConfigurationError, match="fee schedule"):
        ef.load_owner_provided_csv(path)


@pytest.mark.parametrize("field", ["applies_quote", "distinct_from"])
def test_an_other_row_without_its_own_evidence_is_refused(tmp_path: Path, field: str) -> None:
    """``applies_quote`` and ``distinct_from`` are both REQUIRED, and empty is missing."""
    path = tmp_path / "evidence.csv"
    path.write_text(owner_csv([other_row(**{field: ""})]), encoding="utf-8", newline="\n")
    with pytest.raises(ConfigurationError, match=f"{field} is required"):
        ef.load_owner_provided_csv(path)


def test_a_non_cme_host_for_a_cme_other_row_is_refused(tmp_path: Path) -> None:
    """The charge has to be quoted from CME Group's own site."""
    path = tmp_path / "host.csv"
    path.write_text(
        owner_csv([other_row(source_url="https://example.invalid/a-blog-post")]),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ConfigurationError, match=r"www\.cmegroup\.com"):
        ef.load_owner_provided_csv(path)


def test_an_exchange_row_may_not_cover_other(tmp_path: Path) -> None:
    """An exchange fee cannot cover other components: that is its own row with its own evidence."""
    path = tmp_path / "covers.csv"
    path.write_text(
        owner_csv([exchange_row(covers="exchange;other")]), encoding="utf-8", newline="\n"
    )
    with pytest.raises(ConfigurationError, match="cannot cover other components"):
        ef.load_owner_provided_csv(path)


def test_two_other_rows_with_one_name_may_not_overlap(tmp_path: Path) -> None:
    """One charge written twice is refused; two DIFFERENT names are two charges (next test)."""
    rows = [
        other_row(effective_from="2026-01-01", effective_to="2026-12-31"),
        other_row(effective_from="2026-06-01", per_side_usd="0.04"),
    ]
    owner = tmp_path / "overlap.csv"
    owner.write_text(owner_csv(rows), encoding="utf-8", newline="\n")
    with pytest.raises(ConfigurationError, match="overlaps"):
        ef.build_exchange_fees(raw_folder(tmp_path), tmp_path / "store", owner_provided=[owner])


# ----------------------------------------------------- 8. a valid `other` row is a real charge


def test_a_named_other_charge_is_priced_only_when_the_component_is_excluded(tmp_path: Path) -> None:
    """Two distinctly named ``other`` rows are two charges: 0.03 + 0.04 = 0.07 per side.

    The declaration, not the dataset's coverage, decides what is charged: with ``other``
    ``unknown`` the rows are not added at all (a gap); with ``other`` ``excluded`` they are summed,
    each once; and a cost-assumption file that prices the gap replaces the sum with ITS number.
    """
    rows = [
        other_row(),
        other_row(
            charge_name="CME market data access fee",
            per_side_usd="0.04",
            quote="SYNTHETIC TEST VALUE: a 0.04 per-contract-side market data charge",
        ),
    ]
    store = build(tmp_path, [exchange_row(), *rows])
    declared = price(
        components(exchange="excluded", clearing="included", nfa="included", other="excluded"),
        store,
    )
    assert declared.schedule.other_fee == Decimal("0.03") + Decimal("0.04")
    assert declared.schedule.other_fee == Decimal("0.07")
    assert declared.component_charge("other").status == "excluded_priced"
    assert declared.fees_per_side == Decimal("0.50") + Decimal("0.62") + Decimal("0.07")
    assert declared.fees_per_side == Decimal("1.19")
    assert declared.gaps == ()

    unknown = price(components(exchange="excluded", clearing="included", nfa="included"), store)
    assert unknown.schedule.other_fee == Decimal("0")
    assert unknown.gaps == ("other",)

    assumption_path = write_assumption(
        tmp_path / "other.yaml",
        [
            {
                "covers": ["other"],
                "per_side_usd": "0.09",
                "unit": "per_contract_per_side",
                "charge_name": "SYNTHETIC TEST VALUE: a named per-side charge",
            }
        ],
    )
    assumed = price(
        components(exchange="excluded", clearing="included", nfa="included"),
        store,
        assumption=load_cost_assumption(assumption_path),
    )
    assert assumed.schedule.other_fee == Decimal("0.09")
    assert assumed.priced_by_assumption == ("other",)
    assert assumed.status == "conditional"


# --------------------------------------------------------- 9. what a cost-assumption entry owes


def write_assumption(path: Path, entries: list[dict[str, object]]) -> Path:
    """A SYNTHETIC cost-assumption file with the given ES entries, dumped as real YAML."""
    document: dict[str, object] = {
        "name": "synthetic-owner-estimate",
        "description": "SYNTHETIC TEST VALUE: an estimate invented for a test",
        "provided_by": "owner",
        "status": "unverified",
        "evidence": "SYNTHETIC TEST VALUE: no document states this split",
        "amounts": {"ES": entries},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8", newline=chr(10))
    return path


def test_an_assumption_entry_needs_the_per_side_unit(tmp_path: Path) -> None:
    """Every amount states ``unit: per_contract_per_side``; missing or monthly is refused."""
    missing = write_assumption(
        tmp_path / "missing-unit.yaml", [{"covers": ["exchange"], "per_side_usd": "0.40"}]
    )
    with pytest.raises(ConfigurationError, match="unit is required"):
        load_cost_assumption(missing)
    monthly = write_assumption(
        tmp_path / "monthly.yaml",
        [{"covers": ["exchange"], "per_side_usd": "0.40", "unit": "monthly"}],
    )
    with pytest.raises(ConfigurationError, match="per_contract_per_side"):
        load_cost_assumption(monthly)


def test_an_assumption_for_other_without_a_charge_name_is_refused(tmp_path: Path) -> None:
    """An assumption covering ``other`` names the charge, exactly as a fee row does."""
    unnamed = write_assumption(
        tmp_path / "no-name.yaml",
        [{"covers": ["other"], "per_side_usd": "0.09", "unit": "per_contract_per_side"}],
    )
    with pytest.raises(ConfigurationError, match="needs charge_name"):
        load_cost_assumption(unnamed)
    generic = write_assumption(
        tmp_path / "generic.yaml",
        [
            {
                "covers": ["other"],
                "per_side_usd": "0.09",
                "unit": "per_contract_per_side",
                "charge_name": "misc.",
            }
        ],
    )
    with pytest.raises(ConfigurationError, match="generic name"):
        load_cost_assumption(generic)


# ------------------------------------------- 10. every ruleset still validates, none re-verified


def test_every_ruleset_still_validates_and_no_verification_status_changed() -> None:
    """INDEX.json's 201 entries keep their hash and their ``unverified`` status.

    The lock is the repository's record of what the owner has and has not confirmed (ADR-0107
    section 1): this change touches no ruleset, so every file must still load to the SAME content
    hash and the SAME verification value the index states.
    """
    from crucible.prop.ruleset import load_ruleset

    root = Path(__file__).resolve().parents[2]
    entries = json.loads((root / "rulesets/prop/INDEX.json").read_text(encoding="utf-8"))
    assert len(entries["entries"]) == 201
    for entry in entries["entries"]:
        assert entry["verification"] == "unverified"
        ruleset = load_ruleset(root / str(entry["path"]))
        assert ruleset.ruleset_sha256 == entry["ruleset_sha256"]
        assert ruleset.verification.status == entry["verification"]
