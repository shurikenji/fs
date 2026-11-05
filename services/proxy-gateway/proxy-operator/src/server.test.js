const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const {
    acquireRuntimeGuard,
    atomicWriteExisting,
    buildNginxConfig,
    buildEcosystem,
    classifyDesiredPm2Apps,
    cleanupPrivateNginxTemp,
    createPrivateNginxTemp,
    getCertCandidateDirs,
    probeHealth,
    releaseRuntimeGuard,
    serializeError,
    validateProxyLayout,
    validateProxies,
    validOperatorToken
} = require('./server');

test('atomic ecosystem writes retain the previous file when replacement fails', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'proxy-atomic-test-'));
    const file = path.join(root, 'ecosystem.config.js');
    fs.writeFileSync(file, 'old');
    const rename = fs.renameSync;
    try {
        atomicWriteExisting(file, 'new');
        assert.equal(fs.readFileSync(file, 'utf8'), 'new');
        fs.renameSync = () => { throw new Error('injected rename failure'); };
        assert.throws(() => atomicWriteExisting(file, 'incomplete'), /injected rename failure/);
        assert.equal(fs.readFileSync(file, 'utf8'), 'new');
        assert.deepEqual(fs.readdirSync(root), ['ecosystem.config.js']);
    } finally {
        fs.renameSync = rename;
        fs.unlinkSync(file);
        fs.rmdirSync(root);
    }
});

test('nginx temporary files use private unique directories and are removed', () => {
    const first = createPrivateNginxTemp('first');
    const second = createPrivateNginxTemp('second');
    try {
        assert.notEqual(first.directory, second.directory);
        assert.equal(fs.readFileSync(first.file, 'utf8'), 'first');
        if (process.platform !== 'win32') assert.equal(fs.statSync(first.directory).mode & 0o077, 0);
    } finally {
        cleanupPrivateNginxTemp(first);
        cleanupPrivateNginxTemp(second);
    }
    assert.equal(fs.existsSync(first.directory), false);
    assert.equal(fs.existsSync(second.directory), false);
});

test('rollback stops and reports the first nginx file failure', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'proxy-rollback-test-'));
    const available = path.join(root, 'available');
    const enabled = path.join(root, 'enabled');
    fs.mkdirSync(available);
    fs.mkdirSync(enabled);
    try {
        const code = `let calls=0;
            require('child_process').exec=(_cmd,_opts,cb)=>{calls++;cb(new Error('injected'),'', '')};
            const m=require(process.argv[1]);
            m.restoreState({ecosystem:null,managedFiles:{'proxy-managed-test.conf':'server {}'},pm2ProxyNames:[]})
              .then(()=>process.exit(1),()=>process.exit(calls===1?0:2));`;
        const result = spawnSync(process.execPath, ['-e', code, path.join(__dirname, 'server.js')], {
            env: { ...process.env, NGINX_SITES_AVAILABLE: available, NGINX_SITES_ENABLED: enabled }, encoding: 'utf8', timeout: 5000
        });
        assert.equal(result.status, 0);
    } finally {
        fs.rmdirSync(available);
        fs.rmdirSync(enabled);
        fs.rmdirSync(root);
    }
});

test('runtime guard excludes other processes and preserves a replacement owner', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'proxy-guard-test-'));
    const lock = path.join(root, 'runtime.lock');
    try {
        const first = acquireRuntimeGuard('first', lock);
        assert.throws(() => acquireRuntimeGuard('second', lock), /lock is held/);
        const code = 'const m=require(process.argv[1]);try{m.acquireRuntimeGuard("child",process.argv[2]);process.exit(0)}catch(e){process.exit(e.step==="busy"?3:4)}';
        const child = spawnSync(process.execPath, ['-e', code, path.join(__dirname, 'server.js'), lock], { encoding: 'utf8', timeout: 5000 });
        assert.equal(child.status, 3);
        const applyCode = 'const m=require(process.argv[1]);m.applyRuntimeState(JSON.parse(process.argv[2])).then(()=>process.exit(0),e=>process.exit(e.step==="busy"?3:4))';
        const desired = [{ id: 'sv1', name: 'One', domain: 'one.example.test', target_host: 'example.test', port: 4001 }];
        const apply = spawnSync(process.execPath, ['-e', applyCode, path.join(__dirname, 'server.js'), JSON.stringify(desired)], {
            env: { ...process.env, OPERATOR_RUNTIME_LOCK_DIR: lock }, encoding: 'utf8', timeout: 5000
        });
        assert.equal(apply.status, 3);
        fs.unlinkSync(path.join(lock, 'owner'));
        fs.rmdirSync(lock);
        const second = acquireRuntimeGuard('second', lock);
        releaseRuntimeGuard(first);
        assert.equal(fs.readFileSync(path.join(lock, 'owner'), 'utf8').trim(), 'second');
        releaseRuntimeGuard(second);
        assert.equal(fs.existsSync(lock), false);
    } finally {
        if (fs.existsSync(path.join(lock, 'owner'))) fs.unlinkSync(path.join(lock, 'owner'));
        if (fs.existsSync(lock)) fs.rmdirSync(lock);
        fs.rmdirSync(root);
    }
});

