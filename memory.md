# Shupremium Stack Memory

## Canonical workspace

- Working repo root: `D:\Projects\Code\shupremium-stack`
- Canonical memory file moving forward: `D:\Projects\Code\shupremium-stack\memory.md`
- Legacy docs copied from old workspace still exist under `docs/`, including `docs/memory.md`
- Treat this root `memory.md` as the current source of truth for future conversations

## Git status

- Git root has been initialized in this monorepo
- Current branch: `main`
- Current remote:
  - `origin = https://github.com/shurikenji/fs.git`
- If remote changes later, update this file

## Monorepo architecture

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

### App mapping

- `apps/portal`
  - imported from old `Business/pricing-hub`
  - public pricing, balance, keys, logs site
  - Python / FastAPI
- `apps/platform-control`
  - imported from old `Business/platform-control`
  - control plane and admin shell
  - Python / FastAPI
- `apps/shopbot`
  - imported from old `Business/shopbot`
  - bot + embedded admin panel
  - Python
- `services/proxy-gateway`
  - imported from old `Business/proxy-gateway`
  - includes:
    - `proxy-service`
    - `proxy-operator`
    - `admin-panel`
  - Node.js
- `services/balance-checker`
  - imported from old `Business/balance-checker`
  - legacy service

### Local tooling folders in repo root

- `.claude`
- `.gitnexus`
- `AGENTS.md`
- `CLAUDE.md`

These are local/dev tooling artifacts. Do not deploy them to VPS runtime paths.

## Important repo hygiene

The monorepo was created as source-only. Runtime state must stay outside Git:

- `.env`
- `.venv`
- `node_modules`
- `data/`
- SQLite files
- logs
- tar/zip deploy artifacts

Nested `.git` repos from old subprojects were intentionally removed from the monorepo tree.

## Ops scaffolding already created

These files already exist and are the starting point for production deploy standardization:

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

These scripts are scaffolded, not fully production-hardened yet. They still need review before first real cutover.

## Production topology

### ARM VPS

- Host: `ubuntu@instance-20260114-0319`
- Verified hostname: `instance-20260114-0319`
- Verified OS: `Ubuntu 22.04.5 LTS`
- Verified kernel/arch: `Linux 6.8.0-1041-oracle`, `aarch64`
- `/etc/shupremium-host-role` exists and currently contains `arm`
- This machine currently runs:
  - `portal`
  - `platform-control`
  - `proxy-gateway`
- Current live code paths are now mixed:
  - `portal`: `/srv/shupremium-stack/current/portal`
  - `platform-control`: `/srv/shupremium-stack/current/platform-control`
  - `proxy-gateway`: `/home/ubuntu/proxy-gateway`
- First successful monorepo cutover completed for `portal` on `2026-04-05`
- First successful monorepo cutover completed for `platform-control` on `2026-04-05`
- First portal release path:
  - `/srv/shupremium-stack/releases/20260405-065120/portal`
- First platform-control release path:
  - `/srv/shupremium-stack/releases/20260405-071018/platform-control`
- Legacy portal path still exists as rollback safety copy:
  - `/home/ubuntu/portal`
- Legacy platform-control path still exists as rollback safety copy:
  - `/home/ubuntu/platform-control`
- `/srv/shupremium-stack` is now initialized on ARM VPS:
  - `repo/`
  - `releases/`
  - `current/`
  - `shared/portal`
  - `shared/platform-control`
  - `shared/proxy-gateway`
  - `shared/shopbot`
- `/home/ubuntu` still contains many legacy deploy artifacts and backups:
  - `deploy/`
  - `deploy-20260404*`
  - `portal-backup-20260404-*`
  - `platform-control-backup-20260403`
  - multiple tar.gz / zip deploy archives

### Shopbot VPS

- Separate VPS from the ARM machine
- Intended runtime remains `shopbot`
- Verified host: `ubuntu@instance-20260306-0442`
- Verified OS: `Ubuntu 22.04.5 LTS`
- Verified kernel/arch: `Linux 6.8.0-1044-oracle`, `x86_64`
- `/etc/shupremium-host-role` is currently missing on this machine
- Verified candidate code paths:
  - `/home/ubuntu/shopbot`
  - `/home/ubuntu/shopbot-v4-staging/shopbot`
- Verified runtime:
  - `shopbot.service` is enabled and active
  - `WorkingDirectory=/home/ubuntu/shopbot`
  - `ExecStart=/home/ubuntu/shopbot/.venv/bin/python -m bot.main`
  - main PID observed: `1512545`
  - listens on `0.0.0.0:8080`
- Verified admin HTTP behavior in logs:
  - `/` redirects with `303`
  - `/login-shopbot-admin` returns `200`
- Verified on `2026-04-05`: `/srv/shupremium-stack/current/shopbot` and `/srv/shupremium-stack/shared/shopbot` are missing
- Existing docs were correct: `shopbot` currently runs under `systemd`, not PM2

## Current live runtime on ARM VPS

### PM2 processes confirmed running

From the last verified PM2 list on ARM VPS:

