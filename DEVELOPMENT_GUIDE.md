# Quant Watchlist Platform - Development Guide

This guide is for future development and expert handoff. Keep it updated whenever the project structure, pipeline, database schema, dashboard behavior, or decision logic changes.

## Project Shape

The project is a local Solana meme-token analysis system.

Main layers:

1. Data ingestion from DexScreener, RugCheck-style sources, and Helius.
2. Analysis services that write normalized results to PostgreSQL.
3. Final decision service that combines all risk layers.
4. Local dashboard and token detail pages served by `app/web_server.py`.

## Important Files

- `pyproject.toml`: package metadata, dependencies, and console script entry points.
- `app/__init__.py`: marks `app/` as an importable Python package.
- `app/apply_migrations.py`: migration runner — tracks applied SQL in `schema_migrations` table.
- `app/http_utils.py`: shared `tenacity` retry helpers + `UpstreamUnavailable` exception used by both external API clients.
- `app/ingest_dexscreener.py`: discovers latest candidates from DexScreener profiles, ads, boosts, and community takeovers, then saves newest completed DEX pairs.
- `app/dexscreener.py`: selected pair and discovery helper logic. This is important because Pump.fun bonding pairs and later DEX pairs can coexist. The current rule skips bonding-only `pumpfun` pairs and analyzes only completed non-bonding DEX pairs.
- `app/services/market_filter_service.py`: momentum, age, activity, and dump-risk filter.
- `app/services/contract_risk_service.py`: contract/security risk analysis.
- `app/services/liquidity_filter_service.py`: liquidity depth and Liquidity Trap score.
- `app/services/wallet_analysis_service.py`: top-holder concentration.
- `app/services/cluster_analysis_service.py`: Helius funding-source cluster detection.
- `app/services/wallet_intelligence_service.py`: wallet labels, early buyer profit map, fresh wallets, snipers, bots, whales, dumpers.
- `app/services/wallet_manipulation_service.py`: shared funders, token splitters, wallet links, coordinated dumps.
- `app/services/dev_wallet_audit_service.py`: developer wallet sell/transfer/no-balance audit.
- `app/services/dev_wallet_flow_service.py`: bounded developer flow graph, proxy dump detection, splitter detection, and Shadow Dev Score.
- `app/services/whale_discovery_service.py`: Whale Radar discovery from tracked profitable wallet-intelligence trades.
- `app/services/whale_reverse_discovery_service.py`: Reverse Profit Discovery from recent DexScreener gainers, Helius pair signatures, early buyers, and estimated PnL.
- `app/services/whale_consistency_auditor_service.py`: audits elite wallet consistency from recent Helius transactions.
- `app/services/whale_price_refresh_service.py`: refreshes tracked whale trade prices with DexScreener bulk requests.
- `app/services/whale_webhook_service.py`: creates/updates the Helius webhook watcher for elite wallets.
- `app/services/whale_survival_service.py`: Survival Intelligence profiles, survival rate, rug detection, whale style, exit style, and security level.
- `whale_signal_analysis_jobs`: queue/audit table for token analyses triggered by whale live signals.
- `app/services/whale_signal_service.py`: receiver/storage logic for live whale webhook signals.
- `app/whale_scoring_logic.py`: elite wallet reliability scoring algorithm.
- `app/services/watchlist_decision_service.py`: final decision, decision tree, Insider Probability.
- `app/web_server.py`: local API, dashboard serving, scan monitor state.
- `app/static/dashboard.html`: main dashboard UI.
- `app/static/whale_radar.html`: Whale Radar leaderboard and live signal UI.
- `app/static/token_detail.html`: token detail UI, decision tree, wallet tables, timeline.
- `migrations/*.sql`: database schema.
- `tests/*.py`: unit tests for risk logic and service rules.
- `PROJECT_OVERVIEW.md`: expert-level architecture and current behavior.
- `PROJECT_ACHIEVEMENTS.md`: completed features and current state.
- `README.md`: quick setup and commands.

## Package Structure and Imports

The project is an installable Python package defined by `pyproject.toml`.

