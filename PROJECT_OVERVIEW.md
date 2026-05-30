# Quant Watchlist Platform - Expert Overview

This project is a local Solana meme-token analysis platform. It ingests early token data, enriches it with risk and wallet intelligence, then shows final decisions on a local dashboard.

The core idea is not only to ask "is the token early?" but also "who owns it?", "who funded those wallets?", "are wallets linked?", and "is the token being promoted on DexScreener?"

## Runtime

- Language: Python
- Database: PostgreSQL/TimescaleDB via Docker
- Dashboard: local static HTML served by `app/web_server.py`
- Main external data sources:
  - DexScreener API
  - RugCheck API
  - Helius Enhanced Transactions API

The local dashboard runs at:

```text
http://127.0.0.1:8000
```

For future development rules and expert handoff instructions, read `DEVELOPMENT_GUIDE.md`.

## Current Pipeline

1. `app/ingest_dexscreener.py`
   - Pulls latest Solana candidates from DexScreener token profiles, ads, boosts, and community takeovers.
   - Checks candidates using `DEXSCREENER_MAX_DISCOVERY_CANDIDATES`, default `40`, hard cap `120`.
   - Saves the newest completed pairs using `DEXSCREENER_MAX_LATEST_TOKENS`, default `10`, hard cap `30`.
   - Uses `DEXSCREENER_MIN_REQUEST_INTERVAL_SECONDS`, default `0.35`, to avoid hitting DexScreener too aggressively.
   - Fetches token pairs, selects the preferred analysis pair, and sorts completed candidates by `pairCreatedAt` newest first.
   - Pair selection requires a completed non-bonding DEX pair. `pumpfun` is treated as bonding and skipped, while `pumpswap`, Raydium, Orca, and other DEX IDs are treated as DEX-listed pairs.
   - Saves token, pair, price, raw snapshots, and DexScreener paid order snapshots.

2. `app/services/market_filter_service.py`
   - Checks early status, age, price/volume behavior, and dump risk.
   - Produces `MARKET_PASS`, `MARKET_PASS_HIGH_RISK`, or market rejection statuses.

3. `app/services/contract_risk_service.py`
   - Uses RugCheck-style contract/security data.
   - Tracks mint/freeze authority, warnings, raw risk score, and holder concentration.

4. `app/services/liquidity_filter_service.py`
   - Checks liquidity size, market-cap-to-liquidity ratio, and volume-to-liquidity ratio.
   - Calculates `Liquidity Trap` score from 0 to 100.
   - Detects liquidity that exists but is too shallow for the market cap, too small for active volume, or has unknown LP lock/burn status.

5. `app/services/wallet_analysis_service.py`
   - Extracts top holders.
   - Measures holder concentration:
     - top holder %
     - top 10 %
     - top 20 %

6. `app/services/cluster_analysis_service.py`
   - Uses Helius transactions to find the SOL funding source of top holders.
   - Detects shared funder clusters.

7. `app/services/wallet_intelligence_service.py`
   - Labels individual wallets:
     - `SMART_WALLET`
     - `FRESH_WALLET`
     - `SNIPER`
     - `WHALE`
     - `DUMPER`
     - `DEV_RELATED`
     - `BOT`
     - `UNKNOWN`
   - Stores label reasons inside `details.label_reasons`.

8. `app/services/wallet_manipulation_service.py`
   - Detects deeper wallet manipulation patterns:
     - shared SOL funder
     - token splitter/distributor
     - direct links between top holders
     - coordinated dump in a short time window
   - Produces:
     - `MANIPULATION_PASS`
     - `MANIPULATION_WARNING`
     - `MANIPULATION_DANGER`
     - `MANIPULATION_UNKNOWN`
   - Uses a 0-10 manipulation score.

