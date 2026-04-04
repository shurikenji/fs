# Shupremium Stack Memory

## Workspace hiện tại
https://github.com/shurikenji/fs.git
- Monorepo mới đã được tạo tại: `D:\Projects\Code\shupremium-stack`
- Đây là repo làm việc mới cho toàn bộ stack.
- Thư mục cũ `D:\Projects\Code\Business\shupremium-stack` đã được chuyển đi và xóa.
- Các source gốc trong `D:\Projects\Code\Business\...` vẫn còn, đóng vai trò bản an toàn/back-up, chưa bị xóa.

## Mục tiêu của monorepo này

Chuẩn hóa toàn bộ stack vào một repo duy nhất nhưng vẫn giữ runtime production theo hướng:

- Git làm source of truth
- PM2 + nginx cho các app trên VPS ARM
- systemd giữ lại cho `shopbot`
- Không dùng Docker ở giai đoạn hiện tại

Lý do:

- `portal` và `platform-control` đang ổn với PM2
- Có SQLite và file runtime cục bộ
- Vấn đề production lớn nhất là deploy thủ công dễ chép nhầm `.env`, `.venv`, DB

## Cấu trúc monorepo hiện tại

```text
shupremium-stack/
  apps/
    portal/
    platform-control/
    shopbot/
  services/
    proxy-gateway/
    balance-checker/
  docs/
  ops/
    deploy/
    pm2/
    nginx/
    scripts/
  archive/
  memory.md
```

## Ánh xạ code đã import

- `apps/portal`
  - import từ `D:\Projects\Code\Business\pricing-hub`
- `apps/platform-control`
  - import từ `D:\Projects\Code\Business\platform-control`
- `apps/shopbot`
  - import từ `D:\Projects\Code\Business\shopbot`
- `services/proxy-gateway`
  - import từ `D:\Projects\Code\Business\proxy-gateway`
- `services/balance-checker`
  - import từ `D:\Projects\Code\Business\balance-checker`

## Những gì đã được làm

### 1. Đã tạo monorepo mới

- Tạo thư mục gốc `shupremium-stack`
- Copy toàn bộ source cần thiết vào monorepo
- Không copy runtime state vào repo mới

### 2. Đã dọn runtime artifact khỏi repo mới

Monorepo hiện tại đã được dọn khỏi:

- `.env`
- `.venv`
- `node_modules`
- SQLite DB
- nested `.git`
- zip/tar runtime artifact trong cây repo mới

### 3. Đã khởi tạo Git root cho monorepo

Repo Git mới đã được init tại:

- `D:\Projects\Code\shupremium-stack\.git`

### 4. Đã scaffold lớp vận hành

Các file vận hành quan trọng đã có:

- `README.md`
- `docs/deployment-guide.md`
- `ops/deploy/app-manifest.sh`
- `ops/deploy/lib.sh`
- `ops/deploy/bootstrap-host.sh`
- `ops/deploy/deploy-portal.sh`
- `ops/deploy/deploy-platform-control.sh`
- `ops/deploy/deploy-shopbot.sh`
- `ops/deploy/deploy-proxy-gateway.sh`
- `ops/deploy/rollback-app.sh`
- `ops/pm2/portal.ecosystem.config.cjs`
- `ops/pm2/platform-control.ecosystem.config.cjs`
- `ops/pm2/proxy-operator.ecosystem.config.cjs`
- `ops/pm2/shopbot.ecosystem.config.cjs`
- `ops/nginx/README.md`

## Quyết định vận hành đã chốt

### 1. Topology production

- VPS ARM chạy:
  - `portal`
  - `platform-control`
  - `proxy-gateway`
- VPS riêng chạy:
  - `shopbot`

### 2. Monorepo không có nghĩa deploy cả stack cùng lúc

Deploy sẽ theo:

- từng app
- từng host role

Không deploy kiểu copy nguyên repo lên cả 2 VPS rồi chạy tất cả.

### 3. Shared runtime phải nằm ngoài repo checkout

Layout khuyến nghị trên VPS:

```text
/srv/shupremium-stack/
  repo/
  releases/
  current/
  shared/
```

Trong đó:

- `repo/`: git clone
- `releases/`: mỗi lần deploy tạo release mới
- `current/`: symlink đang chạy
- `shared/`: `.env`, `data`, `venv`

### 4. Runtime state tuyệt đối không được đưa vào Git

Bao gồm:

- `.env`
- `.venv`
- `data/`
- SQLite DB
- log runtime
- tar/zip deploy artifact

## Runtime / deploy model theo app

### portal

- Runtime: PM2
- Shared state:
  - `/srv/shupremium-stack/shared/portal/.env`
  - `/srv/shupremium-stack/shared/portal/data`
  - `/srv/shupremium-stack/shared/portal/venv`
- Health checks dự kiến:
  - `/health`
  - `/`
  - `/pricing`

### platform-control

