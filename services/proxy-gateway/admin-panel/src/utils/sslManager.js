const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');
const Settings = require('../models/Settings');

const SSL_PATH = '/etc/letsencrypt/live';
const CF_CREDENTIALS = '/home/ubuntu/.secrets/cloudflare.ini';
const CERT_NAME = 'proxy-gateway';
const LOCK_FILE = '/tmp/certbot.lock';

class SSLManager {
    // Kiểm tra domain có trong cert không
    static checkCert(domain) {
        return new Promise((resolve) => {
            exec('sudo certbot certificates 2>/dev/null', (error, stdout) => {
                if (error) {
                    resolve({ exists: false });
                    return;
                }
                
                // Tìm cert proxy-gateway và kiểm tra domain có trong đó không
                const blocks = stdout.split('Certificate Name:');
                for (const block of blocks) {
                    if (block.includes(CERT_NAME) || block.includes('proxy-gateway')) {
                        // Tìm dòng Domains:
                        const domainsMatch = block.match(/Domains:\s*([^\n]+)/);
                        if (domainsMatch) {
                            const domains = domainsMatch[1].trim().split(/\s+/);
                            if (domains.includes(domain)) {
                                resolve({ 
                                    exists: true, 
                                    path: path.join(SSL_PATH, CERT_NAME),
                                    certName: CERT_NAME
                                });
                                return;
                            }
                        }
                    }
                }
                
                resolve({ exists: false });
            });
        });
    }

    // Kiểm tra sync - để dùng trong view
    static checkCertSync(domain) {
        try {
            const result = require('child_process').execSync(
                'sudo certbot certificates 2>/dev/null',
                { encoding: 'utf8', timeout: 10000 }
            );
            
            // Tìm trong output
            if (result.includes(domain)) {
                return { exists: true, path: path.join(SSL_PATH, CERT_NAME) };
            }
            return { exists: false };
        } catch (e) {
            return { exists: false };
        }
    }

    // Lấy danh sách certificates
    static async listCerts() {
        return new Promise((resolve) => {
            exec('sudo certbot certificates 2>/dev/null', (error, stdout) => {
                if (error) return resolve([]);
                
                const certs = [];
                const blocks = stdout.split('Certificate Name:').slice(1);
                
                for (const block of blocks) {
                    const lines = block.split('\n');
                    const cert = { name: lines[0].trim(), domains: [], expiry: null };
                    
                    for (const line of lines) {
                        if (line.includes('Domains:')) {
                            cert.domains = line.split(':')[1].trim().split(/\s+/).filter(d => d);
                        }
                        if (line.includes('Expiry Date:')) {
                            const match = line.match(/Expiry Date:\s*([^(]+)/);
                            if (match) cert.expiry = match[1].trim();
                        }
                    }
                    if (cert.domains.length > 0) certs.push(cert);
                }
                resolve(certs);
            });
        });
    }

    // Kiểm tra Cloudflare đã cấu hình chưa
    static isCloudflareConfigured() {
        // Kiểm tra từ database
        if (Settings.isCloudflareConfigured()) {
            return true;
        }
        
        // Kiểm tra file credentials
        if (fs.existsSync(CF_CREDENTIALS)) {
            const content = fs.readFileSync(CF_CREDENTIALS, 'utf8');
            return content.includes('dns_cloudflare_api_token') && 
                   !content.includes('YOUR_TOKEN');
        }
        
        return false;
    }

    // Cấu hình Cloudflare token
    static setupCloudflare(token) {
        if (!token || token.length < 20) {
            throw new Error('Token không hợp lệ');
        }
        
        // Lưu vào database
        Settings.setCloudflareToken(token);
        
        // Lưu vào file cho certbot
        const dir = path.dirname(CF_CREDENTIALS);
        if (!fs.existsSync(dir)) {
            fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
        }
        fs.writeFileSync(CF_CREDENTIALS, `dns_cloudflare_api_token = ${token}\n`, { mode: 0o600 });
        
        console.log('[SSL] Cloudflare token configured');
    }

    // Lấy SSL bằng DNS challenge (thêm domain vào cert chung)
    static async obtainDNS(domain, email = null) {
        if (!this.isCloudflareConfigured()) {
            throw new Error('Cloudflare chưa được cấu hình. Vào Settings > SSL để cấu hình.');
        }
        
        // Lock để tránh chạy song song
        if (fs.existsSync(LOCK_FILE)) {
            const lockTime = fs.statSync(LOCK_FILE).mtimeMs;
            if (Date.now() - lockTime < 180000) { // 3 phút
                throw new Error('Certbot đang chạy, vui lòng đợi...');
            }
        }
        fs.writeFileSync(LOCK_FILE, Date.now().toString());
        
        try {
            email = email || Settings.get('admin_email') || 'admin@localhost';
            
            // Lấy danh sách domains hiện có trong cert
            const certs = await this.listCerts();
            const existingCert = certs.find(c => c.name === CERT_NAME);
            
            let domains = [domain];
            if (existingCert && existingCert.domains) {
                const allDomains = new Set([...existingCert.domains, domain]);
                domains = Array.from(allDomains);
            }
            
            const domainsArg = domains.map(d => `-d ${d}`).join(' ');
            
            const cmd = `sudo certbot certonly --dns-cloudflare ` +
                       `--dns-cloudflare-credentials ${CF_CREDENTIALS} ` +
                       `${domainsArg} ` +
                       `--cert-name ${CERT_NAME} ` +
                       `--non-interactive --agree-tos -m ${email} ` +
                       `--expand 2>&1`;
            
            console.log(`[SSL] Obtaining cert for: ${domains.join(', ')}`);
            const result = await this._exec(cmd, 180000);
            console.log('[SSL] Certificate obtained successfully');
            return result;
            
        } finally {
            if (fs.existsSync(LOCK_FILE)) fs.unlinkSync(LOCK_FILE);
        }
    }

    // Renew tất cả certificates
    static async renew() {
        return this._exec('sudo certbot renew 2>&1', 300000);
    }

    static _exec(cmd, timeout = 60000) {
        return new Promise((resolve, reject) => {
            exec(cmd, { timeout }, (error, stdout, stderr) => {
                const output = stdout || stderr || '';
                
                if (error) {
                    console.error('[SSL] Error:', output);
                    
                    if (output.includes('DNS problem')) {
                        reject(new Error('DNS chưa trỏ về server hoặc chưa propagate'));
                    } else if (output.includes('too many certificates')) {
                        reject(new Error('Rate limit - đợi 1 tuần'));
                    } else if (output.includes('unauthorized') || output.includes('403')) {
                        reject(new Error('Cloudflare token không hợp lệ hoặc không có quyền'));
                    } else {
                        reject(new Error(output.substring(0, 200) || error.message));
                    }
                } else {
                    resolve(output);
                }
            });
        });
    }
}

module.exports = SSLManager;
