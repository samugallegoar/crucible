"""The versioned upper-bound cost file: what it prices, what it never prices (ADR-0107 s10).

The owner's decision of 2026-11-23 keeps the per-firm cost-component table as the tracker of which
firms have sourced costs, and adds ONE explicit, versioned upper bound
(``rulesets/prop/cost_assumptions/upper_bound_v1.yaml``) for a preliminary analysis across every
firm. It fills only the gaps: never a component the firm includes, never one the fee dataset priced,
never a commission the firm states. Each firm's total below is written out as arithmetic against the
file's own table, never derived from the engine's output:

- ES/NQ/YM/RTY: exchange 2.00, clearing 0.50, NFA 0.02, other 0.50 (MES/MNQ/MYM/M2K: 0.60, 0.25,
  0.02, 0.25; NKD: 3.00, 0.50, 0.02, 0.50).

A firm-like ruleset below means the component DECLARATIONS a firm's page produces (the real files
live under ``rulesets/prop/<firm>``; their values are the owner's to verify and this test never
touches them): Apex declares every component unknown, Topstep includes exchange and NFA, FundedNext
includes all but ``other``, and FTMO excludes exchange and NFA.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from crucible.core.errors import ConfigurationError
from crucible.data.exchange_fees import (
    EXCHANGE_CLASSIFICATION_DIMENSION,
    EXCHANGE_CLASSIFICATION_VALUE,
    ParticipantProfile,
)
from crucible.execution.futures_sim import CostSchedule
from crucible.prop.costs import (
    ComponentFeeRow,
    ComponentFeeSource,
    ComponentFeeTable,
    CostAssumption,
    CostPricing,
    load_cost_assumption,
    price_components,
)
from crucible.prop.rules_schema import Commissions

ROOT = Path(__file__).resolve().parents[2]
UPPER_BOUND = ROOT / "rulesets" / "prop" / "cost_assumptions" / "upper_bound_v1.yaml"
"""The committed file: its values are the ones the tests hand-sum."""

COMPONENT_NAMES = ("exchange", "clearing", "nfa", "other")

PROFILE = ParticipantProfile.from_mapping(
    {"cme_membership_status": "non_member", "nfa_assessment_eligibility": "fcm_member"}
)

TABLE: dict[str, dict[str, str]] = {
    "ES": {"exchange": "2.00", "clearing": "0.50", "nfa": "0.02", "other": "0.50"},
    "NQ": {"exchange": "2.00", "clearing": "0.50", "nfa": "0.02", "other": "0.50"},
    "YM": {"exchange": "2.00", "clearing": "0.50", "nfa": "0.02", "other": "0.50"},
    "RTY": {"exchange": "2.00", "clearing": "0.50", "nfa": "0.02", "other": "0.50"},
    "NKD": {"exchange": "3.00", "clearing": "0.50", "nfa": "0.02", "other": "0.50"},
    "MES": {"exchange": "0.60", "clearing": "0.25", "nfa": "0.02", "other": "0.25"},
    "MNQ": {"exchange": "0.60", "clearing": "0.25", "nfa": "0.02", "other": "0.25"},
    "MYM": {"exchange": "0.60", "clearing": "0.25", "nfa": "0.02", "other": "0.25"},
    "M2K": {"exchange": "0.60", "clearing": "0.25", "nfa": "0.02", "other": "0.25"},
}
"""The owner's table, written out here by hand so a silent edit of the file fails this test."""


def assumption() -> CostAssumption:
    return load_cost_assumption(UPPER_BOUND)


def declarations(**statuses: str) -> dict[str, dict[str, str]]:
    """The four component declarations; every one not named is ``unknown``."""
    out: dict[str, dict[str, str]] = {}
    for name in COMPONENT_NAMES:
        status = statuses.get(name, "unknown")
        if status == "unknown":
            out[name] = {
                "status": "unknown",
                "evidence": "not_stated",
                "text": "SYNTHETIC TEST VALUE: the sources checked say nothing",
            }
        else:
            out[name] = {
                "status": status,
                "evidence": "official_quote",
                "text": f"SYNTHETIC TEST VALUE: the commission is {status} for this component",
            }
    return out


def commissions(*, per_side: dict[str, str], status: str = "known", **statuses: str) -> Commissions:
    """A firm-like commission table: the declarations plus its own per-side figures."""
    document: dict[str, object] = {
        "status": status,
        "components": declarations(**statuses),
        "per_side_usd": per_side,
        "platform": None,
        "source": {
            "url": "https://example.invalid/synthetic-commissions",
            "quote": "SYNTHETIC TEST VALUE: a commission invented for a test",
            "snapshot_sha256": "0" * 64,
            "retrieved_at": "2024-01-01T00:00:00Z",
            "synthetic": True,
        },
    }
    return Commissions.model_validate(document)


