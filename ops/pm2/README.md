# PM2 Ecosystem Configs (Archived)

Các file ecosystem `.cjs` cũ đã bị xoá vì deploy pipeline hiện tại dùng `lib.sh` trực tiếp:

- `restart_pm2_python_app()` cho portal, platform-control
- `restart_proxy_gateway_pm2()` cho proxy-operator + proxy-service
- `restart_shopbot_systemd()` cho shopbot (dùng systemd)

Proxy-service ecosystem được `proxy-operator` tạo động tại runtime.
