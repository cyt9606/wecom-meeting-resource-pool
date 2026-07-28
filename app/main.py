from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .access_control import (
    WECOM_ONLY_ERROR_PAGE,
    is_public_path,
    is_wecom_user_agent,
)
from .api import build_api_router
from .auth import build_auth_router
from .config import Settings, get_settings
from .db import Database
from .logging_config import configure_logging
from .repositories import Repository
from .wecom import WeComClient


configure_logging()
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(settings.DATABASE_URL)
        database.initialize()
        repository = Repository(database)
        repository.sync_resources(settings.WECOM_MEETING_RESOURCE_USERIDS)
        admin_count = repository.bootstrap_admins(settings.WECOM_ADMIN_USERIDS)
        if not admin_count:
            raise RuntimeError("至少需要通过 WECOM_ADMIN_USERIDS 引导一名管理员")
        released = repository.release_expired_holds()
        if released:
            logger.warning("released expired meeting holds count=%d", released)
        app.state.database = database
        app.state.repository = repository
        app.state.wecom = WeComClient(
            settings.WECOM_CORP_ID,
            settings.WECOM_APP_SECRET,
            settings.WECOM_AGENT_ID,
        )
        yield
        await app.state.wecom.close()

    app = FastAPI(
        title="企业微信高级会议资源池",
        version="0.1.0",
        docs_url=None if settings.APP_ENV == "production" else "/debug/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(GZipMiddleware, minimum_size=800)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SESSION_SECRET,
        session_cookie="meeting_pool_session",
        max_age=8 * 60 * 60,
        same_site="lax",
        https_only=settings.APP_BASE_URL.startswith("https://"),
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.monotonic()
        if (
            settings.REQUIRE_WECOM_CLIENT
            and not is_public_path(request.url.path)
            and not is_wecom_user_agent(request.headers.get("user-agent"))
        ):
            if request.url.path.startswith("/api/"):
                response = JSONResponse(
                    status_code=403,
                    content={
                        "detail": "请从企业微信工作台进入",
                        "code": "WECOM_CLIENT_REQUIRED",
                    },
                )
            else:
                response = HTMLResponse(
                    WECOM_ONLY_ERROR_PAGE,
                    status_code=403,
                )
            response.headers["X-WeCom-Client-Required"] = "true"
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; "
            "base-uri 'self'; form-action 'self'"
        )
        logger.info(
            "request method=%s path=%s status=%s duration_ms=%d",
            request.method,
            request.url.path,
            response.status_code,
            int((time.monotonic() - started) * 1000),
            extra={"request_id": request_id},
        )
        return response

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, error: Exception):
        logger.exception(
            "unhandled request error",
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "服务暂时不可用，请稍后重试"},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "wecom-meeting-pool"}

    app.include_router(build_auth_router())
    app.include_router(build_api_router())

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


app = create_app()
