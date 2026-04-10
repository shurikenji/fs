"""
db/models.py — Tạo tất cả tables, indexes, và default settings.
Gọi init_db() một lần khi khởi động application.
"""
from __future__ import annotations


# ── DDL Statements ──────────────────────────────────────────────────────────

_CREATE_TABLES = """
-- USERS
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id     INTEGER UNIQUE NOT NULL,
    username        TEXT,
    full_name       TEXT,
    is_admin        INTEGER DEFAULT 0,
    disable_discounts INTEGER DEFAULT 0,
    is_banned       INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);
CREATE INDEX IF NOT EXISTS idx_users_tgid ON users(telegram_id);

-- WALLETS (1 user = 1 wallet)
CREATE TABLE IF NOT EXISTS wallets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER UNIQUE NOT NULL REFERENCES users(id),
    balance         INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);

-- WALLET TRANSACTIONS (audit log)
CREATE TABLE IF NOT EXISTS wallet_transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    amount          INTEGER NOT NULL,
    balance_after   INTEGER NOT NULL,
    type            TEXT NOT NULL,
    reference_id    TEXT,
    description     TEXT,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);
CREATE INDEX IF NOT EXISTS idx_wtx_user ON wallet_transactions(user_id);

-- API SERVERS (multi-server NewAPI)
CREATE TABLE IF NOT EXISTS api_servers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    user_id_header  TEXT NOT NULL,
    access_token    TEXT NOT NULL,
    price_per_unit  INTEGER NOT NULL,
    dollar_per_unit REAL NOT NULL DEFAULT 10.0,
    quota_multiple  REAL NOT NULL DEFAULT 1.0,
    quota_per_unit  INTEGER NOT NULL,
    is_active       INTEGER DEFAULT 1,
    sort_order      INTEGER DEFAULT 0,
    default_group   TEXT,
    -- New fields for multi-type support
    api_type                TEXT DEFAULT 'newapi',
    supports_multi_group   INTEGER DEFAULT 0,
    groups_cache           TEXT,
    groups_updated_at      TEXT,
    manual_groups          TEXT,
    -- Flexible authentication
    auth_type              TEXT DEFAULT 'header',
    auth_user_header       TEXT,
    auth_user_value        TEXT,
    auth_token             TEXT,
    auth_cookie            TEXT,
    -- Custom
    custom_headers         TEXT,
    groups_endpoint        TEXT,
    import_spend_accrual_enabled INTEGER DEFAULT 0,
    discount_stack_mode    TEXT DEFAULT 'exclusive',
    discount_allowed_stack_types TEXT DEFAULT 'cashback',
    supports_key_lookup_by_id INTEGER DEFAULT 0,
    token_key_endpoint_template TEXT DEFAULT '/api/token/{id}/key',
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);

-- CATEGORIES
CREATE TABLE IF NOT EXISTS categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    icon            TEXT DEFAULT '📦',
    description     TEXT,
    cat_type        TEXT DEFAULT 'general',
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);

-- PRODUCTS
CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id     INTEGER NOT NULL REFERENCES categories(id),
    server_id       INTEGER REFERENCES api_servers(id),
    name            TEXT NOT NULL,
    description     TEXT,
    price_vnd       INTEGER NOT NULL,
    product_type    TEXT NOT NULL,
    quota_amount    INTEGER DEFAULT 0,
    dollar_amount   REAL DEFAULT 0,
    group_name      TEXT,
    delivery_type   TEXT DEFAULT 'auto',
    delivery_data   TEXT,
    stock           INTEGER DEFAULT -1,
    is_active       INTEGER DEFAULT 1,
    sort_order      INTEGER DEFAULT 0,
    meta_json       TEXT,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);
CREATE INDEX IF NOT EXISTS idx_prod_cat ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_prod_srv ON products(server_id);

-- CHATGPT ACCOUNTS STOCK — ⚠️ DEPRECATED: Dùng account_stocks thay thế.
-- Giữ lại DDL để không mất data cũ nếu có. Không dùng cho tính năng mới.
CREATE TABLE IF NOT EXISTS chatgpt_accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    account_data    TEXT NOT NULL,
    is_sold         INTEGER DEFAULT 0,
    sold_to_user    INTEGER REFERENCES users(id),
    sold_order_id   INTEGER,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    sold_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_cga_prod ON chatgpt_accounts(product_id, is_sold);

-- ACCOUNT STOCKS (bảng chung cho tất cả loại tài khoản: ChatGPT, Netflix, ...)
CREATE TABLE IF NOT EXISTS account_stocks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    account_data    TEXT NOT NULL,
    is_sold         INTEGER DEFAULT 0,
    sold_to_user    INTEGER REFERENCES users(id),
    sold_order_id   INTEGER,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    sold_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_accstk_prod ON account_stocks(product_id, is_sold);

-- ORDERS
CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_code      TEXT UNIQUE NOT NULL,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    product_id      INTEGER REFERENCES products(id),
    product_name    TEXT,
    product_type    TEXT NOT NULL,
    amount          INTEGER NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1,
    payment_method  TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',
    api_key         TEXT,
    api_token_id    INTEGER,
    api_token_name  TEXT,
    server_id       INTEGER REFERENCES api_servers(id),
    quota_before    INTEGER,
    quota_after     INTEGER,
    group_name      TEXT,
    existing_key    TEXT,
    custom_quota    INTEGER,
    delivery_info   TEXT,
    delivery_token_names TEXT,
    user_input_data TEXT,
    base_amount     INTEGER,
    discount_amount INTEGER DEFAULT 0,
    cashback_amount INTEGER DEFAULT 0,
    spend_credit_amount INTEGER DEFAULT 0,
    pricing_version_id INTEGER,
    applied_tier_id INTEGER,
    pricing_snapshot TEXT,
    promotion_snapshot TEXT,
    mb_transaction_id TEXT,
    qr_content      TEXT,
    paid_at         TEXT,
    completed_at    TEXT,
    is_refunded     INTEGER DEFAULT 0,
    refund_reason   TEXT,
    refunded_at     TEXT,
    expired_at      TEXT,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);
CREATE INDEX IF NOT EXISTS idx_ord_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_ord_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_ord_code ON orders(order_code);
CREATE INDEX IF NOT EXISTS idx_ord_completed_at ON orders(completed_at);
CREATE INDEX IF NOT EXISTS idx_ord_refunded_at ON orders(refunded_at);

-- SERVER PRICING VERSIONS
CREATE TABLE IF NOT EXISTS server_pricing_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id       INTEGER NOT NULL REFERENCES api_servers(id),
    version_code    INTEGER NOT NULL,
    name            TEXT,
    effective_from  TEXT NOT NULL,
    price_per_unit  INTEGER NOT NULL,
    quota_per_unit  INTEGER NOT NULL,
    dollar_per_unit REAL NOT NULL DEFAULT 10.0,
    quota_multiple  REAL NOT NULL DEFAULT 1.0,
    rounding_mode   TEXT DEFAULT 'round',
    rounding_step   INTEGER DEFAULT 1,
    min_payable_amount INTEGER DEFAULT 1000,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    UNIQUE(server_id, version_code)
);
CREATE INDEX IF NOT EXISTS idx_spv_server_effective ON server_pricing_versions(server_id, effective_from);

-- SERVER DISCOUNT TIERS
CREATE TABLE IF NOT EXISTS server_discount_tiers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id       INTEGER NOT NULL REFERENCES api_servers(id),
    name            TEXT NOT NULL,
    min_spend_vnd   INTEGER NOT NULL,
    is_active       INTEGER DEFAULT 1,
    sort_order      INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);
CREATE INDEX IF NOT EXISTS idx_sdt_server ON server_discount_tiers(server_id, min_spend_vnd);

-- SERVER TIER BENEFITS
CREATE TABLE IF NOT EXISTS server_tier_benefits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tier_id         INTEGER NOT NULL REFERENCES server_discount_tiers(id),
    benefit_type    TEXT NOT NULL,
    value_amount    REAL,
    config_json     TEXT,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);
CREATE INDEX IF NOT EXISTS idx_stb_tier ON server_tier_benefits(tier_id);

-- PRODUCT PROMOTIONS
CREATE TABLE IF NOT EXISTS product_promotions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    name            TEXT NOT NULL,
    promotion_type  TEXT NOT NULL,
    value_amount    REAL,
    config_json     TEXT,
    conditions_json TEXT,
    starts_at       TEXT,
    ends_at         TEXT,
    priority        INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);
CREATE INDEX IF NOT EXISTS idx_pp_product ON product_promotions(product_id, priority);

-- USER KEYS (Keys của tôi)
CREATE TABLE IF NOT EXISTS user_keys (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    server_id       INTEGER NOT NULL REFERENCES api_servers(id),
    api_key         TEXT NOT NULL,
    api_token_id    INTEGER,
    label           TEXT,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);
CREATE INDEX IF NOT EXISTS idx_ukeys_user ON user_keys(user_id);

-- API KEY REGISTRY
CREATE TABLE IF NOT EXISTS api_key_registry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id       INTEGER NOT NULL REFERENCES api_servers(id),
    api_key_hash    TEXT NOT NULL,
    owner_user_id   INTEGER NOT NULL REFERENCES users(id),
    masked_key      TEXT,
    last_observed_total_quota INTEGER DEFAULT 0,
    last_pricing_version_id INTEGER REFERENCES server_pricing_versions(id),
    first_seen_at   TEXT DEFAULT (datetime('now', '+7 hours')),
    last_seen_at    TEXT DEFAULT (datetime('now', '+7 hours')),
    is_owner_locked INTEGER DEFAULT 1,
    UNIQUE(server_id, api_key_hash)
);
CREATE INDEX IF NOT EXISTS idx_akr_owner ON api_key_registry(owner_user_id, server_id);

-- API KEY VALUATION EVENTS
CREATE TABLE IF NOT EXISTS api_key_valuation_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id       INTEGER NOT NULL REFERENCES api_servers(id),
    api_key_registry_id INTEGER REFERENCES api_key_registry(id),
    user_id         INTEGER NOT NULL REFERENCES users(id),
    pricing_version_id INTEGER REFERENCES server_pricing_versions(id),
    source          TEXT NOT NULL,
    source_ref      TEXT,
    status          TEXT NOT NULL,
    observed_total_quota INTEGER DEFAULT 0,
    previous_recorded_quota INTEGER DEFAULT 0,
    credited_delta_quota INTEGER DEFAULT 0,
    credited_value_vnd INTEGER DEFAULT 0,
    detail_json     TEXT,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);
CREATE INDEX IF NOT EXISTS idx_akve_registry ON api_key_valuation_events(api_key_registry_id, created_at);

-- API KEY ALERT STATES
CREATE TABLE IF NOT EXISTS api_key_alert_states (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    server_id       INTEGER NOT NULL REFERENCES api_servers(id),
    api_key_hash    TEXT NOT NULL,
    masked_key      TEXT,
    last_seen_remain_quota INTEGER DEFAULT 0,
    last_seen_balance_dollar REAL DEFAULT 0,
    last_alert_threshold REAL,
    last_alert_sent_at TEXT,
    last_checked_at  TEXT DEFAULT (datetime('now', '+7 hours')),
    last_error      TEXT,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    UNIQUE(user_id, server_id, api_key_hash)
);
CREATE INDEX IF NOT EXISTS idx_akas_user_server ON api_key_alert_states(user_id, server_id, updated_at);

-- SPEND LEDGER
CREATE TABLE IF NOT EXISTS spend_ledger (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    server_id       INTEGER NOT NULL REFERENCES api_servers(id),
    source_type     TEXT NOT NULL,
    source_ref      TEXT NOT NULL,
    amount          INTEGER NOT NULL,
    direction       TEXT NOT NULL,
    description     TEXT,
    detail_json     TEXT,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    UNIQUE(source_type, source_ref)
);
CREATE INDEX IF NOT EXISTS idx_spend_ledger_user_server ON spend_ledger(user_id, server_id, created_at);

-- USER SERVER SPEND SUMMARY
CREATE TABLE IF NOT EXISTS user_server_spend_summary (
    user_id         INTEGER NOT NULL REFERENCES users(id),
    server_id       INTEGER NOT NULL REFERENCES api_servers(id),
    total_spend_vnd INTEGER DEFAULT 0,
    last_ledger_id  INTEGER REFERENCES spend_ledger(id),
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    PRIMARY KEY (user_id, server_id)
);

-- ADMIN NOTIFICATION EVENTS (idempotent admin Telegram outbox)
CREATE TABLE IF NOT EXISTS admin_notification_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL REFERENCES orders(id),
    event_type      TEXT NOT NULL,
    target_chat_id  INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    message_text    TEXT,
    error_message   TEXT,
    sent_at         TEXT,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    UNIQUE(order_id, event_type, target_chat_id)
);
CREATE INDEX IF NOT EXISTS idx_admin_notify_order_event ON admin_notification_events(order_id, event_type);

-- FSM STORAGE
CREATE TABLE IF NOT EXISTS fsm_storage (
    storage_id      TEXT PRIMARY KEY,
    bot_id          INTEGER NOT NULL,
    chat_id         INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    thread_id       INTEGER,
    business_connection_id TEXT,
    destiny         TEXT NOT NULL,
    state           TEXT,
    data_json       TEXT NOT NULL DEFAULT '{}',
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);
CREATE INDEX IF NOT EXISTS idx_fsm_storage_lookup ON fsm_storage(bot_id, chat_id, user_id, destiny);

-- SETTINGS (key-value)
CREATE TABLE IF NOT EXISTS settings (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    description     TEXT,
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);

-- PROCESSED TRANSACTIONS (dedup MBBank)
CREATE TABLE IF NOT EXISTS processed_transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id  TEXT UNIQUE NOT NULL,
    order_code      TEXT,
    amount          INTEGER,
    processed_at    TEXT DEFAULT (datetime('now', '+7 hours'))
);

-- LOGS
CREATE TABLE IF NOT EXISTS logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    level           TEXT DEFAULT 'info',
    module          TEXT,
    message         TEXT NOT NULL,
    detail          TEXT,
    created_at      TEXT DEFAULT (datetime('now', '+7 hours'))
);

-- GROUP TRANSLATIONS (AI translation cache)
CREATE TABLE IF NOT EXISTS group_translations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    original_name   TEXT NOT NULL,
    api_type        TEXT NOT NULL,
    name_en         TEXT,
    name_vi         TEXT,
    desc_en         TEXT,
    desc_vi         TEXT,
    category        TEXT,
    updated_at      TEXT DEFAULT (datetime('now', '+7 hours')),
    UNIQUE(original_name, api_type)
);
"""

