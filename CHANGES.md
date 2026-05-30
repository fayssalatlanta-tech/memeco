# Project Changes Log

This file records every modification Kiro makes to the memeco project, in
reverse chronological order. Each entry lists what changed, why, and the
files touched. It is meant to be read top-to-bottom by anyone catching up on
the project.

---

## 2026-05-26 — UX polish batch: Ops Deck, whale ticker, browser notifications, tier hovers

### Why

Five small-but-visible follow-ups requested after the page redesigns. They
target operational visibility, momentum awareness, and personality at the
edges of the UI.

### What changed

#### 1. `/system` — Ops Deck (new page + endpoint)

* `app/web_server.py`: new `GET /api/system` returning `{ config,
  activity, failed_runs, db_size, hypertables, retention_policies,
  whale_webhook, decisions, scan_state }`. Reads ENV for API config,
  rolls up `raw_api_snapshots` per source for the last 1h/24h, queries
  TimescaleDB catalog (`timescaledb_information.hypertables` and
  `timescaledb_information.jobs`) for retention info, fetches DB size
  via `pg_database_size`, lists the last 5 failed/errored runs, and
  reads the active webhook config.
* `app/web_server.py`: new `GET /system` static route serving
  `system.html`.
* `app/static/system.html`: new full page styled to match the rest of
  the suite. Top: brand bar + last-updated pulse pill. HUD: total
  decisions / pass / pass-high-risk / latest decision. Two-column
  status (External APIs configured ✓/✗, Whale Webhook live config).
  Activity table per source (1h / 24h / last seen). Storage panel
  with hypertables + retention. Failure list with red-edge cards.
  Polls `/api/system` every 30s.
* All four other pages get a "SYSTEM" link in the nav so the page is
  one click away.

#### 2. Whale Intercept ticker on the dashboard

* `app/static/dashboard.html`: new horizontal strip below the brand
  bar showing the last 3 high-signal whale events (BUY type · token ·
  wallet · SOL amount · "23s ago"). Auto-hides when there are no
  alerts. Polls `/api/whale-radar?limit=10` every 60 seconds, slides
  cards in with a brief animation. Honors prefers-reduced-motion.

#### 3. Browser notifications for starred-token status flips

* `app/static/dashboard.html`: extended `recordDecisionDiffs` to fire
  a `Notification` (browser-native) when a starred token's
  `final_watchlist_status` changes between two consecutive renders.
  Sticky opt-in via `localStorage` (`memeco.notify.starred`). The
  permission prompt is asked only the first time the user stars a
  token — never out of the blue.

#### 4. Tier emblem hover effects (wallet detail)

* `app/static/wallet_detail.html`: each tier emblem (TITAN / WHALE /
  DOLPHIN / TROUT / MINNOW / BAGHOLDER) now reacts when hovered:
  TITAN shimmers gold, WHALE/DOLPHIN dive forward, TROUT spins on
  its Y-axis, MINNOW bubbles up + tints orange, BAGHOLDER shakes
  (sad reaction). Honors prefers-reduced-motion.

#### 5. Vite SPA refactor — deferred

* This one was promised in the original roadmap but is genuinely
  an architectural lift (set up Vite, extract reusable components,
  build pipeline, rewire FastAPI to serve the built bundle, update
  CI). Doing it in a single conversation turn would risk leaving
  the project in a half-broken state.
* Documented as a follow-up in `DEVELOPMENT_GUIDE.md` so an expert
  picking it up later has the right context and constraints.

### Tests

* All 72 unit tests still pass.
* All five HTML pages (`dashboard`, `token_detail`, `whale_radar`,
  `wallet_detail`, `system`) parse cleanly.
* `GET /api/system` and `GET /system` both return 200 against the
  local DB.

### Backwards compatibility

* No schema changes.
* `/api/whale-radar` unchanged (the ticker reads existing fields).
* New `/api/system` and `/system` are additive.
* Notifications are opt-in and degrade silently on browsers that
  lack the API or where the user has denied permission.

---

## 2026-05-26 — UI polish batch: Token Detail Case File, Wallet tier hover narratives

### Why

