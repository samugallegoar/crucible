# DEPENDENCIES — what we depend on, why, and what we refuse

> Every third-party package the repo declares, where it is used, how it is
> pinned, and the additions that need a decision first. Enforced by
> `tests/unit/test_dependencies_doc.py`: each declared package must appear in the
> tables below, `crucible/` may import only declared runtime packages, and no
> package from the forbidden list may be imported. Stack rationale: ADR-0001/0002/0003.

## 1. Pinning policy

- **Direction of trust**: `uv.lock` is the pin. `pyproject.toml` states only a
  **lower bound** (`polars>=1.0`) — the oldest version we have reason to believe
  works — never an upper cap. CI installs with `uv sync --locked`, so a lock that
  disagrees with `pyproject.toml` fails the build.
- **Never `pip install`** (AGENTS.md §2). Add with `uv add <pkg>` (runtime) or
  `uv add --dev <pkg>`; both rewrite `pyproject.toml` and `uv.lock` — commit both.
- **Upgrade deliberately**: `uv lock --upgrade-package <pkg>`, then the full suite.
  A dependency bump that moves a golden hash is a **regression** until proven
  otherwise (`docs/COMPATIBILITY.md` §6): Polars, NumPy and Parquet writers are
  the usual suspects for byte-level drift.
- **The lock hash is provenance**: `manifest.json` records `env_lock_hash`
  (SHA-256 of `uv.lock`), so a result can be tied to the exact environment.
- **Python** `>=3.12` (`.python-version` pins the interpreter for `uv`).
- Adding **any** runtime dependency needs a one-line justification in this file and,
  if it touches determinism, timing or the money path, an ADR.

## 2. Runtime dependencies (`[project].dependencies`)

| Package | Lower bound | Why | Where it is used | Watch out for |
|---------|-------------|-----|------------------|---------------|
| `polars` | 1.0 | Primary dataframe library; lazy, Arrow-native; deterministic Parquet writes (uncompressed, no statistics) | `data/` (store, contracts, transforms, importers), `analytics/`, `experiments/` (artifact frames), `live/` (feed frames), `vectorized/`, `cli/` | Version drift can change Parquet bytes and therefore golden hashes. |
| `numpy` | 2.0 | Numerics and the explicit `Generator` RNG threaded through every stochastic component | `analytics/`, `validation/`, `execution/models.py`, `portfolio/`, `core/`, `experiments/`, `live/` | Never use the legacy global `np.random`. |
| `duckdb` | 1.0 | Embedded SQL for the trial registry (`trial_registry.duckdb`, ADR-0014) | `validation/trial_registry.py` only | One process may hold the database file; parallel sweeps register serially in the parent (ADR-0038). ADR-0002 also anticipated PIT queries over Parquet; the store reads with Polars instead. |
| `pyarrow` | 17.0 | Arrow interchange named by ADR-0002 (Polars <-> DuckDB, Parquet) | **No direct import in the repo** (audit 2026-09-28); available to Polars/DuckDB interop | Candidate for removal or for an "extra" — open decision, see Known gaps. |
| `pydantic` | 2.7 | Frozen, validated config models, hashing, schema export | `experiments/config.py`, `validation/config.py`, `data/importers/spec.py` | Config models are `frozen=True, extra="forbid"`; the schema generator in `tools/docgen.py` reads `model_json_schema()`. |
| `exchange-calendars` | 4.5 | Trading sessions, holidays, half-days | `data/calendars.py` (wrapped behind typed methods) | Untyped (`ignore_missing_imports` in `pyproject.toml`); its window moves with today's date unless `start`/`end` are passed (ADR-0053); it pulls in **pandas** transitively, which stays behind the calendar boundary. |
| `pyyaml` | 6.0 | YAML configs and import specs; canonical config rendering | `experiments/config.py`, `data/importers/`, `cli/` | Use `safe_load`/`safe_dump` only. |
| `yfinance` | 0.2.40 | **Optional extra** (`uv sync --extra yfinance`): Yahoo Finance prices for the default provider (ADR-0063). Not in the core install, so the core carries no scraping dependency | `data/providers/yfinance.py` only, imported lazily; a missing install raises `ProviderUnavailableError` with the command | Unofficial: Yahoo can break or throttle it without notice. Pulls in pandas, which the adapter never imports (it reads the returned frame by duck typing). The Tiingo adapter uses stdlib `urllib`, so it adds nothing. |
| `mcp` | 2.3 (`<3`) | **Optional extra** (`uv sync --extra mcp`): the official Model Context Protocol SDK for the stdio server (ADR-0066). Not in the core install | `mcp_server/` only (imported inside `build_server`) | Pinned to 2.x (`MCPServer`, `mcp.Client`); 1.x lacks these APIs. A major bump may need a change in `mcp_server/server.py`. Pulls in an HTTP stack (uvicorn, starlette) that the stdio server does not use. |
| `matplotlib` | 3.11.2 | The deterministic SVG equity/drawdown plot in reports | `analytics/plots.py` only | Backend must stay non-interactive; SVG metadata is pinned so bytes are stable (ADR-0011). |

