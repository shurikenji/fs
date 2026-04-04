const express = require('express');
const router = express.Router();
const Settings = require('../models/Settings');
const ActivityLog = require('../models/ActivityLog');
const Proxy = require('../models/Proxy');
const OperatorClient = require('../utils/operatorClient');

router.get('/', (req, res) => {
    res.render('settings/index', {
        title: 'Cai dat',
        adminEmail: Settings.get('admin_email') || '',
        operatorUrl: process.env.PROXY_OPERATOR_URL || 'http://127.0.0.1:8091',
        success: req.query.success,
        error: req.query.error
    });
});

router.post('/password', (req, res) => {
    try {
        const { current, newpass, confirm } = req.body;

        if (!Settings.verifyPassword(current)) {
            throw new Error('Mat khau hien tai khong dung');
        }

        if (newpass !== confirm) {
            throw new Error('Mat khau moi khong khop');
        }

        if (newpass.length < 6) {
            throw new Error('Mat khau phai it nhat 6 ky tu');
        }

        Settings.changePassword(newpass);
        ActivityLog.create('CHANGE_PASSWORD', 'Doi mat khau admin', req.ip);
        res.redirect('/settings?success=' + encodeURIComponent('Da doi mat khau'));
    } catch (error) {
        res.redirect('/settings?error=' + encodeURIComponent(error.message));
    }
});

router.post('/email', (req, res) => {
    try {
        const { email } = req.body;
        if (!email || !email.includes('@')) {
            throw new Error('Email khong hop le');
        }
        Settings.set('admin_email', email);
        ActivityLog.create('UPDATE_EMAIL', `Cap nhat email: ${email}`, req.ip);
        res.redirect('/settings?success=' + encodeURIComponent('Da cap nhat email'));
    } catch (error) {
        res.redirect('/settings?error=' + encodeURIComponent(error.message));
    }
});

router.post('/regenerate', async (req, res) => {
    try {
        const activeProxies = Proxy.getActive();
        await OperatorClient.applyState(activeProxies);

        ActivityLog.create('REGENERATE', `Sync runtime for ${activeProxies.length} proxies`, req.ip);
        res.redirect('/settings?success=' + encodeURIComponent(`Da sync ${activeProxies.length} proxy configs qua operator`));
    } catch (error) {
        res.redirect('/settings?error=' + encodeURIComponent(error.message));
    }
});

module.exports = router;
