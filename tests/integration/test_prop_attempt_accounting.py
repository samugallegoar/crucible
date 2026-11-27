"""What an attempt pays (ADR-0107, amendment of 2026-11-27).

Three FTMO review findings (F14, F15, F16) were accounting bugs, not rule values, and each is
pinned here by hand on synthetic bars:

- **F14.** A monthly subscription is charged for every calendar month STARTED while the attempt is
  alive, from the purchase month up to and including the month of its terminal event. An attempt
  that dies on its first session pays ONE month, not one per month of the analyst's horizon, and
  no month after the terminal event is charged.

- **F15.** "The economic calendar does not cover the attempt period" may only be listed when a
  ``news_restriction`` rule REQUESTED an event type the calendar does not cover. A ruleset with no
  news rule never says it, even when a ``not_modeled`` entry's id contains the word "news".
- **F16.** ``phase_outcomes[*].trading_days`` is the number of trading days actually elapsed in
  that phase up to its terminal event: an attempt failing in its first session reports 1, not the
  horizon's 20.

The bars are the scheduled 60-minute ES sessions of real trade dates, every bar flat except the
breach bar; one ES contract at $50 a point on a $50,000 account, no commission, no spread and no
slippage, so every number below is arithmetic on the price series.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import polars as pl

from crucible.data.cme_session_table import cme_session_table
from crucible.data.cme_sessions import SessionCalendar
from crucible.data.contracts import ROLL_SCHEMA
from crucible.data.futures_specs import futures_spec
from crucible.execution.futures_sim import CostSchedule
from crucible.prop.attempt import simulate_attempt
from crucible.prop.ruleset import Attribution, PropRuleset

_COMPONENTS_ALL_IN = {
    name: {"status": "included", "evidence": "official_quote", "text": "SYNTHETIC TEST VALUE"}
    for name in ("exchange", "clearing", "nfa", "other")
}
"""A commission whose four cost components are all inside it (synthetic, all-in)."""

NS = 1_000_000_000
CALENDAR = SessionCalendar(cme_session_table(), "ES")
ENTRY = 4800.0
"""Every bar's open: one ES contract at $50 a point, so one point is $50."""

FIRST = dt.date(2024, 6, 12)
"""The first session of the short attempt (a Wednesday: one full CME session)."""

LATER = dt.date(2024, 7, 15)
"""A session past the June/July boundary, so a horizon window can outlive the terminal event."""


def _source() -> Attribution:
    return Attribution(
        url="https://example.invalid/synthetic-rules",
        quote="Synthetic rule value invented for a test, not a real firm's rule",
        snapshot_sha256="0" * 64,
        retrieved_at=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
        synthetic=True,
    )


def _ruleset(
    *,
    rules: list[dict[str, object]] | None = None,
    fees: list[dict[str, object]] | None = None,
    not_modeled: list[dict[str, object]] | None = None,
) -> PropRuleset:
    source = _source().model_dump(mode="json")
    declared = [_drawdown("500")] if rules is None else rules
    for rule in declared + (fees or []):
        rule.setdefault("source", source)
        rule.setdefault("evidence", "official_quote")
    return PropRuleset.model_validate(
        {
            "schema_version": 2,
            "ruleset_id": "synthetic-accounting",
            "version": 1,
            "firm": "SyntheticFirm A",
            "program": "Synthetic Evaluation",
            "account_size_usd": "50000",
            "as_of": "2024-01-01",
            "effective_from": "2024-01-01",
            "instruments": [{"root": "ES", "contract_weight": "1"}],
            "reset": {"time": "17:00:00", "tz": "America/Chicago"},
            "commissions": {
                "status": "known",
                "components": _COMPONENTS_ALL_IN,
                "per_side_usd": {"ES": "0.00"},
                "platform": None,
                "source": source,
            },
            "phases": [
                {
                    "phase_id": "evaluation",
                    "kind": "evaluation",
                    "starting_balance_usd": "50000",
                    "rules": declared,
                    "pass_conditions": [],
                    "fees": fees or [],
                }
            ],
            "not_modeled": [
                {**entry, "source": entry.get("source", source)} for entry in (not_modeled or [])
            ],
        }
    )


