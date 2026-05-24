BEGIN;

CREATE TABLE IF NOT EXISTS wallet_relationship_edges (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT REFERENCES token_pairs(id) ON DELETE CASCADE,
    from_wallet TEXT,
    to_wallet TEXT,
    relation_type TEXT NOT NULL,
    amount NUMERIC,
    signature TEXT,
    timestamp TIMESTAMPTZ,
    source TEXT NOT NULL,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT wallet_relationship_edges_unique_key UNIQUE (
        run_id,
        token_id,
        relation_type,
        from_wallet,
        to_wallet,
        signature
    )
);

CREATE TABLE IF NOT EXISTS wallet_manipulation_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT REFERENCES token_pairs(id) ON DELETE CASCADE,
    manipulation_status TEXT NOT NULL,
    manipulation_pass BOOLEAN NOT NULL,
    manipulation_reason TEXT NOT NULL,
    manipulation_score NUMERIC NOT NULL DEFAULT 0,
    shared_funder_cluster_size INTEGER NOT NULL DEFAULT 0,
    token_distributor_count INTEGER NOT NULL DEFAULT 0,
    linked_wallet_count INTEGER NOT NULL DEFAULT 0,
    coordinated_dump_count INTEGER NOT NULL DEFAULT 0,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT wallet_manipulation_results_run_token_key UNIQUE (run_id, token_id)
);

CREATE INDEX IF NOT EXISTS wallet_relationship_edges_run_token_idx
    ON wallet_relationship_edges(run_id, token_id);

CREATE INDEX IF NOT EXISTS wallet_relationship_edges_from_to_idx
    ON wallet_relationship_edges(from_wallet, to_wallet);

CREATE INDEX IF NOT EXISTS wallet_manipulation_results_created_idx
    ON wallet_manipulation_results(created_at DESC);

ALTER TABLE watchlist_decisions
    ADD COLUMN IF NOT EXISTS manipulation_status TEXT,
    ADD COLUMN IF NOT EXISTS manipulation_pass BOOLEAN,
    ADD COLUMN IF NOT EXISTS manipulation_score NUMERIC;

COMMIT;