9. `app/services/dev_wallet_audit_service.py`
   - Extracts the developer/creator wallet from RugCheck raw data.
   - Uses Helius transactions to estimate:
     - tokens received by the developer
     - tokens sold through swaps
     - tokens transferred out to other wallets
     - current creator balance from RugCheck
   - Produces:
     - `DEV_HOLDING`
     - `DEV_SOLD_PARTIAL`
     - `DEV_SOLD_OUT`
     - `DEV_TRANSFERRED_TOKENS`
     - `DEV_NO_BALANCE`
     - `DEV_UNKNOWN`

10. `app/services/dev_wallet_flow_service.py`
   - Tracks developer token flow across bounded degrees of separation.
   - Uses a strict graph budget: max depth 2, top 20 direct recipients, top 20 second-degree recipients, and a 0.5% minimum received amount threshold.
   - Detects `DEV_DIRECT_SHIELD`, `DEV_PROXY_DUMP`, `DEV_SPLITTER_DETECTED`, and `DEV_SECOND_DEGREE_RECIPIENT`.
   - Produces `Shadow Dev Score` from 0 to 100.

11. `app/services/watchlist_decision_service.py`
   - Combines all filters into the final decision:
     - `WATCHLIST_PASS`
     - `WATCHLIST_PASS_HIGH_RISK`
     - `WATCHLIST_REVIEW`
     - `WATCHLIST_WAIT_*`
     - `WATCHLIST_REJECT_*`
   - Stores a decision-tree payload in `watchlist_decisions.details` so the token detail page can explain every layer, not only the final rejection reason.
   - Calculates `Insider Probability` from cluster size, manipulation score, sniper wallets, top holder %, and top 10 holder %.

12. `app/web_server.py`
   - Serves dashboard, token detail pages, scan status, and JSON APIs.
   - Keeps the dashboard fast by returning compact watchlist rows from `/api/watchlist`; full decision details are loaded only on token detail pages.

13. `app/services/whale_discovery_service.py`
   - Builds the first version of Whale Radar from existing wallet-intelligence PnL evidence.
   - Scores wallets with `app/whale_scoring_logic.py` using win rate, ROI, early entry, consistency, dust filtering, and bot exclusion.
   - Reliability formula: `Score = (W * 0.35) + (R * 0.25) + (E * 0.20) + (C * 0.20)`, where W is win rate, R is average ROI capped at 500%, E is early entry timing, and C is 30-day SOL profit consistency capped at 100 SOL.
   - The internal score is `0-100`; UI can display it as `0-10` by dividing by 10.
   - Stores elite wallets, historical trade evidence, and live whale signals.
   - The Helius webhook receiver is available at `POST /api/whale-signal`; automated remote webhook registration is intentionally left for a later integration step.

14. `app/services/whale_reverse_discovery_service.py`
   - Adds the Reverse Profit Discovery path for Whale Radar.
   - Selects recent completed DexScreener pairs from the local database, refreshes them with the official DexScreener batch token endpoint, then ranks them by `priceChange.h24`.
   - Uses Helius `getSignaturesForAddress` against the selected pair address, loads enhanced transactions in bounded batches, and extracts the first 50-100 early buyers.
   - Estimates buyer PnL from SOL spent, SOL received, remaining token balance, and current DexScreener `priceNative`.
   - Promotes wallets with profit above `WHALE_MIN_PROFIT_SOL` into `elite_wallets` and stores trade evidence with source `reverse_profit_discovery`.
   - Keeps limits configurable through `WHALE_TOP_GAINER_LIMIT`, `WHALE_TOP_GAINER_CANDIDATE_POOL`, `WHALE_SIGNATURE_LIMIT`, `WHALE_EARLY_BUYER_LIMIT`, and `WHALE_TOP_GAINER_MAX_AGE_HOURS`.

15. `app/services/whale_consistency_auditor_service.py`
   - Audits existing elite wallets using the latest Helius enhanced transactions.
   - Builds token positions from wallet token/native transfers, refreshes prices through DexScreener bulk requests, and recalculates win rate, ROI, and reliability score.
   - Keeps bot/dust rules from `app/whale_scoring_logic.py` and writes audit evidence with source `wallet_consistency_audit`.