```
pip install -e .          # editable install — all console scripts become available
memeco-server             # start the dashboard/API server
memeco-ingest             # run DexScreener ingestion
memeco-pipeline           # run the full analysis pipeline
memeco-migrate            # apply pending database migrations
memeco-migrate --dry-run  # show pending migrations without applying
```

All internal imports use **absolute paths** rooted at the `app` package:

```python
from app.db import create_pool
from app.services.watchlist_decision_service import run_watchlist_decision_service
from app.whale_scoring_logic import WhaleTrade
```

Do NOT use bare imports like `from db import ...` or `from services.xxx import ...`.
Do NOT add `try/except ModuleNotFoundError` import fallbacks.

## Migrations

SQL migration files live in `migrations/`. The runner (`app/apply_migrations.py`)
tracks which have been applied via a `schema_migrations` table (version, filename,
SHA-256 checksum, applied_at).

To add a new migration:

1. Create `migrations/NNN_description.sql` (number it sequentially).
2. Write idempotent SQL when possible (`IF NOT EXISTS`, etc.).
3. Run `memeco-migrate` — it applies only new files in filename order.
4. The tool detects TimescaleDB-specific statements and runs them outside an
   explicit transaction block when necessary.

## Development Rules

- Keep the dashboard light. The main `/api/watchlist` endpoint should return compact fields only.
- Put heavy data on the token detail endpoint, not on the dashboard list.
- Do not remove public tables just because they look old. First check whether token detail pages, decision trees, raw audit history, or tests use them.
- When adding a new signal, store both:
  - machine-readable status/score fields
  - human-readable reason/warnings
- Prefer explicit statuses over free text. Example: `LIQUIDITY_TRAP_HIGH` is better than only `"liquidity looks bad"`.
- Keep scores bounded:
  - normalized contract risk: 0 to 10
  - manipulation score: 0 to 10
  - insider probability: 0 to 100
  - liquidity trap: 0 to 100
  - shadow dev score: 0 to 100
- Do not claim timeline events are complete chain truth unless the code actually indexes all transactions. Use labels like "tracked holder" when events come from sampled top-holder analysis.
- Do not turn developer flow into unlimited recursion. Keep graph tracking bounded by depth, top recipients, and minimum amount thresholds unless it moves to a background job with caching.

## Adding A New Filter

1. Create or update a service in `app/services/`.
2. Add a migration if the result needs a new table or new columns.
3. Add a `run_*.py` wrapper if it should run independently.
4. Add the service to `app/run_analysis_pipeline.py` and to `app/web_server.py` scan flow when needed.
5. Add result fields to `watchlist_decision_service.py`.
6. Add dashboard or token detail UI only after the backend result is stable.
7. Add tests for the scoring/status rules.
8. Update:
   - `README.md`
   - `PROJECT_OVERVIEW.md`
   - `PROJECT_ACHIEVEMENTS.md`
   - this file

## Dashboard Rules

- Main dashboard should show summary signals only.
- Token detail page should carry the heavy evidence.
- Keep the UI full dark unless intentionally changing the visual direction.
- Keep cards and panels at 8px radius.
- If a value is approximate, say so in the label or tooltip.
- If data is missing, show `N/A`, `Unknown`, or `Pending`; do not fake a value.

## Performance Rules