After the cyberpunk reskin and the four big page redesigns
(Dashboard → Command Bridge / Signal Floor, Whale Radar → Radar
Console, Wallet → Wallet Dossier with PnL tiers, Token → Case File),
the four-page suite shares one design language: black + neon orange,
monospace data, sticky brand bars, edge-stripe HUD tiles, tone-coded
everything. This entry records that whole arc.

### What changed (UI redesign arc)

* **Cyberpunk theme migration** — `app/static/shared/tokens.css` plus
  every page's inline `:root` block re-themed to true black bg,
  dark-gray panels, neon orange accent, pure white priority text.
  ~200 hardcoded colors converted across 4 pages.
* **Dashboard COMMAND BRIDGE** — replaced sidebar+main grid with
  brand bar / command rail / HUD strip / scan ticker / filter bar /
  hero / opportunity grid / decision-stream table. New monospace
  typography, terminal-prompt search.
* **SIGNAL FLOOR upgrade** — Decision Stream renamed to SIGNAL
  FLOOR, gained:
  * Live PASS/WAIT/REJECT/FRESHEST counters in the section header.
  * **9-bar Signal Chain barcode** in every row — colored ticks for
    each pipeline stage (Market → Contract → Liquidity → Trap →
    Wallet → Cluster → Manip → Dev → Insider). Hover any bar for
    "Stage: status".
  * Three view modes via a tab switcher: ▦ TABLE (dense default),
    ≡ TAPE (chronological pulse feed), ▣ COCKPIT (detailed card
    grid). All views share state, sort, filter, drawer-on-hover,
    starring, keyboard nav.
  * Better empty state (glowing orange ▲ + uppercase mono).
* **Whale Radar RADAR CONSOLE** — replaced stacked panels with a
  centerpiece radar orb (3 concentric rings, sweeping arm, pulsing
  pip that flashes white on new signals) + LAST INTERCEPT readout,
  vertical command rail, alerts grid (INCOMING + GROUP BUY side by
  side), gold/silver/bronze rank chips on the leaderboard.
* **Wallet Detail WALLET DOSSIER + tiers** — wallet rank emblems
  driven by Total PnL:
  * `>= 100 SOL` → TITAN (gold halo + crown)
  * `50–100 SOL` → WHALE
  * `20–50 SOL`  → DOLPHIN
  * `5–20 SOL`   → TROUT
  * `0–5 SOL`    → MINNOW
  * `< 0 SOL`    → BAGHOLDER (drooping bag, red border)
  * All emblems are inline SVGs; tier reskins the hero border + glow.
  * RECENT P&L SPARK histogram + ROI BALANCE scale (literally tilts
    based on win/loss ratio) + SAFETY panel.
* **Token Detail CASE FILE** — sticky brand bar / hero with token
  head + Change Signals diff strip / KPI HUD / **9-card forensic
  Decision Dossier** with auto-numbered counters and tone-coded
  edges / horizontal Token Timeline with pip-marker dots on a
  glowing orange axis line / reskinned tables (Wallet Intelligence,
  Early Buyer Profit Map, Top Holders, Wallet Relationships).

Pure markup + CSS + a sprinkle of JS. No backend or schema changes
in the UI batch. 72 tests still pass throughout.

---

## 2026-05-25 — Pipeline review batch: parallel Helius, batched DB writes, run-scoped services, lifespan singletons, async workers, modular layout

### Why

Eleven follow-ups from the recent code review, addressed as one coherent
pass because they touch overlapping code paths. Headlines:

1. **Sequential Helius requests (item 8)** — Cluster and wallet-manipulation
   loops fetched one holder's transactions at a time. With the per-instance
   rate limiter already in place, parallelizing with `asyncio.gather` +
   `Semaphore(10)` is a free wall-clock win without changing upstream RPS.

2. **Connection-pool abuse (item 9)** — Each per-holder edge save did its own
   `pool.acquire()`. For 10 holders that's 11 round-trips per token. Now
   one transaction per token via `executemany`.

3. **Retention vs dashboard (item 10)** — Migration 012's 14-day retention
   on `raw_api_snapshots` would silently empty dashboard fields like
   `dex_active_boosts`, `logo_url`, and `priceChange` for older tokens.
   Bumped to 90 days; long-term plan is to materialize these into a
   dashboard-state table so retention can tighten back down.