- `portal`
- `platform-control`
- `proxy-operator`
- `proxy-gpt1` x2
- `proxy-gpt2` x2
- `proxy-gpt3` x2
- `proxy-gpt4` x2
- `proxy-gpt5` x2
- `proxy-sv1` x2
- `proxy-sv2` x2

### PM2 process present but currently not relied on

- `admin-panel`
  - present in PM2 list
  - status verified as `stopped` again on `2026-04-05`
  - do not assume it is a required live dependency right now

### Ports currently in use on ARM VPS

- Verified on `2026-04-05`:
  - `portal`: `127.0.0.1:8080`
  - `platform-control`: `0.0.0.0:8090`
  - `proxy-operator`: `0.0.0.0:8091`
- proxy-service clusters:
  - `proxy-gpt1`: `0.0.0.0:3001`
  - `proxy-gpt2`: `0.0.0.0:3002`
  - `proxy-gpt3`: `0.0.0.0:3003`
  - `proxy-gpt4`: `0.0.0.0:3004`
  - `proxy-gpt5`: `0.0.0.0:3005`
  - `proxy-sv1`: `0.0.0.0:4001`
  - `proxy-sv2`: `0.0.0.0:4002`

### Public domains currently mapped through gateway

- `https://gpt1.shupremium.com`
- `https://gpt2.shupremium.com`
- `https://gpt4.shupremium.com`
- `https://gpt5.shupremium.com`
- `https://sv1.shupremium.com`
- Main public site:
  - `https://shupremium.com`

### Live tree details verified on ARM VPS

- `portal` current live tree still contains local/dev artifacts that should not survive monorepo cutover:
  - `.agent/`
  - `.claude/`
  - `.git/`
- `platform-control` current live tree contains:
  - `.env`
  - `.venv/`
  - `data/platform_control.db`
  - `data/pc-data-backup/`
- `proxy-gateway` current live tree contains:
  - `admin-panel/data/`
  - `admin-panel/node_modules/`
  - `proxy-operator/.env`
  - `proxy-operator/node_modules/`
  - backup folders under `proxy-gateway/backups/`

### ARM VPS verification note

- A second short `ss -ltnp` run on `2026-04-05` successfully captured the live port bindings above
- `portal` is loopback-only right now, while `platform-control`, `proxy-operator`, and proxy-service ports are bound on `0.0.0.0`
- This means the public edge for `portal` is still expected to sit in front of localhost `8080`, while `platform-control` and proxy services are currently reachable on host interfaces unless external firewall/nginx rules restrict them

## Current production app/runtime notes

### portal

- Runtime: PM2
- Current active release path:
  - `/srv/shupremium-stack/current/portal`
- Current resolved release path:
  - `/srv/shupremium-stack/releases/20260405-065120/portal`
- PM2 process name stayed the same after cutover:
  - `portal`
- PM2 currently runs `portal` via:
  - script path `/srv/shupremium-stack/shared/portal/venv/bin/python`
  - script args `/srv/shupremium-stack/current/portal/main.py`
  - interpreter `none`
  - exec cwd `/srv/shupremium-stack/current/portal`
- Legacy path `/home/ubuntu/portal` is still present as rollback safety copy
- Old legacy tree still includes `.git`, `.agent`, `.claude`
- Health endpoint: `/health`
- Public root `/` and `/pricing` confirmed working after monorepo cutover hotfix
- Production must run with:
  - `APP_DEBUG=false`
- Important env coupling:
  - `CONTROL_PLANE_TOKEN` in `portal/.env` must match `platform-control/.env`
  - `PRICING_ADMIN_TOKEN` must stay on the production random token, never local token

### platform-control

- Runtime: PM2
- Current active release path:
  - `/srv/shupremium-stack/current/platform-control`
- Current resolved release path:
  - `/srv/shupremium-stack/releases/20260405-071018/platform-control`
- PM2 process name stayed the same after cutover:
  - `platform-control`
- PM2 currently runs `platform-control` via:
  - script path `/srv/shupremium-stack/shared/platform-control/venv/bin/python`
  - script args `/srv/shupremium-stack/current/platform-control/main.py`
  - interpreter `none`
  - exec cwd `/srv/shupremium-stack/current/platform-control`
- Legacy path `/home/ubuntu/platform-control` is still present as rollback safety copy
- Verified legacy live tree includes `.venv/` and local SQLite data under `data/`
- Live port: `8090`
- Portal depends on it during startup and admin sync

### proxy-gateway

- **Migrated on `2026-04-07`** from `/home/ubuntu/proxy-gateway` to monorepo layout
- Current active release path:
  - `/srv/shupremium-stack/current/proxy-gateway`
- Current resolved release path:
  - `/srv/shupremium-stack/releases/20260406-060854/proxy-gateway`
- Runtime split:
  - `proxy-service`: PM2 ecosystem (cluster mode, 2 instances each)
  - `proxy-operator`: PM2 process (fork mode)
  - `admin-panel`: legacy/optional, not migrated
- All proxy apps now run from new path (`pm_cwd=/srv/shupremium-stack/releases/...`)
- Legacy path `/home/ubuntu/proxy-gateway` is still present as rollback safety copy

### shopbot

