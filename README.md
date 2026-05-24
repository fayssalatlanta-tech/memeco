# Quant Watchlist Platform

Backend pipeline and local dashboard for screening early Solana meme tokens.

## What It Does

The project ingests DexScreener token data, runs market, contract-risk, liquidity, wallet-distribution, cluster funding-source, wallet-intelligence, and wallet-manipulation filters, then writes final watchlist decisions.

The token detail page includes a `Why Rejected?` decision tree so every rejected token shows which layer failed: Market, Contract, Liquidity, Liquidity Trap, Wallet, Cluster, Manipulation, Intelligence, Insider Probability, and the final decision.

The main dashboard is optimized to stay light: it uses a full-dark UI, loads compact watchlist rows, shows 1h/4h/24h price movement chips from stored price snapshots, and leaves heavy wallet/decision evidence for the token detail page.

`Scan Monitor` includes a speedometer-style system load gauge. It shows whether the system is light, active, heavy, or in a problem state based on scan activity, running pipeline steps, elapsed scan time, and errors.

The token detail timeline is evidence-based: it shows stored pair/profile/price timestamps, tracked top-holder wallet events, observed DexScreener promotion, and final decision time. It does not claim to know the first buyer unless that buyer is inside the tracked wallet set.

Pipeline:

1. DexScreener ingestion
2. Market filter
3. RugCheck contract-risk filter
4. Liquidity filter
5. Liquidity Trap score
6. Wallet concentration analysis
7. Cluster funding-source analysis
8. Wallet intelligence labels, including fresh top-holder wallets
9. Wallet manipulation analysis
10. Dev wallet audit
11. Dev wallet flow / Shadow Dev Score
12. Insider Probability score
13. Final watchlist decision
14. Local dashboard/API

## Setup

Start PostgreSQL/TimescaleDB:

```powershell
docker compose up -d
```

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

Apply the database schema:

```powershell
docker cp migrations\001_initial_schema.sql quant_db:/tmp/001_initial_schema.sql
docker exec quant_db psql -U admin -d quant_intelligence -v ON_ERROR_STOP=1 -f /tmp/001_initial_schema.sql
```

Apply later migrations in order when new features are added:

```powershell
Get-Content migrations\007_dev_wallet_flow.sql | docker exec -i quant_db psql -U admin -d quant_intelligence -v ON_ERROR_STOP=1
Get-Content migrations\008_whale_radar.sql | docker exec -i quant_db psql -U admin -d quant_intelligence -v ON_ERROR_STOP=1
Get-Content migrations\009_whale_reverse_discovery.sql | docker exec -i quant_db psql -U admin -d quant_intelligence -v ON_ERROR_STOP=1
```

For cluster analysis, set a Helius key in `.env`:

```text
HELIUS_API_KEY=your_key_here
```

DexScreener ingestion is intentionally rate-limited so the API is not hit too aggressively:

```text
DEXSCREENER_MAX_LATEST_TOKENS=10
DEXSCREENER_MAX_DISCOVERY_CANDIDATES=40
DEXSCREENER_MIN_REQUEST_INTERVAL_SECONDS=0.35
```

`DEXSCREENER_MAX_LATEST_TOKENS` defaults to `10` and has a hard cap of `30`. Increase it carefully.
`DEXSCREENER_MAX_DISCOVERY_CANDIDATES` defaults to `40` and has a hard cap of `120`; it controls how many fresh DexScreener candidates are checked for completed DEX pairs before saving the newest ones.

The ingestion step combines official DexScreener latest profiles, ads, boosts, and community takeovers, then only saves completed, non-bonding DEX pairs. Pump.fun bonding-only pairs are skipped, so the dashboard focuses on tokens that have actually entered a DEX.

## Run The Pipeline

Ingest fresh DexScreener data:

```powershell
python app\ingest_dexscreener.py
```

Run the analysis pipeline on stored data:

```powershell
python app\run_analysis_pipeline.py
```