def schedule() -> CostSchedule:
    """The run's own schedule: every field is a sentinel the pricing must overwrite or ignore."""
    return CostSchedule(
        commission=Decimal("9.99"),
        exchange_fee=Decimal("9.99"),
        clearing_fee=Decimal("9.99"),
        regulatory_fee=Decimal("9.99"),
        other_fee=Decimal("9.99"),
        spread_ticks=Decimal(0),
        slippage_ticks=Decimal(0),
    )


def price(
    table: Commissions,
    root: str,
    *,
    fee_source: ComponentFeeSource | None = None,
    file: CostAssumption | None = None,
) -> CostPricing:
    """Price one root against the committed upper bound (or ``file``), with the run's profile."""
    return price_components(
        components=table.components,
        commission_status=table.status,
        commission_per_side=table.per_side(root) if table.status == "known" else None,
        root=root,
        when=dt.date(2024, 1, 8),
        costs=schedule(),
        fee_source=fee_source,
        profile=PROFILE,
        assumption=assumption() if file is None else file,
    )


def amount(pricing: CostPricing, component: str) -> Decimal:
    """The USD the component charges (a priced or included one, never a gap)."""
    charge = pricing.component_charge(component)
    assert charge.usd is not None
    return charge.usd


# ------------------------------------------------------------------ 1. the file and its table


def test_the_file_validates_as_an_unverified_upper_bound_and_holds_the_owners_table() -> None:
    """Owner-provided, unverified, ``kind: upper_bound``, per contract per side: the table."""
    file = assumption()
    assert file.kind == "upper_bound"
    assert file.is_upper_bound is True
    assert file.cost_bound == "upper"
    assert file.provided_by == "owner"
    assert file.status == "unverified"
    assert len(file.sha256) == 64
    assert file.roots == tuple(TABLE)
    for root, row in TABLE.items():
        for component, per_side in row.items():
            entry = file.amount_for(root, component)
            assert entry is not None, f"{root} prices no {component}"
            assert entry.per_side_usd == Decimal(per_side)
            assert entry.unit == "per_contract_per_side"
            assert entry.covers == (component,), "each component is its own entry"
    assert file.amount_for("ES", "other").charge_name == (  # type: ignore[union-attr]
        "unidentified_per_side_charges_upper_bound"
    )


# ------------------------------------------------------------- 2. one firm-like ruleset at a time


def test_an_apex_like_ruleset_is_charged_the_whole_bound_on_top_of_its_commission() -> None:
    """Apex-like: every component unknown, commission 1.55 for ES.

    1.55 + 2.00 + 0.50 + 0.02 + 0.50 = 4.57 per side, and every component is ``assumption``.
    """
    table = commissions(per_side={"ES": "1.55"})
    pricing = price(table, "ES")
    assert pricing.fees_per_side == Decimal("4.57")
    assert pricing.schedule.commission == Decimal("1.55")
    assert pricing.status == "conditional"
    assert pricing.gaps == ()
    assert pricing.priced_by_assumption == ("exchange", "clearing", "nfa", "other")
    assert pricing.cost_bound == "upper"
    for component, expected in (
        ("exchange", "2.00"),
        ("clearing", "0.50"),
        ("nfa", "0.02"),
        ("other", "0.50"),
    ):
        assert pricing.component_charge(component).status == "assumption"
        assert amount(pricing, component) == Decimal(expected)


def test_a_topstep_like_ruleset_is_charged_only_its_two_gaps() -> None:
    """Topstep-like: exchange and NFA included, clearing and other unknown, commission 1.89.

    1.89 + 0.50 + 0.50 = 2.89 per side: the bound's exchange and NFA amounts are never charged, and
    the file listing them is not an error (an upper bound fills only the gaps).
    """
    table = commissions(
        per_side={"ES": "1.89"},
        exchange="included",
        clearing="unknown",
        nfa="included",
        other="unknown",
    )
    pricing = price(table, "ES")
    assert pricing.fees_per_side == Decimal("2.89")
    assert pricing.priced_by_assumption == ("clearing", "other")
    assert pricing.component_charge("exchange").status == "included"
    assert amount(pricing, "exchange") == Decimal(0)
    assert pricing.component_charge("nfa").status == "included"
    assert amount(pricing, "nfa") == Decimal(0)
    assert amount(pricing, "clearing") == Decimal("0.50")
    assert amount(pricing, "other") == Decimal("0.50")


def test_a_fundednext_like_ruleset_adds_only_its_unknown_other() -> None:
    """FundedNext-like: only ``other`` unknown, commission 1.25 -> 1.25 + 0.50 = 1.75 per side."""
    table = commissions(
        per_side={"ES": "1.25"},
        exchange="included",
        clearing="included",
        nfa="included",
        other="unknown",
    )
    pricing = price(table, "ES")
    assert pricing.fees_per_side == Decimal("1.75")
    assert pricing.priced_by_assumption == ("other",)
    assert amount(pricing, "other") == Decimal("0.50")


