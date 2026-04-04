'use strict';

const Fastify = require('fastify');
const fastifyHttpProxy = require('@fastify/http-proxy');
const { Agent } = require('undici');
const { securityMiddleware } = require('./middleware/security');

// ========================================
// CONFIGURATION (từ environment variables)
// ========================================

const PORT = parseInt(process.env.PORT) || 3001;
const TARGET_HOST = process.env.TARGET_HOST || 'api.openai.com';
const TARGET_PROTOCOL = process.env.TARGET_PROTOCOL === 'http' ? 'http' : 'https';
const TLS_SKIP_VERIFY = process.env.TLS_SKIP_VERIFY === 'true';
const SERVICE_NAME = process.env.SERVICE_NAME || 'proxy';
const PROXY_DOMAIN = process.env.PROXY_DOMAIN || 'localhost';

// ========================================
// BROWSER LANDING PAGE
// ========================================

const BROWSER_PAGE = `<!DOCTYPE html>
<html>
<head>
    <title>API Gateway</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f0f23 0%, #1a1a3e 50%, #0d1b2a 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            text-align: center;
            padding: 60px 40px;
            background: rgba(255,255,255,0.03);
            border-radius: 24px;
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255,255,255,0.1);
            max-width: 480px;
            box-shadow: 0 25px 50px rgba(0,0,0,0.3);
        }
        .icon { font-size: 4em; margin-bottom: 24px; }
        h1 { color: #fff; font-size: 2rem; margin-bottom: 16px; font-weight: 600; }
        p { color: rgba(255,255,255,0.7); font-size: 1rem; line-height: 1.6; margin-bottom: 12px; }
        code { 
            background: rgba(255,255,255,0.1); padding: 4px 10px; border-radius: 6px; 
            font-family: 'SF Mono', Monaco, monospace; font-size: 0.9rem; color: #7dd3fc;
        }
        .status { 
            display: inline-flex; align-items: center; gap: 8px; padding: 12px 24px; 
            background: linear-gradient(135deg, #059669, #10b981); color: white; 
            border-radius: 50px; font-weight: 600; font-size: 0.95rem; margin-top: 24px;
            box-shadow: 0 4px 15px rgba(16, 185, 129, 0.3);
        }
        .dot { width: 8px; height: 8px; background: #fff; border-radius: 50%; animation: pulse 2s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">🔐</div>
        <h1>API Gateway</h1>
        <p>This is a secure API proxy service.</p>
        <p>Use <code>POST /v1/chat/completions</code></p>
        <div class="status"><span class="dot"></span>Service Online</div>
    </div>
</body>
</html>`;

// ========================================
// HTTP AGENT (Connection Pooling)
// ========================================

const proxyAgent = new Agent({
    keepAliveTimeout: 60000,
    keepAliveMaxTimeout: 120000,
    connections: 100,
    pipelining: 1,
    connect: {
        timeout: 60000,
        rejectUnauthorized: !TLS_SKIP_VERIFY
    }
});

// ========================================
// CREATE FASTIFY INSTANCE
// ========================================

const app = Fastify({
    logger: {
        level: process.env.LOG_LEVEL || 'warn'
    },
    trustProxy: true,
    bodyLimit: 629145600,  // 600MB
    connectionTimeout: 0,
    keepAliveTimeout: 300000,
    disableRequestLogging: true
});

// ========================================
// CORS HANDLING (thay vì dùng plugin - tránh conflict)
// ========================================

app.addHook('onRequest', async (request, reply) => {
    // Set CORS headers
    reply.header('Access-Control-Allow-Origin', '*');
    reply.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS, PATCH');
    reply.header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With, Accept');
    reply.header('Access-Control-Allow-Credentials', 'true');
    
    // Handle preflight OPTIONS request
    if (request.method === 'OPTIONS') {
        reply.code(204).send();
        return;
    }
});

// ========================================
// SECURITY & BROWSER CHECK MIDDLEWARE
// ========================================

app.addHook('onRequest', async (request, reply) => {
    // Skip if already handled (OPTIONS)
    if (reply.sent) return;
    
    // Run security middleware
    await securityMiddleware(request, reply);
    if (reply.sent) return;
    
    // Browser detection for root path - show landing page
    const path = request.url.split('?')[0];
    if (path === '/' || path === '') {
        const userAgent = request.headers['user-agent'] || '';
        const hasAuth = request.headers['authorization'];
        const isJSON = request.headers['content-type']?.includes('application/json');
        const isBrowser = /Mozilla|Chrome|Safari|Edge|Opera|Firefox/i.test(userAgent);
        
        if (isBrowser && !hasAuth && !isJSON) {
            reply.type('text/html').code(200);
            return reply.send(BROWSER_PAGE);
        }
    }
});

// ========================================
// HEALTH CHECK - ẨN THÔNG TIN NHẠY CẢM
// ========================================

app.get('/health', async (request, reply) => {
    // Public health - chỉ trả status cơ bản, KHÔNG lộ target
    return {
        status: 'healthy',
        timestamp: new Date().toISOString()
    };
});

// ========================================
// INTERNAL HEALTH - CHỈ LOCALHOST
// ========================================

