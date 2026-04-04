const express = require('express');
const session = require('express-session');
const SQLiteStore = require('connect-sqlite3')(session);
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const path = require('path');

const app = express();
const PORT = process.env.ADMIN_PORT || 8080;

// ========================================
// SECURITY
// ========================================

// Trust proxy (chạy sau nginx)
app.set('trust proxy', 1);

// Helmet security headers
app.use(helmet({ 
    contentSecurityPolicy: false,
    crossOriginEmbedderPolicy: false
}));

// Rate limiting
app.use(rateLimit({
    windowMs: 15 * 60 * 1000, // 15 phút
    max: 200,
    message: 'Quá nhiều request, vui lòng thử lại sau',
    standardHeaders: true,
    legacyHeaders: false
}));

// ========================================
// BODY PARSER
// ========================================

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ========================================
// SESSION
// ========================================

app.use(session({
    store: new SQLiteStore({ 
        db: 'sessions.db', 
        dir: path.join(__dirname, '../data') 
    }),
    secret: process.env.SESSION_SECRET || 'proxy-gateway-secret-change-this-in-production',
    resave: false,
    saveUninitialized: false,
    cookie: { 
        secure: false, // Set true khi dùng HTTPS
        httpOnly: true, 
        maxAge: 24 * 60 * 60 * 1000, // 24 giờ
        sameSite: 'lax'
    }
}));

// ========================================
// VIEW ENGINE
// ========================================

app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));

// Static files
app.use(express.static(path.join(__dirname, '../public')));

// ========================================
// AUTH MIDDLEWARE
// ========================================

const requireAuth = (req, res, next) => {
    // Cho phép truy cập auth routes
    if (req.path.startsWith('/auth')) {
        return next();
    }
    
    // Kiểm tra đăng nhập
    if (!req.session.authenticated) {
        return res.redirect('/auth/login');
    }
    
    next();
};

app.use(requireAuth);

// ========================================
// ROUTES
// ========================================

app.use('/auth', require('./routes/auth'));
app.use('/dashboard', require('./routes/dashboard'));
app.use('/proxy', require('./routes/proxy'));
app.use('/ssl', require('./routes/ssl'));
app.use('/settings', require('./routes/settings'));

// Root redirect
app.get('/', (req, res) => res.redirect('/dashboard'));

// ========================================
// ERROR HANDLERS
// ========================================

// 404
app.use((req, res) => {
    res.status(404).render('error', { 
        title: '404 - Không tìm thấy', 
        message: 'Trang bạn tìm không tồn tại' 
    });
});

// 500
app.use((err, req, res, next) => {
    console.error('[Error]', err);
    res.status(500).render('error', { 
        title: 'Lỗi', 
        message: err.message || 'Đã có lỗi xảy ra' 
    });
});

// ========================================
// START SERVER
// ========================================

app.listen(PORT, '0.0.0.0', () => {
    console.log(`
╔═══════════════════════════════════════════════════════════╗
║              ADMIN PANEL STARTED                          ║
╠═══════════════════════════════════════════════════════════╣
║  URL:      http://localhost:${PORT}                          ║
║  Password: admin123 (đổi sau khi đăng nhập)               ║
╚═══════════════════════════════════════════════════════════╝
    `);
});
