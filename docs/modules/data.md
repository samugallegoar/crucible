# Module: data

## What exists

Datasets, point-in-time access, calendars and quality. Detail sections follow.

- `contracts.py` — `BAR_SCHEMA`, `UNIVERSE_SCHEMA`, `CORPORATE_ACTION_SCHEMA`, `FX_RATE_SCHEMA`
  and their sort keys (columns in `docs/SCHEMAS.md`).
- `store.py` — `ParquetDataStore` (as-of reads only) and `build_dataset` (deterministic writes +
  manifests). `pit.py` — `StorePITAccessor`, the information barrier (`LookaheadError`).
- `universe.py` — `TableUniverseProvider`. `calendars.py` — `ExchangeCalendarAdapter`,
  `AlwaysOpenCalendar`, `get_trading_calendar`; the `TradingCalendar` Protocol.
- `quality.py` — the five checks of `DEFAULT_BAR_CHECKS` (`sorted_unique_event_times`,
  `positive_prices`, `ohlc_bounds`, `availability_not_before_event`, `calendar_coverage`; the
  names are the `data.quality_skip` keys) and `run_quality_checks`.
- `transforms.py` — the null-test bar transforms (`shuffle_bar_returns`, `sign_flip_returns`,
  `synthetic_gbm_like`).
- `importers/` — spec-driven `ohlcv_csv`, `polymarket_csv`, `polymarket_parquet` importers behind
  `crucible data build`.
- `providers/` — price providers behind one interface (`PriceProvider`, ADR-0063): the `tiingo` and `yfinance`
  adapters, and `fetch.py` behind `crucible data fetch`, the shared normalizer, settings (API keys),
  HTTP retry and the raw-response cache. See "Data providers" below.
- `interfaces.py` — `DatasetManifest` and the Protocols `PITAccessor`, `DataStore`,
  `UniverseProvider`, `TradingCalendar`, `QualityCheck`.

## Responsibility
Data contracts (`event_time` + `available_at` on everything), deterministic
Parquet store with manifests, point-in-time queries, universe membership,
calendars, quality checks.

## Implementations (ADR-0025/0026)
- `contracts.py`: `BAR_SCHEMA`, `UNIVERSE_SCHEMA`, `CORPORATE_ACTION_SCHEMA`
  + sort keys; `END_AT_OPEN` sentinel for open-ended membership.
  `CORPORATE_ACTION_SCHEMA.pay_at` (nullable) — required for
  `cash_dividend` rows (the ex-date/pay-date split, ADR-0026), unused for
  every other action type.
  `FX_RATE_SCHEMA` — shaped exactly like `BAR_SCHEMA` (`symbol`/
  `event_time`/`available_at` + `mid`/`bid`/`ask`), `symbol` holding a
  currency-pair code (`"EURUSD"` = "1 EUR = `mid` USD"). Deliberately
  reuses the bar shape rather than a bespoke schema so the existing
  generic `PITAccessor`/`ParquetDataStore` handle FX rates with zero new
  code — an FX rate is PIT data like any other.
- `store.py`: `build_dataset` (sorted, uncompressed Parquet + manifest.json
  with SHA-256 content hash — ADR-0011); `ParquetDataStore.read(dataset,
  as_of)` — the scan itself filters `available_at <= as_of`; there is no
  unfiltered read.
- `pit.py`: `StorePITAccessor.get/history` — guards `as_of <= clock.now`
  (`LookaheadError`, I8) before touching data. Absent symbols are absent
  rows, never fabricated.
- `calendars.py`: `ExchangeCalendarAdapter` (wraps `exchange_calendars`; the
  only tz-aware code besides I/O) and `AlwaysOpenCalendar` (24/7, UTC
  midnight closes); `get_trading_calendar(name, *, start, end)` factory ("24/7" or an
  exchange_calendars name). An exchange calendar covers the requested range padded by 366
  days, never `exchange_calendars`' date-dependent default window (ADR-0053). Both calendars implement
  `session_open_at(ts)`: the open of the session with `open <= ts <= close`
  (`None` outside any session; the 24/7 calendar's session is the day ending at
  the next midnight), used for the dividend ex-date cutoff (ADR-0046).
- `quality.py`: 5-check battery (sorted/unique event times, positive prices,
  OHLC bounds, `available_at >= event_time`, calendar coverage);
  `run_quality_checks` refuses skips without a reason.
- `universe.py`: `TableUniverseProvider.members(as_of)`; `end_at` exclusive.
- `transforms.py`: null-test bar transforms (ADR-0019) —
  `shuffle_bar_returns`/`sign_flip_returns`/`synthetic_gbm_like(bars, ...)`.
  Each decomposes a symbol's bars into per-bar shape features
  (`intrabar_return`, non-negative `high_wick`/`low_wick`, `volume`),
  transforms only what that null test targets, then re-chains
  `open[k+1] = close[k]` and reapplies the wick fractions — every
  reconstructed bar is valid (`high >= max(open,close)`,
  `low <= min(open,close)`) by construction, not by post-hoc repair.
  Raises `DataQualityError` if a transformed return would drive a price to
  zero or below. `event_time`/`available_at`/`symbol` and corporate
  actions/universe membership are never touched — only bar prices/volume.
  Consumed by `experiments/null_tests.py`, which re-runs the engine
  against the transformed data (a new `experiments` → `data` dependency
  this session first exercised for validation purposes).