- Avoid loading full wallet histories on dashboard page load.
- Avoid sending full `watchlist_decisions.details` in `/api/watchlist`.
- Keep DexScreener scans bounded with `DEXSCREENER_MAX_DISCOVERY_CANDIDATES`, `DEXSCREENER_MAX_LATEST_TOKENS`, and `DEXSCREENER_MIN_REQUEST_INTERVAL_SECONDS`.
- Keep Whale Reverse Discovery bounded with `WHALE_TOP_GAINER_LIMIT`, `WHALE_TOP_GAINER_CANDIDATE_POOL`, `WHALE_SIGNATURE_LIMIT`, and `WHALE_EARLY_BUYER_LIMIT`.
- Keep Wallet Consistency Auditor bounded with `WHALE_AUDIT_WALLET_LIMIT` and `WHALE_AUDIT_TX_LIMIT`.
- Never configure Helius webhooks with localhost. Use a public HTTPS tunnel and set `WHALE_WEBHOOK_URL`.
- Cache or reuse wallet analysis when possible before expanding top-holder graph depth.
- Helius-heavy analysis should stay bounded or move to background jobs.
- Relationship and raw snapshot tables can grow quickly; use retention or pagination before deleting data.
- `token_prices` and `raw_api_snapshots` are TimescaleDB hypertables (see
  `migrations/012_timescale_hypertables.sql`). Retention policies drop raw
  rows after 30 / 14 days respectively. Long-range price history is kept in
  the `token_prices_hourly` continuous aggregate, not in the raw table.
  When adding features that need older raw price rows, query the continuous
  aggregate instead of extending retention.

## External API Calls

External clients (`DexScreenerClient`, `HeliusClient`) live in `app/dexscreener.py`
and `app/helius.py`. They share these conventions:

- One persistent `httpx.AsyncClient` per instance (TLS handshake reused).
  Use the client as an async context manager (`async with HeliusClient() as h:`)
  or call `await client.aclose()` in a `finally` block to release sockets.
- Outgoing requests pass through a shared rate limiter. Tunable via
  `DEXSCREENER_MIN_REQUEST_INTERVAL_SECONDS` (default 0.35) and
  `HELIUS_MIN_REQUEST_INTERVAL_SECONDS` (default 0.1).
- Transient failures (429 / 5xx / timeouts / network errors) are retried
  with exponential backoff and jitter via `tenacity`, configured in
  `app/http_utils.py`. After ~5 attempts the call raises `UpstreamUnavailable`.
- 4xx errors other than 429 are **not** retried — they propagate as
  `httpx.HTTPStatusError`.
- When ingesting data and the upstream is unreachable, write one
  `data_unavailable` risk_check row via `risk.record_data_unavailable(...)`
  instead of silently producing an empty analysis. The DexScreener path
  in `app/ingest_dexscreener.py` is the canonical example.

## Database Write Performance

- Bulk inserts: prefer one `pool.acquire()` + transaction + `executemany`
  over a loop of individual `await conn.execute(...)` calls. Each
  `pool.acquire()` is a round-trip; the difference is 10× at the per-token
  ingest level. See `risk.add_basic_risk_checks()` and
  `risk.insert_risk_checks()` for the pattern.

## Current API Surface

- `GET /api/health`
- `GET /api/summary`
- `GET /api/watchlist?limit=100`
- `GET /api/watchlist?status=WATCHLIST_PASS,WATCHLIST_REVIEW` (multi-select via comma-separated values)
- `GET /api/token-detail?run_id=<id>&token_id=<id>`
- `GET /api/runs`
- `GET /api/scan/status`
- `GET /api/events` — Server-Sent Events stream of scan-state and scan-step events
- `GET /api/whale-radar?limit=N&wallet=<address>`
- `GET /api/wallet-detail?wallet=<address>`
- `GET /api/system` — operational telemetry: API config, activity, retention, errors
- `POST /api/scan`
- `POST /api/analyze-token`
- `POST /api/whale-signal` (Helius webhook receiver)
- `POST /api/whale-radar/audit`
- `POST /api/whale-radar/refresh-prices`
- `POST /api/whale-radar/sync-webhook`
- `POST /api/whale-radar/survival`

Browser pages (all served by FastAPI lifespan):

| Path           | Page                                               |
|----------------|----------------------------------------------------|
| `/`            | dashboard.html — COMMAND BRIDGE / SIGNAL FLOOR     |
| `/whale-radar` | whale_radar.html — RADAR CONSOLE                   |
| `/wallet`      | wallet_detail.html — WALLET DOSSIER (PnL tiers)    |
| `/token`       | token_detail.html — CASE FILE / DECISION DOSSIER   |
| `/system`      | system.html — OPS DECK                             |

Whale live-signal behavior:

