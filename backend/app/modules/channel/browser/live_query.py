"""Job-scoped reads of the personal browser evidence stream."""

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.modules.channel.browser import live_loki
from app.modules.channel.browser.answers import CHANNEL, CONNECTOR
from app.modules.channel.browser.content import require_tool
from app.modules.channel.browser.http import deny
from app.modules.channel.browser.live_capture import LivePage
from app.modules.channel.browser.recordings import contract
from app.modules.channel.browser.scope import active_app
from app.modules.channel.browser.workshop_bindings import workshop_choices

PAGE_WINDOW_MS = 30 * 60 * 1000
RETENTION_NS = 7 * 86400 * 10**9
SUMMARY_FIELDS = frozenset(
    (
        "action",
        "element",
        "node_id",
        "method",
        "api_path",
        "api_origin",
        "request_key",
        "baseline_id",
        "trace_id",
        "request_id",
        "side",
        "status",
        "outcome",
        "original_bytes",
        "omitted",
        "numeric_precision",
    )
)


def authorized_job(c: Any, job: str, tool: str) -> dict:
    if tool not in ("search_recording", "get_recording_evidence"):
        raise deny("access_denied", 403)
    row = c.database.execute_one(
        """select p.*,w.environment_id,w.base_id,w.workshop_id,m.origin,m.user_id,m.application_id,
           j.retry_count,j.business_application_publication_id
           from browser_live_job_page p join browser_workshop_binding w on w.id=p.binding_id and w.revision=p.revision
           join browser_workshop_binding head on head.id=w.id and head.is_head=1 and head.enabled=1
           join browser_message_receipt m on m.job_id=p.job_id
           join agent_job j on j.id=m.job_id join agent_session s on s.id=j.session_id
           where p.job_id=? and j.status='RUNNING' and j.cancel_requested_at is null
           and j.source_channel=? and j.source_connector_id=? and s.requester_id=m.user_id
           and j.internal_user_id=m.user_id and j.business_application_id=m.application_id
           and s.business_application_id=m.application_id and m.origin=w.origin and m.user_id=w.user_id
           and m.application_id=w.application_id""",
        (job, CHANNEL, CONNECTOR),
    )
    if not row:
        raise deny("access_denied", 403)
    active = active_app(c, row["origin"], row["user_id"], row["application_id"])
    if not c.business_authorization_service.decide(
        user_id=row["user_id"],
        application_id=row["application_id"],
        tool_identifier=tool,
        stage="tool_call",
    )["allowed"]:
        raise deny("access_denied", 403)
    if active["publication_id"] != row["business_application_publication_id"] or not any(
        all(s[k] == row[k] for k in ("environment_id", "base_id", "workshop_id"))
        for s in workshop_choices(c, row["user_id"], row["application_id"])
    ):
        raise deny("access_denied", 403)
    require_tool(c, job, tool)
    return {**row, "scope_ref": active["scope_ref"]}


