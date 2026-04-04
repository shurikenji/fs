# Solution Moi Cho `pricing-hub`

## 1. Ket luan ngan

`pricing-hub` hien tai da di dung huong voi kien truc **FastAPI + Jinja2 SSR + Alpine.js + SQLite**, phu hop hon nhieu so voi phuong an Next.js cu cho moi truong VPS Oracle Free Tier 1 CPU / 1 GB RAM.

Tai lieu cu trong `solotion.md` dang:

- sai ten file;
- lech voi codebase thuc te;
- con noi dung cua phuong an Next.js da bi thay the;
- bi loi encoding;
- chua phan anh dung phan nao da xong va phan nao con thieu.

Giai phap dung cho du an nay la:

1. Giu nguyen huong **FastAPI standalone project**.
2. Hoan thien lop **adapter + normalization + public sanitizer + admin CRUD**.
3. Bo sung cac phan chua hoan tat nhu **translation pipeline, sync log, poller, key group management, bootstrap seed, monitoring**.
4. On dinh deployment theo mo hinh **mot process Python duy nhat**, khong can Node.js tren server.

---

## 2. Hien trang da kiem tra trong repo

### 2.1 Stack hien tai

- Entry: `main.py`
- App factory: `app/app.py`
- Config: `app/config.py`
- Router public SSR:
  - `app/routers/public_pricing.py`
  - `app/routers/public_logs.py`
  - `app/routers/public_keys.py`
- JSON API:
  - `app/routers/api_pricing.py`
  - `app/routers/api_logs.py`
  - `app/routers/api_keys.py`
- Admin:
  - `app/routers/control/auth.py`
  - `app/routers/control/servers.py`
- Adapter:
  - `app/adapters/base.py`
  - `app/adapters/newapi.py`
  - `app/adapters/rixapi.py`
- DB:
  - `db/database.py`
  - `db/models.py`
  - `db/queries/servers.py`
  - `db/queries/translations.py`
- UI template:
  - `templates/`
- Static assets:
  - `static/`

### 2.2 Nhung gi da co the dung ngay

#### A. Kien truc van hanh

- FastAPI app factory da co.
- Session middleware cho admin da co.
- Static mount da co.
- SQLite bootstrap tu tao bang khi startup da co.

#### B. Public product surface

- Trang `/pricing` da render SSR.
- Trang `/logs` da co shell UI va goi API.
- Trang `/keys` da co shell UI va resolve API key.
- API `/api/pricing/{server_id}` da tra pricing da sanitize.
- API `/api/logs` da proxy log query len upstream.
- API `/api/keys/resolve` da resolve token tu API key.

#### C. Admin surface

- Login bang secret da co.
- Dashboard admin da co.
- CRUD server config da co.
- Nut sync pricing tung server da co.

#### D. Domain logic

- Header auth builder da co.
- Token search candidate / matching logic da co.
- Log fetch pattern da co.
- NewAPI adapter da normalize duoc phan lon pricing data.
- RixAPI adapter da ke thua normalize flow.
- Public sanitizer da co fallback translate co ban cho group/description.
- In-memory cache + DB cache da co.

### 2.3 Cac khoang trong thuc te

Day la nhung phan hien van chua hoan chinh hoac moi chi co khung:

1. **AI translation chua duoc noi vao runtime**
   - `translation_cache` va query da co, nhung chua co service goi AI provider va chua co warm-up/caching flow.

2. **`custom` adapter chua duoc implement**
   - Schema/admin UI co `custom`, nhung adapter factory hien chi map `newapi` va `rixapi`.

3. **Key manager moi chi resolve**
   - Chua co API list groups kha dung.
   - Chua co API doi group cho key.
   - UI hien chua thao tac duoc gi ngoai xem thong tin key.

4. **Logs page chua hoan thien filter UX**
   - Dropdown group chua load du lieu thuc te.
   - Cost estimation dang dung heuristic tai client, chua dong bo voi normalized pricing cache.

5. **Sync log/poller chua co**
   - Bang `sync_log` da ton tai nhung chua co noi ghi log.
   - Chua co background poller / scheduled refresh.

6. **Lifecycle dong DB chua hoan tat**
   - `init_db()` co chay o startup, nhung `close_db()` chua duoc goi o shutdown.

7. **Encoding dang lan loi mojibake**
   - Nhieu comment/text trong file cu va mot so template hien thi ky tu loi.

8. **Bootstrap moi truong chua duoc xac nhan**
   - `python -m compileall` chay duoc.
   - Nhung import app trong moi truong hien tai fail do thieu package `pydantic_settings` o interpreter dang dung, du dependency da co trong `requirements.txt`.

---

## 3. Kien truc dung can chot

### 3.1 Muc tieu san pham

