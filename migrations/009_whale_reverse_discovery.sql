BEGIN;

CREATE TABLE IF NOT EXISTS whale_discovery_targets (
    id BIGSERIAL PRIMARY KEY,
    token_id BIGINT REFERENCES tokens(id) ON DELETE SET NULL,
    pair_id BIGINT REFERENCES token_pairs(id) ON DELETE SET NULL,
    chain TEXT NOT NULL DEFAULT 'solana',
    token_address TEXT NOT NULL,
    token_symbol TEXT,
    pair_address TEXT,
    price_native NUMERIC,
    price_usd NUMERIC,
    price_change_24h_percent NUMERIC,
    volume_24h_usd NUMERIC,
    liquidity_usd NUMERIC,
    pair_created_at TIMESTAMPTZ,
    source TEXT NOT NULL DEFAULT 'dexscreener_recent_gainers',
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    buyers_checked INTEGER NOT NULL DEFAULT 0,
    profitable_buyers INTEGER NOT NULL DEFAULT 0,
    promoted_wallets INTEGER NOT NULL DEFAULT 0,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_analyzed_at TIMESTAMPTZ,
    CONSTRAINT whale_discovery_targets_pair_source_key UNIQUE (pair_address, source)
);

CREATE INDEX IF NOT EXISTS whale_discovery_targets_recent_idx
    ON whale_discovery_targets(discovered_at DESC, price_change_24h_percent DESC);

CREATE INDEX IF NOT EXISTS whale_discovery_targets_status_idx
    ON whale_discovery_targets(status, last_analyzed_at DESC);

CREATE INDEX IF NOT EXISTS whale_performance_source_created_idx
    ON whale_performance_tracking(source, created_at DESC);

ALTER TABLE whale_performance_tracking
    ADD COLUMN IF NOT EXISTS current_price_usd NUMERIC,
    ADD COLUMN IF NOT EXISTS current_price_native NUMERIC,
    ADD COLUMN IF NOT EXISTS current_value_sol NUMERIC,
    ADD COLUMN IF NOT EXISTS current_unrealized_pnl_sol NUMERIC,
    ADD COLUMN IF NOT EXISTS price_refreshed_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS whale_webhook_configs (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'helius',
    webhook_id TEXT UNIQUE,
    webhook_url TEXT NOT NULL,
    auth_header TEXT,
    transaction_types JSONB NOT NULL DEFAULT '["SWAP"]'::jsonb,
    account_addresses JSONB NOT NULL DEFAULT '[]'::jsonb,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'PENDING',
    last_error TEXT,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS whale_webhook_configs_provider_idx
    ON whale_webhook_configs(provider, updated_at DESC);

COMMIT;