4. **Singleton clients via lifespan (item 11)** — Each service constructed
   its own DexScreener/Helius client, defeating the per-instance rate
   limiter. Now created once in the FastAPI lifespan and shared.

5. **Periodic pool/loop churn (item 12)** — `mark_signal_*` and the worker
   functions each called `asyncio.run(...)` and `create_pool()` on every
   invocation. Workers now run as `asyncio.create_task` on the FastAPI main
   loop and reuse the lifespan-managed pool.

6. **Real DB in CI (item 13)** — Added a TimescaleDB service container and
   a `migrations-smoke` job that applies every migration, re-applies for
   idempotency, and asserts dry-run reports no pending work.

7. **Monolithic web_server.py (item 14)** — Extracted scan state into
   `app/jobs/scan_state.py` and workers + orchestrator into
   `app/jobs/workers.py`. `web_server.py` dropped from ~2090 → ~1690 lines.

8. **Duplicate dependency lists (item 15)** — Deleted `requirements.txt`.
   `pyproject.toml` is the single source of truth.

9. **Dev/CI Python mismatch (item 16)** — Added `.python-version` (3.12)
   and Python 3.13 to the unit-tests matrix.

10. **MAX(id) implicit run (item 17)** — Every analysis service now accepts
    `run_id: int | None = None`. The orchestrator threads the run id
    through explicitly so concurrent ingest paths can no longer race on
    a global "current run." Standalone CLI scripts still pass `None`,
    which falls back to the previous behavior.

11. **Sloppy 4xx (item 18)** — `?limit=abc` used to silently fall back to
    the default. Now returns 400 with a useful error message.

### What changed

#### Parallelism + batching

- `app/services/cluster_analysis_service.py`
  - `_fetch_funding_edge_for_holder` is run with `asyncio.gather` +
    `Semaphore(HELIUS_PARALLELISM=10)`.
  - New `save_token_cluster_state()` writes all funding edges in one
    `executemany` and the cluster result in one `fetchrow`, all inside a
    single `pool.acquire()` + transaction. Old `save_funding_edge` and
    `save_cluster_result` kept for back-compat.
  - `HeliusClient` is opened with `async with ...` so the underlying
    `httpx.AsyncClient` is always closed.
- `app/services/wallet_manipulation_service.py`
  - Same shape: `_fetch_holder_relationship_data` fans out via
    `asyncio.gather`, then `save_token_manipulation_state` batches all
    relationship edges + the result row.

#### Retention

- `migrations/013_extend_raw_snapshots_retention.sql` (new)
  - Drops the previous policy and re-adds with `INTERVAL '90 days'`.
  - Idempotent.

#### Singletons + async workers

- `app/web_server.py`
  - Lifespan now owns one `DexScreenerClient`, one `HeliusClient`, and
    the `asyncpg.Pool`. All three close in `finally`.
  - Routes that schedule background work pass `request.app` so workers
    can pull `app.state.pool / dexscreener_client / helius_client`.
- `app/ingest_dexscreener.py`
  - `ingest_manual_token()` and `main()` now accept optional `pool=` and
    `client=`. The CLI path still creates-and-closes its own; the FastAPI
    workers pass the lifespan singletons. `main()` returns the new
    `run_id`.

#### Modular layout

- `app/jobs/scan_state.py` (new) — SCAN_LOCK, SCAN_STATE, get/update/append
  helpers, `utc_now_iso()`.
- `app/jobs/workers.py` (new) — `scan_worker`, `manual_token_worker`,
  `whale_signal_token_worker`, the `mark_signal_*` helpers,
  `latest_decision_for_token`, `run_analysis_pipeline_with_status`,
  `start_scan_job`, `start_manual_token_job`, `is_valid_solana_address`.
- `app/web_server.py` keeps lifespan, routes, and SQL query helpers.

#### Run-scoped services (item 17)

Every `get_*_inputs` and `run_*_service` now accepts `run_id: int | None`.
SQL fragments use `WHERE … = COALESCE($1, (SELECT MAX(id) FROM ingestion_runs))`
so the legacy `None` path is identical to before. Updated services:

