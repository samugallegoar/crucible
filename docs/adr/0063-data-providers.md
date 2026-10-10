# ADR-0063: Data providers (yfinance and Tiingo) behind one interface

- **Status**: accepted
- **Date**: 2026-10-07

## Context

Crucible could only ingest files a user already had (ADR-0052). To run on real data without a file the
user needs to fetch from free providers, starting with yfinance (no key) and Tiingo (free key), without
giving up reproducibility (AGENTS.md §1.3), the raw-versus-adjusted rule (§9), or the "refuse, don't warn"
stance (§1.5), and without adding network libraries to the core install (`docs/DEPENDENCIES.md` §4).
Design note: `docs/features/data-providers.md`.

## Decision

1. **Providers sit upstream of the store.** A fetch writes a dataset with `build_dataset`; runs name the
   stored dataset exactly as today. The engine never calls a provider, so a run's inputs are the stored
   dataset's content hash, not whatever a vendor returns that day.
2. **One interface, one output format.** `PriceProvider.get_prices(symbol, start, end, interval,
   price_basis)` returns a frame in the existing `BAR_SCHEMA` (UTC int64 ns, `event_time` = bar close,
   `available_at = event_time + feed_latency_s`, sorted, no pandas index). One adapter per provider
   (`yfinance`, `tiingo`); a new provider is one file and one registry line. Session-close mapping reuses
   the OHLCV importer's lookup, extracted into a shared helper.
3. **Price basis is explicit.** Default `adjusted`, recorded in the manifest `source` and import report;
   `raw` is available where the provider can honestly supply it. Tiingo supplies both. yfinance supplies
   `adjusted` only: Yahoo's `Close` is split-adjusted, so a raw series is not available and a `raw`
   request is refused rather than mislabelled.
4. **Dependencies.** yfinance is an optional extra (`uv sync --extra yfinance`); the default provider is
   still yfinance and the command prints the install hint when the package is missing. Tiingo uses
   stdlib `urllib`; `.env` is read by a small stdlib parser. No core dependency is added.
5. **Secrets.** Keys come from the environment or `.env` (the environment wins); `.env` is gitignored and
   `.env.example` documents every variable. A key is held in a masked wrapper and sent in the
   `Authorization` header, never in a URL; it never reaches logs, errors, cache keys, manifests or reports.
6. **Reliability.** Bounded retry with backoff on 429, 5xx and network errors (honouring `Retry-After`),
   typed errors otherwise, and no dataset written if any requested symbol failed unless `--allow-partial`.
   Raw responses are cached under `data/cache/providers/` for ranges that ended before today.
7. **Selection.** `--provider`, then `CRUCIBLE_DATA_PROVIDER`, then `yfinance` (as built there is no fetch spec
   file, so no spec level). The choice never enters an experiment config, so config hashes and experiment ids are
   unchanged.

## Alternatives considered

- **Fetching at run time** (the engine asks the provider): makes results depend on the vendor's current
  answer and the network; rejected by AGENTS.md §1.3.
- **yfinance in the core dependencies:** zero extra step, but it brings pandas and a network stack into
  every install, against `docs/DEPENDENCIES.md` §4 (owner chose the optional extra).
- **`requests`/`httpx` for Tiingo:** a core dependency for one HTTP GET; stdlib suffices.
- **`python-dotenv`:** a dependency for twenty lines of parsing.
- **Raw prices by default:** more faithful, but the engine cannot process splits, so unadjusted history
  would show price jumps; the adjusted default is labelled so it cannot be mistaken for raw.

## Consequences

- A user can build a dataset from a free provider in one command and run on it; the dataset is as
  reproducible as any other (content-hashed), and refetching later may give different bytes, which the
  manifest hash makes visible.
- yfinance is unofficial and can break or rate-limit without notice; the README says so. Adjusted history
  from a provider can change when the provider restates it.
- Deferred: dividends and splits as corporate-action datasets, fundamentals, more providers, async or
  bulk download.
