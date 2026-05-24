BEGIN;

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    tokens_found INTEGER NOT NULL DEFAULT 0,
    tokens_saved INTEGER NOT NULL DEFAULT 0,
    pairs_saved INTEGER NOT NULL DEFAULT 0,
    prices_saved INTEGER NOT NULL DEFAULT 0,
    errors_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS tokens (
    id BIGSERIAL PRIMARY KEY,
    chain TEXT NOT NULL,
    address TEXT NOT NULL,
    symbol TEXT,
    name TEXT,
    decimals INTEGER,
    source TEXT,
    creator_address TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT tokens_chain_address_key UNIQUE (chain, address)
);

CREATE TABLE IF NOT EXISTS token_pairs (
    id BIGSERIAL PRIMARY KEY,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    chain TEXT NOT NULL,
    pair_address TEXT NOT NULL,
    base_token_address TEXT,
    quote_token_address TEXT,
    quote_token_symbol TEXT,
    dex_id TEXT,
    url TEXT,
    pair_created_at TIMESTAMPTZ,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT token_pairs_chain_pair_address_key UNIQUE (chain, pair_address)
);

CREATE TABLE IF NOT EXISTS token_prices (
    time TIMESTAMPTZ NOT NULL,
    pair_id BIGINT NOT NULL REFERENCES token_pairs(id) ON DELETE CASCADE,
    price_usd NUMERIC,
    price_native NUMERIC,
    liquidity_usd NUMERIC,
    volume_5m_usd NUMERIC,
    volume_1h_usd NUMERIC,
    volume_6h_usd NUMERIC,
    volume_24h_usd NUMERIC,
    buys_5m INTEGER NOT NULL DEFAULT 0,
    sells_5m INTEGER NOT NULL DEFAULT 0,
    buys_1h INTEGER NOT NULL DEFAULT 0,
    sells_1h INTEGER NOT NULL DEFAULT 0,
    buys_24h INTEGER NOT NULL DEFAULT 0,
    sells_24h INTEGER NOT NULL DEFAULT 0,
    market_cap_usd NUMERIC,
    fdv_usd NUMERIC,
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT token_prices_time_pair_id_key UNIQUE (time, pair_id)
);

CREATE TABLE IF NOT EXISTS raw_api_snapshots (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES ingestion_runs(id) ON DELETE SET NULL,
    source TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    chain TEXT,
    token_address TEXT,
    pair_address TEXT,
    raw_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS risk_checks (
    id BIGSERIAL PRIMARY KEY,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT REFERENCES token_pairs(id) ON DELETE CASCADE,
    run_id BIGINT REFERENCES ingestion_runs(id) ON DELETE SET NULL,
    check_category TEXT NOT NULL,
    check_name TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    score NUMERIC,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS market_filter_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT NOT NULL REFERENCES token_pairs(id) ON DELETE CASCADE,
    market_filter_status TEXT NOT NULL,
    market_filter_pass BOOLEAN NOT NULL,
    market_filter_reason TEXT NOT NULL,
    data_readiness_status TEXT NOT NULL,
    early_category TEXT,
    passes_early_dex_filter BOOLEAN,
    dump_risk_category TEXT,
    passes_anti_dump_filter BOOLEAN,
    activity_category TEXT,
    passes_market_activity_filter BOOLEAN,
    market_warning_level TEXT,
    market_warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT market_filter_results_run_token_pair_key UNIQUE (run_id, token_id, pair_id)
);

CREATE TABLE IF NOT EXISTS contract_risk_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT NOT NULL REFERENCES token_pairs(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    contract_risk_status TEXT NOT NULL,
    contract_risk_pass BOOLEAN NOT NULL,
    contract_risk_reason TEXT NOT NULL,
    risk_score NUMERIC,
    risk_level TEXT,
    mint_authority_status TEXT,
    freeze_authority_status TEXT,
    top_holders_percent NUMERIC,
    dev_wallet_percent NUMERIC,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT contract_risk_results_run_token_source_key UNIQUE (run_id, token_id, source)
);

CREATE TABLE IF NOT EXISTS liquidity_filter_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT NOT NULL REFERENCES token_pairs(id) ON DELETE CASCADE,
    liquidity_status TEXT NOT NULL,
    liquidity_pass BOOLEAN NOT NULL,
    liquidity_reason TEXT NOT NULL,
    liquidity_usd NUMERIC,
    market_cap_usd NUMERIC,
    volume_1h_usd NUMERIC,
    mcap_to_liquidity_ratio NUMERIC,
    volume_to_liquidity_ratio NUMERIC,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT liquidity_filter_results_run_token_pair_key UNIQUE (run_id, token_id, pair_id)
);

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