- Runtime: PM2
- Shared state:
  - `/srv/shupremium-stack/shared/platform-control/.env`
  - `/srv/shupremium-stack/shared/platform-control/data`
  - `/srv/shupremium-stack/shared/platform-control/venv`

### shopbot

- Runtime chính nên giữ: systemd
- Lý do:
  - app hiện đã có flow docs theo systemd
  - không cần ép PM2 chỉ để đồng nhất bề ngoài
- Shared state:
  - `/srv/shupremium-stack/shared/shopbot/.env`
  - `/srv/shupremium-stack/shared/shopbot/data`
  - `/srv/shupremium-stack/shared/shopbot/venv`

### proxy-gateway

- Runtime:
  - `proxy-service`: PM2 ecosystem
  - `proxy-operator`: PM2 process
  - `admin-panel`: PM2 ecosystem, optional deploy
- Shared state:
  - `/srv/shupremium-stack/shared/proxy-gateway/proxy-operator/.env`
  - `/srv/shupremium-stack/shared/proxy-gateway/admin-panel/.env`
  - `/srv/shupremium-stack/shared/proxy-gateway/admin-panel/data`

## Những điểm kỹ thuật quan trọng đã xác nhận

### portal

- App Python/FastAPI
- Có `.env`, `.venv`, SQLite `data/hub.db`
- Production phải chạy với `APP_DEBUG=false`
- Trước đây đã từng có incident:
  - `.env` bị overwrite bởi artifact local
  - `PRICING_ADMIN_TOKEN` và `CONTROL_PLANE_TOKEN` bị đổi thành local token
  - `hub.db` từng bị corrupt sau lần deploy sai

### platform-control

- App Python/FastAPI
- Có `.env`, `.venv`, SQLite `data/platform_control.db`
- Đang gọi từ `portal` qua token nội bộ

### shopbot

- Python app
- Entry chính: `python -m bot.main`
- Có admin panel FastAPI chạy cùng process
- Docs cũ có `shopbot.service` qua systemd

### proxy-gateway

- Node-based
- Bao gồm:
  - `proxy-service`
  - `proxy-operator`
  - `admin-panel`
- `proxy-service` và `admin-panel` đã có `ecosystem.config.js`
- `proxy-operator` dùng `.env`, chạy ở port 8091

## Tình trạng pricing/Yunwu cần nhớ

Trong các cuộc trước đã xác nhận:

- Public pricing hiện đi theo snapshot/cache, không fetch upstream trực tiếp cho user request
- `quota_multiple` vẫn là rule bắt buộc cho public display
- `gpt2` có shape gần `rixapi`
- `gpt1`, `gpt4`, `gpt5`, `sv1` có shape catalog-list/Yunwu-style
- Pricing Yunwu hiện đã có patch để:
  - hiển thị `billing_label`
  - `billing_unit`
  - `price_multiplier`
  - endpoint path + method rõ ràng cho user

Nhưng kiến trúc pricing hiện tại mới là bản vá thực dụng. Hướng tốt hơn đã được xác định là:

- parser thô
- pricing engine riêng
- presenter public riêng
- registry rule rõ ràng

Việc này chưa refactor toàn bộ trong monorepo mới.

## Những việc còn dang dở

### 1. Push monorepo lên GitHub riêng

Cần làm:

```bash
cd D:\Projects\Code\shupremium-stack
git add .
git commit -m "Initial monorepo import"
git remote add origin <PRIVATE_GITHUB_URL>
git push -u origin main
```

### 2. Bootstrap 2 VPS theo layout mới

- clone repo vào `/srv/shupremium-stack/repo`
- tạo `/etc/shupremium-host-role`
- chạy `ops/deploy/bootstrap-host.sh`
- chép shared runtime vào `/srv/shupremium-stack/shared/...`

### 3. Cần review lại deploy script trước khi dùng production

Các script đã scaffold xong, nhưng trước khi rollout production thật nên review thêm:

- path symlink
- quyền `systemctl` cho `shopbot`
- flow PM2 cho `proxy-gateway`
- smoke checks phù hợp từng app

### 4. Chưa migrate production thật sang layout release/current/shared

Hiện mới dừng ở mức scaffold code và script local.

## Cách làm việc nên dùng từ giờ

Nếu mở cuộc trò chuyện mới, nên bắt đầu từ:

- working directory: `D:\Projects\Code\shupremium-stack`

Và nói rõ mục tiêu tiếp theo là một trong các việc sau:

- review lại monorepo structure
- push repo mới lên GitHub
- hoàn thiện deploy script production
- bootstrap ARM VPS
- bootstrap shopbot VPS
- refactor pricing engine theo kiến trúc parser/engine/presenter

## Nguyên tắc quan trọng phải giữ

- Không deploy bằng tarball thủ công nữa nếu không phải trường hợp khẩn cấp
- Không copy đè `.env`
- Không copy đè `data/`
- Không để `.venv` và `node_modules` vào Git
- Không ép Docker khi runtime và SQLite chưa được externalize sạch