test('operator rejects missing and default tokens at startup', () => {
    for (const token of ['', 'change-me', ' CHANGE-ME ', 'short', 'replace-with-a-placeholder-value-long']) {
        const result = spawnSync(process.execPath, [path.join(__dirname, 'server.js')], {
            env: { ...process.env, OPERATOR_TOKEN: token }, encoding: 'utf8', timeout: 5000
        });
        assert.equal(result.status, 1);
        assert.match(result.stderr, /OPERATOR_TOKEN must be configured/);
    }
    assert.equal(validOperatorToken('x'.repeat(32)), true);
});

test('generated proxy processes receive the configured bind address', () => {
    const previous = process.env.PROXY_BIND_HOST;
    process.env.PROXY_BIND_HOST = '127.0.0.1';
    try {
        const context = { module: { exports: {} } };
        vm.runInNewContext(buildEcosystem([{ id: 's1', name: 'S1', port: 4001, target_host: 'example.test', domain: 'proxy.test' }]), context);
        assert.equal(context.module.exports.apps[0].env.PROXY_BIND_HOST, '127.0.0.1');
        assert.equal(path.isAbsolute(context.module.exports.apps[0].cwd), true);
    } finally {
        if (previous === undefined) delete process.env.PROXY_BIND_HOST;
        else process.env.PROXY_BIND_HOST = previous;
    }
});

test('proxy validation rejects unsafe identities and conflicting runtime names', () => {
    const valid = { id: 'sv1', name: 'Test API', domain: 'sv1.example.test', target_host: 'api.example.test:8443', port: 4001, target_protocol: 'https', tls_skip_verify: 0 };
    assert.doesNotThrow(() => validateProxies([valid]));
    for (const bad of [
        { ...valid, id: '../escape' }, { ...valid, domain: 'ok.test;include x' },
        { ...valid, target_host: 'user:pass@example.test' }, { ...valid, target_host: 'example.test/path' },
        { ...valid, port: '1e3' }, { ...valid, port: 65536 }, { ...valid, port: 8092 }, { ...valid, tls_skip_verify: 'false' }
    ]) assert.throws(() => validateProxies([bad]));
    assert.throws(() => validateProxies([]));
    assert.throws(() => validateProxies([valid, { ...valid, id: 'sv2', domain: 'sv2.example.test', port: 4002, name: 'Test-API' }]));
    assert.throws(() => validateProxies([valid, { ...valid, id: 'sv2', domain: 'SV1.EXAMPLE.TEST', port: 4002, name: 'Other' }]));
    assert.throws(() => validateProxies([valid, { ...valid, id: 'sv2', domain: 'sv2.example.test', port: '4001', name: 'Other' }]));
});

test('combined layout requires isolated paths, unique ports and loopback bindings', () => {
    const base = path.resolve(os.tmpdir(), 'proxy-layout-test');
    const layout = { service: path.join(base, 'current'), lock: path.join(base, 'runtime.lock'), state: path.join(base, 'state'), role: 'combined' };
    const env = {
        PROXY_SERVICE_PATH: layout.service, OPERATOR_RUNTIME_LOCK_DIR: layout.lock,
        OPERATOR_BACKUP_ROOT: path.join(layout.state, 'backups'), OPERATOR_JOB_LOG_DIR: path.join(layout.state, 'jobs'),
        OPERATOR_BIND_HOST: '127.0.0.1', PROXY_BIND_HOST: '127.0.0.1'
    };
    const app = { name: 'proxy-one', cwd: layout.service, script: './src/index.js', env: { PORT: 4001, PROXY_BIND_HOST: '127.0.0.1' } };
    assert.doesNotThrow(() => validateProxyLayout({ apps: [app] }, env, layout));
    assert.throws(() => validateProxyLayout({ apps: [app] }, { ...env, OPERATOR_BIND_HOST: '0.0.0.0' }, layout));
    assert.throws(() => validateProxyLayout({ apps: [{ ...app, env: { ...app.env, PROXY_BIND_HOST: '0.0.0.0' } }] }, env, layout));
    assert.throws(() => validateProxyLayout({ apps: [{ ...app, env: { ...app.env, PORT: 8092 } }] }, env, layout));
    assert.throws(() => validateProxyLayout({ apps: [app, { ...app, name: 'proxy-two' }] }, env, layout));
    assert.throws(() => validateProxyLayout({ apps: [app] }, { ...env, OPERATOR_RUNTIME_LOCK_DIR: path.join(base, 'other') }, layout));
});

