# ADR-0060: Quote-aware spread (bid/ask on bars)

- **Status**: accepted
- **Date**: 2026-10-03

## Context

The Polymarket importers read top-of-book bid and ask for each side of a contract and kept only
the mid in the bar (ADR-0052). A taker who buys at the mid is filled at a price the market never
offered, so every Polymarket result was optimistic by half the spread on each trade, most of all
where the book is thin (3.4% of the tick file has a zero up-bid). `StaticSpread` and
`DynamicSpread` approximate this with a guess in bps; nothing could fill at the quote the venue
actually showed. Design note: `docs/features/quote-aware-fills.md`.

## Decision

1. **Quotes are optional columns of the bar dataset**, not a separate dataset: `bid_open`,
   `ask_open` (the bar's first quote) and `bid_close`, `ask_close` (its last), nullable Float64
   (`contracts.BAR_QUOTE_SCHEMA`; `QUOTED_BAR_SCHEMA` is `BAR_SCHEMA` plus them). A dataset
   without them is still a valid bar dataset and behaves exactly as before. `BarEvent` carries
   four optional fields; the replay and venue feeds copy the columns when present.
2. **`QuotedSpread` (`execution.spread.type: quoted`, level 2 or higher)** returns the half of the
   wider of the bar's open and close spread: `max(ask_open - bid_open, ask_close - bid_close) / 2`
   in price units. The ladder's existing step prices a buy at reference + half-spread and a sell at
   reference - half-spread, so with a mid reference the buy pays the ask and the sell gets the
   bid. The simulator does not know which of the two quotes a market order met, so it assumes the
   wider one (AGENTS.md section 1.4).
3. **A missing, partial or crossed quote raises** `DataQualityError` naming the symbol and
   timestamp; there is no fallback to the mid, to zero, or to an earlier quote. A zero bid is a
   valid one-sided book and gives a wide spread. A `quoted` run on a dataset without the columns
   is refused at run start, before the quality gate, so nothing is created.
4. **The I5 fill range is `[low, high]` widened to the bar's quotes** when it carries all four
   (`BarEvent.fill_range()`), used by the aggressive-fill clamp and by `validate_fill_within_bar`.
   Measured reason: Polymarket bars are mids, and a one-tick bucket has `high == low == mid`, so
   clamping to `[low, high]` would erase the whole spread (in the end-to-end fixture the quoted
   and mid runs would be identical). A taker meeting the ask can legitimately trade above the
   traded range. This is the more pessimistic choice (fewer clamps).
5. **Limit orders on a quoted bar are measured against the quote a taker meets**, not the mid
   (found in review: a buy limit at mid + 0.001 would otherwise have filled at the mid with the
   ask 2 cents higher): the open price is the open ask for a buy and the open bid for a sell, and
   the through-check uses the lower of the two asks (buy) or the higher of the two bids (sell).
   Bars without quotes are unchanged.
6. **Settlement bars carry `bid = ask = price`** (a settlement is a print, not a market, so it
   charges no spread); **spot bars carry null quotes**, so trading the spot symbol under `quoted`
   raises and names it.
7. **`QuoteConsistency` quality check** (null, or all four present with `0 <= bid <= ask` and
   `ask > 0`) runs only on frames that carry the columns, so the `quality_checks_ran` list of
   every existing run manifest is unchanged.
8. **Checkpoint `SCHEMA_VERSION` 4 to 5**: `BarEvent` is serialized, so its new fields change what
   a checkpoint writes. Old checkpoints are refused with the existing version message.
9. **Refused combinations**: the vectorized engine (no Level 2+ models at all); null tests (their
   transforms rebuild bars with `BAR_SCHEMA`, dropping the quotes), refused before the real run so
   no artifacts or trial are recorded; and a scenario that sets a quoted spread on a store without
   quotes, refused before the base run.

## Alternatives considered

- **A separate quotes dataset joined point in time** (like `fx_rates`). Most general (tick-level
  quotes) but needs a new contract, feed event and engine wiring; deferred until Level 5.
- **A per-bar spread column with the mid kept as the price.** Loses which side is empty or stale
  and cannot represent a one-sided book.
- **Taking the close quote only.** Less pessimistic; rejected because the open quote is the one an
  open-referenced fill meets.
- **Keeping the `[low, high]` clamp.** Makes the model inert on the bars it was built for.
- **Registering the check in `DEFAULT_BAR_CHECKS`.** Changes `quality_checks_ran` for every run.

## Consequences

- A Polymarket strategy can now be run at Level 2 with `spread: quoted`
  (`examples/real_data/polymarket_up_quoted.yaml`); Level 1 results still assume mid fills and the
  data docs say so.
- Stores rebuilt from the Polymarket importers have extra columns, hence new dataset hashes and
  experiment ids; existing stores, config hashes and golden fixtures are unchanged.
- Limit orders on quoted bars use the ask/bid touch (decision 5); stop triggers still use the mid;
  no queue model; the venue backend reuses the same model, so paper and backtest match (I14).
- Deferred: tick-level quotes and queue position (Level 5), quote-aware stop triggers, quotes in the
  vectorized engine. The wider fill range also applies to `static`/`dynamic` spreads on a
  quote-carrying store (more pessimistic, never less).
