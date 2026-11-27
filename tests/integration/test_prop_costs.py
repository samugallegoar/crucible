"""Per-component execution costs: the arithmetic, the gaps and the refusals (ADR-0107 s10).

Every number here is SYNTHETIC (``0.77`` and the words ``SYNTHETIC TEST VALUE``), and every
expectation is written out as arithmetic: the commission plus the components the firm says are on
top of it, plus whatever a cost-assumption FILE prices. Nothing is derived from the engine's own
output, and no real exchange fee appears anywhere (see the last test).

The rules of the game, each pinned by a test below:

- a component the sources do not state is a gap, never a zero, and the cost is ``unavailable``;
- a cost-assumption file prices exactly the root and components it names — never another root —
  and only that makes the number ``conditional``, never ``complete``;
- the participant PROFILE that prices an ``excluded`` component is a run input, resolved per
  component, and using it is a reason the estimate is not complete;
- a row covers only its exact root, its own classification and its dates, and a row covering
  several components is charged once.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from crucible.core.errors import ConfigurationError
from crucible.data.exchange_fees import (
    EXCHANGE_CLASSIFICATION_DIMENSION,
    EXCHANGE_CLASSIFICATION_VALUE,
    NFA_CLASSIFICATION_DIMENSION,
    NFA_CLASSIFICATION_VALUE,
    ParticipantProfile,
)
from crucible.execution.futures_sim import CostSchedule
from crucible.prop.attempt import cash_estimate, estimate_status
from crucible.prop.costs import (
    PARTICIPANT_PROFILE_REASON,
    UPPER_BOUND_CASH_LABEL,
    UPPER_BOUND_REASON,
    ComponentCharge,
    ComponentFeeRow,
    ComponentFeeTable,
    load_cost_assumption,
    price_components,
)
from crucible.prop.rules_schema import Commissions

if TYPE_CHECKING:
    pass

WHEN = dt.date(2024, 1, 8)
"""The attempt date every pricing test resolves at."""
PROFILE = ParticipantProfile.from_mapping(
    {"cme_membership_status": "non_member", "nfa_assessment_eligibility": "fcm_member"}
)
"""The run's participant profile: it resolves the synthetic exchange row and the NFA row."""

COMPONENT_NAMES = ("exchange", "clearing", "nfa", "other")


def declarations(**statuses: str) -> dict[str, dict[str, str]]:
    """The four component declarations; every one not named defaults to ``unknown``."""
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


