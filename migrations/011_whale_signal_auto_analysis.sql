BEGIN;

CREATE TABLE IF NOT EXISTS whale_signal_analysis_jobs (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT REFERENCES live_whale_signals(id) ON DELETE SET NULL,
    wallet_address TEXT NOT NULL,
    token_address TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    reason TEXT,
    run_id BIGINT REFERENCES ingestion_runs(id) ON DELETE SET NULL,
    final_watchlist_status TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    CONSTRAINT whale_signal_analysis_jobs_token_key UNIQUE (token_address)
);

CREATE INDEX IF NOT EXISTS whale_signal_analysis_jobs_status_idx
    ON whale_signal_analysis_jobs(status, created_at DESC);

CREATE INDEX IF NOT EXISTS whale_signal_analysis_jobs_wallet_idx
    ON whale_signal_analysis_jobs(wallet_address, created_at DESC);

COMMIT;
