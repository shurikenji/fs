#!/usr/bin/env node
'use strict';

// Copy a generated PM2 state into shared storage without modifying its source.
const fs = require('node:fs');
const path = require('node:path');

const [source, stackArgument] = process.argv.slice(2);
if (!source || !stackArgument) {
    console.error('Usage: node prepare-proxy-state.js <source-ecosystem> <stack-root>');
    process.exit(2);
}

try {
    const root = fs.realpathSync(stackArgument);
    const shared = path.join(root, 'shared', 'proxy-gateway', 'proxy-service');
    if (fs.realpathSync(shared) !== shared) throw new Error('Shared proxy state path must not traverse symlinks');
    const sourceInfo = fs.statSync(source);
    if (!sourceInfo.isFile() || sourceInfo.size > 10 * 1024 * 1024) throw new Error('Invalid source ecosystem file');
    const text = fs.readFileSync(source, 'utf8');
    const match = text.match(/^\s*(?:\/\/[^\n]*\n\s*)*module\.exports\s*=\s*\{\s*apps\s*:\s*(\[[\s\S]*\])\s*\}\s*;?\s*$/);
    if (!match) throw new Error('Source must use the generated JSON ecosystem format');
    const apps = JSON.parse(match[1]);
    if (!Array.isArray(apps) || apps.length === 0) throw new Error('Source ecosystem has no apps');
    const names = new Set();
    const ports = new Set();
    const reserved = new Set([22, 80, 443, 8080, 8090, 8091, 8092, 8093]);
    const cwd = path.join(root, 'current', 'proxy-gateway', 'proxy-service');
    for (const app of apps) {
        const rawPort = String(app?.env?.PORT ?? '');
        const port = Number(rawPort);
        if (!app || typeof app !== 'object' || !app.env || typeof app.env !== 'object' || Array.isArray(app.env) || typeof app.name !== 'string' || !/^proxy-[a-z0-9-]+$/.test(app.name) ||
            names.has(app.name) || app.script !== './src/index.js' || !/^[0-9]{1,5}$/.test(rawPort) || port < 1 || port > 65535 || reserved.has(port) || ports.has(port)) {
            throw new Error('Invalid or duplicate proxy name, script, or port');
        }
        names.add(app.name);
        ports.add(port);
        app.cwd = cwd;
        app.env.PROXY_BIND_HOST = '127.0.0.1';
    }
    const destination = path.join(shared, 'ecosystem.config.js');
    const fd = fs.openSync(destination, 'wx', 0o600);
    try {
        fs.writeFileSync(fd, `// Migrated PM2 state; managed by Proxy Operator\nmodule.exports = ${JSON.stringify({ apps }, null, 2)};\n`);
    } finally {
        fs.closeSync(fd);
    }
    console.log(`Prepared proxy state for ${apps.length} apps; source was not modified.`);
} catch (error) {
    console.error(`Proxy state preparation failed: ${error.message}`);
    process.exitCode = 1;
}