test('probeHealth checks the basic health endpoint', async () => {
    const originalFetch = globalThis.fetch;
    const urls = [];
    globalThis.fetch = async (url) => {
        urls.push(url);
        return { ok: true, json: async () => ({ status: 'healthy' }) };
    };
    try {
        const result = await probeHealth([{ id: 'test', domain: 'example.test', port: 3001 }], { attempts: 1 });
        assert.deepEqual(urls, ['http://127.0.0.1:3001/health']);
        assert.equal(result[0].health.status, 'healthy');
    } finally {
        globalThis.fetch = originalFetch;
    }
});

test('buildNginxConfig emits https server when wildcard cert is available', () => {
    const config = buildNginxConfig(
        {
            id: 'sv3',
            name: 'SV3',
            domain: 'sv3.shupremium.com',
            port: 4003
        },
        {
            available: true,
            path: '/etc/letsencrypt/live/shupremium-wildcard'
        }
    );

    assert.equal(config.filename, 'proxy-managed-sv3.conf');
    assert.match(config.content, /listen 443 ssl http2;/);
    assert.match(config.content, /ssl_certificate \/etc\/letsencrypt\/live\/shupremium-wildcard\/fullchain\.pem;/);
    assert.doesNotMatch(config.content, /HTTP fallback/);
});

test('buildNginxConfig falls back to http when wildcard cert is unavailable', () => {
    const config = buildNginxConfig(
        {
            id: 'sv3',
            name: 'SV3',
            domain: 'sv3.shupremium.com',
            port: 4003
        },
        {
            available: false,
            path: '/etc/letsencrypt/live/shupremium-wildcard'
        }
    );

    assert.match(config.content, /HTTP fallback/);
    assert.doesNotMatch(config.content, /listen 443 ssl http2;/);
});

test('buildNginxConfig renders configured Gemini and custom routes only', () => {
    const config = buildNginxConfig(
        {
            id: 'gemini',
            name: 'Gemini',
            domain: 'gemini.shupremium.com',
            port: 4010,
            max_body_size: '600m',
            route_policy: {
                effective_prefixes: ['/v1beta/models', '/v1beta/openai/', '/vendor/custom/']
            }
        },
        { available: false, path: '/etc/letsencrypt/live/shupremium-wildcard' }
    );

    assert.match(config.content, /location \^~ \/v1beta\/models\//);
    assert.match(config.content, /location \^~ \/v1beta\/openai\//);
    assert.match(config.content, /location \^~ \/vendor\/custom\//);
    assert.doesNotMatch(config.content, /location \^~ \/v1\//);
    assert.match(config.content, /client_max_body_size 600m;/);
});

test('buildNginxConfig rejects unsafe route prefixes before rendering', () => {
    assert.throws(
        () => buildNginxConfig({ id: 'bad', name: 'Bad', domain: 'bad.example.com', port: 4011, allowed_path_prefixes: ['/'] }, { available: false }),
        /Invalid route prefix/
    );
});

test('getCertCandidateDirs includes env path and legacy fallbacks', () => {
    const candidates = getCertCandidateDirs().map((item) => item.path);

    assert.ok(candidates.some((item) => item.endsWith('letsencrypt/live/shupremium-wildcard') || item.endsWith('letsencrypt\\live\\shupremium-wildcard')));
    assert.ok(candidates.some((item) => item.endsWith('letsencrypt/live/proxy-gateway') || item.endsWith('letsencrypt\\live\\proxy-gateway')));
});

test('serializeError preserves operator step metadata', () => {
    const error = new Error('nginx -t failed');
    error.step = 'nginx_test';
    error.details = { file: 'proxy-managed-sv3.conf' };

    assert.deepEqual(serializeError(error), {
        ok: false,
        error: 'nginx -t failed',
        step: 'nginx_test',
        details: { file: 'proxy-managed-sv3.conf' }
    });
});

test('classifyDesiredPm2Apps separates existing, restarting, and missing entries', () => {
    const result = classifyDesiredPm2Apps(
        new Set(['proxy-gpt1', 'proxy-sv3', 'proxy-sv4']),
        [
            { name: 'proxy-gpt1', status: 'online' },
            { name: 'proxy-sv3', status: 'stopped' }
        ]
    );

    assert.deepEqual(result, {
        existingNames: ['proxy-gpt1'],
        restartNames: ['proxy-sv3'],
        missingNames: ['proxy-sv4']
    });
});