16. `app/services/whale_webhook_service.py`
   - Creates or updates one Helius enhanced webhook for all watched elite wallets.
   - Requires `WHALE_WEBHOOK_URL` to be a public HTTPS endpoint; Helius cannot deliver to `localhost`.
   - Optional `WHALE_WEBHOOK_AUTH_HEADER` is stored and verified by `POST /api/whale-signal`.

17. `app/services/whale_price_refresh_service.py`
   - Uses DexScreener `/tokens/v1/{chainId}/{tokenAddresses}` in batches of up to 30 tokens.
   - Updates current price/value fields on `whale_performance_tracking` for more realistic Shadow Performance.

18. `app/services/whale_survival_service.py`
   - Builds Whale Survival Intelligence profiles from `whale_performance_tracking`.
   - Calculates Survival Rate, rugged trade count, whale style, exit style, laddering score, favorite symbols, warning flags, and security level.
   - Marks profiles as `SAFE_TO_WATCH`, `RISKY`, `INSIDER_RISK`, or `UNPROVEN`.

19. Whale signal auto-analysis
   - `POST /api/whale-signal` stores live whale events and automatically queues token analysis for watched-wallet `BUY` or `TOKEN_IN` events.
   - Duplicate guard: if a token already has a watchlist decision, no new analysis job is created.
   - Jobs are stored in `whale_signal_analysis_jobs` and shown on Whale Radar.
   - The Whale Radar page is a full-dark operations board with system/webhook status, metrics, a leaderboard, Live Feed signal cards, and auto-analysis job cards.
   - Clicking a leaderboard wallet filters the Live Feed to that wallet's captured movements. Wallet and token addresses can be copied from the UI, wallet rows include Solscan account links, and token logos are shown when a stored DexScreener profile icon exists.
   - `High Signal Alerts` is a filtered layer above the raw Live Feed. It keeps only meaningful BUY/TOKEN_IN events from reliable non-risky wallets, above `WHALE_SIGNAL_ALERT_MIN_SOL`, above `WHALE_SIGNAL_ALERT_MIN_SCORE_10`, and excludes SOL/USDC/USDT noise tokens.
   - Auto-analysis ignores SOL/USDC/USDT and movements below `WHALE_SIGNAL_AUTO_ANALYZE_MIN_SOL`.
   - `Token Confluence` groups filtered live signals by token and highlights tokens entered by multiple watched wallets within `WHALE_CONFLUENCE_WINDOW_HOURS`.
   - `/wallet?wallet=<address>` shows a GMGN-inspired wallet detail page with PnL, win rate, reliability, survival/security, ROI buckets, buy-size buckets, tracked trades, live signals, and open holdings.

## Important Decision Priority

The final decision is intentionally ordered. Earlier filters can stop the decision before later filters:

1. Market filter
2. Contract risk
3. Liquidity
4. Wallet concentration
5. Cluster analysis
6. Wallet manipulation
7. Wallet intelligence
8. Final pass/high-risk/review

Example: if a token is already rejected by Market, the dashboard shows `WATCHLIST_REJECT_MARKET` even if Wallet Intelligence also finds bots or dumpers.

## Wallet Intelligence Rules

Current rules are heuristic and intentionally conservative.

- `WHALE`: holder owns at least 5%, or is a top 3 holder with at least 1.5%.
- `FRESH_WALLET`: oldest seen wallet transaction is less than 24 hours old and the fetched history does not look truncated.
- `SNIPER`: first token entry within 60 seconds after launch.
- `DUMPER`: wallet sold at least 65% of received tokens, or has negative net flow with meaningful selling.
- `DEV_RELATED`: wallet shares a funding source with other top holders.
- `BOT`: many DEX-like transactions, burst activity, or high transaction rate.
- `SMART_WALLET`: positive net position, low sell ratio, no bot/dev/sniper/dumper signals.

