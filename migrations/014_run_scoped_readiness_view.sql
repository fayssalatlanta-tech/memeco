-- migrations/014_run_scoped_readiness_view.sql
--
-- Make the data-readiness view run-scoped.
--
-- Why:
--   `latest_token_data_readiness` baked `WHERE source = 'dexscreener_latest_profiles'
--   AND run_id = MAX(id)` straight into its definition. That is fine for
--   ad-hoc CLI debugging, but every analysis service inherited the same
--   MAX(id) implicit assumption, which means any process that does not
--   strictly serialize against the in-memory SCAN_LOCK can pick up the
--   wrong run.
--
--   We expose all-runs data via `token_data_readiness`. The original view
--   stays as a thin wrapper for back-compat. Services that receive an
--   explicit run_id query the new view; everything else continues to work
--   unchanged.
--
-- This migration is idempotent: it drops & recreates both views.

DROP VIEW IF EXISTS latest_token_data_readiness;
DROP VIEW IF EXISTS token_data_readiness;

-- General view: every run's readiness, not just the latest.
CREATE VIEW token_data_readiness AS
WITH checks AS (
    SELECT
        rc.run_id,
        rc.token_id,
        rc.pair_id,
        BOOL_OR(rc.check_name = 'price_available' AND rc.risk_level = 'PASS') AS has_price,
        BOOL_OR(rc.check_name = 'volume_1h_available' AND rc.risk_level = 'PASS') AS has_volume_1h,
        BOOL_OR(rc.check_name = 'market_cap_available' AND rc.risk_level = 'PASS') AS has_market_cap,
        BOOL_OR(rc.check_name = 'fdv_available' AND rc.risk_level = 'PASS') AS has_fdv,
        BOOL_OR(rc.check_name = 'pair_created_at_available' AND rc.risk_level = 'PASS') AS has_pair_created_at,
        BOOL_OR(rc.check_name = 'txns_available' AND rc.risk_level = 'PASS') AS has_txns,
        BOOL_OR(rc.check_name = 'price_change_available' AND rc.risk_level = 'PASS') AS has_price_change,
        BOOL_OR(rc.check_name = 'liquidity_ok' AND rc.risk_level = 'PASS') AS has_liquidity,
        BOOL_OR(rc.check_name = 'missing_liquidity') AS missing_liquidity,
        BOOL_OR(rc.check_name = 'low_volume_5m') AS low_volume_5m
    FROM risk_checks rc
    JOIN ingestion_runs ir
        ON ir.id = rc.run_id
       AND ir.source = 'dexscreener_latest_profiles'
    GROUP BY rc.run_id, rc.token_id, rc.pair_id
)
SELECT
    c.run_id,
    t.id AS token_id,
    p.id AS pair_id,
    t.symbol,
    t.name,
    t.chain,
    t.address AS token_address,
    p.pair_address,
    c.has_price,
    c.has_volume_1h,
    c.has_market_cap,
    c.has_fdv,
    c.has_pair_created_at,
    c.has_txns,
    c.has_price_change,
    c.has_liquidity,
    c.missing_liquidity,
    c.low_volume_5m,
    CASE
        WHEN c.has_price = FALSE
          OR c.has_volume_1h = FALSE
          OR c.has_market_cap = FALSE
          OR c.has_fdv = FALSE
          OR c.has_pair_created_at = FALSE
          OR c.has_txns = FALSE
          OR c.has_price_change = FALSE
            THEN 'NOT_READY'
        WHEN c.missing_liquidity = TRUE
            THEN 'PARTIAL_BUT_PASS'
        ELSE 'READY_FOR_ANALYSIS'
    END AS data_readiness_status
FROM checks c
JOIN tokens t
    ON t.id = c.token_id
JOIN token_pairs p
    ON p.id = c.pair_id;

-- Back-compat: keep the original view as a thin wrapper that filters
-- by the most recent ingestion run.
CREATE VIEW latest_token_data_readiness AS
SELECT *
FROM token_data_readiness
WHERE run_id = (
    SELECT MAX(id)
    FROM ingestion_runs
    WHERE source = 'dexscreener_latest_profiles'
);
