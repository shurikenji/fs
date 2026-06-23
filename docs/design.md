# Current Architecture

Updated: 2026-06-23

## Overview

```text
                         Public users
                              |
                              v
                    +-------------------+
                    | portal            |
                    | shupremium.com    |
                    | ARM role :8080    |
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
| admin.shupremium.com  |        | ARM role :8091      |
| ARM role :8090        |        +----------+----------+
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
| separate Shopbot VPS  |
| Telegram + admin + DB |
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

It runs on the ARM host role, normally on port `8090`, behind `admin.shupremium.com`.

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

`shopbot` is intentionally isolated on its own VPS. It owns:

- Telegram bot runtime
- payment polling
- orders, products, users, wallets, fulfillment
- Shopbot admin UI
- its own SQLite DB

`platform-control` does not write Shopbot DB directly. It only opens Shopbot admin through a short-lived signed launch token.

## Data boundaries

| Store | Owner | Content |
| --- | --- | --- |
| `shared/platform-control/data/platform_control.db` | `platform-control` | Admin/control-plane intent |
| `shared/portal/data/hub.db` | `portal` | Runtime cache, snapshots, public derived data |
| `shared/shopbot/data/*` | `shopbot` | Orders, users, wallets, fulfillment |
| PM2/nginx/proxy runtime | `proxy-gateway` | Active customer proxy processes and routing |

## Internal contracts

- `X-Control-Plane-Token` protects platform-control internal APIs consumed by portal.
- `X-Pricing-Admin-Token` protects portal internal pricing admin APIs consumed by platform-control.
- Shopbot admin launch uses a separate shared secret and short TTL token.
- Shopbot internal portal APIs use their own internal token boundary.

## Host roles and migration state

| Role | Apps | Notes |
| --- | --- | --- |
| `arm` | `portal`, `platform-control`, `proxy-gateway` | Runs the public portal, admin shell, proxy operator, and generated proxy services. A Singapore Oracle ARM host is being prepared for cutover. |
| `shopbot` | `shopbot` | Runs Telegram commerce and payment polling separately from the ARM proxy/admin plane. |

The expected role file on each host is `/etc/shupremium-host-role`.

Do not hard-code Oracle instance names in architecture docs. During a VPS migration, the source of truth is the host role file, `/srv/shupremium-stack` layout, PM2/systemd health, and DNS records.

## Deprecated or archived components

- `archive/services/balance-checker` is archived source only.
- Old standalone Shopbot path under `/home/ubuntu/shopbot` is no longer canonical.
- Old manual portal/platform deploy paths are no longer canonical once the `/srv/shupremium-stack` layout is active.
- `admin-panel` is not the primary admin shell; `platform-control` is.
- `docs/implementation-plan-v4.md` is obsolete; `docs/implementation-plan.md` is the active roadmap.