def commissions(
    *,
    status: str = "known",
    per_side: dict[str, str] | None = None,
    **statuses: str,
) -> Commissions:
    """A commission table with the four component declarations."""
    document: dict[str, object] = {
        "status": status,
        "components": declarations(**statuses),
        "per_side_usd": {} if per_side is None else per_side,
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


def fee_table(*rows: ComponentFeeRow, sha: str = "1") -> ComponentFeeTable:
    """A fee table written down in code, the shape the stored dataset hands back."""
    return ComponentFeeTable(rows=rows, source_sha256=sha * 64)


def nfa_row(amount: str = "0.02", root: str = "ES") -> ComponentFeeRow:
    """The NFA assessment row: the assessment the bylaw makes on the FCM member."""
    return ComponentFeeRow(
        root=root,
        fee_type="nfa",
        classification_dimension=NFA_CLASSIFICATION_DIMENSION,
        classification_value=NFA_CLASSIFICATION_VALUE,
        covers=("nfa",),
        per_side_usd=Decimal(amount),
        effective_from=dt.date(2023, 1, 1),
    )


def exchange_row(
    amount: str = "0.77",
    *,
    root: str = "ES",
    covers: tuple[str, ...] = ("exchange",),
    effective_from: dt.date = dt.date(2023, 1, 1),
    effective_to: dt.date | None = None,
) -> ComponentFeeRow:
    """An exchange row; with ``covers=("exchange", "clearing")`` it prices both, charged once."""
    return ComponentFeeRow(
        root=root,
        fee_type="exchange",
        classification_dimension=EXCHANGE_CLASSIFICATION_DIMENSION,
        classification_value=EXCHANGE_CLASSIFICATION_VALUE,
        covers=covers,
        per_side_usd=Decimal(amount),
        effective_from=effective_from,
        effective_to=effective_to,
    )


OTHER_CHARGE = "SYNTHETIC TEST VALUE: per-side connectivity charge"
"""The specific name an assumption covering ``other`` must give (a generic word is refused)."""


def write_assumption(
    path: Path,
    amounts: dict[str, list[dict[str, object]]],
    *,
    name: str = "synthetic-owner-estimate",
    kind: str = "point_estimate",
) -> Path:
    """A SYNTHETIC cost-assumption file."""
    document = {
        "name": name,
        "kind": kind,
        "description": "SYNTHETIC TEST VALUE: an estimate invented for a test",
        "provided_by": "owner",
        "status": "unverified",
        "evidence": "SYNTHETIC TEST VALUE: no document states this split",
        # every amount states its unit: the file prices a per-side execution cost
        "amounts": {
            root: [{"unit": "per_contract_per_side", **entry} for entry in entries]
            for root, entries in amounts.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8", newline="\n")
    return path


def cost_schedule() -> CostSchedule:
    """The run's own schedule: every field is a sentinel the pricing must overwrite or ignore."""
    return CostSchedule(
        commission=Decimal("9.99"),
        exchange_fee=Decimal("9.99"),
        clearing_fee=Decimal("9.99"),
        regulatory_fee=Decimal("9.99"),
        other_fee=Decimal("9.99"),
    )


def price(
    table: Commissions,
    *,
    root: str = "ES",
    fee_source: ComponentFeeTable | None = None,
    profile: ParticipantProfile | None = PROFILE,
    assumption: object = None,
    when: dt.date = WHEN,
):
    """``price_components`` for one root, with the table's own commission."""
    return price_components(
        components=table.components,
        commission_status=table.status,
        commission_per_side=table.per_side(root) if table.status == "known" else None,
        root=root,
        when=when,
        costs=cost_schedule(),
        fee_source=fee_source,
        profile=profile if table.excluded_components else None,
        assumption=assumption,  # type: ignore[arg-type]
    )


# ------------------------------------------------------- 1. an all-unknown firm (Apex-like)


def test_an_all_unknown_firm_leaves_the_cash_unavailable_and_lists_every_component() -> None:
    """Apex's mapping: the commission is known, and no component's status is stated.

    The commission is 1.99 per side and the four components are ``unknown``, so the cash statistic
    is ``unavailable`` with four named gaps — never 1.99 presented as the whole cost.
    """
    table = commissions(per_side={"ES": "1.99"})
    assert (table.excluded_components, table.unknown_components) == (
        (),
        ("exchange", "clearing", "nfa", "other"),
    )
    pricing = price(table)
    assert pricing.charges[0] == ComponentCharge(
        component="commission",
        status="known",
        usd=Decimal("1.99"),
        detail="the firm's per-side commission",
    )
    assert pricing.gaps == ("exchange", "clearing", "nfa", "other")
    assert pricing.status == "unavailable"
    assert [item.status for item in pricing.charges[1:]] == ["unknown"] * 4
    # nothing is added to the commission: a gap is never charged as zero, it is not charged at all
    assert pricing.schedule.exchange_fee == Decimal("0")
    assert pricing.fees_per_side == Decimal("1.99")
    status, reasons = cash_estimate(
        payouts_modeled=True,
        payout_cap_unknown=False,
        cost_status=pricing.status,
        cost_assumption=None,
        fees_incomplete=pricing.gap_text,
    )
    assert status == "unavailable"
    assert any("exchange" in reason for reason in reasons)


def test_an_assumption_covering_one_component_leaves_the_other_gaps_named(tmp_path: Path) -> None:
    """0.40 for the exchange only: the cost is STILL unavailable, with three gaps left.

    An assumption prices what it lists and nothing else. The value it supplies is charged (so a
    reader can see what was assumed), but the estimate cannot become a number while clearing, NFA
    and other stay unknown.
    """
    condition = load_cost_assumption(
        write_assumption(
            tmp_path / "exchange-only.yaml",
            {"ES": [{"covers": ["exchange"], "per_side_usd": "0.40"}]},
        )
    )
    pricing = price(commissions(per_side={"ES": "1.99"}), assumption=condition)
    assert pricing.gaps == ("clearing", "nfa", "other")
    assert pricing.priced_by_assumption == ("exchange",)
    assert pricing.status == "unavailable"
    assert pricing.schedule.exchange_fee == Decimal("0.40")
    assert any("synthetic-owner-estimate" in reason for reason in pricing.reasons)


def test_an_assumption_covering_every_component_makes_the_cost_conditional(
    tmp_path: Path,
) -> None:
    """1.99 commission + 0.40 exchange + 0.11 clearing + 0.02 NFA + 0.00 other = 2.52 per side.

    Every gap is priced by the file, so the cost is a number — under that assumption, which is why
    it is ``conditional`` and carries the file's SHA-256, never ``complete``.
    """
    assumption = load_cost_assumption(
        write_assumption(
            tmp_path / "all-in.yaml",
            {
                "ES": [
                    {"covers": ["exchange"], "per_side_usd": "0.40"},
                    {"covers": ["clearing"], "per_side_usd": "0.11"},
                    {"covers": ["nfa"], "per_side_usd": "0.02"},
                    {"covers": ["other"], "per_side_usd": "0.00", "charge_name": OTHER_CHARGE},
                ]
            },
        )
    )
    pricing = price(commissions(per_side={"ES": "1.99"}), assumption=assumption)
    assert pricing.gaps == ()
    assert pricing.status == "conditional"
    assert pricing.priced_by_assumption == ("exchange", "clearing", "nfa", "other")
    assert pricing.schedule.fees_per_side == (
        Decimal("1.99") + Decimal("0.40") + Decimal("0.11") + Decimal("0.02") + Decimal("0.00")
    )
    assert pricing.fees_per_side == Decimal("2.52")
    status, reasons = cash_estimate(
        payouts_modeled=True,
        payout_cap_unknown=False,
        cost_status=pricing.status,
        cost_assumption="synthetic-owner-estimate",
        fees_incomplete=pricing.gap_text,
    )
    assert status == "conditional"
    assert any("synthetic-owner-estimate" in reason for reason in reasons)


def test_a_bound_that_leaves_the_commission_a_gap_is_never_a_lower_bound(tmp_path: Path) -> None:
    """A ceiling on four components does NOT make the cash a ``lower_bound`` (F6).

    The firm states a commission for NQ and nothing for ES, and the bound prices the four
    components around it: ``commission`` stays a gap. Hand-computed, the cash is therefore
    ``unavailable`` -- not ``lower_bound`` (which would claim the missing commission is free) and
    not ``conditional`` -- and its reason names the one component still missing.
    """
    bound = load_cost_assumption(
        write_assumption(
            tmp_path / "bound.yaml",
            {
                "ES": [
                    {"covers": ["exchange"], "per_side_usd": "2.00"},
                    {"covers": ["clearing"], "per_side_usd": "0.50"},
                    {"covers": ["nfa"], "per_side_usd": "0.02"},
                    {"covers": ["other"], "per_side_usd": "0.50", "charge_name": OTHER_CHARGE},
                ]
            },
            name="upper-bound-v1",
            kind="upper_bound",
        )
    )
    pricing = price(commissions(per_side={"NQ": "2.88"}), assumption=bound)
    assert pricing.gaps == ("commission",)
    assert pricing.priced_by_assumption == ("exchange", "clearing", "nfa", "other")
    assert pricing.status == "unavailable"
    status, reasons = cash_estimate(
        payouts_modeled=True,
        payout_cap_unknown=False,
        cost_status=pricing.status,
        cost_assumption="upper-bound-v1",
        cost_gaps=pricing.gaps,
        cost_assumption_kind=pricing.assumption_kind,
    )
    assert status == "unavailable"
    assert any("does not price commission" in reason for reason in reasons)
    assert not any("covered every cost gap" in reason for reason in reasons)


def test_a_bound_that_fills_every_gap_is_still_a_lower_bound(tmp_path: Path) -> None:
    """The same file, with the commission priced: nothing is missing, so the label stands.

    ``commission`` 1.50 + exchange 2.00 + clearing 0.50 + NFA 0.02 + other 0.50 = 4.52 per side,
    every gap filled, so the cost is ``conditional`` (an assumption supplied amounts) and the cash
    is the floor of that ceiling: ``lower_bound`` with the upper-bound reason beside it.
    """
    bound = load_cost_assumption(
        write_assumption(
            tmp_path / "bound-all.yaml",
            {
                "ES": [
                    {"covers": ["commission"], "per_side_usd": "1.50"},
                    {"covers": ["exchange"], "per_side_usd": "2.00"},
                    {"covers": ["clearing"], "per_side_usd": "0.50"},
                    {"covers": ["nfa"], "per_side_usd": "0.02"},
                    {"covers": ["other"], "per_side_usd": "0.50", "charge_name": OTHER_CHARGE},
                ]
            },
            name="upper-bound-v1",
            kind="upper_bound",
        )
    )
    pricing = price(commissions(per_side={"NQ": "2.88"}), assumption=bound)
    assert pricing.gaps == ()
    assert pricing.status == "conditional"
    assert pricing.fees_per_side == Decimal("4.52")
    status, reasons = cash_estimate(
        payouts_modeled=True,
        payout_cap_unknown=False,
        cost_status=pricing.status,
        cost_assumption="upper-bound-v1",
        cost_gaps=pricing.gaps,
        cost_assumption_kind=pricing.assumption_kind,
    )
    assert status == UPPER_BOUND_CASH_LABEL
    assert UPPER_BOUND_REASON in reasons


# ------------------------------------------- 2. a firm that charges the fees on top (FTMO-like)


def ftmo_like() -> Commissions:
    """A firm that says exchange, clearing and NFA are on top of its 0.50 commission."""
    return commissions(
        per_side={"ES": "0.50"},
        exchange="excluded",
        clearing="excluded",
        nfa="excluded",
    )


def test_an_excluded_component_needs_the_run_participant_profile() -> None:
    """The ruleset never states who the account is, so the run must: refused when it is missing."""
    with pytest.raises(ConfigurationError, match="participant profile"):
        price_components(
            components=ftmo_like().components,
            commission_status="known",
            commission_per_side=Decimal("0.50"),
            root="ES",
            when=WHEN,
            costs=cost_schedule(),
            fee_source=fee_table(nfa_row()),
            profile=None,
        )


def test_an_nfa_only_dataset_leaves_the_exchange_component_a_gap() -> None:
    """The NFA assessment prices 0.02; the exchange and the clearing fee have no row at all."""
    pricing = price(ftmo_like(), fee_source=fee_table(nfa_row()))
    assert pricing.charges[0].usd == Decimal("0.50")
    assert [item.status for item in pricing.charges[1:]] == [
        "excluded_unpriced",
        "excluded_unpriced",
        "excluded_priced",
        "unknown",
    ]
    assert pricing.gaps == ("exchange", "clearing", "other")
    assert pricing.status == "unavailable"
    assert pricing.schedule.regulatory_fee == Decimal("0.02")


def test_a_row_covering_exchange_and_clearing_is_charged_once_and_other_stays_unknown() -> None:
    """One CME cell (``covers=exchange;clearing``, 0.77) + the NFA 0.02 leaves ``other`` unknown.

    Per side: 0.50 + 0.77 (ONE row, which covers two components and is charged once) + 0.02 = 1.29.
    The cost is still ``unavailable`` because ``other`` is a component the sources do not state.
    """
    table = fee_table(exchange_row(covers=("exchange", "clearing")), nfa_row())
    pricing = price(ftmo_like(), fee_source=table)
    assert pricing.gaps == ("other",)
    assert pricing.status == "unavailable"
    assert pricing.schedule.exchange_fee == Decimal("0.77")
    # the same cell covers the clearing fee: charged once, so the clearing component adds nothing
    assert pricing.component_charge("clearing").status == "covered_by_row"
    assert pricing.component_charge("clearing").usd == Decimal("0")
    assert pricing.schedule.clearing_fee == Decimal("0")
    assert pricing.schedule.regulatory_fee == Decimal("0.02")
    assert pricing.fees_per_side == Decimal("0.50") + Decimal("0.77") + Decimal("0.02")


def test_an_assumption_for_the_last_gap_makes_it_conditional_with_the_profile(
    tmp_path: Path,
) -> None:
    """Pricing ``other`` at 0.00 closes the last gap: 0.50 + 0.77 + 0.02 + 0.00 = 1.29 per side.

    The estimate is ``conditional`` for TWO reasons that must both be visible: the assumption file,
    and the participant profile the excluded components were resolved through. It is never
    reported as complete.
    """
    assumption = load_cost_assumption(
        write_assumption(
            tmp_path / "other.yaml",
            {"ES": [{"covers": ["other"], "per_side_usd": "0", "charge_name": OTHER_CHARGE}]},
        )
    )
    table = fee_table(exchange_row(covers=("exchange", "clearing")), nfa_row())
    pricing = price(ftmo_like(), fee_source=table, assumption=assumption)
    assert pricing.gaps == ()
    assert pricing.status == "conditional"
    assert pricing.fees_per_side == Decimal("1.29")
    assert PARTICIPANT_PROFILE_REASON in pricing.reasons
    status, reasons = cash_estimate(
        payouts_modeled=True,
        payout_cap_unknown=False,
        cost_status=pricing.status,
        cost_assumption="synthetic-owner-estimate",
        participant_profile=PROFILE.sha256,
    )
    assert status == "conditional"
    assert any(PARTICIPANT_PROFILE_REASON in reason for reason in reasons)


def test_a_firm_that_leaves_clearing_unknown_never_gets_a_complete_cost() -> None:
    """FTMO's own mapping leaves ``clearing`` and ``other`` unknown, so even a full dataset gaps.

    A row that covers exchange and clearing prices nothing for a component the ruleset does not
    say is on top: the declaration, not the dataset's coverage, decides what is charged.
    """
    table = commissions(
        per_side={"ES": "0.50"},
        exchange="excluded",
        nfa="excluded",
    )
    pricing = price(
        table, fee_source=fee_table(exchange_row(covers=("exchange", "clearing")), nfa_row())
    )
    assert pricing.gaps == ("clearing", "other")
    assert pricing.schedule.clearing_fee == Decimal("0")
    assert pricing.status == "unavailable"


# --------------------------------------------------------------- 3. the historical, per-root table


def test_a_date_picks_its_own_historical_row() -> None:
    """Two ES rows: 0.51 through 2023, 0.63 from 2024. A 2023 attempt charges 0.51.

    The rows are historical data, not a single current rate: the 2023 attempt pays 0.50 + 0.77...
    no: 0.50 + 0.51 + 0.02 = 1.03 per side, and the 2024 one 0.50 + 0.63 + 0.02 = 1.15.
    """
    table = fee_table(
        exchange_row(
            "0.51", effective_from=dt.date(2023, 1, 1), effective_to=dt.date(2023, 12, 31)
        ),
        exchange_row("0.63", effective_from=dt.date(2024, 1, 1)),
        nfa_row(),
    )
    table = ComponentFeeTable(rows=table.rows, source_sha256="1" * 64)
    in_2023 = price(ftmo_like(), fee_source=table, when=dt.date(2023, 7, 3))
    in_2024 = price(ftmo_like(), fee_source=table, when=dt.date(2024, 7, 1))
    assert in_2023.schedule.exchange_fee == Decimal("0.51")
    assert in_2023.fees_per_side == Decimal("0.50") + Decimal("0.51") + Decimal("0.02")
    assert in_2024.schedule.exchange_fee == Decimal("0.63")
    assert in_2024.fees_per_side == Decimal("0.50") + Decimal("0.63") + Decimal("0.02")


def test_a_row_prices_only_its_own_root() -> None:
    """An ES-only table prices ES and says nothing about NQ (never an extrapolated fee).

    The table refuses an overlapping or unsourced row set, and a request for a root it does not
    carry comes back with no amount at all, which the caller reports as a gap.
    """
    table = fee_table(exchange_row("0.77"))
    found = table.lookup("ES", WHEN, profile=PROFILE, components=("exchange",))
    assert found.priced["exchange"][0] == Decimal("0.77")
    missing = table.lookup("NQ", WHEN, profile=PROFILE, components=("exchange",))
    assert missing.priced == {}
    assert "no fee row covers" in missing.gaps["exchange"]
    with pytest.raises(ConfigurationError, match="overlap"):
        fee_table(exchange_row("0.51", effective_to=dt.date(2024, 6, 30)), exchange_row("0.63"))


def test_a_member_row_does_not_price_a_non_member_profile() -> None:
    """No extrapolation across classification values; the NFA row needs its own dimension."""
    member = ComponentFeeRow(
        root="ES",
        fee_type="exchange",
        classification_dimension=EXCHANGE_CLASSIFICATION_DIMENSION,
        classification_value="member",
        covers=("exchange",),
        per_side_usd=Decimal("0.31"),
        effective_from=dt.date(2023, 1, 1),
    )
    table = fee_table(member, nfa_row())
    # a profile that declares no cme_membership_status leaves the exchange a gap AND the nfa one
    exclusive = table.lookup(
        "ES",
        WHEN,
        profile=ParticipantProfile.from_mapping({"trading_class": "proprietary"}),
        components=("exchange", "nfa"),
    )
    assert exclusive.priced == {}
    assert exclusive.gaps["exchange"] == ("classification cme_membership_status not declared")
    assert exclusive.gaps["nfa"] == ("classification nfa_assessment_eligibility not declared")
    exact = table.lookup(
        "ES",
        WHEN,
        profile=ParticipantProfile.from_mapping(
            {"cme_membership_status": "member", "nfa_assessment_eligibility": "fcm_member"}
        ),
        components=("exchange",),
    )
    assert exact.priced["exchange"][0] == Decimal("0.31")


# ------------------------------------------------------------------------- 4. the refusals


def test_the_old_all_in_flag_is_refused_by_name() -> None:
    """``includes_exchange_and_regulatory_fees`` is gone: the error names the new block."""
    with pytest.raises(ValueError, match=r"commissions\.components"):
        Commissions.model_validate(
            {
                "status": "known",
                "includes_exchange_and_regulatory_fees": True,
                "per_side_usd": {"ES": "1.99"},
                "source": {
                    "url": "https://example.invalid/synthetic",
                    "quote": "SYNTHETIC TEST VALUE",
                    "snapshot_sha256": "0" * 64,
                    "retrieved_at": "2024-01-01T00:00:00Z",
                },
            }
        )


def test_a_missing_component_key_is_refused_with_no_default() -> None:
    """Three keys are not four: every component must be declared, there is no default."""
    document = declarations()
    document.pop("other")
    with pytest.raises(ValueError, match="other"):
        Commissions.model_validate(
            {
                "status": "known",
                "components": document,
                "per_side_usd": {"ES": "1.99"},
                "source": {
                    "url": "https://example.invalid/synthetic",
                    "quote": "SYNTHETIC TEST VALUE",
                    "snapshot_sha256": "0" * 64,
                    "retrieved_at": "2024-01-01T00:00:00Z",
                },
            }
        )


def test_an_included_component_without_a_quotation_is_refused() -> None:
    """``included`` is a claim about the firm: it needs a quotation that says so."""
    with pytest.raises(ValueError, match="official_quote or owner_provided"):
        Commissions.model_validate(
            {
                "status": "known",
                "components": {
                    **declarations(),
                    "exchange": {
                        "status": "included",
                        "evidence": "not_stated",
                        "text": "synthetic",
                    },
                },
                "per_side_usd": {"ES": "1.99"},
                "source": {
                    "url": "https://example.invalid/synthetic",
                    "quote": "SYNTHETIC TEST VALUE",
                    "snapshot_sha256": "0" * 64,
                    "retrieved_at": "2024-01-01T00:00:00Z",
                },
            }
        )


def test_an_assumption_may_not_override_an_included_component(tmp_path: Path) -> None:
    """The firm says the exchange fee is inside the commission: no file may add one."""
    assumption = load_cost_assumption(
        write_assumption(
            tmp_path / "override.yaml", {"ES": [{"covers": ["exchange"], "per_side_usd": "0.40"}]}
        )
    )
    table = commissions(per_side={"ES": "1.99"}, exchange="included")
    with pytest.raises(ConfigurationError, match="may not override"):
        price(table, assumption=assumption)


def test_an_assumption_that_prices_another_root_is_allowed_and_reported(tmp_path: Path) -> None:
    """A file may price roots the run does not trade: unused, and reported as unused."""
    assumption = load_cost_assumption(
        write_assumption(
            tmp_path / "two-roots.yaml",
            {
                "ES": [{"covers": ["exchange"], "per_side_usd": "0.40"}],
                "NQ": [{"covers": ["exchange"], "per_side_usd": "0.44"}],
            },
        )
    )
    assert assumption.roots == ("ES", "NQ")
    assert assumption.unused_roots(("ES",)) == ("NQ",)
    assert assumption.unused_roots(("ES", "NQ")) == ()
    pricing = price(commissions(per_side={"ES": "1.99"}), assumption=assumption)
    # the NQ amount never leaks into an ES attempt
    assert pricing.schedule.exchange_fee == Decimal("0.40")


def test_an_assumption_file_must_be_unverified_and_complete(tmp_path: Path) -> None:
    """A file that claims verification, or leaves out a key, is refused."""
    path = write_assumption(
        tmp_path / "bad.yaml", {"ES": [{"covers": ["exchange"], "per_side_usd": "0.4"}]}
    )
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["status"] = "verified"
    path.write_text(yaml.safe_dump(document), encoding="utf-8", newline="\n")
    with pytest.raises(ConfigurationError, match="status must be 'unverified'"):
        load_cost_assumption(path)

    path2 = tmp_path / "missing.yaml"
    path2.write_text(
        yaml.safe_dump({"name": "x", "amounts": {"ES": []}}), encoding="utf-8", newline="\n"
    )
    with pytest.raises(ConfigurationError, match="missing key"):
        load_cost_assumption(path2)


def test_overlapping_rows_and_a_covers_cell_without_its_own_fee_type_are_refused() -> None:
    """Two rows for one component on one date, or a covers cell that omits the row's own type."""
    with pytest.raises(ConfigurationError, match="does not contain its own fee_type"):
        ComponentFeeRow(
            root="ES",
            fee_type="exchange",
            classification_dimension=EXCHANGE_CLASSIFICATION_DIMENSION,
            classification_value=EXCHANGE_CLASSIFICATION_VALUE,
            covers=("clearing",),
            per_side_usd=Decimal("0.77"),
            effective_from=dt.date(2023, 1, 1),
        )
    with pytest.raises(ConfigurationError, match="overlap"):
        fee_table(exchange_row(), exchange_row("0.88"))


# ------------------------------------------------------ 5. a firm that includes everything


def test_an_all_in_firm_has_complete_costs_but_unverified_labels() -> None:
    """FundedNext-like: all four components included, so nothing is added and nothing is a gap.

    Per side: 2.88, which is the commission and every fee inside it. The COST is ``complete``; the
    ESTIMATE is still ``conditional`` because the ruleset is unverified — the two labels answer
    different questions and neither is a verdict.
    """
    table = commissions(
        per_side={"ES": "2.88"},
        exchange="included",
        clearing="included",
        nfa="included",
        other="unknown",
    )
    # ``other`` is unknown for the firm that names three components and no fourth
    pricing = price(table, profile=None)
    assert pricing.gaps == ("other",)
    assert pricing.status == "unavailable"

    full = commissions(
        per_side={"ES": "2.88"},
        exchange="included",
        clearing="included",
        nfa="included",
        other="included",
    )
    complete = price(full, profile=None)
    assert complete.gaps == ()
    assert complete.status == "complete"
    assert complete.fees_per_side == Decimal("2.88")
    assert [item.status for item in complete.charges] == ["known"] + ["included"] * 4
    # a profile the run declares but nothing needs is not an assumption: it resolved no component,
    # so it neither appears on the cost nor makes it conditional
    unused = price_components(
        components=full.components,
        commission_status=full.status,
        commission_per_side=full.per_side("ES"),
        root="ES",
        when=WHEN,
        costs=cost_schedule(),
        fee_source=fee_table(nfa_row()),
        profile=ParticipantProfile.from_mapping({"cme_membership_status": "member"}),
    )
    assert unused.profile_priced is False
    assert unused.status == "complete"
    status, reasons = cash_estimate(
        payouts_modeled=True,
        payout_cap_unknown=False,
        cost_status=complete.status,
        cost_assumption=None,
    )
    assert status == "exact"
    estimate, estimate_reasons = estimate_status(
        coverage=(),
        verified=False,
        commissions_known=True,
        cost_assumption=None,
        news_covered=None,
    )
    assert (estimate, status) == ("conditional", "exact")
    assert "the ruleset is unverified" in estimate_reasons
    assert reasons == ()


# --------------------------------------------------------------- 6. no real fee in the engine


def test_a_cme_fee_estimate_appears_nowhere_in_the_engine_or_the_rulesets() -> None:
    """The unverified owner reference 1.38 is documentation only (AGENTS.md section 1.5).

    It is NOT a fee: no ruleset and no engine module may carry it as one, so a grep is the test.
    It may appear only in ``docs/data/cme-exchange-fees.md``, under "Unverified owner references",
    and through a cost-assumption file the user passes. The versioned assumption files under
    ``rulesets/prop/cost_assumptions`` are exactly that kind of file: the upper bound's evidence
    explains where its 2.00 comes from (Topstep's published 2.76 round turn = 1.38 per side,
    matching the owner's reference, plus margin), and no engine module or firm ruleset carries it.
    """
    root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for pattern in ("crucible/**/*.py", "rulesets/**/*.yaml", "rulesets/**/*.yml"):
        for path in root.glob(pattern):
            if "cost_assumptions" in path.relative_to(root).parts:
                continue
            if "1.38" in path.read_text(encoding="utf-8"):
                offenders.append(path.relative_to(root).as_posix())
    assert not offenders, f"a real CME fee estimate leaked into data: {offenders}"