# ── Default settings ────────────────────────────────────────────────────────

_DEFAULT_SETTINGS = [
    ("mb_api_url", "https://apicanhan.com/api/mbbankv3", "MBBank API URL"),
    ("mb_api_key", "", "API key apicanhan.com"),
    ("mb_username", "", "SĐT đăng nhập MB"),
    ("mb_password", "", "Mật khẩu MB"),
    ("mb_account_no", "", "STK nhận tiền"),
    ("mb_account_name", "", "Tên chủ TK"),
    ("mb_bank_id", "MB", "Bank ID cho VietQR"),
    ("poll_interval", "12", "Poll interval (giây)"),
    ("order_expire_min", "30", "Hết hạn đơn QR (phút)"),
    ("admin_telegram_ids", "", "Telegram IDs admin (phẩy)"),
    ("admin_notify_enabled", "true", "Bật/tắt thông báo đơn hàng cho admin qua Telegram"),
    ("admin_notify_order_completed", "true", "Thông báo khi đơn hàng hoàn thành"),
    ("admin_notify_service_paid", "true", "Thông báo khi đơn dịch vụ đã thanh toán và cần xử lý"),
    ("admin_notify_service_completed", "true", "Thông báo khi admin hoàn tất đơn dịch vụ"),
    ("admin_notify_order_refunded", "true", "Thông báo khi đơn hàng được hoàn tiền"),
    ("vietqr_template", "compact2", "Template VietQR"),
    ("support_url", "https://t.me/yoursupport", "Link hỗ trợ"),
    ("support_text", "Liên hệ admin để được hỗ trợ", "Nội dung hỗ trợ"),
    ("pagination_size", "6", "Items mỗi trang"),
    ("bot_name", "ShopBot", "Tên bot"),
    ("welcome_message", "Chào mừng bạn đến với ShopBot!", "Lời chào /start"),
    ("admin_password", "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9", "Mật khẩu admin panel (hash của admin123)"),
    ("wallet_topup_min", "30000", "Nạp ví tối thiểu (VNĐ)"),
    ("key_alert_enabled", "true", "Bật/tắt cảnh báo Telegram khi API key sắp hết số dư"),
    ("key_alert_poll_interval_min", "15", "Chu kỳ quét cảnh báo API key (phút)"),
    ("key_alert_thresholds", "5,3,1", "Các mốc cảnh báo API key theo USD"),
    # Custom dollar settings
    ("quota_per_dollar", "500000", "Quota tương đương $1 (hằng số quy đổi)"),
    ("custom_dollar_min_wallet", "1", "$ tối thiểu nhập custom - thanh toán ví"),
    ("custom_dollar_min_qr", "10", "$ tối thiểu nhập custom - thanh toán QR"),
    ("custom_vnd_min", "10000", "VNĐ tối thiểu đơn custom $ (floor)"),
    ("wallet_topup_max", "100000000", "Nạp ví tối đa (VNĐ)"),
    # AI Translation Settings
    ("ai_provider", "openai", "AI provider: openai, openai_compatible, anthropic, gemini"),
    ("ai_api_key", "", "API key for AI translation"),
    ("ai_model", "gpt-4o-mini", "Model sử dụng cho translation"),
    ("ai_base_url", "", "Base URL for OpenAI Compatible API (Ollama, LM Studio, etc.)"),
    ("ai_enabled", "false", "Bật/tắt AI translation"),
    # Delivery message templates
    ("msg_key_new",
     "✅ Đơn <b>{order_code}</b> hoàn thành!\n\n"
     "🔑 API Key của bạn:\n<code>{api_key}</code>\n\n"
     "💵 Số dư: <b>{dollar}</b>\n"
     "🖥 Server: <b>{server}</b>\n\n"
     "⚠️ Vui lòng lưu key cẩn thận!",
     "Thông báo giao key mới ({order_code},{api_key},{dollar},{server})"),
    ("msg_key_topup",
     "✅ Đơn <b>{order_code}</b> hoàn thành!\n\n"
     "🔑 Key: <code>{api_key}</code>\n"
     "💵 Số dư trước: <b>{dollar_before}</b>\n"
     "💵 Nạp thêm: <b>+{dollar_added}</b>\n"
     "💵 Số dư sau: <b>{dollar_after}</b>",
     "Thông báo nạp key ({order_code},{api_key},{dollar_before},{dollar_added},{dollar_after})"),
    ("msg_chatgpt",
     "✅ Đơn <b>{order_code}</b> hoàn thành!\n\n"
     "📦 Thông tin tài khoản:\n<code>{account_data}</code>\n\n"
     "⚠️ Vui lòng lưu thông tin và đổi mật khẩu ngay!",
     "Thông báo giao tài khoản tự động ({order_code},{account_data})"),
    ("msg_wallet_topup",
     "✅ Nạp ví thành công!\n\n"
     "💰 Số tiền: <b>{amount}</b>\n"
     "👛 Số dư mới: <b>{balance}</b>\n"
     "📋 Mã đơn: <b>{order_code}</b>",
     "Thông báo nạp ví ({order_code},{amount},{balance})"),
]


async def _legacy_init_db_impl() -> None:
    """Legacy compatibility entrypoint that delegates to bootstrap."""
    from db.bootstrap import init_db as bootstrap_init_db

    await bootstrap_init_db()
    return


async def init_db() -> None:
    """Backward-compatible public entrypoint that delegates to bootstrap."""
    from db.bootstrap import init_db as bootstrap_init_db

    await bootstrap_init_db()

