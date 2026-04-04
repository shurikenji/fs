const db = require('./database');

class Proxy {
    static getAll() {
        return db.prepare('SELECT * FROM proxies ORDER BY port ASC').all();
    }

    static getActive() {
        return db.prepare('SELECT * FROM proxies WHERE status = ? ORDER BY port ASC').all('active');
    }

    static findById(id) {
        return db.prepare('SELECT * FROM proxies WHERE id = ?').get(id);
    }

    static findByDomain(domain) {
        return db.prepare('SELECT * FROM proxies WHERE domain = ?').get(domain);
    }

    static findByPort(port) {
        return db.prepare('SELECT * FROM proxies WHERE port = ?').get(port);
    }

    static create(data) {
        const stmt = db.prepare(`
            INSERT INTO proxies (name, domain, target_host, target_protocol, tls_skip_verify, port, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        `);
        const result = stmt.run(
            data.name,
            data.domain,
            data.target_host,
            data.target_protocol || 'https',
            data.tls_skip_verify ? 1 : 0,
            data.port,
            data.status || 'active'
        );
        return result.lastInsertRowid;
    }

    static update(id, data) {
        const stmt = db.prepare(`
            UPDATE proxies 
            SET name = ?, domain = ?, target_host = ?, target_protocol = ?, tls_skip_verify = ?, port = ?, 
                status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        `);
        stmt.run(
            data.name,
            data.domain,
            data.target_host,
            data.target_protocol || 'https',
            data.tls_skip_verify ? 1 : 0,
            data.port,
            data.status,
            id
        );
    }

    static updateStatus(id, status) {
        db.prepare('UPDATE proxies SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?')
          .run(status, id);
    }

    static delete(id) {
        db.prepare('DELETE FROM proxies WHERE id = ?').run(id);
    }

    static restore(data) {
        db.prepare(`
            INSERT OR REPLACE INTO proxies (
                id, name, domain, target_host, target_protocol, tls_skip_verify, port, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        `).run(
            data.id,
            data.name,
            data.domain,
            data.target_host,
            data.target_protocol || 'https',
            data.tls_skip_verify ? 1 : 0,
            data.port,
            data.status || 'active',
            data.created_at || null,
            data.updated_at || null
        );
    }

    static getNextPort() {
        const result = db.prepare('SELECT MAX(port) as max_port FROM proxies').get();
        return (result.max_port || 3000) + 1;
    }

    static getStats() {
        return {
            total: db.prepare('SELECT COUNT(*) as c FROM proxies').get().c,
            active: db.prepare('SELECT COUNT(*) as c FROM proxies WHERE status = ?').get('active').c,
            inactive: db.prepare('SELECT COUNT(*) as c FROM proxies WHERE status = ?').get('inactive').c
        };
    }
}

module.exports = Proxy;
