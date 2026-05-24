BEGIN;

CREATE TABLE IF NOT EXISTS elite_wallets (
    id BIGSERIAL PRIMARY KEY,
    wallet_address TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL DEFAULT 'ELITE_CANDIDATE',
    total_profit_sol NUMERIC NOT NULL DEFAULT 0,
    total_profit_30d_sol NUMERIC NOT NULL DEFAULT 0,
    win_rate_percent NUMERIC NOT NULL DEFAULT 0,
    avg_roi_percent NUMERIC NOT NULL DEFAULT 0,
    avg_minutes_after_launch NUMERIC,
    trade_count INTEGER NOT NULL DEFAULT 0,
    profitable_trade_count INTEGER NOT NULL DEFAULT 0,
    reliability_score NUMERIC NOT NULL DEFAULT 0,
    bot_flag BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'WATCHING',
    source TEXT NOT NULL DEFAULT 'wallet_intelligence',
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_scored_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS whale_performance_tracking (
    id BIGSERIAL PRIMARY KEY,
    elite_wallet_id BIGINT REFERENCES elite_wallets(id) ON DELETE CASCADE,
    wallet_address TEXT NOT NULL,
    token_id BIGINT REFERENCES tokens(id) ON DELETE SET NULL,
    pair_id BIGINT REFERENCES token_pairs(id) ON DELETE SET NULL,
    token_address TEXT,
    token_symbol TEXT,
    entry_at TIMESTAMPTZ,
    exit_at TIMESTAMPTZ,
    minutes_after_launch NUMERIC,
    native_spent_sol NUMERIC NOT NULL DEFAULT 0,
    native_received_sol NUMERIC NOT NULL DEFAULT 0,
    pnl_sol NUMERIC,
    roi_percent NUMERIC,
    trade_status TEXT NOT NULL DEFAULT 'OBSERVED',
    source TEXT NOT NULL DEFAULT 'wallet_intelligence',
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT whale_performance_tracking_wallet_token_source_key UNIQUE (
        wallet_address,
        token_address,
        source
    )
);

CREATE TABLE IF NOT EXISTS live_whale_signals (
    id BIGSERIAL PRIMARY KEY,
    elite_wallet_id BIGINT REFERENCES elite_wallets(id) ON DELETE SET NULL,
    wallet_address TEXT NOT NULL,
    token_address TEXT,
    token_symbol TEXT,
    signal_type TEXT NOT NULL,
    amount_sol NUMERIC,
    price_usd NUMERIC,
    signature TEXT,
    source TEXT NOT NULL DEFAULT 'helius_webhook',
    signal_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT live_whale_signals_signature_key UNIQUE (signature)
);

CREATE INDEX IF NOT EXISTS elite_wallets_score_idx
    ON elite_wallets(reliability_score DESC, total_profit_sol DESC);

CREATE INDEX IF NOT EXISTS elite_wallets_status_idx
    ON elite_wallets(status, bot_flag, reliability_score DESC);

CREATE INDEX IF NOT EXISTS whale_performance_wallet_idx
    ON whale_performance_tracking(wallet_address, created_at DESC);

CREATE INDEX IF NOT EXISTS whale_performance_token_idx
    ON whale_performance_tracking(token_address);

CREATE INDEX IF NOT EXISTS live_whale_signals_created_idx
    ON live_whale_signals(created_at DESC);

CREATE INDEX IF NOT EXISTS live_whale_signals_wallet_idx
    ON live_whale_signals(wallet_address, signal_at DESC);

COMMIT;
