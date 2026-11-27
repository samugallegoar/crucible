"""The MFFU rulesets after the owner review round of 2026-11-24 (ADR-0107 amendment).

Three properties the review settled, pinned against the committed files so a later edit cannot
undo them silently:

1. **What the cost page's subtitle states.** MFFU publishes one all-in number per contract
   (``Total Cost Round Trip``) and a group phrase for what it contains, "Includes Contract
   Specifications, Commissions, and Trading Fees". That phrase is a statement of inclusion: every
   MFFU file declares ``exchange`` and ``nfa`` ``included`` and keeps ``clearing`` and ``other``
   ``unknown`` (the subtitle does not name them), so the upper-bound cost file prices only the two
   gaps.
2. **The per-side number that follows.** One ES side is 2.34 (the firm's 4.68 round trip / 2) plus
   the bound's clearing 0.50 and other 0.50 = **3.34 USD**, and MES is 0.95 + 0.25 + 0.25 = 1.45.
   Both are written out here by hand, never derived from the engine's output.
3. **Every rule's own number is in one of its quotations.** The review re-quoted 25 attributions
   that quoted a neighbouring sentence (F.34) and the Pro 100K/150K post-payout lock (F.35), so a
   rule's headline number must appear in its own source, a supporting source, or the selected
   source of a conflict on that rule.

Every file stays ``unverified``: these are the owner's decisions applied on the coordinator's
delegation, not a confirmation (ADR-0107 section 2).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from crucible.data.exchange_fees import ParticipantProfile
from crucible.execution.futures_sim import CostSchedule
from crucible.prop.costs import load_cost_assumption, price_components
from crucible.prop.promotions import resolve_promotions
from crucible.prop.rules_schema import (
    MaxContractsRule,
    PayoutRule,
    StaticDrawdownRule,
    TrailingDrawdownRule,
    _Rule,
)
from crucible.prop.ruleset import load_ruleset

ROOT = Path(__file__).resolve().parents[2]
MFFU = ROOT / "rulesets" / "prop" / "mffu"
UPPER_BOUND = ROOT / "rulesets" / "prop" / "cost_assumptions" / "upper_bound_v1.yaml"
FILES = sorted(MFFU.glob("*.v1.yaml"))
"""Every MFFU variant: 5 Builder, 4 Pro, 4 Rapid, 4 Rapid EOD and 3 Studio."""

PROFILE = ParticipantProfile.from_mapping(
    {"cme_membership_status": "non_member", "nfa_assessment_eligibility": "fcm_member"}
)
"""The run profile the bound is priced with; the two included components never consult it."""


def schedule() -> CostSchedule:
    """The run's own schedule: every fee is a sentinel the pricing must overwrite or ignore."""
    return CostSchedule(
        commission=Decimal("9.99"),
        exchange_fee=Decimal("9.99"),
        clearing_fee=Decimal("9.99"),
        regulatory_fee=Decimal("9.99"),
        other_fee=Decimal("9.99"),
        spread_ticks=Decimal(0),
        slippage_ticks=Decimal(0),
    )


def price(path: Path, root: str):
    ruleset = load_ruleset(path)
    commissions = ruleset.commissions
    return price_components(
        components=commissions.components,
        commission_status=commissions.status,
        commission_per_side=commissions.per_side(root),
        root=root,
        when=dt.date(2024, 1, 8),
        costs=schedule(),
        fee_source=None,
        profile=PROFILE,
        assumption=load_cost_assumption(UPPER_BOUND),
    )


def evaluation_fee(ruleset: object):
    phase = ruleset.phases[0]
    return next(rule for rule in phase.fees if rule.rule_id == "evaluation_fee")


def test_all_twenty_files_still_load_and_are_unverified() -> None:
    assert len(FILES) == 20
    for path in FILES:
        ruleset = load_ruleset(path)
        assert ruleset.verified is False, path.name
        assert ruleset.schema_version == 2


def test_the_cost_pages_subtitle_makes_exchange_and_nfa_included() -> None:
    """F.1-F.5: the group phrase states inclusion, and only for what it names."""
    for path in FILES:
        components = load_ruleset(path).commissions.components
        assert components.status("exchange") == "included", path.name
        assert components.status("nfa") == "included", path.name
        assert components.status("clearing") == "unknown", path.name
        assert components.status("other") == "unknown", path.name
        for name in ("exchange", "nfa"):
            declaration = components.declaration(name)
            assert declaration.evidence == "official_quote"
            assert "Includes Contract Specifications, Commissions, and Trading Fees" in (
                declaration.text
            )


@pytest.mark.parametrize(("root", "expected"), [("ES", Decimal("3.34")), ("MES", Decimal("1.45"))])
def test_one_side_of_es_is_the_firms_own_figure_plus_the_two_gaps(
    root: str, expected: Decimal
) -> None:
    """2.34 + 0.50 + 0.50 and 0.95 + 0.25 + 0.25: only the components the subtitle does not name."""
    pricing = price(MFFU / "mffu-rapid-50k.v1.yaml", root)
    assert pricing.fees_per_side == expected
    assert pricing.priced_by_assumption == ("clearing", "other")
    assert pricing.gaps == ()
    assert pricing.status == "conditional"
    assert pricing.cost_bound == "upper"
    assert pricing.component_charge("exchange").usd == Decimal(0)
    assert pricing.component_charge("nfa").usd == Decimal(0)


