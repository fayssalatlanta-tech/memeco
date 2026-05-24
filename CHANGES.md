# Project Changes Log

This file records every modification Kiro makes to the memeco project, in
reverse chronological order. Each entry lists what changed, why, and the
files touched. It is meant to be read top-to-bottom by anyone catching up on
the project.

---

## 2026-05-24 — Proper package structure, migration tool, remove dual-import hacks

### Why

Two structural issues made the project fragile:

1. **Fragile imports.** Service files had `try/except ModuleNotFoundError`
   blocks to support two import paths depending on how Python was launched
   (`cwd=app/` for scripts vs project root for tests). This breaks the moment
   a new developer or CI runs from a different directory.

2. **No migration tool.** Migrations were raw SQL applied via `docker cp` +
   PowerShell one-liners. This breaks the moment a teammate joins or you ship
   to a server. There was no way to know which migrations had already been
   applied.

Both are fixed by turning `app/` into a proper installable package with
`pyproject.toml` and adding a lightweight migration runner.

### What changed

#### `pyproject.toml` (new)

- Defines the `memeco` package with setuptools.
- Declares all dependencies (previously in `requirements.txt`).
- Requires Python ≥ 3.10 (the codebase uses `type | None` syntax).
- Console script entry points:
  - `memeco-server` → `app.web_server:main`
  - `memeco-ingest` → `app.ingest_dexscreener:cli`
  - `memeco-pipeline` → `app.run_analysis_pipeline:cli`
  - `memeco-migrate` → `app.apply_migrations:main`

#### `app/__init__.py` (new)

- Marks `app/` as a Python package.

#### `app/apply_migrations.py` (new)

- ~160-line migration runner.
- Creates a `schema_migrations` table (version, filename, SHA-256 checksum,
  applied_at) if not present.
- Discovers all `migrations/*.sql` files, sorts by filename, applies pending
  ones in order.
- Detects TimescaleDB-specific statements (`create_hypertable`,
  `add_retention_policy`, etc.) and runs those outside an explicit transaction.
