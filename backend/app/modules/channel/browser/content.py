"""Shared resource checks. Ids from clients and from the model confer no authority."""

from __future__ import annotations

import time
from typing import Any

from app.modules.channel.browser.answers import CHANNEL, CONNECTOR
from app.modules.channel.browser.scope import active_app
from app.modules.channel.browser.http import deny
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST


def recording(
    c: Any, rid: str, *, user: str | None = None, origin: str | None = None, lock: bool = False
) -> dict[str, Any]:
    suffix = " for update" if lock and c.database.engine == "postgres" else ""
    row = c.database.execute_one("select * from browser_recording where id=?" + suffix, (rid,))
    if not row or (user is not None and (row["user_id"] != user or row["origin"] != origin)):
        raise deny("access_denied", 404)
    active = active_app(c, row["origin"], row["user_id"], row["application_id"])
    if active["scope_ref"] != row["scope_ref"]:
        raise deny("scope_changed", 409)
    if row["state"] in {"expired", "upload_expired"} or row["expires_at"] <= time.time():
        raise deny(
            "upload_expired" if row["state"] in {"uploading", "upload_expired"} else "not_found",
            410,
        )
    return dict(row)


def expected_part(c: Any, rid: str, number: int) -> dict[str, Any]:
    part = c.database.execute_one(
        "select * from browser_recording_part where recording_id=? and part_number=?", (rid, number)
    )
    if not part:
        raise deny("not_found", 404)
    return dict(part)


def require_tool(c: Any, job: str, tool: str) -> None:
    definition = MCP_TOOL_MANIFEST.get(tool)
    snapshot = c.mcp_tool_snapshot_service.verify(job)["snapshot"]
    pubs = c.database.execute_one(
        "select agent_publication_id,business_application_publication_id from agent_job where id=?",
        (job,),
    )
    if (
        not pubs
        or snapshot.get("agent_publication_id") != pubs["agent_publication_id"]
        or snapshot.get("application_publication_id") != pubs["business_application_publication_id"]
    ):
        raise deny("access_denied", 403)
    if not definition or not any(
        item.get("tool_identifier") == tool
        and item.get("server_code") == "tool-mcp"
        and item.get("schema_hash") == definition.schema_hash
        for item in snapshot["tools"]
    ):
        raise deny("access_denied", 403)


def job_recording(c: Any, job: str, tool: str) -> tuple[dict[str, Any], int]:
    row = c.database.execute_one(
        """select br.recording_id,br.scope_ref,j.retry_count,j.internal_user_id,
        mr.origin,j.business_application_publication_id from browser_job_recording br
        join browser_message_receipt mr on mr.job_id=br.job_id
        join agent_job j on j.id=br.job_id join agent_session s on s.id=j.session_id
        where j.id=? and j.status='RUNNING' and j.cancel_requested_at is null and j.source_channel=?
        and j.source_connector_id=? and s.requester_id=mr.user_id and mr.user_id=j.internal_user_id
        and mr.application_id=j.business_application_id and s.business_application_id=mr.application_id""",
        (job, CHANNEL, CONNECTOR),
    )
    if not row:
        raise deny("access_denied", 403)
    rec = recording(c, row["recording_id"], user=row["internal_user_id"], origin=row["origin"])
    if (
        rec["state"] != "ready"
        or rec["scope_ref"] != row["scope_ref"]
        or rec["publication_id"] != row["business_application_publication_id"]
    ):
        raise deny("access_denied", 403)
    if not c.business_authorization_service.decide(
        user_id=rec["user_id"],
        application_id=rec["application_id"],
        tool_identifier=tool,
        stage="tool_call",
    )["allowed"]:
        raise deny("access_denied", 403)
    require_tool(c, job, tool)
    return rec, row["retry_count"]
