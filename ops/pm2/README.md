# PM2 Ecosystem Configs (Archived)

Updated: 2026-06-23

Các file ecosystem `.cjs` cũ đã bị xoá vì deploy pipeline hiện tại dùng `lib.sh` trực tiếp:

- `restart_pm2_python_app()` cho portal, platform-control
- `restart_proxy_gateway_pm2()` cho proxy-operator + proxy-service
- `restart_shopbot_systemd()` cho shopbot (dùng systemd)

Proxy-service ecosystem được `proxy-operator` tạo động tại runtime.

PM2 vẫn là runtime manager cho `portal`, `platform-control`, `proxy-operator`, và các generated proxy services trên host role `arm`. Sau khi deploy host mới, chạy `pm2 startup` và `pm2 save` theo `docs/deployment-guide.md` để process sống qua reboot.
