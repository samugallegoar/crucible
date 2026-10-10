# Crucible

**A quant backtesting engine that makes it hard to fool yourself.**

Most backtests flatter the strategy: they peek at the future, fill at prices that never existed,
and report a headline Sharpe from the one run that happened to work. Crucible is built the other
way round. It enforces point-in-time data access in code, assumes the worse outcome whenever the
simulator cannot know, and refuses to report a headline metric without its confidence interval,
the number of trials behind it, the deflated Sharpe / overfitting probability and the realism
level. A strategy has to pass four gates before its performance is believed:

```
Data Integrity -> Signal Validity -> Execution Realism -> Statistical Validity
```

Runs are deterministic (identical inputs give byte-identical artifacts), resumable from a
checkpoint, and drivable by people, scripts and agents: every command has a JSON form and there is
an [MCP server](#use-it-from-an-mcp-client).

## Features

- **Event-driven engine, realism Levels 0-4.** Instant fills up to a spread/latency/slippage
  ladder with dynamic spread, square-root impact, per-share commissions, participation caps and
  quote-aware fills; market, limit, stop, trailing, bracket/OCO/OTO and TWAP/VWAP orders.
- **Point-in-time data.** Every read takes an `as_of` and filters `available_at <= as_of`; a
  poisoned-future test harness checks that strategies cannot see ahead. Parquet store with
  manifests and content hashes, exchange calendars, and a quality battery that runs before every
  run.
- **Accounting that holds its identities.** Ledger-derived portfolio, multi-currency with FX
  marking, shorts, margin and margin calls, borrow cost and financing, futures with daily
  mark-to-market and rolls, dividends, delistings, settlement lag. Identities are checked at run
  time (`docs/INVARIANTS.md`).
- **Statistical validation.** Deflated Sharpe, probability of backtest overfitting (CSCV), purged
  K-fold and walk-forward splits, Monte Carlo resampling, null tests (shuffled, sign-flipped,
  synthetic GBM), factor regression, sensitivity surfaces, contamination flagging and a trial
  registry that counts every run.
- **Fast path and promotion.** A vectorized engine (Levels 0-1) for research sweeps, with
  position episodes and parallel trial-counted sweeps; `promote` reruns the same signal through
  the event-driven engine under realistic friction, and the two agree on a frictionless setup.
- **Checkpoint / resume and live parity.** A resumed run equals the uninterrupted one; a paper
  runtime and a simulated-venue live runtime reproduce the backtest's orders and fills.
- **Data providers.** `crucible data fetch` pulls prices from yfinance (no key) or Tiingo (free
  key) into the dataset store; runs never call a provider.
- **Agent-friendly.** `--json` on every command, `--override PATH=VALUE`, `crucible schema`, and
  an MCP server exposing the commands as tools.

## Installation

Requires Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/samugallegoar/crucible.git
cd crucible
uv sync                       # core install
uv sync --extra yfinance      # optional: Yahoo Finance prices
uv sync --extra mcp           # optional: the MCP server
```

## Quick start

```bash
uv run python examples/momentum/build_data.py       # seeded synthetic dataset
uv run crucible run examples/momentum/config.yaml   # prints EXP-<id>
# open experiments/EXP-<id>/report.html
```

The report opens with the headline metrics, each with its confidence interval, next to the trial
count, DSR/PBO, contamination flag and realism level. Artifacts (`manifest.json`, `metrics.json`,
`equity.parquet`, `trades.parquet`, `ledger.parquet`, ...) are described in
[`docs/SCHEMAS.md`](docs/SCHEMAS.md).

## Usage

```bash
uv run crucible run examples/momentum/config.yaml --json             # one JSON document
uv run crucible run examples/momentum/config.yaml \
    --override strategy.params.lookback=90                           # edit a field before validation
uv run crucible optimize examples/momentum/config.yaml \
    --param lookback --values 40,60,80                               # a sweep: PBO and best-point DSR
uv run crucible run-vectorized examples/trend_demo/config_vectorized.yaml
uv run crucible compare momentum_daily_example                       # every recorded trial of a family
uv run crucible report EXP-<id>                                      # re-render a report
uv run crucible debug EXP-<id> --at 2020-06-01                       # deterministic replay to a time
uv run crucible schema                                               # JSON Schema of the config
```

From Python, see [`docs/USAGE.md`](docs/USAGE.md) (its code blocks are executed by the test
suite). Every command and option is listed in [`docs/INVENTORY.md`](docs/INVENTORY.md).

## Configuration

A run is one YAML file. The shipped `examples/momentum/config.yaml` is a good template:

```yaml
experiment: {name: momentum_daily_example, family: momentum_daily_example,
             mode: evaluation, seed: 182736, realism_level: 1}
data:       {store: examples/momentum/data, bars: momentum_bars_v1,
             calendar: XNYS, base_currency: USD}
strategy:   {entrypoint: "examples.momentum.strategy:Momentum", params: {lookback: 60, top_k: 2}}
execution:  {slippage_bps: 5.0, commission_bps: 2.0}
initial_cash: "1000000"
start: "2020-01-01"
end: "2022-01-01"
```

`crucible schema` prints every valid field. The config hash (and so the experiment id) covers the
whole config, which is what makes a result reproducible; what may change without breaking that is
in [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md).

## Data providers

`crucible data fetch` downloads prices, normalizes them to the engine's bar format, runs the
quality checks and writes a dataset. Backtests then run on the stored dataset as always: **a run
never calls a provider**, so results stay reproducible.

| | yfinance (default) | Tiingo |
|---|---|---|
| Key | none | free API key (`TIINGO_API_KEY`) |
| Official API | **no** (scrapes Yahoo Finance; it can break, return gaps or be rate-limited without notice) | yes |
| Bars | daily, and intraday 5m / 15m / 30m / 1h (Yahoo keeps about 60 days of intraday) | daily end-of-day |
| Prices | `adjusted` only (splits and dividends; Yahoo's close is already split-adjusted, so no true raw series) | `adjusted` and `raw` |
| Install | `uv sync --extra yfinance` | nothing extra |
| Free limits | informal, Yahoo throttles heavy use | 50 requests/hour, 1,000/day, 500 unique symbols/month |

Zero setup (yfinance):

```bash
uv sync --extra yfinance
uv run crucible data fetch --store data/processed --dataset spy_daily \
    --symbols SPY,QQQ --start 2020-01-01 --end 2024-12-31
```

Switching to Tiingo:

1. Create a free account at <https://www.tiingo.com> and copy the API token from your account page.
2. Copy `.env.example` to `.env` (git ignores it) and set `TIINGO_API_KEY=<your token>`. A real
   environment variable of the same name wins over `.env`. The key is sent in a request header and
   is never printed, logged or written to a dataset or report.
3. Pick the provider with `--provider tiingo`, or set `CRUCIBLE_DATA_PROVIDER=tiingo` in `.env`.
   Without a key the command stops and tells you these steps instead of crashing.

```bash
uv run crucible data fetch --provider tiingo --price-basis raw --store data/processed \
    --dataset spy_raw --symbols SPY --start 2020-01-01 --end 2024-12-31
```

Prices are `adjusted` unless you ask for `raw`, and the dataset records which (its manifest
`source` and `import_report.json` name the provider and the price basis). Answers for date ranges
that ended before yesterday are cached under `data/cache/providers` (`--refresh` re-fetches,
`--no-cache` skips the cache). Rate limits, network failures and empty answers stop with a message
saying what happened and what to try; if some symbols fail nothing is written unless you pass
`--allow-partial`. Details: [`docs/data/providers.md`](docs/data/providers.md).

To use your own files instead, see [`docs/data/adding-a-dataset.md`](docs/data/adding-a-dataset.md).

## Use it from an MCP client

`uv sync --extra mcp`, then point your MCP client at `crucible-mcp` (stdio). The tools run the same
commands as `crucible ... --json` (run, run-vectorized, validate, optimize, promote, debug,
compare, report, data list/check/build/fetch, schema) and return their JSON documents. Each call
runs in a fresh process, so editing a strategy between calls takes effect. Details:
[`docs/modules/mcp_server.md`](docs/modules/mcp_server.md).

## Project structure

```
crucible/        the library: core (engine, clock, events), data, orders, execution, portfolio,
                 accounting, risk, strategy, analytics, validation, vectorized, experiments,
                 live, cli, mcp_server
examples/        runnable strategies and configs; every example is also a test
tests/           unit, property (hypothesis), golden, integration, lookahead
tools/           documentation generators and the import-layering check
docs/            architecture, conventions, schemas, ADRs, one page per module
experiments/     artifact store (gitignored except reference manifests)
```

Where a change belongs: [`docs/WHERE_THINGS_GO.md`](docs/WHERE_THINGS_GO.md). The system as built,
with its layering rule: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Why it was built this way:
the decision records in [`docs/adr/`](docs/adr/README.md).

## Known limitations & future improvements

Crucible is a research and validation tool with a deliberately bounded scope.

- **No real broker connection.** The live runtime drives a simulated venue that reuses the backtest
  fill models; a vendor adapter is a possible next step. Level 5 (order-book replay, queue position,
  tick-level quotes) is not supported.
- **Instruments.** Equities, multi-currency symbols, futures and prediction-market contracts; no
  options. Corporate actions beyond dividends and delistings (splits, spin-offs, mergers) raise
  instead of being applied.
- **Margin.** Reg-T style short margin and futures per-contract margins; no percent or SPAN margin,
  and a margin call liquidates the whole book.
- **Vectorized engine.** Levels 0-1 only. Futures run as fractional contracts on a continuous series
  (no roll cost, no margin); FX needs one aligned bar calendar; episode pnl excludes costs.
- **Data.** yfinance is unofficial and adjusted-only; Tiingo is daily-only. Splits and dividends are
  not fetched as corporate-action datasets, and fundamentals, news and filings have no dataset
  contract.
- **Scale.** The replay feed holds every event in memory (about 5 million rows is the guard);
  runs are single-process apart from parallel sweeps.
- **Execution.** IOC/FOK/GTD time-in-force are refused; VWAP uses an equal-slice approximation;
  Almgren-Chriss impact is not implemented.
- **Unused extension points.** A handful of Protocols (`FillModel`, `MetricsComputer`,
  `ReportRenderer`, `ArtifactStore`, `RunRegistry` and five event kinds) have no implementation;
  they are listed in [`docs/EXTENSION_POINTS.md`](docs/EXTENSION_POINTS.md).

Each module page in [`docs/modules/`](docs/modules/) ends with its own "Known gaps".

## Contributing

Bug reports and pull requests are welcome. Run the checks from the repository root before opening
one:

```bash
uv run pytest
uv run mypy --strict crucible examples tools
uv run ruff check . && uv run ruff format --check crucible tests examples tools
uv run python -m tools.lint_imports
uv run python -m tools.docgen --check
```

The rules the project holds itself to (determinism, point-in-time access, refusing instead of
warning, documentation obligations) are in [`CONTRIBUTING.md`](CONTRIBUTING.md) and
[`AGENTS.md`](AGENTS.md).

## License

MIT; see [`LICENSE`](LICENSE).