- market_filter (`get_early_dex_candidates` + new `token_data_readiness` view)
- contract_risk
- liquidity_filter
- wallet_analysis
- cluster_analysis
- wallet_intelligence
- wallet_manipulation
- dev_wallet_audit
- dev_wallet_flow
- watchlist_decision

The orchestrator (`run_analysis_pipeline_with_status` in
`app/jobs/workers.py`) threads the `run_id` returned by ingestion into
every stage.

- `migrations/014_run_scoped_readiness_view.sql` (new)
  - Splits `latest_token_data_readiness` into a base `token_data_readiness`
    (all runs) plus a thin back-compat view filtered to `MAX(id)`.

#### CI + dev environment

- `.github/workflows/ci.yml`
  - Added Python 3.13 to the unit-tests matrix.
  - Removed `requirements.txt` from `cache-dependency-path`.
  - New `migrations-smoke` job: TimescaleDB service container, applies all
    migrations, re-applies (idempotency), and verifies dry-run.
- `.python-version` (new) — pins the editor to 3.12.
- `requirements.txt` — deleted. `pyproject.toml` is the canonical list.

#### Strict input parsing

- `app/web_server.py`
  - `parse_limit_str` now raises `ValueError` on non-integer input.
  - New `_parse_limit_or_400` helper produces a 400 instead of falling
    back to the default for `/api/watchlist`, `/api/runs`, and
    `/api/whale-radar`. Missing/empty still returns the default.
  - `is_valid_solana_address` tightened from 32–64 chars to 32–44 (real
    base58 pubkey range).

### Tests

- All 72 existing tests still pass: `python -m unittest discover -s tests`
  reports `Ran 72 tests in 0.014s — OK`.
- No new tests added in this batch — the changes are mostly structural and
  the existing classifier tests (which mock pools and clients) cover the
  hot paths. The CI Postgres job now exercises the real migration chain
  end to end on every PR.

### Backwards compatibility

- All public API URLs, request/response shapes, and CLI commands are
  unchanged.
- Service signatures only added optional kwargs (`run_id=None`,
  `helius_client=None`); existing callers keep working.
- `requirements.txt` users should switch to `pip install -e .` (the file
  was a thin alias for `pyproject.toml` since the package was set up).
- Legacy `latest_token_data_readiness` view still exists, so anything that
  queried it directly (none in code, but possibly in ad-hoc psql sessions)
  keeps working.

### Follow-ups identified during this work (NOT addressed here)

- **Materialize dashboard fields at ingest time.** The 90-day retention
  bump buys breathing room, but the long-term fix is a
  `token_dashboard_state` table refreshed in the ingest path so retention
  can tighten without breaking the UI.
- **Generic upstream error masking.** Several handlers still
  `return {"error": str(exc)}`; should log + return a generic message.
- **Per-event webhook idempotency.** Inbound `/api/whale-signal` events
  could be deduped by `(signature, wallet, signal_type)` before queueing
  analysis.

---

## 2026-05-24 — Constant-time webhook auth, pinned dependencies, GitHub Actions CI

### Why

Three pre-production items that were previously listed as follow-ups but
overdue for a 14k-LOC trading-adjacent codebase:

1. **`/api/whale-signal` is publicly reachable.** The auth check used a
   plain `==` comparison against `WHALE_WEBHOOK_AUTH_HEADER`. Even with a
   long random secret this leaks the secret a byte at a time through
   response-time differences. Use `hmac.compare_digest(...)` so an
   attacker can't time-attack the secret.
2. **Unpinned dependencies.** `requirements.txt` had loose `>=` ranges
   and `pyproject.toml` mirrored them. A breaking `httpx` or `fastapi`
   release could silently break ingestion or the dashboard with no
   warning at install time.
3. **No CI.** Nothing was running tests, linting, or type-checking on
   pull requests. Easy to land a typo or import regression.

### What changed

#### `app/web_server.py`

- New `_whale_webhook_auth_ok(provided, expected)` helper. Encodes both
  inputs to UTF-8 bytes and compares them with `hmac.compare_digest`. If
  no expected secret is configured, auth is disabled (existing behavior).
