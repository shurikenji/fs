# shupremium-stack

Monorepo này là source of truth cho stack Shupremium đang chạy production. Repo chỉ chứa code, cấu hình mẫu, tài liệu vận hành và script deploy; runtime state luôn nằm ngoài Git.

## Current status

Updated: 2026-06-23

- Production deploy model is `/srv/shupremium-stack` with per-app releases and shared runtime state.
- The ARM role currently runs `portal`, `platform-control`, and `proxy-gateway`.
- A new Singapore Oracle ARM VPS is being prepared as the next ARM host. DNS should only be switched after local health checks and `curl --resolve` checks pass.
- The Shopbot role remains separate and runs only `shopbot`.
- Local-only cleanup and sensitive/session files are kept under `_local_cleanup/` and are ignored by Git.
- GitHub is still treated as public. Only sanitized source, examples, and docs may be pushed.

## Thành phần active

| App | Path | Runtime | Host role | Vai trò |
| --- | --- | --- | --- | --- |
| Portal | `apps/portal` | Python/FastAPI + PM2 | `arm` | Public site: pricing, balance, keys, logs, status |
| Platform Control | `apps/platform-control` | Python/FastAPI + PM2 | `arm` | Admin shell/control plane |
| Shopbot | `apps/shopbot` | Python + systemd | `shopbot` | Telegram bot, payment poller, shop admin |
| Proxy Gateway | `services/proxy-gateway` | Node.js + PM2 | `arm` | Proxy operator + generated proxy services |

`archive/services/balance-checker` là legacy code đã archive, không nằm trong active deploy manifest.

## Production topology

```text
Users
  -> https://shupremium.com
  -> portal (:8080 on ARM VPS)

Admins
  -> https://admin.shupremium.com
  -> platform-control (:8090 on ARM VPS)
  -> linked launch to shopbot admin when needed

Proxy customers
  -> gpt*.shupremium.com / sv*.shupremium.com
  -> proxy-service processes managed by proxy-operator (:8091)

Telegram commerce
  -> shopbot on separate VPS
  -> systemd unit: shopbot
```

## Deploy model

Production layout is standardized:

```text
/srv/shupremium-stack/
  repo/       # git checkout
  releases/   # timestamped app releases
  current/    # active symlinks per app
  shared/     # .env, data, venv, operator secrets, audit logs
```

Deploy is always per app:

```bash
cd /srv/shupremium-stack/repo
git fetch origin
git pull --ff-only origin main
bash ops/deploy/deploy-portal.sh main
bash ops/deploy/deploy-platform-control.sh main
bash ops/deploy/deploy-proxy-gateway.sh main
bash ops/deploy/deploy-shopbot.sh main
```

Do not copy whole local folders to production. Do not commit or overwrite production `.env`, DB files, `data/`, `.venv`, `node_modules`, logs, or generated release artifacts.

For the current public GitHub repo, push source code and sanitized docs only. Do not push `_local_cleanup/`, `.gitnexus/`, `.claude/`, `.agents/`, real `.env` files, SQLite DBs, `data/`, `venv`, `node_modules`, logs, or downloaded design/export files. Keep the same rule even after moving to a private repo.

## Important docs

- [docs/design.md](docs/design.md): current architecture and data boundaries.
- [docs/deployment-guide.md](docs/deployment-guide.md): deploy, rollback, health checks, and VPS layout.
- [docs/server.md](docs/server.md): sanitized pricing source configuration reference.
- [docs/implementation-plan.md](docs/implementation-plan.md): current state and future roadmap.
- [docs/gitnexus-analysis.md](docs/gitnexus-analysis.md): code intelligence notes and high-risk areas.
- [memory.md](memory.md): compact handoff memory for future changes.

## Local workflow

```powershell
git status --short
npx gitnexus analyze
```

Before changing code, use GitNexus impact/context as required by `AGENTS.md`. Before committing code changes, run GitNexus change detection and focused verification for the touched app.

Node dependencies are generated locally with `npm ci` inside the relevant service package when needed. They are not part of the source repo.
