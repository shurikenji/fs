require('dotenv').config();
const express = require('express');
const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');

const app = express();
app.use(express.json({ limit: '2mb' }));

const PORT = parseInt(process.env.OPERATOR_PORT || '8091', 10);
const TOKEN = process.env.OPERATOR_TOKEN || 'change-me';
const ROOT_DOMAIN = process.env.ROOT_DOMAIN || 'shupremium.com';
const CERT_NAME = process.env.WILDCARD_CERT_NAME || 'shupremium-wildcard';
const CERT_DIR = process.env.WILDCARD_CERT_DIR || `/etc/letsencrypt/live/${CERT_NAME}`;
const CF_CREDENTIALS = process.env.CLOUDFLARE_CREDENTIALS || '/home/ubuntu/.secrets/cloudflare.ini';
const PROXY_SERVICE_PATH = process.env.PROXY_SERVICE_PATH || path.join(__dirname, '../../proxy-service');
const ECOSYSTEM_PATH = path.join(PROXY_SERVICE_PATH, 'ecosystem.config.js');
const NGINX_SITES_AVAILABLE = process.env.NGINX_SITES_AVAILABLE || '/etc/nginx/sites-available';
const NGINX_SITES_ENABLED = process.env.NGINX_SITES_ENABLED || '/etc/nginx/sites-enabled';
const BACKUP_ROOT = process.env.OPERATOR_BACKUP_ROOT || path.join(__dirname, '../runtime/backups');
const MANAGED_PREFIX = 'proxy-managed-';

function requireToken(req, res, next) {
    if (req.headers['x-operator-token'] !== TOKEN) {
        return res.status(401).json({ error: 'Unauthorized' });
    }
    next();
}

function execAsync(command, timeout = 60000) {
    return new Promise((resolve, reject) => {
        exec(command, { timeout }, (error, stdout, stderr) => {
            const output = (stdout || stderr || '').trim();
            if (error) {
                reject(new Error(output || error.message));
                return;
            }
            resolve(output);
        });
    });
}

function certExists() {
    return fs.existsSync(path.join(CERT_DIR, 'fullchain.pem')) && fs.existsSync(path.join(CERT_DIR, 'privkey.pem'));
}

function sanitizeName(value) {
    return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'proxy';
}

function safePm2Name(proxy) {
    return `proxy-${sanitizeName(proxy.name || proxy.id)}`;
}

function validateProxies(proxies) {
    const domains = new Set();
    const ports = new Set();
    for (const proxy of proxies) {
        if (!proxy.id || !proxy.name || !proxy.domain || !proxy.target_host || !proxy.port) {
            throw new Error(`Invalid proxy payload: ${JSON.stringify(proxy)}`);
        }
        if (domains.has(proxy.domain)) {
            throw new Error(`Duplicate domain: ${proxy.domain}`);
        }
        if (ports.has(proxy.port)) {
            throw new Error(`Duplicate port: ${proxy.port}`);
        }
        domains.add(proxy.domain);
        ports.add(proxy.port);
    }
}

