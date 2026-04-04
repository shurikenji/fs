# Shupremium V4 — Remaining Rollout Plan

## Live State (từ memory.md)

| Component | Trạng thái | VPS | Ghi chú |
|-----------|-----------|-----|---------|
| **shopbot** | ✅ Live | Shopbot VPS | SSO consumer active, DB healthy |
| **platform-control** | ✅ Live | ARM VPS (PM2) | `admin.shupremium.com`, SSO + proxy sync OK |
| **proxy-operator** | ✅ Live | ARM VPS (PM2) | `:8091`, health OK |
| **proxy-gateway** | ✅ Live | ARM VPS (PM2+Nginx) | 7 proxies serving customers |
| **pricing-hub** (Portal) | ⏳ Code ready, chưa deploy | — | Cần deploy lên ARM VPS |
| **balance-checker** (cũ) | ⚠️ Vẫn live | Oracle VPS khác | Chưa thay thế |
| **admin-panel** (cũ) | ⚠️ Còn trong PM2 | ARM VPS | Traffic đã chuyển sang platform-control |
| **Wildcard cert** | ❌ Missing | ARM VPS | `/etc/letsencrypt/live/shupremium-wildcard` not found |

---

## Phase 1: Deploy Portal lên ARM VPS

> [!IMPORTANT]
> Portal (pricing-hub) chạy trên cùng ARM VPS với proxy-gateway + platform-control. Port `:8080`.

### Bước thực hiện

```bash
# 1. SSH vào ARM VPS
ssh ubuntu@<ARM-IP>

# 2. Clone/copy pricing-hub code
mkdir -p /home/ubuntu/portal
# Upload pricing-hub code từ local (SCP hoặc git clone)
scp -r pricing-hub/* ubuntu@<ARM-IP>:/home/ubuntu/portal/

# 3. Setup Python venv
cd /home/ubuntu/portal
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. Tạo .env
cat > .env << 'EOF'
APP_TITLE=Shupremium Portal
APP_HOST=0.0.0.0
APP_PORT=8080
APP_DEBUG=false
DB_PATH=data/hub.db
ADMIN_SECRET=<generate-random-secret>
CONTROL_PLANE_URL=http://127.0.0.1:8090
CONTROL_PLANE_TOKEN=<same-token-as-platform-control>
CONTROL_PLANE_SYNC_ENABLED=true
EOF

# 5. Init DB + verify
mkdir -p data
source .venv/bin/activate
python main.py &   # Test start
curl http://localhost:8080/health
curl http://localhost:8080/
# Ctrl+C to stop test

# 6. Add to PM2
pm2 start --name portal --interpreter /home/ubuntu/portal/.venv/bin/python /home/ubuntu/portal/main.py
pm2 save
```

### Nginx config cho Portal

```bash
# 7. Tạo nginx config
sudo tee /etc/nginx/sites-available/portal.conf << 'EOF'
server {
    listen 443 ssl http2;
    server_name shupremium.com www.shupremium.com;

    ssl_certificate     /etc/letsencrypt/live/shupremium.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/shupremium.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
server {
    listen 80;
    server_name shupremium.com www.shupremium.com;
    return 301 https://$host$request_uri;
}
EOF

sudo ln -sf /etc/nginx/sites-available/portal.conf /etc/nginx/sites-enabled/
sudo nginx -t
# CHƯA reload nginx — đợi DNS + cert sẵn sàng
```

> [!WARNING]
> SSL cert cho `shupremium.com` cần tồn tại trước khi enable config. Nếu chưa có cert riêng, dùng certbot:
> ```bash
> sudo certbot certonly --nginx -d shupremium.com -d www.shupremium.com
> ```
> Hoặc nếu wildcard cert đã fix xong thì dùng chung wildcard.

### Verify Portal trước khi public

```bash
# Test nội bộ trên ARM VPS
curl http://localhost:8080/           # Landing
curl http://localhost:8080/pricing    # Pricing 
curl http://localhost:8080/check      # Balance checker
curl http://localhost:8080/status     # Proxy status
curl http://localhost:8080/health     # Health check
```

---

## Phase 2: DNS + Go Live Portal

| Record | Type | Value | Proxy |
|--------|------|-------|-------|
| `shupremium.com` | A | `<ARM-IP>` | ☁️ Proxied |
| `www.shupremium.com` | CNAME | `shupremium.com` | ☁️ Proxied |

```bash
# Sau khi DNS propagate:
sudo nginx -s reload
# Verify public
curl -I https://shupremium.com/
curl -I https://shupremium.com/pricing
curl -I https://shupremium.com/check
```

---

## Phase 3: Fix Wildcard Certificate

Wildcard cert hiện đang missing. Cần tạo bằng Certbot DNS challenge qua Cloudflare:

```bash
# 1. Cài Cloudflare plugin cho certbot (nếu chưa có)
sudo apt install python3-certbot-dns-cloudflare

# 2. Tạo Cloudflare credentials file
sudo mkdir -p /etc/letsencrypt
sudo tee /etc/letsencrypt/cloudflare.ini << 'EOF'
dns_cloudflare_api_token = <CLOUDFLARE-API-TOKEN>
EOF
sudo chmod 600 /etc/letsencrypt/cloudflare.ini

# 3. Request wildcard cert
sudo certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /etc/letsencrypt/cloudflare.ini \
  -d "*.shupremium.com" \
  -d "shupremium.com" \
  --cert-name shupremium-wildcard

# 4. Verify
sudo ls /etc/letsencrypt/live/shupremium-wildcard/

# 5. Update all nginx configs to use wildcard cert
# Thay thế cert path trong portal.conf, admin-panel.conf, và proxy configs
```

