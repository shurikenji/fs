const db = require('./database');

class ActivityLog {
    static create(action, details, ip) {
        db.prepare('INSERT INTO activity_logs (action, details, ip_address) VALUES (?, ?, ?)')
          .run(action, typeof details === 'string' ? details : JSON.stringify(details), ip);
    }

    static getRecent(limit = 50) {
        return db.prepare('SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT ?').all(limit);
    }

    static clear() {
        db.prepare('DELETE FROM activity_logs').run();
    }
}

module.exports = ActivityLog;
