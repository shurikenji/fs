'use strict';

// ========================================
// BLOCKED PATTERNS - Chặn request độc hại
// ========================================

const BLOCKED_PATHS = [
    // Environment & Config files
    /\.env/i,
    /\.git/i,
    /\.svn/i,
    /\.htaccess/i,
    /\.htpasswd/i,
    /\.DS_Store/i,
    /config\.(php|ini|yml|yaml|json|xml)/i,
    /composer\.(json|lock)/i,
    /package\.(json|lock)/i,
    
    // Shell & Backdoor
    /shell\.(php|asp|aspx|jsp|cgi|txt)/i,
    /cmd\.(php|asp|aspx|jsp|cgi|txt)/i,
    /backdoor/i,
    /webshell/i,
    /c99\.(php|txt)/i,
    /r57\.(php|txt)/i,
    
    // Admin panels
    /phpmyadmin/i,
    /adminer/i,
    /phpinfo/i,
    /wp-admin/i,
    /wp-login/i,
    /wp-config/i,
    /xmlrpc\.php/i,
    
    // Vendor paths
    /\/vendor\//i,
    /\/node_modules\//i,
    
    // Backup files
    /\.(bak|backup|old|orig|save|swp|sql|db|sqlite)$/i,
    
    // Executable files
    /\.(php|asp|aspx|jsp|cgi|pl|py|rb|sh|bash|exe|dll)$/i
];

const BLOCKED_USER_AGENTS = [
    /sqlmap/i,
    /nikto/i,
    /nmap/i,
    /masscan/i,
    /zgrab/i,
    /gobuster/i,
    /dirbuster/i,
    /wfuzz/i,
    /ffuf/i,
    /nuclei/i,
    /acunetix/i,
    /scanner/i
];

const BLOCKED_QUERY_PATTERNS = [
    // SQL Injection
    /union\s+(all\s+)?select/i,
    /select\s+.*\s+from/i,
    /insert\s+into/i,
    /drop\s+(table|database)/i,
    
    // XSS
    /<script/i,
    /javascript:/i,
    /onerror\s*=/i,
    
    // Path traversal
    /\.\.\//,
    /%2e%2e/i
];

// Allowed API paths (whitelist)
const ALLOWED_PATH_PREFIXES = [
    '/v1/',
    '/api/',
    '/dashboard/billing/',
    '/health',
    '/_internal/health'
];

// ========================================
// CHECK FUNCTIONS
// ========================================

function isBlockedPath(path) {
    for (const pattern of BLOCKED_PATHS) {
        if (pattern.test(path)) return true;
    }
    return false;
}

function isBlockedUserAgent(userAgent) {
    if (!userAgent) return false;
    for (const pattern of BLOCKED_USER_AGENTS) {
        if (pattern.test(userAgent)) return true;
    }
    return false;
}

function isBlockedQuery(url) {
    for (const pattern of BLOCKED_QUERY_PATTERNS) {
        if (pattern.test(url)) return true;
    }
    return false;
}

function isAllowedPath(path) {
    if (path === '/' || path === '') return true;
    for (const prefix of ALLOWED_PATH_PREFIXES) {
        if (path.startsWith(prefix)) return true;
    }
    return false;
}

// ========================================
// MIDDLEWARE
// ========================================

async function securityMiddleware(request, reply) {
    const path = request.url.split('?')[0];
    const userAgent = request.headers['user-agent'] || '';
    const ip = request.ip;
    
    // 1. Check User-Agent (scanner detection)
    if (isBlockedUserAgent(userAgent)) {
        request.log.warn({ type: 'BLOCKED_UA', ip, userAgent });
        reply.code(403);
        return reply.send({ error: { message: 'Forbidden', type: 'security_error' } });
    }
    
    // 2. Check blocked paths
    if (isBlockedPath(path)) {
        request.log.warn({ type: 'BLOCKED_PATH', ip, path });
        reply.code(403);
        return reply.send({ error: { message: 'Forbidden', type: 'security_error' } });
    }
    
    // 3. Check query patterns (SQL injection, XSS)
    if (isBlockedQuery(request.url)) {
        request.log.warn({ type: 'BLOCKED_QUERY', ip, url: request.url });
        reply.code(403);
        return reply.send({ error: { message: 'Forbidden', type: 'security_error' } });
    }
    
    // 4. Check allowed paths (whitelist)
    if (!isAllowedPath(path)) {
        reply.code(404);
        return reply.send({ error: { message: 'Not found', type: 'invalid_request_error' } });
    }
}

module.exports = { securityMiddleware };
