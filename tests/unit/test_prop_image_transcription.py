"""Evidence that lives only in an image: the type, its refusals and the self-check.

Some firm values are printed only inside a picture (the Topstep XFA scaling-plan ladder is one:
three images, no text table anywhere). Quoting the page would prove nothing about the numbers, so
the schema carries the transcription itself, the image's own sha256 and who transcribed it when,
and the self-check verifies the image FILE. Nothing compares a transcription with page text,
because there is none to compare it with.

Every path here is a temporary directory: no real snapshot folder is read.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from crucible.core.errors import DataQualityError
from crucible.prop.rules_schema import Attribution, ScalingPlanRule
from crucible.prop.ruleset import PropRuleset
from crucible.prop.sources import check_sources, verify_sources

RETRIEVED = dt.datetime(2026, 11, 23, tzinfo=dt.UTC)
PAGE_QUOTE = "The Scaling Plan is an Express Funded Account objective."
TRANSCRIPTION = "Below $1,500 2 Lots; $1,500 - $2,000 3 Lots; Above $2,000 5 Lots"


def image_source(**overrides: object) -> Attribution:
    fields: dict[str, object] = {
        "url": "https://example.invalid/scaling-plan",
        "quote": PAGE_QUOTE,
        "snapshot_sha256": "a" * 64,
        "retrieved_at": RETRIEVED,
        "synthetic": True,
        "image_snapshot_sha256": "b" * 64,
        "image_path": "topstep/20261123_hc_scaling-plan-xfa-charts.png",
        "transcription": TRANSCRIPTION,
        "transcribed_by": "the coordinator",
        "transcribed_at": RETRIEVED,
    }
    fields.update(overrides)
    return Attribution.model_validate(fields)


def ladder_rule(source: Attribution | None = None, evidence: str = "official_image_transcription"):
    return {
        "kind": "scaling_plan",
        "rule_id": "xfa_max_contracts",
        "description": "the XFA ladder, transcribed from the image",
        "steps": [
            {"max_contracts": "2"},
            {"min_balance_usd": "1500", "max_contracts": "3"},
            {"min_balance_usd": "2000", "max_contracts": "5"},
        ],
        "evaluated": "eod",
        "basis": "balance",
        "comparison": ">",
        "action": "clip",
        "source": (source or image_source()).model_dump(mode="json"),
        "evidence": evidence,
    }


def ruleset_document(root: Path, rule: dict[str, object]) -> dict[str, object]:
    page = root / "topstep" / "page.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"<p>{PAGE_QUOTE}</p>", encoding="utf-8")
    image = root / "topstep" / "20261123_hc_scaling-plan-xfa-charts.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n not really a png, but its bytes are the evidence")
    source = {
        "url": "https://example.invalid/scaling-plan",
        "quote": PAGE_QUOTE,
        "snapshot_sha256": hashlib.sha256(page.read_bytes()).hexdigest(),
        "retrieved_at": RETRIEVED.isoformat(),
        "image_snapshot_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "image_path": "topstep/20261123_hc_scaling-plan-xfa-charts.png",
        "transcription": TRANSCRIPTION,
        "transcribed_by": "the coordinator",
        "transcribed_at": RETRIEVED.isoformat(),
    }
    rule["source"] = source
    commissions_source = {
        key: value
        for key, value in source.items()
        if key
        not in {
            "image_snapshot_sha256",
            "image_path",
            "transcription",
            "transcribed_by",
            "transcribed_at",
        }
    }
    return {
        "schema_version": 2,
        "ruleset_id": "synthetic-image-evidence",
        "version": 1,
        "firm": "SyntheticFirm A",
        "program": "Synthetic XFA",
        "account_size_usd": "50000",
        "as_of": "2026-11-22",
        "effective_from": "2026-11-22",
        "instruments": [{"root": "ES", "contract_weight": "1"}],
        "reset": {"time": "17:00:00", "tz": "America/Chicago"},
        "commissions": {
            "status": "known",
            "components": {
                name: {"status": "included", "evidence": "official_quote", "text": "synthetic"}
                for name in ("exchange", "clearing", "nfa", "other")
            },
            "per_side_usd": {"ES": "2.00"},
            "source": commissions_source,
        },
        "conflicts": [],
        "phases": [
            {
                "phase_id": "funded",
                "kind": "funded",
                "starting_balance_usd": "0",
                "rules": [rule],
                "pass_conditions": [],
                "max_calendar_days": None,
                "max_trading_days": None,
                "fees": [],
            }
        ],
        "not_modeled": [],
    }


def test_a_transcribed_image_value_is_a_rule_the_schema_accepts() -> None:
    rule = ScalingPlanRule.model_validate(ladder_rule())
    assert rule.evidence == "official_image_transcription"
    assert rule.source.image_path == "topstep/20261123_hc_scaling-plan-xfa-charts.png"
    assert rule.source.transcription.startswith("Below $1,500 2 Lots")
    assert rule.source.transcribed_by == "the coordinator"


def test_an_image_transcription_needs_the_whole_image_block() -> None:
    """All five fields or none: a sha256 without the transcription proves no values."""
    for missing in (
        "image_snapshot_sha256",
        "image_path",
        "transcription",
        "transcribed_by",
        "transcribed_at",
    ):
        raw = image_source().model_dump(mode="json")
        raw[missing] = None
        with pytest.raises(ValidationError, match="all-or-nothing"):
            Attribution.model_validate(raw)


def test_an_image_path_must_stay_under_the_private_snapshots_root() -> None:
    for path in ("C:/secret/x.png", "/abs/x.png", "../outside/x.png", "topstep\\x.png"):
        with pytest.raises(ValidationError, match="relative to the private snapshots root"):
            image_source(image_path=path)


def test_a_naive_transcription_time_is_refused() -> None:
    with pytest.raises(ValidationError, match="transcribed_at must carry a UTC offset"):
        image_source(transcribed_at=dt.datetime(2026, 11, 23, tzinfo=None))  # noqa: DTZ001


def test_the_evidence_type_and_the_source_must_agree() -> None:
    """An image-only value that does not say so, and a transcription with no image, both refuse."""
    with pytest.raises(ValidationError, match="must say so"):
        ScalingPlanRule.model_validate(ladder_rule(evidence="official_quote"))
    with pytest.raises(ValidationError, match="source must"):
        ScalingPlanRule.model_validate(
            ladder_rule(
                source=Attribution(
                    url="https://example.invalid/x",
                    quote=PAGE_QUOTE,
                    snapshot_sha256="a" * 64,
                    retrieved_at=RETRIEVED,
                )
            )
        )


def test_the_self_check_verifies_the_image_bytes_and_never_the_transcription(
    tmp_path: Path,
) -> None:
    """The page quote must be in the saved page, the image file must hash to its declared sha256,
    and the transcription is NOT searched in any page text (it exists only in the picture)."""
    document = ruleset_document(tmp_path, ladder_rule())
    # a transcription whose words appear nowhere on the page is still valid evidence
    document["phases"][0]["rules"][0]["source"]["transcription"] = "zzz not on any page zzz"
    ruleset = PropRuleset.model_validate(document)
    result = verify_sources(ruleset, tmp_path)
    assert result.ok
    assert (result.attributions, result.images) == (2, 1)  # the rule and the commissions block


def test_the_self_check_REFUSES_a_wrong_image_sha(tmp_path: Path) -> None:
    """A file whose bytes do not hash to image_snapshot_sha256 is refused, never warned."""
    document = ruleset_document(tmp_path, ladder_rule())
    document["phases"][0]["rules"][0]["source"]["image_snapshot_sha256"] = "c" * 64
    ruleset = PropRuleset.model_validate(document)
    with pytest.raises(DataQualityError, match="hashes to"):
        verify_sources(ruleset, tmp_path)
    assert not check_sources(ruleset, tmp_path).ok


def test_the_self_check_refuses_a_missing_image_file(tmp_path: Path) -> None:
    document = ruleset_document(tmp_path, ladder_rule())
    document["phases"][0]["rules"][0]["source"]["image_path"] = "topstep/gone.png"
    ruleset = PropRuleset.model_validate(document)
    with pytest.raises(DataQualityError, match="is not a file"):
        verify_sources(ruleset, tmp_path)


def test_the_self_check_refuses_a_quote_that_is_not_in_its_own_snapshot(tmp_path: Path) -> None:
    """The quote is searched in the page its own hash names, never in another file."""
    document = ruleset_document(tmp_path, ladder_rule())
    document["phases"][0]["rules"][0]["source"]["quote"] = "a sentence no saved page contains"
    ruleset = PropRuleset.model_validate(document)
    with pytest.raises(DataQualityError, match="quote not found"):
        verify_sources(ruleset, tmp_path)


def test_the_self_check_refuses_a_hash_that_names_no_file(tmp_path: Path) -> None:
    document = ruleset_document(tmp_path, ladder_rule())
    document["phases"][0]["rules"][0]["source"]["snapshot_sha256"] = "d" * 64
    ruleset = PropRuleset.model_validate(document)
    with pytest.raises(DataQualityError, match="names no file"):
        verify_sources(ruleset, tmp_path)


def test_supporting_sources_are_cited_and_checked(tmp_path: Path) -> None:
    """The page quotes behind a rule's basis and timing are attributions too, not description."""
    rule = ladder_rule()
    document = ruleset_document(tmp_path, rule)
    page = (tmp_path / "topstep" / "page.html").read_text(encoding="utf-8")
    page_hash = hashlib.sha256(page.encode("utf-8")).hexdigest()
    rule["supporting_sources"] = [
        {
            "url": "https://example.invalid/scaling-plan",
            "quote": PAGE_QUOTE,
            "snapshot_sha256": page_hash,
            "retrieved_at": RETRIEVED.isoformat(),
            "section": "When the tier changes",
        }
    ]
    rule["assumptions"] = [
        {
            "name": "boundary_ties_go_to_the_lower_tier",
            "rationale": "the conservative reading (owner delegation 2026-11-23)",
            "assumption_kind": "owner_decision",
        }
    ]
    ruleset = PropRuleset.model_validate(document)
    typed = ruleset.phases[0].rules[0]
    assert typed.all_assumptions()[0].name == "boundary_ties_go_to_the_lower_tier"
    assert len(typed.all_sources()) == 2
    result = verify_sources(ruleset, tmp_path)
    assert result.attributions == 3  # commissions, the value's source, the supporting one
    # a supporting attribution is held to the same standard as the value's own
    rule["supporting_sources"][0]["quote"] = "nowhere"
    broken = PropRuleset.model_validate(document)
    assert not check_sources(broken, tmp_path).ok


def test_a_root_that_is_not_a_directory_is_refused_by_name(tmp_path: Path) -> None:
    """The root is an argument: the self-check never guesses where the snapshots live."""
    ruleset = PropRuleset.model_validate(ruleset_document(tmp_path, ladder_rule()))
    with pytest.raises(DataQualityError, match="is not a directory"):
        verify_sources(ruleset, tmp_path / "nope")
    assert ScalingPlanRule.model_validate(ladder_rule()).steps[0].min_balance_usd is None
    assert ScalingPlanRule.model_validate(ladder_rule()).steps[1].min_balance_usd == Decimal("1500")
