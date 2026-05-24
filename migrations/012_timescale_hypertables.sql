-- Migration 012: Convert token_prices and raw_api_snapshots to TimescaleDB
-- hypertables, add retention policies, and create a continuous aggregate
-- for hourly OHLC on token_prices.
--
-- This migration is intentionally NOT wrapped in a single BEGIN/COMMIT
-- because some TimescaleDB statements (continuous aggregate creation,
-- policy registration) historically cannot run inside an explicit
-- transaction block. Each step is idempotent and safe to re-run.
--
-- Apply with:
--   docker exec -i quant_db psql -U admin -d quant_intelligence \
--       -v ON_ERROR_STOP=1 -f /tmp/012_timescale_hypertables.sql

-- 1. Make sure the TimescaleDB extension is loaded.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 2. Convert token_prices to a hypertable on the `time` column.
--    The existing UNIQUE (time, pair_id) constraint already includes the
--    partitioning column, so no schema rewrite is needed.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM timescaledb_information.hypertables
        WHERE hypertable_schema = 'public'
          AND hypertable_name = 'token_prices'
    ) THEN
        PERFORM create_hypertable(
            'token_prices',
            'time',
            chunk_time_interval => INTERVAL '1 day',
            migrate_data        => TRUE,
            if_not_exists       => TRUE
        );
    END IF;
END $$;

-- 3. Convert raw_api_snapshots to a hypertable on `created_at`.
--    A hypertable's primary key / unique indexes must include the
--    partitioning column, so we replace PRIMARY KEY (id) with
--    PRIMARY KEY (id, created_at). The BIGSERIAL sequence on `id`
--    is independent of the constraint and keeps working unchanged.
--    Nothing in the schema or codebase references raw_api_snapshots(id)
--    via foreign key, so this is safe.
DO $$
DECLARE
    pk_columns TEXT;
BEGIN
    SELECT string_agg(a.attname, ',' ORDER BY array_position(i.indkey, a.attnum))
    INTO pk_columns
    FROM pg_index i
    JOIN pg_attribute a
      ON a.attrelid = i.indrelid
     AND a.attnum   = ANY(i.indkey)
    WHERE i.indrelid  = 'public.raw_api_snapshots'::regclass
      AND i.indisprimary;

    IF pk_columns IS DISTINCT FROM 'id,created_at' THEN
        IF pk_columns = 'id' THEN
            ALTER TABLE raw_api_snapshots
                DROP CONSTRAINT raw_api_snapshots_pkey;
        END IF;

        ALTER TABLE raw_api_snapshots
            ADD CONSTRAINT raw_api_snapshots_pkey
            PRIMARY KEY (id, created_at);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM timescaledb_information.hypertables
        WHERE hypertable_schema = 'public'
          AND hypertable_name = 'raw_api_snapshots'
    ) THEN
        PERFORM create_hypertable(
            'raw_api_snapshots',
            'created_at',
            chunk_time_interval => INTERVAL '1 day',
            migrate_data        => TRUE,
            if_not_exists       => TRUE
        );
    END IF;
END $$;

-- 4. Retention policies.
--    token_prices    : keep 30 days of raw rows; hourly continuous aggregate
--                      below holds longer history at lower resolution.
--    raw_api_snapshots: keep 14 days. These are debugging blobs and grow fast.
SELECT add_retention_policy(
    'token_prices',
    drop_after    => INTERVAL '30 days',
    if_not_exists => TRUE
);

SELECT add_retention_policy(
    'raw_api_snapshots',
    drop_after    => INTERVAL '14 days',
    if_not_exists => TRUE
);

-- 5. Continuous aggregate: hourly OHLC + liquidity/volume/mcap per pair.
--    Useful for the dashboard's 1h/4h/24h price chips and any future
--    price-history view, and lets us drop raw rows after 30 days while
--    still serving long-range trends.
CREATE MATERIALIZED VIEW IF NOT EXISTS token_prices_hourly
WITH (timescaledb.continuous) AS
SELECT
    pair_id,
    time_bucket(INTERVAL '1 hour', time)             AS bucket,
    FIRST(price_usd, time)                           AS open_price_usd,
    LAST(price_usd, time)                            AS close_price_usd,
    MAX(price_usd)                                   AS high_price_usd,
    MIN(price_usd)                                   AS low_price_usd,
    AVG(price_usd)                                   AS avg_price_usd,
    AVG(liquidity_usd)                               AS avg_liquidity_usd,
    MAX(volume_1h_usd)                               AS max_volume_1h_usd,
    MAX(volume_24h_usd)                              AS max_volume_24h_usd,
    LAST(market_cap_usd, time)                       AS last_market_cap_usd,
    LAST(fdv_usd, time)                              AS last_fdv_usd,
    SUM(buys_1h)                                     AS total_buys_1h,
    SUM(sells_1h)                                    AS total_sells_1h,
    COUNT(*)                                         AS sample_count
FROM token_prices
GROUP BY pair_id, bucket
WITH NO DATA;

-- Refresh policy: keep the last 30 days of buckets fresh, ignore the
-- still-forming current hour, and refresh every 30 minutes.
SELECT add_continuous_aggregate_policy(
    'token_prices_hourly',
    start_offset      => INTERVAL '30 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '30 minutes',
    if_not_exists     => TRUE
);

-- Backfill the aggregate once so the view is immediately useful.
-- This is a no-op on a fresh DB and cheap on a small one.
CALL refresh_continuous_aggregate('token_prices_hourly', NULL, NULL);