CREATE TABLE IF NOT EXISTS watchlist_decisions (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    pair_id BIGINT NOT NULL REFERENCES token_pairs(id) ON DELETE CASCADE,
    market_filter_status TEXT NOT NULL,
    market_filter_pass BOOLEAN NOT NULL,
    market_warning_level TEXT,
    contract_risk_status TEXT,
    contract_risk_pass BOOLEAN,
    risk_score NUMERIC,
    top_holders_percent NUMERIC,
    wallet_status TEXT,
    wallet_pass BOOLEAN,
    top_holder_percent NUMERIC,
    top10_holders_percent NUMERIC,
    cluster_status TEXT,
    cluster_pass BOOLEAN,
    largest_cluster_size INTEGER,
    largest_cluster_funder TEXT,
    manipulation_status TEXT,
    manipulation_pass BOOLEAN,
    manipulation_score NUMERIC,
    final_watchlist_status TEXT NOT NULL,
    final_watchlist_pass BOOLEAN NOT NULL,
    final_watchlist_reason TEXT NOT NULL,
    intelligence_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT watchlist_decisions_run_token_key UNIQUE (run_id, token_id)
);

CREATE INDEX IF NOT EXISTS token_pairs_token_id_idx ON token_pairs(token_id);
CREATE INDEX IF NOT EXISTS token_prices_pair_time_idx ON token_prices(pair_id, time DESC);
CREATE INDEX IF NOT EXISTS raw_api_snapshots_pair_endpoint_created_idx
    ON raw_api_snapshots(pair_address, endpoint, created_at DESC);
CREATE INDEX IF NOT EXISTS risk_checks_run_token_pair_idx ON risk_checks(run_id, token_id, pair_id);
CREATE INDEX IF NOT EXISTS market_filter_results_created_idx ON market_filter_results(created_at DESC);
CREATE INDEX IF NOT EXISTS contract_risk_results_created_idx ON contract_risk_results(created_at DESC);
CREATE INDEX IF NOT EXISTS liquidity_filter_results_created_idx ON liquidity_filter_results(created_at DESC);
CREATE INDEX IF NOT EXISTS token_holders_run_token_rank_idx ON token_holders(run_id, token_id, rank);
CREATE INDEX IF NOT EXISTS wallet_analysis_results_created_idx ON wallet_analysis_results(created_at DESC);
CREATE INDEX IF NOT EXISTS wallet_funding_edges_run_token_idx ON wallet_funding_edges(run_id, token_id);
CREATE INDEX IF NOT EXISTS wallet_funding_edges_funder_idx ON wallet_funding_edges(funder_address);
CREATE INDEX IF NOT EXISTS cluster_analysis_results_created_idx ON cluster_analysis_results(created_at DESC);
CREATE INDEX IF NOT EXISTS wallet_intelligence_results_run_token_idx
    ON wallet_intelligence_results(run_id, token_id);
CREATE INDEX IF NOT EXISTS wallet_intelligence_results_wallet_idx
    ON wallet_intelligence_results(wallet_address);
CREATE INDEX IF NOT EXISTS wallet_intelligence_results_labels_idx
    ON wallet_intelligence_results USING GIN(labels);
