"""Promotional values that depend on what the run bought (ADR-0107, amendment of 2026-11-23).

The Topstep doubled payout cap is the reference case: it applies ONLY when the account is a new
Trading Combine purchase, the daily-loss-limit add-on was chosen at that purchase, and the purchase
date is on or after the offer start (2026-06-02). Otherwise the standard cap applies, and an
ineligible run is never given the better number: eligibility that cannot be shown is not assumed.

Every ruleset here is synthetic (``tests/fixtures/prop/``); the values are the owner's example
arithmetic (a 2,000 cap doubled to 4,000) and nothing is fetched.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from crucible.core.errors import ConfigurationError
from crucible.data.exchange_fees import ParticipantProfile
from crucible.prop.promotions import promotion_reason, resolve_promotions
from crucible.prop.ruleset import PropRuleset

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "prop"
AS_OF = dt.date(2026, 11, 22)
"""The ruleset's ``as_of``: an offer whose end is unknown is not assumed past it."""


def _promotion(**overrides: object) -> dict[str, object]:
    """The doubled-cap promotion of the owner's decision, on a payout rule's ``max_usd``."""
    promotion: dict[str, object] = {
        "id": "dll_payout_cap_doubled",
        "field": "max_usd",
        "value": "4000",
        "starts_on": "2026-06-02",
        "ends_on": "unknown",
        "purchase_on_or_after": "2026-06-02",
        "requires": {"account_purchase": "new", "dll_selected_at_purchase": "true"},
        "source": {
            "url": "https://example.invalid/synthetic-offer",
            "quote": "SYNTHETIC TEST VALUE: the offer sentence invented for a test",
            "snapshot_sha256": "0" * 64,
            "retrieved_at": "2026-06-01T00:00:00Z",
            "synthetic": True,
        },
    }
    promotion.update(overrides)
    return promotion


def _ruleset(promotion: dict[str, object] | None = None) -> PropRuleset:
    """The payout fixture, with the promotion attached to its first rule."""
    raw = yaml.safe_load((FIXTURES / "synthetic_p_payout.yaml").read_text(encoding="utf-8"))
    raw["as_of"] = AS_OF.isoformat()
    raw["phases"][0]["rules"][0]["promotions"] = [] if promotion is None else [promotion]
    return PropRuleset.model_validate(raw)


def _payout_cap(ruleset: PropRuleset) -> object:
    rule = ruleset.phases[0].rules[0]
    return rule.max_usd


def profile(**values: str) -> ParticipantProfile:
    return ParticipantProfile.from_mapping(values)


ELIGIBLE = profile(
    account_purchase="new",
    dll_selected_at_purchase="true",
    purchase_date="2026-06-10",
)
"""The full eligible profile: a new Combine bought on 2026-06-10 with the DLL add-on."""

BASE_CAP = Decimal("2000")
"""The fixture's standard per-payout cap, which the promotion doubles."""


def test_an_eligible_purchase_applies_the_promoted_value() -> None:
    """A complete eligible profile doubles the cap: 2,000 becomes 4,000, and it is recorded."""
    ruleset = _ruleset(_promotion())
    assert _payout_cap(ruleset) == BASE_CAP
    promoted, outcome = resolve_promotions(ruleset, ELIGIBLE)
    assert _payout_cap(promoted) == Decimal("4000")
    assert outcome.applied_ids == ("dll_payout_cap_doubled",)
    assert outcome.applied == ("dll_payout_cap_doubled:payout:max_usd=4000",)
    assert outcome.not_applied == ()
    # the promoted VALUE differs but nothing else does: the same ruleset id, version and as_of
    assert (promoted.ruleset_id, promoted.version, promoted.as_of) == (
        ruleset.ruleset_id,
        ruleset.version,
        ruleset.as_of,
    )


def test_a_multiplier_scales_the_base_value() -> None:
    """``multiplier: 2`` is the same doubling, taken from the base value rather than stated."""
    promotion = _promotion(value=None, multiplier="2")
    promoted, outcome = resolve_promotions(_ruleset(promotion), ELIGIBLE)
    assert _payout_cap(promoted) == BASE_CAP * 2
    assert outcome.applied_ids == ("dll_payout_cap_doubled",)


def test_without_a_profile_the_base_value_stands_and_the_reason_is_recorded() -> None:
    """Eligibility that cannot be shown is not assumed: 2,000 and a named reason."""
    ruleset = _ruleset(_promotion())
    promoted, outcome = resolve_promotions(ruleset, None)
    assert _payout_cap(promoted) == BASE_CAP
    assert outcome.applied_ids == ()
    assert outcome.not_applied == (
        "promotion dll_payout_cap_doubled not applied: no participant profile was declared",
    )


def test_a_false_purchase_fact_blocks_the_promotion() -> None:
    """``dll_selected_at_purchase: false`` is a declared fact that does NOT match the offer."""
    who = profile(
        account_purchase="new", dll_selected_at_purchase="false", purchase_date="2026-06-10"
    )
    promoted, outcome = resolve_promotions(_ruleset(_promotion()), who)
    assert _payout_cap(promoted) == BASE_CAP
    assert outcome.not_applied == (
        "promotion dll_payout_cap_doubled not applied: dll_selected_at_purchase is 'false', "
        "not 'true'",
    )