- **Migrated on `2026-04-07`** from `/home/ubuntu/shopbot` to monorepo layout
- Current active release path:
  - `/srv/shupremium-stack/current/shopbot`
- Runtime: `systemd` (`shopbot.service`)
  - `WorkingDirectory=/srv/shupremium-stack/current/shopbot`
  - `ExecStart=/srv/shupremium-stack/shared/shopbot/venv/bin/python -m bot.main`
- Contains bot loop + admin server on `0.0.0.0:8080` in same process
- DB path: `/srv/shupremium-stack/shared/shopbot/data/shopbot.db` (SQLite WAL)
- Legacy path `/home/ubuntu/shopbot` still present as rollback safety copy
- Cutover backup at `/home/ubuntu/shopbot-cutover-backups/20260406-210810/`
- Safe `.env` key inventory observed on Shopbot VPS includes:
  - `ADMIN_LAUNCH_SECRET`
  - `ADMIN_LAUNCH_TTL_SECONDS`
  - `ADMIN_PORT`
  - `ADMIN_SECRET_KEY`
  - `ADMIN_TELEGRAM_IDS`
  - `BOT_TOKEN`
  - `DB_PATH`
  - `MB_ACCOUNT_NAME`
  - `MB_ACCOUNT_NO`
  - `MB_API_KEY`
  - `MB_API_URL`
  - `MB_BANK_ID`
  - `MB_PASSWORD`
  - `MB_USERNAME`
  - `ORDER_EXPIRE_MINUTES`
  - `PLATFORM_ADMIN_URL`
  - `POLL_INTERVAL`
  - `PORTAL_INTERNAL_TOKEN`
  - `PORTAL_SESSION_SECRET`

## VPS command capture note

The first Shopbot command pack produced noisy output mainly because `find` walked into `.git/objects`.
When re-running tree discovery on either VPS, prefer pruning `.git`, `.venv`, and `node_modules` unless those directories are the thing being audited.
- The cleaner command was already tested on Shopbot VPS and produced the expected top-level tree, aside from a harmless `find` warning about option ordering
- Preferred cleaner form going forward:
  - `find /path -mindepth 1 -maxdepth 3 \\( -path "*/.git" -o -path "*/.venv" -o -path "*/node_modules" \\) -prune -o -print | sort | sed -n "1,220p"`

## Current pricing source reality

The admin/source config in `docs/server.md` contains the current upstream/public source mapping. The sensitive values exist there, but operationally the important non-secret facts are:

- `gpt1`
  - public base: `https://gpt1.shupremium.com`
  - upstream base: `https://api.aabao.top`
  - pricing path: `/api/pricing`
  - quota multiple: `0.3`
- `gpt2`
  - public base: `https://gpt2.shupremium.com`
  - upstream base: `https://api.996444.cn`
  - pricing path: `/api/pricing`
  - quota multiple: `0.5`
- `gpt4`
  - public base: `https://gpt4.shupremium.com`
  - upstream base: `https://api.kksj.org`
  - pricing path: `/api/pricing`
  - quota multiple: `0.9`
- `gpt5`
  - public base: `https://gpt5.shupremium.com`
  - upstream base: `https://new.xjai.cc`
  - pricing path: `/api/pricing`
  - quota multiple: `1.0`
- `sv1`
  - public base: `https://sv1.shupremium.com`
  - upstream base: `https://yunwu.ai`
  - pricing path: `api/pricing_new`
  - quota multiple: `1.0`

## Important parser/display fact for pricing

Do not trust the admin-configured source type alone.

Live payload classification verified earlier:

- `gpt2` behaves like `rixapi` / inline group pricing
- `gpt1`, `gpt4`, `gpt5`, `sv1` all behave like catalog-list / Yunwu-style payloads by actual JSON shape

This matters for future pricing work:

- parser selection should be based on real payload shape first
- not only on the configured "type" string in admin

## Yunwu pricing status to remember

Earlier production work established:

- public pricing uses cache/snapshot, not direct upstream fetch per user request
- `quota_multiple` is still mandatory and must remain unchanged in public output
- Yunwu-related display patch currently supports:
  - `billing_label`
  - `billing_unit`
  - `price_multiplier`
  - explicit endpoint path + method for the user

Current architecture is still pragmatic, not yet the final clean architecture.
Long-term desired direction remains:

- raw parser
- pricing engine
- public presenter
- rule registry

## Production incidents already seen

These are important and must stay in memory:

### 1. `.env` overwrite incident on `portal`

Production `portal/.env` was overwritten by local deploy artifacts at least once.

The bad values observed on production were:

- `APP_DEBUG=true`
- `CONTROL_PLANE_TOKEN=local-control-plane-token`
- `PRICING_ADMIN_TOKEN=local-pricing-admin-token`

Symptoms:

- `portal` started in reload/watch mode
- startup call to `platform-control` failed with `401 Unauthorized`

Fix that worked:

- restore production values in `/home/ubuntu/portal/.env`
- ensure `CONTROL_PLANE_TOKEN` matches `platform-control/.env`
- set `APP_DEBUG=false`
- `pm2 restart portal --update-env`

### 2. `hub.db` corruption incident on `portal`