def own_numbers(rule: _Rule) -> list[str]:
    """The rule's headline numbers, as the strings a page prints them as."""
    numbers: list[str] = []
    if isinstance(rule, TrailingDrawdownRule | StaticDrawdownRule):
        numbers.append(f"{rule.amount_usd:,.0f}")
    elif isinstance(rule, MaxContractsRule):
        limit = rule.limit
        assert limit is not None
        numbers.append(str(limit))
    elif isinstance(rule, PayoutRule):
        numbers.extend(
            f"{value:,.0f}"
            for value in (rule.buffer_usd, rule.min_usd, rule.min_profit_since_last_usd)
        )
        if isinstance(rule.max_usd, Decimal):
            numbers.append(f"{rule.max_usd:,.0f}")
        share = rule.split * 100
        numbers.append("|".join((f"{share:.0f}%", f"{share:.0f}/")))
    return numbers


def test_every_rules_own_number_is_in_one_of_its_quotations() -> None:
    """F.34/F.35: a reader checking an attribution alone must be able to see the number.

    A weighted contract limit below one mini (5 micros -> 0.5) is the one sanctioned exception: the
    page prints the micro count and the description states the 0.1-per-micro conversion.
    """
    problems: list[str] = []
    for path in FILES:
        ruleset = load_ruleset(path)
        for phase in ruleset.phases:
            for rule in (*phase.rules, *phase.pass_conditions, *phase.fees):
                quotes = [rule.source.quote]
                quotes.extend(source.quote for source in rule.supporting_sources)
                for conflict in ruleset.conflicts:
                    if conflict.rule_id == rule.rule_id:
                        quotes.append(conflict.selected_source.quote)
                blob = " ".join(quotes)
                # A weighted limit below one mini (5 micros -> 0.5) is the one exception: the page
                # prints the micro count and the description states the 0.1-per-micro conversion.
                if isinstance(rule, MaxContractsRule) and rule.limit is not None and rule.limit < 1:
                    continue
                for number in own_numbers(rule):
                    if not any(option in blob for option in number.split("|")):
                        problems.append(f"{path.name} {phase.phase_id}.{rule.rule_id}: {number}")
    assert not problems, problems


def test_the_published_discounts_are_promotions_on_the_list_price() -> None:
    """F.8: the base fee is the list price, and the discount the run bought is the one applied."""
    ruleset = load_ruleset(MFFU / "mffu-rapid-50k.v1.yaml")
    fee = evaluation_fee(ruleset)
    assert fee.amount_usd == Decimal("209")
    ids = {promotion.id for promotion in fee.promotions}
    assert ids == {"club_40_off_any_plan", "new_trader_50_off_first_evaluation"}
    club = next(promotion for promotion in fee.promotions if promotion.id == "club_40_off_any_plan")
    assert club.multiplier == Decimal("0.6")
    assert club.requires["coupon_applied"] == "CLUB"
    assert club.ends_on == "unknown"

    club_profile = ParticipantProfile.from_mapping(
        {
            "account_purchase": "new",
            "coupon_applied": "CLUB",
            "discount_taken": "club_40_off",
            "purchase_date": "2026-11-22",
        }
    )
    promoted, outcome = resolve_promotions(ruleset, club_profile)
    assert evaluation_fee(promoted).amount_usd == Decimal("209") * Decimal("0.6")
    assert any("club_40_off_any_plan" in entry for entry in outcome.applied)

    first_eval = ParticipantProfile.from_mapping(
        {
            "account_purchase": "new",
            "discount_taken": "first_evaluation_50_off",
            "purchase_date": "2026-11-22",
        }
    )
    promoted, outcome = resolve_promotions(ruleset, first_eval)
    assert evaluation_fee(promoted).amount_usd == Decimal("104.5")
    assert any("new_trader_50_off_first_evaluation" in entry for entry in outcome.applied)

    base, outcome = resolve_promotions(ruleset, None)
    assert evaluation_fee(base).amount_usd == Decimal("209")
    assert outcome.applied == ()


def test_the_builder_guide_rows_are_the_printed_prices() -> None:
    """The guide prints 107 / 87 at 30% off and 92 / 75 at 40% off; both are declared."""
    for name, off30, off40 in (
        ("mffu-builder-50k.v1.yaml", Decimal("107"), Decimal("92")),
        ("mffu-builder-50k-addon.v1.yaml", Decimal("87"), Decimal("75")),
    ):
        ruleset = load_ruleset(MFFU / name)
        fee = evaluation_fee(ruleset)
        rows = {promotion.id: promotion for promotion in fee.promotions}
        assert rows["builder_guide_30_off"].value == off30, name
        assert rows["builder_guide_40_off_two_uses_only"].value == off40, name
        taken = ParticipantProfile.from_mapping(
            {
                "account_purchase": "new",
                "discount_taken": "builder_40_off_two_uses",
                "purchase_date": "2026-11-22",
            }
        )
        promoted, _ = resolve_promotions(ruleset, taken)
        assert evaluation_fee(promoted).amount_usd == off40, name