Wallet score ranges from -10 to +10.

## Wallet Manipulation Rules

This layer tries to detect fake distribution and coordinated movement.

Signals:

- `SHARED_FUNDER_CLUSTER`: multiple top holders funded by the same wallet.
- `TOKEN_SPLITTER`: one wallet distributed the target token to multiple top holders.
- `LINKED_TOP_HOLDERS`: top holders directly sent SOL or token to each other.
- `COORDINATED_DUMP`: multiple top/linked wallets sold within 10 minutes.

Score:

- 0-2: `MANIPULATION_PASS`
- 3-6: `MANIPULATION_WARNING`
- 7-10: `MANIPULATION_DANGER`

The current implementation scans the latest run, top 3 holders, and 30 transactions per holder for speed. This is a practical first version. It can later be expanded with background jobs and pagination.

## Insider Probability

`Insider Probability` is a 0-100 heuristic score shown on the dashboard and token detail page. It estimates the chance that a token has insider-controlled distribution.

Inputs:

- Cluster analysis: shared funding-source cluster size and cluster status.
- Wallet manipulation: 0-10 manipulation score and manipulation status.
- Dev wallet audit: whether the developer sold, transferred, or has no remaining creator balance.
- Snipers: number of top-holder wallets labeled `SNIPER`.
- Fresh wallets: number of top-holder wallets labeled `FRESH_WALLET`.
- Top holders: top holder % and top 10 holder %.

Levels:

- 0-24: `LOW`
- 25-49: `MEDIUM`
- 50-74: `HIGH`
- 75-100: `CRITICAL`

## Liquidity Trap

`Liquidity Trap` is a 0-100 score inside the liquidity filter. It answers: "Does liquidity exist, but look dangerous or easy to trap buyers with?"

Inputs:

- Liquidity depth in USD.
- Market-cap-to-liquidity ratio.
- Volume-to-liquidity ratio.
- LP lock/burn status from RugCheck market data when available:
  - `LP_LOCKED`
  - `LP_MOSTLY_LOCKED`
  - `LP_PARTIALLY_LOCKED`
  - `LP_UNLOCKED`
  - `LP_BURNED_OR_NON_WITHDRAWABLE`
  - `LP_LOCK_UNKNOWN`

Current limitation: when RugCheck does not return market LP data, the system falls back to `LP_LOCK_UNKNOWN`.

Levels:

- 0-24: `LIQUIDITY_TRAP_LOW`
- 25-49: `LIQUIDITY_TRAP_MEDIUM`
- 50-74: `LIQUIDITY_TRAP_HIGH`
- 75-100: `LIQUIDITY_TRAP_CRITICAL`

## DexScreener Ads Detection

DexScreener paid promotion is shown in the dashboard as `Ads`.

Signals:

- `Profile`: DexScreener `tokenProfile` paid order detected.
- `Boost`: active boost or boost order detected.
- `Golden`: active boost count is at least 500.
- `None`: no paid order or boost detected in latest stored scan.

Data comes from:

```text
/orders/v1/{chainId}/{tokenAddress}
/token-pairs/v1/{chainId}/{tokenAddress}
```

## Main Database Tables

- `ingestion_runs`: scan/run metadata.
- `tokens`: token identity.
- `token_pairs`: Dex pair metadata.
- `token_prices`: price/liquidity/volume snapshots.
- `raw_api_snapshots`: raw external API data.
- `risk_checks`: low-level data readiness and risk checks.
- `market_filter_results`
- `contract_risk_results`
- `liquidity_filter_results`
- `token_holders`
- `wallet_analysis_results`
- `wallet_funding_edges`
- `cluster_analysis_results`
- `wallet_intelligence_results`
- `wallet_relationship_edges`
- `wallet_manipulation_results`
- `watchlist_decisions`

## Dashboard Views

