# shupremium-stack

Monorepo này gom toàn bộ code đang chạy của stack Shupremium vào một repo duy nhất, nhưng vẫn giữ runtime production theo hướng:

- `Git` làm source of truth
- `PM2 + nginx` cho các app trên VPS ARM
- `systemd` giữ lại cho `shopbot` vì đó là runtime đang hợp với app này nhất hiện tại

Mục tiêu chính là tách hẳn `code` khỏi `runtime state` để không lặp lại các lỗi deploy thủ công như:

- chép nhầm `.env`
- chép nhầm SQLite DB
- chép cả `.venv` hoặc `node_modules`
- rollout khó rollback

## Cấu trúc repo

```text
shupremium-stack/
  apps/
    portal/
    platform-control/
    shopbot/
  services/
    proxy-gateway/
  docs/
  ops/
    deploy/
    pm2/
    nginx/
    scripts/
  archive/
    services/
      balance-checker/
```

## Ánh xạ ứng dụng

- `apps/portal`: public pricing, balance, keys, logs
- `apps/platform-control`: control plane và admin shell
- `apps/shopbot`: bot + admin panel của shopbot
- `services/proxy-gateway`: proxy-service và proxy-operator
- `archive/services/balance-checker`: archived legacy service, no longer maintained in the active stack

## Triển khai trên 2 VPS

Monorepo không làm deploy khó hơn. Cách đúng là deploy theo app và theo host role:

- VPS ARM:
  - `portal`
  - `platform-control`
  - `proxy-gateway`
- VPS Shopbot:
  - `shopbot`

Mỗi app có script deploy riêng trong `ops/deploy/`. Bạn không deploy nguyên repo lên cả 2 máy, mà chỉ checkout cùng một repo rồi extract đúng subtree cần cho từng app.

## Runtime state không được commit

Những thứ sau phải nằm ngoài Git checkout:

- `.env`
- `.venv`
- `node_modules`
- `data/`
- SQLite DB
- log, tarball, zip, temp

Layout production khuyến nghị nằm ở:

```text
/srv/shupremium-stack/
  repo/
  releases/
  current/
  shared/
```

Chi tiết vận hành xem thêm ở [docs/deployment-guide.md](docs/deployment-guide.md).
