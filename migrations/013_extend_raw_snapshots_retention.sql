-- migrations/013_extend_raw_snapshots_retention.sql
--
-- Bump retention on `raw_api_snapshots` from 14 days to 90 days.
--
-- Why:
--   The dashboard reads logo_url, dex_active_boosts, dex_paid_order_count,
--   dex_paid_order_types, dex_promotion_first_seen_at, and priceChange via
--   LATERAL JOINs against `raw_api_snapshots`. Migration 012 added a 14-day
--   retention policy, which silently empties those fields for tokens older
--   than 14 days. Bumping to 90 days gives the dashboard a much wider
--   window without making storage unbounded.
--
-- Long-term follow-up (intentionally NOT in this migration):
--   Materialize the dashboard-critical fields into a `token_dashboard_state`
--   table at ingest time. Once that exists, retention can be tightened
--   back down without breaking the UI.
--
-- This migration is idempotent: it removes the existing retention policy
-- (if any) and re-adds it with the new interval.

-- 1. Drop the previous retention policy on raw_api_snapshots, if it exists.
SELECT remove_retention_policy('raw_api_snapshots', if_exists => TRUE);

-- 2. Re-add with a 90-day window. `if_not_exists => TRUE` keeps the
--    migration safe to re-run.
SELECT add_retention_policy(
    'raw_api_snapshots',
    INTERVAL '90 days',
    if_not_exists => TRUE
);

-- Note: token_prices retention is intentionally left at 30 days. Long-range
-- price history is preserved by the `token_prices_hourly` continuous
-- aggregate (migration 012), so that retention does not break the UI.
