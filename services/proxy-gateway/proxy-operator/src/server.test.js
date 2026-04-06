const test = require('node:test');
const assert = require('node:assert/strict');

const {
    buildNginxConfig,
    getCertCandidateDirs,
    serializeError
} = require('./server');

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
