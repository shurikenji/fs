#!/bin/bash

# ========================================
# PROXY GATEWAY - HEALTH CHECK (Cron)
# ========================================

LOG_FILE="/var/log/proxy-gateway-health.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

# Kiem tra proxy-operator
operator_status=$(pm2 jlist 2>/dev/null | jq -r '.[] | select(.name == "proxy-operator") | .pm2_env.status' 2>/dev/null)
if [ "$operator_status" != "online" ]; then
    echo "[$DATE] ALERT: proxy-operator is DOWN (status: ${operator_status:-missing})" >> "$LOG_FILE"
    pm2 restart proxy-operator 2>/dev/null
    echo "[$DATE] INFO: Attempted restart of proxy-operator" >> "$LOG_FILE"
fi

# Kiem tra cac proxy services qua internal health
for port in $(seq 3001 3020); do
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:$port/_internal/health 2>/dev/null)

    if [ "$status" = "200" ]; then
        continue
    elif [ "$status" = "000" ]; then
        continue
    else
        echo "[$DATE] ALERT: Proxy on port $port is DOWN (HTTP: $status)" >> "$LOG_FILE"

        service_name=$(pm2 jlist 2>/dev/null | jq -r ".[] | select(.pm2_env.PORT == $port) | .name" 2>/dev/null)
        if [ -n "$service_name" ]; then
            pm2 restart "$service_name" 2>/dev/null
            echo "[$DATE] INFO: Attempted restart of $service_name" >> "$LOG_FILE"
        fi
    fi
done

# Kiem tra Nginx
if ! systemctl is-active --quiet nginx; then
    echo "[$DATE] ALERT: Nginx is DOWN" >> "$LOG_FILE"
    sudo systemctl restart nginx
    echo "[$DATE] INFO: Attempted restart of nginx" >> "$LOG_FILE"
fi