`/home/ubuntu/portal/data/hub.db` became malformed after bad deploy/copy operations.

Symptoms:

- `sqlite3.DatabaseError: database disk image is malformed`
- startup/shutdown errors in portal logs
- some routes returned `500`

Recovery that worked:

- stop `portal`
- restore `hub.db` from backup
- restart `portal`

Known portal backups that existed on the server during recovery:

- `/home/ubuntu/portal-backup-20260404-061525`
- `/home/ubuntu/portal-backup-20260404-080748`

## Current production safety rules

Until the live stack is fully migrated to the new monorepo release layout, do NOT do any of the following on ARM VPS:

- do not copy whole local folders over `/home/ubuntu/portal`
- do not copy `.env`
- do not copy `data/`
- do not copy `.venv`
- do not deploy by tarball unless absolutely necessary
- do not assume `rsync` exists unless you install it explicitly

### Safe hotfix pattern for current live ARM VPS

If you need a quick production patch before full monorepo migration:

- upload only the changed source files
- copy only those files into the live app path
- leave `.env`, `data`, `.venv` untouched
- restart the affected PM2 process with `--update-env`

For `portal`, verify immediately after restart:

- `/health`
- `/`
- `/pricing`

## Portal cutover notes from `2026-04-05`

### Successful first cutover state

- Backup created before migration:
  - `/home/ubuntu/portal-cutover-backups/20260405-063502`
- Shared runtime prepared at:
  - `/srv/shupremium-stack/shared/portal/.env`
  - `/srv/shupremium-stack/shared/portal/data/`
  - `/srv/shupremium-stack/shared/portal/venv/`
- Final working PM2 start command for portal was:
  - `pm2 start /srv/shupremium-stack/shared/portal/venv/bin/python --name portal --interpreter none --cwd /srv/shupremium-stack/current/portal -- /srv/shupremium-stack/current/portal/main.py`

### Important cutover failures that happened

- First `deploy-portal.sh` run failed smoke checks because PM2 Python startup in `ops/deploy/lib.sh` used the wrong launch mode for this VPS/PM2 combination
- Working launch mode on this ARM VPS is:
  - start the real Python binary
  - pass `--interpreter none`
  - pass `main.py` as script args
- Until `ops/deploy/lib.sh` is updated on the VPS copy too, do not trust `deploy-portal.sh` to restart `portal` correctly

- After PM2 was fixed manually, `/pricing` still returned `500`
- Root cause was an application regression in `apps/portal/app/translation_service.py`
- Exact bug:
  - `_resolve_short_text_translations()` called `_sanitize_short_label_text(...)`
  - correct callable is `sanitize_short_label_text(...)`
- Hotfix was applied directly on ARM VPS in:
  - `/srv/shupremium-stack/current/portal/app/translation_service.py`
  - `/srv/shupremium-stack/repo/apps/portal/app/translation_service.py`
- After that hotfix, all three checks succeeded:
  - `/health`
  - `/`
  - `/pricing`

## Platform-control cutover notes from `2026-04-05`

### Successful first cutover state

- Backup created before migration:
  - `/home/ubuntu/platform-control-cutover-backups/20260405-070928`
- Shared runtime prepared at:
  - `/srv/shupremium-stack/shared/platform-control/.env`
  - `/srv/shupremium-stack/shared/platform-control/data/`
  - `/srv/shupremium-stack/shared/platform-control/venv/`
- Final working PM2 start command for platform-control was:
  - `pm2 start /srv/shupremium-stack/shared/platform-control/venv/bin/python --name platform-control --interpreter none --cwd /srv/shupremium-stack/current/platform-control -- /srv/shupremium-stack/current/platform-control/main.py`
- Final verification after cutover:
  - `/` returned `200`
  - `/control` returned `303`
  - process bound `0.0.0.0:8090`

### Important cutover behavior observed

- `deploy-platform-control.sh` switched the release symlink correctly, but its smoke check ran before the app finished binding `8090`
- Manual cutover with a short wait loop succeeded without any code hotfix
- Existing `401/500` lines in old platform-control logs were noise from admin/pricing calls to portal and not startup failures for the monorepo release

## Planned target deploy model

Target layout on VPS after migration:

```text
/srv/shupremium-stack/
  repo/
  releases/
  current/
  shared/
```

Where:

- `repo/` = monorepo clone
- `releases/` = immutable deploy outputs by timestamp
- `current/` = symlink to active release per app
- `shared/` = `.env`, `data`, `venv`

This migration is partially complete.

- `portal` is migrated on ARM VPS
- `platform-control` is migrated on ARM VPS
- `proxy-gateway` is migrated on ARM VPS (operator + all proxy apps, `2026-04-07`)
- `shopbot` is migrated on Shopbot VPS (`2026-04-07`)

## Deploy strategy that should be used going forward

- Use Git as the primary deploy path
- Deploy per app, not entire stack
- Keep two host roles:
  - `arm`
  - `shopbot`
- Use `ops/deploy/*` scripts as the base
- Review and harden scripts before first real production use

## ARM VPS first cutover checklist for `portal`

This is the recommended first real migration target.
Do `portal` first on ARM VPS before touching `platform-control` or `proxy-gateway`.