def _drawdown(amount: str) -> dict[str, object]:
    """A static equity drawdown of ``amount`` below the start, failed intraday at the breach."""
    return {
        "kind": "static_drawdown",
        "rule_id": "max_loss",
        "amount_usd": amount,
        "basis": "equity",
        "evaluated": "intraday",
        "comparison": "<=",
        "action": "fail",
        "evidence": "official_quote",
    }


def _monthly(amount: str) -> dict[str, object]:
    return {
        "kind": "fee",
        "rule_id": "monthly",
        "fee_kind": "monthly",
        "amount_usd": amount,
        "when": "per_month",
        "comparison": ">=",
        "action": "charge",
        "evidence": "official_quote",
    }


def _session(day: dt.date, *, breach_bar: int | None, low: float) -> list[tuple[int, float, float]]:
    """One scheduled ES session as ``(bar_end_ns, low, close)``; every other price is the entry.

    ``breach_bar`` is the index whose low is ``low`` (and which closes at the entry price, so the
    loss is a touch); ``None`` keeps every bar flat at 4,800.00.
    """
    rows: list[tuple[int, float, float]] = []
    for index, end in enumerate(CALENDAR.session(day).bar_ends(3600)):
        if breach_bar is not None and index == breach_bar:
            rows.append((end, low, ENTRY))
        else:
            rows.append((end, ENTRY, ENTRY))
    return rows


def _bars(rows: list[tuple[int, float, float]]) -> tuple[pl.DataFrame, pl.DataFrame]:
    bars = pl.DataFrame(
        {
            "event_time": [row[0] for row in rows],
            "open": [ENTRY] * len(rows),
            "high": [ENTRY] * len(rows),
            "low": [row[1] for row in rows],
            "close": [row[2] for row in rows],
            "contract": ["ESM4"] * len(rows),
        }
    )
    targets = pl.DataFrame(
        {"event_time": bars["event_time"], "target": pl.Series([1] * len(rows), dtype=pl.Int64)}
    )
    return bars, targets


def _attempt(
    rows: list[tuple[int, float, float]],
    ruleset: PropRuleset,
    *,
    start: dt.date,
    horizon: int,
):
    bars, targets = _bars(rows)
    return simulate_attempt(
        bars=bars,
        targets=targets,
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=futures_spec("ES"),
        costs=CostSchedule(commission=Decimal(0)),
        ruleset=ruleset,
        start_trade_date=start,
        max_horizon_days=horizon,
        calendar=CALENDAR,
        execution_mode="manual",
    )


# --------------------------------------------------------------------------- F14: the fee window


def test_a_first_session_failure_pays_one_monthly_subscription() -> None:
    """F14: 4,800.00 -> a low of 4,788.00 is 12 points = $600, past the $500 drawdown.

    The account dies on its first session (2024-06-12) while the data runs on to 2024-07-15
    (inside the 40-day horizon), so the monthly fee of 119.00 is charged ONCE: one calendar month
    started (June). Before F14 the same attempt paid for the window's last bar's month too, i.e.
    June + July = 238.00.
    """
    rows = (
        _session(FIRST, breach_bar=10, low=4788.0)
        + _session(dt.date(2024, 6, 13), breach_bar=None, low=ENTRY)
        + _session(LATER, breach_bar=None, low=ENTRY)
    )
    result = _attempt(rows, _ruleset(fees=[_monthly("119")]), start=FIRST, horizon=40)
    assert result.outcome == "fail"
    assert result.breached_rule == "max_loss"
    assert result.fees.monthly_usd == Decimal("119")
    assert result.fees.total_usd == Decimal("119")


def test_the_fee_window_ends_with_the_terminal_event_not_the_horizon() -> None:
    """F14: a start on 2024-01-08 whose data ends on 2024-03-08 pays Jan + Feb + Mar = 3 months.

    The two sessions are 4,800.00 for their whole length, so the $500 drawdown is never touched and
    the attempt is censored at the data end (its terminal event is the horizon end): 3 x 119.00 =
    357.00, and no month after March is charged.
    """
    rows = _session(dt.date(2024, 1, 8), breach_bar=None, low=ENTRY) + _session(
        dt.date(2024, 3, 8), breach_bar=None, low=ENTRY
    )
    result = _attempt(
        rows,
        _ruleset(fees=[_monthly("119")]),
        start=dt.date(2024, 1, 8),
        horizon=70,  # 2024-01-08 + 70 days = 2024-03-18, past the last session
    )
    assert result.outcome == "censored"
    assert result.fees.monthly_usd == Decimal("357")


