const express = require('express');
const router = express.Router();
const Proxy = require('../models/Proxy');
const ActivityLog = require('../models/ActivityLog');
const PM2Manager = require('../utils/pm2Manager');
const OperatorClient = require('../utils/operatorClient');
const os = require('os');

router.get('/', async (req, res) => {
    const stats = Proxy.getStats();
    const proxies = Proxy.getAll();
    const logs = ActivityLog.getRecent(10);
    let sslConfigured = false;
    try {
        const operatorHealth = await OperatorClient.getHealth();
        sslConfigured = Boolean(operatorHealth.wildcard_cert && operatorHealth.wildcard_cert.available);
    } catch (e) {
        console.error('[Dashboard] operator health error:', e.message);
    }
    
    let pm2Status = [];
    try {
        pm2Status = await PM2Manager.getStatus();
    } catch (e) {
        console.error('[Dashboard] PM2 status error:', e.message);
    }

    // System info
    const totalMem = os.totalmem();
    const freeMem = os.freemem();
    const system = {
        hostname: os.hostname(),
        platform: `${os.type()} ${os.release()}`,
        cpu: `${os.cpus().length} cores`,
        memory: `${Math.round((totalMem - freeMem) / 1024 / 1024 / 1024 * 10) / 10}GB / ${Math.round(totalMem / 1024 / 1024 / 1024)}GB`,
        memoryPercent: Math.round((totalMem - freeMem) / totalMem * 100),
        uptime: formatUptime(os.uptime())
    };

    res.render('dashboard/index', {
        title: 'Dashboard',
        stats,
        proxies,
        logs,
        pm2Status,
        system,
        sslConfigured
    });
});

router.get('/logs', (req, res) => {
    const logs = ActivityLog.getRecent(100);
    res.render('dashboard/logs', { title: 'Activity Logs', logs });
});

function formatUptime(seconds) {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${mins}m`;
    return `${mins}m`;
}

module.exports = router;
