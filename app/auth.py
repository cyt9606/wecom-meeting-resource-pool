from __future__ import annotations

import secrets
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from .config import Settings
from .wecom import WeComClient, WeComError


@dataclass(frozen=True)
class CurrentUser:
    userid: str
    is_admin: bool


def safe_next(value: str | None) -> str:
    if not value:
        return "/"
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/"):
        return "/"
    return value


def current_user(request: Request) -> CurrentUser:
    userid = request.session.get("userid")
    if not isinstance(userid, str) or not userid:
        raise HTTPException(status_code=401, detail="请从企业微信工作台登录")
    return CurrentUser(
        userid=userid,
        is_admin=request.app.state.repository.is_admin(userid),
    )


def admin_user(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def build_auth_router() -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.get("/login")
    async def login(request: Request, next: str = "/") -> RedirectResponse:
        settings: Settings = request.app.state.settings
        state = secrets.token_urlsafe(24)
        request.session["oauth_state"] = state
        request.session["oauth_next"] = safe_next(next)
        callback = f"{settings.APP_BASE_URL}/auth/callback"
        url = WeComClient.oauth_url(settings.WECOM_CORP_ID, callback, state)
        return RedirectResponse(url, status_code=302)

    @router.get("/callback")
    async def callback(
        request: Request, code: str, state: str
    ) -> RedirectResponse:
        expected = request.session.pop("oauth_state", None)
        if not expected or not secrets.compare_digest(expected, state):
            raise HTTPException(status_code=400, detail="登录状态无效，请重新进入应用")
        client: WeComClient = request.app.state.wecom
        try:
            userid = await client.get_user_identity(code)
            await client.validate_member(userid)
        except WeComError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        request.session["userid"] = userid
        destination = safe_next(request.session.pop("oauth_next", "/"))
        return RedirectResponse(destination, status_code=303)

    @router.post("/logout")
    async def logout(request: Request) -> dict[str, bool]:
        request.session.clear()
        return {"ok": True}

    @router.post("/test-login")
    async def test_login(request: Request, userid: str) -> dict[str, str]:
        settings: Settings = request.app.state.settings
        if not settings.ALLOW_TEST_AUTH or settings.APP_ENV == "production":
            raise HTTPException(status_code=404)
        request.session["userid"] = userid
        return {"userid": userid}

    return router
