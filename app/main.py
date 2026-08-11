"""Application factory and entrypoint."""
import threading

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from . import backup, config
from .db import SessionLocal, init_db
from .deps import get_current_user
from .models import User, STAFF_ROLES
from .routes import account, admin, auth, labs, notifications

# Paths a user with a pending password change may still reach.
_PW_CHANGE_ALLOWED = {"/account/password", "/logout", "/login"}


async def _enforce_password_change(request, call_next):
    """Redirect users with a pending password change to the change form."""
    path = request.url.path
    user_id = request.session.get("user_id")
    allowed = path in _PW_CHANGE_ALLOWED or path.startswith("/static")
    if user_id and not allowed:
        db = SessionLocal()
        try:
            user = db.get(User, user_id)
        finally:
            db.close()
        if user is not None and user.must_change_password:
            return RedirectResponse("/account/password", status_code=303)
    return await call_next(request)


def create_app() -> FastAPI:
    # Disable the built-in docs (they load Swagger assets from a CDN the HPE VPN
    # blocks). We serve an admin-gated, self-hosted Swagger UI below.
    app = FastAPI(
        title="HOLO", root_path=config.ROOT_PATH,
        docs_url=None, redoc_url=None, openapi_url=None,
    )

    # Added first = inner; SessionMiddleware added last = outer, so request.session
    # is populated by the time the enforcement middleware runs.
    app.add_middleware(BaseHTTPMiddleware, dispatch=_enforce_password_change)
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.SECRET_KEY,
        session_cookie=config.COOKIE_NAME,
        https_only=config.COOKIE_SECURE,
        same_site="lax",
    )

    app.mount(
        "/static",
        StaticFiles(directory=str(config.BASE_DIR / "app" / "static")),
        name="static",
    )

    app.include_router(auth.router)
    app.include_router(account.router)
    app.include_router(admin.router)
    app.include_router(notifications.router)
    app.include_router(labs.router)

    # --- Admin-only, self-hosted API docs (Swagger) --------------------------
    _root = config.ROOT_PATH.rstrip("/")

    @app.get("/openapi.json", include_in_schema=False)
    def holo_openapi(user=Depends(get_current_user)):
        if user is None:
            return RedirectResponse(f"{_root}/login", status_code=303)
        if user.role not in STAFF_ROLES:
            return RedirectResponse(f"{_root}/", status_code=303)
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False)
    def holo_docs(user=Depends(get_current_user)):
        if user is None:
            return RedirectResponse(f"{_root}/login", status_code=303)
        if user.role not in STAFF_ROLES:
            return RedirectResponse(f"{_root}/", status_code=303)
        return get_swagger_ui_html(
            openapi_url=f"{_root}/openapi.json",
            title="HOLO API — Swagger",
            swagger_js_url=f"{_root}/static/vendor/swagger/swagger-ui-bundle.js",
            swagger_css_url=f"{_root}/static/vendor/swagger/swagger-ui.css",
        )

    init_db()

    # Daily DB backup scheduler (in-process; single container).
    threading.Thread(target=backup.run_daily_loop, daemon=True).start()

    return app


app = create_app()