From the dashboard, you can also paste one Solana token address and click `Analyze Token`. The system creates a fresh run for that token and analyzes it like the other dashboard tokens.

From a token detail page, click `Refresh Analysis` to re-run analysis for that token. After the new run finishes, the page opens the latest result and shows `Change Signals` comparing important fields against the previous analysis.

Run wallet analysis only:

```powershell
python app\run_wallet_analysis.py
```

Run cluster analysis only:

```powershell
python app\run_cluster_analysis.py
```

Run wallet intelligence only:

```powershell
python app\run_wallet_intelligence.py
```

Run wallet manipulation only:

```powershell
python app\run_wallet_manipulation.py
```

Run developer wallet audit only:

```powershell
python app\run_dev_wallet_audit.py
```

Run developer wallet flow only:

```powershell
python app\run_dev_wallet_flow.py
```

Run Whale Radar discovery from existing wallet-intelligence PnL:

```powershell
python app\run_whale_discovery.py
```

Elite reliability score is calculated in `app/whale_scoring_logic.py`:

```text
Score = (Win Rate * 0.35) + (ROI * 0.25) + (Early Entry * 0.20) + (Consistency * 0.20)
```

The internal score is `0-100`, and the dashboard also shows the same score as `0-10`.

Run Whale Reverse Profit Discovery from recent DexScreener gainers and early Helius pair transactions:

```powershell
python app\run_whale_reverse_discovery.py
```

Audit tracked whale wallets for consistency using the latest 20-50 Helius transactions:

```powershell
python app\run_whale_consistency_audit.py
```

Refresh tracked whale trade prices with DexScreener bulk requests:

```powershell
python app\run_whale_price_refresh.py
```

Build Whale Survival Intelligence profiles:

```powershell
python app\run_whale_survival.py
```

Sync elite wallets into a Helius webhook watcher:

```powershell
python app\run_whale_webhook_sync.py
```

When Helius sends a watched-wallet `BUY` or `TOKEN_IN` event to `/api/whale-signal`, the server now queues automatic token analysis if the token has not already been analyzed and the wallet is not bot/risky.

Helius webhooks require a public HTTPS URL, not `localhost`. Use a tunnel and set:

```text
WHALE_WEBHOOK_URL=https://your-public-url.example.com/api/whale-signal
WHALE_WEBHOOK_AUTH_HEADER=your-secret-header
WHALE_WEBHOOK_TRANSACTION_TYPES=SWAP
```

Useful limits for this heavier workflow:

```text
WHALE_TOP_GAINER_LIMIT=10
WHALE_TOP_GAINER_CANDIDATE_POOL=30
WHALE_SIGNATURE_LIMIT=180
WHALE_EARLY_BUYER_LIMIT=50
WHALE_MIN_PROFIT_SOL=10
WHALE_TOP_GAINER_MAX_AGE_HOURS=24
WHALE_AUDIT_WALLET_LIMIT=50
WHALE_AUDIT_TX_LIMIT=50
```

## Run The Dashboard

```powershell
python app\web_server.py
```

Open:

```text
http://127.0.0.1:8000
```

API endpoints:

```text
GET /api/health
GET /api/summary
GET /api/watchlist?limit=100
GET /api/watchlist?status=WATCHLIST_PASS
GET /api/runs
GET /api/whale-radar
GET /api/wallet-detail?wallet=<address>
POST /api/analyze-token
POST /api/whale-signal
POST /api/whale-radar/audit
POST /api/whale-radar/refresh-prices
POST /api/whale-radar/sync-webhook
```

For a full expert handoff, read:

```text
PROJECT_OVERVIEW.md
PROJECT_ACHIEVEMENTS.md
DEVELOPMENT_GUIDE.md
```

When changing the project, keep those three files updated so another developer or trading-systems expert can understand the current state quickly.

## Tests

```powershell
python -m unittest discover -s tests -v
```
