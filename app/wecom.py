from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx


class WeComError(RuntimeError):
    def __init__(self, operation: str, code: int | str, message: str):
        super().__init__(f"{operation}失败（{code}）：{message}")
        self.operation = operation
        self.code = str(code)
        self.safe_message = message[:300]


@dataclass
class TokenEntry:
    value: str
    expires_at: float


class WeComClient:
    API_BASE = "https://qyapi.weixin.qq.com"

    def __init__(
        self,
        corp_id: str,
        app_secret: str,
        agent_id: int | None = None,
        *,
        http: httpx.AsyncClient | None = None,
    ):
        self.corp_id = corp_id
        self.app_secret = app_secret
        self.agent_id = agent_id
        self.http = http or httpx.AsyncClient(timeout=20)
        self._token: TokenEntry | None = None
        self._token_lock = asyncio.Lock()

    async def close(self) -> None:
        await self.http.aclose()

    async def access_token(self, force: bool = False) -> str:
        now = time.monotonic()
        if not force and self._token and self._token.expires_at > now:
            return self._token.value
        async with self._token_lock:
            now = time.monotonic()
            if not force and self._token and self._token.expires_at > now:
                return self._token.value
            response = await self.http.get(
                f"{self.API_BASE}/cgi-bin/gettoken",
                params={"corpid": self.corp_id, "corpsecret": self.app_secret},
            )
            result = self._decode(response, "获取 access_token")
            self._ensure_success(result, "获取 access_token")
            token = result.get("access_token")
            if not isinstance(token, str) or not token:
                raise WeComError("获取 access_token", "invalid_response", "响应缺少凭证")
            expires_in = int(result.get("expires_in", 7200))
            self._token = TokenEntry(token, now + max(60, expires_in - 300))
            return token

    async def api(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(2):
            token = await self.access_token(force=attempt == 1)
            query = {"access_token": token, **(params or {})}
            response = await self.http.request(
                method,
                f"{self.API_BASE}{path}",
                params=query,
                json=payload,
            )
            result = self._decode(response, operation)
            if result.get("errcode") in (40014, 42001) and attempt == 0:
                continue
            self._ensure_success(result, operation)
            return result
        raise WeComError(operation, "token_retry_failed", "凭证刷新后仍然失败")

    async def get_user_identity(self, code: str) -> str:
        result = await self.api(
            "GET",
            "/cgi-bin/user/getuserinfo",
            operation="获取登录用户身份",
            params={"code": code},
        )
        userid = result.get("UserId") or result.get("userid")
        if not isinstance(userid, str) or not userid:
            raise WeComError("获取登录用户身份", "not_member", "当前用户不是企业成员")
        return userid

    async def validate_member(self, userid: str) -> None:
        await self.api(
            "GET",
            "/cgi-bin/user/get",
            operation="校验企业成员",
            params={"userid": userid},
        )

    async def list_agents(self) -> list[dict[str, Any]]:
        result = await self.api(
            "GET",
            "/cgi-bin/agent/list",
            operation="查询当前应用",
        )
        agents = result.get("agentlist", [])
        return [item for item in agents if isinstance(item, dict)]

    async def get_user_meeting_ids(
        self, userid: str, begin: datetime, end: datetime
    ) -> list[str]:
        cursor = "0"
        ids: list[str] = []
        while True:
            result = await self.api(
                "POST",
                "/cgi-bin/meeting/get_user_meetingid",
                operation="查询成员会议",
                payload={
                    "userid": userid,
                    "cursor": cursor,
                    "begin_time": int(begin.timestamp()),
                    "end_time": int(end.timestamp()),
                    "limit": 100,
                },
            )
            ids.extend(
                item
                for item in result.get("meetingid_list", [])
                if isinstance(item, str)
            )
            next_cursor = str(result.get("next_cursor") or "0")
            if next_cursor in ("", "0", cursor):
                break
            cursor = next_cursor
        return list(dict.fromkeys(ids))

    async def create_meeting(
        self,
        *,
        admin_userid: str,
        host_userid: str,
        title: str,
        start_at: datetime,
        duration_minutes: int,
        description: str,
        allow_external_user: bool,
    ) -> str:
        attendees = list(dict.fromkeys([admin_userid, host_userid]))
        result = await self.api(
            "POST",
            "/cgi-bin/meeting/create",
            operation="创建会议",
            payload={
                "admin_userid": admin_userid,
                "title": title,
                "meeting_start": int(start_at.timestamp()),
                "meeting_duration": duration_minutes * 60,
                "description": description,
                "attendees": {"userid": attendees},
                "settings": {
                    "remind_scope": 2,
                    "enable_waiting_room": False,
                    "allow_enter_before_host": True,
                    "enable_enter_mute": 1,
                    "allow_external_user": allow_external_user,
                    "hosts": {"userid": [host_userid]},
                },
                "reminders": {"is_repeat": 0, "remind_before": [900]},
            },
        )
        meetingid = result.get("meetingid")
        if not isinstance(meetingid, str) or not meetingid:
            raise WeComError("创建会议", "invalid_response", "响应缺少 meetingid")
        return meetingid

    async def get_meeting_info(self, meetingid: str) -> dict[str, Any]:
        return await self.api(
            "POST",
            "/cgi-bin/meeting/get_info",
            operation="查询会议详情",
            payload={"meetingid": meetingid},
        )

    async def update_meeting(
        self,
        meetingid: str,
        *,
        title: str | None = None,
        start_at: datetime | None = None,
        duration_minutes: int | None = None,
        host_userid: str | None = None,
        admin_userid: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"meetingid": meetingid}
        if title is not None:
            payload["title"] = title
        if start_at is not None and duration_minutes is not None:
            payload["meeting_start"] = int(start_at.timestamp())
            payload["meeting_duration"] = duration_minutes * 60
        if host_userid:
            attendees = [host_userid]
            if admin_userid:
                attendees.insert(0, admin_userid)
            payload["attendees"] = {"userid": list(dict.fromkeys(attendees))}
            payload["settings"] = {"hosts": {"userid": [host_userid]}}
        await self.api(
            "POST",
            "/cgi-bin/meeting/update",
            operation="修改会议",
            payload=payload,
        )

    async def cancel_meeting(self, meetingid: str) -> None:
        try:
            await self.api(
                "POST",
                "/cgi-bin/meeting/cancel",
                operation="取消会议",
                payload={"meetingid": meetingid},
            )
        except WeComError as error:
            # Cancellation is idempotent from the resource-pool perspective.
            if error.code == "400041":
                return
            raise

    async def send_text(self, userid: str, content: str) -> bool:
        if not self.agent_id:
            return False
        await self.api(
            "POST",
            "/cgi-bin/message/send",
            operation="发送应用消息",
            payload={
                "touser": userid,
                "msgtype": "text",
                "agentid": self.agent_id,
                "text": {"content": content},
                "safe": 0,
            },
        )
        return True

    @staticmethod
    def join_info(info: dict[str, Any]) -> dict[str, Any]:
        settings = info.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        return {
            "external_join_url": next(
                (
                    info[key]
                    for key in ("join_url", "meeting_url", "meeting_link")
                    if isinstance(info.get(key), str) and info[key]
                ),
                None,
            ),
            "numeric_meeting_code": next(
                (
                    str(info[key])
                    for key in ("meeting_code", "meeting_number")
                    if info.get(key) not in (None, "")
                ),
                None,
            ),
            "password": settings.get("password"),
        }

    @staticmethod
    def oauth_url(corp_id: str, callback_url: str, state: str) -> str:
        query = urlencode(
            {
                "appid": corp_id,
                "redirect_uri": callback_url,
                "response_type": "code",
                "scope": "snsapi_base",
                "state": state,
            }
        )
        return (
            "https://open.weixin.qq.com/connect/oauth2/authorize?"
            f"{query}#wechat_redirect"
        )

    @staticmethod
    def _decode(response: httpx.Response, operation: str) -> dict[str, Any]:
        try:
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise WeComError(operation, "http_error", "企业微信服务暂时不可用") from error
        if not isinstance(result, dict):
            raise WeComError(operation, "invalid_response", "响应格式错误")
        return result

    @staticmethod
    def _ensure_success(result: dict[str, Any], operation: str) -> None:
        if result.get("errcode") != 0:
            raise WeComError(
                operation,
                result.get("errcode", "unknown"),
                str(result.get("errmsg", "未知错误")),
            )