def test_an_ftmo_like_ruleset_gets_its_excluded_components_from_the_bound() -> None:
    """FTMO-like: exchange and NFA excluded with no fee row, clearing and other unknown.

    Commission 3.00 + 2.00 + 0.02 + 0.50 + 0.50 = 6.02 per side. With no ``ComponentFeeSource`` the
    two excluded components are gaps like the unknown ones, and the bound prices all four.
    """
    table = commissions(
        per_side={"ES": "3.00"},
        exchange="excluded",
        clearing="unknown",
        nfa="excluded",
        other="unknown",
    )
    pricing = price(table, "ES", fee_source=None)
    assert pricing.fees_per_side == Decimal("6.02")
    assert pricing.priced_by_assumption == ("exchange", "clearing", "nfa", "other")
    assert amount(pricing, "exchange") == Decimal("2.00")
    assert amount(pricing, "nfa") == Decimal("0.02")
    assert pricing.status == "conditional"


# --------------------------------------------------- 3. never a priced cost, never a stated one


def test_the_bound_never_double_charges_a_component_the_fee_dataset_priced() -> None:
    """An ``excluded`` exchange the dataset prices keeps the dataset's amount, not the bound's."""
    row = ComponentFeeRow(
        root="ES",
        fee_type="exchange",
        classification_dimension=EXCHANGE_CLASSIFICATION_DIMENSION,
        classification_value=EXCHANGE_CLASSIFICATION_VALUE,
        covers=("exchange",),
        per_side_usd=Decimal("0.77"),
        effective_from=dt.date(2023, 1, 1),
    )
    table = commissions(
        per_side={"ES": "3.00"},
        exchange="excluded",
        clearing="unknown",
        nfa="excluded",
        other="unknown",
    )
    pricing = price(table, "ES", fee_source=ComponentFeeTable(rows=(row,), source_sha256="1" * 64))
    assert pricing.component_charge("exchange").status == "excluded_priced"
    assert amount(pricing, "exchange") == Decimal("0.77")
    assert "exchange" not in pricing.priced_by_assumption
    assert pricing.fees_per_side == Decimal("3.00") + Decimal("0.77") + Decimal("0.02") + (
        Decimal("0.50") + Decimal("0.50")
    )


def test_the_bound_never_overrides_a_commission_the_firm_states() -> None:
    """The file prices no commission: the firm's own per-side figure is what is charged."""
    table = commissions(per_side={"ES": "1.55"})
    pricing = price(table, "ES")
    assert pricing.schedule.commission == Decimal("1.55")
    assert pricing.component_charge("commission").status == "known"
    assert "commission" not in pricing.priced_by_assumption


def test_a_point_estimate_file_still_refuses_a_component_the_firm_already_has() -> None:
    """Only an ``upper_bound`` file may list a cost the firm states; a point estimate is refused."""
    table = commissions(per_side={"ES": "1.89"}, exchange="included")
    point = CostAssumption(
        name="synthetic-owner-estimate",
        description="SYNTHETIC TEST VALUE",
        provided_by="owner",
        status="unverified",
        evidence="SYNTHETIC TEST VALUE",
        amounts=assumption().amounts,
        sha256=assumption().sha256,
        source_path=assumption().source_path,
        kind="point_estimate",
    )
    with pytest.raises(ConfigurationError, match="may not override"):
        price(table, "ES", file=point)


# --------------------------------------------------------- 4. micro rows, and a root it lacks


def test_a_micro_root_is_charged_the_micro_row() -> None:
    """MES: 0.51 + 0.60 + 0.25 + 0.02 + 0.25 = 1.63 per side, never ES's 4.57."""
    table = commissions(per_side={"MES": "0.51"})
    pricing = price(table, "MES")
    assert pricing.fees_per_side == Decimal("1.63")
    assert amount(pricing, "exchange") == Decimal("0.60")
    assert amount(pricing, "other") == Decimal("0.25")


def test_a_root_the_file_does_not_price_stays_a_named_gap() -> None:
    """A root missing from the file is a named gap: the file never extrapolates a component."""
    table = commissions(per_side={"CL": "2.50"})
    pricing = price(table, "CL")
    assert pricing.status == "unavailable"
    assert pricing.gaps == ("exchange", "clearing", "nfa", "other")
    assert pricing.fees_per_side == Decimal("2.50")
    assert pricing.cost_bound == "upper"
    text = pricing.gap_text or ""
    for component in ("exchange", "clearing", "nfa", "other"):
        assert f"{component}:" in text


# ------------------------------------------------------------------ 5. what the kind claims


def test_an_upper_bound_is_never_a_point_estimate_and_never_complete() -> None:
    """The kind is a claim, not an amount: with every gap priced the cost is ``conditional``."""
    assert assumption().is_upper_bound is True
    pricing = price(commissions(per_side={"ES": "1.55"}), "ES")
    assert pricing.status == "conditional"
    assert pricing.cost_bound == "upper"
    assert pricing.assumption_kind == "upper_bound"
