BEGIN;

CREATE TABLE IF NOT EXISTS wallet_funding_edges (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    holder_address TEXT NOT NULL,
    funder_address TEXT,
    signature TEXT,
    amount_lamports BIGINT,
    timestamp TIMESTAMPTZ,
    source TEXT NOT NULL,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT wallet_funding_edges_run_token_holder_source_key UNIQUE (run_id, token_id, holder_address, source)
);

CREATE TABLE IF NOT EXISTS cluster_analysis_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT REFERENCES token_pairs(id) ON DELETE CASCADE,
    cluster_status TEXT NOT NULL,
    cluster_pass BOOLEAN NOT NULL,
    cluster_reason TEXT NOT NULL,
    holder_count INTEGER NOT NULL DEFAULT 0,
    funded_holder_count INTEGER NOT NULL DEFAULT 0,
    shared_funder_count INTEGER NOT NULL DEFAULT 0,
    largest_cluster_size INTEGER NOT NULL DEFAULT 0,
    largest_cluster_funder TEXT,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT cluster_analysis_results_run_token_key UNIQUE (run_id, token_id)
);

ALTER TABLE watchlist_decisions
    ADD COLUMN IF NOT EXISTS cluster_status TEXT,
    ADD COLUMN IF NOT EXISTS cluster_pass BOOLEAN,
    ADD COLUMN IF NOT EXISTS largest_cluster_size INTEGER,
    ADD COLUMN IF NOT EXISTS largest_cluster_funder TEXT;

CREATE INDEX IF NOT EXISTS wallet_funding_edges_run_token_idx ON wallet_funding_edges(run_id, token_id);
CREATE INDEX IF NOT EXISTS wallet_funding_edges_funder_idx ON wallet_funding_edges(funder_address);
CREATE INDEX IF NOT EXISTS cluster_analysis_results_created_idx ON cluster_analysis_results(created_at DESC);

COMMIT;