function buildEcosystem(proxies) {
    const apps = proxies.map((proxy) => {
        const safeName = sanitizeName(proxy.name || proxy.id);
        return {
            name: safePm2Name(proxy),
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
                TARGET_PROTOCOL: proxy.target_protocol === 'http' ? 'http' : 'https',
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

    return `// PM2 Ecosystem - Auto-generated ${new Date().toISOString()}
// DO NOT EDIT MANUALLY - Managed by Proxy Operator

module.exports = {
  apps: ${JSON.stringify(apps, null, 4)}
};
`;
}

function buildNginxConfig(proxy) {
    const safeFile = `${MANAGED_PREFIX}${proxy.id}.conf`;
    if (certExists()) {
        return {
            filename: safeFile,
            content: `# Managed by proxy-operator
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

    ssl_certificate ${CERT_DIR}/fullchain.pem;
    ssl_certificate_key ${CERT_DIR}/privkey.pem;
    include /etc/nginx/snippets/ssl-params.conf;
    include /etc/nginx/snippets/security-headers.conf;

    access_log /var/log/nginx/${sanitizeName(proxy.id)}-access.log;
    error_log /var/log/nginx/${sanitizeName(proxy.id)}-error.log;

    location = /health {
        proxy_pass http://127.0.0.1:${proxy.port}/health;
        access_log off;
    }

    location /v1/ {
        proxy_pass http://127.0.0.1:${proxy.port};
        include /etc/nginx/snippets/proxy-params.conf;
    }

    location /dashboard/billing/ {
        proxy_pass http://127.0.0.1:${proxy.port};
        include /etc/nginx/snippets/proxy-params.conf;
    }

    location = / {
        proxy_pass http://127.0.0.1:${proxy.port};
        include /etc/nginx/snippets/proxy-params.conf;
    }

    location / {
        return 404;
    }
}
`
        };
    }

    return {
        filename: safeFile,
        content: `# Managed by proxy-operator (HTTP fallback)
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

    location /dashboard/billing/ {
        proxy_pass http://127.0.0.1:${proxy.port};
        include /etc/nginx/snippets/proxy-params.conf;
    }

    location = / {
        proxy_pass http://127.0.0.1:${proxy.port};
    }

    location / {
        return 404;
    }
}
`
    };
}

async function fetchPm2ProxyNames() {
    try {
        const raw = await execAsync('pm2 jlist', 15000);
        const items = JSON.parse(raw || '[]');
        return items
            .map((item) => item && item.name)
            .filter((name) => typeof name === 'string' && name.startsWith('proxy-') && name !== 'proxy-operator');
    } catch (error) {
        return [];
    }
}

async function deleteStalePm2Apps(desiredNames) {
    const currentNames = await fetchPm2ProxyNames();
    for (const name of currentNames) {
        if (!desiredNames.has(name)) {
            await execAsync(`pm2 delete ${name}`, 30000).catch(() => {});
        }
    }
}

function listManagedNginxFiles() {
    if (!fs.existsSync(NGINX_SITES_AVAILABLE)) {
        return [];
    }
    return fs.readdirSync(NGINX_SITES_AVAILABLE).filter((name) => name.startsWith(MANAGED_PREFIX));
}

function captureState() {
    const managedFiles = {};
    for (const file of listManagedNginxFiles()) {
        const fullPath = path.join(NGINX_SITES_AVAILABLE, file);
        managedFiles[file] = fs.readFileSync(fullPath, 'utf8');
    }
    return {
        ecosystem: fs.existsSync(ECOSYSTEM_PATH) ? fs.readFileSync(ECOSYSTEM_PATH, 'utf8') : null,
        managedFiles
    };
}

function persistBackup(state, jobId) {
    fs.mkdirSync(BACKUP_ROOT, { recursive: true });
    const dir = path.join(BACKUP_ROOT, jobId);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'state.json'), JSON.stringify(state, null, 2));
    return dir;
}

async function writeManagedFiles(proxies) {
    const desiredFilenames = new Set();
    for (const proxy of proxies) {
        const config = buildNginxConfig(proxy);
        desiredFilenames.add(config.filename);
        const tempPath = path.join('/tmp', config.filename);
        fs.writeFileSync(tempPath, config.content);
        await execAsync(`sudo mv ${tempPath} ${path.join(NGINX_SITES_AVAILABLE, config.filename)}`);
        await execAsync(`sudo chmod 644 ${path.join(NGINX_SITES_AVAILABLE, config.filename)}`);
        await execAsync(`sudo ln -sf ${path.join(NGINX_SITES_AVAILABLE, config.filename)} ${path.join(NGINX_SITES_ENABLED, config.filename)}`).catch(() => {});
    }

    for (const stale of listManagedNginxFiles()) {
        if (!desiredFilenames.has(stale)) {
            await execAsync(`sudo rm -f ${path.join(NGINX_SITES_ENABLED, stale)}`).catch(() => {});
            await execAsync(`sudo rm -f ${path.join(NGINX_SITES_AVAILABLE, stale)}`).catch(() => {});
        }
    }
}

async function restoreState(state) {
    if (state.ecosystem !== null) {
        fs.writeFileSync(ECOSYSTEM_PATH, state.ecosystem);
    }

    const existing = new Set(listManagedNginxFiles());
    for (const [filename, content] of Object.entries(state.managedFiles || {})) {
        fs.writeFileSync(path.join('/tmp', filename), content);
        await execAsync(`sudo mv ${path.join('/tmp', filename)} ${path.join(NGINX_SITES_AVAILABLE, filename)}`).catch(() => {});
        await execAsync(`sudo chmod 644 ${path.join(NGINX_SITES_AVAILABLE, filename)}`).catch(() => {});
        await execAsync(`sudo ln -sf ${path.join(NGINX_SITES_AVAILABLE, filename)} ${path.join(NGINX_SITES_ENABLED, filename)}`).catch(() => {});
        existing.delete(filename);
    }

    for (const stale of existing) {
        await execAsync(`sudo rm -f ${path.join(NGINX_SITES_ENABLED, stale)}`).catch(() => {});
        await execAsync(`sudo rm -f ${path.join(NGINX_SITES_AVAILABLE, stale)}`).catch(() => {});
    }

    await execAsync('sudo nginx -t', 30000);
    await execAsync('sudo nginx -s reload', 30000);
    await execAsync(`cd ${PROXY_SERVICE_PATH} && (pm2 reload ecosystem.config.js --update-env || pm2 start ecosystem.config.js)`, 60000);
}

async function probeHealth(proxies) {
    const results = [];
    for (const proxy of proxies) {
        const response = await fetch(`http://127.0.0.1:${proxy.port}/_internal/health`, { signal: AbortSignal.timeout(5000) });
        if (!response.ok) {
            throw new Error(`Health probe failed for ${proxy.id} on port ${proxy.port}`);
        }
        results.push(await response.json());
    }
    return results;
}

async function applyRuntimeState(proxies) {
    validateProxies(proxies);
    const jobId = `job-${Date.now()}`;
    const snapshot = captureState();
    persistBackup(snapshot, jobId);
    const desiredPm2Names = new Set(proxies.map((proxy) => safePm2Name(proxy)));

    try {
        fs.writeFileSync(ECOSYSTEM_PATH, buildEcosystem(proxies));
        await writeManagedFiles(proxies);
        await execAsync('sudo nginx -t', 30000);
        await execAsync('sudo nginx -s reload', 30000);
        await execAsync(`cd ${PROXY_SERVICE_PATH} && (pm2 reload ecosystem.config.js --update-env || pm2 start ecosystem.config.js)`, 60000);
        await deleteStalePm2Apps(desiredPm2Names);
        const health = await probeHealth(proxies);
        return { ok: true, jobId, wildcard_cert: certExists(), health };
    } catch (error) {
        await restoreState(snapshot).catch(() => {});
        throw error;
    }
}

async function ensureWildcardCertificate() {
    if (!fs.existsSync(CF_CREDENTIALS)) {
        throw new Error(`Cloudflare credentials not found at ${CF_CREDENTIALS}`);
    }
    const command = [
        'sudo certbot certonly --dns-cloudflare',
        `--dns-cloudflare-credentials ${CF_CREDENTIALS}`,
        `-d ${ROOT_DOMAIN}`,
        `-d *.${ROOT_DOMAIN}`,
        `--cert-name ${CERT_NAME}`,
        '--non-interactive --agree-tos --keep-until-expiring',
        `-m admin@${ROOT_DOMAIN}`
    ].join(' ');
    const output = await execAsync(command, 240000);
    return { ok: true, cert_name: CERT_NAME, cert_dir: CERT_DIR, output };
}

app.get('/health', requireToken, async (req, res) => {
    res.json({
        status: 'ok',
        root_domain: ROOT_DOMAIN,
        wildcard_cert: {
            cert_name: CERT_NAME,
            cert_dir: CERT_DIR,
            available: certExists()
        }
    });
});

app.post('/api/runtime/apply', requireToken, async (req, res) => {
    try {
        const proxies = Array.isArray(req.body.proxies) ? req.body.proxies : [];
        const result = await applyRuntimeState(proxies);
        res.json(result);
    } catch (error) {
        res.status(500).json({ ok: false, error: error.message });
    }
});

app.post('/api/runtime/wildcard/ensure', requireToken, async (req, res) => {
    try {
        const result = await ensureWildcardCertificate();
        res.json(result);
    } catch (error) {
        res.status(500).json({ ok: false, error: error.message });
    }
});

app.post('/api/runtime/restart/:name', requireToken, async (req, res) => {
    try {
        await execAsync(`pm2 restart ${req.params.name}`, 30000);
        res.json({ ok: true, name: req.params.name });
    } catch (error) {
        res.status(500).json({ ok: false, error: error.message });
    }
});

app.listen(PORT, '0.0.0.0', () => {
    console.log(`[proxy-operator] listening on :${PORT}`);
});
