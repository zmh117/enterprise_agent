from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.channel.browser.http import deny

from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError

CHANNEL = "browser_extension"
CONNECTOR = "browser-extension"
# Includes the negotiated preview allowance. Reserve a disjoint range per attempt.
STRIDE = 4096


def record_delta(db: Database, job_id: str, event: dict[str, Any]) -> None:
    row = db.execute_one(
        "select retry_count,source_connector_id,reply_route_json from agent_job where id=? and source_channel=?",
        (job_id, CHANNEL),
    )
    if not row:
        return
    route = json.loads(row["reply_route_json"])
    attempt = int(row["retry_count"])
    if (
        route.get("type") != CHANNEL
        or route.get("connector_id") != row["source_connector_id"]
        or event["invocation_id"] != f"{job_id}.attempt-{attempt}"
    ):
        return
    payload = event["payload"]
    phase = payload.get("phase", "answer")
    inserted = db.execute_one(
        """insert into browser_answer_delta(job_id,attempt,sequence,body,phase) values(?,?,?,?,?)
           on conflict(job_id,attempt,sequence) do nothing returning sequence""",
        (job_id, attempt, event["sequence"], payload["text"], phase),
    )

    if inserted is None:
        same = db.execute_one(
            "select 1 from browser_answer_delta where job_id=? and attempt=? and sequence=? and body=? and phase=?",
            (job_id, attempt, event["sequence"], payload["text"], phase),
        )
        if not same:
            raise NonRetryableExecutionError(
                "Conflicting replay of assistant text",
                safe_message="回答增量重放不一致",
                error_code="runtime_event_conflict",
            )


def purge_answers(db: Database) -> None:
    cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    db.execute(
        """delete from browser_answer_delta where exists (
        select 1 from agent_job j where j.id=browser_answer_delta.job_id and j.source_channel=?
         and j.status in ('SUCCEEDED','FAILED','TIMEOUT') and j.finished_at < ?
         and (browser_answer_delta.phase='answer' or browser_answer_delta.attempt<>j.retry_count))""",
        (CHANNEL, cutoff),
    )
    db.execute(
        "delete from browser_extension_credential where expires_at < ?",
        (int(datetime.now(UTC).timestamp()) - 900,),
    )


def read_answer(
    db: Database, job: dict[str, Any], cursor: int | None
) -> dict[str, Any] | list[dict[str, Any]]:
    job_id = job["id"]
    attempt = int(job["retry_count"])
    base = attempt * STRIDE
    common = {"job_id": job_id, "attempt_id": f"{job_id}.attempt-{attempt}"}
    status = job["status"]
    state = {"PENDING": "queued", "WAITING_INPUT": "queued", "RETRY_WAIT": "retrying"}.get(
        status, "analyzing"
    )
    # Source sequence 1 is execution_started, never assistant text. Its cursor
    # is available to announce RUNNING before the first public text arrives.
    running = status == "RUNNING"
    state_cursor = base + (2 if running else 1)
    end = base + STRIDE - 1
    terminal: dict[str, Any] = {}
    if status == "SUCCEEDED":
        msg = db.execute_one(
            """select content,created_at from agent_message where job_id=? and session_id=?
            and role='assistant' order by sequence_no desc limit 1""",
            (job_id, job["session_id"]),
        )
        if not msg:
            raise deny("result_pending", 503)
        terminal = {
            "event": "completed",
            "final_answer": msg["content"],
            "answered_at": msg["created_at"],
        }
        duration_ms = job_duration_ms(job["created_at"], job["finished_at"] or msg["created_at"])
        if duration_ms is not None:
            terminal["duration_ms"] = duration_ms
    elif status in {"FAILED", "TIMEOUT"}:
        reason = (
            "timeout"
            if status == "TIMEOUT"
            else "cancelled"
            if job["cancel_requested_at"]
            else "failed"
        )
        terminal = {"event": "failed", "reason": reason}
    if cursor is None and terminal:
        return {
            **common,
            "through_cursor": end,
            "state": terminal["event"],
            **{k: v for k, v in terminal.items() if k != "event"},
        }
    if cursor:
        cursor_attempt, offset = divmod(cursor, STRIDE)
        known = cursor_attempt <= attempt and (
            offset == 1
            or (offset == 2 and (cursor_attempt < attempt or running or terminal))
            or (cursor == end and terminal)
            or db.execute_one(
                "select 1 from browser_answer_delta where job_id=? and attempt=? and sequence=?",
                (job_id, cursor_attempt, offset - 1),
            )
        )
        if not known:
            raise deny("cursor_invalid", 409)
    rows = db.execute(
        """select sequence,body,phase from browser_answer_delta where job_id=? and attempt=?
        and sequence>? order by sequence"""
        + (" limit 16" if cursor is not None else ""),
        (job_id, attempt, max(0, (cursor or 0) - base - 1)),
    )
    if cursor is None:
        last_process = max((r["sequence"] for r in rows if r["phase"] == "process"), default=0)
        return {
            **common,
            "state": state,
            "through_cursor": base + 1 + rows[-1]["sequence"] if rows else state_cursor,
            "draft": "".join(r["body"] for r in rows if r["sequence"] > last_process),
        }
    events: list[dict[str, Any]] = []
    if attempt and cursor < base + 1:
        events.append({**common, "id": base + 1, "event": "reset"})
    if cursor < state_cursor and (not attempt or running) and not terminal:
        events.append({**common, "id": state_cursor, "event": "status", "status": state})
    events.extend(
        {
            **common,
            "event": "answer_delta",
            "id": base + 1 + r["sequence"],
            **({"text": "", "replace": True} if r["phase"] == "process" else {"text": r["body"]}),
        }
        for r in rows
    )
    if terminal and cursor < end and len(rows) < 16:
        events.append({**common, "id": end, **terminal})
    return events


def job_duration_ms(created_at: str, finished_at: str) -> int | None:
    try:
        elapsed = datetime.fromisoformat(finished_at) - datetime.fromisoformat(created_at)
    except (TypeError, ValueError):
        return None
    return elapsed // timedelta(milliseconds=1) if elapsed >= timedelta(0) else None
