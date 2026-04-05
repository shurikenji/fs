"""FastAPI application factory for platform-control."""
from __future__ import annotations

import os
import platform
import time
from contextlib import asynccontextmanager
from html import escape
import secrets

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.deps import get_templates, verify_csrf
from app.operator_client import apply_proxy_state, ensure_wildcard_certificate, get_operator_status
from app.pricing_hub_client import pricing_import_control_plane
from app.pricing_admin import register_pricing_admin_routes
from app.security import require_control_plane_token
from db.database import close_db, init_db
from db.queries import (
    create_activity_log,
    create_deploy_job,
    delete_portal_module,
    delete_proxy_endpoint,
    delete_service_source,
    get_activity_logs,
    get_deploy_jobs,
    get_module_stats,
    get_portal_modules,
    get_proxy_endpoints,
    get_proxy_stats,
    get_public_balance_sources,
    get_public_modules,
    get_public_proxy_status,
    get_service_sources,
    get_source_stats,
    mark_deploy_job_finished,
    toggle_proxy_status,
    upsert_portal_module,
    upsert_proxy_endpoint,
    upsert_service_source,
)


def _client_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown").split(",")[0].strip()


def _system_info() -> dict:
    import shutil
    mem = shutil.disk_usage("/") if os.name != "nt" else None
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        mem_total = int([l for l in lines if l.startswith("MemTotal")][0].split()[1]) * 1024
        mem_avail = int([l for l in lines if l.startswith("MemAvailable")][0].split()[1]) * 1024
        mem_used = mem_total - mem_avail
        mem_pct = round(mem_used / mem_total * 100)
        mem_str = f"{round(mem_used / 1073741824, 1)}GB / {round(mem_total / 1073741824)}GB"
    except Exception:
        mem_total = mem_used = 0
        mem_pct = 0
        mem_str = "N/A"

    try:
        with open("/proc/cpuinfo") as f:
            cpu_count = sum(1 for l in f if l.startswith("processor"))
    except Exception:
        cpu_count = os.cpu_count() or 0

    try:
        uptime_sec = float(open("/proc/uptime").read().split()[0])
        days = int(uptime_sec // 86400)
        hours = int((uptime_sec % 86400) // 3600)
        mins = int((uptime_sec % 3600) // 60)
        if days > 0:
            uptime_str = f"{days}d {hours}h"
        elif hours > 0:
            uptime_str = f"{hours}h {mins}m"
        else:
            uptime_str = f"{mins}m"
    except Exception:
        uptime_str = "N/A"

    return {
        "hostname": platform.node(),
        "platform": f"{platform.system()} {platform.release()}",
        "cpu": f"{cpu_count} cores",
        "memory": mem_str,
        "memory_percent": mem_pct,
        "uptime": uptime_str,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        yield
    finally:
        await close_db()


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _shopbot_serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.shopbot_launch_secret, salt="shopbot-admin-launch")


def _issue_shopbot_launch_token() -> str:
    settings = get_settings()
    now = int(time.time())
    ttl = max(int(settings.shopbot_launch_ttl_seconds), 30)
    payload = {
        "sub": "platform-admin",
        "issuer": settings.public_base_url.rstrip("/"),
        "issued_at": now,
        "expires_at": now + ttl,
        "nonce": secrets.token_urlsafe(16),
    }
    return _shopbot_serializer().dumps(payload)


def _describe_proxy_endpoint_error(exc: Exception) -> str:
    message = str(exc).strip()
    lowered = message.lower()
    if "proxy_endpoints.domain" in lowered or "unique constraint failed: proxy_endpoints.domain" in lowered:
        return "Domain proxy da ton tai. Hay doi domain khac hoac sua proxy hien co."
    if "proxy_endpoints.port" in lowered or "unique constraint failed: proxy_endpoints.port" in lowered:
        return "Port noi bo da duoc su dung. Hay chon port khac."
    if "foreign key constraint failed" in lowered:
        return "Source ID khong hop le hoac khong ton tai."
    if message:
        return message
    return exc.__class__.__name__


async def _require_admin_post(request: Request) -> RedirectResponse | None:
    if not request.session.get("is_admin"):
        return _redirect("/control/login")
    await verify_csrf(request)
    return None


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_title, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=settings.admin_secret)

    import pathlib
    static_dir = pathlib.Path(__file__).resolve().parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    register_pricing_admin_routes(app)

    # ── Public endpoints ─────────────────────────────────────────

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def public_index(request: Request):
        templates = get_templates()
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "modules": await get_public_modules(), "statuses": await get_public_proxy_status()},
        )

    @app.get("/status", response_class=HTMLResponse)
    async def public_status(request: Request):
        templates = get_templates()
        return templates.TemplateResponse("status.html", {"request": request, "statuses": await get_public_proxy_status()})

    # ── Public API ───────────────────────────────────────────────

    @app.get("/api/public/modules")
    async def public_modules():
        return {"modules": await get_public_modules()}

    @app.get("/api/public/status")
    async def public_status_api():
        return {"proxies": await get_public_proxy_status()}

    @app.get("/api/public/balance-sources")
    async def public_balance_sources():
        return {"servers": await get_public_balance_sources()}

    # ── Internal API ─────────────────────────────────────────────

    @app.get("/api/internal/service-sources", dependencies=[Depends(require_control_plane_token)])
    async def internal_service_sources():
        return {"service_sources": await get_service_sources(enabled_only=False)}

    @app.get("/api/internal/proxy-endpoints", dependencies=[Depends(require_control_plane_token)])
    async def internal_proxy_endpoints():
        return {"proxy_endpoints": await get_proxy_endpoints(active_only=False)}

    @app.get("/api/internal/portal-modules", dependencies=[Depends(require_control_plane_token)])
    async def internal_portal_modules():
        return {"portal_modules": await get_portal_modules(public_only=False)}

    @app.get("/api/internal/deploy-jobs", dependencies=[Depends(require_control_plane_token)])
    async def internal_deploy_jobs():
        return {"deploy_jobs": await get_deploy_jobs(limit=20)}

    @app.post("/api/internal/deploy/proxies/sync", dependencies=[Depends(require_control_plane_token)])
    async def internal_deploy_proxies_sync():
        active = await get_proxy_endpoints(active_only=True)
        job_id = await create_deploy_job("proxy_sync", "queued", "proxy-runtime", {"count": len(active)})
        try:
            result = await apply_proxy_state(active)
            await mark_deploy_job_finished(job_id, "success", response_payload=result)
            return {"job_id": job_id, "result": result}
        except Exception as exc:
            await mark_deploy_job_finished(job_id, "failed", error_message=str(exc))
            raise

    # ── Auth ─────────────────────────────────────────────────────

    @app.get("/control/login", response_class=HTMLResponse)
    async def control_login(request: Request):
        templates = get_templates()
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": request.session.pop("flash_error", "")},
        )

    @app.post("/control/login")
    async def control_login_submit(request: Request, password: str = Form(...)):
        await verify_csrf(request)
        ip = _client_ip(request)
        if password != settings.admin_password:
            await create_activity_log("LOGIN_FAILED", "Sai mat khau admin", ip)
            request.session["flash_error"] = "Sai mật khẩu quản trị."
            return _redirect("/control/login")
        request.session["is_admin"] = True
        await create_activity_log("LOGIN", "Dang nhap thanh cong", ip)
        return _redirect("/control")

    @app.post("/control/logout")
    async def control_logout(request: Request):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        await create_activity_log("LOGOUT", "Dang xuat", ip)
        request.session.clear()
        return _redirect("/control/login")

    # ── SSO Shopbot Launch ───────────────────────────────────────

    @app.post("/control/launch/shopbot", response_class=HTMLResponse)
    async def control_launch_shopbot(request: Request):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect

        ip = _client_ip(request)
        await create_activity_log("LAUNCH_SHOPBOT", "Mo Shopbot admin qua SSO", ip)

        action_url = f"{settings.shopbot_admin_url.rstrip('/')}/sso/consume"
        token = _issue_shopbot_launch_token()
        html = f"""
        <!DOCTYPE html>
        <html lang="vi">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Launching Shopbot Admin</title>
            <style>
                body {{
                    margin: 0;
                    min-height: 100vh;
                    display: grid;
                    place-items: center;
                    font-family: 'Inter', -apple-system, sans-serif;
                    background: #F0F2F5;
                    color: #222831;
                }}
                .card {{
                    width: min(92vw, 520px);
                    background: #FFFFFF;
                    border: 1px solid rgba(34,40,49,0.08);
                    border-radius: 20px;
                    padding: 32px;
                    box-shadow: 0 12px 40px rgba(34,40,49,0.08);
                }}
                h1 {{ margin: 0 0 10px; font-size: 1.5rem; font-weight: 700; }}
                p {{ margin: 0 0 8px; color: #4A5568; line-height: 1.6; }}
                button {{
                    margin-top: 12px;
                    padding: 12px 20px;
                    border: 0;
                    border-radius: 10px;
                    background: #00ADB5;
                    color: white;
                    font: 600 14px/1 'Inter', sans-serif;
                    cursor: pointer;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Launching Shopbot Admin</h1>
                <p>Phiên quản trị đang được chuyển sang runtime commerce riêng của Shopbot.</p>
                <p>Nếu trình duyệt không tự chuyển, bấm nút bên dưới.</p>
                <form id="launch-form" method="post" action="{escape(action_url)}">
                    <input type="hidden" name="token" value="{escape(token)}">
                    <button type="submit">Open Shopbot Admin</button>
                </form>
                <p style="margin-top:16px; font-size:13px;">Token có thời hạn ngắn và không chia sẻ cookie với control plane.</p>
            </div>
            <script>document.getElementById('launch-form').submit();</script>
        </body>
        </html>
        """
        return HTMLResponse(html)

    # ── Dashboard ────────────────────────────────────────────────

    @app.get("/control", response_class=HTMLResponse)
    async def control_dashboard(request: Request):
        if not request.session.get("is_admin"):
            return _redirect("/control/login")
        templates = get_templates()
        try:
            operator_status = await get_operator_status()
        except Exception as exc:
            operator_status = {"status": "degraded", "error": str(exc)}
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "service_sources": await get_service_sources(enabled_only=False),
                "proxy_endpoints": await get_proxy_endpoints(active_only=False),
                "portal_modules": await get_portal_modules(public_only=False),
                "deploy_jobs": await get_deploy_jobs(limit=15),
                "activity_logs": await get_activity_logs(limit=15),
                "proxy_stats": await get_proxy_stats(),
                "source_stats": await get_source_stats(),
                "module_stats": await get_module_stats(),
                "operator_status": operator_status,
                "system_info": _system_info(),
                "shopbot_admin_url": settings.shopbot_admin_url.rstrip("/"),
                "flash_message": request.session.pop("flash_message", ""),
                "flash_error": request.session.pop("flash_error", ""),
            },
        )

    # ── Activity Logs Page ───────────────────────────────────────

    @app.get("/control/logs", response_class=HTMLResponse)
    async def control_logs_page(request: Request):
        if not request.session.get("is_admin"):
            return _redirect("/control/login")
        templates = get_templates()
        return templates.TemplateResponse(
            "logs.html",
            {
                "request": request,
                "logs": await get_activity_logs(limit=100),
            },
        )

    # ── Settings Page ────────────────────────────────────────────

    @app.get("/control/settings", response_class=HTMLResponse)
    async def control_settings_page(request: Request):
        if not request.session.get("is_admin"):
            return _redirect("/control/login")
        templates = get_templates()
        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "operator_url": settings.proxy_operator_url,
                "flash_message": request.session.pop("flash_message", ""),
                "flash_error": request.session.pop("flash_error", ""),
            },
        )

    @app.post("/control/settings/password")
    async def control_settings_password(
        request: Request,
        current: str = Form(...),
        newpass: str = Form(...),
        confirm: str = Form(...),
    ):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        if current != settings.admin_password:
            request.session["flash_error"] = "Mật khẩu hiện tại không đúng."
            return _redirect("/control/settings")
        if newpass != confirm:
            request.session["flash_error"] = "Mật khẩu mới không khớp."
            return _redirect("/control/settings")
        if len(newpass) < 6:
            request.session["flash_error"] = "Mật khẩu phải ít nhất 6 ký tự."
            return _redirect("/control/settings")
        # Note: password change requires updating .env file on disk
        await create_activity_log("CHANGE_PASSWORD", "Doi mat khau admin (can cap nhat .env)", ip)
        request.session["flash_message"] = "Yêu cầu đổi mật khẩu đã ghi nhận. Cập nhật ADMIN_PASSWORD trong .env và restart service."
        return _redirect("/control/settings")

    # ── Service Sources CRUD ─────────────────────────────────────

    @app.post("/control/service-sources/save")
    async def control_service_sources_save(
        request: Request,
        source_id: str = Form(...),
        name: str = Form(...),
        upstream_base_url: str = Form(...),
        public_base_url: str = Form(""),
        source_type: str = Form("newapi"),
        enabled: str | None = Form(default=None),
        public_pricing_enabled: str | None = Form(default=None),
        public_balance_enabled: str | None = Form(default=None),
        balance_rate: float = Form(1.0),
        auth_mode: str = Form("header"),
        auth_user_header: str = Form(""),
        auth_user_value: str = Form(""),
        auth_token: str = Form(""),
        auth_cookie: str = Form(""),
        pricing_path: str = Form("/api/pricing"),
        ratio_config_path: str = Form("/api/ratio_config"),
        log_path: str = Form("/api/log/self"),
        token_search_path: str = Form("/api/token/search"),
        notes: str = Form(""),
    ):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        await upsert_service_source(
            source_id.strip(),
            name=name.strip(),
            upstream_base_url=upstream_base_url.strip(),
            public_base_url=public_base_url.strip(),
            source_type=source_type.strip() or "newapi",
            enabled=1 if enabled else 0,
            public_pricing_enabled=1 if public_pricing_enabled else 0,
            public_balance_enabled=1 if public_balance_enabled else 0,
            balance_rate=balance_rate,
            auth_mode=auth_mode.strip() or "header",
            auth_user_header=auth_user_header.strip(),
            auth_user_value=auth_user_value.strip(),
            auth_token=auth_token.strip(),
            auth_cookie=auth_cookie.strip(),
            pricing_path=pricing_path.strip(),
            ratio_config_path=ratio_config_path.strip(),
            log_path=log_path.strip(),
            token_search_path=token_search_path.strip(),
            notes=notes.strip(),
        )
        await create_activity_log("SAVE_SOURCE", f"Luu service source: {source_id.strip()}", ip)
        try:
            result = await pricing_import_control_plane()
            request.session["flash_message"] = (
                f"Đã lưu service source {source_id.strip()} và đồng bộ pricing runtime "
                f"({result.get('sources_imported', 0)} sources)."
            )
        except Exception as exc:
            request.session["flash_error"] = (
                f"Service source đã lưu nhưng pricing runtime chưa đồng bộ được: {exc}"
            )
        return _redirect("/control")

    @app.post("/control/service-sources/delete")
    async def control_service_sources_delete(request: Request, source_id: str = Form(...)):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        await delete_service_source(source_id)
        await create_activity_log("DELETE_SOURCE", f"Xoa service source: {source_id}", ip)
        try:
            result = await pricing_import_control_plane()
            request.session["flash_message"] = (
                f"Đã xóa service source {source_id} và đồng bộ pricing runtime "
                f"({result.get('sources_imported', 0)} sources)."
            )
        except Exception as exc:
            request.session["flash_error"] = (
                f"Service source đã xóa nhưng pricing runtime chưa đồng bộ được: {exc}"
            )
        return _redirect("/control")

    # ── Proxy Endpoints CRUD ─────────────────────────────────────

    @app.post("/control/proxy-endpoints/save")
    async def control_proxy_endpoints_save(
        request: Request,
        endpoint_id: str = Form(...),
        source_id: str = Form(""),
        name: str = Form(...),
        domain: str = Form(...),
        target_host: str = Form(...),
        target_protocol: str = Form("https"),
        tls_skip_verify: str | None = Form(default=None),
        port: int = Form(...),
        status: str = Form("active"),
    ):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        normalized_source_id = source_id.strip() or None
        try:
            await upsert_proxy_endpoint(
                endpoint_id.strip(),
                source_id=normalized_source_id,
                name=name.strip(),
                domain=domain.strip().lower(),
                target_host=target_host.strip(),
                target_protocol=target_protocol.strip() or "https",
                tls_skip_verify=1 if tls_skip_verify else 0,
                port=port,
                status=status.strip() or "active",
            )
            await create_activity_log("SAVE_PROXY", f"Luu proxy endpoint: {endpoint_id.strip()} ({domain.strip()})", ip)
            request.session["flash_message"] = f"Đã lưu proxy endpoint {endpoint_id.strip()}."
        except Exception as exc:
            await create_activity_log("SAVE_PROXY_FAIL", f"Luu proxy that bai: {endpoint_id.strip()} - {exc}", ip)
            request.session["flash_error"] = f"Luu proxy loi: {_describe_proxy_endpoint_error(exc)}"
        return _redirect("/control")

    @app.post("/control/proxy-endpoints/delete")
    async def control_proxy_endpoints_delete(request: Request, endpoint_id: str = Form(...)):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        try:
            await delete_proxy_endpoint(endpoint_id)
            await create_activity_log("DELETE_PROXY", f"Xoa proxy endpoint: {endpoint_id}", ip)
            request.session["flash_message"] = f"Đã xóa proxy endpoint {endpoint_id}."
        except Exception as exc:
            await create_activity_log("DELETE_PROXY_FAIL", f"Xoa proxy that bai: {endpoint_id} - {exc}", ip)
            request.session["flash_error"] = f"Xoa proxy loi: {_describe_proxy_endpoint_error(exc)}"
        return _redirect("/control")

    @app.post("/control/proxy-endpoints/toggle")
    async def control_proxy_endpoints_toggle(request: Request, endpoint_id: str = Form(...)):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        try:
            new_status = await toggle_proxy_status(endpoint_id)
            action = "Bat" if new_status == "active" else "Tat"
            await create_activity_log("TOGGLE_PROXY", f"{action} proxy: {endpoint_id}", ip)
            request.session["flash_message"] = f"Đã {action.lower()} proxy {endpoint_id}."
        except Exception as exc:
            request.session["flash_error"] = f"Toggle proxy lỗi: {exc}"
        return _redirect("/control")

    # ── Portal Modules CRUD ──────────────────────────────────────

    @app.post("/control/portal-modules/save")
    async def control_portal_modules_save(
        request: Request,
        module_id: str = Form(...),
        name: str = Form(...),
        path: str = Form(...),
        public_url: str = Form(""),
        icon: str = Form(""),
        description: str = Form(""),
        enabled: str | None = Form(default=None),
        is_public: str | None = Form(default=None),
        sort_order: int = Form(0),
    ):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        await upsert_portal_module(
            module_id.strip(),
            name=name.strip(),
            path=path.strip(),
            public_url=public_url.strip(),
            icon=icon.strip(),
            description=description.strip(),
            enabled=1 if enabled else 0,
            is_public=1 if is_public else 0,
            sort_order=sort_order,
        )
        await create_activity_log("SAVE_MODULE", f"Luu portal module: {module_id.strip()}", ip)
        request.session["flash_message"] = f"Đã lưu portal module {module_id.strip()}."
        return _redirect("/control")

    @app.post("/control/portal-modules/delete")
    async def control_portal_modules_delete(request: Request, module_id: str = Form(...)):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        await delete_portal_module(module_id)
        await create_activity_log("DELETE_MODULE", f"Xoa portal module: {module_id}", ip)
        request.session["flash_message"] = f"Đã xóa portal module {module_id}."
        return _redirect("/control")

    # ── Deploy Actions ───────────────────────────────────────────

    @app.post("/control/deploy/proxies/sync")
    async def control_deploy_proxies_sync(request: Request):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        active = await get_proxy_endpoints(active_only=True)
        job_id = await create_deploy_job("proxy_sync", "queued", "proxy-runtime", {"count": len(active)})
        try:
            result = await apply_proxy_state(active)
            await mark_deploy_job_finished(job_id, "success", response_payload=result)
            await create_activity_log("PROXY_SYNC", f"Sync {len(active)} proxy xuong runtime - thanh cong", ip)
            request.session["flash_message"] = f"Đã đồng bộ {len(active)} proxy xuống runtime."
        except Exception as exc:
            await mark_deploy_job_finished(job_id, "failed", error_message=str(exc))
            await create_activity_log("PROXY_SYNC_FAIL", f"Sync proxy that bai: {exc}", ip)
            request.session["flash_error"] = f"Proxy sync lỗi: {exc}"
        return _redirect("/control")

    @app.post("/control/deploy/wildcard-cert")
    async def control_deploy_wildcard_cert(request: Request):
        redirect = await _require_admin_post(request)
        if redirect:
            return redirect
        ip = _client_ip(request)
        job_id = await create_deploy_job("wildcard_cert", "queued", "proxy-runtime", {})
        try:
            result = await ensure_wildcard_certificate()
            await mark_deploy_job_finished(job_id, "success", response_payload=result)
            await create_activity_log("WILDCARD_CERT", "Ensure wildcard cert - thanh cong", ip)
            request.session["flash_message"] = "Đã yêu cầu proxy-operator đảm bảo wildcard certificate."
        except Exception as exc:
            await mark_deploy_job_finished(job_id, "failed", error_message=str(exc))
            await create_activity_log("WILDCARD_CERT_FAIL", f"Wildcard cert that bai: {exc}", ip)
            request.session["flash_error"] = f"Wildcard certificate lỗi: {exc}"
        return _redirect("/control")

    return app
