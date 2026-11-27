"""The FTMO rulesets after the owner review round of 2026-11-27 (ADR-0107 amendment).

The six files are corrected in place on the owner's delegation (packet
``internal/reviews/ftmo.md``, F1-F22) and stay ``unverified``: only the owner confirms a ruleset.
What this file pins, so a later edit cannot undo it silently, is the set of DECLARATIONS the round
added - no rule value moved - and the two conditions an automated run now carries:

- the four payout sentences the cap, 90/10 ratio, $20 minimum and withdrawable share rest on are
  ``supporting_sources`` of ``funded_payout``, and ``min_profit_since_last_usd`` 0 is an
  ``owner_decision`` assumption (F3, F17);
- both session-relative ``flat_by`` rules are ``provisional_conservative`` assumptions with the
  absolute clock as a supporting source, and the 60-day ``funded_inactivity`` close is one too while
  the 30-day warning is an immaterial ``not_modeled`` entry (F4, F5);
- ``cross_account_hedging`` carries the cross-firm id and its ``becomes_immaterial_if``, and every
  other immaterial entry with a real condition states it (F10);
- the unfair-advantage automation sentence is a ``material`` + ``block`` compliance rule on
  ``automated`` (the permitted sentence stays the context), so an automated run lists TWO conditions
  and a manual run one, with the copy-trading ban kept (F12, F18, F21);
- ``clearing`` and ``other`` stay ``unknown`` (F1, F2), ``eval_consistency`` reads ``<=`` on "not
  more than 40%" (F20), the nine equity-index roots are the scope (F19) and ``as_of`` stays
  2026-11-22 (F22).

The quote/hash self-check needs the private snapshots folder, which is not in the repository:
``uv run crucible prop validate <file> --snapshots-root D:/proyectos/crucible-notes/internal/
prop_snapshots/ftmo`` reports 33 attributions on a Growth file and 34 on a Pro file, every quote and
hash verified.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from crucible.prop.attempt import practical_eligibility
from crucible.prop.ruleset import load_ruleset

ROOT = Path(__file__).resolve().parents[2]
FTMO = ROOT / "rulesets" / "prop" / "ftmo"
FILES = sorted(FTMO.glob("*.v1.yaml"))
"""Every FTMO variant: Futures Growth and Futures Pro at 50K, 100K and 150K."""

CAP = {
    "ftmo-futures-growth-50k.v1.yaml": "$2,500",
    "ftmo-futures-growth-100k.v1.yaml": "$3,000",
    "ftmo-futures-growth-150k.v1.yaml": "$4,000",
    "ftmo-futures-pro-50k.v1.yaml": "$5,000",
    "ftmo-futures-pro-100k.v1.yaml": "$6,000",
    "ftmo-futures-pro-150k.v1.yaml": "$8,000",
}
SHARE = {
    "ftmo-futures-growth-50k.v1.yaml": "50%",
    "ftmo-futures-growth-100k.v1.yaml": "50%",
    "ftmo-futures-growth-150k.v1.yaml": "50%",
    "ftmo-futures-pro-50k.v1.yaml": "100%",
    "ftmo-futures-pro-100k.v1.yaml": "100%",
    "ftmo-futures-pro-150k.v1.yaml": "100%",
}
CONDITIONS = {
    "automated": (
        "compliance_no_copy_or_third_party_trading",
        "compliance_no_unfair_advantage_automation",
    ),
    "manual": ("compliance_no_copy_or_third_party_trading",),
}


def rules(files: list[Path]):
    """``(path, ruleset)`` pairs, so a failure names the file."""
    return [(path, load_ruleset(path)) for path in files]


def rule(ruleset, rule_id: str):
    for phase in ruleset.phases:
        for item in (*phase.rules, *phase.pass_conditions, *phase.fees):
            if item.rule_id == rule_id:
                return item
    raise AssertionError(f"no rule {rule_id}")


def test_all_six_files_load_and_stay_unverified() -> None:
    assert len(FILES) == 6
    for path, ruleset in rules(FILES):
        assert ruleset.verified is False, path.name
        assert ruleset.schema_version == 2
        assert ruleset.as_of == dt.date(2026, 11, 22), path.name  # F22


def test_the_nine_equity_index_roots_are_the_scope() -> None:
    """F19: ES, NQ, YM, RTY, NKD at weight 1 and their micros at 0.1."""
    expected = {"ES", "NQ", "YM", "RTY", "NKD", "MES", "MNQ", "MYM", "M2K"}
    for path, ruleset in rules(FILES):
        assert {instrument.root for instrument in ruleset.instruments} == expected, path.name


def test_clearing_and_other_stay_unknown() -> None:
    """F1/F2: the page names three cost parts and no clearing or other charge."""
    for path, ruleset in rules(FILES):
        components = ruleset.commissions.components
        assert components.status("exchange") == "excluded", path.name
        assert components.status("nfa") == "excluded", path.name
        assert components.status("clearing") == "unknown", path.name
        assert components.status("other") == "unknown", path.name


def test_both_flat_rules_declare_the_session_relative_reading() -> None:
    """F4: ``provisional_conservative`` on BOTH phases, with the absolute clock carried."""
    for path, ruleset in rules(FILES):
        for rule_id in ("eval_flat_by", "funded_flat_by"):
            flat = rule(ruleset, rule_id)
            assert flat.evidence == "assumption", path.name
            (assumption,) = flat.all_assumptions()
            assert assumption.assumption_kind == "provisional_conservative", path.name
            assert "delegated to the coordinator 2026-11-27" in assumption.rationale, path.name
            assert flat.minutes_before_session_end == 50, path.name
            # the ABSOLUTE clock is a supporting source of the rule
            quotes = " ".join(item.quote for item in flat.all_sources())
            assert "4:10 p" in quotes, path.name


def test_the_inactivity_close_is_an_assumption_and_the_warning_is_not_modeled() -> None:
    """F5: the 60-day close is read, the 30-day warning is immaterial and changes no outcome."""
    for path, ruleset in rules(FILES):
        closed = rule(ruleset, "funded_inactivity")
        (assumption,) = closed.all_assumptions()
        assert assumption.assumption_kind == "provisional_conservative", path.name
        assert closed.max_gap == 60, path.name
        entries = {entry.rule: entry for entry in ruleset.not_modeled}
        warning = entries["inactivity_warning_30_days"]
        assert warning.materiality == "immaterial", path.name
        assert "30 consecutive calendar days" in warning.source.quote, path.name
        assert warning.becomes_immaterial_if is None, path.name


def test_the_payout_terms_carry_their_own_sentences() -> None:
    """F3: the cap, the 90/10 ratio, the $20 minimum and the share are attributions of the rule."""
    for path, ruleset in rules(FILES):
        payout = rule(ruleset, "funded_payout")
        quotes = [item.quote for item in payout.supporting_sources]
        assert len(quotes) == 4, path.name
        assert any(f"The Payout Cap is {CAP[path.name]} per request." == quote for quote in quotes)
        assert any("operates on a 90/10 ratio" in quote for quote in quotes)
        assert any("minimum amount available for payout is $20" in quote for quote in quotes)
        assert any(
            f"withdraw up to {SHARE[path.name]} of your Profit above the Initial Simulated"
            in " ".join(quote.split())
            for quote in quotes
        )
        for item in payout.supporting_sources:
            assert item.snapshot_sha256 == (
                "d18fbddf728f67093605e9b0651c640447417038831ce759732c8e299abddcc2"
            ), path.name
            assert item.synthetic is False, path.name


def test_no_minimum_net_profit_since_the_last_payout_is_the_owners_decision() -> None:
    """F17: FTMO states no positive net-profit gate, so 0 is declared as an owner decision."""
    for path, ruleset in rules(FILES):
        payout = rule(ruleset, "funded_payout")
        assert payout.min_profit_since_last_usd == 0, path.name
        (assumption,) = payout.all_assumptions()
        assert assumption.assumption_kind == "owner_decision", path.name
        assert "delegated to the coordinator 2026-11-27" in assumption.rationale, path.name


def test_cross_account_hedging_has_the_cross_firm_id_and_its_condition() -> None:
    """F10: the id and the ``becomes_immaterial_if`` text the cross-firm ruling asks for."""
    for path, ruleset in rules(FILES):
        entries = {entry.rule: entry for entry in ruleset.not_modeled}
        assert "hedging_and_netting_across_accounts" not in entries, path.name
        hedging = entries["cross_account_hedging"]
        assert hedging.materiality == "immaterial", path.name
        assert hedging.becomes_immaterial_if == (
            "becomes material if several accounts, copy trading or coordinated strategies are "
            "simulated"
        ), path.name
        # the other immaterial entries that have a real condition state it too
        for name in (
            "live_funded_account",
            "evaluation_vs_funded_mismatch",
            "exploit_simulation_artifacts",
            "max_concurrent_accounts_3",
        ):
            assert entries[name].becomes_immaterial_if, (path.name, name)


def test_the_material_not_modeled_rules_stay_material() -> None:
    """F6-F9: the four questions asked to stay material."""
    expected = {
        "cme_price_limit_2pct_entry_ban",
        "discretionary_risk_management_clause",
        "inconsistent_position_sizing",
        "news_event_concentration",
    }
    for path, ruleset in rules(FILES):
        material = {entry.rule for entry in ruleset.not_modeled if entry.materiality == "material"}
        assert material == expected, path.name
        assert all(
            entry.becomes_immaterial_if is None
            for entry in ruleset.not_modeled
            if entry.rule in expected
        ), path.name


def test_the_unfair_advantage_ban_is_a_material_block_on_automated_only() -> None:
    """F18: the second condition an automated run carries, and no ``not_modeled`` HFT entry."""
    for path, ruleset in rules(FILES):
        ban = rule(ruleset, "compliance_no_unfair_advantage_automation")
        assert ban.materiality == "material", path.name
        assert ban.action == "block", path.name
        assert ban.applies_to_execution == ("automated",), path.name
        assert "Automated trading is permitted." in ban.source.quote, path.name
        entries = {entry.rule for entry in ruleset.not_modeled}
        assert "hft_and_latency_arbitrage_ban" not in entries, path.name


@pytest.mark.parametrize(("mode", "expected"), CONDITIONS.items())
def test_practical_eligibility_lists_the_conditions_per_mode(mode: str, expected: tuple[str, ...]):
    """F12/F18/F21: ``eligible_conditional`` in both modes, with the conditions named in order."""
    for path, ruleset in rules(FILES):
        eligibility = practical_eligibility(ruleset, mode)  # type: ignore[arg-type]
        assert eligibility.status == "eligible_conditional", path.name
        assert eligibility.blocker is None, path.name
        listed = tuple(item.split(":", 1)[0] for item in eligibility.conditions)
        assert listed == expected, path.name


def test_the_consistency_boundary_admits_exactly_the_limit() -> None:
    """F20: "does not represent more than 40%" (50% on Pro) is ``<=``."""
    for path, ruleset in rules(FILES):
        consistency = rule(ruleset, "eval_consistency")
        assert consistency.comparison == "<=", path.name
        assert str(consistency.max_day_share) in {"0.4", "0.5"}, path.name
