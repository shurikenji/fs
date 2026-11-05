require('dotenv').config();
const express = require('express');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const os = require('os');
const { exec } = require('child_process');

const app = express();
app.use(express.json({ limit: '2mb' }));

const PORT = parseInt(process.env.OPERATOR_PORT || '8091', 10);
const TOKEN = process.env.OPERATOR_TOKEN || '';
const TOKEN_CONFIGURED = validOperatorToken(TOKEN);
const ROOT_DOMAIN = process.env.ROOT_DOMAIN || 'shupremium.com';
const CERT_NAME = process.env.WILDCARD_CERT_NAME || 'shupremium-wildcard';
const CERT_DIR = process.env.WILDCARD_CERT_DIR || `/etc/letsencrypt/live/${CERT_NAME}`;
const CF_CREDENTIALS = process.env.CLOUDFLARE_CREDENTIALS || '/home/ubuntu/.secrets/cloudflare.ini';
const PROXY_SERVICE_PATH = process.env.PROXY_SERVICE_PATH || path.join(__dirname, '../../proxy-service');
const ECOSYSTEM_PATH = path.join(PROXY_SERVICE_PATH, 'ecosystem.config.js');
const NGINX_SITES_AVAILABLE = process.env.NGINX_SITES_AVAILABLE || '/etc/nginx/sites-available';
const NGINX_SITES_ENABLED = process.env.NGINX_SITES_ENABLED || '/etc/nginx/sites-enabled';
const BACKUP_ROOT = process.env.OPERATOR_BACKUP_ROOT || path.join(__dirname, '../runtime/backups');
const JOB_LOG_DIR = process.env.OPERATOR_JOB_LOG_DIR || path.join(__dirname, '../runtime/jobs');
const JOB_LOG_MAX = parseInt(process.env.OPERATOR_JOB_LOG_MAX || '50', 10);
const RUNTIME_LOCK_DIR = process.env.OPERATOR_RUNTIME_LOCK_DIR || '/srv/shupremium-stack/shared/_ops/runtime.lock';
const MANAGED_PREFIX = 'proxy-managed-';
const FALLBACK_CERT_NAMES = ['proxy-gateway', 'shupremium-wildcard', CERT_NAME];
const LEGACY_ROUTE_PREFIXES = ['/v1/', '/dashboard/billing/'];
const ROUTE_PREFIX_PATTERN = /^\/[A-Za-z0-9._~!$&'()*+,;=:@%/-]+$/;
const ROUTE_REGEX_META = /[()[\]|+^$]/;
const RESERVED_PROXY_PORTS = new Set([22, 80, 443, 8080, 8090, 8091, 8092, 8093]);

let lastApplyStatus = null;

function acquireRuntimeGuard(owner, lockDir = RUNTIME_LOCK_DIR) {
    fs.mkdirSync(path.dirname(lockDir), { recursive: true });
    try {
        fs.mkdirSync(lockDir, { mode: 0o700 });
    } catch (error) {
        if (error.code === 'EEXIST') throw makeStepError('busy', new Error('Runtime lock is held or requires operator review'));
        throw error;
    }
    try {
        fs.writeFileSync(path.join(lockDir, 'owner'), `${owner}\n`, { flag: 'wx', mode: 0o600 });
    } catch (error) {
        try { fs.rmdirSync(lockDir); } catch { /* leave an uncertain lock for review */ }
        throw error;
    }
    return { lockDir, owner };
}

function releaseRuntimeGuard(guard) {
    if (!guard) return;
    try {
        const ownerFile = path.join(guard.lockDir, 'owner');
        if (fs.readFileSync(ownerFile, 'utf8').trim() !== guard.owner) return;
        fs.unlinkSync(ownerFile);
        fs.rmdirSync(guard.lockDir);
    } catch (error) {
        if (error.code !== 'ENOENT') console.error('[proxy-operator] Runtime lock cleanup failed:', error.code || 'error');
    }
}

function atomicWriteExisting(filePath, content) {
    const destination = fs.realpathSync(filePath);
    const temp = `${destination}.${crypto.randomUUID()}.tmp`;
    let fd;
    try {
        fd = fs.openSync(temp, 'wx', fs.statSync(destination).mode & 0o777);
        fs.writeFileSync(fd, content);
        fs.fsyncSync(fd);
        fs.closeSync(fd);
        fd = undefined;
        fs.renameSync(temp, destination);
    } finally {
        if (fd !== undefined) fs.closeSync(fd);
        try { fs.unlinkSync(temp); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
}

function createPrivateNginxTemp(content) {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'shupremium-nginx-'));
    const file = path.join(directory, 'site.conf');
    try {
        fs.writeFileSync(file, content, { flag: 'wx', mode: 0o600 });
        return { directory, file };
    } catch (error) {
        try { fs.rmdirSync(directory); } catch { /* preserve uncertain temporary state */ }
        throw error;
    }
}

function cleanupPrivateNginxTemp(temp) {
    try { fs.unlinkSync(temp.file); } catch (error) { if (error.code !== 'ENOENT') console.error('[proxy-operator] Temporary file cleanup failed'); }
    try { fs.rmdirSync(temp.directory); } catch (error) { if (error.code !== 'ENOENT') console.error('[proxy-operator] Temporary directory cleanup failed'); }
}

function validOperatorToken(value) {
    return typeof value === 'string' && value === value.trim() && value.length >= 32 &&
        !value.toLowerCase().startsWith('change-me') && !value.toLowerCase().startsWith('replace-with');
}

function validateProxyLayout(config, env, layout) {
    const expectedService = path.resolve(layout.service);
    const expectedLock = path.resolve(layout.lock);
    const expectedState = path.resolve(layout.state);
    if (!env.PROXY_SERVICE_PATH || path.resolve(env.PROXY_SERVICE_PATH) !== expectedService ||
        !env.OPERATOR_RUNTIME_LOCK_DIR || path.resolve(env.OPERATOR_RUNTIME_LOCK_DIR) !== expectedLock ||
        !env.OPERATOR_BACKUP_ROOT || path.resolve(env.OPERATOR_BACKUP_ROOT) !== path.join(expectedState, 'backups') ||
        !env.OPERATOR_JOB_LOG_DIR || path.resolve(env.OPERATOR_JOB_LOG_DIR) !== path.join(expectedState, 'jobs')) {
        throw new Error('Proxy operator paths must use the active release and shared storage');
    }
    if (layout.role === 'combined' && (env.OPERATOR_BIND_HOST !== '127.0.0.1' || env.PROXY_BIND_HOST !== '127.0.0.1')) {
        throw new Error('Combined proxy operator and services must bind loopback');
    }
    if (!Array.isArray(config?.apps) || config.apps.length === 0) throw new Error('Proxy ecosystem must contain applications');
    const names = new Set();
    const ports = new Set();
    for (const app of config.apps) {
        const rawPort = String(app?.env?.PORT ?? '');
        const port = Number(rawPort);
        if (!app || typeof app.name !== 'string' || !/^proxy-[a-z0-9-]+$/.test(app.name) || names.has(app.name) ||
            typeof app.cwd !== 'string' || !path.isAbsolute(app.cwd) || path.resolve(app.cwd) !== expectedService ||
            app.script !== './src/index.js' || !/^[0-9]{1,5}$/.test(rawPort) || port < 1 || port > 65535 || RESERVED_PROXY_PORTS.has(port) || ports.has(port) ||
            (layout.role === 'combined' && app.env.PROXY_BIND_HOST !== '127.0.0.1')) {
            throw new Error('Proxy ecosystem has an invalid name, port, working directory, or bind address');
        }
        names.add(app.name);
        ports.add(port);
    }
}

function persistJobStatus(status) {
    lastApplyStatus = status;
    try {
        fs.mkdirSync(JOB_LOG_DIR, { recursive: true, mode: 0o700 });
        const filePath = path.join(JOB_LOG_DIR, `${status.job_id}.json`);
        fs.writeFileSync(filePath, JSON.stringify(status, null, 2), { mode: 0o600 });
        // Cleanup old job logs
        const files = fs.readdirSync(JOB_LOG_DIR).filter((f) => f.endsWith('.json')).sort().reverse();
        for (const old of files.slice(JOB_LOG_MAX)) {
            try { fs.unlinkSync(path.join(JOB_LOG_DIR, old)); } catch { }
        }
    } catch (err) {
        console.error('[proxy-operator] Failed to persist job status:', err.message);
    }
}

function loadLastJobStatus() {
    try {
        if (!fs.existsSync(JOB_LOG_DIR)) return;
        const files = fs.readdirSync(JOB_LOG_DIR).filter((f) => f.endsWith('.json')).sort().reverse();
        if (files.length === 0) return;
        lastApplyStatus = JSON.parse(fs.readFileSync(path.join(JOB_LOG_DIR, files[0]), 'utf8'));
    } catch (err) {
        console.error('[proxy-operator] Failed to load job history:', err.message);
    }
}

function requireToken(req, res, next) {
    if (!TOKEN_CONFIGURED || req.headers['x-operator-token'] !== TOKEN) {
        return res.status(401).json({ error: 'Unauthorized' });
    }
    next();
}

function shellQuote(value) {
    return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

function execAsync(command, timeout = 60000) {
    return new Promise((resolve, reject) => {
        exec(command, { timeout }, (error, stdout, stderr) => {
            const output = `${stdout || ''}${stderr || ''}`.trim();
            if (error) {
                reject(new Error(output || error.message));
                return;
            }
            resolve(output);
        });
    });
}

function logStep(step, status, extra = {}) {
    const payload = {
        component: 'proxy-operator',
        step,
        status,
        timestamp: new Date().toISOString(),
        ...extra
    };
    console.log(JSON.stringify(payload));
}

function makeStepError(step, error, details = null) {
    const wrapped = error instanceof Error ? error : new Error(String(error));
    wrapped.step = step;
    if (details !== null && details !== undefined) {
        wrapped.details = details;
    }
    return wrapped;
}

function serializeError(error) {
    return {
        ok: false,
        error: error?.message || String(error),
        step: error?.step || 'unknown',
        details: error?.details || null
    };
}

function sanitizeName(value) {
    return String(value || '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '') || 'proxy';
}

function safePm2Name(proxy) {
    return `proxy-${sanitizeName(proxy.name || proxy.id)}`;
}

function validateProxies(proxies) {
    if (!Array.isArray(proxies) || proxies.length === 0) {
        throw makeStepError('validate', new Error('Proxy list must contain at least one proxy'));
    }
    const domains = new Set();
    const ports = new Set();
    const ids = new Set();
    const names = new Set();
    for (const proxy of proxies) {
        if (!proxy || typeof proxy.id !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(proxy.id) ||
            typeof proxy.name !== 'string' || !proxy.name.trim() || proxy.name.length > 200 ||
            typeof proxy.domain !== 'string' || proxy.domain.length > 253 ||
            !proxy.domain.split('.').every((label) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label)) ||
            typeof proxy.target_host !== 'string' || !proxy.target_host || /[\s\\/?#@]/.test(proxy.target_host) ||
            !/^[0-9]{1,5}$/.test(String(proxy.port)) || Number(proxy.port) < 1 || Number(proxy.port) > 65535 || RESERVED_PROXY_PORTS.has(Number(proxy.port)) ||
            (proxy.target_protocol != null && !['http', 'https'].includes(proxy.target_protocol)) ||
            (proxy.tls_skip_verify != null && ![true, false, 0, 1].includes(proxy.tls_skip_verify))) {
            throw makeStepError('validate', new Error('Invalid proxy identity, domain, target, port, or TLS policy'));
        }
        try {
            const target = new URL(`http://${proxy.target_host}`);
            if (!target.hostname || target.username || target.password || target.pathname !== '/' || target.search || target.hash) throw new Error('invalid');
        } catch {
            throw makeStepError('validate', new Error('Invalid proxy target'));
        }
        const domain = proxy.domain.toLowerCase();
        const port = Number(proxy.port);
        const pm2Name = safePm2Name(proxy);
        if (domains.has(domain) || ports.has(port) || ids.has(proxy.id) || names.has(pm2Name)) {
            throw makeStepError('validate', new Error('Duplicate proxy identity, domain, port, or process name'));
        }
        routePrefixes(proxy);
        bodyLimit(proxy);
        domains.add(domain);
        ports.add(port);
        ids.add(proxy.id);
        names.add(pm2Name);
    }
}

function bodyLimit(proxy) {
    const value = String(proxy?.max_body_size || '600m').trim();
    if (!/^[1-9][0-9]{0,8}[kKmMgG]$/.test(value)) {
        throw makeStepError('validate', new Error(`Invalid max body size: ${value}`), { proxy_id: proxy?.id });
    }
    return value;
}

function routePrefixes(proxy) {
    const raw = proxy?.route_policy?.effective_prefixes || proxy?.allowed_path_prefixes;
    const prefixes = Array.isArray(raw) ? raw : LEGACY_ROUTE_PREFIXES;
    const customPrefixes = proxy?.route_policy?.custom_prefixes;
    if (Array.isArray(customPrefixes) && customPrefixes.length > 32) {
        throw makeStepError('validate', new Error('A proxy cannot have more than 32 custom route prefixes'), { proxy_id: proxy?.id });
    }
    if (prefixes.length > 64) {
        throw makeStepError('validate', new Error('A proxy cannot have more than 64 effective route prefixes'), { proxy_id: proxy?.id });
    }
    const seen = new Set();
    for (const value of prefixes) {
        const prefix = String(value || '').trim();
        if (!prefix || prefix.length > 128 || prefix === '/' || prefix.includes('..') || prefix.includes('?') || prefix.includes('#') || prefix.includes(';') || ROUTE_REGEX_META.test(prefix) || !ROUTE_PREFIX_PATTERN.test(prefix)) {
            throw makeStepError('validate', new Error(`Invalid route prefix: ${prefix}`), { proxy_id: proxy?.id });
        }
        if (prefix.startsWith('/_internal') || prefix.startsWith('/.well-known/') || prefix === '/health' || prefix.startsWith('/health/')) {
            throw makeStepError('validate', new Error(`Reserved route prefix: ${prefix}`), { proxy_id: proxy?.id });
        }
        seen.add(prefix);
    }
    return Array.from(seen);
}

function renderProxyLocation(proxy, prefix, certState) {
    const upstream = `http://127.0.0.1:${proxy.port}`;
    const safePrefix = prefix.endsWith('/') ? prefix : `${prefix}/`;
    const block = (location) => `    location ${location} {
        proxy_pass ${upstream};
        include /etc/nginx/snippets/proxy-params.conf;
    }`;
    if (prefix.endsWith('/')) return block(`^~ ${prefix}`);
    return [
        block(`= ${prefix}`),
        block(`^~ ${safePrefix}`),
        block(`~ ^${prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}:`)
    ].join('\n\n');
}

function buildEcosystem(proxies) {
    const apps = proxies.map((proxy) => {
        const safeName = sanitizeName(proxy.name || proxy.id);
        return {
            name: safePm2Name(proxy),
            cwd: path.resolve(PROXY_SERVICE_PATH),
            script: './src/index.js',
            instances: 2,
            exec_mode: 'cluster',
            autorestart: true,
            watch: false,
            max_memory_restart: '512M',
            env: {
                NODE_ENV: 'production',
                PORT: proxy.port,
                PROXY_BIND_HOST: process.env.PROXY_BIND_HOST || '0.0.0.0',
                TARGET_HOST: proxy.target_host,
                TARGET_PROTOCOL: proxy.target_protocol === 'http' ? 'http' : 'https',
                TLS_SKIP_VERIFY: proxy.tls_skip_verify ? 'true' : 'false',
                SERVICE_NAME: proxy.name,
                PROXY_DOMAIN: proxy.domain,
                ALLOWED_PATH_PREFIXES_JSON: JSON.stringify(routePrefixes(proxy)),
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

function getCertCandidateDirs() {
    const seen = new Set();
    const candidates = [];
    const pushCandidate = (dirPath, certName, source) => {
        if (!dirPath || seen.has(dirPath)) {
            return;
        }
        seen.add(dirPath);
        candidates.push({ path: dirPath, cert_name: certName, source });
    };

    pushCandidate(CERT_DIR, CERT_NAME, 'env');
    for (const certName of FALLBACK_CERT_NAMES) {
        pushCandidate(path.join('/etc/letsencrypt/live', certName), certName, certName === CERT_NAME ? 'env_name' : 'fallback');
    }

    return candidates;
}

async function probeCertDir(candidate) {
    const certPath = path.join(candidate.path, 'fullchain.pem');
    const keyPath = path.join(candidate.path, 'privkey.pem');
    try {
        await execAsync(
            `sudo test -f ${shellQuote(certPath)} && sudo test -f ${shellQuote(keyPath)}`,
            15000
        );
        return {
            available: true,
            cert_name: candidate.cert_name,
            path: candidate.path,
            probe_method: 'sudo_test'
        };
    } catch (error) {
        return {
            available: false,
            cert_name: candidate.cert_name,
            path: candidate.path,
            probe_method: 'sudo_test',
            error: error.message
        };
    }
}

async function certExists() {
    const state = await resolveWildcardCertificate();
    return state.available;
}

async function resolveWildcardCertificate() {
    const failures = [];
    for (const candidate of getCertCandidateDirs()) {
        const probed = await probeCertDir(candidate);
        if (probed.available) {
            return probed;
        }
        failures.push({
            cert_name: probed.cert_name,
            path: probed.path,
            error: probed.error
        });
    }

    return {
        available: false,
        cert_name: CERT_NAME,
        path: CERT_DIR,
        probe_method: 'sudo_test',
        attempts: failures
    };
}

function buildNginxConfig(proxy, certState) {
    const safeFile = `${MANAGED_PREFIX}${proxy.id}.conf`;
    const locations = routePrefixes(proxy).map((prefix) => renderProxyLocation(proxy, prefix)).join('\n\n');
    const bodyLimitValue = bodyLimit(proxy);
    if (certState?.available) {
        return {
            filename: safeFile,
            content: `# Managed by proxy-operator
server {
    listen 80;
    server_name ${proxy.domain};
    client_max_body_size ${bodyLimitValue};

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

    ssl_certificate ${certState.path}/fullchain.pem;
    ssl_certificate_key ${certState.path}/privkey.pem;
    include /etc/nginx/snippets/ssl-params.conf;
    include /etc/nginx/snippets/security-headers.conf;

    access_log off;
    error_log /var/log/nginx/${sanitizeName(proxy.id)}-error.log;
    client_max_body_size ${bodyLimitValue};

    location = /health {
        proxy_pass http://127.0.0.1:${proxy.port}/health;
        access_log off;
    }

${locations}

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
    client_max_body_size ${bodyLimitValue};

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location = /health {
        proxy_pass http://127.0.0.1:${proxy.port}/health;
    }

${locations}

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

async function fetchPm2ProxyApps() {
    try {
        const raw = await execAsync('pm2 jlist', 15000);
        const items = JSON.parse(raw || '[]');
        return items
            .map((item) => ({
                name: item && item.name,
                status: item?.pm2_env?.status || 'unknown'
            }))
            .filter((item) => typeof item.name === 'string' && item.name.startsWith('proxy-') && item.name !== 'proxy-operator');
    } catch (error) {
        return [];
    }
}

async function fetchPm2ProxyNames() {
    const apps = await fetchPm2ProxyApps();
    return apps.map((item) => item.name);
}

function classifyDesiredPm2Apps(desiredNames, currentApps) {
    const currentByName = new Map(currentApps.map((item) => [item.name, item.status]));
    const healthyStatuses = new Set(['online', 'launching']);
    const existingNames = [];
    const restartNames = [];
    const missingNames = [];

    for (const name of desiredNames) {
        const status = currentByName.get(name);
        if (!status) {
            missingNames.push(name);
            continue;
        }
        if (healthyStatuses.has(status)) {
            existingNames.push(name);
            continue;
        }
        restartNames.push(name);
    }

    return {
        existingNames,
        restartNames,
        missingNames
    };
}

async function deleteStalePm2Apps(desiredNames) {
    const currentNames = await fetchPm2ProxyNames();
    for (const name of currentNames) {
        if (!desiredNames.has(name)) {
            await execAsync(`pm2 delete ${shellQuote(name)}`, 30000).catch(() => { });
        }
    }
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

async function syncDesiredPm2Apps(desiredNames) {
    const currentApps = await fetchPm2ProxyApps();
    const { existingNames, restartNames, missingNames } = classifyDesiredPm2Apps(desiredNames, currentApps);

    if (existingNames.length > 0) {
        await execAsync(
            `cd ${shellQuote(PROXY_SERVICE_PATH)} && (pm2 reload ecosystem.config.js --only ${shellQuote(existingNames.join(','))} --update-env || pm2 restart ecosystem.config.js --only ${shellQuote(existingNames.join(','))} --update-env)`,
            60000
        );
    }

    for (const name of [...restartNames, ...missingNames]) {
        await execAsync(`pm2 delete ${shellQuote(name)}`, 30000).catch(() => { });
        await execAsync(
            `cd ${shellQuote(PROXY_SERVICE_PATH)} && pm2 start ecosystem.config.js --only ${shellQuote(name)} --update-env`,
            60000
        ).catch(async () => {
            await execAsync(
                `cd ${shellQuote(PROXY_SERVICE_PATH)} && pm2 start ecosystem.config.js --only ${shellQuote(name)} --update-env`,
                60000
            );
        });
    }

    return {
        reloaded: existingNames,
        started: [...restartNames, ...missingNames]
    };
}

function listManagedNginxFiles() {
    if (!fs.existsSync(NGINX_SITES_AVAILABLE)) {
        return [];
    }
    return fs.readdirSync(NGINX_SITES_AVAILABLE).filter((name) => name.startsWith(MANAGED_PREFIX));
}

async function captureState() {
    const managedFiles = {};
    for (const file of listManagedNginxFiles()) {
        const fullPath = path.join(NGINX_SITES_AVAILABLE, file);
        managedFiles[file] = fs.readFileSync(fullPath, 'utf8');
    }
    return {
        ecosystem: fs.existsSync(ECOSYSTEM_PATH) ? fs.readFileSync(ECOSYSTEM_PATH, 'utf8') : null,
        managedFiles,
        pm2ProxyNames: await fetchPm2ProxyNames()
    };
}

function persistBackup(state, jobId) {
    fs.mkdirSync(BACKUP_ROOT, { recursive: true, mode: 0o700 });
    const dir = path.join(BACKUP_ROOT, jobId);
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    fs.writeFileSync(path.join(dir, 'state.json'), JSON.stringify(state, null, 2), { mode: 0o600 });
    return dir;
}

async function writeManagedFiles(proxies, certState) {
    const desiredFilenames = new Set();
    for (const proxy of proxies) {
        const config = buildNginxConfig(proxy, certState);
        desiredFilenames.add(config.filename);
        const temp = createPrivateNginxTemp(config.content);
        const destination = path.join(NGINX_SITES_AVAILABLE, config.filename);
        const symlink = path.join(NGINX_SITES_ENABLED, config.filename);
        try {
            await execAsync(`sudo mv ${shellQuote(temp.file)} ${shellQuote(destination)}`);
            await execAsync(`sudo chmod 644 ${shellQuote(destination)}`);
            await execAsync(`sudo ln -sf ${shellQuote(destination)} ${shellQuote(symlink)}`);
        } finally {
            cleanupPrivateNginxTemp(temp);
        }
    }

    for (const stale of listManagedNginxFiles()) {
        if (!desiredFilenames.has(stale)) {
            await execAsync(`sudo rm -f ${shellQuote(path.join(NGINX_SITES_ENABLED, stale))}`);
            await execAsync(`sudo rm -f ${shellQuote(path.join(NGINX_SITES_AVAILABLE, stale))}`);
        }
    }
}

async function reloadRuntime() {
    await execAsync('sudo nginx -t', 30000);
    await execAsync('sudo nginx -s reload', 30000);
    await execAsync(
        `cd ${shellQuote(PROXY_SERVICE_PATH)} && (pm2 reload ecosystem.config.js --update-env || pm2 start ecosystem.config.js)`,
        60000
    );
}

async function restoreState(state) {
    if (state.ecosystem !== null) {
        atomicWriteExisting(ECOSYSTEM_PATH, state.ecosystem);
    }

    const existing = new Set(listManagedNginxFiles());
    for (const [filename, content] of Object.entries(state.managedFiles || {})) {
        const temp = createPrivateNginxTemp(content);
        const destination = path.join(NGINX_SITES_AVAILABLE, filename);
        const symlink = path.join(NGINX_SITES_ENABLED, filename);
        try {
            await execAsync(`sudo mv ${shellQuote(temp.file)} ${shellQuote(destination)}`);
            await execAsync(`sudo chmod 644 ${shellQuote(destination)}`);
            await execAsync(`sudo ln -sf ${shellQuote(destination)} ${shellQuote(symlink)}`);
        } finally {
            cleanupPrivateNginxTemp(temp);
        }
        existing.delete(filename);
    }

    for (const stale of existing) {
        await execAsync(`sudo rm -f ${shellQuote(path.join(NGINX_SITES_ENABLED, stale))}`);
        await execAsync(`sudo rm -f ${shellQuote(path.join(NGINX_SITES_AVAILABLE, stale))}`);
    }

    await reloadRuntime();
    await deleteStalePm2Apps(new Set(state.pm2ProxyNames || []));
}

async function preflightRuntime(proxies) {
    validateProxies(proxies);

    const checks = [
        ['proxy_service_path', `test -d ${shellQuote(PROXY_SERVICE_PATH)}`],
        ['ecosystem_parent', `test -d ${shellQuote(path.dirname(ECOSYSTEM_PATH))} && test -w ${shellQuote(path.dirname(ECOSYSTEM_PATH))}`],
        ['nginx_sites_available', `sudo test -d ${shellQuote(NGINX_SITES_AVAILABLE)} && sudo test -w ${shellQuote(NGINX_SITES_AVAILABLE)}`],
        ['nginx_sites_enabled', `sudo test -d ${shellQuote(NGINX_SITES_ENABLED)} && sudo test -w ${shellQuote(NGINX_SITES_ENABLED)}`]
    ];

    for (const [step, command] of checks) {
        try {
            await execAsync(command, 15000);
        } catch (error) {
            throw makeStepError('validate', error, { check: step });
        }
    }

    return {
        wildcard_cert: await resolveWildcardCertificate()
    };
}

async function probeHealth(proxies, options = {}) {
    const attempts = options.attempts || 15;
    const retryDelayMs = options.retryDelayMs || 1000;
    const requestTimeoutMs = options.requestTimeoutMs || 2000;
    const results = [];
    for (const proxy of proxies) {
        let lastError = null;
        for (let attempt = 1; attempt <= attempts; attempt += 1) {
            let response;
            try {
                response = await fetch(`http://127.0.0.1:${proxy.port}/health`, {
                    signal: AbortSignal.timeout(requestTimeoutMs)
                });
            } catch (error) {
                lastError = makeStepError('health_probe', error, {
                    proxy_id: proxy.id,
                    domain: proxy.domain,
                    port: proxy.port,
                    attempt
                });
                if (attempt < attempts) {
                    await sleep(retryDelayMs);
                    continue;
                }
                throw lastError;
            }

            if (!response.ok) {
                lastError = makeStepError(
                    'health_probe',
                    new Error(`Health probe failed for ${proxy.id} on port ${proxy.port}`),
                    {
                        proxy_id: proxy.id,
                        domain: proxy.domain,
                        port: proxy.port,
                        status_code: response.status,
                        attempt
                    }
                );
                if (attempt < attempts) {
                    await sleep(retryDelayMs);
                    continue;
                }
                throw lastError;
            }

            let body = null;
            try {
                body = await response.json();
            } catch (error) {
                body = { ok: true };
            }

            results.push({
                id: proxy.id,
                domain: proxy.domain,
                port: proxy.port,
                attempts: attempt,
                health: body
            });
            lastError = null;
            break;
        }

        if (lastError) {
            throw lastError;
        }
    }
    return results;
}

async function applyRuntimeState(proxies, options = {}) {
    validateProxies(proxies);
    const ensureWildcard = options.ensureWildcard !== false;
    const jobId = `job-${Date.now()}-${crypto.randomUUID()}`;
    const guard = acquireRuntimeGuard(`${jobId} pid=${process.pid}`);
    try {
        const desiredPm2Names = new Set(proxies.map((proxy) => safePm2Name(proxy)));
        const snapshot = await captureState();
        persistBackup(snapshot, jobId);

        persistJobStatus({
            status: 'running',
            step: 'validate',
            job_id: jobId,
            updated_at: new Date().toISOString()
        });

        try {
            logStep('validate', 'start', { job_id: jobId, proxy_count: proxies.length });
            const preflight = await preflightRuntime(proxies);
            let certState = preflight.wildcard_cert;
            logStep('validate', 'ok', { job_id: jobId, wildcard_cert: certState });

            if (!certState.available && ensureWildcard) {
                logStep('ensure_cert', 'start', { job_id: jobId, cert_name: CERT_NAME });
                await ensureWildcardCertificate();
                certState = await resolveWildcardCertificate();
                if (!certState.available) {
                    throw makeStepError('cert_probe', new Error('Wildcard certificate is still unavailable after ensure'), certState);
                }
                logStep('ensure_cert', 'ok', { job_id: jobId, wildcard_cert: certState });
            }

            if (!certState.available) {
                throw makeStepError('cert_probe', new Error('Wildcard certificate is unavailable'), certState);
            }

            logStep('write_ecosystem', 'start', { job_id: jobId, ecosystem_path: ECOSYSTEM_PATH });
            atomicWriteExisting(ECOSYSTEM_PATH, buildEcosystem(proxies));
            logStep('write_ecosystem', 'ok', { job_id: jobId });

            logStep('write_nginx', 'start', { job_id: jobId, proxy_count: proxies.length });
            await writeManagedFiles(proxies, certState);
            logStep('write_nginx', 'ok', { job_id: jobId });

            logStep('nginx_test', 'start', { job_id: jobId });
            await execAsync('sudo nginx -t', 30000);
            logStep('nginx_test', 'ok', { job_id: jobId });

            logStep('nginx_reload', 'start', { job_id: jobId });
            await execAsync('sudo nginx -s reload', 30000);
            logStep('nginx_reload', 'ok', { job_id: jobId });

            logStep('pm2_reload', 'start', { job_id: jobId, proxy_service_path: PROXY_SERVICE_PATH });
            const pm2Sync = await syncDesiredPm2Apps(desiredPm2Names);
            await deleteStalePm2Apps(desiredPm2Names);
            logStep('pm2_reload', 'ok', {
                job_id: jobId,
                desired_pm2_names: Array.from(desiredPm2Names),
                reloaded_existing: pm2Sync.reloaded,
                started_missing: pm2Sync.started
            });

            logStep('health_probe', 'start', { job_id: jobId });
            const health = await probeHealth(proxies);
            logStep('health_probe', 'ok', { job_id: jobId, proxy_count: health.length });

            persistJobStatus({
                status: 'success',
                step: 'health_probe',
                job_id: jobId,
                updated_at: new Date().toISOString()
            });

            return {
                ok: true,
                jobId,
                wildcard_cert: certState,
                health
            };
        } catch (error) {
            const stepError = error?.step ? error : makeStepError('apply_runtime', error);
            logStep(stepError.step, 'failed', { job_id: jobId, error: stepError.message, details: stepError.details || null });

            let rollbackError = null;
            try {
                await restoreState(snapshot);
                logStep('rollback', 'ok', { job_id: jobId });
            } catch (innerError) {
                rollbackError = innerError;
                logStep('rollback', 'failed', { job_id: jobId, error: innerError.message });
            }

            const details = { ...(stepError.details || {}) };
            if (rollbackError) {
                details.rollback_error = rollbackError.message;
            }

            stepError.details = Object.keys(details).length > 0 ? details : null;
            persistJobStatus({
                status: 'failed',
                step: stepError.step,
                job_id: jobId,
                error: stepError.message,
                details: stepError.details,
                updated_at: new Date().toISOString()
            });
            throw stepError;
        }
    } finally {
        releaseRuntimeGuard(guard);
    }
}

async function ensureWildcardCertificate() {
    if (!fs.existsSync(CF_CREDENTIALS)) {
        throw makeStepError('ensure_cert', new Error(`Cloudflare credentials not found at ${CF_CREDENTIALS}`));
    }

    const command = [
        'sudo certbot certonly --dns-cloudflare',
        `--dns-cloudflare-credentials ${shellQuote(CF_CREDENTIALS)}`,
        `-d ${shellQuote(ROOT_DOMAIN)}`,
        `-d ${shellQuote(`*.${ROOT_DOMAIN}`)}`,
        `--cert-name ${shellQuote(CERT_NAME)}`,
        '--non-interactive --agree-tos --keep-until-expiring',
        `-m ${shellQuote(`admin@${ROOT_DOMAIN}`)}`
    ].join(' ');

    try {
        const output = await execAsync(command, 240000);
        const certState = await resolveWildcardCertificate();
        return {
            ok: true,
            cert_name: certState.cert_name,
            cert_dir: certState.path,
            wildcard_cert: certState,
            output
        };
    } catch (error) {
        throw makeStepError('ensure_cert', error);
    }
}

app.get('/health', requireToken, async (req, res) => {
    const wildcardCert = await resolveWildcardCertificate();
    res.json({
        status: 'ok',
        root_domain: ROOT_DOMAIN,
        proxy_service_path: PROXY_SERVICE_PATH,
        wildcard_cert: {
            cert_name: wildcardCert.cert_name,
            path: wildcardCert.path,
            available: wildcardCert.available,
            probe_method: wildcardCert.probe_method,
            attempts: wildcardCert.attempts || []
        },
        last_apply_status: lastApplyStatus
    });
});

app.get('/api/runtime/jobs', requireToken, (req, res) => {
    try {
        if (!fs.existsSync(JOB_LOG_DIR)) return res.json([]);
        const limit = Math.min(parseInt(req.query.limit || '20', 10), JOB_LOG_MAX);
        const files = fs.readdirSync(JOB_LOG_DIR).filter((f) => f.endsWith('.json')).sort().reverse().slice(0, limit);
        const jobs = files.map((f) => {
            try { return JSON.parse(fs.readFileSync(path.join(JOB_LOG_DIR, f), 'utf8')); }
            catch { return null; }
        }).filter(Boolean);
        res.json(jobs);
    } catch (error) {
        res.status(500).json(serializeError(makeStepError('list_jobs', error)));
    }
});

app.post('/api/runtime/apply', requireToken, async (req, res) => {
    try {
        const proxies = Array.isArray(req.body.proxies) ? req.body.proxies : [];
        const ensureWildcard = req.body.ensure_wildcard !== false;
        const result = await applyRuntimeState(proxies, { ensureWildcard });
        res.json(result);
    } catch (error) {
        res.status(error?.step === 'busy' ? 409 : 500).json(serializeError(error));
    }
});

app.post('/api/runtime/wildcard/ensure', requireToken, async (req, res) => {
    let guard;
    try {
        guard = acquireRuntimeGuard(`cert-${Date.now()}-${crypto.randomUUID()} pid=${process.pid}`);
        const result = await ensureWildcardCertificate();
        res.json(result);
    } catch (error) {
        res.status(error?.step === 'busy' ? 409 : 500).json(serializeError(error));
    } finally {
        releaseRuntimeGuard(guard);
    }
});

app.post('/api/runtime/restart/:name', requireToken, async (req, res) => {
    let guard;
    try {
        if (!/^proxy-[a-z0-9-]+$/.test(req.params.name)) {
            return res.status(400).json({ error: 'Invalid proxy process name' });
        }
        guard = acquireRuntimeGuard(`restart-${Date.now()}-${crypto.randomUUID()} pid=${process.pid}`);
        await execAsync(`pm2 restart ${shellQuote(req.params.name)}`, 30000);
        res.json({ ok: true, name: req.params.name });
    } catch (error) {
        res.status(error?.step === 'busy' ? 409 : 500).json(serializeError(error?.step ? error : makeStepError('pm2_restart', error)));
    } finally {
        releaseRuntimeGuard(guard);
    }
});

if (require.main === module) {
    if (!TOKEN_CONFIGURED) {
        console.error('[proxy-operator] OPERATOR_TOKEN must be configured with a non-default value');
        process.exit(1);
    }
    loadLastJobStatus();
    app.listen(PORT, process.env.OPERATOR_BIND_HOST || '0.0.0.0', () => {
        console.log(`[proxy-operator] listening on :${PORT}`);
    });
}

module.exports = {
    acquireRuntimeGuard,
    atomicWriteExisting,
    cleanupPrivateNginxTemp,
    createPrivateNginxTemp,
    app,
    applyRuntimeState,
    buildEcosystem,
    buildNginxConfig,
    captureState,
    certExists,
    classifyDesiredPm2Apps,
    deleteStalePm2Apps,
    ensureWildcardCertificate,
    fetchPm2ProxyNames,
    getCertCandidateDirs,
    probeCertDir,
    probeHealth,
    resolveWildcardCertificate,
    restoreState,
    releaseRuntimeGuard,
    serializeError,
    validateProxyLayout,
    validateProxies,
    validOperatorToken,
    writeManagedFiles
};
