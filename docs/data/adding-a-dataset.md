# Adding a dataset (instructions for agents)

Follow this when AGENTS.md section 14 sends you here: a user gave you a data file or folder and
`docs/data/README.md` has no page for it. Work in the order below. Do not skip steps and do
not re-ingest a source that already has a page.

Never write to the raw location. Output goes to `data/processed/` (gitignored). If a step
would overwrite an existing dataset, delete files, or read a very large source
(the 42M-row Polymarket file is the scale to beware of), stop and ask the user first.

## 1. Inspect the raw source (read only)

Record, for every file kind: path, size, row count, columns and types, delimiter, first and
last timestamps, sample rows. Then answer each question below; write the answers down, they go
in the data page. If an answer is not in the file and not given by the user, **ask the user**
or record it as an explicit assumption. Never guess silently.

| Question | Why it matters | Where it goes in the spec |
|---|---|---|
| Are prices raw or adjusted for splits/dividends? Compare one known ticker/date against a real price. | Adjusted data is not raw data; dividends may already be inside the prices. | `price_basis: raw` or `adjusted` (required, no default) |
| What does the timestamp mean: bar open, bar close, or a trading day? | Using an open stamp as a close is look-ahead. | `timestamp.meaning` |
| Which timezone are the timestamps in? Any daylight saving? | Wrong zone shifts bars. | `timestamp.timezone` |
| Which symbol(s)? A column, the file name, or one fixed symbol? | | `symbol` |
| Nulls, duplicates, OHLC-bound violations (`high < max(open, close)`, `low > min(open, close)`), zero or negative prices, NaN, gaps? | Each is a data-quality decision. | `rows`, `quality_skip` |
| Does the market follow an exchange calendar (equities), run 24/7, or 24/5? | Decides the calendar checks. | `timestamp.calendar`, `quality_calendar`, `quality_skip` |

Useful one-liners: `uv run python -c "import polars as pl; print(pl.read_csv(PATH, separator=';', n_rows=5, infer_schema=False))"`
and `pl.scan_parquet(PATH).select(pl.len()).collect()`. Print with `PYTHONIOENCODING=utf-8` on
Windows.

## 2. Pick the importer

| Source | `kind` |
|---|---|
| OHLCV bars in CSV files (any delimiter, one or many files) | `ohlcv_csv` |
| Polymarket five-minute BTC contracts, CSV with a `winner` column | `polymarket_csv` |
| Polymarket ticks in Parquet plus an outcomes Parquet | `polymarket_parquet` |
| Anything else (Parquet OHLCV, another vendor, fundamentals) | not supported: see section 6 |

## 3. Write the spec

Copy the closest file in `examples/imports/` to `examples/imports/<source>.yaml`. Start it
with a comment naming the raw path and every assumption. Unknown keys are refused. Paths with
spaces go in single quotes.

### `ohlcv_csv` fields

| Field | Meaning |
|---|---|
| `dataset` | Output dataset id, e.g. `equities_daily_v1`. Bump the suffix when the meaning changes. |
| `input` | Glob of CSV files; read in sorted order. Must match at least one file. |
| `price_basis` | `raw` or `adjusted`. Required. Recorded in the manifest. |
| `delimiter` | One character; default `,`. |
| `columns` | Names of `timestamp, open, high, low, close` and optional `volume` (a missing volume becomes 0). |
| `symbol` | Exactly one of `column: NAME`, `from_filename: true`, `fixed: SYMBOL`. Upper-cased. |
| `timestamp.format` | strptime pattern, e.g. `"%Y-%m-%d"`, `"%Y.%m.%d %H:%M"`. A `%z`/`%Z` format needs `timezone: UTC`. |
| `timestamp.timezone` | Zone of the file's stamps; default `UTC`. An ambiguous or non-existent local time (daylight saving) refuses. |
| `timestamp.meaning` | `bar_open` (needs `interval`), `bar_close`, or `session_close` (needs `calendar`). |
| `timestamp.interval` | `15m`, `1h`, `1d`, `1w`, `1mo`, ... (bar_open only). Days, weeks and months are added in the file's zone. |
| `timestamp.calendar` | An `exchange_calendars` name such as `XNYS` (session_close only; not `24/7`). Each date maps to that session's close; a date that is not a session is dropped and counted. |
| `feed_latency_s` | `available_at = event_time + latency`; default 0. |
| `rows.on_incomplete` | `drop` (default, counted) or `refuse`. |
| `rows.ohlc_repair` | `refuse` (default: the quality battery refuses violating rows) or `clamp` (`high = max(o,h,l,c)`, `low = min(o,h,l,c)`, counted). Choose `clamp` only after looking at the violations. |
| `rows.max_dropped_fraction` | Refuse when dropped plus repaired rows exceed this share of rows read; default 0.05. |
| `quality_calendar` | Calendar for the coverage check when `meaning` is not `session_close`. |
| `quality_skip` / `quality_skip_reason` | Checks to skip, e.g. `[calendar_coverage]`, with a written reason (required when skipping). |