def test_a_month_without_a_terminal_event_is_not_charged() -> None:
    """F14: start 2024-01-08, fail on 2024-01-09, data runnning on to 2024-03-08: 119.00, once."""
    rows = (
        _session(dt.date(2024, 1, 8), breach_bar=None, low=ENTRY)
        + _session(dt.date(2024, 1, 9), breach_bar=10, low=4788.0)
        + _session(dt.date(2024, 3, 8), breach_bar=None, low=ENTRY)
    )
    result = _attempt(rows, _ruleset(fees=[_monthly("119")]), start=dt.date(2024, 1, 8), horizon=70)
    assert result.outcome == "fail"
    assert result.fees.monthly_usd == Decimal("119")


# ------------------------------------------------------------------- F16: the trading-day count


def test_a_first_session_failure_reports_one_trading_day() -> None:
    """F16: the attempt dies on 2024-06-12 with the data running to 2024-07-15, so it reports 1 day.

    Before F16 the count ran to the analyst's window end, so the same attempt reported every
    trading day of the window (the packet measured 20 on a 20-trading-day horizon).
    """
    rows = (
        _session(FIRST, breach_bar=10, low=4788.0)
        + _session(dt.date(2024, 6, 13), breach_bar=None, low=ENTRY)
        + _session(LATER, breach_bar=None, low=ENTRY)
    )
    result = _attempt(rows, _ruleset(), start=FIRST, horizon=40)
    assert result.outcome == "fail"
    assert result.phase_outcomes[0].trading_days == 1


def test_the_count_is_the_days_elapsed_up_to_the_terminal_event() -> None:
    """F16: a failure on the SECOND of three sessions reports 2 trading days, not 3."""
    rows = (
        _session(dt.date(2024, 1, 8), breach_bar=None, low=ENTRY)
        + _session(dt.date(2024, 1, 9), breach_bar=10, low=4788.0)
        + _session(dt.date(2024, 1, 10), breach_bar=None, low=ENTRY)
    )
    result = _attempt(rows, _ruleset(), start=dt.date(2024, 1, 8), horizon=30)
    assert result.outcome == "fail"
    assert result.phase_outcomes[0].trading_days == 2


# ------------------------------------------------------------------- F15: the estimate reason


def _news_not_modeled() -> dict[str, object]:
    return {
        "rule": "news_event_concentration",
        "description": "A discretionary news rule that names no event type, window or instrument.",
        "materiality": "material",
    }


def test_a_ruleset_with_no_news_rule_never_reports_a_calendar_gap() -> None:
    """F15: FTMO requests no event type, so the estimate lists no coverage reason.

    The attempt is ``partial`` because the discretionary rule is a material unmodeled rule (the
    reason names it); it is NOT made to look like an economic-calendar gap.
    """
    result = _attempt(
        _session(FIRST, breach_bar=None, low=ENTRY),
        _ruleset(not_modeled=[_news_not_modeled()]),
        start=FIRST,
        horizon=5,
    )
    assert result.estimate_status == "partial"
    assert any(
        reason == "unmodeled material rule news_event_concentration"
        for reason in result.estimate_reasons
    )
    assert not any(
        "does not cover the attempt period" in reason for reason in result.estimate_reasons
    )


def test_a_requested_event_type_without_coverage_still_reports_the_gap() -> None:
    """F15: a ``news_restriction`` rule whose period the calendar does not cover DOES list it."""
    ruleset = _ruleset(
        rules=[
            {
                "kind": "news_restriction",
                "rule_id": "news_fomc",
                "event_types": ["FOMC_STATEMENT"],
                "instruments": ["ES"],
                "pre_minutes": 5,
                "post_minutes": 5,
                "scope": "new_entries",
                "flatten": "none",
                "effect": "block",
                "comparison": ">=",
                "action": "block_entries",
                "evidence": "official_quote",
            }
        ]
    )
    result = _attempt(
        _session(FIRST, breach_bar=None, low=ENTRY),
        ruleset,
        start=FIRST,
        horizon=5,
    )
    assert result.news_covered is False
    assert any("does not cover the attempt period" in reason for reason in result.estimate_reasons)
