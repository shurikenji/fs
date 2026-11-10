# Nginx Config Reference

Updated: 2026-11-11

Thư mục `snippets/` chứa **bản tham chiếu** của các nginx snippet. Production hiện chạy chung trên một VPS, dùng role `combined`.

Đây **không phải** file deploy tự động — mục đích là:
- Lưu trữ trong Git để track thay đổi
- Tham chiếu khi cần tạo VPS mới
- So sánh khi troubleshoot

## Files

- `snippets/ssl-params.conf` — TLS settings
- `snippets/proxy-params.conf` — reverse proxy headers (dùng bởi proxy-operator generated configs)
- `snippets/security-headers.conf` — X-Frame-Options, X-Content-Type-Options, etc.

## Đồng bộ với VPS

Khi thay đổi snippet trên VPS, copy lại vào đây. Dùng host/IP của VPS hiện tại, không hard-code tên instance cũ:
```bash
VPS_HOST=ubuntu@<current-vps-host-or-ip>
scp "$VPS_HOST":/etc/nginx/snippets/{ssl-params,proxy-params,security-headers}.conf ops/nginx/snippets/
```

Khi muốn push snippet mới lên VPS:
```bash
ARM_HOST=ubuntu@<arm-host-or-ip>
scp ops/nginx/snippets/*.conf "$VPS_HOST":/tmp/
ssh "$VPS_HOST" 'sudo cp /tmp/{ssl-params,proxy-params,security-headers}.conf /etc/nginx/snippets/ && sudo nginx -t && sudo nginx -s reload'
```

For any future host replacement, test snippets with `sudo nginx -t` on the replacement before DNS cutover.
