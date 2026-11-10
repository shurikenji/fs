# Ops Scripts

Updated: 2026-11-11

Thư mục này dành cho các script phụ trợ không phải deploy trực tiếp.

Ví dụ phù hợp để đặt ở đây:

- script kiểm tra `.env` trước deploy
- script audit `shared/` trên VPS
- script backup SQLite trước rollout
- script smoke test nâng cao cho pricing

Hiện tại các script deploy chính nằm trong `ops/deploy/`.

Script kiểm tra chính sau deploy hoặc khi dựng host mới:

```bash
bash ops/scripts/verify-all-health.sh combined
```

Production uses one VPS with role `combined`; this checks all five apps. The `arm` and `shopbot` filters are retained for targeted diagnostics, not as current host placement.