`pricing-hub` la mot ung dung doc lap de:

- tong hop pricing tu nhieu upstream relay/API server;
- chuan hoa ve mot schema chung;
- cong khai du lieu pricing da sanitize;
- ho tro tra cuu usage logs;
- ho tro resolve API key;
- cung cap admin panel de quan tri server nguon.

### 3.2 Kien truc de xuat cuoi cung

```text
pricing-hub/
|-- main.py
|-- app/
|   |-- app.py
|   |-- config.py
|   |-- deps.py
|   |-- cache.py
|   |-- sanitizer.py
|   |-- schemas.py
|   |-- adapters/
|   |   |-- base.py
|   |   |-- newapi.py
|   |   |-- rixapi.py
|   |   `-- custom.py              # can bo sung
|   |-- services/
|   |   |-- translation.py         # can bo sung
|   |   |-- sync_service.py        # can bo sung
|   |   |-- key_service.py         # can bo sung
|   |   `-- pricing_service.py     # nen tach tu cache/adapters
|   `-- routers/
|       |-- public_*.py
|       |-- api_*.py
|       `-- control/*.py
|-- db/
|   |-- database.py
|   |-- models.py
|   `-- queries/
|-- templates/
|-- static/
`-- data/
    `-- hub.db
```

### 3.3 Luong du lieu chuan

#### Luong pricing

1. Admin tao server trong `/control/servers`.
2. Public hoac admin goi `/api/pricing/{server_id}`.
3. `app/cache.py` kiem tra in-memory cache.
4. Neu miss:
   - doc config server tu SQLite;
   - chon adapter theo `type`;
   - fetch upstream `/api/pricing` va co the them `/api/ratio_config`;
   - normalize ve `NormalizedPricing`;
   - sanitize truoc khi public tra ra;
   - ghi cache vao RAM va `servers.pricing_cache`.

#### Luong logs

1. Nguoi dung nhap API key hoac credentials.
2. Neu co API key:
   - adapter search token;
   - resolve token name;
   - dung admin credential cua server de query logs.
3. Proxy ket qua ve JSON API.

#### Luong key manager

1. Resolve API key ra token metadata.
2. Lay group hien tai.
3. Trong pha hoan thien:
   - load available groups tu pricing/group cache;
   - cho phep update group qua upstream API.

---

## 4. Thiet ke domain hoan chinh

### 4.1 Pricing normalization

Schema hien tai trong `app/schemas.py` la hop ly va nen giu:

- `NormalizedPricing`
- `NormalizedModel`
- `NormalizedGroup`
- `GroupPriceSnapshot`

Diem can chuan hoa them:

1. `pricing_mode`
   - `token`
   - `fixed`
   - `request_scaled`
   - `unknown`

2. Endpoint inference
   - giu heuristic hien tai;
   - bo sung map ro hon cho `embeddings`, `rerank`, `audio`, `image`, `messages`.

3. Tag inference
   - chuan hoa tag sang tap nho, on dinh;
   - tranh giu raw tag hon loan tu upstream.

4. Group pricing
   - phai dam bao neu server co `group_info`, gia theo tung group luon duoc tinh nhat quan;
   - neu khong co `group_info`, fallback ratio = `1.0`.

### 4.2 Translation strategy

Nen chia translation thanh 3 tang:

1. **Tang 1: static fallback**
   - nhu `fallback_english()` hien tai;
   - luon chay duoc, khong phu thuoc AI.

2. **Tang 2: DB cache**
   - doc/ghi tu `translation_cache`;
   - key theo `original_name + server_type`.

3. **Tang 3: AI translation**
   - chi chay neu `AI_ENABLED=true`;
   - khong chay trong hot path cua request cong khai;
   - nen warm cache theo batch khi sync server hoac admin bam refresh.

Nguyen tac:

- Public page khong duoc block lau vi AI.
- Neu AI loi, fallback text van phai dung duoc.

### 4.3 Caching

Nen giu mo hinh cache 2 lop:

1. RAM cache:
   - nhanh;
   - TTL ngan 3-5 phut.

2. SQLite snapshot cache:
   - fallback khi upstream loi;
   - dung cho cold restart.

Nen bo sung:

- truong `last_error`;
- truong `last_success_at`;
- bang `sync_log` phai ghi lai ket qua sync.

### 4.4 Security

Muc toi thieu can chot:

1. `ADMIN_SECRET` bat buoc manh.
2. Khong bao gio expose `auth_token`, `auth_cookie`, full API key ra public JSON.
3. Them rate limit cho:
   - `/api/logs`
   - `/api/keys/resolve`
   - `/control/login`
4. Neu co reverse proxy:
   - chi trust forwarded headers tu proxy noi bo.

### 4.5 Admin

Admin panel can hoan thien theo 3 cum:

1. Server config
   - CRUD day du;
   - test connection;
   - sync now;
   - xem trang thai lan sync cuoi.

2. Translation ops
   - refresh translation cache;
   - xem group nao dang fallback, group nao da AI translate.

3. Sync ops
   - sync all;
   - lich chay dinh ky;
   - xem lich su sync.

---

## 5. Roadmap trien khai khuyen nghi

### P0. On dinh nen tang

Phai lam ngay:

1. Tao `solution.md` moi va bo dung tai lieu cu.
2. Sua encoding cho cac file dang bi loi ky tu.
3. Goi `close_db()` trong shutdown lifecycle.
4. Chuan hoa bootstrap environment:
   - venv
   - `pip install -r requirements.txt`
   - script run dev/prod
5. Seed it nhat 1 server mau de app khong trong hoan toan khi bat lan dau.

### P1. Hoan thien core feature

1. Tach `pricing_service` ra khoi `cache.py`.
2. Bo sung `custom.py` adapter.
3. Ghi `sync_log` o moi lan sync thanh cong/that bai.
4. Them `sync all`.
5. Lam cho `/logs` dung normalized pricing cache de estimate cost chinh xac hon.

### P2. Hoan thien translation va key manager

1. Tao `services/translation.py`.
2. Noi `translation_cache` vao sync flow.
3. Them endpoint:
   - list groups cho key/server;
   - update key group.
4. Nang cap UI `/keys` de doi group.

### P3. Van hanh production

1. Them logging chuan JSON hoac structured log.
2. Them health checks:
   - app health
   - db health
   - upstream reachability summary
3. Them systemd service va Nginx reverse proxy.
4. Them backup DB dinh ky.

---

## 6. Ke hoach trien khai thuc te theo pha

### Phase 1: chay on dinh duoc

Muc tieu:

- app khoi dong sach;
- login admin duoc;
- tao server duoc;
- sync pricing duoc;
- `/pricing` xem duoc du lieu.

Deliverables:

- fixed lifecycle;
- fixed environment docs;
- fixed encoding;
- seed du lieu mau.

### Phase 2: usable cho nguoi dung that

Muc tieu:

- logs tra cuu on dinh;
- key resolve on dinh;
- group label sach;
- sync co lich su.

Deliverables:

- sync log;
- better cost estimation;
- translation cache flow;
- improved error handling.

### Phase 3: usable cho van hanh

Muc tieu:

- admin biet server nao loi;
- co the refresh du lieu theo lo;
- co backup/restore toi thieu.

Deliverables:

- sync dashboard;
- bulk actions;
- backup instructions;
- deployment scripts.

---

## 7. Khuyen nghi trien khai cho Oracle Free Tier

### 7.1 Kien truc runtime

- 1 process `uvicorn`
- 1 file SQLite
- static file serve truc tiep tu FastAPI hoac Nginx
- khong dung Redis o giai doan nay
- khong dung Celery/RQ o giai doan dau

### 7.2 Uoc tinh tai nguyen

- FastAPI + Uvicorn: khoang 50-90 MB
- SQLite + cache nho: khoang 20-60 MB
- Template + static CDN: gan nhu khong dang ke

Tong the van phu hop voi VPS 1 GB RAM neu khong mo rong vo toi va.

### 7.3 Deployment toi thieu

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

Production nen chay bang:

```bash
uvicorn app.app:create_app --factory --host 0.0.0.0 --port 8080
```

Sau do dat Nginx phia truoc cho TLS va cache static.

---

## 8. Definition of Done cho ban hoan thien

Co the coi `pricing-hub` hoan thien phien ban 1 khi dat du:

1. Admin tao/sua/xoa server va sync duoc.
2. Public pricing hoat dong voi it nhat `newapi` va `rixapi`.
3. Group label khong lo thong tin noi bo nhay cam.
4. Logs query hoat dong bang API key hoac credentials.
5. Key resolve hoat dong on dinh.
6. Co sync log va fallback cache khi upstream loi.
7. App restart khong lam mat snapshot pricing gan nhat.
8. Co huong dan deploy ro rang cho VPS 1 GB RAM.

---

## 9. Ket luan cuoi

Huong di dung cua du an khong phai la quay lai Next.js, ma la **hoan thien codebase FastAPI hien tai**.

Noi ngan gon:

- huong kien truc hien tai la dung;
- khung he thong da co khoang 60-70% phan xuong song;
- cac phan con thieu chu yeu la hoan thien service layer, translation pipeline, sync/audit, key management va hardening production.

Neu tiep tuc trien khai, thu tu tot nhat la:

1. on dinh nen tang;
2. hoan thien pricing/logs/keys;
3. hoan thien admin ops;
4. chot deployment production.
