const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');
const Proxy = require('../models/Proxy');

const NGINX_SITES = '/etc/nginx/sites-available';
const NGINX_ENABLED = '/etc/nginx/sites-enabled';
const SSL_PATH = '/etc/letsencrypt/live';
const CERT_NAME = 'proxy-gateway';

class NginxManager {
    // Tìm SSL cert path
    static findSSLPath() {
        const possibleNames = [CERT_NAME, 'shupremium-proxy', 'gpt-shupremium'];
        for (const name of possibleNames) {
            const certPath = path.join(SSL_PATH, name, 'fullchain.pem');
            // Dùng sudo test vì /etc/letsencrypt/live cần root
            try {
                require('child_process').execSync(`sudo test -f ${certPath}`, { stdio: 'ignore' });
                return path.join(SSL_PATH, name);
            } catch (e) {
                continue;
            }
        }
        return null;
    }

    // Generate nginx config cho một proxy
    static generateConfig(proxy) {
        const sslPath = this.findSSLPath();
        const safeName = proxy.name.toLowerCase().replace(/[^a-z0-9]/g, '-');
        
        if (sslPath) {
            return this._sslConfig(proxy, sslPath, safeName);
        }
        return this._httpConfig(proxy, safeName);
    }

    static _sslConfig(proxy, sslPath, safeName) {
        return `# Proxy: ${proxy.name}
# Domain: ${proxy.domain} -> ${proxy.target_host}
# Port: ${proxy.port}
# Generated: ${new Date().toISOString()}

server {
    listen 80;
    server_name ${proxy.domain};
    
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    
    location / {
        return 301 https://\\$server_name\\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name ${proxy.domain};
    
    # SSL
    ssl_certificate ${sslPath}/fullchain.pem;
    ssl_certificate_key ${sslPath}/privkey.pem;
    include /etc/nginx/snippets/ssl-params.conf;
    include /etc/nginx/snippets/security-headers.conf;
    
    # Logs
    access_log /var/log/nginx/${safeName}-access.log;
    error_log /var/log/nginx/${safeName}-error.log;

    # Security blocks
    location ~ /\\.(env|git|svn|htaccess) { return 403; }
    location ~* \\.(php|asp|aspx|jsp|cgi)$ { return 403; }
    location ~* ^/(shell|cmd|backdoor|admin|phpmyadmin|wp-admin) { return 403; }

    # Health check
    location = /health {
        proxy_pass http://127.0.0.1:${proxy.port}/health;
        access_log off;
    }

    # API endpoints
    location /v1/ {
        proxy_pass http://127.0.0.1:${proxy.port};
        include /etc/nginx/snippets/proxy-params.conf;
        
        sub_filter '${proxy.target_host}' '${proxy.domain}';
        sub_filter_once off;
        sub_filter_types application/json text/plain *;
    }

    # Billing dashboard
    location /dashboard/billing/ {
        proxy_pass http://127.0.0.1:${proxy.port};
        include /etc/nginx/snippets/proxy-params.conf;
    }

    # Root path
    location = / {
        proxy_pass http://127.0.0.1:${proxy.port};
        include /etc/nginx/snippets/proxy-params.conf;
    }

    # Block everything else
    location / { return 404; }
}
`;
    }

    static _httpConfig(proxy, safeName) {
        return `# Proxy: ${proxy.name} (HTTP only - SSL chưa cấu hình)
# Domain: ${proxy.domain} -> ${proxy.target_host}
# Port: ${proxy.port}
# Generated: ${new Date().toISOString()}

server {
    listen 80;
    server_name ${proxy.domain};

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location = /health {
        proxy_pass http://127.0.0.1:${proxy.port}/health;
    }

    location /v1/ {
        proxy_pass http://127.0.0.1:${proxy.port};
        include /etc/nginx/snippets/proxy-params.conf;
    }

    location = / {
        proxy_pass http://127.0.0.1:${proxy.port};
    }

    location / { return 404; }
}
`;
    }

    // Lưu config và enable site
    static async saveConfig(proxy) {
        const config = this.generateConfig(proxy);
        const filename = `proxy-${proxy.id}.conf`;
        const tempPath = `/tmp/${filename}`;
        const destPath = `${NGINX_SITES}/${filename}`;
        const enabledPath = `${NGINX_ENABLED}/${filename}`;
        
        // Ghi file tạm
        fs.writeFileSync(tempPath, config);
        
        // Move với sudo
        await this._exec(`sudo mv ${tempPath} ${destPath}`);
        await this._exec(`sudo chmod 644 ${destPath}`);
        
        // Enable site
        await this._exec(`sudo ln -sf ${destPath} ${enabledPath}`).catch(() => {});
        
        console.log(`[Nginx] Saved config for ${proxy.domain}`);
    }

    // Xóa config
    static async deleteConfig(proxyId) {
        const filename = `proxy-${proxyId}.conf`;
        await this._exec(`sudo rm -f ${NGINX_ENABLED}/${filename}`).catch(() => {});
        await this._exec(`sudo rm -f ${NGINX_SITES}/${filename}`).catch(() => {});
        console.log(`[Nginx] Deleted config for proxy ${proxyId}`);
    }

    // Test config
    static async test() {
        return this._exec('sudo nginx -t');
    }

    // Reload nginx
    static async reload() {
        await this.test();
        return this._exec('sudo nginx -s reload');
    }

    // Regenerate tất cả configs
    static async generateAll() {
        const proxies = Proxy.getActive();
        for (const proxy of proxies) {
            await this.saveConfig(proxy);
        }
        console.log(`[Nginx] Regenerated ${proxies.length} configs`);
        return proxies.length;
    }

    static _exec(cmd) {
        return new Promise((resolve, reject) => {
            exec(cmd, { timeout: 30000 }, (error, stdout, stderr) => {
                if (error) reject(new Error(stderr || error.message));
                else resolve(stdout);
            });
        });
    }
}

module.exports = NginxManager;
