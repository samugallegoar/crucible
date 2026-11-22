"""Rule coverage and evaluation status: what is modeled, what is declared unmodeled (ADR-0106).

Unmodeled rules are never ignored. Every rule of the ruleset is one coverage row marked
``modeled``; every ``not_modeled`` entry is a row marked ``not_modeled`` with its materiality. The
status follows from the worst unmodeled materiality:

- ``complete``: nothing is unmodeled, or only immaterial rules are (they still warn);
- ``conditional_on_modeled_rules``: a material rule is unmodeled, so a claim is conditional on
  the modeled rules only;
- ``blocked``: a critical rule is unmodeled, so no definitive verdict is possible.

``counterfactual_application`` labels rules read now applied to a data window that starts before
the ruleset's ``effective_from``: every pre-2025 run under current rules.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from crucible.prop.rules_schema import NewsRestrictionRule
from crucible.prop.ruleset import Attribution, PropRuleset

if TYPE_CHECKING:
    from crucible.data.cme_sessions import SessionCalendar, TradeDateSession

Materiality = Literal["immaterial", "material", "critical"]
EvaluationStatus = Literal["complete", "conditional_on_modeled_rules", "blocked"]


@dataclass(frozen=True, slots=True)
class RuleCoverageRow:
    """One firm rule: modeled or declared unmodeled, with its materiality and its source."""

    rule: str
    description: str
    materiality: Materiality
    modeled: bool
    source: Attribution


def rule_coverage(
    ruleset: PropRuleset,
    *,
    news_covered: bool | None = None,
    news_unmodeled: Mapping[str, str] | None = None,
) -> tuple[RuleCoverageRow, ...]:
    """One row per rule of every phase, then one per ``not_modeled`` entry.

    ``news_covered`` says whether the economic calendar covers this attempt's period. A news rule
    without coverage is ``not_modeled`` (material): an uncovered window is never "no news".
    ``news_unmodeled`` maps a news rule's ``rule_id`` to the reason the rule cannot be modeled for
    this attempt (an event type the calendar does not carry, for instance); those rules are
    ``not_modeled`` (material) too, and the reason is part of the row's description.
    """
    rows: list[RuleCoverageRow] = []
    unmodeled_by_type = dict(news_unmodeled or {})
    for phase in ruleset.phases:
        for rule in (*phase.rules, *phase.pass_conditions, *phase.fees):
            reason = unmodeled_by_type.get(rule.rule_id)
            unmodeled_news = isinstance(rule, NewsRestrictionRule) and news_covered is not True
            unmodeled = unmodeled_news or reason is not None
            description = rule.description or rule.kind
            if reason is not None:
                description = f"{description}: {reason}"
            rows.append(
                RuleCoverageRow(
                    rule=f"{phase.phase_id}.{rule.rule_id}",
                    description=description,
                    materiality="material" if unmodeled else "immaterial",
                    modeled=not unmodeled,
                    source=rule.source,
                )
            )
    rows.extend(
        RuleCoverageRow(
            rule=entry.rule,
            description=entry.description,
            materiality=entry.materiality,
            modeled=False,
            source=entry.source,
        )
        for entry in ruleset.not_modeled
    )
    return tuple(rows)


def material_unmodeled(
    rows: tuple[RuleCoverageRow, ...] | list[RuleCoverageRow],
) -> tuple[str, ...]:
    """The unmodeled rules that weaken a claim (material or critical)."""
    return tuple(row.rule for row in rows if not row.modeled and row.materiality != "immaterial")


def evaluation_status(
    rows: tuple[RuleCoverageRow, ...] | list[RuleCoverageRow],
) -> EvaluationStatus:
    """The worst unmodeled materiality decides the status."""
    unmodeled = {row.materiality for row in rows if not row.modeled}
    if "critical" in unmodeled:
        return "blocked"
    if "material" in unmodeled:
        return "conditional_on_modeled_rules"
    return "complete"


def coverage_warnings(
    rows: tuple[RuleCoverageRow, ...] | list[RuleCoverageRow], ruleset: PropRuleset
) -> tuple[str, ...]:
    """Every declared gap, plus the ruleset's own labels. Warnings, never silent weakening."""
    warnings = [
        f"{row.rule} is not modeled ({row.materiality}): {row.description}"
        for row in rows
        if not row.modeled
    ]
    if not ruleset.verified:
        warnings.append(
            f"ruleset {ruleset.ruleset_id} v{ruleset.version} is unverified: no result computed "
            "from it may be presented as confirmed firm rules"
        )
    return tuple(warnings)


def chicago_day(instant_ns: int) -> dt.date:
    """The ``America/Chicago`` calendar date of an instant.

    The CME session table is transcribed in Chicago wall clock, so the days an unsourced window
    names are Chicago days; nothing else in the prop package is zoned, so this stays local to the
    one comparison that needs it.
    """
    from zoneinfo import ZoneInfo

    seconds = int(instant_ns) // 1_000_000_000
    return dt.datetime.fromtimestamp(seconds, dt.UTC).astimezone(ZoneInfo("America/Chicago")).date()


def session_calendar_gaps(
    calendar: SessionCalendar, sessions: Iterable[TradeDateSession]
) -> tuple[str, ...]:
    """The unsourced CME session-calendar windows an attempt trades through.

    A rule that measures against the session schedule (a session-relative ``flat_by``, the rule-day
    boundary, the end-of-day test) is only as good as that schedule. Some CME schedules were never
    archived: the table builds those sessions from the regular-week *regime* and flags them
    ``verified: False``, which for a holiday means the close (and any early close) is a guess.

    The check uses each touched session's own calendar days -- its Chicago opening day through its
    Chicago closing day, NOT just the trade date -- because a holiday's session opens on the evening
    before: the session of trade date 2023-11-24 opens on 2023-11-23, which is inside the unsourced
    Thanksgiving 2023 window. Each gap is reported as ``"<first>..<last>"``, sorted.
    """
    found: set[str] = set()
    for session in sessions:
        first = chicago_day(session.open_ns)
        last = chicago_day(session.close_ns)
        for window in calendar.table.unsourced:
            if calendar.root not in window.roots:
                continue
            if window.first <= last and first <= window.last:
                found.add(f"{window.first.isoformat()}..{window.last.isoformat()}")
    return tuple(sorted(found))


def counterfactual_application(data_start: dt.date, ruleset: PropRuleset) -> bool:
    """True when the data window starts before the ruleset took effect: current rules applied to
    an older market is a counterfactual application, and the result says so."""
    return data_start < ruleset.effective_from
