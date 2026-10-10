"""Ready-made strategy specs to start from (ADR-0067).

Each one is a complete, valid spec; ``crucible spec templates --name <name>`` prints it. An agent
changes the numbers to what the person asked for rather than inventing a shape. The tests compile
every template, so none can rot.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Template:
    title: str
    summary: str
    spec: dict[str, object]

    def as_dict(self, *, include_spec: bool = True) -> dict[str, object]:
        out: dict[str, object] = {"title": self.title, "summary": self.summary}
        if include_spec:
            out["spec"] = self.spec
        return out


TEMPLATES: dict[str, Template] = {
    "sma_crossover": Template(
        "Moving-average crossover",
        "Buy when the fast simple moving average crosses above the slow one, sell when it "
        "crosses back below. Long only.",
        {
            "spec_version": 1,
            "name": "SMA 10/30 crossover",
            "direction": "long_only",
            "entry": {"long": "sma(10) crosses_above sma(30)"},
            "exit": {"long": "sma(10) crosses_below sma(30)"},
            "sizing": {"type": "all_in"},
        },
    ),
    "ema_crossover": Template(
        "Exponential moving-average crossover",
        "Like the SMA crossover but reacts faster to recent prices (12/26 bars).",
        {
            "spec_version": 1,
            "name": "EMA 12/26 crossover",
            "direction": "long_only",
            "entry": {"long": "ema(12) crosses_above ema(26)"},
            "exit": {"long": "ema(12) crosses_below ema(26)"},
        },
    ),
    "trend_filter": Template(
        "Trend filter",
        "Hold while the price is above its 200-bar moving average, otherwise stay in cash.",
        {
            "spec_version": 1,
            "name": "Above the 200-day average",
            "direction": "long_only",
            "entry": {"long": "close crosses_above sma(200)"},
            "exit": {"long": "close crosses_below sma(200)"},
        },
    ),
    "rsi_mean_reversion": Template(
        "RSI mean reversion",
        "Buy when the 14-bar RSI is oversold (below 30), sell when it recovers above 55, with "
        "an 8 % stop loss.",
        {
            "spec_version": 1,
            "name": "RSI oversold bounce",
            "direction": "long_only",
            "entry": {"long": "rsi(14) < 30"},
            "exit": {"long": "rsi(14) > 55"},
            "risk": {"stop_loss_pct": 8},
        },
    ),
    "breakout": Template(
        "Channel breakout",
        "Buy a close above the previous 20-bar high, sell a close below the previous 10-bar low.",
        {
            "spec_version": 1,
            "name": "20-day breakout",
            "direction": "long_only",
            "entry": {"long": "close > highest(20)"},
            "exit": {"long": "close < lowest(10)"},
        },
    ),
    "bollinger_reversion": Template(
        "Bollinger band reversion",
        "Buy when the price closes below the lower Bollinger band, sell when it returns to the "
        "20-bar average.",
        {
            "spec_version": 1,
            "name": "Bollinger bounce",
            "direction": "long_only",
            "entry": {"long": "close < bb_lower(20, 2)"},
            "exit": {"long": "close > sma(20)"},
            "risk": {"stop_loss_pct": 8},
        },
    ),
    "momentum": Template(
        "Simple momentum",
        "Hold while the last 126 bars (about six months) were up, otherwise stay in cash.",
        {
            "spec_version": 1,
            "name": "6-month momentum",
            "direction": "long_only",
            "entry": {"long": "roc(126) > 0"},
            "exit": {"long": "roc(126) <= 0"},
        },
    ),
    "sma_long_short": Template(
        "Moving-average crossover, long and short",
        "Long when the fast average is above the slow one, short when it is below; reverses "
        "directly. Short selling has costs and risks the simulation only approximates.",
        {
            "spec_version": 1,
            "name": "SMA 20/50 long-short",
            "direction": "long_short",
            "entry": {
                "long": "sma(20) crosses_above sma(50)",
                "short": "sma(20) crosses_below sma(50)",
            },
        },
    ),
    "buy_and_hold": Template(
        "Buy and hold",
        "Be fully invested from the first bar. The benchmark every other strategy is "
        "compared with.",
        {"spec_version": 1, "name": "Buy and hold", "entry": {"long": "always"}},
    ),
}
