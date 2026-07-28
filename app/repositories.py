from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg import errors

from .db import Database
from .models import busy_bounds


ACTIVE_RESERVATION_STATUSES = (
    "HELD",
    "CREATING",
    "CREATED",
    "UPDATING",
    "CANCELLING",
    "RECONCILING",
)


class SlotConflict(RuntimeError):
    pass


class DuplicateResource(RuntimeError):
    pass


class LastAdmin(RuntimeError):
    pass


class Repository:
    def __init__(self, database: Database):
        self.database = database

    def sync_resources(self, userids: list[str]) -> None:
        with self.database.connection() as connection:
            for index, userid in enumerate(userids, start=1):
                connection.execute(
                    """
                    INSERT INTO meeting_resource
                        (id, wecom_userid, display_name, priority)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (wecom_userid) DO UPDATE
                    SET updated_at = now()
                    """,
                    (
                        uuid.uuid4(),
                        userid,
                        f"高级会议资源 {index:02d}",
                        index * 10,
                    ),
                )

    def bootstrap_admins(self, userids: list[str]) -> int:
        normalized = list(
            dict.fromkeys(
                userid.strip()
                for userid in userids
                if isinstance(userid, str) and userid.strip()
            )
        )
        with self.database.connection() as connection:
            count = int(
                connection.execute(
                    "SELECT count(*) AS count FROM app_admin"
                ).fetchone()["count"]
            )
            if count:
                return count
            for userid in normalized:
                connection.execute(
                    """
                    INSERT INTO app_admin (userid, created_by)
                    VALUES (%s, 'bootstrap')
                    ON CONFLICT DO NOTHING
                    """,
                    (userid,),
                )
            return len(normalized)

    def is_admin(self, userid: str) -> bool:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM app_admin WHERE lower(userid) = lower(%s)
                ) AS is_admin
                """,
                (userid,),
            ).fetchone()
            return bool(row["is_admin"])

    def list_admins(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT userid, created_by, created_at
                FROM app_admin
                ORDER BY lower(userid)
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def add_admin(self, userid: str, actor: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            existing = connection.execute(
                """
                SELECT userid, created_by, created_at
                FROM app_admin
                WHERE lower(userid) = lower(%s)
                """,
                (userid,),
            ).fetchone()
            if existing:
                return dict(existing)
            row = connection.execute(
                """
                INSERT INTO app_admin (userid, created_by)
                VALUES (%s, %s)
                RETURNING userid, created_by, created_at
                """,
                (userid, actor),
            ).fetchone()
            return dict(row)

    def remove_admin(self, userid: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT userid, created_by, created_at
                FROM app_admin
                ORDER BY lower(userid)
                FOR UPDATE
                """
            ).fetchall()
            target = next(
                (
                    dict(row)
                    for row in rows
                    if row["userid"].lower() == userid.lower()
                ),
                None,
            )
            if not target:
                return None
            if len(rows) <= 1:
                raise LastAdmin("必须至少保留一名管理员")
            connection.execute(
                "DELETE FROM app_admin WHERE userid = %s",
                (target["userid"],),
            )
            return target

    def release_expired_holds(self) -> int:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                UPDATE resource_calendar_slot
                SET status = 'RELEASED', updated_at = now()
                WHERE status = 'HELD'
                  AND hold_expires_at IS NOT NULL
                  AND hold_expires_at < now()
                RETURNING reservation_id
                """
            ).fetchall()
            reservation_ids = [
                row["reservation_id"]
                for row in rows
                if row.get("reservation_id") is not None
            ]
            if reservation_ids:
                connection.execute(
                    """
                    UPDATE reservation
                    SET status = 'FAILED',
                        last_error_code = 'HOLD_EXPIRED',
                        last_error_message = '创建占位超时，已自动释放',
                        updated_at = now()
                    WHERE id = ANY(%s)
                      AND status IN ('HELD', 'CREATING')
                    """,
                    (reservation_ids,),
                )
            return len(rows)

    def list_resources(self, enabled_only: bool = True) -> list[dict[str, Any]]:
        where = "WHERE enabled = true" if enabled_only else ""
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT id, wecom_userid, display_name, priority, enabled,
                       health_status, last_synced_at, allocation_count,
                       allocated_seconds
                FROM meeting_resource
                {where}
                ORDER BY priority, allocated_seconds, allocation_count, id
                """
            ).fetchall()
            return list(rows)

    def create_resource(
        self, userid: str, display_name: str, priority: int
    ) -> dict[str, Any]:
        try:
            with self.database.connection() as connection:
                row = connection.execute(
                    """
                    INSERT INTO meeting_resource
                        (id, wecom_userid, display_name, priority)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                    """,
                    (uuid.uuid4(), userid, display_name, priority),
                ).fetchone()
                return dict(row)
        except errors.UniqueViolation as error:
            raise DuplicateResource("该企业微信用户已配置为高级资源") from error

    def update_resource(
        self, resource_id: uuid.UUID, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {"wecom_userid", "display_name", "priority", "enabled"}
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in values.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = %s")
            params.append(value)
            if key == "enabled":
                assignments.append("health_status = %s")
                params.append("HEALTHY" if value else "DISABLED")
        if not assignments:
            with self.database.connection() as connection:
                row = connection.execute(
                    "SELECT * FROM meeting_resource WHERE id = %s",
                    (resource_id,),
                ).fetchone()
                return dict(row) if row else None
        params.append(resource_id)
        try:
            with self.database.connection() as connection:
                row = connection.execute(
                    f"""
                    UPDATE meeting_resource
                    SET {", ".join(assignments)},
                        version = version + 1, updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    params,
                ).fetchone()
                return dict(row) if row else None
        except errors.UniqueViolation as error:
            raise DuplicateResource("该企业微信用户已配置为高级资源") from error

    def get_policy(self) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM system_policy WHERE id = 1"
            ).fetchone()
            if not row:
                raise RuntimeError("system policy is missing")
            return dict(row)

    def update_policy(self, actor: str, values: dict[str, int]) -> dict[str, Any]:
        allowed = {
            "buffer_minutes",
            "min_lead_minutes",
            "max_duration_minutes",
            "max_advance_days",
            "max_pending_per_user",
        }
        assignments = []
        params: list[Any] = []
        for key, value in values.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = %s")
            params.append(value)
        if not assignments:
            return self.get_policy()
        params.extend([actor])
        with self.database.connection() as connection:
            row = connection.execute(
                f"""
                UPDATE system_policy
                SET {", ".join(assignments)}, updated_by = %s, updated_at = now()
                WHERE id = 1
                RETURNING *
                """,
                params,
            ).fetchone()
            return dict(row)

    def set_resource_enabled(
        self, resource_id: uuid.UUID, enabled: bool
    ) -> dict[str, Any] | None:
        return self.update_resource(resource_id, {"enabled": enabled})

    def find_by_idempotency(
        self, applicant_userid: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT r.*, mr.display_name AS resource_display_name
                FROM reservation r
                JOIN meeting_resource mr ON mr.id = r.resource_id
                WHERE r.applicant_userid = %s AND r.idempotency_key = %s
                """,
                (applicant_userid, idempotency_key),
            ).fetchone()
            return dict(row) if row else None

    def count_pending(self, applicant_userid: str) -> int:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT count(*) AS count
                FROM reservation
                WHERE applicant_userid = %s
                  AND status = ANY(%s)
                  AND end_at > now()
                """,
                (applicant_userid, list(ACTIVE_RESERVATION_STATUSES)),
            ).fetchone()
            return int(row["count"])

    def hold(
        self,
        *,
        applicant_userid: str,
        idempotency_key: str,
        resource: dict[str, Any],
        title: str,
        description: str,
        start_at: datetime,
        end_at: datetime,
        buffer_minutes: int,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        reservation_id = uuid.uuid4()
        slot_id = uuid.uuid4()
        busy_start, busy_end = busy_bounds(
            start_at, end_at, buffer_minutes
        )
        try:
            with self.database.connection() as connection:
                row = connection.execute(
                    """
                    INSERT INTO reservation (
                        id, idempotency_key, applicant_userid, resource_id,
                        title, description, start_at, end_at, status,
                        settings_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'HELD', %s::jsonb)
                    RETURNING *
                    """,
                    (
                        reservation_id,
                        idempotency_key,
                        applicant_userid,
                        resource["id"],
                        title,
                        description,
                        start_at,
                        end_at,
                        json.dumps(settings),
                    ),
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO resource_calendar_slot (
                        id, resource_id, reservation_id, source_type,
                        source_id, busy_range, status, hold_expires_at
                    )
                    VALUES (
                        %s, %s, %s, 'RESERVATION', %s,
                        tstzrange(%s, %s, '[)'), 'HELD', %s
                    )
                    """,
                    (
                        slot_id,
                        resource["id"],
                        reservation_id,
                        str(reservation_id),
                        busy_start,
                        busy_end,
                        datetime.now(timezone.utc) + timedelta(minutes=2),
                    ),
                )
                result = dict(row)
                result["resource_display_name"] = resource["display_name"]
                result["resource_userid"] = resource["wecom_userid"]
                return result
        except errors.ExclusionViolation as error:
            raise SlotConflict("resource time slot overlaps") from error
        except errors.UniqueViolation:
            existing = self.find_by_idempotency(
                applicant_userid, idempotency_key
            )
            if existing:
                return existing
            raise

    def mark_creating(self, reservation_id: uuid.UUID) -> None:
        self._set_status(reservation_id, "CREATING")

    def confirm_created(
        self,
        reservation_id: uuid.UUID,
        meetingid: str,
        join_info: dict[str, Any],
    ) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                UPDATE reservation
                SET status = 'CREATED', meetingid = %s,
                    join_info_json = %s::jsonb, updated_at = now(),
                    last_error_code = NULL, last_error_message = NULL
                WHERE id = %s
                RETURNING *
                """,
                (meetingid, json.dumps(join_info), reservation_id),
            ).fetchone()
            connection.execute(
                """
                UPDATE resource_calendar_slot
                SET status = 'ACTIVE', hold_expires_at = NULL, updated_at = now()
                WHERE reservation_id = %s AND status = 'HELD'
                """,
                (reservation_id,),
            )
            connection.execute(
                """
                UPDATE meeting_resource mr
                SET allocation_count = allocation_count + 1,
                    allocated_seconds = allocated_seconds
                        + EXTRACT(EPOCH FROM (r.end_at - r.start_at))::bigint,
                    updated_at = now()
                FROM reservation r
                WHERE mr.id = r.resource_id AND r.id = %s
                """,
                (reservation_id,),
            )
            if not row:
                raise RuntimeError("reservation disappeared during confirmation")
            return dict(row)

    def fail_and_release(
        self,
        reservation_id: uuid.UUID,
        code: str,
        message: str,
    ) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """
                UPDATE reservation
                SET status = 'FAILED', last_error_code = %s,
                    last_error_message = %s, updated_at = now()
                WHERE id = %s
                """,
                (code, message[:500], reservation_id),
            )
            connection.execute(
                """
                UPDATE resource_calendar_slot
                SET status = 'RELEASED', updated_at = now()
                WHERE reservation_id = %s AND status = 'HELD'
                """,
                (reservation_id,),
            )

    def list_for_user(self, applicant_userid: str) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT r.*, mr.display_name AS resource_display_name
                FROM reservation r
                JOIN meeting_resource mr ON mr.id = r.resource_id
                WHERE r.applicant_userid = %s
                ORDER BY r.start_at DESC
                LIMIT 100
                """,
                (applicant_userid,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_reservation(
        self, reservation_id: uuid.UUID
    ) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT r.*, mr.display_name AS resource_display_name,
                       mr.wecom_userid AS resource_userid
                FROM reservation r
                JOIN meeting_resource mr ON mr.id = r.resource_id
                WHERE r.id = %s
                """,
                (reservation_id,),
            ).fetchone()
            return dict(row) if row else None

    def mark_cancelled(self, reservation_id: uuid.UUID) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """
                UPDATE reservation
                SET status = 'CANCELLED', updated_at = now()
                WHERE id = %s
                """,
                (reservation_id,),
            )
            connection.execute(
                """
                UPDATE resource_calendar_slot
                SET status = 'RELEASED', updated_at = now()
                WHERE reservation_id = %s AND status IN ('HELD', 'ACTIVE')
                """,
                (reservation_id,),
            )

    def update_title(
        self, reservation_id: uuid.UUID, title: str
    ) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                UPDATE reservation
                SET title = %s, status = 'CREATED', updated_at = now(),
                    last_error_code = NULL, last_error_message = NULL
                WHERE id = %s
                RETURNING *
                """,
                (title, reservation_id),
            ).fetchone()
            if not row:
                raise RuntimeError("reservation not found")
            return dict(row)

    def set_status(
        self,
        reservation_id: uuid.UUID,
        status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """
                UPDATE reservation
                SET status = %s, last_error_code = %s,
                    last_error_message = %s, updated_at = now()
                WHERE id = %s
                """,
                (status, error_code, error_message, reservation_id),
            )

    def audit(
        self,
        request_id: str,
        actor: str,
        action: str,
        target_type: str,
        target_id: str | None,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO operation_log (
                    request_id, actor_userid, action, target_type,
                    target_id, result, details_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    request_id,
                    actor,
                    action,
                    target_type,
                    target_id,
                    result,
                    json.dumps(details or {}),
                ),
            )

    def _set_status(self, reservation_id: uuid.UUID, status: str) -> None:
        self.set_status(reservation_id, status)
