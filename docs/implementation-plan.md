# Shupremium V4 Implementation Plan

## Summary

- `shupremium.com` is the single public portal shell.
- `admin.shupremium.com` is the control-plane entrypoint for infrastructure and linked admin launch.
- `shopbot` remains isolated on its own VPS and keeps ownership of commerce data and admin writes.
- `proxy-gateway` remains isolated on the ARM VPS and is still driven by `proxy-operator`.
- `balance-checker` standalone is deprecated after portal cutover because its logic now lives inside `pricing-hub`, which acts as the portal runtime.

## Runtime Layout

### 1. Public Portal

- Runtime: `pricing-hub`
- Domain: `shupremium.com`
- Public routes:
  - `/`
  - `/pricing`
  - `/check`
  - `/keys`
  - `/logs`
  - `/status`
- Source of truth:
  - pricing data is cached locally in portal DB
  - balance sources and proxy status are fetched from `platform-control` public APIs and stored as local JSON snapshots for fallback

### 2. Admin Shell

- Runtime: `platform-control`
- Domain: `admin.shupremium.com`
- Responsibilities:
  - service source registry
  - proxy endpoint registry
  - portal module registry
  - deploy job history
  - proxy sync and wildcard certificate triggers
  - linked launch into `shopbot admin`

### 3. Shopbot

- Runtime: `shopbot`
- Domain: internal or directly exposed only as needed
- Responsibilities:
  - Telegram bot
  - payment polling
  - orders, products, users, wallets, fulfillment
  - business admin
  - read-only portal APIs
  - launch-token consumer endpoint for linked admin entry

### 4. Proxy Plane

- Runtime: `proxy-gateway` plus `proxy-operator`
- Domain pattern:
  - `gpt*.shupremium.com`
  - `sv*.shupremium.com`
- Responsibilities:
  - runtime proxy processes
  - nginx and certificate handling
  - rollback-safe desired-state apply flow

## Admin Linking Model

- `platform-control` issues a short-lived signed launch token.
- Admin clicks `Open Shopbot Admin` from `admin.shupremium.com/control`.
- Browser auto-posts the token to `shopbot` at `/sso/consume`.
- `shopbot` verifies:
  - signature
  - issuer
  - nonce presence
  - short TTL
- If valid, `shopbot` creates its own local session.
- If invalid or expired, `shopbot` falls back to normal login.

This keeps:

- separate cookies
- separate session stores
- separate deployment cadence
- no direct DB access from control plane to shopbot

## Public Data Flow

### Pricing

- `platform-control` publishes service source registry.
- `pricing-hub` imports enabled sources into its local DB.
- portal pricing, keys, and logs keep using the existing pricing-hub stack and local cache.

### Balance

- portal reads `/api/public/balance-sources` from `platform-control`
- successful responses are written to local snapshot files
- if control plane is down, portal uses the latest local snapshot
- if no snapshot exists yet, portal falls back to enabled local pricing servers

### Status

- portal reads `/api/public/status` from `platform-control`
- successful responses are written to local snapshot files
- if control plane is down, portal shows the latest cached snapshot

## Deploy Order

1. Deploy `shopbot` with `ADMIN_LAUNCH_SECRET` and `PLATFORM_ADMIN_URL`.
2. Deploy `platform-control` with `SHOPBOT_ADMIN_URL`, `SHOPBOT_LAUNCH_SECRET`, and TTL config.
3. Verify linked launch from `platform-control` to `shopbot`.
4. Deploy portal changes in `pricing-hub`.
5. Point `shupremium.com` at the portal runtime.
6. Keep `balance-checker` old service up only during transition, then remove it from active routing.

## Required Environment

### platform-control

- `SHOPBOT_ADMIN_URL`
- `SHOPBOT_LAUNCH_SECRET`
- `SHOPBOT_LAUNCH_TTL_SECONDS`

### shopbot

- `PLATFORM_ADMIN_URL`
- `ADMIN_LAUNCH_SECRET`
- `ADMIN_LAUNCH_TTL_SECONDS`
- existing `PORTAL_INTERNAL_TOKEN`
- existing `PORTAL_SESSION_SECRET`

### pricing-hub

- `CONTROL_PLANE_URL`
- `CONTROL_PLANE_SYNC_ENABLED=true`
- `CONTROL_PLANE_TOKEN` only if internal source import is enabled

## Acceptance Checks

- Portal home loads on `/` and pricing moves to `/pricing`.
- Balance checker works from `/check` without hardcoded server list.
- Proxy status page loads on `/status`.
- `platform-control` dashboard shows `Open Shopbot Admin`.
- Clicking `Open Shopbot Admin` logs into shopbot without re-entering password.
- Invalid or expired launch token is rejected by shopbot.
- Restarting portal or control plane does not affect `shopbot` bot/admin runtime.
- Proxy sync flow still runs only through `proxy-operator`.
