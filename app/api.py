from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .auth import CurrentUser, admin_user, current_user
from .models import ReservationCreate, ReservationUpdate, validate_policy
from .repositories import DuplicateResource, LastAdmin, SlotConflict
from .scheduler import ResourceUnavailable, Scheduler
from .wecom import WeComError


class PolicyUpdate(BaseModel):
    buffer_minutes: int | None = Field(default=None, ge=0, le=120)
    min_lead_minutes: int | None = Field(default=None, ge=0, le=1440)
    max_duration_minutes: int | None = Field(default=None, ge=5, le=480)
    max_advance_days: int | None = Field(default=None, ge=1, le=365)
    max_pending_per_user: int | None = Field(default=None, ge=1, le=100)


class ResourceCreate(BaseModel):
    wecom_userid: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    priority: int = Field(default=100, ge=1, le=9999)


class ResourceUpdate(BaseModel):
    wecom_userid: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    priority: int | None = Field(default=None, ge=1, le=9999)
    enabled: bool | None = None


class AdminCreate(BaseModel):
    userid: str = Field(min_length=1, max_length=128)


class RateLimiter:
    def __init__(self, limit: int = 12, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self.events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        bucket = self.events[key]
        while bucket and bucket[0] <= now - self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.limit:
            raise HTTPException(status_code=429, detail="操作过于频繁，请稍后重试")
        bucket.append(now)


limiter = RateLimiter()


def repository(request: Request):
    return request.app.state.repository


def scheduler(request: Request) -> Scheduler:
    return Scheduler(request.app.state.repository, request.app.state.wecom)


def require_same_origin(request: Request) -> None:
    expected = urlparse(request.app.state.settings.APP_BASE_URL).netloc.lower()
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc.lower() != expected:
        raise HTTPException(status_code=403, detail="请求来源无效")
    if request.headers.get("X-Requested-With") != "meeting-pool":
        raise HTTPException(status_code=403, detail="缺少请求校验标记")


def public_reservation(row: dict[str, Any]) -> dict[str, Any]:
    settings = row.get("settings_json") or {}
    join_info = dict(row.get("join_info_json") or {})
    if join_info.get("password") is None and settings.get("password"):
        join_info["password"] = settings["password"]
    return {
        "id": row["id"],
        "status": row["status"],
        "title": row["title"],
        "description": row.get("description", ""),
        "start_at": row["start_at"],
        "end_at": row["end_at"],
        "meetingid": row.get("meetingid"),
        "host_userid": row.get("applicant_userid"),
        "resource_display_name": row.get("resource_display_name"),
        "join_info": join_info,
        "allow_external_user": bool(
            settings.get("allow_external_user", True)
        ),
        "enable_waiting_room": bool(
            settings.get("enable_waiting_room", False)
        ),
        "last_error": row.get("last_error_message"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def resource_unavailable_detail(error: ResourceUnavailable) -> dict[str, Any]:
    return {
        "message": str(error),
        "recommendations": [
            recommendation.isoformat()
            for recommendation in error.recommendations
        ],
    }


def build_api_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["api"])

    @router.get("/me")
    async def me(
        request: Request,
        user: CurrentUser = Depends(current_user),
    ) -> dict[str, Any]:
        policy = repository(request).get_policy()
        return {
            "userid": user.userid,
            "is_admin": user.is_admin,
            "policy": {
                key: policy[key]
                for key in (
                    "buffer_minutes",
                    "min_lead_minutes",
                    "max_duration_minutes",
                    "max_advance_days",
                    "max_pending_per_user",
                )
            },
        }

    @router.get("/availability")
    async def availability(
        request: Request,
        start_at: datetime,
        duration_minutes: int = Query(ge=5, le=480),
        user: CurrentUser = Depends(current_user),
    ) -> dict[str, Any]:
        limiter.check(f"availability:{user.userid}")
        if start_at.tzinfo is None:
            raise HTTPException(status_code=422, detail="时间必须包含时区")
        return await scheduler(request).availability(
            start_at.astimezone(timezone.utc), duration_minutes
        )

    @router.post(
        "/reservations",
        status_code=201,
        dependencies=[Depends(require_same_origin)],
    )
    async def create_reservation(
        request: Request,
        body: ReservationCreate,
        idempotency_key: str = Header(
            min_length=16, max_length=128, alias="Idempotency-Key"
        ),
        user: CurrentUser = Depends(current_user),
    ) -> dict[str, Any]:
        limiter.check(f"create:{user.userid}")
        repo = repository(request)
        try:
            result = await scheduler(request).create(
                user.userid, body, idempotency_key
            )
            repo.audit(
                request.state.request_id,
                user.userid,
                "CREATE",
                "reservation",
                str(result["id"]),
                "SUCCESS",
            )
            return public_reservation(result)
        except ResourceUnavailable as error:
            repo.audit(
                request.state.request_id,
                user.userid,
                "CREATE",
                "reservation",
                None,
                "NO_RESOURCE",
            )
            raise HTTPException(
                status_code=409,
                detail=resource_unavailable_detail(error),
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except WeComError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @router.get("/reservations")
    async def list_reservations(
        request: Request,
        user: CurrentUser = Depends(current_user),
    ) -> list[dict[str, Any]]:
        return [
            public_reservation(row)
            for row in repository(request).list_for_user(user.userid)
        ]

    @router.get("/reservations/{reservation_id}")
    async def get_reservation(
        request: Request,
        reservation_id: uuid.UUID,
        user: CurrentUser = Depends(current_user),
    ) -> dict[str, Any]:
        row = repository(request).get_reservation(reservation_id)
        if not row:
            raise HTTPException(status_code=404, detail="会议申请不存在")
        if row["applicant_userid"].lower() != user.userid.lower() and not user.is_admin:
            raise HTTPException(status_code=403, detail="无权查看该会议")
        return public_reservation(row)

    @router.patch(
        "/reservations/{reservation_id}",
        dependencies=[Depends(require_same_origin)],
    )
    async def update_reservation(
        request: Request,
        reservation_id: uuid.UUID,
        body: ReservationUpdate,
        user: CurrentUser = Depends(current_user),
    ) -> dict[str, Any]:
        limiter.check(f"update:{user.userid}")
        repo = repository(request)
        row = repo.get_reservation(reservation_id)
        if not row:
            raise HTTPException(status_code=404, detail="会议申请不存在")
        if row["applicant_userid"].lower() != user.userid.lower() and not user.is_admin:
            raise HTTPException(status_code=403, detail="无权修改该会议")
        if row["status"] != "CREATED" or row["start_at"] <= datetime.now(timezone.utc):
            raise HTTPException(status_code=409, detail="仅可修改未开始的有效会议")
        policy = repo.get_policy()
        settings = dict(row.get("settings_json") or {})
        join_info = dict(row.get("join_info_json") or {})
        next_start = body.start_at or row["start_at"]
        current_duration = int(
            (row["end_at"] - row["start_at"]).total_seconds() // 60
        )
        next_duration = body.duration_minutes or current_duration
        next_end = next_start + timedelta(minutes=next_duration)
        next_title = body.title or row["title"]
        next_description = (
            body.description
            if body.description is not None
            else row.get("description", "")
        )
        next_allow_external = (
            body.allow_external_user
            if body.allow_external_user is not None
            else bool(settings.get("allow_external_user", True))
        )
        password_provided = "password" in body.model_fields_set
        next_password = (
            body.password
            if password_provided
            else settings.get("password") or join_info.get("password")
        )
        next_waiting_room = (
            body.enable_waiting_room
            if body.enable_waiting_room is not None
            else bool(settings.get("enable_waiting_room", False))
        )
        proposed = ReservationCreate(
            title=next_title,
            start_at=next_start,
            duration_minutes=next_duration,
            description=next_description,
            allow_external_user=next_allow_external,
            password=next_password,
            enable_waiting_room=next_waiting_room,
        )
        time_changed = (
            proposed.start_at != row["start_at"]
            or proposed.end_at != row["end_at"]
        )
        if time_changed:
            try:
                validate_policy(
                    proposed,
                    now=datetime.now(timezone.utc),
                    min_lead_minutes=policy["min_lead_minutes"],
                    max_duration_minutes=policy["max_duration_minutes"],
                    max_advance_days=policy["max_advance_days"],
                )
            except ValueError as error:
                raise HTTPException(
                    status_code=422, detail=str(error)
                ) from error
            try:
                busy = await scheduler(request).remote_busy(
                    row["resource_userid"],
                    proposed.start_at,
                    proposed.end_at,
                    policy["buffer_minutes"],
                    exclude_meetingids={row["meetingid"]},
                )
            except WeComError as error:
                raise HTTPException(status_code=502, detail=str(error)) from error
            if busy:
                raise HTTPException(
                    status_code=409,
                    detail="所选时段的高级会议资源已被占用",
                )
        next_settings = {
            **settings,
            "allow_external_user": proposed.allow_external_user,
            "host_userid": row["applicant_userid"],
            "password": proposed.password,
            "enable_waiting_room": proposed.enable_waiting_room,
        }
        try:
            repo.prepare_update(
                reservation_id,
                current_start=row["start_at"],
                current_end=row["end_at"],
                next_start=proposed.start_at,
                next_end=proposed.end_at,
                buffer_minutes=policy["buffer_minutes"],
            )
        except SlotConflict as error:
            raise HTTPException(
                status_code=409,
                detail="所选时段的高级会议资源已被占用",
            ) from error
        try:
            await request.app.state.wecom.update_meeting(
                row["meetingid"],
                title=proposed.title,
                start_at=proposed.start_at,
                duration_minutes=proposed.duration_minutes,
                description=proposed.description,
                allow_external_user=proposed.allow_external_user,
                password=proposed.password,
                set_password=password_provided,
                enable_waiting_room=proposed.enable_waiting_room,
            )
            if password_provided:
                join_info["password"] = proposed.password
            try:
                info = await request.app.state.wecom.get_meeting_info(
                    row["meetingid"]
                )
                join_info = request.app.state.wecom.join_info(info)
                if (
                    join_info.get("password") is None
                    and proposed.password is not None
                ):
                    join_info["password"] = proposed.password
            except WeComError:
                pass
            updated = repo.finish_update(
                reservation_id,
                title=proposed.title,
                description=proposed.description,
                start_at=proposed.start_at,
                end_at=proposed.end_at,
                buffer_minutes=policy["buffer_minutes"],
                settings=next_settings,
                join_info=join_info,
            )
            updated["resource_display_name"] = row["resource_display_name"]
            repo.audit(
                request.state.request_id,
                user.userid,
                "UPDATE",
                "reservation",
                str(reservation_id),
                "SUCCESS",
            )
            return public_reservation(updated)
        except WeComError as error:
            repo.fail_update(
                reservation_id,
                start_at=row["start_at"],
                end_at=row["end_at"],
                buffer_minutes=policy["buffer_minutes"],
                error_code=error.code,
                error_message=error.safe_message,
            )
            raise HTTPException(status_code=502, detail=str(error)) from error

    @router.post(
        "/reservations/{reservation_id}/cancel",
        dependencies=[Depends(require_same_origin)],
    )
    async def cancel_reservation(
        request: Request,
        reservation_id: uuid.UUID,
        user: CurrentUser = Depends(current_user),
    ) -> dict[str, Any]:
        limiter.check(f"cancel:{user.userid}")
        repo = repository(request)
        row = repo.get_reservation(reservation_id)
        if not row:
            raise HTTPException(status_code=404, detail="会议申请不存在")
        if row["applicant_userid"].lower() != user.userid.lower() and not user.is_admin:
            raise HTTPException(status_code=403, detail="无权取消该会议")
        if row["status"] != "CREATED" or row["start_at"] <= datetime.now(timezone.utc):
            raise HTTPException(status_code=409, detail="仅可取消未开始的有效会议")
        repo.set_status(reservation_id, "CANCELLING")
        try:
            await request.app.state.wecom.cancel_meeting(row["meetingid"])
            repo.mark_cancelled(reservation_id)
            repo.audit(
                request.state.request_id,
                user.userid,
                "CANCEL",
                "reservation",
                str(reservation_id),
                "SUCCESS",
            )
            return {"ok": True, "status": "CANCELLED"}
        except WeComError as error:
            repo.set_status(
                reservation_id,
                "RECONCILING",
                error_code=error.code,
                error_message=error.safe_message,
            )
            raise HTTPException(
                status_code=502,
                detail="取消结果暂不确定，系统将保留资源并等待核对",
            ) from error

    @router.get("/admin/resources")
    async def admin_resources(
        request: Request,
        user: CurrentUser = Depends(admin_user),
    ) -> list[dict[str, Any]]:
        del user
        return repository(request).list_resources(enabled_only=False)

    @router.post(
        "/admin/resources",
        status_code=201,
        dependencies=[Depends(require_same_origin)],
    )
    async def create_resource(
        request: Request,
        body: ResourceCreate,
        user: CurrentUser = Depends(admin_user),
    ) -> dict[str, Any]:
        userid = body.wecom_userid.strip()
        display_name = body.display_name.strip()
        if not userid or not display_name:
            raise HTTPException(status_code=422, detail="用户 ID 和资源名称不能为空")
        try:
            await request.app.state.wecom.validate_member(userid)
            row = repository(request).create_resource(
                userid, display_name, body.priority
            )
        except DuplicateResource as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except WeComError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        repository(request).audit(
            request.state.request_id,
            user.userid,
            "RESOURCE_CREATE",
            "resource",
            str(row["id"]),
            "SUCCESS",
            {
                "wecom_userid": userid,
                "display_name": display_name,
                "priority": body.priority,
            },
        )
        return row

    @router.patch(
        "/admin/resources/{resource_id}",
        dependencies=[Depends(require_same_origin)],
    )
    async def update_resource(
        request: Request,
        resource_id: uuid.UUID,
        body: ResourceUpdate,
        user: CurrentUser = Depends(admin_user),
    ) -> dict[str, Any]:
        values = body.model_dump(exclude_none=True)
        if "wecom_userid" in values:
            values["wecom_userid"] = values["wecom_userid"].strip()
            if not values["wecom_userid"]:
                raise HTTPException(status_code=422, detail="企业微信用户 ID 不能为空")
            try:
                await request.app.state.wecom.validate_member(
                    values["wecom_userid"]
                )
            except WeComError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
        if "display_name" in values:
            values["display_name"] = values["display_name"].strip()
            if not values["display_name"]:
                raise HTTPException(status_code=422, detail="资源名称不能为空")
        try:
            row = repository(request).update_resource(resource_id, values)
        except DuplicateResource as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not row:
            raise HTTPException(status_code=404, detail="资源不存在")
        repository(request).audit(
            request.state.request_id,
            user.userid,
            "RESOURCE_UPDATE",
            "resource",
            str(resource_id),
            "SUCCESS",
            values,
        )
        return row

    @router.get("/admin/admins")
    async def list_admins(
        request: Request,
        user: CurrentUser = Depends(admin_user),
    ) -> list[dict[str, Any]]:
        del user
        return repository(request).list_admins()

    @router.post(
        "/admin/admins",
        status_code=201,
        dependencies=[Depends(require_same_origin)],
    )
    async def create_admin(
        request: Request,
        body: AdminCreate,
        user: CurrentUser = Depends(admin_user),
    ) -> dict[str, Any]:
        userid = body.userid.strip()
        if not userid:
            raise HTTPException(status_code=422, detail="管理员用户 ID 不能为空")
        try:
            await request.app.state.wecom.validate_member(userid)
        except WeComError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        row = repository(request).add_admin(userid, user.userid)
        repository(request).audit(
            request.state.request_id,
            user.userid,
            "ADMIN_CREATE",
            "admin",
            row["userid"],
            "SUCCESS",
        )
        return row

    @router.delete(
        "/admin/admins/{userid}",
        dependencies=[Depends(require_same_origin)],
    )
    async def delete_admin(
        request: Request,
        userid: str,
        user: CurrentUser = Depends(admin_user),
    ) -> dict[str, bool]:
        try:
            deleted = repository(request).remove_admin(userid)
        except LastAdmin as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not deleted:
            raise HTTPException(status_code=404, detail="管理员不存在")
        repository(request).audit(
            request.state.request_id,
            user.userid,
            "ADMIN_DELETE",
            "admin",
            deleted["userid"],
            "SUCCESS",
        )
        return {"ok": True}

    @router.get("/admin/policies")
    async def get_policy(
        request: Request,
        user: CurrentUser = Depends(admin_user),
    ) -> dict[str, Any]:
        del user
        return repository(request).get_policy()

    @router.patch(
        "/admin/policies",
        dependencies=[Depends(require_same_origin)],
    )
    async def update_policy(
        request: Request,
        body: PolicyUpdate,
        user: CurrentUser = Depends(admin_user),
    ) -> dict[str, Any]:
        values = body.model_dump(exclude_none=True)
        row = repository(request).update_policy(user.userid, values)
        repository(request).audit(
            request.state.request_id,
            user.userid,
            "POLICY_UPDATE",
            "policy",
            "1",
            "SUCCESS",
            values,
        )
        return row

    return router
