# Project Changes Log

This file records every modification Kiro makes to the memeco project, in
reverse chronological order. Each entry lists what changed, why, and the
files touched. It is meant to be read top-to-bottom by anyone catching up on
the project.

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
4. **TimescaleDB image without hypertables.** No migration calls
   `create_hypertable()` despite using `timescale/timescaledb:latest-pg15`.
   `token_prices` and `raw_api_snapshots` are the natural candidates.
5. **Migration tool.** SQL files are still applied via `docker cp` + manual
   `psql`. Adding Alembic / dbmate / a tiny `apply_migrations.py` would make
   onboarding and deploys safer.
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