## 3. Development dependencies (`[dependency-groups].dev`)

| Package | Why | Where |
|---------|-----|-------|
| `pytest` | Test runner; markers `bench`, `golden`, `lookahead` (`--strict-markers`) | `tests/` |
| `hypothesis` | Property tests; derandomized in CI (`tests/conftest.py` profiles) | `tests/property/` and a few unit tests |
| `ruff` | Lint and format (`ruff check .`; format only `crucible tests examples tools`) | CI, pre-commit |
| `mypy` | `mypy --strict crucible examples tools`, with the pydantic plugin | CI, pre-commit |
| `pre-commit` | Runs the same checks before a commit | `.pre-commit-config.yaml` |
| `types-pyyaml` | Type stubs for `yaml` | mypy |
| `import-linter` | Enforces the layering rule of `docs/ARCHITECTURE.md` (`uv run python -m tools.lint_imports`) | CI, `tests/unit/test_architecture_conformance.py` |
| `psutil` | Peak-memory measurement for the opt-in scale benchmarks (`uv run pytest -m bench tests/bench -s`, ADR-0054) | `tests/bench/test_real_data_scale.py` only |

The standard library carries the rest: `decimal`, `dataclasses`, `hashlib`,
`statistics.NormalDist` (DSR), `argparse` (CLI), `json`, `concurrent.futures` (sweeps).

## 4. Forbidden and gated additions

| Addition | Status | Reason |
|----------|--------|--------|
| A **Rust/C++/native** extension as a *core* dependency | **Forbidden** (AGENTS.md §9, ADR-0003) | Hot-path ports go behind existing Python Protocols and stay optional. |
| **pandas** imported directly in `crucible/` | **Forbidden** | Polars is the dataframe. pandas is present only because `exchange-calendars` needs it; it must not cross the `data/calendars.py` boundary. |
| **numba** | **Gated** — needs an ADR and a measured hot path with golden/property coverage first (ADR-0003, AGENTS.md §1.1) | JIT constrains style and complicates debugging; it must sit behind an existing Protocol and be optional. |
| **scipy, scikit-learn, statsmodels** | **Forbidden** without an ADR | The statistical routines are implemented and unit-tested in `validation/` from named formulas (DSR, PBO, CSCV); a black-box replacement would move results and hide assumptions. |
| **Network clients / broker or vendor SDKs** (`requests`, `httpx`, `ib_insync`, ...) in the core install | **Forbidden** in `[project].dependencies` | Live adapters live at the I/O boundary behind the `live.enabled` flag and, when they exist, ship as optional extras (`docs/modules/live.md`). |
| A **second dataframe or storage engine** (Dask, Spark, SQLite stores, pickle/feather artifacts) | **Forbidden** without an ADR superseding ADR-0002 | Byte-identical artifacts depend on one deterministic writer. |
| Anything that **reads the wall clock or a global RNG** in simulation code (`freezegun`-style patches, `random`, `np.random.*` module functions) | **Forbidden** | AGENTS.md §5/§9. Tests use fixed timestamps and seeded generators. |
| `pip install` / another package manager | **Forbidden** | `uv` and the lockfile are the environment. |

## 5. How to add a dependency

1. Try the standard library and the packages above first (`docs/INVENTORY.md` lists
   what already exists in `crucible/`).
2. `uv add <pkg>` (or `--dev`); commit `pyproject.toml` and `uv.lock` together.
3. Add a row to §2 or §3 saying why, where, and the watch-outs.
4. Run the **full** suite: goldens must not move. If they do, see
   `docs/COMPATIBILITY.md` §6 before touching a fixture.
5. If it touches determinism, timing or money: write the ADR.

## Known gaps

- `pyarrow` is declared but never imported; keep it (Arrow interchange in ADR-0002),
  demote it to an extra, or drop it — **owner decision**.
- `numba` and any hot-path port are deferred (ADR-0003); the opt-in scale benchmarks
  (`tests/bench`, ADR-0054) showed none was needed
  beyond the opt-in `bench` marker.
- No automated license or vulnerability audit of the lockfile.