The local dashboard is served by `app/web_server.py` and consists of five
HTML pages under `app/static/`. All five share the cyberpunk theme (true
black background, neon-orange accent, monospace typography, sticky brand
bars) and were rebuilt during the 2026-05-26 redesign arc.

### Five pages, one design language

| Page  | Path           | Identity                                         |
|-------|----------------|--------------------------------------------------|
| `/`         | dashboard.html       | **COMMAND BRIDGE / SIGNAL FLOOR**          |
| `/whale-radar` | whale_radar.html  | **RADAR CONSOLE** with live orb            |
| `/wallet`   | wallet_detail.html   | **WALLET DOSSIER** with PnL tier emblems   |
| `/token`    | token_detail.html    | **CASE FILE / DECISION DOSSIER**           |
| `/system`   | system.html          | **OPS DECK** — telemetry & health          |

### Dashboard (`/`)

Layout, top to bottom:
- **Brand bar** — sticky orange-glow ▲ mark, "MEMECO QUANT INTELLIGENCE",
  centered nav (DASHBOARD / WHALE RADAR / SYSTEM), live freshness pill
  with a pulsing dot.
- **Whale Intercept ticker** — strip showing the last 3 high-signal whale
  events with type · token · wallet · SOL amount · "23s ago". Polls
  `/api/whale-radar` every 60s. Auto-hides when empty.