CREATE INDEX IF NOT EXISTS wallet_relationship_edges_run_token_idx
    ON wallet_relationship_edges(run_id, token_id);
CREATE INDEX IF NOT EXISTS wallet_relationship_edges_from_to_idx
    ON wallet_relationship_edges(from_wallet, to_wallet);
CREATE INDEX IF NOT EXISTS wallet_manipulation_results_created_idx
    ON wallet_manipulation_results(created_at DESC);
CREATE INDEX IF NOT EXISTS dev_wallet_audit_results_created_idx
    ON dev_wallet_audit_results(created_at DESC);
CREATE INDEX IF NOT EXISTS dev_wallet_audit_results_wallet_idx
    ON dev_wallet_audit_results(dev_wallet_address);
CREATE INDEX IF NOT EXISTS watchlist_decisions_final_idx
    ON watchlist_decisions(final_watchlist_status, final_watchlist_pass, created_at DESC);

DROP VIEW IF EXISTS latest_token_data_readiness;

CREATE VIEW latest_token_data_readiness AS
WITH latest_run AS (
    SELECT MAX(id) AS run_id
    FROM ingestion_runs
    WHERE source = 'dexscreener_latest_profiles'
),
checks AS (
    SELECT
        rc.run_id,
        rc.token_id,
        rc.pair_id,
        BOOL_OR(rc.check_name = 'price_available' AND rc.risk_level = 'PASS') AS has_price,
        BOOL_OR(rc.check_name = 'volume_1h_available' AND rc.risk_level = 'PASS') AS has_volume_1h,
        BOOL_OR(rc.check_name = 'market_cap_available' AND rc.risk_level = 'PASS') AS has_market_cap,
        BOOL_OR(rc.check_name = 'fdv_available' AND rc.risk_level = 'PASS') AS has_fdv,
        BOOL_OR(rc.check_name = 'pair_created_at_available' AND rc.risk_level = 'PASS') AS has_pair_created_at,
        BOOL_OR(rc.check_name = 'txns_available' AND rc.risk_level = 'PASS') AS has_txns,
        BOOL_OR(rc.check_name = 'price_change_available' AND rc.risk_level = 'PASS') AS has_price_change,
        BOOL_OR(rc.check_name = 'liquidity_ok' AND rc.risk_level = 'PASS') AS has_liquidity,
        BOOL_OR(rc.check_name = 'missing_liquidity') AS missing_liquidity,
        BOOL_OR(rc.check_name = 'low_volume_5m') AS low_volume_5m
    FROM risk_checks rc
    JOIN latest_run lr
        ON rc.run_id = lr.run_id
    GROUP BY rc.run_id, rc.token_id, rc.pair_id
)
SELECT
    c.run_id,
    t.id AS token_id,
    p.id AS pair_id,
    t.symbol,
    t.name,
    t.chain,
    t.address AS token_address,
    p.pair_address,
    c.has_price,
    c.has_volume_1h,
    c.has_market_cap,
    c.has_fdv,
    c.has_pair_created_at,
    c.has_txns,
    c.has_price_change,
    c.has_liquidity,
    c.missing_liquidity,
    c.low_volume_5m,
    CASE
        WHEN c.has_price = FALSE
          OR c.has_volume_1h = FALSE
          OR c.has_market_cap = FALSE
          OR c.has_fdv = FALSE
          OR c.has_pair_created_at = FALSE
          OR c.has_txns = FALSE
          OR c.has_price_change = FALSE
            THEN 'NOT_READY'
        WHEN c.missing_liquidity = TRUE
            THEN 'PARTIAL_BUT_PASS'
        ELSE 'READY_FOR_ANALYSIS'
    END AS data_readiness_status
FROM checks c
JOIN tokens t
    ON t.id = c.token_id
JOIN token_pairs p
    ON p.id = c.pair_id;

COMMIT;
