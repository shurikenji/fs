#!/bin/bash

# ========================================
# PROXY GATEWAY - HEALTH CHECK (Cron)
# ========================================

LOG_FILE="/var/log/proxy-gateway-health.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

# Kiểm tra Admin Panel
status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://localhost:8080/auth/login 2>/dev/null)
if [ "$status" != "200" ]; then
    echo "[$DATE] ALERT: Admin Panel is DOWN (HTTP: $status)" >> "$LOG_FILE"
    pm2 restart admin-panel 2>/dev/null
    echo "[$DATE] INFO: Attempted restart of admin-panel" >> "$LOG_FILE"
fi

# Kiểm tra các proxy services qua internal health
for port in $(seq 3001 3020); do
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:$port/_internal/health 2>/dev/null)
    
    if [ "$status" = "200" ]; then
        # Service đang chạy OK
        continue
    elif [ "$status" = "000" ]; then
        # Không có service trên port này - bỏ qua
        continue
    else
        # Service có vấn đề
        echo "[$DATE] ALERT: Proxy on port $port is DOWN (HTTP: $status)" >> "$LOG_FILE"
        
        # Tìm tên service
        service_name=$(pm2 jlist 2>/dev/null | jq -r ".[] | select(.pm2_env.PORT == $port) | .name" 2>/dev/null)
        if [ -n "$service_name" ]; then
            pm2 restart "$service_name" 2>/dev/null
            echo "[$DATE] INFO: Attempted restart of $service_name" >> "$LOG_FILE"
        fi
    fi
done

# Kiểm tra Nginx
if ! systemctl is-active --quiet nginx; then
    echo "[$DATE] ALERT: Nginx is DOWN" >> "$LOG_FILE"
    sudo systemctl restart nginx
    echo "[$DATE] INFO: Attempted restart of nginx" >> "$LOG_FILE"
fi
