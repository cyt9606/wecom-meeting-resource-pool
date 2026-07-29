from __future__ import annotations

import logging
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import ReservationCreate, validate_policy
from .repositories import Repository, SlotConflict
from .wecom import WeComClient, WeComError


logger = logging.getLogger(__name__)


class ResourceUnavailable(RuntimeError):
    def __init__(self, recommendations: list[datetime] | None = None):
        super().__init__("所选时段的高级会议资源均已占用")
        self.recommendations = recommendations or []


class Scheduler:
    def __init__(self, repository: Repository, wecom: WeComClient):
        self.repository = repository
        self.wecom = wecom

    @staticmethod
    def applicant_is_host(info: dict[str, Any], applicant_userid: str) -> bool:
        applicant = applicant_userid.lower()
        hosts = ((info.get("settings") or {}).get("hosts") or {}).get(
            "userid", []
        )
        explicit_hosts = {str(item).lower() for item in hosts}
        creator_or_admin = {
            str(info.get(key) or "").lower()
            for key in ("creator_userid", "admin_userid")
        }
        # WeCom filters the creator from settings.hosts automatically; the
        # creator nevertheless retains host privileges.
        return applicant in explicit_hosts or applicant in creator_or_admin

    async def remote_busy(
        self,
        resource_userid: str,
        start_at: datetime,
        end_at: datetime,
        buffer_minutes: int,
        *,
        exclude_meetingids: set[str] | None = None,
    ) -> bool:
        buffer = timedelta(minutes=buffer_minutes)
        meetingids = await self.wecom.get_user_meeting_ids(
            resource_userid,
            start_at - buffer,
            end_at + buffer,
        )
        for meetingid in meetingids:
            if meetingid in (exclude_meetingids or set()):
                continue
            try:
                info = await self.wecom.get_meeting_info(meetingid)
            except WeComError:
                # Unknown manual/system meetings must conservatively block allocation.
                return True
            try:
                status = int(info.get("status", 1))
            except (TypeError, ValueError):
                return True
            if status in (1, 2):
                return True
        return False

    async def availability(
        self,
        start_at: datetime,
        duration_minutes: int,
    ) -> dict[str, Any]:
        policy = self.repository.get_policy()
        end_at = start_at + timedelta(minutes=duration_minutes)
        checked = 0
        for resource in self.repository.list_resources():
            checked += 1
            try:
                if not await self.remote_busy(
                    resource["wecom_userid"],
                    start_at,
                    end_at,
                    policy["buffer_minutes"],
                ):
                    return {
                        "available": True,
                        "checked_resources": checked,
                        "display_name": resource["display_name"],
                    }
            except WeComError:
                logger.exception(
                    "resource availability sync failed resource_id=%s",
                    resource["id"],
                )
        return {
            "available": False,
            "checked_resources": checked,
            "recommendations": [
                start_at + timedelta(minutes=30 * step)
                for step in range(1, 4)
            ],
        }

    async def create(
        self,
        applicant_userid: str,
        request: ReservationCreate,
        idempotency_key: str,
    ) -> dict[str, Any]:
        idempotency_key = hashlib.sha256(
            (
                f"{self.wecom.corp_id}\0{applicant_userid.lower()}\0"
                f"{idempotency_key}"
            ).encode("utf-8")
        ).hexdigest()
        existing = self.repository.find_by_idempotency(
            applicant_userid, idempotency_key
        )
        if existing:
            return existing

        policy = self.repository.get_policy()
        validate_policy(
            request,
            now=datetime.now(timezone.utc),
            min_lead_minutes=policy["min_lead_minutes"],
            max_duration_minutes=policy["max_duration_minutes"],
            max_advance_days=policy["max_advance_days"],
        )
        if (
            self.repository.count_pending(applicant_userid)
            >= policy["max_pending_per_user"]
        ):
            raise ValueError(
                f"每人最多保留 {policy['max_pending_per_user']} 个待开始会议"
            )

        await self.wecom.validate_member(applicant_userid)
        last_error: WeComError | None = None
        for resource in self.repository.list_resources():
            try:
                if await self.remote_busy(
                    resource["wecom_userid"],
                    request.start_at,
                    request.end_at,
                    policy["buffer_minutes"],
                ):
                    continue
            except WeComError as error:
                last_error = error
                continue

            try:
                held = self.repository.hold(
                    applicant_userid=applicant_userid,
                    idempotency_key=idempotency_key,
                    resource=resource,
                    title=request.title,
                    description=request.description,
                    start_at=request.start_at,
                    end_at=request.end_at,
                    buffer_minutes=policy["buffer_minutes"],
                    settings={
                        "allow_external_user": request.allow_external_user,
                        "host_userid": applicant_userid,
                        "password": request.password,
                        "enable_waiting_room": request.enable_waiting_room,
                    },
                )
            except SlotConflict:
                continue

            if held["status"] != "HELD":
                return held
            self.repository.mark_creating(held["id"])
            try:
                meetingid = await self.wecom.create_meeting(
                    admin_userid=resource["wecom_userid"],
                    host_userid=applicant_userid,
                    title=request.title,
                    start_at=request.start_at,
                    duration_minutes=request.duration_minutes,
                    description=request.description,
                    allow_external_user=request.allow_external_user,
                    password=request.password,
                    enable_waiting_room=request.enable_waiting_room,
                )
            except WeComError as error:
                last_error = error
                self.repository.fail_and_release(
                    held["id"], error.code, error.safe_message
                )
                continue

            join_info: dict[str, Any] = {}
            try:
                info = await self.wecom.get_meeting_info(meetingid)
                if not self.applicant_is_host(info, applicant_userid):
                    await self.wecom.update_meeting(
                        meetingid,
                        host_userid=applicant_userid,
                        admin_userid=resource["wecom_userid"],
                    )
                    info = await self.wecom.get_meeting_info(meetingid)
                if not self.applicant_is_host(info, applicant_userid):
                    raise WeComError(
                        "校验会议主持人",
                        "host_not_applied",
                        "企业微信未将申请人设置为主持人",
                    )
                join_info = self.wecom.join_info(info)
            except WeComError as error:
                logger.exception(
                    "meeting verification failed; rolling back meetingid=%s",
                    meetingid,
                )
                try:
                    await self.wecom.cancel_meeting(meetingid)
                except WeComError:
                    logger.exception(
                        "rollback cancellation failed meetingid=%s", meetingid
                    )
                self.repository.fail_and_release(
                    held["id"], error.code, error.safe_message
                )
                last_error = error
                continue
            confirmed = self.repository.confirm_created(
                held["id"], meetingid, join_info
            )
            confirmed["resource_display_name"] = resource["display_name"]
            await self._notify_created(applicant_userid, confirmed)
            return confirmed

        recommendations = [
            request.start_at + timedelta(minutes=30 * step)
            for step in range(1, 4)
        ]
        if last_error:
            raise last_error
        raise ResourceUnavailable(recommendations)

    async def _notify_created(
        self, applicant_userid: str, reservation: dict[str, Any]
    ) -> None:
        try:
            local_start = reservation["start_at"].astimezone()
            local_end = reservation["end_at"].astimezone()
            join_info = reservation.get("join_info_json") or {}
            meeting_number = join_info.get("numeric_meeting_code") or "未返回"
            meeting_link = join_info.get("external_join_url") or "未返回"
            await self.wecom.send_text(
                applicant_userid,
                "高级会议已创建\n"
                f"主题：{reservation['title']}\n"
                f"时间：{local_start:%Y-%m-%d %H:%M} - {local_end:%H:%M}\n"
                f"主持人：{applicant_userid}\n"
                f"会议号：{meeting_number}\n"
                f"入会链接：{meeting_link}\n"
                f"会议ID：{reservation['meetingid']}",
            )
        except WeComError:
            logger.exception(
                "meeting notification failed reservation_id=%s",
                reservation["id"],
            )
