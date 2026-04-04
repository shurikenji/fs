const express = require('express');
const router = express.Router();
const Proxy = require('../models/Proxy');
const ActivityLog = require('../models/ActivityLog');
const OperatorClient = require('../utils/operatorClient');

router.get('/', async (req, res) => {
    let operatorHealth = { status: 'unknown', wildcard_cert: { available: false } };
    try {
        operatorHealth = await OperatorClient.getHealth();
    } catch (error) {
        operatorHealth = { status: 'degraded', error: error.message, wildcard_cert: { available: false } };
    }

    res.render('ssl/index', {
        title: 'Wildcard SSL',
        proxies: Proxy.getAll(),
        operatorHealth,
        success: req.query.success,
        error: req.query.error
    });
});

router.post('/ensure', async (req, res) => {
    try {
        const result = await OperatorClient.ensureWildcardCertificate();
        ActivityLog.create('ENSURE_WILDCARD_SSL', `Ensure wildcard cert: ${result.cert_name || 'ok'}`, req.ip);
        res.redirect('/ssl?success=' + encodeURIComponent('Da yeu cau proxy-operator cap nhat wildcard certificate'));
    } catch (error) {
        res.redirect('/ssl?error=' + encodeURIComponent(error.message));
    }
});

module.exports = router;
