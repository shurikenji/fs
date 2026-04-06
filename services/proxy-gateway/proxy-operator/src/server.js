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
const FALLBACK_CERT_NAMES = ['proxy-gateway', 'shupremium-wildcard', CERT_NAME];

let lastApplyStatus = null;

function requireToken(req, res, next) {
    if (req.headers['x-operator-token'] !== TOKEN) {
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
    const domains = new Set();
    const ports = new Set();
    for (const proxy of proxies) {
        if (!proxy.id || !proxy.name || !proxy.domain || !proxy.target_host || !proxy.port) {
            throw makeStepError('validate', new Error(`Invalid proxy payload: ${JSON.stringify(proxy)}`));
        }
        if (domains.has(proxy.domain)) {
            throw makeStepError('validate', new Error(`Duplicate domain: ${proxy.domain}`));
        }
        if (ports.has(proxy.port)) {
            throw makeStepError('validate', new Error(`Duplicate port: ${proxy.port}`));
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
    if (certState?.available) {
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

    ssl_certificate ${certState.path}/fullchain.pem;
    ssl_certificate_key ${certState.path}/privkey.pem;
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

async function deleteStalePm2Apps(desiredNames) {
    const currentNames = await fetchPm2ProxyNames();
    for (const name of currentNames) {
        if (!desiredNames.has(name)) {
            await execAsync(`pm2 delete ${shellQuote(name)}`, 30000).catch(() => {});
        }
    }
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

async function startMissingPm2Apps(desiredNames) {
    const currentApps = await fetchPm2ProxyApps();
    const currentByName = new Map(currentApps.map((item) => [item.name, item.status]));
    const restartableStatuses = new Set(['online', 'launching']);
    const missingNames = [];
    const restartNames = [];

    for (const name of desiredNames) {
        const status = currentByName.get(name);
        if (!status) {
            missingNames.push(name);
            continue;
        }
        if (!restartableStatuses.has(status)) {
            restartNames.push(name);
        }
    }

    if (missingNames.length === 0) {
        for (const name of restartNames) {
            await execAsync(`pm2 restart ${shellQuote(name)} --update-env`, 30000).catch(async () => {
                await execAsync(
                    `cd ${shellQuote(PROXY_SERVICE_PATH)} && pm2 start ecosystem.config.js --only ${shellQuote(name)} --update-env`,
                    60000
                );
            });
        }
        return restartNames;
    }

    await execAsync(
        `cd ${shellQuote(PROXY_SERVICE_PATH)} && pm2 start ecosystem.config.js --only ${shellQuote(missingNames.join(','))} --update-env`,
        60000
    );
    for (const name of restartNames) {
        await execAsync(`pm2 restart ${shellQuote(name)} --update-env`, 30000).catch(async () => {
            await execAsync(
                `cd ${shellQuote(PROXY_SERVICE_PATH)} && pm2 start ecosystem.config.js --only ${shellQuote(name)} --update-env`,
                60000
            );
        });
    }
    return [...missingNames, ...restartNames];
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
    fs.mkdirSync(BACKUP_ROOT, { recursive: true });
    const dir = path.join(BACKUP_ROOT, jobId);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'state.json'), JSON.stringify(state, null, 2));
    return dir;
}

async function writeManagedFiles(proxies, certState) {
    const desiredFilenames = new Set();
    for (const proxy of proxies) {
        const config = buildNginxConfig(proxy, certState);
        desiredFilenames.add(config.filename);
        const tempPath = path.join('/tmp', config.filename);
        fs.writeFileSync(tempPath, config.content);
        const destination = path.join(NGINX_SITES_AVAILABLE, config.filename);
        const symlink = path.join(NGINX_SITES_ENABLED, config.filename);
        await execAsync(`sudo mv ${shellQuote(tempPath)} ${shellQuote(destination)}`);
        await execAsync(`sudo chmod 644 ${shellQuote(destination)}`);
        await execAsync(`sudo ln -sf ${shellQuote(destination)} ${shellQuote(symlink)}`).catch(() => {});
    }

    for (const stale of listManagedNginxFiles()) {
        if (!desiredFilenames.has(stale)) {
            await execAsync(`sudo rm -f ${shellQuote(path.join(NGINX_SITES_ENABLED, stale))}`).catch(() => {});
            await execAsync(`sudo rm -f ${shellQuote(path.join(NGINX_SITES_AVAILABLE, stale))}`).catch(() => {});
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
        fs.writeFileSync(ECOSYSTEM_PATH, state.ecosystem);
    }

    const existing = new Set(listManagedNginxFiles());
    for (const [filename, content] of Object.entries(state.managedFiles || {})) {
        const tempPath = path.join('/tmp', filename);
        const destination = path.join(NGINX_SITES_AVAILABLE, filename);
        const symlink = path.join(NGINX_SITES_ENABLED, filename);
        fs.writeFileSync(tempPath, content);
        await execAsync(`sudo mv ${shellQuote(tempPath)} ${shellQuote(destination)}`).catch(() => {});
        await execAsync(`sudo chmod 644 ${shellQuote(destination)}`).catch(() => {});
        await execAsync(`sudo ln -sf ${shellQuote(destination)} ${shellQuote(symlink)}`).catch(() => {});
        existing.delete(filename);
    }

    for (const stale of existing) {
        await execAsync(`sudo rm -f ${shellQuote(path.join(NGINX_SITES_ENABLED, stale))}`).catch(() => {});
        await execAsync(`sudo rm -f ${shellQuote(path.join(NGINX_SITES_AVAILABLE, stale))}`).catch(() => {});
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
                response = await fetch(`http://127.0.0.1:${proxy.port}/_internal/health`, {
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
    const ensureWildcard = options.ensureWildcard !== false;
    const jobId = `job-${Date.now()}`;
    const desiredPm2Names = new Set(proxies.map((proxy) => safePm2Name(proxy)));
    const snapshot = await captureState();
    persistBackup(snapshot, jobId);

    lastApplyStatus = {
        status: 'running',
        step: 'validate',
        job_id: jobId,
        updated_at: new Date().toISOString()
    };

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
        fs.writeFileSync(ECOSYSTEM_PATH, buildEcosystem(proxies));
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
        await execAsync(
            `cd ${shellQuote(PROXY_SERVICE_PATH)} && (pm2 startOrReload ecosystem.config.js --update-env || pm2 reload ecosystem.config.js --update-env || pm2 start ecosystem.config.js)`,
            60000
        );
        const startedMissing = await startMissingPm2Apps(desiredPm2Names);
        await deleteStalePm2Apps(desiredPm2Names);
        logStep('pm2_reload', 'ok', {
            job_id: jobId,
            desired_pm2_names: Array.from(desiredPm2Names),
            started_missing: startedMissing
        });

        logStep('health_probe', 'start', { job_id: jobId });
        const health = await probeHealth(proxies);
        logStep('health_probe', 'ok', { job_id: jobId, proxy_count: health.length });

        lastApplyStatus = {
            status: 'success',
            step: 'health_probe',
            job_id: jobId,
            updated_at: new Date().toISOString()
        };

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
        lastApplyStatus = {
            status: 'failed',
            step: stepError.step,
            job_id: jobId,
            error: stepError.message,
            details: stepError.details,
            updated_at: new Date().toISOString()
        };
        throw stepError;
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

app.post('/api/runtime/apply', requireToken, async (req, res) => {
    try {
        const proxies = Array.isArray(req.body.proxies) ? req.body.proxies : [];
        const ensureWildcard = req.body.ensure_wildcard !== false;
        const result = await applyRuntimeState(proxies, { ensureWildcard });
        res.json(result);
    } catch (error) {
        res.status(500).json(serializeError(error));
    }
});

app.post('/api/runtime/wildcard/ensure', requireToken, async (req, res) => {
    try {
        const result = await ensureWildcardCertificate();
        res.json(result);
    } catch (error) {
        res.status(500).json(serializeError(error));
    }
});

app.post('/api/runtime/restart/:name', requireToken, async (req, res) => {
    try {
        await execAsync(`pm2 restart ${shellQuote(req.params.name)}`, 30000);
        res.json({ ok: true, name: req.params.name });
    } catch (error) {
        res.status(500).json(serializeError(makeStepError('pm2_restart', error)));
    }
});

if (require.main === module) {
    app.listen(PORT, '0.0.0.0', () => {
        console.log(`[proxy-operator] listening on :${PORT}`);
    });
}

module.exports = {
    app,
    applyRuntimeState,
    buildEcosystem,
    buildNginxConfig,
    captureState,
    certExists,
    deleteStalePm2Apps,
    ensureWildcardCertificate,
    fetchPm2ProxyNames,
    getCertCandidateDirs,
    probeCertDir,
    probeHealth,
    resolveWildcardCertificate,
    restoreState,
    serializeError,
    writeManagedFiles
};