## Extension points
New datasets = new contract schema + sort keys. New checks implement
`QualityCheck` and join `DEFAULT_BAR_CHECKS`. A new file format = a new
`kind` in `importers/spec.py` plus an importer returning an `ImportResult`
(`importers/report.py`); `importers/build.py` dispatches it. Step by step for agents:
`docs/data/adding-a-dataset.md`.

## Importers (ADR-0052)
`crucible/data/importers/`: `spec.py` (YAML models: `ohlcv_csv`,
`polymarket_csv`, `polymarket_parquet`; `price_basis` required; OHLC repair
opt-in), `ohlcv.py` (timestamp meanings `bar_open`/`bar_close`/`session_close`,
timezone conversion, counted drops and repairs), `polymarket.py` (UP/DOWN mid
bars, spot series, settlement bars plus `delisting` actions), `report.py`
(`ImportReport`, `import_report.json`, manifest `source` string) and `build.py`
(quality battery and size guard before writing, so a refusal writes nothing).
Timing: a bar is available at its close plus `feed_latency_s`; a Polymarket
snapshot only after its bucket ends. Pessimism: the price is the mid and volume
is 0 on Polymarket data; the bars also carry the bucket's first and last bid/ask
(`bid_open`, `ask_open`, `bid_close`, `ask_close`, `contracts.BAR_QUOTE_SCHEMA`,
optional on any bar dataset) so `spread: quoted` can fill at the quote (ADR-0060).
The `quote_consistency` check (null, or all four present with `0 <= bid <= ask`)
runs only on frames that carry the columns. Per-source facts and counts: `docs/data/`.

Importer guards (ADR-0052): a Polymarket snapshot whose `ts` is null or not finite is dropped and
counted `invalid_ts`; a missing or non-numeric `start_time` refuses naming the contract;
`unresolved_contract_rows` counts only contracts inside `--start/--end`; ties on `ts` inside a bucket
are ordered by the quotes so the bucket's first/last quote does not depend on row order. The OHLCV
importer refuses negative volume and files with no data rows, and reports blank volumes (turned into 0)
as `volume_zeroed` in the report's `extra`. `--max-rows` and `--max-contracts` must be 1 or more.
`QuoteConsistency` also refuses NaN and infinite quotes (`non_finite`).

## Data providers (ADR-0063)

`providers/` fetches prices from a free provider and normalizes them; **a run never calls a
provider**. A fetch writes a dataset with `build_dataset`, and runs name the stored dataset as today.

- `base.py` — the `PriceProvider` Protocol (`get_prices(symbol, start, end, interval, price_basis)`
  returning `BAR_SCHEMA` bars, and `fetch_bars` which also returns the drop/repair counts), `ProviderInfo`
  (name, key variable, intervals, price bases, official or not) and `BarsProvider`, the base class an
  adapter derives from: it validates the request, reads the raw cache, calls the adapter's `_fetch_raw`
  and normalizes.
- `normalize.py` — the one place a provider's raw frame (`ts`, `open`, `high`, `low`, `close`,
  `volume`) becomes `BAR_SCHEMA`: UTC ns, `event_time` = bar close (an exchange-calendar daily bar closes
  at the session close, a `24/7` daily bar a day after its open, an intraday bar at start + interval),
  `available_at = event_time + feed_latency_s`, sorted, de-duplicated; unusable rows are dropped and
  counted (a bar still forming at fetch time is `not_closed`; an intraday bar never ends after its session's close), an OHLC violation is left to the quality battery unless `ohlc_repair="clamp"`.
- `settings.py` — API keys and the default provider from the environment and `.env` (the environment
  wins); `ApiKey` is masked in every `repr`/`str`. `http.py` — GET with bounded retry and backoff and typed
  errors over stdlib `urllib`; credentials go in headers only. `cache.py` — raw responses for ranges that
  ended before today. `registry.py` — name to adapter factory.
- `tiingo.py` — Tiingo end-of-day bars, `raw` and `adjusted`, daily only (its IEX intraday timestamps are
  undocumented, so it is not offered); needs `TIINGO_API_KEY`.
- `yfinance.py` — Yahoo Finance via the optional `yfinance` package (`uv sync --extra yfinance`), no key,
  `adjusted` only, daily and intraday (about 60 days). Unofficial: it can break or be rate-limited.
- Price basis: Tiingo supplies both `raw` and `adjusted`. A provider that cannot honestly supply a basis
  refuses it rather than mislabel (Yahoo's `Close` is split-adjusted, so it will offer `adjusted` only).

## Known gaps
Provider adapters: `tiingo` and `yfinance` exist (ADR-0063). `data fetch` takes the provider from a flag or the environment, not from a spec file; intraday Tiingo is not offered.
Missingness reason column (ADR-0005) is not materialized — bars are
dense by construction. Abnormal-jump and tz-mismatch checks pending.
Corporate actions beyond delisting unhandled (engine raises on them).
Importers: fundamentals/news/filings have no dataset contract; adjusted equity
prices are imported labelled, not converted to raw; Polymarket bars hold the mid
plus bucket quotes (ADR-0060; limit fills and tick-level quotes are not
quote-aware); no Parquet input for the generic OHLCV importer. Accepted behaviours (decided, not
oversights): a Polymarket loser settles at `settlement_floor` (0.001), not 0, because the quality
battery needs positive prices; an order placed on a contract's last bar fills at the settlement print
(1.0 or the floor, no spread), which gives a buyer no edge since the print is the payoff.
`exchange_calendars` is an untyped boundary (mypy override in pyproject).