### 1. Local preflight

- Ensure local branch is clean enough to reason about:
  - `git status --short`
- Ensure the intended commit is already pushed:
  - `git log --oneline -n 5`
  - `git push`
- Keep `memory.md` updated before touching production.

### 2. ARM VPS pre-cutover snapshot

Run these before any migration so future sessions have exact state instead of guesses:

```bash
ssh ubuntu@instance-20260114-0319 '
set -e
echo "=== host ==="
hostname
uname -a
cat /etc/os-release | sed -n "1,8p"
echo "=== role ==="
cat /etc/shupremium-host-role 2>/dev/null || echo "(missing)"
echo "=== home ==="
ls -la /home/ubuntu
echo "=== live app dirs ==="
for d in /home/ubuntu/portal /home/ubuntu/platform-control /home/ubuntu/proxy-gateway; do
  echo "--- $d"
  if [ -d "$d" ]; then
    find "$d" -maxdepth 2 -mindepth 1 | sort | sed -n "1,200p"
  else
    echo "missing"
  fi
done
echo "=== pm2 ==="
pm2 ls || true
echo "=== ports ==="
ss -ltnp | grep -E ":8080|:8090|:8091|:3001|:3002|:3003|:3004|:3005|:4001|:4002" || true
'
```

### 3. Back up the current `portal` runtime before migration

Do not skip this on the first cutover:

```bash
ssh ubuntu@instance-20260114-0319 '
set -e
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p /home/ubuntu/portal-cutover-backups/$TS
cp /home/ubuntu/portal/.env /home/ubuntu/portal-cutover-backups/$TS/portal.env
cp /home/ubuntu/portal/data/hub.db /home/ubuntu/portal-cutover-backups/$TS/hub.db
pm2 save || true
echo "$TS"
'
```

### 4. Bootstrap the monorepo runtime root on ARM VPS

This matches the current deploy scripts:

```bash
ssh ubuntu@instance-20260114-0319 '
set -e
sudo mkdir -p /srv/shupremium-stack
sudo chown -R $USER:$USER /srv/shupremium-stack
if [ ! -d /srv/shupremium-stack/repo/.git ]; then
  git clone https://github.com/shurikenji/fs.git /srv/shupremium-stack/repo
else
  cd /srv/shupremium-stack/repo
  git fetch origin
  git checkout main
  git pull --ff-only origin main
fi
echo arm | sudo tee /etc/shupremium-host-role
cd /srv/shupremium-stack/repo
bash ops/deploy/bootstrap-host.sh
'
```

### 5. Prepare shared runtime for `portal`

Current `prepare_python_release` expects:

- `/srv/shupremium-stack/shared/portal/.env`
- `/srv/shupremium-stack/shared/portal/data/`
- optional `/srv/shupremium-stack/shared/portal/venv`

The deploy script will create the shared venv automatically if it does not exist.

```bash
ssh ubuntu@instance-20260114-0319 '
set -e
mkdir -p /srv/shupremium-stack/shared/portal/data
cp /home/ubuntu/portal/.env /srv/shupremium-stack/shared/portal/.env
cp -a /home/ubuntu/portal/data/. /srv/shupremium-stack/shared/portal/data/
test -f /srv/shupremium-stack/shared/portal/.env
test -d /srv/shupremium-stack/shared/portal/data
'
```

### 6. Optional safety checks before first deploy

These reduce the chance of repeating the old `.env` and SQLite incidents:

```bash
ssh ubuntu@instance-20260114-0319 '
set -e
echo "=== portal env keys ==="
sed -n "s/^\\([A-Z0-9_][A-Z0-9_]*\\)=.*/\\1/p" /srv/shupremium-stack/shared/portal/.env | sort
echo "=== critical env keys present ==="
grep -E "^(APP_DEBUG|CONTROL_PLANE_TOKEN|PRICING_ADMIN_TOKEN)=" /srv/shupremium-stack/shared/portal/.env | sed -E "s/=.*/=<redacted>/"
echo "=== sqlite quick check ==="
sqlite3 /srv/shupremium-stack/shared/portal/data/hub.db \"PRAGMA integrity_check;\"
'
```

Expected result:

- `APP_DEBUG=<redacted>` exists and production file should still represent `false`
- `CONTROL_PLANE_TOKEN` and `PRICING_ADMIN_TOKEN` keys exist
- SQLite integrity check returns `ok`

### 7. First real deploy of `portal`

```bash
ssh ubuntu@instance-20260114-0319 '
set -e
cd /srv/shupremium-stack/repo
git fetch origin
git checkout main
git pull --ff-only origin main
bash ops/deploy/deploy-portal.sh main
'
```

### 8. Immediate post-cutover verification

```bash
ssh ubuntu@instance-20260114-0319 '
set -e
echo "=== current portal release ==="
readlink -f /srv/shupremium-stack/current/portal
echo "=== symlinked runtime state ==="
ls -la /srv/shupremium-stack/current/portal | sed -n "1,80p"
echo "=== pm2 portal ==="
pm2 describe portal | sed -n "1,160p"
echo "=== health checks ==="
curl -I http://127.0.0.1:8080/health
curl -I http://127.0.0.1:8080/
curl -I http://127.0.0.1:8080/pricing
'
```

