BEGIN;

CREATE TABLE IF NOT EXISTS dev_wallet_flow_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT REFERENCES token_pairs(id) ON DELETE CASCADE,
    dev_wallet_address TEXT,
    flow_status TEXT NOT NULL,
    flow_pass BOOLEAN NOT NULL,
    flow_reason TEXT NOT NULL,
    shadow_dev_score NUMERIC NOT NULL DEFAULT 0,
    direct_recipient_count INTEGER NOT NULL DEFAULT 0,
    tracked_wallet_count INTEGER NOT NULL DEFAULT 0,
    proxy_dump_count INTEGER NOT NULL DEFAULT 0,
    splitter_count INTEGER NOT NULL DEFAULT 0,
    total_direct_amount NUMERIC NOT NULL DEFAULT 0,
    proxy_sold_amount NUMERIC NOT NULL DEFAULT 0,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT dev_wallet_flow_results_run_token_key UNIQUE (run_id, token_id)
);

CREATE TABLE IF NOT EXISTS dev_wallet_flow_edges (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT REFERENCES token_pairs(id) ON DELETE CASCADE,
    from_wallet TEXT NOT NULL,
    to_wallet TEXT NOT NULL,
    degree INTEGER NOT NULL,
    amount NUMERIC NOT NULL DEFAULT 0,
    edge_type TEXT NOT NULL,
    tx_type TEXT,
    signature TEXT,
    timestamp TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS dev_wallet_flow_results_created_idx
    ON dev_wallet_flow_results(created_at DESC);

CREATE INDEX IF NOT EXISTS dev_wallet_flow_results_wallet_idx
    ON dev_wallet_flow_results(dev_wallet_address);

CREATE INDEX IF NOT EXISTS dev_wallet_flow_edges_run_token_idx
    ON dev_wallet_flow_edges(run_id, token_id);

CREATE INDEX IF NOT EXISTS dev_wallet_flow_edges_wallet_idx
    ON dev_wallet_flow_edges(from_wallet, to_wallet);

COMMIT;
