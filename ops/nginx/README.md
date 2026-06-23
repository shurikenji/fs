# Nginx Config Reference

Updated: 2026-06-23

Thư mục `snippets/` chứa **bản tham chiếu** của các nginx snippet đang dùng trên host role `arm`.

Đây **không phải** file deploy tự động — mục đích là:
- Lưu trữ trong Git để track thay đổi
- Tham chiếu khi cần tạo VPS mới
- So sánh khi troubleshoot

## Files

- `snippets/ssl-params.conf` — TLS settings
- `snippets/proxy-params.conf` — reverse proxy headers (dùng bởi proxy-operator generated configs)
- `snippets/security-headers.conf` — X-Frame-Options, X-Content-Type-Options, etc.

## Đồng bộ với VPS

Khi thay đổi snippet trên VPS, copy lại vào đây. Dùng host/IP hiện tại của role `arm`, không hard-code tên Oracle instance cũ:
```bash
ARM_HOST=ubuntu@<arm-host-or-ip>
scp "$ARM_HOST":/etc/nginx/snippets/{ssl-params,proxy-params,security-headers}.conf ops/nginx/snippets/
```

Khi muốn push snippet mới lên VPS:
```bash
ARM_HOST=ubuntu@<arm-host-or-ip>
scp ops/nginx/snippets/*.conf "$ARM_HOST":/tmp/
ssh "$ARM_HOST" 'sudo cp /tmp/{ssl-params,proxy-params,security-headers}.conf /etc/nginx/snippets/ && sudo nginx -t && sudo nginx -s reload'
```

For the Singapore migration, test snippets with `sudo nginx -t` on the new host before DNS cutover.
