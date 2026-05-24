# Quant Watchlist Platform - Project Achievements

This file summarizes what has been completed so another developer or trading-systems expert can understand the current state quickly.

For future development conventions, extension steps, and expert handoff checklist, read `DEVELOPMENT_GUIDE.md`.

## Completed Core System

- DexScreener ingestion for Solana token profiles, token pairs, price/liquidity data, paid orders, and boosts.
- DexScreener latest-token ingestion combines official latest profiles, ads, boosts, and community takeovers, checks up to 40 candidates by default, and saves the newest completed DEX pairs first.
- Preferred pair selection that skips Pump.fun bonding-only tokens and analyzes only completed non-bonding DEX pairs.
- Manual dashboard input for analyzing one Solana mint address on demand.
- Market filter for early momentum, age, weak activity, and dump-risk checks.
- RugCheck-style contract risk analysis.
- Liquidity filter for liquidity depth, market-cap-to-liquidity ratio, and volume-to-liquidity ratio.
- Liquidity Trap score from 0 to 100 for shallow liquidity, high market-cap-to-liquidity, high volume-to-liquidity, and real LP lock/burn status from RugCheck market data.
- Wallet concentration analysis using top holders.
- Cluster analysis using Helius funding-source signals.
- Wallet intelligence labels:
  - `SMART_WALLET`
  - `FRESH_WALLET`
  - `SNIPER`
  - `WHALE`
  - `DUMPER`
  - `DEV_RELATED`
  - `BOT`
  - `UNKNOWN`
- Wallet manipulation analysis with suspicious relationship edges and a 0-10 manipulation score.
- Dev wallet audit that estimates whether the creator sold, transferred tokens out, or currently has zero creator balance.
- Dev wallet flow analysis that tracks developer-linked recipients up to two degrees, detects proxy dumps and splitter wallets, and calculates a 0-100 Shadow Dev Score.
- Final watchlist decision service that combines all filters.
- Dashboard deduplication so the same token appears once and the latest analysis updates its result.
- Dashboard sorting so the latest analyzed token appears first.
- Modern full-dark dashboard UI with token logo, copy-address action, DexScreener ads, bonding progress, age, and analysis status.
- Dashboard price movement chips for each token: 1h, 4h, and 24h change from stored price snapshots.
- Dashboard now exposes more DexScreener market fields directly: price, FDV, market cap, liquidity/bonding liquidity state, 5m/1h/24h volume, and buys/sells.
- Dashboard table market, liquidity, and wallet signal cells now use wider non-truncated stat cards so important numbers remain readable.
- Lightweight dashboard watchlist API payload: the main dashboard receives only compact decision fields, while full analysis details stay available on the token detail page.
- Scan Monitor includes a dashboard-integrated system load gauge that shows light, active, heavy, or problem states from scan activity.
- Token detail page with wallet labels, label reasons, top holders, suspicious wallet relationship highlighting, and a full-dark detail layout.
- Token detail `Refresh Analysis` action that re-runs analysis for the same token and shows `Change Signals` when key status, risk, liquidity, developer, or promotion fields change.
- Corrected token timeline based on stored evidence: pair creation, first DexScreener profile snapshot, first price snapshot, first tracked top-holder entry, first tracked sniper, first tracked major exit, first observed promotion, and final decision.
- `Why Rejected?` decision tree on the token detail page to explain Market, Contract, Liquidity, Liquidity Trap, Wallet, Cluster, Manipulation, Intelligence, and Final decision layers.
- `Insider Probability` score from 0 to 100 based on cluster, manipulation, fresh wallets, sniper wallets, and holder concentration.
- Whale Radar MVP with `elite_wallets`, `whale_performance_tracking`, and `live_whale_signals` tables.
- Elite wallet reliability scoring from 0 to 100 using win rate, ROI, early entry timing, consistency, dust filtering, and bot exclusion.
- Reliability score now stores a detailed breakdown for W/R/E/C weighted components and a `/10` display score.
- Whale Radar page and API for leaderboard, live feed, and shadow performance from tracked wallet-intelligence PnL.
- Reverse Profit Discovery added for Whale Radar: recent completed DexScreener gainers are refreshed through the batch token API, early buyers are sampled from Helius `getSignaturesForAddress`, PnL is estimated, and profitable wallets are promoted into `elite_wallets`.
- Added `whale_discovery_targets` to audit which DexScreener gainer targets were analyzed, how many buyers were checked, and how many wallets were promoted.
- Wallet Consistency Auditor added: pulls recent Helius wallet transactions, rebuilds token positions, refreshes prices, recalculates win rate and reliability, and writes source `wallet_consistency_audit`.
- Helius Webhook manager added: syncs watched elite wallets into one enhanced webhook when `WHALE_WEBHOOK_URL` is configured, and `/api/whale-signal` now supports object or array payloads with optional auth-header verification.
- Whale Radar UI now has action buttons for wallet audit, bulk price refresh, and webhook sync, plus `/10` reliability display beside the internal `/100` score.
- Whale Survival Intelligence added: survival ratio, rugged trade count, whale style, exit style, laddering score, favorite symbols, warning flags, and security level are now stored in `whale_survival_profiles` and shown in Whale Radar.
- Whale-triggered auto-analysis added: watched-wallet buy/token-in signals can now queue token analysis automatically, with duplicate protection through `whale_signal_analysis_jobs`.
- Whale Radar page redesigned into a modern full-dark operations board with status cards, metric cards, a clearer elite-wallet leaderboard, actionable Live Feed signal cards, and visible auto-analysis job cards.
- Whale Radar Live Feed can now be filtered by clicking a wallet in the leaderboard, shows token logo/symbol/address when known, and provides copy actions for wallet and token addresses.
- Whale Radar wallet rows and live wallet signals now include direct Solscan account links for quick external portfolio/history review.
- Whale Radar now separates raw Live Feed movements from `High Signal Alerts`, filtering alert candidates by buy/token-in type, minimum SOL amount, wallet reliability, wallet safety, and SOL/USDC/USDT noise tokens.
- Whale-triggered auto-analysis now ignores SOL/USDC/USDT and tiny movements below `WHALE_SIGNAL_AUTO_ANALYZE_MIN_SOL` so the system spends analysis time on real candidate tokens.
- Added Whale Radar `Token Confluence`: a multi-wallet signal layer that surfaces non-noise tokens bought by at least `WHALE_CONFLUENCE_MIN_WALLETS` watched wallets inside `WHALE_CONFLUENCE_WINDOW_HOURS`.
- Added a GMGN-inspired wallet detail page at `/wallet?wallet=<address>` with wallet header, copy/Solscan actions, PnL summary, win rate, reliability, ROI distribution, buy-size distribution, safety checks, trades, live signals, and open holdings tabs.

