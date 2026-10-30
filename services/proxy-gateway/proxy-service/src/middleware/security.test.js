const assert = require('node:assert/strict');
const { test } = require('node:test');

process.env.ALLOWED_PATH_PREFIXES_JSON = JSON.stringify(['/v1/', '/v1beta/models', '/vendor/custom/']);
const { isAllowedPath } = require('./security');

test('route allowlist uses segment-aware matching', () => {
    assert.equal(isAllowedPath('/v1/chat/completions'), true);
    assert.equal(isAllowedPath('/v1beta/models/gemini-3.7-flash:generateContent'), true);
    assert.equal(isAllowedPath('/v1beta/modelsEvil'), false);
    assert.equal(isAllowedPath('/v1beta/openai/chat/completions'), false);
    assert.equal(isAllowedPath('/vendor/custom/action'), true);
    assert.equal(isAllowedPath('/admin'), false);
});
