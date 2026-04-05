#!/bin/bash

# ========================================
# PROXY GATEWAY CONTROL
# ========================================

PROXY_DIR="$HOME/proxy-gateway"
OPERATOR_DIR="$PROXY_DIR/proxy-operator"
SERVICE_DIR="$PROXY_DIR/proxy-service"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() {
    echo -e "${BLUE}"
    echo "============================================================"
    echo "                 PROXY GATEWAY CONTROL"
    echo "============================================================"
    echo -e "${NC}"
}

case "$1" in
    status|s)
        print_header
        echo -e "${YELLOW}PM2 Status:${NC}"
        pm2 status
        echo ""
        echo -e "${YELLOW}Nginx Status:${NC}"
        sudo systemctl is-active nginx && echo -e "${GREEN}* nginx is running${NC}" || echo -e "${RED}* nginx is stopped${NC}"
        ;;

    start)
        echo "Starting proxy runtime..."
        cd "$SERVICE_DIR" && pm2 start ecosystem.config.js 2>/dev/null
        cd "$OPERATOR_DIR" && pm2 start src/server.js --name proxy-operator 2>/dev/null
        pm2 save
        echo -e "${GREEN}OK: Proxy runtime started${NC}"
        ;;

    stop)
        echo "Stopping proxy runtime..."
        pm2 stop proxy-operator 2>/dev/null || true
        cd "$SERVICE_DIR" && pm2 stop ecosystem.config.js 2>/dev/null || true
        echo -e "${GREEN}OK: Proxy runtime stopped${NC}"
        ;;

    restart|r)
        echo "Restarting proxy runtime..."
        pm2 restart proxy-operator 2>/dev/null || true
        cd "$SERVICE_DIR" && pm2 reload ecosystem.config.js --update-env 2>/dev/null || pm2 restart ecosystem.config.js
        echo -e "${GREEN}OK: Proxy runtime restarted${NC}"
        ;;

    reload)
        echo "Reloading proxy runtime..."
        cd "$SERVICE_DIR" && pm2 reload ecosystem.config.js --update-env
        pm2 restart proxy-operator --update-env 2>/dev/null || true
        sudo nginx -t && sudo nginx -s reload
        echo -e "${GREEN}OK: Configurations reloaded${NC}"
        ;;

    logs|l)
        if [ -n "$2" ]; then
            pm2 logs "$2" --lines 50
        else
            pm2 logs --lines 30
        fi
        ;;

    nginx-test|nt)
        sudo nginx -t
        ;;

    nginx-reload|nr)
        sudo nginx -t && sudo nginx -s reload
        echo -e "${GREEN}OK: Nginx reloaded${NC}"
        ;;

    ssl-status|ss)
        sudo certbot certificates
        ;;

    ssl-renew|sr)
        sudo certbot renew
        sudo nginx -s reload
        echo -e "${GREEN}OK: SSL renewed${NC}"
        ;;

    ip-add|ip)
        "$PROXY_DIR/scripts/admin-ip-sync.sh" "$2"
        ;;

    ip-list|ipl)
        "$PROXY_DIR/scripts/admin-ip-sync.sh" --list
        ;;

    health|h)
        print_header
        echo -e "${YELLOW}Health Check:${NC}"
        echo ""

        operator_status=$(pm2 jlist 2>/dev/null | jq -r '.[] | select(.name=="proxy-operator") | .pm2_env.status' 2>/dev/null)
        if [ "$operator_status" = "online" ]; then
            echo -e "Proxy Operator: ${GREEN}OK Online${NC}"
        else
            echo -e "Proxy Operator: ${RED}FAIL ${operator_status:-missing}${NC}"
        fi

        for port in $(seq 3001 3010); do
            status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://localhost:$port/_internal/health 2>/dev/null)
            if [ "$status" = "200" ]; then
                echo -e "Proxy Service (localhost:$port): ${GREEN}OK Online${NC}"
            elif [ "$status" = "000" ]; then
                continue
            else
                echo -e "Proxy Service (localhost:$port): ${RED}FAIL HTTP $status${NC}"
            fi
        done
        ;;

    *)
        print_header
        echo "Usage: proxy-ctl <command> [options]"
        echo ""
        echo -e "${YELLOW}Service Commands:${NC}"
        echo "  status, s          Show PM2 and Nginx status"
        echo "  start              Start proxy-service and proxy-operator"
        echo "  stop               Stop proxy-service and proxy-operator"
        echo "  restart, r         Restart proxy-service and proxy-operator"
        echo "  reload             Reload configurations"
        echo "  logs, l [name]     View logs (optional: service name)"
        echo "  health, h          Health check all services"
        echo ""
        echo -e "${YELLOW}Nginx Commands:${NC}"
        echo "  nginx-test, nt     Test nginx configuration"
        echo "  nginx-reload, nr   Reload nginx"
        echo ""
        echo -e "${YELLOW}SSL Commands:${NC}"
        echo "  ssl-status, ss     Show SSL certificates"
        echo "  ssl-renew, sr      Renew SSL certificates"
        echo ""
        echo -e "${YELLOW}IP Allowlist Commands:${NC}"
        echo "  ip-add, ip [IP]    Add IP to admin allowlist"
        echo "  ip-list, ipl       List allowed IPs"
        echo ""
        ;;
esac
