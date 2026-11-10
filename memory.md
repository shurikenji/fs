# Shupremium Stack Memory

Production uses one VPS and the canonical `main` branch. The main merge preserves all commits from `deploy/staging-vietqr-20261106b` through `56a51c8` and `deploy/shopbot-local-pricing-20261111` through `00d1caf`, plus main purchase-idempotency and telemetry changes. Deploy future changes from updated `main`, not the historical staging branch.

Last updated: 2026-11-11

This file is a compact handoff. Keep durable repository, deploy, and safety facts here; host snapshots and one-off migration notes belong in runbooks or inventory docs.

## Workspace

- Canonical local repo: `D:\Projects\Code\shupremium-stack`
- Branch: `main`
- Origin: `https://github.com/shurikenji/fs.git`
- Active roadmap: `docs/roadmap.md`
- Architecture: `docs/architecture.md`
- Deploy guide: `docs/deployment-guide.md`
- GitNexus repo name: `fs`

GitNexus `list_repos` on 2026-11-09 reported the current `fs` index (indexed 2026-11-02) as 3,705 nodes, 11,968 edges, 160 communities, and 300 processes. Re-check live GitNexus state before relying on counts or impact data.

## Active deploy targets

Production is **one VPS**, confirmed by the user on 2026-11-11. Do not infer two VPSs from the old `arm` and `shopbot` role names. Use `combined` for production deploy and health commands. The manifest describes compatible app roles; `ensure_host_role` accepts all five apps on `combined`. The live role file and runtime health were not inspected during this correction.

| App | Current deployment role | Runtime |
| --- | --- | --- |
| `portal` | `combined` | PM2 + Python |
| `platform-control` | `combined` | PM2 + Python |
| `proxy-gateway` | `combined` | PM2 + Node.js |
| `shopbot` | `combined` | systemd + Python |
| `key-vault-worker` | `combined` | systemd + Python |

`archive/services/balance-checker` is archived source and is not in the active manifest.

## Deploy model

Canonical layout:

```text
/srv/shupremium-stack/
  repo/
  releases/
  current/
  shared/
```

Deploy only through the matching `ops/deploy/deploy-*.sh` script on the shared VPS, passing `combined`. Run `bash ops/scripts/verify-all-health.sh combined`. For pricing-ownership releases, deploy Shopbot first, then Platform Control.

Python releases create their own `.venv`. Persistent `.env` and `data/` are linked from `shared/<app>`; do not keep a shared Python venv as part of the current deploy contract.

Normal release flow is extract -> prepare -> validate -> switch `current/<app>` -> restart -> smoke -> rollback on restart/smoke failure. Deploy audit records go to `/srv/shupremium-stack/shared/_ops/deploy-audit.jsonl`.

## Shopbot facts

- Selling prices, quota conversion, discounts, tiers, spend accrual and sales groups belong to Shopbot Admin (`/servers`); central connection snapshots must not overwrite them.

- Canonical systemd working directory: `/srv/shupremium-stack/current/shopbot`.
- Canonical executable: `/srv/shupremium-stack/current/shopbot/.venv/bin/python -m bot.main`.
- Telegram polling requests only `message` and `callback_query`.
- Payment, fulfillment, notification, key-alert, and control-plane sync tasks are supervised by the main runtime.
- Pending purchase creation is idempotent through user + `purchase_nonce` uniqueness.
- The current financial schema is explicit. A DB that predates it must be backed up and migrated with `apps/shopbot/scripts/migrate_financial.py`; release preflight refuses an incomplete schema.
- Shopbot installs its Node dependency during deploy for VietQR support.
- MBBank scanning uses the v3 API contract; VietQR account settings remain separate from scanner credentials.

## Key vault facts

- `key-vault-worker` is a separate systemd FastAPI service on host role `combined`.
- It binds `127.0.0.1:8093` and exposes `/health` plus authenticated internal summary/lookup endpoints.
- It gets source configuration from `platform-control`.
- Its SQLite DB must be an absolute path under `shared/key-vault-worker/data` and must be explicitly initialized before deploy.
- Key material is protected by the vault master key; runtime/API/control-plane credentials are required and must remain outside Git.
- When Shopbot is configured for the remote vault, its local key-backup poller is disabled.

## Cross-app boundaries

- `platform-control` owns admin/control-plane intent.
- `portal` owns public runtime/cache/presentation state.
- `proxy-gateway` owns proxy operator and generated proxy services.
- `shopbot` owns commerce data and does not share-write its DB with platform-control.
- `key-vault-worker` owns persistent key history and does not expose raw key material through its summary API.

Keep token boundaries separate: control-plane, portal pricing admin, Shopbot bridge/admin launch, and key-vault credentials serve different trust boundaries.

## Safety workflow

- Never commit real `.env`, API keys/tokens, SQLite DBs, `data/`, logs, `node_modules`, generated releases, or local cleanup snapshots.
- Do not copy whole local app folders into production or overwrite `shared/` during code deploy.
- Verify host role, current symlink, runtime manager, and health/smoke output before production changes.
- Before editing a function/class/method, run GitNexus upstream impact analysis as required by `AGENTS.md`.
- Before commit, run GitNexus change detection and focused verification for the touched app.