def signing_key(c, job, purpose, context):
    if not c.settings.app_config_master_key:
        raise deny("live_evidence_unavailable", 503)
    return hmac.digest(
        c.settings.app_config_master_key.encode(),
        json.dumps(
            [
                "browser-live-v1",
                purpose,
                job["job_id"],
                job["retry_count"],
                job["scope_ref"],
                job["workshop_id"],
                context,
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
        "sha256",
    )


def seal(key, position):
    payload = json.dumps(position, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(hmac.digest(key, payload, "sha256") + payload).decode()


def unseal(key, token):
    raw = base64.b64decode(token, altchars=b"-_", validate=True)
    if len(raw) < 33 or not hmac.compare_digest(raw[:32], hmac.digest(key, raw[32:], "sha256")):
        raise ValueError
    return json.loads(raw[32:])


def bounds(job, scope):
    end = job["asked_ms"]
    if scope == "today":
        local = datetime.fromtimestamp(end / 1000, ZoneInfo(job["timezone"]))
        return int(local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000), end
    return max(0, end - PAGE_WINDOW_MS), end


def candidates(c, job, scope, *, position=(0, "", ""), kind=None, identity=None, limit=1):
    start, end = bounds(job, scope)
    conditions = [
        "r.origin=?",
        "r.user_id=?",
        "r.application_id=?",
        "r.scope_ref=?",
        "w.environment_id=?",
        "w.base_id=?",
        "w.workshop_id=?",
        "e.part_number=0",
        "e.observed_ms between ? and ?",
    ]
    params = [
        job[k]
        for k in (
            "origin",
            "user_id",
            "application_id",
            "scope_ref",
            "environment_id",
            "base_id",
            "workshop_id",
        )
    ]
    params.extend((start, end))
    if scope != "today":
        conditions.append("r.id=?")
        params.append(job["recording_id"])
    if scope == "page":
        conditions.append("p.tab_id=?")
        params.append(job["tab_id"])
    if kind:
        conditions.append("e.kind=?")
        params.append(kind)
    if identity:
        conditions.extend(["r.id=?", "e.event_id=?"])
        params.extend(identity)
    conditions.append("(e.received_ns,e.recording_id,e.event_id)>(?,?,?)")
    params.extend(position)
    return c.database.execute(
        """select e.*,p.binding_id,p.revision from browser_live_evidence_part e
           join browser_live_recording r on r.id=e.recording_id
           join browser_live_page p on p.recording_id=r.id and p.tab_id=e.tab_id and p.document_id=e.document_id
           join browser_workshop_binding w on w.id=p.binding_id and w.revision=p.revision
           join browser_workshop_binding head on head.id=w.id and head.is_head=1 and head.enabled=1
           where """
        + " and ".join(conditions)
        + " order by e.received_ns,e.recording_id,e.event_id limit ?",
        (*params, limit),
    )


def source_scope(c, job, row):
    page = LivePage(**{k: row[k] for k in LivePage.model_fields})
    return live_loki.public_scope(
        c,
        job["origin"],
        job["user_id"],
        job["application_id"],
        job["scope_ref"],
        row["recording_id"],
        page,
    )


def projected_prefix(data):
    # Read scalar fields preceding the large JSON value without loading the full body.
    decoder = json.JSONDecoder()
    text = data.decode("utf-8", errors="ignore").strip()
    fields = {}
    if not text.startswith("{"):
        return fields
    i = 1
    while i < len(text):
        try:
            while i < len(text) and text[i] in " \r\n\t,":
                i += 1
            key, i = decoder.raw_decode(text, i)
            while i < len(text) and text[i].isspace():
                i += 1
            if text[i] != ":":
                break
            i += 1
            while i < len(text) and text[i].isspace():
                i += 1
            if text[i] in "{[":
                break
            val, i = decoder.raw_decode(text, i)
        except (ValueError, IndexError):
            break
        if (
            isinstance(key, str)
            and key in SUMMARY_FIELDS
            and isinstance(val, (str, int))
            and len(str(val)) <= 768
        ):
            fields[key] = val
    return fields


def read_status(scope, row):
    if row["received_ns"] < time.time_ns() - RETENTION_NS:
        return "expired", None
    try:
        data = live_loki.read_part(scope, row)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return "unavailable", None
    return ("visible", data) if data is not None else ("missing_part", None)


def search(c, job, args):
    mode = args.get("scope", "page")
    start, end = bounds(job, mode)
    reply = {
        "hits": [],
        "pending_refs": [],
        "coverage": "open",
        "from_ms": start,
        "to_ms": end,
        "truncated": False,
    }
    if mode != "today" and not job["recording_id"]:
        return {**reply, "coverage": "page_not_recorded"}
    filters = {k: v for k, v in args.items() if k not in ("cursor", "limit")}
    key = signing_key(c, job, "search", filters)
    position = unseal(key, args["cursor"]) if args.get("cursor") else [0, "", ""]
    rows = candidates(c, job, mode, position=position, kind=args.get("kind"), limit=33)
    limit = args.get("limit", 12)
    reference_key = signing_key(c, job, "detail", None)
    bindings = set()
    for row in rows[:32]:
        bindings.add(row["binding_id"])
        scope = source_scope(c, job, row)
        status, data = read_status(scope, row)
        identity = [row["recording_id"], row["event_id"]]
        fields = projected_prefix(data) if data else {}
        field_filters = (
            "request_key",
            "baseline_id",
            "api_path",
            "method",
            "action",
            "trace_id",
            "request_id",
        )
        matches = all(fields.get(k) == args[k] for k in field_filters if k in args)
        if "http_status" in args:
            matches = matches and fields.get("status") == args["http_status"]
        if status != "visible":
            reply["coverage"] = status
        if matches:
            reply["hits"].append(
                {
                    "event_id": row["event_id"],
                    "kind": row["kind"],
                    "recording_id": row["recording_id"],
                    "tab_id": row["tab_id"],
                    "document_id": row["document_id"],
                    "observed_ms": row["observed_ms"],
                    "source_seq": row["source_seq"],
                    "coverage": status,
                    "reference": seal(reference_key, [mode, *identity]),
                    **fields,
                }
            )
        if status in ("missing_part", "unavailable"):
            # A missing line must not block the remainder of the timeline.
            reply["pending_refs"].append(seal(reference_key, [mode, *identity]))
            if status == "unavailable":
                break
        position = [row["received_ns"], *identity]
        if len(reply["hits"]) >= limit:
            break
    if rows and position != [
        rows[-1]["received_ns"],
        rows[-1]["recording_id"],
        rows[-1]["event_id"],
    ]:
        reply["truncated"] = True
    reply["next_cursor"] = seal(key, position)
    if bindings:
        placeholders = ",".join("?" for _ in bindings)
        heads = c.database.execute(
            f"select id from browser_workshop_binding where is_head=1 and enabled=1 and id in ({placeholders})",
            tuple(bindings),
        )
        if len(heads) != len(bindings):
            raise deny("access_denied", 403)
    return reply


def detail(c, job, args):
    reference = args["reference"]
    mode, rid, event_id = unseal(signing_key(c, job, "detail", None), reference)
    rows = candidates(c, job, mode, identity=(rid, event_id))
    if len(rows) != 1:
        raise deny("access_denied", 403)
    first = rows[0]
    scope = source_scope(c, job, first)
    key = signing_key(c, job, "part", reference)
    number = unseal(key, args["cursor"]) if args.get("cursor") else 0
    reply = {
        "event_id": event_id,
        "event_bytes": first["event_bytes"],
        "sha256": first["event_digest"],
        "first": number,
        "parts": [],
        "truncated": False,
    }
    parts = c.database.execute(
        """select * from browser_live_evidence_part where recording_id=? and event_id=?
                        and part_number>=? order by part_number limit 4""",
        (rid, event_id, number),
    )
    logical = bytearray()
    status = "visible"
    for row in parts:
        if number != row["part_number"]:
            break
        status, data = read_status(scope, row)
        if data is None:
            break
        logical.extend(data)
        reply["parts"].append(
            {
                "number": number,
                "sha256": row["part_digest"],
                "data": base64.b64encode(data).decode(),
            }
        )
        number += 1
    done = number == first["part_count"]
    if done and reply["first"] == 0:
        if (
            len(logical) != first["event_bytes"]
            or hashlib.sha256(logical).hexdigest() != first["event_digest"]
        ):
            raise deny("live_evidence_unavailable", 503)
        # Small objects are directly usable by the model. Larger objects page in their original UTF-8 bytes.
        if len(logical) <= 30 * 1024:
            reply.pop("parts")
            if projected_prefix(logical).get("numeric_precision") == "source":
                reply["value_json"] = logical.decode("utf-8")
            else:
                reply["value"] = json.loads(logical)
    if logical and "parts" in reply:
        # Keep an immediately readable excerpt alongside lossless checked bytes.
        reply["excerpt"] = logical[:4096].decode("utf-8", errors="replace")
    if not done and status == "visible":
        status = "partial" if len(parts) == 4 and len(reply["parts"]) == 4 else "missing_part"
    if not candidates(c, job, mode, identity=(rid, event_id)):
        raise deny("access_denied", 403)
    reply.update(
        coverage=status, truncated=not done, next_cursor=seal(key, number) if not done else None
    )
    return reply


def run(c, job_id, attempt, name, args):
    job = authorized_job(c, job_id, name)
    if attempt != job["retry_count"] or not contract(
        "LiveSearch" if name == "search_recording" else "LiveDetail"
    ).is_valid(args):
        raise deny("access_denied", 403)
    try:
        result = search(c, job, args) if name == "search_recording" else detail(c, job, args)
    except (TypeError, KeyError, ValueError, IndexError, OverflowError):
        raise deny("access_denied", 403) from None
    if authorized_job(c, job_id, name) != job:
        raise deny("access_denied", 403)
    if len(json.dumps(result, ensure_ascii=False).encode()) > 256 * 1024:
        raise deny("quota_exceeded", 413)
    return result