- `BUY` and `TOKEN_IN` signals from tracked non-risky wallets can queue automatic token analysis.
- Existing watchlist decisions prevent duplicate analysis jobs.
- Job status is shown in Whale Radar under Whale Signal Auto Analysis.
- Whale Radar UI is intentionally an operations board: system/webhook status first, then metrics, elite-wallet leaderboard, Live Feed signal cards, and auto-analysis jobs.
- Leaderboard wallet rows are interactive: clicking one filters Live Feed through `/api/whale-radar?wallet=<address>`, while copy buttons must stop row-click propagation.
- Wallet addresses shown in Whale Radar should keep both a copy action and a Solscan account link for quick manual review.
- Wallet detail pages live at `/wallet?wallet=<address>` and should remain read-only, fast, and based on `elite_wallets`, `whale_survival_profiles`, `whale_performance_tracking`, and `live_whale_signals`.
- Keep raw Live Feed available for investigation, but show trading candidates through `High Signal Alerts` so tiny SOL/USDC/USDT routing noise does not look like an opportunity.
- Relevant thresholds are configurable with `WHALE_SIGNAL_ALERT_MIN_SOL`, `WHALE_SIGNAL_ALERT_MIN_SCORE_10`, and `WHALE_SIGNAL_AUTO_ANALYZE_MIN_SOL`.
- `Token Confluence` should stay stricter than raw Live Feed: it should only group filtered non-noise buy/token-in signals and is controlled by `WHALE_CONFLUENCE_MIN_WALLETS` and `WHALE_CONFLUENCE_WINDOW_HOURS`.

## Testing Checklist

Install dev tools once:

```powershell
pip install -e ".[dev]"
```

Run the same gates that CI runs:

```powershell
python -m unittest discover -s tests -v   # unit tests
ruff check .                               # lint
mypy                                       # type check (config in pyproject.toml)
```

CI (`.github/workflows/ci.yml`) runs these on every push and pull request
against `main`. Unit tests are exercised on Python 3.10, 3.11, and 3.12;
ruff and mypy run once on 3.12. PRs that fail any gate are blocked.

Manual checks:

- Open `http://127.0.0.1:8000`.
- Confirm dashboard loads without JavaScript errors.
- Confirm Scan Monitor and system load gauge render.
- Open one token detail page.
- Confirm decision tree, timeline, wallet labels, relationships, and early buyer map render.
- Use `Refresh Analysis` on a token detail page when API keys/database are ready, then confirm `Change Signals` appear after the latest run opens.
- Paste a token address into manual analysis only when API keys/database are ready.

## Expert Handoff Checklist

When consulting an expert, send these files:

- `README.md`
- `PROJECT_OVERVIEW.md`
- `PROJECT_ACHIEVEMENTS.md`
- `DEVELOPMENT_GUIDE.md`
- `migrations/001_initial_schema.sql`
- all later migration files in `migrations/`
- relevant service files from `app/services/`
- dashboard files if asking about UX:
  - `app/static/dashboard.html`
  - `app/static/token_detail.html`

Also include:

- what question you want answered
- one example token address
- one screenshot of the dashboard or token detail issue
- whether the result should prioritize speed, accuracy, or deeper wallet coverage

## Known Future Improvements

### Vite SPA refactor (complete — all five pages migrated)

The four interactive pages plus the system page now ship from a Vite
build. The legacy monolithic HTML files in `app/static/` remain on
disk as a safety net (`_vite_or_static` falls back to them if a Vite
build is missing) and can be retired once the Vite build is verified
in production for a few releases.

#### Layout

