# Pricing Source Configuration Reference

Updated: 2026-06-23

This file documents how pricing sources should be configured. It intentionally does not store production tokens, cookies, API keys, or provider credentials.

GitHub is currently public. Treat every value in this document as public-safe example data only.

## Where sources are managed

Pricing source intent is managed in `platform-control`, then pushed/imported into `portal` through the internal pricing bridge.

Runtime direction:

```text
platform-control
  -> source registry and runtime settings
  -> portal internal admin bridge
  -> portal local DB/cache
  -> public pricing, keys, logs, balance pages
```

## Required fields

| Field | Meaning |
| --- | --- |
| `source_id` | Stable ID such as `gpt1`, `gpt2`, `sv1` |
| `display_name` | Human-readable name shown in admin/public UI |
| `source_type` | Adapter/profile hint, for example NewAPI-style or RixAPI-style |
| `upstream_base_url` | Provider base URL used by server-side fetches |
| `public_base_url` | Public Shupremium proxy domain |
| `quota_multiple` | Pricing conversion multiplier; must not be dropped |
| `balance_rate` | Balance conversion/display rate |
| `auth_mode` | Header/bearer/cookie mode used by the upstream |
| `auth_user_header` | Header name when provider requires user ID |
| `auth_user_value` | Provider user ID or account ID |
| `auth_token` | Secret token; store only in DB/runtime, never in docs |
| `auth_cookie` | Secret cookie when needed; store only in DB/runtime |
| `pricing_path` | Provider pricing endpoint path |
| `ratio_config_path` | Provider ratio endpoint path |
| `log_path` | Provider logs endpoint path |
| `token_search_path` | Provider token search endpoint path |
| `groups_path` | Provider user groups endpoint path |
| `manual_groups` | Optional manual group override |
| `hidden_groups_json` | Groups hidden from public output |
| `excluded_models_json` | Models hidden from public output |

## Active source IDs

Current active IDs known from production docs and memory:

| ID | Public base URL | Notes |
| --- | --- | --- |
| `gpt1` | `https://gpt1.shupremium.com` | NewAPI/catalog-list style |
| `gpt2` | `https://gpt2.shupremium.com` | RixAPI/inline ratio style |
| `gpt3` | `https://gpt3.shupremium.com` | Proxy runtime exists; verify pricing source before editing |
| `gpt4` | `https://gpt4.shupremium.com` | NewAPI/catalog-list style |
| `gpt5` | `https://gpt5.shupremium.com` | NewAPI/catalog-list style |
| `sv1` | `https://sv1.shupremium.com` | Yunwu/NewAPI-like payload behavior |
| `sv2` | `https://sv2.shupremium.com` | Proxy runtime exists; verify pricing source before editing |

Do not treat this table as a credential source. Verify live values in `platform-control` before production changes.

## Safe example

```text
Source ID: gpt1
Display name: GPT1
Source type: NewAPI Standard
Upstream base URL: https://provider.example.com
Public base URL: https://gpt1.shupremium.com
Quota multiple: 0.3
Balance rate: 0.3
Auth mode: Header + Bearer
Auth user header: New-Api-User
Auth user value: <provider-user-id>
Auth token: <stored in platform-control only>
Pricing path: /api/pricing
Ratio config path: /api/ratio_config
Log path: /api/log/self
Token search path: /api/token/search
Groups path: /api/user/self/groups
Hidden groups JSON: []
Excluded models JSON: []
```

## Rules

- Never paste real tokens into Markdown.
- Never commit screenshots or copied admin pages containing tokens.
- If a token was committed to public GitHub, rotate it at the provider immediately.
- Keep source IDs stable because order history, pricing cache, and admin workflows may reference them.
- Preserve `quota_multiple` in pricing output.
- Prefer payload-shape detection over trusting only the configured `source_type`.
