const http = require('http');
const https = require('https');

const BASE_URL = process.env.PROXY_OPERATOR_URL || 'http://127.0.0.1:8091';
const TOKEN = process.env.PROXY_OPERATOR_TOKEN || 'change-me';

function requestJson(method, pathname, body = null, timeout = 60000) {
    return new Promise((resolve, reject) => {
        const url = new URL(pathname, BASE_URL);
        const transport = url.protocol === 'https:' ? https : http;
        const payload = body ? JSON.stringify(body) : null;

        const req = transport.request(
            url,
            {
                method,
                timeout,
                headers: {
                    'Content-Type': 'application/json',
                    'X-Operator-Token': TOKEN,
                    ...(payload ? { 'Content-Length': Buffer.byteLength(payload) } : {}),
                },
            },
            (res) => {
                let raw = '';
                res.on('data', (chunk) => {
                    raw += chunk;
                });
                res.on('end', () => {
                    try {
                        const data = raw ? JSON.parse(raw) : {};
                        if (res.statusCode >= 400) {
                            reject(new Error(data.error || data.detail || `Operator HTTP ${res.statusCode}`));
                            return;
                        }
                        resolve(data);
                    } catch (error) {
                        reject(new Error(`Invalid operator response: ${raw}`));
                    }
                });
            }
        );

        req.on('timeout', () => {
            req.destroy(new Error('Operator timeout'));
        });
        req.on('error', reject);

        if (payload) {
            req.write(payload);
        }
        req.end();
    });
}

class OperatorClient {
    static applyState(proxies) {
        return requestJson('POST', '/api/runtime/apply', { proxies });
    }

    static getHealth() {
        return requestJson('GET', '/health', null, 10000);
    }

    static ensureWildcardCertificate() {
        return requestJson('POST', '/api/runtime/wildcard/ensure', {});
    }

    static restart(name) {
        return requestJson('POST', `/api/runtime/restart/${encodeURIComponent(name)}`, {});
    }
}

module.exports = OperatorClient;
