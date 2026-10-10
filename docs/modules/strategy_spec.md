# Module: strategy_spec

## What exists

The no-code strategy path (ADR-0067). A strategy is a validated document, not code.

- `models.py` — `StrategySpec` (Pydantic, frozen, `extra="forbid"`), `Rules`, `Sizing`, `RiskRules`,
  `AllOf` / `AnyOf`, the condition grammar (`parse_condition_text`, `parse_condition`), `parse_spec`,
  `load_spec` (file, YAML/JSON text or mapping), `spec_json_schema`, `canonical_spec`. `check_spec`
  refuses an incoherent spec.
- `indicators.py` — the closed indicator set: bar fields (`close`, `open`, `high`, `low`, `volume`),
  `sma`, `ema`, `rsi`, `roc`, `highest`, `lowest`, `bb_upper`, `bb_lower`, each with its signature,
  warm-up and plain-language description. `resolve_indicator` validates a call.
- `compile.py` — `spec_signal(bars, params)`, a `SignalFunction` (`crucible/vectorized/interfaces.py`)
  with `params["spec"]`; `warmup_bars(spec)`.
- `describe.py` — `describe_spec`, the spec read back in plain sentences.
- `templates.py` — `TEMPLATES`, ready-made specs (all compiled by the tests).

Its CLI is `crucible spec check|templates`, `crucible schema --kind strategy-spec` and, in the
product flow, `crucible backtest` (`docs/modules/product.md`).

### The spec

```yaml
spec_version: 1
name: SMA 10/30 crossover
direction: long_only            # long_only | long_short
entry: {long: "sma(10) crosses_above sma(30)"}      # + short: for long_short
exit:  {long: "sma(10) crosses_below sma(30)"}
sizing: {type: all_in}          # all_in | fixed_fraction + fraction (0, 1]
risk: {stop_loss_pct: 5, take_profit_pct: 15, max_holding_bars: 60}   # all optional
```

A condition is `"<operand> <comparator> <operand>"` (`>`, `>=`, `<`, `<=`, `crosses_above`,
`crosses_below`; `crosses above` with a space is accepted) or `always`, or a group
`{all: [...]}` / `{any: [...]}`. An operand is a number, a bar field or an indicator call
`name(period[, field])`; the Bollinger bands take `(period[, k])`. Reference with every indicator and
translated examples: `docs/guide/strategy-spec.md`.

### Timing, stated once

`spec_signal` returns the **target weight decided from bars up to and including `ts`**. It adds no
lag. The vectorized engine lags it one bar; the promoted event-driven strategy trades it at the next
bar. So `entry: close > sma(20)` is decided at the close of bar `t` and held over bar `t+1`'s return.
Indicators use only bars at or before `t`; a value still inside its warm-up is null and a rule that
touches a null is false.

### Position logic (per symbol, bar by bar)

1. A held position meets its exits first: stop-loss, take-profit (percent move of the close from the
   entry bar's close, checked on closes only), `max_holding_bars`, then the spec's own exit.
2. If it exited, it is flat for the bar and no entry is taken on that bar.
3. A flat position takes its entry; a `long_short` position flips directly on the opposite entry.
4. Both entries true on one bar is refused with the symbol and timestamp.

Sizing: a position is `+/- sizing.weight / N` of equity, `N` the number of symbols in the bars, so
capital is split equally and a `long_only` spec is never levered.

### Refusals (all `ConfigurationError`, with the location and the fix)

A short side on `long_only`; a missing `entry.long`; an entry with no exit and no stop, take-profit or
`max_holding_bars` (a position held forever), unless it is `always` or the spec flips between sides;
`exit.<side>` without `entry.<side>`; an unknown field (the allowed ones are listed), indicator,
comparator or bar field; a period that is not a whole number in 1..2000; a condition that is not one
comparison; two constants compared; a `fixed_fraction` without `fraction` (or the reverse); an
unsupported `spec_version`.

## Responsibility

Turn a described rule into the existing vectorized signal interface, refuse what is ambiguous, and
read the rule back in words. It does no I/O, touches no data store and adds no engine path.

## Interfaces

`spec_signal(bars: pl.LazyFrame, params: dict) -> pl.LazyFrame` (ts, symbol, score). `bars` needs
`symbol`, `event_time`, `open`, `high`, `low`, `close`, `volume`. A config uses
`strategy.entrypoint: crucible.strategy_spec.compile:spec_signal` and `strategy.params: {spec: {...}}`.

## Extension points

A new indicator is one `IndicatorDef` in `indicators.INDICATORS` (name, signature, kind, an
expression builder over one symbol's bars, warm-up, description). It must use only bars up to and
including the current one; add it to `EVERY_INDICATOR` in
`tests/lookahead/test_strategy_spec_poisoned_future.py` and to the table in
`docs/guide/strategy-spec.md` and `AGENT_GUIDE.md`. A new template is an entry in `TEMPLATES`.
A change to the grammar or to a field's meaning needs a new `spec_version`.

## Known gaps

- Daily-style bars only in practice: the grammar has no session, time-of-day or calendar rule, and
  every indicator counts bars, not time.
- Indicators are the eight above; no ATR, MACD, volatility targeting or cross-sectional ranking
  (a ranking strategy is a Python strategy, `examples/momentum`).
- Sizing is per symbol and equal-weight across symbols; no volatility scaling, no pyramiding, no
  per-symbol weights.
- Stops are close-based: a daily bar cannot show an intrabar stop, and a gap through the stop is
  filled at the next price, not at the stop.
- The compiled signal recomputes the whole window each call, so a promoted run needs a lookback of at
  least the run's number of bars (the product flow sets it).
- One spec per run: no portfolio of specs, and no parameter sweep syntax in the spec (use
  `crucible optimize` on a config).
