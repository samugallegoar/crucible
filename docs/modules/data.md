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
- `transforms.py` — the null-test bar transforms (`shuffle_bar_returns`, `shuffle_intrabar_returns`,
  `shuffle_overnight_gaps`, `sign_flip_returns`, `synthetic_gbm_like`; `BarComponents`,
  `decompose`, `reconstruct`).
- `importers/` — spec-driven `ohlcv_csv`, `databento_dbn`, `polymarket_csv`, `polymarket_parquet`
  importers behind `crucible data build`.
- `continuous.py` — continuous futures series from raw per-contract bars (ADR-0086):
  `build_continuous`, `build_continuous_datasets`, `write_continuous`, `RollParams`,
  `trade_dates`, `calendar_for`, `outside_calendar`, `dataset_names`; behind
  `crucible data continuous` (`--trim-to-calendar`, ADR-0092).
- `integrity.py` — the minute-level integrity report (`integrity_report`, ADR-0088): per symbol and
  session, bars, minutes absent inside the session's span, largest hole, short and weekend sessions,
  contract violations (`ok`), optional session-date comparison with a calendar; behind
  `crucible data integrity` and the MCP tool `crucible_data_integrity`. Read-only.
- `resample.py` — causal resampling of a continuous futures series (ADR-0100):
  `resample_session_bars(bars, *, calendar, minutes, source_seconds=60)` aggregates a one-minute
  `CONTINUOUS_BAR_SCHEMA` series into 5- or 15-minute bars and returns a `ResampleResult`
  (`bars`, `dropped_off_schedule`, `buckets`, `partial_buckets`). A bucket is the half-open interval
  of bar ENDS `(k·m, (k+1)·m]` on the UTC clock within ONE scheduled segment, so it never spans the
  maintenance break, a halt or a session boundary; its label is its end clipped to the segment's
  scheduled close (a segment open/close off the grid gives a shorter first/last bucket, flagged
  `partial`). OHLCV is first/max/min/last/sum with a `bars` count of constituents,
  `available_at = max(label, last constituent's available_at)`, an empty bucket produces no row, an
  off-schedule bar is dropped and counted, and a bucket holding two contracts is refused. Any other
  `minutes` is refused (1m is the source series, not a resample). Used by a futures run whose
  `fidelity.resolution` is `5m` or `15m`, for the execution AND the signal series (same buckets).
- `futures_specs.py` — the versioned futures contract specification table (ADR-0090): per root the
  tick size, point value and tick value, currency, exchange, source and effective date range
  (`FuturesContractSpec`, `SPEC_TABLE`, `futures_spec`, `spec_table_document`, `spec_table_hash`).
  ES, NQ, YM, RTY, NKD; values supplied by the owner, tick grids verified on every raw bar.
- `catalog.py` — the dataset registry (`dataset_catalog`, `parse_source`, ADR-0089), derived from
  each manifest and data file at query time: identity, origin and root origin (the provider),
  price basis, lineage through `from=<dataset>@<hash>`, data contract, range (first/last
  `event_time`, symbols); errors (manifest vs file, `--verify` checksum) and findings (rebuilt or
  missing parent, superseded continuous builder). Behind `crucible data catalog` and the MCP tool
  `crucible_data_catalog`. `ParquetDataStore.data_path` gives it the file path; rows are still read
  only through `read(as_of)`.
- `calendars.py` also holds `ExchangeCalendarAdapter.session_dates` and the Chicago
  wall-clock <-> UTC ns
  converters `chicago_wall_to_utc_ns` / `utc_ns_to_chicago_wall` (refuse DST-ambiguous times).
- `cme_sessions.py` + `cme_session_table.py` — the CME Globex session calendar of the equity-index
  futures (ADR-0091). The table: regimes, per-trade-date overrides, no-trade dates, unsourced
  windows, unscheduled events and the cited sources with SHA-256s, versioned
  (`cme-equity-sessions-1`) and hashed (`table_summary`). The logic: `SessionCalendar` (scheduled
  segments per trade date, `verified` flag, validation that refuses contradictions),
  `assign_bars` / `trade_date_of` (bars by their end into sessions), `session_rule_masks`
  (`flat_by_close`, `exit_at`, `entry_window` on the trade-date clock; `on_schedule`,
  `missing_final`, `unverified`) and `schedule_report` (observed bars vs the schedule; validates,
  never defines). Coverage ES/NQ/YM 2010-06-07, RTY 2017-07-10, NKD 2012-11-19, to 2027-12-31.