- **Command rail** — terminal-prompt search ("›  ANALYZE › paste Solana
  mint address") feeding into a glowing orange EXECUTE CTA. RUN SCAN /
  refresh / filters as monospace icon buttons.
- **HUD strip** — KPI tiles in a single horizontal row with left orange
  edge stripes; numbers are big monospace numerals with text-glow.
- **Scan ticker** — linear orange progress meter (replaces the older
  speedometer) + horizontally-scrolling pill rail of recent scan steps.
- **Filter bar** — chip group (ALL / ★ STARRED / PASS / REVIEW / WAIT /
  REJECT… ). Multi-select; serializes to `?status=…&starred=1` URL.
- **Hero opportunity card** + **Opportunity grid** (top 3 ranked passes).
- **SIGNAL FLOOR** (the main table) with three view modes via a tab
  switcher next to the count badge:
  - **▦ TABLE** — dense default. Each row has a 9-bar Signal Chain
    barcode showing the tone of every pipeline stage (Market →
    Contract → Liquidity → Trap → Wallet → Cluster → Manip → Dev →
    Insider). Hover any bar to see "Stage: status". A small verdict
    pill (PASS / REVIEW / REJECT) sits beside the chain.
  - **≡ TAPE** — chronological pulse feed sorted by `created_at` desc.
    Time + token + chain + verdict per row, glowing orange dot on the
    left of each row.
  - **▣ COCKPIT** — detailed card grid. Each token gets its own card
    with stat tiles (Insider/100, Trap/100, Liq $) and the full
    decision reason.
- **Live header counters** — PASS / WAIT / REJECT / FRESHEST update on
  every refresh.
- **Decision diff badges** — when a token's `final_watchlist_status`
  flips between two consecutive renders, a small "↑ now PASS" badge
  appears on the row for ~30 seconds.
- **Decision-tree drawer** — hovering any row opens a slide-in drawer
  on the right with the full decision tree without leaving the page.
- **Star button** in the row toolbar persists the wallet locally and
  optionally fires a browser **Notification** when a starred token's
  status flips.
- **Keyboard nav**: `/` focus search · `j`/`k` next/prev row · `Enter`
  open detail · `c` copy address · `?` cheat-sheet · `Esc` close.
- **Density toggle** (Compact / Comfy) persisted in localStorage.
- **Mobile / tablet** — under 720px the table reflows into a card list;
  the sidebar / nav collapses behind ☰ at tablet widths.

### Whale Radar (`/whale-radar`)

- **Sticky brand bar** matching the dashboard.
- **Radar orb** — three concentric orange rings, a sweeping arm rotating
  every 3.6s, a centered pip that pulses outward. The pip **flashes
  white** the instant a brand-new live signal arrives.
- **LAST INTERCEPT readout** — "<wallet> · <token> · <type> · <amount>
  SOL · 12s ago" beside the orb.
- **Webhook status pill** — green active / red missing / orange idle.
- **Vertical command rail** — REFRESH (orange CTA) + AUDIT WALLETS /
  REFRESH PRICES / SURVIVAL PROFILE / SYNC WEBHOOK as monospace buttons.
- **KPI HUD strip** — same edge-stripe tiles as the dashboard.
- **Alerts grid** — INCOMING (high-signal alerts) and GROUP BUY (token
  confluence) **side by side** instead of stacked.
- **Floor** — leaderboard (rank chips: gold/silver/bronze for top 3) and
  live feed (timeline-dot signal cards).
- **Auto-analysis queue** — full-width strip of job cards.

### Wallet Detail (`/wallet`)

- **Tier emblem driven by Total PnL** — every wallet wears a rank emblem
  rendered as an inline SVG (no external assets):

  | PnL bucket  | Tier      | Emblem            | Hover behavior            |
  |-------------|-----------|-------------------|---------------------------|
  | ≥ 100 SOL   | TITAN     | crown + gold halo | shimmers gold + scales    |
  | 50–100 SOL  | WHALE     | whale silhouette  | dives forward             |
  | 20–50 SOL   | DOLPHIN   | dolphin           | dives forward             |
  | 5–20 SOL    | TROUT     | spotted small fish| Y-axis flip               |
  | 0–5 SOL     | MINNOW    | tiny gray fish    | bubbles up + tints orange |
  | < 0 SOL     | BAGHOLDER | drooping bag      | shakes (sad reaction)     |

  Each tier reskins the hero border + glow color. TITAN gets a literal
  gold halo, BAGHOLDER goes red. All animations honor
  `prefers-reduced-motion`.
- **HERO** — split: 220×220 emblem + tier name on the left; wallet
  handle, address chip, two giant headline numbers (Total PnL, Win
  Rate) and an orange "OPEN ON WHALE RADAR" CTA on the right.
- **KPI HUD strip** — TRADES / AVG HOLD / TOTAL COST / RECEIVED-SPENT /
  AVG ROI / AVG ENTRY / STYLE / SECURITY.
- **Analytics row (3-up)** — RECENT P&L SPARK (vertical bar histogram
  of last ~25 trades, oldest left → newest right, green-up / red-down
  relative to a centered zero line) · ROI BALANCE (a literal scale
  with a fulcrum ▲ that **tilts ±6°** based on win/loss ratio) ·
  SAFETY (phishing/rug/bot rows + buy-size distribution).
- **Tabs + table** — TRADES / LIVE SIGNALS / HOLDINGS.

### Token Detail (`/token`)

- **Sticky brand bar** matching the rest of the suite.
- **HERO — split**: token head card on the left; **Change Signals**
  diff strip on the right (orange-edge tone-coded cells: good = green,
  bad = red, warn = yellow). Diffs are now the first thing you see.
- **KPI HUD strip** — repurposes the existing metric set.
- **DECISION DOSSIER** — the legacy "Why Rejected?" section becomes
  **9 numbered evidence cards** in a responsive grid. Each card has an
  auto-numbered top-right counter (`01`, `02`, …), a pass / warn / fail
  / unknown left edge stripe + tinted background, a pill-shaped status
  chip in the matching tone, and reason + bulleted warnings.
- **TOKEN TIMELINE** — rebuilt as a horizontal track with **pip-marker
  dots above each card**, lit by tone, all sitting on a glowing orange
  axis line.
- **Tables** — Wallet Intelligence, Early Buyer Profit Map, Top
  Holders, Wallet Relationships — every table reskinned to match
  SIGNAL FLOOR (black sticky headers, monospace caps labels).

### Ops Deck (`/system`)

Operational visibility for the local stack. Polls `/api/system` every
30 seconds. Sections:

- **HUD** — total decisions / PASS / PASS·HIGH RISK / latest decision.
- **External APIs** — HELIUS / RUGCHECK / WHALE_WEBHOOK_URL /
  WHALE_WEBHOOK_AUTH_HEADER configured ✓ or missing ✗.
- **Whale webhook** — current status, watched wallet count, last
  updated, last error.
- **API activity** — counts of `raw_api_snapshots` rows per source for
  the last 1h and 24h, plus last seen.
- **Storage & retention** — DB size, hypertable count, per-table
  chunks and retention policy from the Timescale catalog.
- **Recent failures** — last 5 failed/errored ingestion runs with
  truncated error message.

Performance note:

- The main dashboard intentionally avoids sending the full `watchlist_decisions.details` payload for every token. It sends only the fields needed for cards/table rendering.
- Full decision trees, timeline data, wallet labels, and relationship evidence remain available through the token detail endpoint.
- Timeline labels are deliberately conservative: wallet events are called "tracked holder" events because they come from analyzed top-holder wallets, not from a complete all-buyers transaction index.

## Database Cleanup Check

Current public tables were reviewed. No table is safe to remove right now because each table is either part of the pipeline, the dashboard, token detail pages, or raw audit/debug history.

Notable point: `wallet_relationship_edges` can become large, but it is used by the token detail relationship view and wallet manipulation evidence. It should be cleaned later with a retention policy, not deleted as unused data.

## Commands

Start database:

```powershell
docker compose up -d
```

Run ingestion:

```powershell
python app\ingest_dexscreener.py
```

Run full analysis:

```powershell
python app\run_analysis_pipeline.py
```

Run dashboard:

```powershell
python app\web_server.py
```

Manual token analysis:

```text
Open the dashboard, paste a Solana mint address into the manual input, and click Analyze Token.
The server creates a fresh ingestion run for that token, pulls DexScreener pair/order data, runs the analysis pipeline, and then the token appears in the dashboard.
```

Run tests:

```powershell
python -m unittest discover -s tests -v
```

Run individual services:

```powershell
python app\run_market_filter.py
python app\run_contract_risk.py
python app\run_liquidity_filter.py
python app\run_wallet_analysis.py
python app\run_cluster_analysis.py
python app\run_wallet_intelligence.py
python app\run_wallet_manipulation.py
python app\run_dev_wallet_audit.py
python app\run_dev_wallet_flow.py
python app\run_watchlist_decision.py
```

## Environment

Required `.env` values:

```text
DATABASE_URL=postgresql://...
HELIUS_API_KEY=...
```

Do not expose the Helius key publicly.

## Current Known Limitations

- Wallet manipulation is currently optimized for speed: latest run, top 3 holders, 30 transactions each.
- Dev wallet flow is bounded to two degrees and top recipients only; it is not an unlimited recursive graph crawler.
- Full graph analysis would require pagination, caching, and background queues.
- PnL is approximate because token transfers are tracked, but full USD execution pricing per transaction is not yet normalized.
- DexScreener bonding progress is not directly available from the current DexScreener API; the platform now skips Pump.fun bonding-only tokens instead of showing them in the main dashboard.
- If a token has both a Pump.fun bonding pair and a later DEX pair, the platform selects the later non-bonding DEX pair for analysis.
- Price movement chips show `N/A` until enough older price snapshots exist for the requested window.
- DexScreener's public API does not currently expose a dedicated "Top Gainers" endpoint. Whale Reverse Discovery ranks recent locally discovered pairs after refreshing them with the official batch token endpoint and sorting by `priceChange.h24`.

## Recommended Next Steps

1. Add pagination/caching for wallet manipulation so top 20 holders can be scanned safely.
2. Add a visual wallet graph on token detail pages.
3. Add PnL in USD per wallet using swap pricing.
4. Add deployer/dev wallet detection.
5. Add persistent scan history comparison to detect if insiders are exiting over time.
