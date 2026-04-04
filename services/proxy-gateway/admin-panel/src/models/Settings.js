const db = require('./database');
const bcrypt = require('bcryptjs');

class Settings {
    static get(key) {
        const row = db.prepare('SELECT value FROM settings WHERE key = ?').get(key);
        return row ? row.value : null;
    }

    static set(key, value) {
        db.prepare(`
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
        `).run(key, value, value);
    }

    static verifyPassword(password) {
        const hash = this.get('admin_password');
        return bcrypt.compareSync(password, hash);
    }

    static changePassword(newPassword) {
        const hash = bcrypt.hashSync(newPassword, 10);
        this.set('admin_password', hash);
    }

    static getCloudflareToken() {
        return this.get('cloudflare_token') || '';
    }

    static setCloudflareToken(token) {
        this.set('cloudflare_token', token);
    }

    static isCloudflareConfigured() {
        const token = this.getCloudflareToken();
        return token && token.length > 20;
    }
}

module.exports = Settings;