> [!TIP]
> Sau khi có wildcard cert, TẤT CẢ nginx configs có thể dùng chung 1 cert:
> ```nginx
> ssl_certificate     /etc/letsencrypt/live/shupremium-wildcard/fullchain.pem;
> ssl_certificate_key /etc/letsencrypt/live/shupremium-wildcard/privkey.pem;
> ```

---

## Phase 4: Retire Old Services

> Chỉ làm sau khi Portal đã verify ổn định 24-48h.

### 4a. Retire balance-checker standalone

```bash
# Trên Oracle free-tier VPS (balance-checker)
# Verify portal /check hoạt động tốt trước
curl -X POST https://shupremium.com/api/check-balance \
  -H "Content-Type: application/json" \
  -d '{"api_key":"sk-test","server":"1"}'

# Nếu OK → stop old balance-checker
# DNS: xóa record cũ trỏ tới Oracle VPS (nếu có domain riêng)
```

### 4b. Retire old admin-panel

```bash
# Trên ARM VPS
pm2 stop admin-panel
pm2 delete admin-panel
pm2 save

# Giữ code tại chỗ 1 tuần nữa rồi xóa:
# rm -rf /home/ubuntu/proxy-gateway/admin-panel  # sau 1 tuần
```

---

## Phase 5: Backup Automation

### Shopbot DB backup (trên Shopbot VPS)

```bash
# Tạo backup script
sudo tee /home/ubuntu/scripts/shopbot-backup.sh << 'SCRIPT'
#!/bin/bash
set -euo pipefail
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
DB=/home/ubuntu/shopbot/shopbot.db
BACKUP_DIR=/home/ubuntu/backups
mkdir -p "$BACKUP_DIR"

# Safe SQLite backup (không lock DB)
sqlite3 "$DB" ".backup $BACKUP_DIR/shopbot-$TIMESTAMP.db"

# Cleanup > 7 ngày
find "$BACKUP_DIR" -name "shopbot-*.db" -mtime +7 -delete

echo "[$(date)] Backup done: shopbot-$TIMESTAMP.db"
SCRIPT

chmod +x /home/ubuntu/scripts/shopbot-backup.sh

# Cron mỗi 6 giờ
crontab -e
# Thêm dòng:
# 0 */6 * * * /home/ubuntu/scripts/shopbot-backup.sh >> /home/ubuntu/backups/backup.log 2>&1
```

---

## Checklist Tổng Hợp

### Phase 1 — Deploy Portal ⏳
- [ ] Upload pricing-hub code lên ARM VPS `/home/ubuntu/portal`
- [ ] Setup venv + install deps
- [ ] Tạo `.env` với `CONTROL_PLANE_URL=http://127.0.0.1:8090`
- [ ] Test `curl localhost:8080/health`
- [ ] Add PM2 process `portal`
- [ ] Tạo `portal.conf` trong nginx

### Phase 2 — DNS + Go Live ⏳
- [ ] Certbot cho `shupremium.com` (hoặc dùng wildcard)
- [ ] DNS `shupremium.com` → ARM IP
- [ ] `nginx -s reload`
- [ ] Verify tất cả routes public

### Phase 3 — Wildcard Cert ⏳
- [ ] Cài certbot-dns-cloudflare
- [ ] Request `*.shupremium.com` + `shupremium.com` wildcard
- [ ] Update nginx configs dùng wildcard cert
- [ ] Test `Ensure Wildcard Cert` từ platform-control dashboard

### Phase 4 — Cleanup (sau 24-48h ổn định)
- [ ] Verify Portal `/check` thay thế hoàn toàn balance-checker cũ
- [ ] `pm2 delete admin-panel`
- [ ] Stop/release Oracle balance-checker VPS

### Phase 5 — Backup
- [ ] Tạo backup script trên Shopbot VPS
- [ ] Setup cron mỗi 6h
- [ ] Test backup + restore thử 1 lần

---

## PM2 Trạng Thái Sau Rollout

```
ARM VPS PM2 list (mục tiêu):
┌─────────┬──────────────────────┬──────┬───────┐
│ id      │ name                 │ port │ mode  │
├─────────┼──────────────────────┼──────┼───────┤
│ 0       │ proxy-gpt1           │ 3001 │ cluster│
│ 1       │ proxy-gpt2           │ 3002 │ cluster│
│ ...     │ ...                  │ ...  │ ...   │
│ 13      │ proxy-sv2            │ 4002 │ cluster│
│ 14      │ proxy-operator       │ 8091 │ fork  │
│ 15      │ platform-control     │ 8090 │ fork  │
│ 16      │ portal               │ 8080 │ fork  │
│ --      │ admin-panel ❌ (xóa) │ --   │ --    │
└─────────┴──────────────────────┴──────┴───────┘
```

## ❓ Câu Hỏi

1. **Bạn muốn tôi tạo script tự động hóa** Phase 1 (deploy portal) không? Một file `deploy-portal.sh` mà bạn chỉ cần chạy trên ARM VPS.

2. **SSL cert cho `shupremium.com`** — hiện tại đã có cert riêng cho domain này chưa, hay chỉ có cert cho các subdomain proxy (gpt1, gpt2,...)?

3. **Cloudflare API token** — bạn đã có token cho DNS challenge chưa? (Cần cho wildcard cert)
