#!/bin/bash

# ========================================
# PROXY GATEWAY CONTROL
# ========================================

PROXY_DIR="$HOME/proxy-gateway"
ADMIN_DIR="$PROXY_DIR/admin-panel"
SERVICE_DIR="$PROXY_DIR/proxy-service"

# Màu sắc
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() {
    echo -e "${BLUE}"
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║              PROXY GATEWAY CONTROL                        ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

case "$1" in
    status|s)
        print_header
        echo -e "${YELLOW}PM2 Status:${NC}"
        pm2 status
        echo ""
        echo -e "${YELLOW}Nginx Status:${NC}"
        sudo systemctl is-active nginx && echo -e "${GREEN}● nginx is running${NC}" || echo -e "${RED}● nginx is stopped${NC}"
        ;;
    
    start)
        echo "Starting all services..."
        cd "$SERVICE_DIR" && pm2 start ecosystem.config.js 2>/dev/null
        cd "$ADMIN_DIR" && pm2 start ecosystem.config.js 2>/dev/null
        pm2 save
        echo -e "${GREEN}✓ Services started${NC}"
        ;;
    
    stop)
        echo "Stopping all services..."
        pm2 stop all
        echo -e "${GREEN}✓ Services stopped${NC}"
        ;;
    
    restart|r)
        echo "Restarting all services..."
        pm2 restart all
        echo -e "${GREEN}✓ Services restarted${NC}"
        ;;
    
    reload)
        echo "Reloading configurations..."
        cd "$SERVICE_DIR" && pm2 reload ecosystem.config.js --update-env
        sudo nginx -t && sudo nginx -s reload
        echo -e "${GREEN}✓ Configurations reloaded${NC}"
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
        echo -e "${GREEN}✓ Nginx reloaded${NC}"
        ;;
    
    ssl-status|ss)
        sudo certbot certificates
        ;;
    
    ssl-renew|sr)
        sudo certbot renew
        sudo nginx -s reload
        echo -e "${GREEN}✓ SSL renewed${NC}"
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
        
        # Admin Panel
        status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8080/auth/login 2>/dev/null)
        if [ "$status" = "200" ]; then
            echo -e "Admin Panel (localhost:8080): ${GREEN}✓ Online${NC}"
        else
            echo -e "Admin Panel (localhost:8080): ${RED}✗ Offline (HTTP $status)${NC}"
        fi
        
        # Proxy Services
        for port in $(seq 3001 3010); do
            status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://localhost:$port/health 2>/dev/null)
            if [ "$status" = "200" ]; then
                echo -e "Proxy Service (localhost:$port): ${GREEN}✓ Online${NC}"
            elif [ "$status" = "000" ]; then
                # Không có service trên port này
                continue
            else
                echo -e "Proxy Service (localhost:$port): ${RED}✗ HTTP $status${NC}"
            fi
        done
        ;;
    
    *)
        print_header
        echo "Usage: proxy-ctl <command> [options]"
        echo ""
        echo -e "${YELLOW}Service Commands:${NC}"
        echo "  status, s          Show PM2 and Nginx status"
        echo "  start              Start all services"
        echo "  stop               Stop all services"
        echo "  restart, r         Restart all services"
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
