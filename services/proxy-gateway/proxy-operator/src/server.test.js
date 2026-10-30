const test = require('node:test');
const assert = require('node:assert/strict');

const {
    buildNginxConfig,
    classifyDesiredPm2Apps,
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
