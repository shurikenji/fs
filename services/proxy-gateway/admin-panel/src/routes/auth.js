const express = require('express');
const router = express.Router();
const Settings = require('../models/Settings');
const ActivityLog = require('../models/ActivityLog');

router.get('/login', (req, res) => {
    if (req.session.authenticated) {
        return res.redirect('/');
    }
    res.render('auth/login', { 
        title: 'Đăng nhập', 
        error: req.query.error || null 
    });
});

router.post('/login', (req, res) => {
    const { password } = req.body;
    const ip = req.ip;
    
    if (Settings.verifyPassword(password)) {
        req.session.authenticated = true;
        ActivityLog.create('LOGIN', 'Đăng nhập thành công', ip);
        return res.redirect('/');
    }
    
    ActivityLog.create('LOGIN_FAILED', 'Sai mật khẩu', ip);
    res.redirect('/auth/login?error=Mật khẩu không đúng');
});

router.get('/logout', (req, res) => {
    ActivityLog.create('LOGOUT', 'Đăng xuất', req.ip);
    req.session.destroy();
    res.redirect('/auth/login');
});

module.exports = router;
