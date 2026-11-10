# shupremium-stack

Production uses one VPS and the canonical `main` branch. `main` now incorporates both the VPS fixes through `56a51c8` and the pricing release `00d1caf`; the staging/release branches remain historical references.

Monorepo này là source of truth cho stack Shupremium đang chạy production. Repo chỉ chứa code, cấu hình mẫu, tài liệu vận hành và script deploy; runtime state luôn nằm ngoài Git.

## Current status

Updated: 2026-11-11

- Production deploy model is `/srv/shupremium-stack` with per-app releases and shared runtime state.
- The deploy manifest currently contains five apps: `portal`, `platform-control`, `shopbot`, `proxy-gateway`, and `key-vault-worker`.
- Production now runs all five apps on **one VPS**, as confirmed by the operator on 2026-11-11. Use the `combined` deployment role.
- The manifest retains `arm`/`shopbot` app compatibility roles; these do not mean separate production VPSs. The expected host-role file is `/etc/shupremium-host-role = combined`; its live value still needs checking on the VPS.
- Python deploys create an isolated `.venv` inside each release; only `.env` and `data/` are shared across releases.
- Local-only cleanup and sensitive/session files are kept under `_local_cleanup/` and are ignored by Git.
- GitHub is still treated as public. Only sanitized source, examples, and docs may be pushed.

## Thành phần active

| App | Path | Runtime | Current deployment role | Vai trò |
| --- | --- | --- | --- | --- |
| Portal | `apps/portal` | Python/FastAPI + PM2 | `combined` | Public site: pricing, balance, keys, logs, status |
| Platform Control | `apps/platform-control` | Python/FastAPI + PM2 | `combined` | Admin shell/control plane |
| Shopbot | `apps/shopbot` | Python + systemd | `combined` | Telegram bot, payment poller, shop admin |
| Proxy Gateway | `services/proxy-gateway` | Node.js + PM2 | `combined` | Proxy operator + generated proxy services |
| Key Vault Worker | `apps/key-vault-worker` | Python/FastAPI + systemd | `combined` | Encrypted API-key history, source polling, internal lookup/summary API |

`archive/services/balance-checker` là legacy code đã archive, không nằm trong active deploy manifest.

## Production topology

```text
Users
  -> https://shupremium.com
  -> portal (localhost :8080 on the shared VPS)

Admins
  -> https://admin.shupremium.com
  -> platform-control (localhost :8090 on the same VPS)
  -> linked launch to shopbot admin when needed

Proxy customers
  -> gpt*.shupremium.com / sv*.shupremium.com
  -> proxy-service processes managed by proxy-operator (:8091)

Telegram commerce
  -> shopbot on the same VPS; admin on localhost :8092
  -> systemd unit: shopbot

Key vault
  -> key-vault-worker on `combined` host role
  -> systemd unit: key-vault-worker
  -> localhost health/API on :8093
```

## Deploy model

Production layout is standardized:

```text
/srv/shupremium-stack/
  repo/       # git checkout
  releases/   # timestamped app releases
  current/    # active symlinks per app
  shared/     # persistent .env, data, operator secrets, audit logs
```

Deploy is always per app, on the same VPS. Run only the scripts for apps changed by the release. For the Shopbot pricing ownership change, deploy Shopbot before Platform Control:

```bash
cd /srv/shupremium-stack/repo
git fetch origin
git fetch origin
git switch main
git merge --ff-only origin/main
bash ops/deploy/deploy-shopbot.sh HEAD combined
bash ops/deploy/deploy-platform-control.sh HEAD combined
bash ops/scripts/verify-all-health.sh combined
```

Do not copy whole local folders to production. Do not commit or overwrite production `.env`, DB files, `data/`, `.venv`, `node_modules`, logs, or generated release artifacts.

For the current public GitHub repo, push source code and sanitized docs only. Do not push `_local_cleanup/`, `.gitnexus/`, `.claude/`, `.agents/`, real `.env` files, SQLite DBs, `data/`, `venv`, `node_modules`, logs, or downloaded design/export files. Keep the same rule even after moving to a private repo.

## Important docs

- [docs/architecture.md](docs/architecture.md): current architecture and data boundaries.
- [docs/deployment-guide.md](docs/deployment-guide.md): deploy, rollback, backup/standby recovery, health checks, and VPS layout.
- [docs/pricing-sources.md](docs/pricing-sources.md): sanitized pricing source configuration reference.
- [docs/roadmap.md](docs/roadmap.md): current state and future roadmap.
- [docs/code-risk-map.md](docs/code-risk-map.md): code intelligence notes and high-risk areas.
- [memory.md](memory.md): compact handoff memory for future changes.

## Local workflow

```powershell
git status --short
npx gitnexus analyze
```

Before changing code, use GitNexus impact/context as required by `AGENTS.md`. Before committing code changes, run GitNexus change detection and focused verification for the touched app.

Node dependencies are generated locally with `npm ci` inside the relevant service package when needed. They are not part of the source repo.
