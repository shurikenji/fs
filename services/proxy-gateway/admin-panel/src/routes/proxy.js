const express = require('express');
const router = express.Router();
const Proxy = require('../models/Proxy');
const ActivityLog = require('../models/ActivityLog');
const OperatorClient = require('../utils/operatorClient');

function normalizeProxyInput(body) {
    const targetProtocol = body.target_protocol === 'http' ? 'http' : 'https';

    return {
        name: body.name?.trim(),
        domain: body.domain?.trim().toLowerCase(),
        target_host: body.target_host?.trim(),
        target_protocol: targetProtocol,
        tls_skip_verify: body.tls_skip_verify === 'on' && targetProtocol === 'https',
        port: parseInt(body.port, 10),
        status: body.status || 'active'
    };
}

router.get('/', (req, res) => {
    const proxies = Proxy.getAll();
    res.render('proxy/list', {
        title: 'Quan ly Proxy',
        proxies,
        success: req.query.success,
        error: req.query.error
    });
});

router.get('/add', (req, res) => {
    res.render('proxy/form', {
        title: 'Them Proxy moi',
        proxy: null,
        nextPort: Proxy.getNextPort(),
        error: null
    });
});

async function syncRuntimeWithDb() {
    const proxies = Proxy.getActive();
    return OperatorClient.applyState(proxies);
}

router.post('/add', async (req, res) => {
    try {
        const input = normalizeProxyInput(req.body);

        if (!input.name || !input.domain || !input.target_host || !Number.isInteger(input.port)) {
            throw new Error('Vui long dien day du thong tin hop le');
        }

        if (Proxy.findByDomain(input.domain)) {
            throw new Error('Domain nay da ton tai');
        }

        if (Proxy.findByPort(input.port)) {
            throw new Error('Port nay da duoc su dung');
        }

        const id = Proxy.create(input);
        try {
            await syncRuntimeWithDb();
        } catch (syncError) {
            Proxy.delete(id);
            throw syncError;
        }

        ActivityLog.create('CREATE_PROXY', `Tao proxy: ${input.name} (${input.domain})`, req.ip);
        res.redirect('/proxy?success=' + encodeURIComponent(`Da tao proxy "${input.name}" va sync runtime`));
    } catch (error) {
        res.render('proxy/form', {
            title: 'Them Proxy moi',
            proxy: req.body,
            nextPort: req.body.port || Proxy.getNextPort(),
            error: error.message
        });
    }
});

router.get('/edit/:id', (req, res) => {
    const proxy = Proxy.findById(req.params.id);
    if (!proxy) {
        return res.redirect('/proxy?error=Khong%20tim%20thay%20proxy');
    }

    res.render('proxy/form', {
        title: 'Sua Proxy',
        proxy,
        nextPort: proxy.port,
        error: null
    });
});

router.post('/edit/:id', async (req, res) => {
    try {
        const id = parseInt(req.params.id, 10);
        const input = normalizeProxyInput(req.body);

        if (!input.name || !input.domain || !input.target_host || !Number.isInteger(input.port)) {
            throw new Error('Vui long dien day du thong tin hop le');
        }

        const existing = Proxy.findByDomain(input.domain);
        if (existing && existing.id !== id) {
            throw new Error('Domain nay da duoc su dung boi proxy khac');
        }

        const existingPort = Proxy.findByPort(input.port);
        if (existingPort && existingPort.id !== id) {
            throw new Error('Port nay da duoc su dung');
        }

        const oldProxy = Proxy.findById(id);
        if (!oldProxy) {
            throw new Error('Khong tim thay proxy');
        }

        Proxy.update(id, input);
        try {
            await syncRuntimeWithDb();
        } catch (syncError) {
            Proxy.restore(oldProxy);
            throw syncError;
        }

        ActivityLog.create('UPDATE_PROXY', `Cap nhat proxy: ${input.name}`, req.ip);
        res.redirect('/proxy?success=' + encodeURIComponent(`Da cap nhat proxy "${input.name}" va sync runtime`));
    } catch (error) {
        res.render('proxy/form', {
            title: 'Sua Proxy',
            proxy: { ...req.body, id: req.params.id },
            nextPort: req.body.port,
            error: error.message
        });
    }
});

router.post('/delete/:id', async (req, res) => {
    try {
        const proxy = Proxy.findById(req.params.id);
        if (!proxy) {
            throw new Error('Khong tim thay proxy');
        }

        Proxy.delete(proxy.id);
        try {
            await syncRuntimeWithDb();
        } catch (syncError) {
            Proxy.restore(proxy);
            throw syncError;
        }

        ActivityLog.create('DELETE_PROXY', `Xoa proxy: ${proxy.name}`, req.ip);
        res.redirect('/proxy?success=' + encodeURIComponent(`Da xoa proxy "${proxy.name}"`));
    } catch (error) {
        res.redirect('/proxy?error=' + encodeURIComponent(error.message));
    }
});

router.post('/toggle/:id', async (req, res) => {
    try {
        const proxy = Proxy.findById(req.params.id);
        if (!proxy) {
            throw new Error('Khong tim thay proxy');
        }

        const newStatus = proxy.status === 'active' ? 'inactive' : 'active';
        Proxy.updateStatus(proxy.id, newStatus);
        try {
            await syncRuntimeWithDb();
        } catch (syncError) {
            Proxy.restore(proxy);
            throw syncError;
        }

        const action = newStatus === 'active' ? 'Bat' : 'Tat';
        ActivityLog.create('TOGGLE_PROXY', `${action} proxy: ${proxy.name}`, req.ip);
        res.redirect('/proxy?success=' + encodeURIComponent(`Da ${action.toLowerCase()} proxy "${proxy.name}"`));
    } catch (error) {
        res.redirect('/proxy?error=' + encodeURIComponent(error.message));
    }
});

router.post('/restart/:id', async (req, res) => {
    try {
        const proxy = Proxy.findById(req.params.id);
        if (!proxy) {
            throw new Error('Khong tim thay proxy');
        }

        const safeName = proxy.name.toLowerCase().replace(/[^a-z0-9]/g, '-');
        await OperatorClient.restart(`proxy-${safeName}`);

        ActivityLog.create('RESTART_PROXY', `Restart proxy: ${proxy.name}`, req.ip);
        res.redirect('/proxy?success=' + encodeURIComponent(`Da restart proxy "${proxy.name}"`));
    } catch (error) {
        res.redirect('/proxy?error=' + encodeURIComponent(error.message));
    }
});

module.exports = router;