- `api_whale_signal` calls the helper instead of using `!=` directly.
- Pulled the `from datetime import datetime, timezone` out of the body
  of `utc_now_iso()` to the top of the module (ruff PLC0415).
- Annotated `SCAN_STATE` and a couple of mixed `params` lists as
  `dict[str, Any]` / `list[Any]` so mypy is happy.

#### `app/services/watchlist_decision_service.py`

- Collapsed `liquidity_status == "LIQUIDITY_WEAK" or liquidity_status == "LIQUIDITY_WARNING"`
  into `liquidity_status in {"LIQUIDITY_WEAK", "LIQUIDITY_WARNING"}` (ruff PLR1714).

#### `app/services/whale_discovery_service.py`

- Removed an unused `native_received` local in `trade_from_wallet_row()`
  (ruff F841).

#### `app/apply_migrations.py`

- Renamed unused loop variable `version` → `_version` in the dry-run
  print loop (ruff B007).

#### `app/ingest_dexscreener.py`

- Added `from typing import Any` and an explicit
  `best_pair: dict[str, Any] | None` annotation so mypy can narrow the
  `if/else` correctly.

#### Mass auto-fixes (ruff `--fix`)

- 50 cosmetic fixes: import ordering (I001 × 30), trailing newlines
  (W292 × 8), unused imports (F401 × 6), trailing whitespace (W291/W293
  × 4), unused quoted annotations (UP037 × 2). No behavioral change.

#### `pyproject.toml`

- **Pinned all runtime deps to exact versions** (asyncpg 0.31.0,
  fastapi 0.136.3, httpx 0.28.1, python-dotenv 1.2.2, tenacity 9.1.4,
  uvicorn[standard] 0.48.0). These are the versions used in current
  testing.
- Added `[project.optional-dependencies] dev = [ruff, mypy, types-...]`.
  Install with `pip install -e ".[dev]"`.
- Added `[tool.ruff]` config: line-length 100, target Python 3.10, and
  a focused rule selection (E/W/F/I/B/UP/PL/RUF). Ignored a handful of
  pylint metrics that don't fit a service-heavy codebase
  (PLR0911-15 too-many-X, PLR2004 magic numbers, B008 fastapi default,
  PLW0603 SCAN_STATE global).
- Added `[tool.mypy]` config: lenient (no implicit optional + strict
  equality + warn unused ignores), with `app.services.*` overridden to
  ignore-errors because those modules are dominated by raw upstream
  JSON shapes that don't pay back the typing cost. `tests/` is excluded
  from mypy entirely; tests run under unittest.

#### `requirements.txt`

- Pinned to the same versions as `pyproject.toml`. The file remains as
  a back-compat alias; the canonical list is `pyproject.toml`.

#### `.github/workflows/ci.yml` (new)

- Two jobs:
  1. **`lint-and-types`** runs `ruff check .` and `mypy` on Python 3.12.
  2. **`unit-tests`** runs `python -m unittest discover -s tests -v`
     against Python 3.10, 3.11, and 3.12 in parallel
     (`fail-fast: false`).
- pip is cached against `pyproject.toml` + `requirements.txt`.
- Concurrency group cancels superseded runs on the same branch.
- `permissions: contents: read` is the minimum needed for checkout.

#### `tests/test_webhook_auth.py` (new)

- Six tests pin the `_whale_webhook_auth_ok` helper:
  empty/missing config = auth disabled; missing provided header = reject;
  matching secret = accept; wrong secret = reject; off-by-one prefix and
  off-by-one suffix = reject; non-ASCII secret round-trips correctly.

### Backwards compatibility

- The `/api/whale-signal` route's _functional_ behavior is unchanged: a
  configured secret still requires a matching `Authorization` header,
  and a missing/wrong header still returns 401. Only the comparison
  primitive changed.
- All public API responses, CLI commands, and database schema are
  untouched.
- Pinning runtime deps to exact versions means `pip install -e .` will
  resolve to the tested set, but anyone who depended on a wider range
  may need to upgrade pip / use a fresh venv. This is the intended
  behavior — silent dep drift was the bug we're fixing.

