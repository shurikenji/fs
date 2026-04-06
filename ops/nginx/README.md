# Nginx Config Reference

Thư mục `snippets/` chứa **bản tham chiếu** của các nginx snippet đang dùng trên ARM VPS.

Đây **không phải** file deploy tự động — mục đích là:
- Lưu trữ trong Git để track thay đổi
- Tham chiếu khi cần tạo VPS mới
- So sánh khi troubleshoot

## Files

- `snippets/ssl-params.conf` — TLS settings
- `snippets/proxy-params.conf` — reverse proxy headers (dùng bởi proxy-operator generated configs)
- `snippets/security-headers.conf` — X-Frame-Options, X-Content-Type-Options, etc.

## Đồng bộ với VPS

Khi thay đổi snippet trên VPS, copy lại vào đây:
```bash
scp ubuntu@instance-20260114-0319:/etc/nginx/snippets/{ssl-params,proxy-params,security-headers}.conf ops/nginx/snippets/
```

Khi muốn push snippet mới lên VPS:
```bash
scp ops/nginx/snippets/*.conf ubuntu@instance-20260114-0319:/tmp/
ssh ubuntu@instance-20260114-0319 'sudo cp /tmp/{ssl-params,proxy-params,security-headers}.conf /etc/nginx/snippets/ && sudo nginx -t && sudo nginx -s reload'
```