app.get('/_internal/health', async (request, reply) => {
    // Chỉ cho phép từ localhost
    const ip = request.ip;
    const isLocal = ip === '127.0.0.1' || ip === '::1' || ip.includes('127.0.0.1');
    
    if (!isLocal) {
        reply.code(403);
        return { error: 'Forbidden' };
    }
    
    // Internal health - full info cho monitoring
    const mem = process.memoryUsage();
    return {
        status: 'healthy',
        service: SERVICE_NAME,
        target: TARGET_HOST,
        domain: PROXY_DOMAIN,
        port: PORT,
        uptime: Math.floor(process.uptime()),
        memory: {
            rss_mb: Math.round(mem.rss / 1024 / 1024),
            heap_used_mb: Math.round(mem.heapUsed / 1024 / 1024)
        },
        timestamp: new Date().toISOString()
    };
});

// ========================================
// PROXY SETUP
// ========================================

async function setupProxy() {
    await app.register(fastifyHttpProxy, {
        upstream: `${TARGET_PROTOCOL}://${TARGET_HOST}`,
        prefix: '/',
        rewritePrefix: '/',
        http2: false,
        undici: proxyAgent,
        
        replyOptions: {
            // Rewrite request headers - ẩn proxy info
            rewriteRequestHeaders: (originalReq, headers) => {
                // Set host to target
                headers['host'] = TARGET_HOST;
                
                // XÓA tất cả headers có thể expose proxy
                delete headers['x-forwarded-for'];
                delete headers['x-forwarded-proto'];
                delete headers['x-forwarded-host'];
                delete headers['x-forwarded-port'];
                delete headers['x-real-ip'];
                delete headers['forwarded'];
                delete headers['via'];
                
                // Xóa Cloudflare headers
                delete headers['cf-connecting-ip'];
                delete headers['cf-ray'];
                delete headers['cf-ipcountry'];
                delete headers['cf-visitor'];
                delete headers['cf-request-id'];
                
                // Xóa các headers khác có thể leak
                delete headers['x-request-id'];
                delete headers['x-correlation-id'];
                delete headers['x-amzn-trace-id'];
                
                // Ensure proper encoding
                headers['accept-encoding'] = 'gzip, deflate, br';
                headers['connection'] = 'keep-alive';
                
                return headers;
            },
            
            // Rewrite response headers
            rewriteHeaders: (headers, req) => {
                // Xóa headers expose server info
                delete headers['server'];
                delete headers['x-powered-by'];
                delete headers['x-aspnet-version'];
                
                // Xóa Cloudflare headers
                delete headers['cf-ray'];
                delete headers['cf-cache-status'];
                delete headers['cf-request-id'];
                delete headers['alt-svc'];
                delete headers['nel'];
                delete headers['report-to'];
                
                // Rewrite location header (redirects)
                if (headers['location']) {
                    headers['location'] = headers['location']
                        .replace(new RegExp(TARGET_HOST, 'gi'), PROXY_DOMAIN)
                        .replace(/^http:/, 'https:');
                }
                
                // Rewrite cookies
                if (headers['set-cookie']) {
                    const cookies = Array.isArray(headers['set-cookie']) 
                        ? headers['set-cookie'] 
                        : [headers['set-cookie']];
                    headers['set-cookie'] = cookies.map(cookie =>
                        cookie.replace(new RegExp(TARGET_HOST, 'gi'), PROXY_DOMAIN)
                    );
                }
                
                return headers;
            }
        }
    });
}

// ========================================
// ERROR HANDLER
// ========================================

app.setErrorHandler((error, request, reply) => {
    // Log error nhưng không expose chi tiết
    request.log.error({ err: error.message, code: error.code });
    
    if (error.code === 'ECONNREFUSED') {
        return reply.status(503).send({
            error: { message: 'Service temporarily unavailable', type: 'api_error' }
        });
    }
    
    if (error.code === 'ETIMEDOUT' || error.code === 'ESOCKETTIMEDOUT') {
        return reply.status(504).send({
            error: { message: 'Request timeout', type: 'api_error' }
        });
    }

    if (
        error.code === 'CERT_HAS_EXPIRED' ||
        error.code === 'DEPTH_ZERO_SELF_SIGNED_CERT' ||
        error.code === 'SELF_SIGNED_CERT_IN_CHAIN' ||
        error.code === 'UNABLE_TO_VERIFY_LEAF_SIGNATURE'
    ) {
        return reply.status(502).send({
            error: { message: 'Upstream TLS certificate error', type: 'api_error' }
        });
    }
    
    return reply.status(500).send({
        error: { message: 'Internal error', type: 'api_error' }
    });
});

// ========================================
// GRACEFUL SHUTDOWN
// ========================================

const shutdown = async (signal) => {
    console.log(`[${SERVICE_NAME}] Shutting down...`);
    try {
        await app.close();
        process.exit(0);
    } catch (err) {
        process.exit(1);
    }
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

// ========================================
// START SERVER
// ========================================

async function start() {
    try {
        await setupProxy();
        await app.listen({ port: PORT, host: '0.0.0.0' });
        console.log(
            `[${SERVICE_NAME}] Started on port ${PORT} -> ${TARGET_PROTOCOL}://${TARGET_HOST} (verify=${TLS_SKIP_VERIFY ? 'off' : 'on'})`
        );
    } catch (err) {
        console.error(`[${SERVICE_NAME}] Failed to start:`, err.message);
        process.exit(1);
    }
}

start();
