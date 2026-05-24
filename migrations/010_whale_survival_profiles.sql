BEGIN;

CREATE TABLE IF NOT EXISTS whale_survival_profiles (
    id BIGSERIAL PRIMARY KEY,
    elite_wallet_id BIGINT REFERENCES elite_wallets(id) ON DELETE CASCADE,
    wallet_address TEXT NOT NULL UNIQUE,
    survival_rate_percent NUMERIC NOT NULL DEFAULT 0,
    rugged_trade_count INTEGER NOT NULL DEFAULT 0,
    survived_trade_count INTEGER NOT NULL DEFAULT 0,
    total_trades_checked INTEGER NOT NULL DEFAULT 0,
    avg_hold_minutes NUMERIC,
    whale_style TEXT NOT NULL DEFAULT 'UNKNOWN',
    exit_style TEXT NOT NULL DEFAULT 'UNKNOWN',
    laddering_score NUMERIC NOT NULL DEFAULT 0,
    dev_shadow_flag BOOLEAN NOT NULL DEFAULT FALSE,
    dev_shadow_reason TEXT,
    security_level TEXT NOT NULL DEFAULT 'UNKNOWN',
    warning_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    favorite_token_symbols JSONB NOT NULL DEFAULT '[]'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS whale_survival_profiles_security_idx
    ON whale_survival_profiles(security_level, survival_rate_percent DESC);

CREATE INDEX IF NOT EXISTS whale_survival_profiles_wallet_idx
    ON whale_survival_profiles(wallet_address);

COMMIT;
