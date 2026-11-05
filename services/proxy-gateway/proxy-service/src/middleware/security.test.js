const assert = require('node:assert/strict');
const { test } = require('node:test');
const { spawnSync } = require('node:child_process');

process.env.ALLOWED_PATH_PREFIXES_JSON = JSON.stringify(['/v1/', '/v1beta/models', '/vendor/custom/']);
const { isAllowedPath, securityMiddleware } = require('./security');

test('route allowlist uses segment-aware matching', () => {
    assert.equal(isAllowedPath('/v1/chat/completions'), true);
    assert.equal(isAllowedPath('/v1beta/models/gemini-3.7-flash:generateContent'), true);
    assert.equal(isAllowedPath('/v1beta/modelsEvil'), false);
    assert.equal(isAllowedPath('/v1beta/openai/chat/completions'), false);
    assert.equal(isAllowedPath('/vendor/custom/action'), true);
    assert.equal(isAllowedPath('/admin'), false);
});

test('health passes the security hook without exposing internal health', async () => {
    const app = require('fastify')({ trustProxy: true });
    app.addHook('onRequest', securityMiddleware);
    app.get('/health', async () => ({ status: 'healthy' }));
    app.get('/_internal/health', async () => ({ target: 'private' }));
    try {
        const health = await app.inject({ method: 'GET', url: '/health' });
        assert.equal(health.statusCode, 200);
        assert.deepEqual(health.json(), { status: 'healthy' });
        const internal = await app.inject({
            method: 'GET', url: '/_internal/health', headers: { 'x-forwarded-for': '127.0.0.1' }
        });
        assert.equal(internal.statusCode, 404);
        assert.equal(isAllowedPath('/_internal/health'), false);
        assert.equal(isAllowedPath('/health/extra'), false);
    } finally {
        await app.close();
    }
});

test('internal health stays blocked even with a broad configured route', () => {
    const result = spawnSync(process.execPath, ['-e',
        "if (require('./src/middleware/security').isAllowedPath('/_internal/health')) process.exit(1)"
    ], { cwd: require('node:path').resolve(__dirname, '../..'), env: { ...process.env, ALLOWED_PATH_PREFIXES_JSON: '[\"/_internal/\"]' } });
    assert.equal(result.status, 0);
});
