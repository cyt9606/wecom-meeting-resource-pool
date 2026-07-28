"""Local-only static UI preview with deterministic sample API responses."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


STATIC = Path(__file__).parents[1] / "app" / "static"
START = datetime.now(timezone.utc) + timedelta(hours=3)


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def do_GET(self):
        responses = {
            "/api/v1/me": {
                "userid": "preview.user",
                "is_admin": True,
                "policy": {
                    "buffer_minutes": 10,
                    "min_lead_minutes": 15,
                    "max_duration_minutes": 480,
                    "max_advance_days": 90,
                    "max_pending_per_user": 10,
                },
            },
            "/api/v1/reservations": [
                {
                    "id": "preview-reservation",
                    "status": "CREATED",
                    "title": "季度项目评审",
                    "description": "",
                    "start_at": START.isoformat(),
                    "end_at": (START + timedelta(hours=2)).isoformat(),
                    "meetingid": "preview-meeting-id",
                    "resource_display_name": "高级会议资源 01",
                    "join_info": {
                        "numeric_meeting_code": "123 456 789",
                        "external_join_url": "https://example.invalid/join",
                    },
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "/api/v1/admin/resources": [
                {
                    "id": "preview-resource",
                    "wecom_userid": "masked",
                    "display_name": "高级会议资源 01",
                    "priority": 10,
                    "enabled": True,
                    "health_status": "HEALTHY",
                    "allocation_count": 12,
                    "allocated_seconds": 43200,
                }
            ],
            "/api/v1/admin/admins": [
                {
                    "userid": "preview.user",
                    "created_by": "bootstrap",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                {
                    "userid": "meeting.admin",
                    "created_by": "preview.user",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            ],
            "/api/v1/admin/policies": {
                "buffer_minutes": 10,
                "min_lead_minutes": 15,
                "max_duration_minutes": 480,
                "max_advance_days": 90,
                "max_pending_per_user": 10,
            },
        }
        if self.path in responses:
            body = json.dumps(responses[self.path], ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 4174), PreviewHandler).serve_forever()