- `providers/` — price providers behind one interface (`PriceProvider`, ADR-0063): the `tiingo` and `yfinance`
  adapters, and `fetch.py` behind `crucible data fetch`, the shared normalizer, settings (API keys),
  HTTP retry and the raw-response cache. See "Data providers" below.
- `econ_events.py` — the economic-event calendar `econ_events_v2` (ADR-0107 section 12): the release
  instants of every FOMC policy statement (scheduled meetings *and* intermeeting actions), of every
  FOMC press conference the Fed held (dated to its meeting's day: **no page states its hour**), of
  the release of each meeting's minutes, of the BLS Consumer Price Index, Producer Price Index and
  Employment Situation releases, 2010-01-01 to the last date the sources publish, built from raw
  snapshots of federalreserve.gov and bls.gov (`docs/data/econ-events.md`). `ECON_EVENT_SCHEMA` /
  `ECON_EVENT_SORT_KEYS`, the parsers `parse_fomc_statement` / `parse_fomc_calendar` /
  `parse_fomc_historical` / `parse_fomc_press_conference` / `parse_bls_schedule`,
  `events_from_snapshots` (the assembly, where an earlier snapshot of a schedule turns a release
  `rescheduled` or `cancelled`), `build_econ_events(raw_dir, store_root, *, version=2)` (it refuses
  to overwrite a stored dataset; `version=1` still builds `econ_events_v1`, whose rows it
  reproduces), `load_econ_events(store, event_types, start_ns, end_ns, *, as_of=None)` (reads with
  the open-ended sentinel: a calendar is a firm-rule constraint, not a strategy signal),
  `coverage(store)` / `coverage_of(frame)` (the covered intervals and the gaps per event type),
  `day_only_events(frame)` (the rows whose hour no source states) and `fetch_raw` (the ingestion,
  which discovers the statement and press-conference pages from the Fed's own pages and writes
  `MANIFEST.json`). This is **not** market data and the futures vault guard does not cover it.
- `exchange_fees.py` — the per-side, per-contract fee table `exchange_fees_v1` a prop-firm run
  charges on top of commission (`docs/data/cme-exchange-fees.md`): `EXCHANGE_FEE_SCHEMA` /
  `EXCHANGE_FEE_SORT_KEYS`, `parse_nfa_assessment` (the NFA Bylaw 1301 assessment fee, halved from
  the round-turn amount and split at the period the bylaw states), `load_owner_provided_csv` (the
  only route an **exchange** fee has into the dataset: a supplied file, with its SHA-256, its
  supplier and the exact cell text as evidence), `fetch_raw` (NFA only — it fetches no CME Group
  bytes, on purpose), `build_exchange_fees` (refuses to overwrite; its `BuildReport` names the roots
  no exchange fee priced) and `fee_table_as_of(store, date)` (exchange + NFA per side for every root,
  which **refuses** while a root is unpriced rather than pricing an unknown fee at zero).
  `coverage_of(frame)` states the covered intervals; `FEE_CLASS_EXCHANGE` is the assumed customer
  rate class.
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
  rows, never fabricated. A revised observation (same `event_time`, later
  `available_at`) is one observation: `get` and `history` return the latest
  version available at `as_of` (before ADR-0071 `history` returned every
  version, counting a revision twice). Boundary: `available_at == as_of` is
  visible, one nanosecond later is not.
- **What "point-in-time" covers (ADR-0071).** Four separate things:
  *query-time restriction* — the clock guard and the `available_at <= as_of`
  filter inside every read, enforced in code and tested (`tests/lookahead/`,
  `tests/unit/test_pit_accessor.py`); *availability timestamps* — the
  `available_at` values a dataset carries, trusted as given (a provider's
  adjusted daily bar is stamped at its session close, not at the date the
  adjusted value was computed); *version integrity* — **not provided**: the
  store keeps one version per dataset name (the one-step flow archives the
  versions it replaces, `product.data`), so it cannot reconstruct the
  information set of a past date; *price basis* — declared by importers and
  providers in the manifest `source` (`price_basis=raw|adjusted`, read by
  `price_basis_of`), recorded in every run manifest as `bars_price_basis`
  (`undeclared` when the dataset does not say).
- `store.py`: `ParquetDataStore.refuse_dividends_on_adjusted_bars` — the
  engine refuses adjusted bars together with a corporate-actions dataset that
  holds cash dividends (each would be counted twice); a dataset with an
  undeclared basis cannot be checked (ADR-0071).
- `calendars.py`: `canonical_calendar(name)` — one name per set of sessions
  (`"24/7"` or the `exchange_calendars` code after alias resolution; unknown
  names refused), used for dataset identity (ADR-0071).
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
- `transforms.py`: null-test bar transforms (ADR-0019, ADR-0070) —
  `shuffle_bar_returns` (whole bars after the first: the multiset of
  close-to-close returns and the final close are preserved exactly),
  `shuffle_intrabar_returns` (intraday shapes only, gaps stay on their
  dates), `shuffle_overnight_gaps` (gaps only), `sign_flip_returns` (gap
  and intraday return negated), `synthetic_gbm_like` (i.i.d. normal
  close-to-close returns matched to the real mean/stdev). The module
  docstring tabulates what each preserves and destroys.
  Each decomposes a symbol's bars into per-bar components
  (overnight `gap = open[k]/close[k-1] - 1`, `intrabar_return`,
  non-negative `high_wick`/`low_wick`, `volume`), transforms only what that
  null test targets, then rebuilds `open[k+1] = close[k] * (1 + gap[k+1])`
  from the real first open and reapplies the wick fractions. (Before
  ADR-0070 the rebuild was `open[k+1] = close[k]`, which dropped every
  overnight gap: on AAPL 2009-2025 the gapless series compounds at 11.3 % a
  year against 26.8 % close-to-close, so the old shuffle null had less than
  half the real drift.) Every
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

## Holdout vault (C6c, ADR-0105)

`vault.py` is the data-layer lock on the declared protected period of the futures family. It is
consulted by `ParquetDataStore.read` and `ParquetDataStore.data_path`, so no run, batch,
walk-forward, CLI command, MCP tool or plain library call reaches a protected row by accident.

- `VaultDeclaration` / `load_declaration` / `declare_vault` / `write_declaration` — the declaration
  (`vault.json`: `vault_id` `VLT-<16 hex>`, `universe`, `start_trade_date`, `end_trade_date: null`,
  `scope` `family`|`root`, `declared_at`, `audit_ref`, `protected_datasets`). It is written into the
  STORE ROOT and into the CRUCIBLE HOME and enforced if EITHER copy exists; two copies that disagree
  on the locked period are refused, not reconciled. A declaration can only be WIDENED (an earlier or
  equal start, a superset universe, no end date, no `family` -> `root` narrowing).
- `first_protected_session` / `vault_start_ns` — the instant the vault starts: the scheduled OPEN of
  the first protected Globex trade date, from the CME session table of each declared root (the
  earliest of them). For `start_trade_date = 2025-01-01` that is 2024-12-31T23:00:00Z, the 17:00 CT
  open of trade date 2025-01-01. Never derived from observed bars.
- `VaultGuard` (`load`, `check_read`, `check_path`, `protects`) — a read whose `as_of` reaches
  `vault_start_ns` raises `VaultLockedError`; `data_path` (a whole file) is refused unless the
  purpose is `metadata` (catalog and integrity tooling: counts, hashes and date bounds, logged) or an
  evaluation session is active. A `metadata` READ is clipped below the vault start, so a report can
  be produced and no protected row leaves the vault. `dataset` matching is by ROOT (id prefix
  `<root>_`, or a manifest that names the root), never by trial family.
- `VaultSession` / `open_vault_session` / `close_vault_session` / `current_vault_session` — the one
  exception, set ONLY by the authorized evaluation (`experiments.vault.evaluate`). Inside it a read
  is admitted only for the registered datasets, only up to the registered window end; anything else
  is refused.
- `AccessLog` / `DuckDbAccessLog` / `MemoryAccessLog` / `AccessLogEntry` — every attempt on a
  dataset of a protected root, allowed or refused, is appended to `<home>/vault.duckdb`
  (`access_log`, chained hashes). Reads of unrelated datasets are neither locked nor logged.
- `refuse_protected_window` — the explicit, config-level refusal a run/batch/walk-forward calls
  first, so the message names the window before a single row is read (the guard is the enforcement,
  this is the good error).
- `default_guard` / `clear_guard_cache` — the guard of a store root and home, cached by the
  declarations' `(mtime, size)`: a store with no declaration pays two `stat` calls and nothing more.
- `home_root` — the home the guard reads and logs to, resolved in the ADR-0068 order
  (`CRUCIBLE_HOME`, the settings file's `home`, the platform default). It is duplicated from
  `product.home` because `crucible.product` sits ABOVE `crucible.data` in the layering rule and a
  library call must reach the guard; `tests/unit/test_vault_guard.py` pins the two to agree.

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

**Databento futures (ADR-0085).** `importers/databento.py` (`kind: databento_dbn`, optional extra
`databento`) reads `ohlcv-1s|1m|1h` DBN files into one raw dataset per root, symbol = individual
contract with its expiry year (`ESH2024`). `event_time` is the bar *close* (Databento stamps the
open), `available_at` adds `feed_latency_s`; spreads and other products are dropped and counted;
`instrument_id` is resolved **by date** (the provider reuses ids); `expected_sha256` verifies the
provider's checksum before reading; prices are raw. `DbnSource` is the seam tests use. Counts and
the re-run command: `docs/data/glbx-futures-1m.md`.

**Continuous futures (ADR-0086).** `continuous.py` turns the raw per-contract bars of a root into
three datasets: `{root}_1m_cont_v3` (the held contract's own bars, a `contract` column, real prices,
`price_basis=raw`; the only series fills and money are computed on), `{root}_1m_cont_ratio_v3`
(every earlier bar multiplied by the compounded `next / front` ratio, `price_basis=adjusted`; safe
only for scale-invariant use) and `{root}_1m_rolls_v3` (one row per roll: contracts, effective
trade date, `decided_at`, reference minute and prices, `ratio`, `gap_points`, `reason`). The roll is
causal: hold one contract, look only at its successor in the quarterly chain, switch from the
first bar of trade date `d` when the successor's volume on `d-1` exceeds `threshold` x the held
contract's, or when the held contract is in its final session (`backstop_sessions`); never switch
back. Trade date = the CME session calendar's (ADR-0092): the session whose scheduled
segment holds the bar, an off-schedule print the last session that opened before it; raw bars
outside the calendar's coverage are refused or, with `trim_to_calendar`, dropped and counted
(`trimmed_rows` in the manifest, with the calendar version and hash).
A contract still trading on the dataset's last session has no observed expiry, so no backstop
applies. Refusals: a symbol that is not a root contract, a chain with a hole, a roll whose
contracts never shared a traded minute. Parameters are in each manifest's `source`; a rebuild
reproduces the content hashes. Schemas: `docs/SCHEMAS.md` (`CONTINUOUS_BAR_SCHEMA`,
`ROLL_SCHEMA`).

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
  counted (a bar still forming at fetch time is `not_closed`; an intraday bar never ends after its session's close), an OHLC violation is left to the quality battery unless `ohlc_repair="clamp"` (every violation) or `"clamp_rounding"` (only a violation within `ROUNDING_TOLERANCE` = 1e-6 of the close, which is float noise of an adjusted series; a larger one is still refused; ADR-0068).
- `settings.py` — API keys and the default provider from the environment and `.env` (the environment
  wins); `ApiKey` is masked in every `repr`/`str`. `http.py` — GET with bounded retry and backoff and typed
  errors over stdlib `urllib`; credentials go in headers only. `cache.py` — raw responses for ranges that
  ended before today. `registry.py` — name to adapter factory.
- `tiingo.py` — Tiingo end-of-day bars, `raw` and `adjusted`, daily only (its IEX intraday timestamps are
  undocumented, so it is not offered); needs `TIINGO_API_KEY`.
- `yfinance.py` — Yahoo Finance via the `yfinance` package (a core dependency, imported lazily), no key,
  `adjusted` only, daily and intraday (about 60 days). Unofficial: it can break or be rate-limited.
  Yahoo re-computes the adjusted series after every later dividend or split, so it is **not
  point-in-time**: a past bar's price depends on the download date (ADR-0070).
- Price basis: Tiingo supplies both `raw` and `adjusted`. A provider that cannot honestly supply a basis
  refuses it rather than mislabel (Yahoo's `Close` is split-adjusted, so it will offer `adjusted` only).

## Known gaps
- The CME session calendar (ADR-0091) leaves unsourced the 2023 holidays other than Labor Day,
  Christmas and New Year, Martin Luther King Day 2024, and NKD on the 2023-2025 holiday dates
  taken from ES-only captures; those sessions are built from the regime and flagged unverified.
  It covers the five equity-index roots only, and NKD only from trade date 2012-11-19: the
  `nkd_*_v3` continuous datasets start there (314,040 earlier raw bars trimmed, ADR-0092).
- Continuous futures take a contract's scheduled last session from its last observed bar (ADR-0086,
  decision 2): exact for liquid contracts, an approximation for thin ones; a contract specification
  table replaces it. `CMES` is used for session dates only: it models a 24 h block with no
  maintenance break or early closes (ADR-0087, ADR-0088). The roll cost at each roll is not charged
  yet (milestone C3).
- A resampled (`5m`/`15m`) series is a READING, not a dataset: `resample_session_bars` builds the
  bars a run simulates but writes nothing to the store, so a resolution is rebuilt on every run and
  a run's identity covers the config, not a stored aggregate. A fidelity run whose sessions would
  produce a `partial` bucket is refused (`experiments.futures_run._resampled`): the session rules
  are evaluated on a bar grid anchored at the scheduled open, and no CME session of the current
  table opens or closes off a 5- or 15-minute boundary.
- The integrity report cannot tell a minute with no trade from a minute the source lost (Databento's
  OHLCV-1m omits empty minutes); it reports the absent minutes and leaves the judgement to the caller
  (ADR-0088).
- The catalog's lineage stops at the import: importers do not record the raw file's path or hash, so
  the raw source is documented in `docs/data/` only. The range is scanned from the data on every
  query (about 36 s for the whole real store on a cold disk cache; ADR-0089).
Provider adapters: `tiingo` and `yfinance` exist (ADR-0063). `data fetch` takes the provider from a flag or the environment, not from a spec file; intraday Tiingo is not offered.
Missingness reason column (ADR-0005) is not materialized — bars are
dense by construction. Abnormal-jump and tz-mismatch checks pending.
Corporate actions beyond cash dividends and delisting unhandled (engine raises on them).
No versioned (bitemporal) storage: a dataset name holds one version, so past information sets
cannot be reconstructed; adjusted provider prices are re-computed after the fact and are a
research series, not executable historical quotes (ADR-0070, ADR-0071).
Importers: fundamentals/news/filings have no dataset contract; adjusted equity
prices are imported labelled, not converted to raw; Polymarket bars hold the mid
plus bucket quotes (ADR-0060; limit fills and tick-level quotes are not
quote-aware); no Parquet input for the generic OHLCV importer. Accepted behaviours (decided, not
oversights): a Polymarket loser settles at `settlement_floor` (0.001), not 0, because the quality
battery needs positive prices; an order placed on a contract's last bar fills at the settlement print
(1.0 or the floor, no spread), which gives a buyer no edge since the print is the payoff.
`exchange_calendars` is an untyped boundary (mypy override in pyproject).
- **No exchange fee is stored** (`exchange_fees.py`, `docs/data/cme-exchange-fees.md`): CME Group
  refuses automated access under its website Data Terms of Use and its published fee schedule names
  product *buckets* ("E-mini Equity Index", "Micro E-mini Index"), never a root ticker, so a per-root
  exchange fee would be an inference. `exchange_fees_v1` therefore holds the NFA assessment fee only,
  `BuildReport.exchange_roots_missing` lists all nine roots, and `fee_table_as_of` raises for every
  date until the owner supplies a fee file (`load_owner_provided_csv`). The NFA rows start at
  2026-07-01 (the bylaw states the current rate and its period, not earlier ones) and the assumed
  exchange `fee_class` (`non_member_customer`) needs confirming against the firm's clearing
  agreement.
Economic events (`econ_events.py`): every row is `available_at = event_time` because no page states
when its own schedule entries were first published, so a point-in-time read hides an event until it
happens — the dataset serves firm rules, never signals (ADR-0107 section 12). 58 FOMC statement rows
(2010-2015 plus 10 announced-but-unreleased meetings) state a date but no hour; so do all 96 press
conferences (the Fed never states a press conference's hour in HTML) and 44 of the 135 minutes
releases (only a meeting's press-conference page states the 2:00 p.m. hour). The October 2013
shutdown's original BLS dates are not recorded (no pre-shutdown capture of that page exists in the
Internet Archive). Notation-vote statements are read only when labelled "Statement"; joint
Treasury/Fed announcements are not FOMC statements and are absent. `econ_events_v1` is kept as
built; `econ_events_v2` adds the press conference, the minutes and PPI, and reproduces every v1 row
unchanged (`dataset_version` apart).
