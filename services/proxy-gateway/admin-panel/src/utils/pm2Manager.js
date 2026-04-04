const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');
const Proxy = require('../models/Proxy');

const PROXY_SERVICE_PATH = path.join(__dirname, '../../../proxy-service');
const ECOSYSTEM_PATH = path.join(PROXY_SERVICE_PATH, 'ecosystem.config.js');
const LOCK_FILE = '/tmp/pm2-reload.lock';

class PM2Manager {
    // Generate ecosystem.config.js từ database
    static generateEcosystem() {
        const proxies = Proxy.getActive();
        
        const apps = proxies.map(proxy => {
            const safeName = proxy.name.toLowerCase().replace(/[^a-z0-9]/g, '');
            return {
                name: `proxy-${safeName}`,
                script: './src/index.js',
                instances: 2,
                exec_mode: 'cluster',
                autorestart: true,
                watch: false,
                max_memory_restart: '512M',
                env: {
                    NODE_ENV: 'production',
                    PORT: proxy.port,
                    TARGET_HOST: proxy.target_host,
                    TARGET_PROTOCOL: proxy.target_protocol || 'https',
                    TLS_SKIP_VERIFY: proxy.tls_skip_verify ? 'true' : 'false',
                    SERVICE_NAME: proxy.name,
                    PROXY_DOMAIN: proxy.domain,
                    LOG_LEVEL: 'warn'
                },
                error_file: `./logs/${safeName}-error.log`,
                out_file: `./logs/${safeName}-out.log`,
                log_date_format: 'YYYY-MM-DD HH:mm:ss',
                merge_logs: true
            };
        });

        const config = `// PM2 Ecosystem - Auto-generated ${new Date().toISOString()}
// DO NOT EDIT MANUALLY - Managed by Admin Panel

module.exports = {
  apps: ${JSON.stringify(apps, null, 4)}
};
`;
        fs.writeFileSync(ECOSYSTEM_PATH, config);
        console.log(`[PM2] Generated ecosystem with ${apps.length} apps`);
        return apps.length;
    }

    // Reload PM2 với lock để tránh race condition
    static async reload() {
        // Simple lock mechanism
        if (fs.existsSync(LOCK_FILE)) {
            const lockTime = fs.statSync(LOCK_FILE).mtimeMs;
            if (Date.now() - lockTime < 30000) { // Lock 30 giây
                throw new Error('PM2 đang reload, vui lòng đợi...');
            }
        }
        
        fs.writeFileSync(LOCK_FILE, Date.now().toString());
        
        try {
            this.generateEcosystem();
            await this._exec(`cd ${PROXY_SERVICE_PATH} && pm2 reload ecosystem.config.js --update-env`);
        } finally {
            fs.unlinkSync(LOCK_FILE);
        }
    }

    static async restart(name) {
        return this._exec(`pm2 restart ${name}`);
    }

    static async stop(name) {
        return this._exec(`pm2 stop ${name}`);
    }

    static async getStatus() {
        return new Promise((resolve) => {
            exec('pm2 jlist', (error, stdout) => {
                if (error) return resolve([]);
                try {
                    resolve(JSON.parse(stdout));
                } catch {
                    resolve([]);
                }
            });
        });
    }

    static _exec(cmd) {
        return new Promise((resolve, reject) => {
            exec(cmd, { timeout: 60000 }, (error, stdout, stderr) => {
                if (error) reject(new Error(stderr || error.message));
                else resolve(stdout);
            });
        });
    }
}

module.exports = PM2Manager;