```
web/
├── package.json            (Vite 7.x dependency, scripts)
├── package-lock.json
├── vite.config.js          (multi-page input map, base="/static/dist/")
├── src/
│   ├── styles/
│   │   ├── tokens.css      (cyberpunk design tokens)
│   │   └── cyberpunk.css   (shared utility classes & layout primitives)
│   ├── lib/
│   │   ├── api.js          (fetch wrappers for /api/*)
│   │   ├── time.js         (timeAgo, timeAgoShort, formatDate)
│   │   ├── dom.js          (h`` tagged template, raw(), mount(), escapeHtml)
│   │   └── format.js       (numberOrNull, formatNumber/Money/Percent/Sol,
│   │                        formatSignedPercent, shortAddress, parseDetails)
│   ├── components/
│   │   ├── BrandBar.js     (sticky page header — accepts `extraActive`
│   │   │                    for deep-link pages like wallet/token)
│   │   ├── TierEmblem.js   (tierForPnl + inline SVG art for the wallet page)
│   │   ├── OpsHud.js       (KPI HUD strip)
│   │   ├── OpsTable.js     (cyberpunk-styled table)
│   │   ├── ApiPill.js      (live "Updated 5s ago" pulse)
│   │   └── ErrorCard.js    (red-edge failure card)
│   └── pages/
│       ├── system/         (Ops Deck — reference migration)
│       ├── wallet/         (WALLET DOSSIER + tier emblem)
│       ├── token/          (CASE FILE / DECISION DOSSIER)
│       ├── whale/          (RADAR CONSOLE)
│       └── dashboard/      (COMMAND BRIDGE / SIGNAL FLOOR)
└── dist/                   (build output — gitignored)
    ├── pages/<slug>/index.html
    └── assets/<entry>-<hash>.{js,css,map}
```

Vite automatically extracts shared code into chunks (`BrandBar-*.js`,
`format-*.js`, `api-*.js`, `dom-*.js`), so the five pages share a
single ~7 KB vendor bundle instead of duplicating helpers.

#### How FastAPI integrates

`app/web_server.py` holds the wiring. Two pieces matter:

1. `_vite_or_static(page_slug, legacy_filename)` — the page route
   helper. If `web/dist/pages/<slug>/index.html` exists it is served;
   otherwise the legacy `app/static/<filename>` is served. So if the
   Vite build is missing for any reason (e.g. a fresh checkout that
   hasn't run `npm run build`), the page keeps working from the
   legacy file.
2. `/static/dist/{path}` route — serves any file under `web/dist/`
   with the same content-type whitelist as `/static/{path}`. That is
   what resolves the hashed `<script src="/static/dist/assets/…">`
   tags emitted by Vite.

All five page routes (`/`, `/token`, `/whale-radar`, `/wallet`,
`/system`) call `_vite_or_static`.

#### Migration approach for the dashboard

The other four pages were rewritten cleanly using the shared helpers
and components. The dashboard is the most complex page (auto-refresh,
SSE, decision drawer, multi-select chips, sort, tape/cockpit views,
starred-token notifications, keyboard nav, density toggle, sparklines)
so its migration was deliberately conservative: the entire `<style>`
block and the entire `<script>` body from the legacy file were lifted
verbatim into `web/src/pages/dashboard/{dashboard.css, index.js}`. A
small prelude in `index.js` builds a `window.MemecoUtils` shim from
the shared `format.js`/`time.js`/`dom.js` modules so the lifted code
keeps working without changes. This guarantees pixel-for-pixel and
behavior-for-behavior parity with the legacy page. A future cleanup
can refactor the lifted body into shared components incrementally.

#### Build / dev workflow

```bash
# one-time install
cd web && npm install

# production build (used by FastAPI + CI)
npm run build

# dev server with HMR — proxies /api to FastAPI on :8000
npm run dev
```

The `web-build` job in `.github/workflows/ci.yml` runs `npm ci &&
npm run build` and verifies every page's entry chunks exist.

#### Retiring the legacy pages (future)

Once the Vite versions have been in production for long enough that
a regression would have surfaced, the legacy `app/static/*.html`
files plus the `_vite_or_static` fallback can be removed in one
commit. Until then, both paths are maintained and a quick rollback
is one route flip away.

### Other deferred items

- Add persistent token history and alert on dangerous change.
- Add caching for repeated wallet intelligence requests.
- Add paginated wallet graph expansion.
- Add a dedicated system/errors page for API failures.
- Add background discovery jobs for new and upcoming tokens.
