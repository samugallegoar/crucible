"""Prop-firm rulesets and rule coverage (ADR-0106 sections 2, 4 and 5), against synthetic data.

The fixtures under ``tests/fixtures/prop/`` are invented: "SyntheticFirm A", example.invalid URLs,
invented values, every attribution marked ``synthetic: true``. No real firm's rule, name or URL
appears in the code or the fixtures.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.prop import rules as rl
from crucible.prop.coverage import (
    counterfactual_application,
    coverage_warnings,
    evaluation_status,
    material_unmodeled,
    rule_coverage,
)
from crucible.prop.ruleset import (
    PASS_KINDS,
    Attribution,
    Instrument,
    Phase,
    PropRuleset,
    Verification,
    load_registry,
    load_ruleset,
    write_verification_sidecar,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "prop"
BASE = FIXTURES / "synthetic_a_static_drawdown.yaml"


def _raw(path: Path = BASE) -> dict[str, object]:
    raw: dict[str, object] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw


def test_a_ruleset_loads_with_its_identity_and_a_canonical_hash() -> None:
    ruleset = load_ruleset(BASE)
    assert ruleset.ruleset_id == "synthetic-a-static-drawdown"
    assert ruleset.version == 1
    assert ruleset.firm == "SyntheticFirm A"
    assert ruleset.account_size_usd == Decimal(50000)
    assert ruleset.weight("ES") == Decimal(1)
    assert ruleset.weight("MES") == Decimal("0.1")
    assert ruleset.verified is False
    assert ruleset.effective_to is None
    # the hash is of the content: a rewritten file with the same values hashes the same
    again = PropRuleset.model_validate(_raw())
    assert ruleset.ruleset_sha256 == again.ruleset_sha256
    assert len(ruleset.ruleset_sha256) == 64


def test_an_unknown_root_has_no_contract_weight() -> None:
    with pytest.raises(ConfigurationError):
        load_ruleset(BASE).weight("NQ")


def test_two_versions_of_one_ruleset_load_from_a_registry() -> None:
    """Old versions are immutable: v1 and v2 of one id coexist with different hashes."""
    rulesets = load_registry(FIXTURES / "registry")
    assert [(r.ruleset_id, r.version) for r in rulesets] == [
        ("synthetic-registry", 1),
        ("synthetic-registry", 2),
    ]
    assert rulesets[0].ruleset_sha256 != rulesets[1].ruleset_sha256


def test_the_same_version_with_different_content_is_refused() -> None:
    """Two files claiming v1 with different hashes are a rewritten old version: refused."""
    with pytest.raises(DataQualityError):
        load_registry(FIXTURES / "registry_conflict")


def test_a_synthetic_ruleset_can_never_be_verified() -> None:
    with pytest.raises(ConfigurationError):
        load_ruleset(FIXTURES / "synthetic_synthetic_verified.yaml")


def test_a_verified_ruleset_needs_the_owner_confirmation_fields() -> None:
    with pytest.raises(ConfigurationError):
        load_ruleset(FIXTURES / "synthetic_verified_missing.yaml")


def test_a_verified_ruleset_comes_from_the_sidecar_not_the_file(tmp_path: Path) -> None:
    """ADR-0107 section 2: in-file verification is refused; a matching sidecar verifies it."""
    raw = _raw()
    raw["verification"] = {"status": "verified"}
    with pytest.raises(ValidationError, match="verification"):
        PropRuleset.model_validate(raw)

    path = tmp_path / "ruleset.yaml"
    path.write_text(yaml.safe_dump(_raw(), sort_keys=False), encoding="utf-8")
    ruleset = load_ruleset(path)
    assert ruleset.verified is False
    for phase in raw["phases"]:  # type: ignore[union-attr]
        for rule in (*phase["rules"], *phase["pass_conditions"], *phase["fees"]):
            rule["source"]["synthetic"] = False
    clean = PropRuleset.model_validate(raw | {"verification": {"status": "unverified"}})
    fresh = tmp_path / "clean.yaml"
    fresh.write_text(
        yaml.safe_dump(clean.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    write_verification_sidecar(
        fresh, clean, confirmed_by="owner", confirmation_note="synthetic confirmation"
    )
    verified = load_ruleset(fresh)
    assert verified.verified is True
    assert verified.verification.confirmed_by == "owner"


def test_a_bad_rule_kind_is_refused_by_the_discriminated_union() -> None:
    with pytest.raises(ConfigurationError):
        load_ruleset(FIXTURES / "synthetic_bad_kind.yaml")


def test_effective_to_before_effective_from_is_refused() -> None:
    raw = _raw()
    raw["effective_from"] = "2024-06-01"
    raw["effective_to"] = "2024-05-31"
    with pytest.raises(ValidationError, match="before effective_from"):
        PropRuleset.model_validate(raw)


def test_schema_version_one_is_refused_with_a_migration_message() -> None:
    raw = _raw()
    raw["schema_version"] = 1
    with pytest.raises(ValidationError, match=r"(?i)migrate"):
        PropRuleset.model_validate(raw)


def test_a_pass_condition_may_not_sit_in_the_rules_list() -> None:
    raw = _raw()
    raw["phases"][0]["rules"].append(  # type: ignore[index]
        {
            "kind": "profit_target",
            "rule_id": "target",
            "amount_usd": "100",
            "basis": "balance",
            "evaluated": "eod",
            "comparison": ">=",
            "action": "promote_phase",
            "evidence": "official_quote",
            "source": {
                "url": "https://example.invalid/synthetic-rules",
                "quote": "Synthetic rule value invented for a test",
                "snapshot_sha256": "0" * 64,
                "retrieved_at": "2024-01-01T00:00:00Z",
                "synthetic": True,
            },
        }
    )
    with pytest.raises(ValidationError, match="pass conditions"):
        PropRuleset.model_validate(raw)


def test_attribution_requires_a_utc_timestamp_and_a_snapshot_hash() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        Attribution(
            url="https://example.invalid/x",
            quote="q",
            snapshot_sha256="0" * 64,
            retrieved_at=dt.datetime(2024, 1, 1),  # noqa: DTZ001 (the refused naive case)
        )
    with pytest.raises(ValidationError):
        Attribution(
            url="https://example.invalid/x",
            quote="q",
            snapshot_sha256="not-a-hash",
            retrieved_at=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
        )


def test_the_phase_pass_kinds_are_the_three_contracts() -> None:
    assert frozenset({"profit_target", "min_trading_days", "consistency"}) == PASS_KINDS
    phase = load_ruleset(FIXTURES / "synthetic_f_pass_conditions.yaml").phases[0]
    assert [rule.kind for rule in phase.pass_conditions] == [
        "profit_target",
        "min_trading_days",
        "consistency",
    ]
    assert isinstance(phase, Phase)
    assert isinstance(Verification(), Verification)
    assert Instrument(root="ES", contract_weight=Decimal(1)).root == "ES"


# ------------------------------------------------------------------------------ test 16


def test_immaterial_unmodeled_rules_complete_with_a_warning() -> None:
    ruleset = load_ruleset(FIXTURES / "synthetic_g_immaterial.yaml")
    rows = rule_coverage(ruleset)
    assert [row.modeled for row in rows] == [True, False]
    assert evaluation_status(rows) == "complete"
    assert material_unmodeled(rows) == ()
    assert any("news_trading" in warning for warning in coverage_warnings(rows, ruleset))


def test_a_material_unmodeled_rule_conditions_the_claim() -> None:
    ruleset = load_ruleset(FIXTURES / "synthetic_g_material.yaml")
    rows = rule_coverage(ruleset)
    assert evaluation_status(rows) == "conditional_on_modeled_rules"
    assert material_unmodeled(rows) == ("news_trading",)


def test_a_critical_unmodeled_rule_blocks_the_verdict() -> None:
    ruleset = load_ruleset(FIXTURES / "synthetic_g_critical.yaml")
    rows = rule_coverage(ruleset)
    assert evaluation_status(rows) == "blocked"
    assert material_unmodeled(rows) == ("news_trading",)


# ------------------------------------------------------------------------------ test 17


def test_counterfactual_application_when_the_data_precedes_the_ruleset() -> None:
    """Rules read now, applied to pre-2025 data: every such run is a counterfactual."""
    ruleset = load_ruleset(BASE)
    assert counterfactual_application(dt.date(2024, 1, 8), ruleset) is False
    later = ruleset.model_copy(update={"effective_from": dt.date(2026, 1, 1)})
    assert counterfactual_application(dt.date(2024, 1, 8), later) is True


def test_an_unverified_ruleset_warns_that_its_result_is_not_confirmed() -> None:
    ruleset = load_ruleset(BASE)
    assert ruleset.verified is False
    warnings = coverage_warnings(rule_coverage(ruleset), ruleset)
    assert any("unverified" in warning for warning in warnings)


def test_money_keeps_exact_micro_dollars() -> None:
    assert rl.micro(Decimal("2500.000001")) == 2_500_000_001
    with pytest.raises(ConfigurationError):
        rl.micro(Decimal("0.0000001"))


# ------------------------------------------------------------------------------ test 19


def test_the_engine_is_firm_agnostic() -> None:
    """No firm name, firm URL or firm-specific value may appear under ``crucible/``.

    The rules are data (ADR-0106 decision 1): the engine knows rule kinds, never a firm. The
    fixtures invent "SyntheticFirm A" and example.invalid URLs, and a synthetic ruleset can never
    be verified.
    """
    names = (
        "ftmo",
        "lucid",
        "topstep",
        "apex",
        "mffu",
        "myfundedfutures",
        "fundednext",
        "take profit trader",
        "takeprofittrader",
    )
    package = Path(__file__).resolve().parent.parent.parent / "crucible"
    offenders: list[str] = []
    for path in package.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for name in names:
            if name in text:
                offenders.append(f"{path.relative_to(package.parent)}: {name}")
    assert not offenders, f"firm-specific names in the engine: {offenders}"


def test_every_rule_declares_its_semantics_without_a_default() -> None:
    """F1 (owner ruling): no metric, threshold, frequency, reset, comparison or action defaults.

    Every rule model must DECLARE ``comparison`` and ``action`` (the state transition), and none
    of the semantic fields may carry a default. The C7a implicit forms (``severity``,
    ``consequence``, ``on_excess``, ``on_breach``) are gone: the declaration is the rule.
    """
    from crucible.prop import rules_schema as schema

    models = [
        schema.ProfitTargetRule,
        schema.StaticDrawdownRule,
        schema.TrailingDrawdownRule,
        schema.DailyLossRule,
        schema.MaxContractsRule,
        schema.ScalingPlanRule,
        schema.FlatByRule,
        schema.MinTradingDaysRule,
        schema.ConsistencyRule,
        schema.PayoutRule,
        schema.TimeLimitRule,
        schema.FeeRule,
        schema.DailyProfitCapRule,
        schema.InactivityRule,
        schema.NewsRestrictionRule,
        schema.ComplianceRule,
    ]
    required_when_present = {
        "basis",
        "evaluated",
        "mode",
        "hwm_basis",
        "reset",
        "comparison",
        "action",
        "unit",
        "observed",
        "day_counts_if",
        "max_day_share",
        "measure",
        "applies_to",
        "window",
        "threshold_after_payout",
    }
    implicit = {"severity", "consequence", "on_excess", "on_breach"}
    for model in models:
        fields = model.model_fields
        assert {"comparison", "action"} <= set(fields), model.__name__
        assert not (implicit & set(fields)), f"{model.__name__} kept an implicit field"
        for name in required_when_present & set(fields):
            assert fields[name].is_required(), f"{model.__name__}.{name} has a default"
    assert schema.TrailingLock.model_fields["on"].is_required()


def test_an_expired_rule_cannot_sit_in_a_current_ruleset() -> None:
    raw = _raw()
    raw["as_of"] = "2024-06-01"
    raw["phases"][0]["rules"][0]["effective_to"] = "2024-05-31"  # type: ignore[index]
    with pytest.raises(ValidationError, match="effective_to"):
        PropRuleset.model_validate(raw)