### Polymarket fields

`dataset`, `input`, `outcomes` (parquet only), `bar_seconds` (default 1), `window_seconds`
(default 300), `settlement_floor` (default 0.001), `spot_source` (`binance|coinbase|kraken`,
parquet only), `spot_symbol` (default `BTCUSD`), `max_dropped_fraction` (default 0.30). See
`docs/data/polymarket-btc5m-csv.md` for what the bars and settlement mean.

## 4. Build and check

```bash
uv run crucible data build examples/imports/<source>.yaml --store data/processed
uv run crucible data check --store data/processed --dataset <id> --calendar <XNYS|24/7> \
    [--skip calendar_coverage --skip-reason "<same reason as the spec>"]
```

Polymarket only: `--start`, `--end` (contract window start), `--max-contracts N`. All kinds:
`--max-rows N` (default 5,000,000).

The build prints one line per dataset (rows, hash prefix, and the manifest `source` with the
price basis and counts). The quality battery runs before anything is written; on a refusal
nothing is created. Build twice into two stores when you change the importer: the outputs must
be byte-identical.

### When it refuses

Never loosen a guard just to make it pass. Read the message, look at example rows, decide, and
record the decision in the data page.

| Refusal contains | Meaning | What to do |
|---|---|---|
| `price_basis` / `unknown kind` / unknown key | Bad spec | Fix the spec. |
| `matched no files` | `input` glob wrong | Check the path and quoting. |
| `missing column(s)` | Column name differs | Use the file's exact header. |
| `unparsable timestamp` / `unparsable number` | Format or a bad cell | Fix `timestamp.format` or the delimiter; do not clean the raw file. |
| `ambiguous or non-existent local time` | Daylight-saving hour | Ask the user for UTC data or a zone without DST. |
| `max_dropped_fraction` | Too many rows dropped or repaired | Inspect the counts; raise it only with a documented reason. |
| `ohlc_bounds` | High/low do not cover open/close | If the violations are noise, set `rows.ohlc_repair: clamp`; otherwise ask. |
| `sorted_unique_event_times` | Duplicate (symbol, bar) rows | Find the duplicates (several files for one symbol?) and ask the user which to keep. |
| `positive_prices` | Zero or negative price | Ask; these are usually bad rows, not to be dropped silently. |
| `calendar_coverage` | The data lacks sessions the calendar has | Real gap or a 24/5 or windowed market. If expected, `quality_skip: [calendar_coverage]` with a reason; if not, ask. |
| `--max-rows` / `no snapshot` / `no contract` | Too big, or a wrong unit or winner column | Select a window (`--start/--end/--max-contracts`) or fix the spec. |

## 5. Document it

Create `docs/data/<source-name>.md` (copy the structure of `equities-daily.md`): raw source and
where it came from, dataset ids, schema, known issues (adjusted prices, unverified timezone,
missing sessions, ...), a cleaning table with the real counts from the build (rows read,
dropped by reason, repaired by reason, written), and the exact re-run command. Add a row to
`docs/data/README.md`. Keep the spec's header comment and the page consistent. Add the new
spec to the expected count in `tests/unit/test_import_example_specs.py` (it loads every spec
in `examples/imports/`), then run `uv run pytest tests/unit/test_import_example_specs.py`.

Commit the spec, the test change and the page together (`git add` the specific files; the
built data is gitignored).

## 6. When the format is not supported

Add an importer; do not hand-write a one-off script.

1. Add a spec model to `crucible/data/importers/spec.py` (new `kind`, frozen, `extra="forbid"`,
   risky choices without defaults) and register it in `_MODELS`.
2. Write `import_<kind>(spec) -> ImportResult` in a new module beside `ohlcv.py`. Produce
   `BAR_SCHEMA` frames (`crucible/data/contracts.py`); `event_time` is when the bar closed and
   `available_at` is when a participant could first know it; count every drop and repair in the
   `ImportReport`; refuse (`ConfigurationError`) when nothing survives, on unparsable input, and
   above `max_dropped_fraction`.
3. Dispatch it in `build_from_spec` (`importers/build.py`). The quality battery, size guard,
   manifest source string and `import_report.json` come from there.
4. Tests first, with small hand-made files under `tmp_path` and hand-computed expected values
   (see `tests/unit/test_import_ohlcv.py`): timing, each drop reason, each refusal, determinism.
5. Update `docs/modules/data.md`, the ADR-0052 list of kinds (or a new ADR if the decision is
   not obvious), and this page.

Fundamentals, news and filings have no dataset contract yet: adding one is a design task
(spec, ADR), not an import task. Stop and ask the user.