Portal should not be considered migrated until all three URLs succeed and PM2 shows the app online.

Observed during the real first cutover on `2026-04-05`:

- `curl -I` was misleading because these routes allow `GET` but not `HEAD`
- use `curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/...` for final verification
- if `deploy-portal.sh` leaves PM2 pointing at the old path or fails to bind `8080`, manually restart using the shared Python binary plus `--interpreter none`

### 9. Fast rollback path if cutover fails

```bash
ssh ubuntu@instance-20260114-0319 '
set -e
cd /srv/shupremium-stack/repo
bash ops/deploy/rollback-app.sh portal
'
```

If rollback also looks wrong, fall back to the old live path `/home/ubuntu/portal` and the backup made in step 3.

## Live VPS verification command packs

Use these commands whenever the real live state on ARM VPS or Shopbot VPS needs to be re-verified.
Prefer pasting the outputs back into this file after a production session.

### ARM VPS command pack

#### Host and filesystem overview

```bash
ssh ubuntu@instance-20260114-0319 '
set -e
hostname
uname -a
cat /etc/os-release | sed -n "1,8p"
cat /etc/shupremium-host-role 2>/dev/null || echo "(missing host role)"
ls -la /home/ubuntu
ls -la /srv/shupremium-stack 2>/dev/null || true
'
```

#### Current live tree for old paths

```bash
ssh ubuntu@instance-20260114-0319 '
set -e
for d in /home/ubuntu/portal /home/ubuntu/platform-control /home/ubuntu/proxy-gateway; do
  echo "=== $d ==="
  if [ -d "$d" ]; then
    find "$d" -maxdepth 3 -mindepth 1 | sort | sed -n "1,240p"
  else
    echo "missing"
  fi
done
'
```

#### Current monorepo release tree if migration has started

```bash
ssh ubuntu@instance-20260114-0319 '
set -e
find /srv/shupremium-stack -maxdepth 3 -mindepth 1 | sort | sed -n "1,300p"
for d in /srv/shupremium-stack/current/portal /srv/shupremium-stack/current/platform-control /srv/shupremium-stack/current/proxy-gateway; do
  echo "=== $d ==="
  [ -e "$d" ] && readlink -f "$d" || echo "missing"
done
'
```

#### PM2, ports, health

```bash
ssh ubuntu@instance-20260114-0319 '
set -e
pm2 ls || true
pm2 describe portal | sed -n "1,160p" || true
pm2 describe platform-control | sed -n "1,160p" || true
pm2 describe proxy-operator | sed -n "1,160p" || true
ss -ltnp | grep -E ":8080|:8090|:8091|:3001|:3002|:3003|:3004|:3005|:4001|:4002" || true
curl -I http://127.0.0.1:8080/health || true
curl -I http://127.0.0.1:8090/ || true
curl -I http://127.0.0.1:8091/health || true
'
```

#### Safe env key inventory without leaking values

```bash
ssh ubuntu@instance-20260114-0319 '
set -e
for f in \
  /home/ubuntu/portal/.env \
  /home/ubuntu/platform-control/.env \
  /home/ubuntu/proxy-gateway/proxy-operator/.env \
  /home/ubuntu/proxy-gateway/admin-panel/.env \
  /srv/shupremium-stack/shared/portal/.env \
  /srv/shupremium-stack/shared/platform-control/.env \
  /srv/shupremium-stack/shared/proxy-gateway/proxy-operator/.env \
  /srv/shupremium-stack/shared/proxy-gateway/admin-panel/.env
do
  echo "=== $f ==="
  if [ -f "$f" ]; then
    sed -n "s/^\\([A-Z0-9_][A-Z0-9_]*\\)=.*/\\1/p" "$f" | sort | sed -n "1,120p"
  else
    echo "missing"
  fi
done
'
```

### Shopbot VPS command pack

Use this on the separate Shopbot VPS once the exact hostname/IP is re-confirmed.

#### Host, paths, and repo/runtime discovery

```bash
ssh <shopbot-vps> '
set -e
hostname
uname -a
cat /etc/os-release | sed -n "1,8p"
cat /etc/shupremium-host-role 2>/dev/null || echo "(missing host role)"
find /home /srv -maxdepth 3 \\( -type d -name shopbot -o -type d -name shupremium-stack \\) 2>/dev/null | sort | sed -n "1,120p"
'
```

#### systemd and working directory discovery

```bash
ssh <shopbot-vps> '
set -e
systemctl status shopbot --no-pager || true
systemctl cat shopbot || true
systemctl show shopbot -p FragmentPath -p User -p Group -p WorkingDirectory -p ExecStart || true
'
```

#### Process, ports, and filesystem snapshot

```bash
ssh <shopbot-vps> '
set -e
ps -ef | grep -E "python -m bot.main|shopbot" | grep -v grep || true
ss -ltnp | grep -E "python|uvicorn|gunicorn|shopbot" || true
for d in /home/*/shopbot /srv/shupremium-stack/current/shopbot /srv/shupremium-stack/shared/shopbot; do
  echo "=== $d ==="
  [ -e "$d" ] && find "$d" -maxdepth 3 -mindepth 1 | sort | sed -n "1,200p" || echo "missing"
done
'
```

