BEGIN;

CREATE TABLE IF NOT EXISTS wallet_intelligence_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT REFERENCES token_pairs(id) ON DELETE CASCADE,
    wallet_address TEXT NOT NULL,
    rank INTEGER,
    holder_percent NUMERIC,
    labels JSONB NOT NULL DEFAULT '[]'::jsonb,
    wallet_score NUMERIC,
    first_entry_at TIMESTAMPTZ,
    seconds_from_launch INTEGER,
    total_token_in NUMERIC,
    total_token_out NUMERIC,
    net_token_amount NUMERIC,
    transaction_count INTEGER NOT NULL DEFAULT 0,
    funding_source TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT wallet_intelligence_results_run_token_wallet_key UNIQUE (run_id, token_id, wallet_address)
);

ALTER TABLE watchlist_decisions
    ADD COLUMN IF NOT EXISTS intelligence_summary JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS wallet_intelligence_results_run_token_idx
    ON wallet_intelligence_results(run_id, token_id);

CREATE INDEX IF NOT EXISTS wallet_intelligence_results_wallet_idx
    ON wallet_intelligence_results(wallet_address);

CREATE INDEX IF NOT EXISTS wallet_intelligence_results_labels_idx
    ON wallet_intelligence_results USING GIN(labels);

COMMIT;
