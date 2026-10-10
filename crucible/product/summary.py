"""The plain-language reading of a result, generated from the numbers (ADR-0068).

Everything here is a pure function of :class:`SummaryInputs`: the same numbers always give the
same words, in the same order, with no randomness and no free text. The module never says a
strategy "works". Its strongest verdict is ``some_evidence``, and it is reachable only when every
guard below passes; with a single instrument it is unreachable by construction, because one
instrument is one history. The thresholds are named constants so the docs and the tests can cite
them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- thresholds (documented in docs/guide/reading-a-report.md) ---------------------------------
MIN_TRADES = 100
"""Fewer completed trades than this is "few trades": the result rests on too few decisions."""
VERY_FEW_TRADES = 30
MIN_YEARS = 5.0
"""A sample shorter than this is "short": it can sit entirely inside one market regime."""
VERY_SHORT_YEARS = 2.0
WIDE_SHARPE_INTERVAL = 1.0
"""A 95 % Sharpe interval wider than this says the data cannot pin the ratio down."""
DSR_CONFIDENT = 0.95
NULL_P_VALUE = 0.05
REALISM_DROP_PP = 1.5
"""A drop in annual return (percentage points) under realistic fills that is flagged, if it is
also more than a quarter of the headline return."""
BEAT_MARGIN_PP = 0.5
"""Annual-return gap (percentage points) under which strategy and benchmark are "similar"."""

DISCLAIMER = (
    "This is a historical simulation, not a prediction and not investment advice. Past "
    "performance does not tell you what a strategy will do next. Real trading adds costs, "
    "taxes and behaviour that a simulation only approximates."
)


@dataclass(frozen=True, slots=True)
class Side:
    """One of the two curves (strategy or buy-and-hold) in plain numbers."""

    final_equity: float
    total_return_pct: float
    cagr_pct: float
    volatility_pct: float
    max_drawdown_pct: float  # negative
    sharpe: float
    sharpe_low: float | None
    sharpe_high: float | None


@dataclass(frozen=True, slots=True)
class SummaryInputs:
    strategy: Side
    benchmark: Side
    symbols: tuple[str, ...]
    start: str
    end: str
    years: float
    capital: float
    n_trades: int
    hit_rate_pct: float | None
    time_in_market_pct: float
    open_position_at_end: bool
    avg_holding_bars: float | None
    cost_label: str
    slippage_bps: float
    commission_bps: float
    trial_count: int
    dsr: float | None
    contamination: bool
    null_iterations: int
    null_p_value: float | None
    spec_name: str | None = None
    parameter_hints: tuple[str, ...] = ()
    cost_preset: str = "standard"
    realism: Side | None = None
    """The same rules re-run on the event-driven engine at Level 2 (``realism_check``)."""


@dataclass(frozen=True, slots=True)
class Flag:
    code: str
    text: str


@dataclass(frozen=True, slots=True)
class Summary:
    verdict_level: str  # some_evidence | not_conclusive | no_edge_detected
    verdict: str
    headline: str
    what_happened: list[str]
    versus_benchmark: list[str]
    how_much_to_trust: list[str]
    flags: list[Flag]
    next_steps: list[str]
    disclaimer: str = DISCLAIMER
    blockers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "verdict_level": self.verdict_level,
            "verdict": self.verdict,
            "headline": self.headline,
            "what_happened": self.what_happened,
            "versus_benchmark": self.versus_benchmark,
            "how_much_to_trust": self.how_much_to_trust,
            "flags": [{"code": f.code, "text": f.text} for f in self.flags],
            "next_steps": self.next_steps,
            "disclaimer": self.disclaimer,
        }


def money(value: float) -> str:
    return f"${value:,.0f}"


def pct(value: float, *, signed: bool = False) -> str:
    return f"{value:+.1f}%" if signed else f"{value:.1f}%"


def _names(symbols: tuple[str, ...]) -> str:
    if len(symbols) == 1:
        return symbols[0]
    if len(symbols) == 2:
        return f"{symbols[0]} and {symbols[1]}"
    return f"{', '.join(symbols[:-1])} and {symbols[-1]}"


def _flags(i: SummaryInputs) -> list[Flag]:
    flags: list[Flag] = []
    low, high = i.strategy.sharpe_low, i.strategy.sharpe_high
    if low is not None and high is not None:
        if low <= 0.0:
            flags.append(
                Flag(
                    "ci_includes_zero",
                    f"The 95% range for the Sharpe ratio ({low:.2f} to {high:.2f}) includes zero: "
                    "this history cannot rule out that the strategy has no real edge.",
                )
            )
        elif high - low > WIDE_SHARPE_INTERVAL:
            flags.append(
                Flag(
                    "wide_interval",
                    f"The 95% range for the Sharpe ratio is wide ({low:.2f} to {high:.2f}): the "
                    "data cannot pin down how good the strategy is, only that the estimate is "
                    "above zero.",
                )
            )
    if i.n_trades < VERY_FEW_TRADES:
        flags.append(
            Flag(
                "very_few_trades",
                f"Only {i.n_trades} completed trades: far too few to say whether the result is "
                "skill or luck.",
            )
        )
    elif i.n_trades < MIN_TRADES:
        flags.append(
            Flag(
                "few_trades",
                f"Only {i.n_trades} completed trades. A few dozen decisions are not enough to "
                f"separate skill from luck (this report asks for {MIN_TRADES} or more).",
            )
        )
    if len(i.symbols) == 1:
        flags.append(
            Flag(
                "single_instrument",
                f"One instrument ({i.symbols[0]}) is one history. A rule that fits it may be a "
                "coincidence of that particular path; it has not been tested anywhere else.",
            )
        )
    if i.years < VERY_SHORT_YEARS:
        flags.append(
            Flag(
                "very_short_sample",
                f"The test covers only {i.years:.1f} years, which can sit entirely inside one "
                "market mood.",
            )
        )
    elif i.years < MIN_YEARS:
        flags.append(
            Flag(
                "short_sample",
                f"The test covers {i.years:.2f} years; this report asks for {MIN_YEARS:g} or "
                "more, because a shorter test may miss a full market cycle.",
            )
        )
    if i.trial_count > 1:
        flags.append(
            Flag(
                "multiple_trials",
                f"This is trial number {i.trial_count} on this data. Every extra variant tried "
                "makes a good-looking result more likely by chance alone; the deflated Sharpe "
                "below already accounts for that.",
            )
        )
    if i.dsr is not None and i.dsr < DSR_CONFIDENT:
        flags.append(
            Flag(
                "dsr_low",
                f"After accounting for the {i.trial_count} variant(s) tried, the probability "
                f"that the Sharpe ratio is genuinely positive is {i.dsr * 100:.0f}% "
                f"(this report wants {DSR_CONFIDENT * 100:.0f}% or more).",
            )
        )
    if i.null_p_value is not None and i.null_p_value >= NULL_P_VALUE:
        flags.append(
            Flag(
                "null_not_beaten",
                f"Re-ordering the same daily returns at random did as well or better in "
                f"{i.null_p_value * 100:.0f}% of {i.null_iterations} tries. That is within what "
                "luck produces, so the timing of the rules has not been shown to matter.",
            )
        )
    if i.realism is not None:
        drop = i.strategy.cagr_pct - i.realism.cagr_pct
        if drop > max(REALISM_DROP_PP, 0.25 * abs(i.strategy.cagr_pct)):
            flags.append(
                Flag(
                    "fragile_to_execution",
                    f"With realistic fills (next-bar prices, spread and latency) the return "
                    f"falls from {i.strategy.cagr_pct:.1f}% to {i.realism.cagr_pct:.1f}% a year: "
                    "the result leans on optimistic execution.",
                )
            )
    if i.contamination:
        flags.append(
            Flag(
                "contaminated",
                "An earlier optimisation run in this family already looked at this period, so "
                "this is not an out-of-sample result.",
            )
        )
    if i.strategy.sharpe <= i.benchmark.sharpe:
        flags.append(
            Flag(
                "no_better_than_buy_and_hold",
                "Per unit of risk, the strategy did not improve on simply buying and holding "
                f"(Sharpe {i.strategy.sharpe:.2f} vs {i.benchmark.sharpe:.2f}).",
            )
        )
    return flags


def _verdict(i: SummaryInputs, flags: list[Flag]) -> tuple[str, str, list[str]]:
    codes = {f.code for f in flags}
    low = i.strategy.sharpe_low
    if i.strategy.sharpe <= 0.0 or i.strategy.total_return_pct <= 0.0:
        return (
            "no_edge_detected",
            "No edge detected: the strategy did not make money on a risk-adjusted basis over "
            "this period.",
            ["non_positive_result"],
        )
    blockers = sorted(
        codes
        & {
            "ci_includes_zero",
            "very_few_trades",
            "few_trades",
            "single_instrument",
            "very_short_sample",
            "short_sample",
            "dsr_low",
            "null_not_beaten",
            "contaminated",
        }
    )
    if low is None:
        blockers.append("no_interval")
    if not blockers:
        return (
            "some_evidence",
            "Some evidence of a real edge: the result clears every statistical guard this "
            "report applies. That is a reason to test further, not proof that it will work.",
            [],
        )
    if i.strategy.cagr_pct >= i.benchmark.cagr_pct:
        lead = "it made money and beat buy-and-hold in this one backtest"
    else:
        lead = "it made money in this one backtest and earned less than buy-and-hold"
    return (
        "not_conclusive",
        f"Not conclusive: {lead}; the evidence is too thin to tell skill from luck "
        "(see the warnings). Treat it as an idea worth testing further, not a basis for "
        "real money.",
        blockers,
    )


def build_summary(i: SummaryInputs) -> Summary:
    s, b = i.strategy, i.benchmark
    flags = _flags(i)
    level, verdict, blockers = _verdict(i, flags)
    names = _names(i.symbols)
    label = i.spec_name or "The strategy"

    headline = (
        f"{label} turned {money(i.capital)} into {money(s.final_equity)} "
        f"({pct(s.total_return_pct, signed=True)}, {pct(s.cagr_pct)} a year) on {names} from "
        f"{i.start} to {i.end}; buying and holding {names} would have made "
        f"{money(b.final_equity)} ({pct(b.total_return_pct, signed=True)}, {pct(b.cagr_pct)} a "
        "year)."
    )

    gap = s.cagr_pct - b.cagr_pct
    if abs(gap) < BEAT_MARGIN_PP:
        compare = (
            f"The strategy and buy-and-hold earned about the same per year "
            f"({pct(s.cagr_pct)} vs {pct(b.cagr_pct)})."
        )
    elif gap > 0:
        compare = (
            f"The strategy earned {gap:.1f} percentage points a year more than buy-and-hold "
            f"({pct(s.cagr_pct)} vs {pct(b.cagr_pct)})."
        )
    else:
        compare = (
            f"The strategy earned {-gap:.1f} percentage points a year less than buy-and-hold "
            f"({pct(s.cagr_pct)} vs {pct(b.cagr_pct)})."
        )
    if s.max_drawdown_pct > b.max_drawdown_pct:
        risk = (
            f"Its worst peak-to-trough fall was {pct(s.max_drawdown_pct)} against "
            f"{pct(b.max_drawdown_pct)} for buy-and-hold: it was less painful to hold."
        )
    elif s.max_drawdown_pct < b.max_drawdown_pct:
        risk = (
            f"Its worst peak-to-trough fall was {pct(s.max_drawdown_pct)} against "
            f"{pct(b.max_drawdown_pct)} for buy-and-hold: it was more painful to hold."
        )
    else:
        risk = f"Both had the same worst fall, {pct(s.max_drawdown_pct)}."

    trades = f"It completed {i.n_trades} trades"
    if i.hit_rate_pct is not None and i.n_trades:
        trades += f", {i.hit_rate_pct:.0f}% of them profitable before costs"
    trades += f", and was invested {i.time_in_market_pct:.0f}% of the time."
    what = [trades]
    if i.avg_holding_bars is not None:
        what.append(f"A trade lasted {i.avg_holding_bars:.0f} bars on average.")
    if i.open_position_at_end:
        what.append("A position was still open at the end; it is not counted as a trade.")
    what.append(
        f"Costs: {i.slippage_bps:g} bps slippage and {i.commission_bps:g} bps commission on every "
        f"trade ({i.cost_label})."
    )

    trust: list[str] = []
    if s.sharpe_low is not None and s.sharpe_high is not None:
        trust.append(
            f"Sharpe ratio (return per unit of risk): {s.sharpe:.2f}, with a 95% range of "
            f"{s.sharpe_low:.2f} to {s.sharpe_high:.2f}. Buy-and-hold: {b.sharpe:.2f}."
        )
    trust.append(f"Variants tried on this data so far (trial count): {i.trial_count}.")
    tried = "1 variant" if i.trial_count == 1 else f"{i.trial_count} variants"
    if i.dsr is not None:
        trust.append(
            f"Deflated Sharpe ratio: {i.dsr:.2f} (the probability the Sharpe is genuinely "
            f"positive after accounting for {tried} tried)."
        )
    else:
        trust.append(
            "Deflated Sharpe ratio: not computable yet (it needs more than one variant tried "
            "on the same data)."
        )
    if i.null_p_value is not None:
        beaten = (
            f"in none of the {i.null_iterations} tries"
            if i.null_p_value == 0.0
            else f"in {i.null_p_value * 100:.0f}% of {i.null_iterations} tries"
        )
        trust.append(
            f"Random re-ordering test: the same daily returns shuffled at random matched or beat "
            f"the strategy {beaten}. A low number means the strategy gains from the real order "
            "of returns (trends, calm and stormy spells), which shuffling destroys; it does not "
            "by itself show the edge will continue."
        )

    if i.realism is not None:
        what.append(
            f"With realistic fills (event-driven engine, orders filled at the next bar with a "
            f"spread and latency) it would have ended at {money(i.realism.final_equity)} "
            f"({pct(i.realism.cagr_pct)} a year, worst fall {pct(i.realism.max_drawdown_pct)})."
        )
    steps = _next_steps(i, flags)
    return Summary(
        verdict_level=level,
        verdict=verdict,
        headline=headline,
        what_happened=what,
        versus_benchmark=[compare, risk],
        how_much_to_trust=trust,
        flags=flags,
        next_steps=steps,
        blockers=blockers,
    )


def _next_steps(i: SummaryInputs, flags: list[Flag]) -> list[str]:
    codes = {f.code for f in flags}
    steps: list[str] = []
    steps.append(
        "Try a different period (for example the ten years before the start date, or one that "
        "includes a crash) and see whether the behaviour holds. A rule that only works in one "
        "window is a coincidence."
    )
    if "single_instrument" in codes:
        steps.append(
            "Run the same rules on other liquid instruments. A real effect should show up beyond "
            "one ticker."
        )
    if i.cost_preset != "conservative":
        steps.append(
            "Re-run with conservative costs (5 bps slippage, 2 bps commission) to see how much "
            "of the result survives worse fills."
        )
    if i.parameter_hints:
        steps.append(
            "Check that the result does not hinge on exact numbers: try "
            + "; ".join(i.parameter_hints)
            + ". If small changes flip the outcome the result is fragile. Each variant counts as "
            "a trial and lowers the deflated Sharpe, which is the honest price of looking."
        )
    if "no_better_than_buy_and_hold" in codes:
        steps.append(
            "Compare against buy-and-hold on risk, not just return: ask whether the smaller "
            "drawdown is worth the lower return for you."
        )
    return steps