#### Safe env key inventory for Shopbot

```bash
ssh <shopbot-vps> '
set -e
for f in \
  /home/*/shopbot/.env \
  /srv/shupremium-stack/shared/shopbot/.env
do
  for real in $f; do
    echo "=== $real ==="
    [ -f "$real" ] && sed -n "s/^\\([A-Z0-9_][A-Z0-9_]*\\)=.*/\\1/p" "$real" | sort | sed -n "1,120p" || echo "missing"
  done
done
'
```

### What to write back into `memory.md` after a VPS verification session

When any of the command packs above are run, update this file with:

- exact hostname and host role
- exact live code paths
- whether `/srv/shupremium-stack/...` exists yet
- exact PM2 process names on ARM VPS
- exact `shopbot` systemd unit path, working directory, and exec command
- any confirmed health URLs and bound localhost ports
- any newly observed backup paths for `.env` or SQLite files

## What still needs work

### Monorepo / ops

- update `ops/deploy/lib.sh` on the VPS and in Git so `restart_pm2_python_app()` uses the working PM2 launch mode
- re-validate `deploy-portal.sh` after the PM2 launch hotfix is present in the deployed repo copy
- validate `platform-control` cutover next, using the same PM2 launch pattern
- validate `shopbot` systemd deployment path in the new layout

### Production cutover

- ARM VPS:
  - repo cloned
  - `/etc/shupremium-host-role` created
  - `portal` shared runtime prepared
  - `portal` migrated successfully
- Still remaining:
  - migrate `platform-control`
  - migrate `proxy-gateway`
  - bootstrap and migrate `shopbot` VPS layout

### Pricing architecture

- current pricing changes are functional but still not fully refactored
- future direction:
  - parser layer
  - engine layer
  - presenter layer
  - clearer registry-driven rules

## Best starting point for next conversation

Start in:

- `D:\Projects\Code\shupremium-stack`

Then explicitly say which next step you want:

- review deploy scripts
- prepare GitHub push
- harden ARM VPS deployment
- harden shopbot VPS deployment
- migrate one app to `/srv/shupremium-stack`
- continue pricing engine refactor

## 2026-04-06 Proxy Control Failure Notes

### Current repo and deployment state

- Local repo path: `D:\Projects\Code\shupremium-stack`
- ARM VPS repo path: `/srv/shupremium-stack/repo`
- `platform-control` was deployed successfully on ARM VPS and is reachable through `admin.shupremium.com`
- `proxy-operator` was deployed multiple times and currently runs from:
  - script path: `/srv/shupremium-stack/current/proxy-gateway/proxy-operator/src/server.js`
  - exec cwd: `/srv/shupremium-stack/current/proxy-gateway/proxy-operator`
- wildcard certificate is confirmed usable on ARM VPS:
  - cert name: `shupremium-wildcard`
  - cert path: `/etc/letsencrypt/live/shupremium-wildcard`
  - operator `/health` reports `wildcard_cert.available = true`

### User-facing symptom

- In `platform-control`, creating or re-enabling proxy `sv3` fails with:
  - `Thất bại fetch failed (step: health_probe) {'proxy_id': 'sv3', 'domain': 'sv3.shupremium.com', 'port': 4003, 'attempt': 15}`
- This happens during `Lưu proxy + apply`

### Intended target state for the failing proxy

- proxy id / name: `sv3`
- domain: `sv3.shupremium.com`
- port: `4003`
- `Source ID` intentionally left blank
- expected runtime behavior:
  - PM2 app name `proxy-sv3`
  - nginx file `/etc/nginx/sites-available/proxy-managed-sv3.conf`
  - HTTPS enabled immediately via wildcard cert
  - internal health on `http://127.0.0.1:4003/_internal/health`

### What has already been fixed in code

- `platform-control` proxy CRUD was changed to mimic old `admin-panel` behavior:
  - save/delete/toggle proxy now auto-apply runtime
  - rollback DB on apply failure
  - `Source ID` is optional
- `proxy-operator` was hardened to:
  - use privileged wildcard cert probing
  - expose richer `/health`
  - include structured error metadata: `step`, `details`
  - rollback nginx/ecosystem/PM2 state on failure
  - delete stale PM2 apps on rollback

### Commits already pushed and tested during this debugging session

- `5f13342`:
  - restore transactional proxy runtime control in `platform-control`
  - first major hardening pass for `proxy-operator`
- `574f47d`:
  - retry `health_probe` instead of failing immediately
- `c33ace9`:
  - handle stale PM2 proxy entries during runtime apply
- `5995d7d`:
  - replace `startOrReload` style PM2 syncing with a more explicit strategy:
    - reload existing apps
    - start missing apps
    - restart stale/offline apps

### Current confirmed facts from ARM VPS

- Operator health endpoint is healthy after latest deploy:
  - `status = ok`
  - `root_domain = shupremium.com`
  - `proxy_service_path = /srv/shupremium-stack/current/proxy-gateway/proxy-service`
  - `wildcard_cert.available = true`
