from admin.routers.account_stock import router as account_stock_router
from admin.routers.admin_launch import router as admin_launch_router
from admin.routers.auth import router as auth_router
from admin.routers.broadcast import router as broadcast_router
from admin.routers.categories import router as categories_router
from admin.routers.dashboard import router as dashboard_router
from admin.routers.internal_portal import router as internal_portal_router
from admin.routers.logs import router as logs_router
from admin.routers.orders import router as orders_router
from admin.routers.products import router as products_router
from admin.routers.servers import router as servers_router
from admin.routers.settings import router as settings_router
from admin.routers.users import router as users_router

PUBLIC_ROUTERS = [auth_router, admin_launch_router, internal_portal_router]

PROTECTED_ROUTERS = [
    dashboard_router,
    servers_router,
    categories_router,
    products_router,
    settings_router,
    orders_router,
    users_router,
    account_stock_router,
    logs_router,
    broadcast_router,
]
