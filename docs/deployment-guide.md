# Hướng Dẫn Deploy Monorepo

Tài liệu này mô tả cách triển khai `shupremium-stack` một cách an toàn, không chạm vào `.env`, `data`, `venv` và không còn phụ thuộc vào tarball thủ công.

## 1. Chiến lược khuyến nghị

Chiến lược tốt nhất cho stack hiện tại là:

- tạo một private GitHub repo cho `shupremium-stack`
- mỗi VPS clone cùng một repo vào `/srv/shupremium-stack/repo`
- deploy theo `app + git ref`
- runtime state nằm ngoài repo checkout

Không dùng Docker ở giai đoạn này vì:

- `portal` và `platform-control` đang dùng SQLite cục bộ
- `shopbot` cũng có state cục bộ
- vấn đề hiện tại là deploy hygiene, không phải thiếu container

## 2. Layout trên VPS

```text
/srv/shupremium-stack/
  repo/
  releases/
    20260405-120001/
      portal/
      platform-control/
      proxy-gateway/
      shopbot/
  current/
    portal -> /srv/shupremium-stack/releases/<ts>/portal
    platform-control -> /srv/shupremium-stack/releases/<ts>/platform-control
    proxy-gateway -> /srv/shupremium-stack/releases/<ts>/proxy-gateway
    shopbot -> /srv/shupremium-stack/releases/<ts>/shopbot
  shared/
    portal/
      .env
      data/
      venv/
    platform-control/
      .env
      data/
      venv/
    shopbot/
      .env
      data/
      venv/
    proxy-gateway/
      proxy-operator/
        .env
```

## 3. Tạo repo GitHub mới

Tại local:

```bash
cd shupremium-stack
git init -b main
git add .
git commit -m "Initial monorepo import"
git remote add origin <PRIVATE_GITHUB_URL>
git push -u origin main
```

Sau đó có thể dùng branch và tag như bình thường:

- `main`
- `feature/...`
- tag release:
  - `portal-2026-04-05.1`
  - `stack-2026-04-05.1`

## 4. Bootstrap VPS

Trên từng VPS:

```bash
sudo mkdir -p /srv/shupremium-stack
sudo chown -R $USER:$USER /srv/shupremium-stack
git clone <PRIVATE_GITHUB_URL> /srv/shupremium-stack/repo
```

Tạo file host role:

- ARM VPS:
```bash
echo arm | sudo tee /etc/shupremium-host-role
```

- Shopbot VPS:
```bash
echo shopbot | sudo tee /etc/shupremium-host-role
```

Chạy bootstrap:

```bash
cd /srv/shupremium-stack/repo
bash ops/deploy/bootstrap-host.sh
```

## 5. Chuẩn bị shared runtime

### Portal

```bash
mkdir -p /srv/shupremium-stack/shared/portal/data
cp /path/to/current-portal/.env /srv/shupremium-stack/shared/portal/.env
cp -a /path/to/current-portal/data/. /srv/shupremium-stack/shared/portal/data/
python3 -m venv /srv/shupremium-stack/shared/portal/venv
```

### Platform Control

```bash
mkdir -p /srv/shupremium-stack/shared/platform-control/data
cp /path/to/current-platform-control/.env /srv/shupremium-stack/shared/platform-control/.env
cp -a /path/to/current-platform-control/data/. /srv/shupremium-stack/shared/platform-control/data/
python3 -m venv /srv/shupremium-stack/shared/platform-control/venv
```

### Shopbot

```bash
mkdir -p /srv/shupremium-stack/shared/shopbot/data
cp /path/to/current-shopbot/.env /srv/shupremium-stack/shared/shopbot/.env
python3 -m venv /srv/shupremium-stack/shared/shopbot/venv
```

### Proxy Gateway

```bash
mkdir -p /srv/shupremium-stack/shared/proxy-gateway/proxy-operator
cp /path/to/current-proxy-operator/.env /srv/shupremium-stack/shared/proxy-gateway/proxy-operator/.env
```

## 6. Deploy theo app

### ARM VPS

```bash
cd /srv/shupremium-stack/repo
bash ops/deploy/deploy-portal.sh main
bash ops/deploy/deploy-platform-control.sh main
bash ops/deploy/deploy-proxy-gateway.sh main
```

### Shopbot VPS

```bash
cd /srv/shupremium-stack/repo
bash ops/deploy/deploy-shopbot.sh main
```

## 7. Rollback

Rollback về release trước:

```bash
cd /srv/shupremium-stack/repo
bash ops/deploy/rollback-app.sh portal
```

Rollback về release cụ thể:

```bash
bash ops/deploy/rollback-app.sh portal /srv/shupremium-stack/releases/20260405-120001/portal
```

## 8. Ghi chú runtime

- `portal`, `platform-control`: chạy bằng `PM2`
- `proxy-gateway`: `proxy-service` dùng PM2 ecosystem, `proxy-operator` là PM2 process đơn
- `shopbot`: giữ `systemd` làm runtime chính vì app hiện đã có flow này, không ép PM2 chỉ để đồng bộ bề ngoài

## 9. Vì sao monorepo vẫn dễ trên 2 VPS

Monorepo chỉ là cách tổ chức code. Việc deploy vẫn tách theo app:

- cùng một repo
- khác host role
- khác script deploy

Điều này còn dễ hơn hiện tại vì:

- một nơi duy nhất để quản lý code
- script deploy đồng nhất
- rollback đồng nhất
- không cần tarball thủ công