- Failure still occurs only at the final `health_probe` step
- Latest failed operator status looked like:
  - `status = failed`
  - `step = health_probe`
  - `details = { proxy_id: 'sv3', domain: 'sv3.shupremium.com', port: 4003, attempt: 15 }`

### Important VPS evidence collected

- Operator job log for a failing `sv3` apply showed:
  - `validate -> ok`
  - `write_ecosystem -> ok`
  - `write_nginx -> ok`
  - `nginx_test -> ok`
  - `nginx_reload -> ok`
  - `pm2_reload -> ok`
  - `health_probe -> failed`
  - `rollback -> ok`
- Example failing job id:
  - `job-1775455293808`

- During failure:
  - `/srv/shupremium-stack/current/proxy-gateway/proxy-service/logs/sv3-error.log` existed but was empty
  - `/srv/shupremium-stack/current/proxy-gateway/proxy-service/logs/sv3-out.log` existed but was empty
  - after rollback, `/etc/nginx/sites-available/proxy-managed-sv3.conf` no longer existed
  - after rollback, `pm2 ls | grep proxy-sv3` returned nothing

- PM2 daemon log gave the strongest clue:
  - `proxy-sv3` repeatedly went `online`
  - then was immediately `disconnected`
  - then exited with code `0` via signal `SIGINT`
  - then started again
  - this loop repeated many times during the same apply job
  - later rollback attempted to stop `proxy-sv3`, but PM2 said the app did not have a pid

### Example PM2 daemon behavior observed

- Repeated lines from `/home/ubuntu/.pm2/pm2.log`:
  - `App [proxy-sv3:<id>] online`
  - `App name:proxy-sv3 id:<id> disconnected`
  - `App [proxy-sv3:<id>] exited with code [0] via signal [SIGINT]`
  - `App [proxy-sv3:<id>] starting in -cluster mode-`
- This suggests the process is not crashing with an application error.
- It looks more like PM2 orchestration is cycling the new app during apply.

### Interpretation of the current unresolved bug

- The remaining bug does not appear to be:
  - wildcard certificate availability
  - nginx config generation
  - nginx syntax test
  - nginx reload
  - application-level exception inside `sv3` itself
- The remaining bug appears to be in PM2 orchestration for newly added proxy apps.
- Specifically, `proxy-sv3` seems to be started, then interrupted, then started again repeatedly during the same apply window, and never remains stable long enough for `health_probe` to succeed.

### Why old `admin-panel` felt more stable

- Old `admin-panel` was tightly coupled to the exact VPS runtime state and had already been battle-tested against:
  - legacy PM2 dump state
  - existing nginx layout
  - older cert paths and deploy habits
- New `platform-control + proxy-operator` architecture is cleaner, but initially lacked compatibility handling for this messy real production state.
- Most parity gaps have already been closed, but the PM2 orchestration bug for new proxy instances remains unresolved.

### Exact local repo state when handing off to another AI

- `origin/main` already contains:
  - `5f13342`
  - `574f47d`
  - `c33ace9`
  - `5995d7d`
- `memory.md` is intentionally local and not meant to be committed
- Additional local-only note files may also exist:
  - `vps-arm.md`
  - `vps-shopbot.md`
  - `docs/portal-arm-cutover-runbook.md`

### Root cause identified and resolved on `2026-04-06`

- The bug was **NOT** a PM2 cluster mode orchestration issue
- The actual root cause: **`node_modules` missing** at the new deploy path
- `proxy-service` code was deployed to `/srv/shupremium-stack/releases/.../proxy-gateway/proxy-service/`
- But `npm ci` was never run there — only source files were copied via `git archive`
- All existing proxy apps (`proxy-gpt1` through `proxy-sv2`) still ran from old path `/home/ubuntu/proxy-gateway/proxy-service/` which had `node_modules`
- When operator tried to start `proxy-sv3` from the new path, `require('fastify')` threw `MODULE_NOT_FOUND`
- The process crash was masked by the graceful shutdown handler (`SIGINT` → exit code 0), making it look like a PM2 cycling issue in daemon logs

### Evidence that confirmed root cause

```
cd /srv/shupremium-stack/current/proxy-gateway/proxy-service
PORT=4003 TARGET_HOST=test.com SERVICE_NAME=SV3 node src/index.js
→ Error: Cannot find module 'fastify'

cd /home/ubuntu/proxy-gateway/proxy-service
PORT=4099 TARGET_HOST=test.com SERVICE_NAME=TEST node src/index.js
→ [TEST] Started on port 4099 -> https://test.com (verify=on)
```

### Fixes applied

1. **Quick fix on VPS**: `npm ci --production` in `/srv/shupremium-stack/current/proxy-gateway/proxy-service/`
   - After this, creating/toggling/deleting `sv3` from `platform-control` worked immediately
2. **Deploy script fix**: `ops/deploy/lib.sh` → `prepare_proxy_gateway_release()` now runs `npm ci --omit=dev` for both `proxy-operator` and `proxy-service` during the prepare phase, before any PM2 operations
   - This mirrors how `prepare_python_release()` handles `pip install`

