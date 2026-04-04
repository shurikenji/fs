require('dotenv').config();
const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const axios = require('axios');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;
const CONTROL_PLANE_URL = (process.env.CONTROL_PLANE_URL || '').replace(/\/$/, '');
const SERVERS_CACHE_TTL_MS = parseInt(process.env.SERVERS_CACHE_TTL_MS || '60000', 10);

// ==================== SECURITY MIDDLEWARE ====================

// Helmet - Security headers
app.use(helmet({
    contentSecurityPolicy: {
        directives: {
            defaultSrc: ["'self'"],
            styleSrc: ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
            fontSrc: ["'self'", "https://fonts.gstatic.com"],
            scriptSrc: ["'self'"],
            imgSrc: ["'self'", "data:"],
        },
    },
}));

// CORS - Strict origin
const allowedOrigins = [
    process.env.ALLOWED_ORIGIN || 'https://check.shupremium.com',
    'http://localhost:3000', // Dev
];

app.use(cors({
    origin: (origin, callback) => {
        if (!origin || allowedOrigins.includes(origin)) {
            callback(null, true);
        } else {
            callback(new Error('CORS blocked'));
        }
    },
    credentials: true,
}));

// Rate limiting - 30 requests per minute per IP (supports multiple keys)
const limiter = rateLimit({
    windowMs: 60 * 1000,
    max: 30,
    message: { error: 'Too many requests. Please wait 1 minute.' },
    standardHeaders: true,
    legacyHeaders: false,
});
app.use('/api/', limiter);

// JSON parser
app.use(express.json());

// Static files
app.use(express.static(path.join(__dirname, 'public')));

// ==================== HIDDEN PROXY CONFIG ====================

let cachedServers = null;
let cachedServersAt = 0;

function buildFallbackServers() {
    const fallback = {};
    const sources = [
        ['server1', process.env.PROXY_AABAO, 'Server 1', 0.3],
        ['server2', process.env.PROXY_996444, 'Server 2', 0.5],
        ['server4', process.env.PROXY_KKSJ, 'Server 4', 0.9],
        ['server5', process.env.PROXY_XJAI, 'Server 5', 1.0],
    ];

    for (const [id, url, name, rate] of sources) {
        if (url) {
            fallback[id] = { url, name, rate };
        }
    }
    return fallback;
}

async function loadServers(force = false) {
    const now = Date.now();
    if (!force && cachedServers && (now - cachedServersAt) < SERVERS_CACHE_TTL_MS) {
        return cachedServers;
    }

    if (!CONTROL_PLANE_URL) {
        cachedServers = buildFallbackServers();
        cachedServersAt = now;
        return cachedServers;
    }

    try {
        const response = await axios.get(`${CONTROL_PLANE_URL}/api/public/balance-sources`, { timeout: 10000 });
        const next = {};
        const items = Array.isArray(response.data?.servers) ? response.data.servers : [];
        for (const item of items) {
            if (!item?.id || !item?.base_url) continue;
            next[String(item.id)] = {
                url: String(item.base_url),
                name: String(item.name || item.id),
                rate: Number(item.rate || 1),
            };
        }
        cachedServers = Object.keys(next).length > 0 ? next : buildFallbackServers();
    } catch (error) {
        console.error(`[${new Date().toISOString()}] Control plane fetch failed:`, error.message);
        cachedServers = buildFallbackServers();
    }

    cachedServersAt = now;
    return cachedServers;
}

// ==================== HELPER FUNCTIONS ====================

function maskApiKey(key) {
    if (!key || key.length < 10) return '***';
    return key.substring(0, 5) + '***' + key.substring(key.length - 4);
}

function validateApiKey(key) {
    if (!key || typeof key !== 'string') return false;
    return /^sk-[a-zA-Z0-9]{20,}$/.test(key);
}

async function fetchBillingData(proxyUrl, apiKey) {
    const headers = {
        'Authorization': `Bearer ${apiKey}`,
        'Accept': 'application/json',
    };

    const [subscriptionRes, usageRes] = await Promise.all([
        axios.get(`${proxyUrl}/v1/dashboard/billing/subscription`, { headers, timeout: 15000 }),
        axios.get(`${proxyUrl}/v1/dashboard/billing/usage`, { headers, timeout: 15000 }),
    ]);

    return {
        subscription: subscriptionRes.data,
        usage: usageRes.data,
    };
}

// ==================== API ROUTES ====================

// Get available servers (URLs and rates are hidden)
app.get('/api/servers', async (req, res) => {
    const serversMap = await loadServers();
    const servers = Object.entries(serversMap).map(([id, s]) => ({
        id,
        name: s.name,
    }));
    res.json({ servers });
});

// Check balance endpoint
app.post('/api/check-balance', async (req, res) => {
    const { api_key, server } = req.body;
    const serversMap = await loadServers();

    // Validate input
    if (!validateApiKey(api_key)) {
        return res.status(400).json({
            error: 'Invalid API key format. Must start with sk-'
        });
    }

    if (!server || !serversMap[server]) {
        return res.status(400).json({
            error: 'Invalid server'
        });
    }

    const serverConfig = serversMap[server];
    const maskedKey = maskApiKey(api_key);

    console.log(`[${new Date().toISOString()}] Check balance: ${maskedKey} via ${serverConfig.name}`);

    try {
        const data = await fetchBillingData(serverConfig.url, api_key);

        // Raw values from API
        const rawLimit = data.subscription.hard_limit_usd || 0;
        const rawUsage = (data.usage.total_usage || 0) / 100; // API returns cents

        // Apply rate conversion to get real USD value
        const rate = serverConfig.rate;
        const limit = rawLimit / rate;
        const usage = rawUsage / rate;
        const balance = Math.max(0, limit - usage);

        res.json({
            success: true,
            server: serverConfig.name,
            data: {
                limit_usd: limit.toFixed(2),
                usage_usd: usage.toFixed(2),
                balance_usd: balance.toFixed(2),
                has_payment_method: data.subscription.has_payment_method || false,
            },
        });
    } catch (error) {
        console.error(`[${new Date().toISOString()}] Error for ${maskedKey}:`, error.message);

        // Parse API error
        let errorMessage = 'Failed to check balance';
        if (error.response?.data?.error?.message) {
            errorMessage = error.response.data.error.message;
            // Translate common Chinese errors
            if (errorMessage.includes('无效的令牌')) {
                errorMessage = 'Invalid API key';
            } else if (errorMessage.includes('额度已用尽')) {
                errorMessage = 'Quota exhausted';
            }
        }

        res.status(error.response?.status || 500).json({
            success: false,
            error: errorMessage,
        });
    }
});

// Serve index.html for /check-balance route
app.get('/check-balance', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// ==================== START SERVER ====================

app.listen(PORT, () => {
    console.log(`🚀 Balance Checker running on port ${PORT}`);
    console.log(`📍 Local: http://localhost:${PORT}/check-balance`);
    console.log(`🔒 CORS allowed: ${allowedOrigins.join(', ')}`);
});
