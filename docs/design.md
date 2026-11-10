# Current Architecture

Updated: 2026-11-11

## Overview

All five apps run on one production VPS, confirmed by the operator on 2026-11-11. The diagram shows service/data boundaries on that VPS, not separate machines. `combined` is the deployment role for this topology; no live host inspection was performed for this documentation update.

```text
                         Public users
                              |
                              v
                    +-------------------+
                    | portal            |
                    | shupremium.com    |
                    | localhost :8080    |
                    +---------+---------+
                              |
                              v
                    +-------------------+
                    | portal DB/cache   |
                    | shared/portal     |
                    +-------------------+

Admins
  |
  v
+-----------------------+        +---------------------+
| platform-control      |------->| proxy-operator      |
| admin.shupremium.com  |        | localhost :8091      |
| localhost :8090        |        +----------+----------+
+-----------+-----------+                   |
            |                               v
            |                    +---------------------+
            |                    | proxy-service       |
            |                    | gpt1..gpt5 sv1..2  |
            |                    +---------------------+
            |
            | signed launch token
            v
+-----------------------+
| shopbot               |
| same VPS, admin :8092  |
| Telegram + admin + DB |
+-----------------------+

platform-control
  |
  | source registry / internal config
  v
+-----------------------+
| key-vault-worker      |
| combined role :8093   |
| encrypted key history |
+-----------------------+
```

## Runtime ownership

### `platform-control`

`platform-control` is the central admin shell and control plane. It owns admin-facing intent for:

- service source registry
- pricing runtime settings
- proxy endpoint registry
- portal module visibility
- deploy job history
- linked launch into Shopbot admin

It runs on the shared production VPS, on localhost port `8090`, behind `admin.shupremium.com`.

### `portal`

`portal` is the public runtime for `shupremium.com`. It owns public-facing derived state:

- pricing pages and pricing APIs
- balance checker
- key/log lookup tools
- proxy status display
- local pricing cache and snapshots
- public-safe model/group presentation

It is not the admin source of truth. It imports or receives state from `platform-control` through internal token-protected endpoints.

### `proxy-gateway`

`proxy-gateway` contains:

- `proxy-operator`: control endpoint used by `platform-control`
- `proxy-service`: generated PM2 proxy processes serving customer traffic

Nginx/certificate/proxy changes should flow through `proxy-operator` or the deploy scripts, not by ad-hoc edits unless it is an incident response.

### `shopbot`

`shopbot` runs as its own systemd service on the same VPS as the other apps, with its admin on localhost `8092`. It owns:

- Telegram bot runtime
- payment polling
- orders, products, users, wallets, fulfillment
- Shopbot admin UI
- its own SQLite DB

`platform-control` does not write Shopbot DB directly. It provides connection configuration through the internal snapshot API and opens Shopbot admin through a short-lived signed launch token. Shopbot keeps its selling prices, quota conversion, discounts, tiers, spend accrual and sales groups locally; connection sync must preserve these settings.

### `key-vault-worker`

`key-vault-worker` is a separate systemd service on the `combined` host role. It owns:

- polling configured upstream key sources from `platform-control`
- encrypted key inventory/history and balance snapshots
- retention for snapshots and keys no longer present upstream
- authenticated internal summary and lookup APIs

Its HTTP service binds to `127.0.0.1:8093`. Runtime secrets and its SQLite DB live under `shared/key-vault-worker`; key material must never be returned by the summary endpoint.

## Data boundaries

| Store | Owner | Content |
| --- | --- | --- |
| `shared/platform-control/data/platform_control.db` | `platform-control` | Admin/control-plane intent |
| `shared/portal/data/hub.db` | `portal` | Runtime cache, snapshots, public derived data |
| `shared/shopbot/data/*` | `shopbot` | Orders, users, wallets, fulfillment |
| `shared/key-vault-worker/data/*` | `key-vault-worker` | Encrypted key inventory, snapshots, polling history |
| PM2/nginx/proxy runtime | `proxy-gateway` | Active customer proxy processes and routing |

## Internal contracts

- `X-Control-Plane-Token` protects platform-control internal APIs consumed by portal.
- `X-Pricing-Admin-Token` protects portal internal pricing admin APIs consumed by platform-control.
- Shopbot admin launch uses a separate shared secret and short TTL token.
- Shopbot internal portal APIs use their own internal token boundary.
- `key-vault-worker` reads its source registry through a control-plane token and protects its own API with separate vault credentials.

## Host roles

| Role | Apps | Notes |
| --- | --- | --- |
| `combined` | All five apps | Current single-VPS deployment; accepts apps whose manifest compatibility role is `arm`, `shopbot`, or `combined`. |
| `arm` | `portal`, `platform-control`, `proxy-gateway` | Retained split-host compatibility; not the current production topology. |
| `shopbot` | `shopbot` | Retained split-host compatibility; not a separate current production VPS. |

The expected role file on the production VPS is `/etc/shupremium-host-role` containing `combined`.

Do not hard-code VPS instance names in architecture docs. The operator-confirmed topology is one VPS. The deploy manifest describes app compatibility, while the live host-role file, `/srv/shupremium-stack` layout, PM2/systemd health, and DNS/runtime checks establish actual runtime state.

## Deprecated or archived components

- `archive/services/balance-checker` is archived source only.
- Old standalone Shopbot path under `/home/ubuntu/shopbot` is no longer canonical.
- Old manual portal/platform deploy paths are no longer canonical once the `/srv/shupremium-stack` layout is active.
- `admin-panel` is not the primary admin shell; `platform-control` is.
- `docs/implementation-plan.md` is the active roadmap; historical rollout plans should stay outside the active docs set.
