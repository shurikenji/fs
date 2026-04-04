const Database = require('better-sqlite3');
const path = require('path');
const bcrypt = require('bcryptjs');

const dbPath = path.join(__dirname, '../../data/admin.db');
const db = new Database(dbPath);

// Initialize tables
function init() {
    // Proxies table
    db.exec(`
        CREATE TABLE IF NOT EXISTS proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            domain TEXT UNIQUE NOT NULL,
            target_host TEXT NOT NULL,
            target_protocol TEXT NOT NULL DEFAULT 'https',
            tls_skip_verify INTEGER NOT NULL DEFAULT 0,
            port INTEGER UNIQUE NOT NULL,
            status TEXT DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    `);

    // Activity logs table
    db.exec(`
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details TEXT,
            ip_address TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    `);

    // Settings table
    db.exec(`
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    `);

    // Initialize default settings
    const defaults = [
        ['admin_password', bcrypt.hashSync('admin123', 10)],
        ['site_name', 'Proxy Gateway'],
        ['cloudflare_token', ''],
        ['admin_email', 'admin@localhost']
    ];

    const stmt = db.prepare('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)');
    defaults.forEach(([key, value]) => stmt.run(key, value));

    migrateSchema();

    console.log('[DB] Database initialized');
}

function migrateSchema() {
    const columns = db.prepare("PRAGMA table_info(proxies)").all();
    const columnNames = new Set(columns.map((column) => column.name));

    if (!columnNames.has('target_protocol')) {
        db.exec("ALTER TABLE proxies ADD COLUMN target_protocol TEXT NOT NULL DEFAULT 'https'");
    }

    if (!columnNames.has('tls_skip_verify')) {
        db.exec("ALTER TABLE proxies ADD COLUMN tls_skip_verify INTEGER NOT NULL DEFAULT 0");
    }
}

init();

module.exports = db;