## Database Review

The public schema was reviewed after the latest features. No public table is currently unused.

Important tables and their purpose:

- `tokens`, `token_pairs`, `token_prices`: token identity and market snapshots.
- `raw_api_snapshots`: audit/debug snapshots from DexScreener, RugCheck, and related endpoints.
- `risk_checks`: low-level readiness and risk evidence.
- `market_filter_results`, `contract_risk_results`, `liquidity_filter_results`: core risk filters.
- `token_holders`, `wallet_analysis_results`: holder concentration data.
- `wallet_funding_edges`, `cluster_analysis_results`: funding-source and cluster detection.
- `wallet_intelligence_results`: wallet labels and reasons.
- `wallet_relationship_edges`, `wallet_manipulation_results`: manipulation evidence and score.
- `dev_wallet_audit_results`: developer wallet sell/transfer audit.
- `dev_wallet_flow_results`, `dev_wallet_flow_edges`: developer-linked flow graph, proxy dump evidence, splitter evidence, and Shadow Dev Score.
- `watchlist_decisions`: final decision and decision-tree details.

`wallet_relationship_edges` can grow quickly, but it is still used by token detail pages and manipulation evidence. A future cleanup should use retention or pagination, not deletion as unused data.

## Maintainability Improvements

- Added `DEVELOPMENT_GUIDE.md` as the main future-development and expert-handoff guide.
- Documented extension rules for adding filters, keeping dashboard payloads light, and avoiding misleading timeline labels.
- Documented expert handoff file list and testing checklist.

## Next Useful Improvements

- Add pagination/caching for deeper wallet graph analysis.
- Add a retention policy for old raw snapshots and relationship edges.
- Add background jobs for scheduled discovery of upcoming/new tokens.
- Add trend history charts for repeated analysis of the same token.
