BEGIN;

CREATE TABLE IF NOT EXISTS token_holders (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT REFERENCES token_pairs(id) ON DELETE CASCADE,
    owner_address TEXT NOT NULL,
    rank INTEGER NOT NULL,
    amount NUMERIC,
    percent NUMERIC,
    source TEXT NOT NULL,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT token_holders_run_token_owner_source_key UNIQUE (run_id, token_id, owner_address, source)
);

CREATE TABLE IF NOT EXISTS wallet_analysis_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT REFERENCES token_pairs(id) ON DELETE CASCADE,
    wallet_status TEXT NOT NULL,
    wallet_pass BOOLEAN NOT NULL,
    wallet_reason TEXT NOT NULL,
    top_holder_percent NUMERIC,
    top10_holders_percent NUMERIC,
    top20_holders_percent NUMERIC,
    holder_count INTEGER NOT NULL DEFAULT 0,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT wallet_analysis_results_run_token_key UNIQUE (run_id, token_id)
);

ALTER TABLE watchlist_decisions
    ADD COLUMN IF NOT EXISTS wallet_status TEXT,
    ADD COLUMN IF NOT EXISTS wallet_pass BOOLEAN,
    ADD COLUMN IF NOT EXISTS top_holder_percent NUMERIC,
    ADD COLUMN IF NOT EXISTS top10_holders_percent NUMERIC;

CREATE INDEX IF NOT EXISTS token_holders_run_token_rank_idx ON token_holders(run_id, token_id, rank);
CREATE INDEX IF NOT EXISTS wallet_analysis_results_created_idx ON wallet_analysis_results(created_at DESC);

COMMIT;
