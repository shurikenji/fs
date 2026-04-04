"""Database DDL for platform-control."""

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS service_sources (
    id                      TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    upstream_base_url       TEXT NOT NULL,
    public_base_url         TEXT,
    source_type             TEXT NOT NULL DEFAULT 'newapi',
    enabled                 INTEGER NOT NULL DEFAULT 1,
    sort_order              INTEGER NOT NULL DEFAULT 0,
    quota_multiple          REAL NOT NULL DEFAULT 1.0,
    supports_group_chain    INTEGER NOT NULL DEFAULT 0,
    ratio_config_enabled    INTEGER NOT NULL DEFAULT 0,
    public_pricing_enabled  INTEGER NOT NULL DEFAULT 1,
    public_balance_enabled  INTEGER NOT NULL DEFAULT 0,
    public_keys_enabled     INTEGER NOT NULL DEFAULT 1,
    public_logs_enabled     INTEGER NOT NULL DEFAULT 1,
    balance_rate            REAL NOT NULL DEFAULT 1.0,
    auth_mode               TEXT NOT NULL DEFAULT 'header',
    auth_user_header        TEXT,
    auth_user_value         TEXT,
    auth_token              TEXT,
    auth_cookie             TEXT,
    pricing_path            TEXT DEFAULT '/api/pricing',
    ratio_config_path       TEXT DEFAULT '/api/ratio_config',
    log_path                TEXT DEFAULT '/api/log/self',
    token_search_path       TEXT DEFAULT '/api/token/search',
    groups_path             TEXT,
    manual_groups           TEXT,
    hidden_groups           TEXT,
    excluded_models         TEXT,
    notes                   TEXT,
    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS proxy_endpoints (
    id                  TEXT PRIMARY KEY,
    source_id           TEXT REFERENCES service_sources(id),
    name                TEXT NOT NULL,
    domain              TEXT NOT NULL UNIQUE,
    target_host         TEXT NOT NULL,
    target_protocol     TEXT NOT NULL DEFAULT 'https',
    tls_skip_verify     INTEGER NOT NULL DEFAULT 0,
    port                INTEGER NOT NULL UNIQUE,
    status              TEXT NOT NULL DEFAULT 'active',
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deploy_jobs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type            TEXT NOT NULL,
    status              TEXT NOT NULL,
    target_ref          TEXT NOT NULL,
    request_payload     TEXT,
    response_payload    TEXT,
    error_message       TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS portal_modules (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    path                TEXT NOT NULL,
    public_url          TEXT,
    icon                TEXT,
    description         TEXT,
    enabled             INTEGER NOT NULL DEFAULT 1,
    is_public           INTEGER NOT NULL DEFAULT 1,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    action              TEXT NOT NULL,
    details             TEXT,
    ip_address          TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pricing_runtime_settings (
    key                 TEXT PRIMARY KEY,
    value               TEXT,
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pricing_sync_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id           TEXT NOT NULL,
    trigger             TEXT NOT NULL DEFAULT 'manual',
    status              TEXT NOT NULL,
    model_count         INTEGER NOT NULL DEFAULT 0,
    group_count         INTEGER NOT NULL DEFAULT 0,
    translated_count    INTEGER NOT NULL DEFAULT 0,
    duration_ms         INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);
"""