def test_a_purchase_before_the_offer_start_is_not_promoted() -> None:
    """2026-06-01 is one day before the offer start, so the standard cap applies."""
    who = profile(
        account_purchase="new", dll_selected_at_purchase="true", purchase_date="2026-06-01"
    )
    promoted, outcome = resolve_promotions(_ruleset(_promotion()), who)
    assert _payout_cap(promoted) == BASE_CAP
    assert outcome.not_applied == (
        "promotion dll_payout_cap_doubled not applied: the purchase on 2026-06-01 is before "
        "2026-06-02",
    )


def test_a_purchase_after_as_of_with_an_unknown_end_is_not_promoted() -> None:
    """``ends_on: unknown`` never continues past the ruleset's ``as_of`` (2026-11-22)."""
    who = profile(
        account_purchase="new", dll_selected_at_purchase="true", purchase_date="2026-11-23"
    )
    promoted, outcome = resolve_promotions(_ruleset(_promotion()), who)
    assert _payout_cap(promoted) == BASE_CAP
    assert outcome.not_applied == (
        "promotion dll_payout_cap_doubled not applied: the purchase on 2026-11-23 is after the "
        "ruleset's as_of 2026-11-22 and the offer's end is unknown",
    )


def test_an_unknown_requirement_is_a_gap_not_a_match() -> None:
    """The literal ``unknown`` in the profile is *not known*, so the base value stands."""
    who = profile(
        account_purchase="new", dll_selected_at_purchase="unknown", purchase_date="2026-06-10"
    )
    promoted, outcome = resolve_promotions(_ruleset(_promotion()), who)
    assert _payout_cap(promoted) == BASE_CAP
    assert "dll_selected_at_purchase is unknown" in outcome.not_applied[0]


def test_a_promotion_needs_exactly_one_of_value_and_multiplier() -> None:
    """The vocabulary refuses a promotion that says neither (or both)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="exactly one of value"):
        _ruleset(_promotion(value=None))
    with pytest.raises(ValidationError, match="exactly one of value"):
        _ruleset(_promotion(multiplier="2"))


def test_two_promotions_on_one_field_are_refused() -> None:
    """Two applicable promotions on the same field would make the value depend on order."""
    ruleset = _ruleset(_promotion())
    rule = ruleset.phases[0].rules[0]
    second = rule.promotions[0].model_copy(update={"id": "another"})
    doubled = rule.model_copy(update={"promotions": (*rule.promotions, second)})
    phase = ruleset.phases[0].model_copy(update={"rules": (doubled,)})
    clashing = ruleset.model_copy(update={"phases": (phase,)})
    with pytest.raises(ConfigurationError, match="two promotions apply"):
        resolve_promotions(clashing, ELIGIBLE)


def test_an_attempt_records_what_it_used_and_cites_the_files_hash() -> None:
    """The attempt carries the promotions it applied and still cites the RULESET FILE's hash.

    ``promotions_applied`` is the per-attempt record (``attempts.parquet``); the promoted value is
    a property of the run, so the artifact's ruleset hash is the file's, not the promoted copy's.
    """
    import polars as pl

    from crucible.data.cme_session_table import cme_session_table
    from crucible.data.cme_sessions import SessionCalendar
    from crucible.data.contracts import ROLL_SCHEMA
    from crucible.data.futures_specs import futures_spec
    from crucible.execution.futures_sim import CostSchedule
    from crucible.prop.attempt import simulate_attempt

    start = int(dt.datetime(2024, 1, 8, 15, 1, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
    bars = pl.DataFrame(
        {
            "event_time": [start + minute * 60_000_000_000 for minute in (0, 1)],
            "open": [5000.0, 5000.0],
            "high": [5000.0, 5000.0],
            "low": [5000.0, 5000.0],
            "close": [5000.0, 5000.0],
            "contract": ["ESH4", "ESH4"],
        }
    )
    targets = pl.DataFrame(
        {"event_time": bars["event_time"], "target": pl.Series([0, 0], dtype=pl.Int64)}
    )

    def attempt(who: ParticipantProfile | None):
        ruleset = _ruleset(_promotion())
        return ruleset, simulate_attempt(
            bars=bars,
            targets=targets,
            rolls=pl.DataFrame(schema=ROLL_SCHEMA),
            spec=futures_spec("ES"),
            costs=CostSchedule(commission=Decimal("2.00")),
            ruleset=ruleset,
            start_trade_date=dt.date(2024, 1, 8),
            max_horizon_days=5,
            calendar=SessionCalendar(cme_session_table(), "ES"),
            execution_mode="manual",
            profile=who,
        )

    ruleset, eligible = attempt(ELIGIBLE)
    assert eligible.promotions_applied == ("dll_payout_cap_doubled:payout:max_usd=4000",)
    assert eligible.ruleset_sha256 == ruleset.ruleset_sha256
    assert eligible.verification_status == ruleset.verification_status
    _, ineligible = attempt(None)
    assert ineligible.promotions_applied == ()


def test_promotion_reason_is_none_when_every_fact_matches() -> None:
    """The reason function is the one rule: everything declared, matching, and in the window."""
    promotion = _ruleset(_promotion()).phases[0].rules[0].promotions[0]
    assert promotion_reason(promotion, ELIGIBLE, as_of=AS_OF) is None
    missing = profile(purchase_date="2026-06-10")
    assert promotion_reason(promotion, missing, as_of=AS_OF) == "account_purchase not declared"
