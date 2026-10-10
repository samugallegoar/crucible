# ADR-0067: A declarative strategy spec that compiles to the vectorized signal path

- **Status**: accepted
- **Date**: 2026-10-10

## Context

A strategy had to be a Python class (event-driven) or a polars signal function (vectorized), plus a
YAML config, a symbols list and a pre-built dataset. The vectorized path also carries a lag
convention that is only documented in a docstring (`examples/trend_demo/vectorized_signal.py`: the
engine lags a score by one bar, and a strategy that mirrors an event-driven rule may need a second
one). A person who does not code, driving Crucible through an agent, cannot be asked to write
either, and an agent that writes polars from a plain-language description will get the lag wrong.

## Decision

1. **The spec is data.** A versioned (`spec_version: 1`), Pydantic-validated YAML/JSON document
   (`crucible/strategy_spec/`): `direction` (`long_only`, `long_short`), `entry`/`exit` conditions per
   side, `sizing` (`all_in`, `fixed_fraction`), optional `risk` (`stop_loss_pct`, `take_profit_pct`,
   `max_holding_bars`). Conditions are one-line comparisons (`"sma(10) crosses_above sma(30)"`) or
   `{all: [...]}` / `{any: [...]}` groups. Its JSON Schema is `crucible schema --kind strategy-spec`.
2. **Indicators are a closed, tested set**: bar fields, `sma`, `ema`, `rsi` (Wilder), `roc`,
   `highest`/`lowest` (previous bars, today excluded), `bb_upper`/`bb_lower` (population standard
   deviation). Each value at bar `t` uses bars up to and including `t`; a warm-up null is false.
3. **It compiles to an existing `SignalFunction`** (`compile.spec_signal`), so the vectorized engine,
   `promote` and the event-driven `PromotedSignalStrategy` run it unchanged. **The lag convention is
   stated once**: the compiled score is the target weight decided at bar `t`'s close, adds no lag of
   its own, and the engine's mandatory one-bar lag (or the promoted strategy's next-bar fill) is the
   only delay. A spec author never reasons about it.
4. **Path-dependent logic is evaluated bar by bar** with one state machine per symbol (exits before
   entries; no re-entry on the bar that exited; opposite entry flips; both entries true on one bar is
   refused). Stops are checked on closes only and measured from the entry bar's close.
5. **Refuse ambiguity** (AGENTS.md section 5): a long entry with no way out, a short side on a
   `long_only` spec, an unknown field or indicator, a non-integer period, a condition that is not a
   single comparison, and both entries firing on one bar are each a `ConfigurationError` that names
   the location in the spec and says what to write.
6. **No custom code in a spec**: Python strategies stay the advanced path. A rule the spec cannot say
   is a Python strategy, not an escape hatch inside the spec.

## Alternatives considered

- *A Python DSL / fluent API:* friendly to coders, but it is code; an agent must write and register
  it, which is the problem being solved.
- *Free-text rules interpreted by a model:* non-deterministic and unrefusable.
- *A new engine path for specs:* a second implementation to keep equal to the first. Compiling to
  the existing signal interface reuses the shift discipline, the poisoned-future harness and the
  promotion equivalence.
- *Lag chosen per indicator:* leaks the convention back to the author.

## Consequences

- The no-code path inherits the vectorized engine's scope (Levels 0-1, no risk limits, no corporate
  actions); a spec run at a higher realism level goes through `promote`.
- `spec_signal` recomputes the whole window each call. On the promoted path the history window must
  cover everything the rules' state depends on (stops and exits depend on the entry bar), so
  promotion of a spec needs `lookback` of at least the number of bars in the run.
- Every indicator is in the poisoned-future and prefix-invariance harness
  (`tests/lookahead/test_strategy_spec_poisoned_future.py`); adding one adds it there.
- No change to `ExperimentConfig`, the config hash or any golden fixture of an existing run.
