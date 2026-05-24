BEGIN;

CREATE TABLE IF NOT EXISTS dev_wallet_audit_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT REFERENCES token_pairs(id) ON DELETE CASCADE,
    dev_wallet_address TEXT,
    dev_audit_status TEXT NOT NULL,
    dev_audit_pass BOOLEAN NOT NULL,
    dev_audit_reason TEXT NOT NULL,
    current_balance NUMERIC,
    total_token_in NUMERIC NOT NULL DEFAULT 0,
    total_token_out NUMERIC NOT NULL DEFAULT 0,
    sold_token_amount NUMERIC NOT NULL DEFAULT 0,
    transferred_token_amount NUMERIC NOT NULL DEFAULT 0,
    sell_transaction_count INTEGER NOT NULL DEFAULT 0,
    transfer_transaction_count INTEGER NOT NULL DEFAULT 0,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT dev_wallet_audit_results_run_token_key UNIQUE (run_id, token_id)
);

CREATE INDEX IF NOT EXISTS dev_wallet_audit_results_created_idx
    ON dev_wallet_audit_results(created_at DESC);

CREATE INDEX IF NOT EXISTS dev_wallet_audit_results_wallet_idx
    ON dev_wallet_audit_results(dev_wallet_address);

COMMIT;