- Supports `--dry-run` / `-n` to show pending without applying.
- Warns (but doesn't fail) if a previously-applied file's checksum changed.

#### All `app/services/*.py` files with dual imports (10 files)

- Removed every `try: ... except ModuleNotFoundError: ...` block.
- Kept only the canonical `from app.xxx import ...` form.

#### All `app/run_*.py` CLI scripts (17 files)

- Changed `from db import create_pool` → `from app.db import create_pool`.
- Changed `from services.xxx import ...` → `from app.services.xxx import ...`.
- Added `def cli(): asyncio.run(main())` to `run_analysis_pipeline.py` and
  `ingest_dexscreener.py` for the console script entry points.

#### `app/web_server.py`

- Changed all bare imports to absolute `from app.xxx import ...`.

#### `app/ingest_dexscreener.py`

- Changed all bare imports to absolute `from app.xxx import ...`.
- Added `def cli()` entry point.

#### `app/pairs.py`, `app/prices.py`, `app/tokens.py`, `app/risk.py`

- Changed `from validation import require_keys` → `from app.validation import ...`.

#### `app/services/cluster_analysis_service.py`

- Changed bare `from helius import ...` → `from app.helius import ...`.

#### `requirements.txt`

- Kept for backwards compatibility with a note pointing to `pyproject.toml`.
- Changed pinned versions to minimum-version ranges.

#### `README.md`

- Setup section now shows `pip install -e .` + `memeco-migrate`.
- Run sections show console script commands alongside module invocations.
- Kept legacy manual-migration note for existing users.

#### `DEVELOPMENT_GUIDE.md`

- Added "Package Structure and Imports" section with rules.
- Added "Migrations" section explaining the runner and how to add new ones.
- Added `pyproject.toml`, `app/__init__.py`, `app/apply_migrations.py` to
  Important Files list.

### Backwards compatibility

- **Tests:** All 52 existing tests pass unchanged — they already used
  `from app.xxx` imports.
- **Running scripts directly:** `python -m app.run_analysis_pipeline` works
  from project root. The old `python app/run_analysis_pipeline.py` from
  `cwd=app/` will NOT work anymore (bare imports removed). Use the console
  scripts or `-m` form instead.
- **Docker:** `docker compose up -d` is unchanged. The migration tool connects
  via `DATABASE_URL` like everything else.
- **CI/CD:** Any CI that did `pip install -r requirements.txt` will still work
  (the file still exists) but should migrate to `pip install -e .`.

### Tests

- `pip install -e .` succeeds cleanly on Python 3.12.
- All imports verified: `from app.db`, `from app.services.*`, `from app.web_server`,
  `from app.apply_migrations` all resolve.
- `python3 -m unittest discover -s tests -v` — 52 tests, all pass.
- `memeco-migrate --dry-run` correctly discovers 12 migration files in order
  with deterministic checksums.

---

## 2026-05-24 — Justify the TimescaleDB image: hypertables, retention, continuous aggregate

### Why

`docker-compose.yml` was already pulling `timescale/timescaledb:latest-pg15`
but no migration ever called `create_hypertable()`. We were paying the image
and operational overhead of TimescaleDB while running it as plain Postgres.
`token_prices` and `raw_api_snapshots` are the two natural candidates: both
are append-mostly, time-keyed, and already grow without bound (`raw_api_snapshots`
in particular has no retention and is queried only by recency).

This was follow-up #4 in the previous changelog entry.

### What changed

#### `migrations/012_timescale_hypertables.sql` (new)

- Loads `CREATE EXTENSION IF NOT EXISTS timescaledb`.
- Converts `token_prices` to a hypertable on `time` with 1-day chunks. The
  existing `UNIQUE (time, pair_id)` constraint already includes the
  partitioning column, so no schema rewrite is needed.
- Converts `raw_api_snapshots` to a hypertable on `created_at` with 1-day
  chunks. Replaces `PRIMARY KEY (id)` with `PRIMARY KEY (id, created_at)`
  because hypertable unique constraints must include the partitioning column.
  The `BIGSERIAL` sequence is unaffected and nothing in the codebase
  references `raw_api_snapshots(id)` by FK, so this is invisible to callers.
- Adds retention policies: `token_prices` keeps 30 days of raw rows,
  `raw_api_snapshots` keeps 14 days. Both are registered with
  `if_not_exists => TRUE`.
- Creates the continuous aggregate `token_prices_hourly` (1-hour buckets per
  pair, OHLC + avg/max liquidity, max 1h/24h volume, last market cap / FDV,
  total buys/sells per hour, sample count) and a refresh policy that runs
  every 30 minutes over the last 30 days. This keeps long-range price
  history available even after the raw rows are dropped by retention.
- The whole migration is idempotent: re-running it emits NOTICEs but does
  not error or duplicate work.

#### `README.md`

- Added migration 012 to the "Apply later migrations in order" block.
- Added a short paragraph explaining what 012 changes and why it justifies
  the TimescaleDB image.

#### `DEVELOPMENT_GUIDE.md`

- Added a Performance Rule pointing future contributors at the continuous
  aggregate when they need long-range price history.
- Removed "Add raw snapshot retention policy" from "Known Future Improvements"
  since it is now done.

### Backwards compatibility

- `token_prices` schema is unchanged. The existing upsert in
  `app/prices.py` (`ON CONFLICT (time, pair_id)`) still works because that
  unique constraint already included the partitioning column.
- `raw_api_snapshots` keeps the same columns. The only schema change is
  promoting `(id, created_at)` to the primary key. The insert path in
  `app/system.py` does not specify the primary key columns and is unaffected.
- All existing read paths (`market_filter_service`, `liquidity_filter_service`,
  `web_server.py` lateral joins) are plain SELECTs and continue to work
  against hypertables transparently.
- No application code depends on `raw_api_snapshots(id)` and no FK targets
  it, so dropping/recreating the primary key is safe.
- Retention will start dropping data older than 30 / 14 days. On a fresh
  install nothing is dropped; on an existing install older rows will be
  pruned by the next retention job. If a deployment needs to keep more
  raw history, change the `drop_after` intervals before applying the
  migration.

### Tests

- Validated end-to-end against a real PostgreSQL 15 + TimescaleDB 2.27
  instance:
  - Loaded `001_initial_schema.sql`, inserted 201 sample rows into
    `token_prices` and 51 into `raw_api_snapshots`.
  - Applied `012_timescale_hypertables.sql`. Both tables became hypertables
    with one chunk; all rows preserved; 3 jobs registered (2 retention,
    1 continuous aggregate refresh); `token_prices_hourly` populated
    with 4 hourly buckets.
  - Re-applied the migration: emitted only NOTICEs, no errors, no
    duplicates.
  - Confirmed the existing app SQL paths still work post-migration: the
    `app/prices.py` upsert (`ON CONFLICT (time, pair_id)`) and the
    `app/system.py` snapshot insert both succeeded on the hypertables.

### Follow-ups identified during this work (NOT addressed here)

- Continuous aggregate `token_prices_hourly` is not yet wired into the
  dashboard's 1h/4h/24h price chips. Today those chips read directly from
  `token_prices` via lateral joins. After 30 days of retention they will
  start returning fewer rows; the dashboard should switch to the aggregate
  for any range > a few hours.
- Compression policies were intentionally not added. They are worth doing
  once row volume justifies the operational complexity, especially for
  `raw_api_snapshots` whose JSONB blobs compress very well.

---

## 2026-05-24 — Migrate web server from `BaseHTTPRequestHandler` to FastAPI

### Why

The whole codebase is `asyncio` + `asyncpg`, but the HTTP layer was a hand-rolled
`BaseHTTPRequestHandler` on `ThreadingHTTPServer`. Every request:

- created a brand-new `asyncpg` pool via `create_pool()`,
- ran the handler under `asyncio.run(...)` (new event loop per request),
- closed the pool in a `finally` block.

This wasted TLS handshakes, connection setup, and blocked sync↔async hand-offs.
The migration reuses one pool for the whole process and unlocks streaming JSON,
OpenAPI docs, and proper backpressure.

### What changed

#### `app/web_server.py` (1867 → ~1900 lines, but ~180 lines of hand-rolled HTTP boilerplate removed)

- Replaced `http.server` imports with FastAPI / uvicorn / asyncpg / contextlib.
- Removed `class QuantRequestHandler(BaseHTTPRequestHandler)` and the
  `ThreadingHTTPServer` entrypoint. Replaced with a `FastAPI` app, route
  decorators, and `uvicorn.run(...)` in `main()`.
- Added a `lifespan` async context manager that creates **one** shared
  `asyncpg.Pool` at app startup and closes it on shutdown
  (`app.state.pool`).
- Refactored every request-scoped helper to take `pool` as its first argument
  instead of creating its own pool:
  - `fetch_summary`, `fetch_watchlist`, `fetch_token_detail`, `fetch_runs`,
    `fetch_whale_radar`, `fetch_wallet_detail`
  - `store_whale_signal`, `store_whale_signal_payload`,
    `maybe_queue_whale_signal_analysis`
  - `run_whale_action`
- Background-thread workers were intentionally **left untouched** because they
  run in a fresh `asyncio.run(...)` loop on a separate thread and must own
  their pool:
  - `run_analysis_pipeline_with_status`
  - `scan_worker`, `manual_token_worker`, `whale_signal_token_worker`
  - `mark_signal_analysis_started`, `mark_signal_analysis_finished`,
    `mark_signal_analysis_failed`
- Added `QuantJSONResponse`, a custom `JSONResponse` that uses
  `json.dumps(..., default=str)` so `Decimal` and `datetime` values serialize
  exactly the way the previous handler did. This keeps existing dashboard
  HTML/JS byte-compatible with the new API.
- Added a `Cache-Control: no-store` middleware to preserve the original
  no-cache header on every response.
- Preserved the original 400-on-bad-input behavior (FastAPI's default 422 was
  bypassed) for:
  - `POST /api/analyze-token` and `POST /api/whale-signal` malformed JSON
    bodies — still return `{"error": "Invalid JSON body"}` with 400.
  - `GET /api/token-detail` non-integer `run_id`/`token_id` — still returns
    `{"error": "run_id and token_id are required integers"}` with 400.
  - `GET /api/wallet-detail` invalid Solana address — still returns
    `{"error": "wallet is required"}` with 400.
- Replaced `parse_limit(query: dict)` with `parse_limit_str(raw: str | None)`
  that takes a single query value and matches the original fallback semantics
  (invalid integer → default).
- Entrypoint is now `python app/web_server.py` (still works) **or** the
  recommended `python -m uvicorn web_server:app --host 127.0.0.1 --port 8000`.
  The `MEMECO_HOST` and `MEMECO_PORT` env vars override defaults when launched
  via `main()`.

#### Routes — all preserved exactly

| Method | Path                            | Handler                  |
| ------ | ------------------------------- | ------------------------ |
| GET    | `/`                             | `dashboard.html`         |
| GET    | `/token`                        | `token_detail.html`      |
| GET    | `/whale-radar`                  | `whale_radar.html`       |
| GET    | `/wallet`                       | `wallet_detail.html`     |
| GET    | `/api/health`                   | `{"status": "ok"}`       |
| GET    | `/api/summary`                  | `fetch_summary`          |
| GET    | `/api/watchlist`                | `fetch_watchlist`        |
| GET    | `/api/token-detail`             | `fetch_token_detail`     |
| GET    | `/api/runs`                     | `fetch_runs`             |
| GET    | `/api/whale-radar`              | `fetch_whale_radar`      |
| GET    | `/api/wallet-detail`            | `fetch_wallet_detail`    |
| GET    | `/api/scan/status`              | `get_scan_state`         |
| POST   | `/api/scan`                     | `start_scan_job`         |
| POST   | `/api/analyze-token`            | `start_manual_token_job` |
| POST   | `/api/whale-signal`             | `store_whale_signal_payload` |
| POST   | `/api/whale-radar/{action}`     | `run_whale_action`       |

Where `{action}` ∈ `audit`, `refresh-prices`, `sync-webhook`, `survival`.

#### `requirements.txt`

Pinned all dependencies to current stable versions. Added FastAPI and uvicorn:

```
asyncpg==0.30.0
fastapi==0.115.5
httpx==0.27.2
python-dotenv==1.0.1
uvicorn[standard]==0.32.1
```

### Backwards compatibility

- All API URLs, query parameters, request bodies, response status codes, and
  response JSON shapes are unchanged.
- All four static HTML pages are still served at the same paths.
- Background scan / manual analyze / whale webhook flows still launch via
  `threading.Thread` exactly as before.
- The webhook `Authorization` check still uses `==` (see Follow-ups).
- `python app/web_server.py` still works for ad-hoc runs.

### Tests

- No existing test imports `web_server`, so unit tests are unaffected.
- Migration was syntax-checked with `python -m py_compile` and smoke-imported
  to confirm the FastAPI app boots cleanly.

### Follow-ups identified during this work (NOT addressed here)

These are surfaced for future work, intentionally kept out of this change to
limit blast radius:

1. **Constant-time webhook auth.** `/api/whale-signal` compares the
   `Authorization` header with `==`. Should switch to
   `hmac.compare_digest(...)` to remove a timing-attack surface.
2. **`docker-compose.yml` magic password.** `POSTGRES_PASSWORD=your_strong_password`
   is committed verbatim. Should be `${POSTGRES_PASSWORD:?...}` and live in `.env`.
3. **CLI scripts still create-and-close their own pools** (`run_*.py`,
   `ingest_dexscreener.py`). That is correct for one-shot CLI invocations and
   was deliberately left alone.
4. **TimescaleDB image without hypertables.** ~~No migration calls
   `create_hypertable()` despite using `timescale/timescaledb:latest-pg15`.
   `token_prices` and `raw_api_snapshots` are the natural candidates.~~
   Done in `migrations/012_timescale_hypertables.sql` (2026-05-24).
5. **Migration tool.** ~~SQL files are still applied via `docker cp` + manual
   `psql`. Adding Alembic / dbmate / a tiny `apply_migrations.py` would make
   onboarding and deploys safer.~~
   Done in `app/apply_migrations.py` + `memeco-migrate` (2026-05-24).
6. **No retry/backoff on DexScreener / Helius.** Transient 429/5xx is silently
   swallowed and recorded as "no data." Add `tenacity` with jitter.

---

<!--
Kiro changelog conventions
- Newest entry on top.
- One section per change with: date heading, Why, What changed (grouped by file),
  Backwards compatibility, Tests, Follow-ups.
- Keep it honest. Note risks and follow-ups even if not addressed.
-->
