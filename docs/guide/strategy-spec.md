# Strategy spec reference

A strategy spec says, in a few lines of YAML or JSON, when to buy, when to sell, how much to use
and what stops to apply. You do not write code and you never think about timing: Crucible applies the
one-bar delay itself. An agent writes the spec for you; this page is what it follows.

```yaml
spec_version: 1
name: SMA 10/30 crossover
direction: long_only
entry: {long: "sma(10) crosses_above sma(30)"}
exit:  {long: "sma(10) crosses_below sma(30)"}
sizing: {type: all_in}
risk: {stop_loss_pct: 5, take_profit_pct: 15, max_holding_bars: 60}
```

Check one without running it: `crucible spec check --spec my.yaml` (it reads the rule back in words).
Ready-made starting points: `crucible spec templates`. The JSON Schema:
`crucible schema --kind strategy-spec`.

## Fields

| Field | Values | Meaning |
|---|---|---|
| `spec_version` | `1` | the spec language version |
| `name` | text | a label for reports; does not affect the result |
| `direction` | `long_only` (default), `long_short` | whether it may sell short |
| `entry.long` / `entry.short` | condition | when to open a long / short position |
| `exit.long` / `exit.short` | condition | when to close it |
| `sizing.type` | `all_in` (default), `fixed_fraction` | all of the capital, or a fraction of it |
| `sizing.fraction` | 0 < x <= 1 | with `fixed_fraction`; the rest stays in cash |
| `risk.stop_loss_pct` | percent, 0-100 | close a position that is this far below (above, for a short) its entry close |
| `risk.take_profit_pct` | percent | close a position this far in profit |
| `risk.max_holding_bars` | whole number >= 1 | close a position after this many bars |

## Conditions

A condition is one comparison, `"<left> <comparator> <right>"`:

- comparators: `>`, `>=`, `<`, `<=`, `crosses_above`, `crosses_below` (a crossing is true on the bar
  where the left side moves from at-or-below to above the right side, or the reverse);
- operands: a number (`30`), a bar field (`close`, `open`, `high`, `low`, `volume`) or an indicator;
- `always`: true on every bar (buy and hold);
- groups: `{all: [c1, c2]}` (every one) and `{any: [c1, c2]}` (at least one), nestable.

```yaml
entry:
  long:
    all:
      - "close > sma(200)"
      - any: ["rsi(14) < 35", "close < bb_lower(20, 2)"]
```

## Indicators

| Indicator | Meaning | Warm-up (bars) |
|---|---|---|
| `sma(n[, field])` | simple moving average | n |
| `ema(n[, field])` | exponential moving average, smoothing 2/(n+1) | n |
| `rsi(n[, field])` | Wilder relative strength index, 0-100 | n+1 |
| `roc(n[, field])` | percent change over n bars (`roc(126) > 0`: up over ~6 months) | n+1 |
| `highest(n[, field])` | highest of the **previous** n bars (today excluded) | n+1 |
| `lowest(n[, field])` | lowest of the previous n bars | n+1 |
| `bb_upper(n[, k])` | moving average + k standard deviations (k defaults to 2) | n |
| `bb_lower(n[, k])` | moving average - k standard deviations | n |

`field` is one of `close` (default), `open`, `high`, `low`, `volume`. Until an indicator has its
full window its value is missing, and any rule that touches a missing value is false: nothing is
back-filled and a rule cannot act on history that did not exist.

## Rules of the position logic

On each bar, for each symbol:

1. A held position first meets its exits: the stop, the take-profit, the holding limit, then your
   `exit` condition. If it exits, it stays flat for that bar (no instant re-entry).
2. A flat position takes its `entry` if true.
3. In `long_short`, a long position meets the short entry by flipping to short directly, and
   the reverse.
4. If the long and short entries are both true on one bar, the run is refused: make them mutually
   exclusive.
5. Stops are checked on closing prices from the entry bar's close. A daily bar cannot show an
   intraday stop, and a gap through the level fills at the next price.

With several symbols the capital is split equally between them and each trades on its own signal.
`all_in` never uses leverage.

## Plain language to spec

| You say | Spec |
|---|---|
| "buy when the 10-day average crosses above the 30-day, sell when it crosses below" | entry `sma(10) crosses_above sma(30)`, exit `sma(10) crosses_below sma(30)` |
| "buy dips: RSI under 30, sell at 55, stop at 8%" | entry `rsi(14) < 30`, exit `rsi(14) > 55`, `risk.stop_loss_pct: 8` |
| "buy a new 20-day high, sell a new 10-day low" | entry `close > highest(20)`, exit `close < lowest(10)` |
| "stay in while above the 200-day average" | entry `close crosses_above sma(200)`, exit `close crosses_below sma(200)` |
| "buy when the price drops below the lower Bollinger band, sell back at the average" | entry `close < bb_lower(20, 2)`, exit `close > sma(20)` |
| "momentum: hold when the last six months were up" | entry `roc(126) > 0`, exit `roc(126) <= 0` |
| "long when the 20 is above the 50, short when below" | `long_short`, entry long `sma(20) crosses_above sma(50)`, short `sma(20) crosses_below sma(50)` |
| "use half of my money" | `sizing: {type: fixed_fraction, fraction: 0.5}` |

## What a refusal looks like

A bad spec stops before anything runs, with where it is wrong and what to write:

```
refused: entry.long has no way out: a position would be held forever. Add exit.long (e.g. the
opposite crossing), or a risk.stop_loss_pct / take_profit_pct / max_holding_bars. To hold from
the first bar, use entry: {long: always}
```

Other refusals: a short rule on a `long_only` spec, an unknown field or indicator (the allowed ones
are listed), a period that is not a whole number, a condition that is not a single comparison,
`fixed_fraction` without a fraction, and a window too short for the longest indicator.

## Beyond the spec

A rule the spec cannot express (ranking a universe, volatility targeting, anything stateful beyond
the position) is a Python strategy: see [the contributor hub](../contributing/README.md) and
`examples/momentum`. The spec's own limits are in [`docs/modules/strategy_spec.md`](../modules/strategy_spec.md).