### Tests

- `python -m unittest discover -s tests -v` — **72 tests**, all green
  (66 existing + 6 new auth helper tests).
- `ruff check .` — All checks passed.
- `mypy` — Success: no issues found in 50 source files.
- All three commands are wired into `.github/workflows/ci.yml`, so
  future PRs are blocked on the same gates.

### Follow-ups identified during this work (NOT addressed here)

- `mypy` is lenient by design. Tightening `app.services.*` (currently
  `ignore_errors = true`) would catch a few real bugs but requires a
  big typing pass on the upstream-JSON code paths.
- The CI doesn't run a real Postgres yet, so SQL changes are still
  validated only by manual scan + the unit-test fakes. A Postgres /
  TimescaleDB service container per `unit-tests` job would close that
  gap and let `tests/` reach the real `risk_checks` insert path.
- `docker-compose.yml` still has `POSTGRES_PASSWORD=your_strong_password`
  hard-coded (FastAPI changelog follow-up #2). Out of scope for this
  PR; should switch to `${POSTGRES_PASSWORD:?...}` and `.env` next.

---

## 2026-05-24 — Retries with backoff, Helius rate limit, batched risk_check inserts

### Why

Three connected reliability / performance issues:

1. **No retry/backoff on external APIs.** `DexScreenerClient` and
   `HeliusClient` swallowed errors and returned `[]` / `{}`. A single 429
   or transient 5xx silently became "no data" and the pipeline recorded a
   misleading clean analysis with no warning.
2. **Helius had no rate limiter and opened a fresh `httpx.AsyncClient`
   per call.** Wallet-manipulation, cluster, dev-flow and reverse-discovery
   all hammered Helius with no backpressure. Every call paid the TLS
   handshake cost.
3. **`risk.add_basic_risk_checks` did ~10 sequential `pool.acquire()`
   round-trips per token.** Easy 10× speedup at this layer by batching
   into one transaction with `executemany`.

### What changed

#### `app/http_utils.py` (new)

- `UpstreamUnavailable` exception — raised when retries are exhausted on
  a transient error. Lets callers distinguish "endpoint says no data"
  (e.g. 404 → `httpx.HTTPStatusError`) from "we couldn't reach upstream"
  (→ `UpstreamUnavailable`).
- `is_retryable_http_error()` — predicate for tenacity. Retries on 429,
  any 5xx, timeouts, network errors. Does **not** retry on other 4xx.
- `request_with_retry()` — wraps `httpx.AsyncClient.request()` with
  `tenacity.AsyncRetrying`, exponential backoff with random jitter
  (1s … 30s), max 5 attempts by default.

#### `app/dexscreener.py`

- One persistent `httpx.AsyncClient` is reused across calls (TLS reuse).
- `aclose()` + async context manager protocol added for clean shutdown.
- All HTTP calls go through `_get_json()` → `request_with_retry()`.
- Public methods (`get_latest_profiles`, `get_token_pairs`, …) keep
  back-compatible "log + return empty" behavior on `UpstreamUnavailable`
  so existing service callers continue to skip-and-continue.
- Added strict variants `get_token_pairs_strict()` and
  `get_preferred_token_pair_strict()` that raise `UpstreamUnavailable`.
  These are used by the ingestion pipeline so it can record a
  `data_unavailable` risk_check on persistent failure.

#### `app/helius.py`

- Same shared-client + rate-limit pattern as DexScreener. Configurable via
  `HELIUS_MIN_REQUEST_INTERVAL_SECONDS` (default 0.1).
- All HTTP and JSON-RPC calls now go through `_request()` →
  `request_with_retry()`.
- `aclose()` + async context manager added.
- Public methods now raise `UpstreamUnavailable` on persistent failure
  rather than returning silently empty results. Existing callers already
  catch broad exceptions in their per-item loops so this fails loud where
  before it failed silent.

#### `app/risk.py`

- `add_basic_risk_checks()` now builds a list of validated tuples and
  performs **one** `pool.acquire()` + transaction + `executemany`. Drops
  ~10 round-trips per ingested token to one. The function returns the
  number of rows inserted.
- New `insert_risk_checks(pool, rows)` for general-purpose batch inserts.
- New `record_data_unavailable(...)` helper writes the canonical
  `data_unavailable` risk_check row when an upstream API was reachable-
  but-broken after retries.
- `insert_risk_check()` (single-row + RETURNING) is preserved for the
  occasional caller that needs the inserted row back.

#### `app/ingest_dexscreener.py`

- Uses `get_preferred_token_pair_strict()` for the per-token pair fetch.
- On `UpstreamUnavailable`, upserts a minimal token row and writes one
  `data_unavailable` risk_check before re-raising. Result: when
  DexScreener has a bad day, you get a paper trail instead of an empty
  watchlist row that looks like "we analyzed it and found nothing."
- Closes the shared `DexScreenerClient` in `finally` so the underlying
  `httpx.AsyncClient` is released cleanly.

#### `pyproject.toml` / `requirements.txt`

- Added `tenacity>=9.0.0`.

### Backwards compatibility

- All public method signatures unchanged for DexScreener; new strict
  variants are additive.
- Helius public methods now raise `UpstreamUnavailable` instead of
  silently empty — services already catch broad exceptions per-item.
- `add_basic_risk_checks` previously returned `None`; now returns the
  count of inserted rows. No caller in the codebase reads this return
  value, so this is a non-breaking enrichment.
- `risk_checks` table schema is unchanged.

### Tests

- New `tests/test_http_utils.py`: 12 tests covering the retry predicate
  (429/5xx retried, 4xx not retried, timeouts retried) plus end-to-end
  `request_with_retry()` behavior using a fake `AsyncClient` (succeeds
  on first try, retries 429 then succeeds, retries 503 then succeeds,
  4xx propagates immediately, persistent 429 raises `UpstreamUnavailable`,
  persistent timeout raises `UpstreamUnavailable`).
- New `tests/test_risk_batch.py`: pins the batched-insert behavior with
  a fake pool — asserts `pool.acquire()` is called exactly once and that
  one `executemany` writes all 9 rows. A second test verifies low
  liquidity still emits a `DANGER` row.
- All 52 existing tests still pass (66 total).

### Follow-ups identified during this work (NOT addressed here)

- The shared-instance rate limiter only bounds requests per
  `DexScreenerClient` / `HeliusClient` instance. Several services still
  construct their own client per run, so concurrent runs can collectively
  exceed the upstream rate limit. Promoting the clients to FastAPI
  `lifespan`-managed singletons (next to the asyncpg pool) would close
  this gap.
- The "data unavailable" risk_check is recorded for the DexScreener pair
  fetch in ingest. Helius-driven services (cluster, dev-flow, wallet
  intelligence) still skip-and-continue on `UpstreamUnavailable`. They
  could record their own `data_unavailable` rows to make Helius outages
  equally visible in the dashboard.

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
- The webhook `Authorization` check still uses `==` (see Follow-ups). _Resolved in the 2026-05-24 webhook-auth + CI entry below._
- `python app/web_server.py` still works for ad-hoc runs.

### Tests

- No existing test imports `web_server`, so unit tests are unaffected.
- Migration was syntax-checked with `python -m py_compile` and smoke-imported
  to confirm the FastAPI app boots cleanly.

### Follow-ups identified during this work (NOT addressed here)

These are surfaced for future work, intentionally kept out of this change to
limit blast radius:

1. **Constant-time webhook auth.** ~~`/api/whale-signal` compares the
   `Authorization` header with `==`. Should switch to
   `hmac.compare_digest(...)` to remove a timing-attack surface.~~
   Done in `app/web_server.py:_whale_webhook_auth_ok` (2026-05-24).
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
6. **No retry/backoff on DexScreener / Helius.** ~~Transient 429/5xx is silently
   swallowed and recorded as "no data." Add `tenacity` with jitter.~~
   Done in `app/http_utils.py` + `tenacity` retry wiring (2026-05-24).

---

<!--
Kiro changelog conventions
- Newest entry on top.
- One section per change with: date heading, Why, What changed (grouped by file),
  Backwards compatibility, Tests, Follow-ups.
- Keep it honest. Note risks and follow-ups even if not addressed.
-->
