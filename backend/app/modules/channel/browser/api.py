from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import nullcontext
import asyncio
import json
import re
import time
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.modules.channel.browser.answers import CHANNEL, CONNECTOR, STRIDE, read_answer
from app.modules.channel.browser.auth import PREFIX, authenticated_user_and_origin
from app.modules.channel.browser.http import BrowserRoute, deny
from app.modules.channel.browser.scope import active_app, fingerprint
from app.modules.channel.browser.recordings import (
    MAX_MANIFEST_BYTES,
    MAX_PART_BYTES,
    parse_initialization,
    reserve,
)
from app.modules.channel.domain.channel_event import (
    ChannelEvent,
    ChannelSource,
    ReplyRoute,
    RoutingContext,
)
from app.modules.identity.api.dependencies import container
from app.modules.job.domain.agent_job import AgentJob
from app.shared.exceptions import AppError
from app.bootstrap import Container


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_message_id: str = Field(pattern=r"^[a-zA-Z0-9._:-]{1,128}$")
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9._:-]{1,128}$")
    recording_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9._:-]{1,128}$")


def receipt(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": row["job_id"],
        "session_id": row["session_id"],
        "conversation_id": row["session_id"],
        "recording_id": row.get("recording_id"),
    }


def message_receipt(
    c: Container, origin: str, user: str, app: str, key: str
) -> dict[str, Any] | None:
    return c.database.execute_one(
        """select r.digest,r.job_id,j.session_id,b.recording_id from browser_message_receipt r
        left join browser_job_recording b on b.job_id=r.job_id
        join agent_job j on j.id=r.job_id where r.origin=? and r.user_id=? and r.application_id=?
        and r.client_message_id=?""",
        (origin, user, app, key),
    )


def visible_job(req: Request, c: Container, job_id: str) -> dict[str, Any]:
    user, origin = authenticated_user_and_origin(req)
    suffix = " for share of j" if c.database.engine == "postgres" else ""
    job = c.database.execute_one(
        """select j.id,j.session_id,j.status,j.cancel_requested_at,j.retry_count,j.created_at,j.finished_at,
        j.business_application_id,j.reply_route_json from agent_job j join agent_session s on s.id=j.session_id
        join browser_message_receipt r on r.job_id=j.id and r.origin=? and r.user_id=? and r.application_id=j.business_application_id
        where j.id=? and j.internal_user_id=? and s.requester_id=? and s.source_channel=? and j.source_channel=?
        and j.source_connector_id=? and s.source_connector_id=? and s.business_application_id=j.business_application_id"""
        + suffix,
        (
            origin,
            user,
            job_id,
            user,
            user,
            CHANNEL,
            CHANNEL,
            CONNECTOR,
            CONNECTOR,
        ),
    )
    if not job:
        raise deny("access_denied", 404)
    route = json.loads(job["reply_route_json"])
    if route.get("type") != CHANNEL or route.get("connector_id") != CONNECTOR:
        raise deny("access_denied", 404)
    active_app(c, origin, user, job["business_application_id"])
    return job


def read(req: Request, job_id: str, cursor: int | None) -> Any:
    c = container(req)
    with c.database.unit_of_work():
        return read_answer(c.database, visible_job(req, c, job_id), cursor)


def private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix=PREFIX, dependencies=[Depends(private_response)], route_class=BrowserRoute
)


@router.get("/applications")
def applications(req: Request) -> list[dict[str, Any]]:
    c = container(req)
    user, origin = authenticated_user_and_origin(req)
    rows = c.database.execute(
        "select distinct application_id from business_application_active_route where trigger_type=? and connector_id=?",
        (CHANNEL, CONNECTOR),
    )
    environments = {
        row["id"]: {"code": row["code"], "name": row["display_name"] or row["code"]}
        for row in c.platform_config_service.list_environments(include_disabled=False)
    }
    out = []
    for row in rows:
        app = row["application_id"]
        try:
            a = active_app(c, origin, user, app)
            c.business_application_resolver.resolve_trigger(
                "local", CHANNEL, CONNECTOR, "application:" + app.lower()
            )
        except (AppError, HTTPException):
            continue
        granted_ids = {
            scope["environment_id"]
            for access in c.authorization_center_repository.business_access_for_user(
                user_id=user, application_id=app
            )
            for scope in access["scopes"]
        }
        out.append(
            {
                "id": app,
                "name": a["name"],
                "scope_ref": a["scope_ref"],
                "environments": [env for key, env in environments.items() if key in granted_ids],
            }
        )
    return out


def recording_owner(
    req: Request, app: str, *, locked: bool = False
) -> tuple[str, str, dict[str, Any]]:
    c = container(req)
    user, origin = authenticated_user_and_origin(req)
    if locked and c.database.engine == "postgres":
        c.database.execute_one("select id from app_user where id=? for update", (user,))
    active = active_app(c, origin, user, app)
    if req.headers.get("x-application-scope") != active["scope_ref"]:
        raise deny("scope_changed", 409)
    return user, origin, active


@router.post("/applications/{app}/recordings")
async def initialize_recording(req: Request, app: str) -> dict[str, Any]:
    await run_in_threadpool(recording_owner, req, app)
    if (
        req.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/json"
        or req.headers.get("content-encoding", "identity") != "identity"
    ):
        raise deny("invalid_request", 415)
    raw = bytearray()
    async for chunk in req.stream():
        if len(raw) + len(chunk) > MAX_MANIFEST_BYTES:
            raise deny("quota_exceeded", 413)
        raw.extend(chunk)

    def admit() -> dict[str, Any]:
        data = parse_initialization(bytes(raw))
        db = container(req).database
        with db.unit_of_work():
            user, origin, active = recording_owner(req, app, locked=True)
            return reserve(db, origin=origin, user=user, app=app, active=active, data=data)

    return await run_in_threadpool(admit)


@router.get("/applications/{app}/messages/{key}")
def lookup(req: Request, app: str, key: str) -> dict[str, Any]:
    c = container(req)
    user, origin = authenticated_user_and_origin(req)
    active_app(c, origin, user, app)
    row = message_receipt(c, origin, user, app, key)
    if not row:
        raise deny("not_found", 404)
    return receipt(row)


def replay_receipt(
    c: Container, origin: str, user: str, app: str, key: str, digest: str
) -> dict[str, Any] | None:
    previous = message_receipt(c, origin, user, app, key)
    if not previous:
        return None
    if digest != previous["digest"]:
        raise deny("message_conflict", 409)
    return receipt(previous)


@router.post("/applications/{app}/messages", status_code=202)
def ask(req: Request, app: str, body: Question) -> dict[str, Any]:
    c = container(req)
    if not body.question.strip() or (
        "conversation_id" in body.model_fields_set and not body.conversation_id
    ):
        raise deny("invalid_request", 422)
    key = body.client_message_id
    digest = fingerprint(body.model_dump(exclude_unset=True))
    with c.database.unit_of_work():
        user, origin = authenticated_user_and_origin(req)
        active = active_app(c, origin, user, app)
        if previous := replay_receipt(c, origin, user, app, key, digest):
            return previous
        if req.headers.get("x-application-scope") != active["scope_ref"]:
            raise deny("scope_changed", 409)
    guard = c.create_agent_job_service.runtime_readiness_guard
    try:
        with guard.admission_check(active["runtime_kind"]) if guard else nullcontext():
            return accept_question(req, app, body, key, digest)
    except AppError as exc:
        raise deny("application_unavailable", 409) from exc


def accept_question(
    req: Request, app: str, body: Question, key: str, digest: str
) -> dict[str, Any]:
    c = container(req)
    with c.database.unit_of_work():
        user, origin = authenticated_user_and_origin(req)
        # Serialize concurrent submissions by this principal, including a lost first receipt.
        suffix = " for update" if c.database.engine == "postgres" else ""
        c.database.execute_one("select id from app_user where id=?" + suffix, (user,))
        active = active_app(c, origin, user, app)
        if previous := replay_receipt(c, origin, user, app, key, digest):
            return previous
        if req.headers.get("x-application-scope") != active["scope_ref"]:
            raise deny("scope_changed", 409)
        identity = fingerprint([origin, user, app, key])
        conversation = identity
        if body.conversation_id:
            row = c.database.execute_one(
                """select s.external_conversation_id from agent_session s
                join agent_job j on j.session_id=s.id join browser_message_receipt r on r.job_id=j.id
                where s.id=? and r.origin=? and r.user_id=? and r.application_id=? and s.source_channel=? limit 1""",
                (body.conversation_id, origin, user, app, CHANNEL),
            )
            if not row:
                raise deny("not_found", 404)
            conversation = row["external_conversation_id"]
        event = ChannelEvent(
            source=ChannelSource(
                CHANNEL,
                CONNECTOR,
                identity,
                user,
                conversation,
                {"application_id": app, "tenant_code": origin},
            ),
            delivery=ReplyRoute(type=CHANNEL, connector_id=CONNECTOR),
            routing=RoutingContext(project_code=active["project_code"]),
            message=body.question,
            idempotency_key="browser:" + identity,
        )
        job = c.channel_ingress_service.accept(event)
        if (
            not isinstance(job, AgentJob)
            or job.business_application_publication_id != active["publication_id"]
        ):
            raise deny("scope_changed", 409)
        c.database.execute(
            """insert into browser_message_receipt(origin,user_id,application_id,client_message_id,digest,job_id)
            values(?,?,?,?,?,?)""",
            (origin, user, app, key, digest, job.id),
        )
        from app.modules.channel.browser.content import recording, require_tool

        selected = body.recording_id
        if "recording_id" not in body.model_fields_set:
            saved = c.database.execute_one(
                "select recording_id from browser_session_recording where session_id=?",
                (job.session_id,),
            )
            selected = saved["recording_id"] if saved else None
        if selected:
            rec = recording(c, selected, user=user, origin=origin, lock=True)
            if (
                rec["application_id"] != app
                or rec["scope_ref"] != active["scope_ref"]
                or rec["state"] != "ready"
            ):
                raise deny("access_denied", 403)
            for tool in ("search_recording", "get_recording_evidence"):
                require_tool(c, job.id, tool)
                if not c.business_authorization_service.decide(
                    user_id=user, application_id=app, tool_identifier=tool
                )["allowed"]:
                    raise deny("access_denied", 403)
            c.database.execute(
                """insert into browser_session_recording(session_id,recording_id,scope_ref) values(?,?,?)
              on conflict(session_id) do update set recording_id=excluded.recording_id,scope_ref=excluded.scope_ref""",
                (job.session_id, selected, rec["scope_ref"]),
            )
            c.database.execute(
                "insert into browser_job_recording(job_id,recording_id,scope_ref) values(?,?,?)",
                (job.id, selected, rec["scope_ref"]),
            )
        elif "recording_id" in body.model_fields_set:
            c.database.execute(
                "delete from browser_session_recording where session_id=?", (job.session_id,)
            )
        return receipt({"job_id": job.id, "session_id": job.session_id, "recording_id": selected})


@router.get("/conversations")
def conversation_list(
    req: Request,
    before: str | None = Query(default=None, max_length=256),
    limit: int = Query(default=30, ge=1, le=100),
    application_id: str | None = Query(default=None, min_length=1, max_length=128),
) -> dict[str, Any]:
    c = container(req)
    with c.database.unit_of_work():
        user, origin = authenticated_user_and_origin(req)
        if application_id is not None:
            active_app(c, origin, user, application_id)
            allowed = [application_id]
        else:
            apps = c.database.execute(
                "select distinct application_id from browser_message_receipt where origin=? and user_id=?",
                (origin, user),
            )
            allowed = []
            for row in apps:
                try:
                    active_app(c, origin, user, row["application_id"])
                except HTTPException as exc:
                    if exc.status_code == 404:
                        continue
                    raise
                allowed.append(row["application_id"])
        if not allowed:
            return {"items": [], "next_before": None}
        places = ",".join("?" for _ in allowed)
        args: list[Any] = [origin, user, CHANNEL, CONNECTOR, CHANNEL, CONNECTOR, *allowed]
        boundary = ""
        if before:
            stamp, sep, sid = before.partition("|")
            if not sep or not stamp or not sid:
                raise deny("cursor_invalid", 409)
            boundary = " and (activity_at, conversation_id) < (?, ?)"
            args.extend([stamp, sid])
        rows = c.database.execute(
            f"""with turns as (
                select s.id as conversation_id,s.business_application_id as application_id,
                       coalesce(s.last_message_at,s.created_at) as activity_at,
                       substr(m.content,1,96) as title,
                       row_number() over(partition by s.id order by m.sequence_no) as position
                  from browser_message_receipt r join agent_job j on j.id=r.job_id
                  join agent_session s on s.id=j.session_id
                  join agent_message m on m.id=j.input_message_id and m.session_id=s.id
                 where r.origin=? and r.user_id=? and s.requester_id=r.user_id and j.internal_user_id=r.user_id
                   and s.source_channel=? and s.source_connector_id=? and j.source_channel=? and j.source_connector_id=?
                   and s.business_application_id=r.application_id and j.business_application_id=r.application_id
                   and r.application_id in ({places})
              ) select conversation_id,application_id,activity_at,title from turns where position=1"""
            + boundary
            + " order by activity_at desc, conversation_id desc limit ?",
            (*args, limit + 1),
        )
        page = rows[:limit]
        return {
            "items": page,
            "next_before": (
                f"{page[-1]['activity_at']}|{page[-1]['conversation_id']}"
                if len(rows) > limit
                else None
            ),
        }


@router.get("/jobs/{job_id}/activity")
def job_activity(req: Request, job_id: str) -> dict[str, Any]:
    from app.shared.tool_response_summary import (
        MAX_TOOL_SUMMARY_SOURCE_CHARS,
        tool_response_summary,
    )

    c = container(req)
    with c.database.unit_of_work():
        job = visible_job(req, c, job_id)
        process = c.database.execute(
            """select body from browser_answer_delta where job_id=? and attempt=? and phase='process'
               order by sequence""",
            (job_id, job["retry_count"]),
        )
        tools = c.database.execute(
            """select id,tool_name,status,duration_ms,created_at,
                 case when length(response_summary)<=? then response_summary end as summary
               from agent_tool_call where job_id=? order by created_at,id""",
            (MAX_TOOL_SUMMARY_SOURCE_CHARS, job_id),
        )
        for tool in tools:
            summary = tool_response_summary(tool["summary"])
            # Plugin users receive safe result facts, never free-form legacy errors.
            tool["summary"] = {k: v for k, v in summary.items() if k != "error"}
        return {"process": "".join(row["body"] for row in process), "tools": tools}


@router.get("/conversations/{conversation}")
def conversation_page(
    req: Request,
    conversation: str,
    before: str | None = None,
    limit: int = Query(default=10, ge=1, le=20),
) -> dict[str, Any]:
    c = container(req)
    with c.database.unit_of_work():
        user, origin = authenticated_user_and_origin(req)
        session = c.database.execute_one(
            """select s.business_application_id,r.id,r.state,r.expires_at,r.scope_ref
            from agent_session s left join browser_session_recording b on b.session_id=s.id
            left join browser_recording r on r.id=b.recording_id
            where s.id=? and s.requester_id=? and s.source_channel=? and s.source_connector_id=?
            and exists(select 1 from browser_message_receipt mr join agent_job j on j.id=mr.job_id
            where j.session_id=s.id and mr.user_id=? and mr.origin=? and mr.application_id=s.business_application_id)""",
            (conversation, user, CHANNEL, CONNECTOR, user, origin),
        )
        if not session:
            raise deny("not_found", 404)
        active = active_app(c, origin, user, session["business_application_id"])
        select = """ from agent_job j join browser_message_receipt mr on mr.job_id=j.id
            join agent_message m on m.id=j.input_message_id and m.session_id=j.session_id
            where j.session_id=? and mr.origin=? and mr.user_id=? and mr.application_id=?
            and j.internal_user_id=mr.user_id and j.business_application_id=mr.application_id
            and j.source_channel=? and j.source_connector_id=? """
        args: tuple[Any, ...] = (
            conversation,
            origin,
            user,
            session["business_application_id"],
            CHANNEL,
            CONNECTOR,
        )
        if before:
            boundary = c.database.execute_one(
                "select m.sequence_no" + select + " and j.id=?", (*args, before)
            )
            if not boundary:
                raise deny("cursor_invalid", 409)
            select += " and m.sequence_no<?"
            args += (boundary["sequence_no"],)
        jobs = c.database.execute(
            """select j.id as job_id,j.status,m.content as question,m.created_at as asked_at,
                      coalesce((select substr(a.content,1,150) from agent_message a
                          where a.job_id=j.id and a.session_id=j.session_id and a.role='assistant'
                          order by a.sequence_no desc limit 1),'') as answer_preview"""
            + select
            + " order by m.sequence_no desc limit ?",
            (*args, limit + 1),
        )
        page = jobs[:limit]
        state = "none"
        if session["id"]:
            state = (
                "ready"
                if (
                    session["state"] == "ready"
                    and session["expires_at"] > time.time()
                    and session["scope_ref"] == active["scope_ref"]
                    and all(
                        c.business_authorization_service.decide(
                            user_id=user,
                            application_id=session["business_application_id"],
                            tool_identifier=name,
                        )["allowed"]
                        for name in ("search_recording", "get_recording_evidence")
                    )
                )
                else "unavailable"
            )
        return {
            "conversation_id": conversation,
            "recording_id": session["id"],
            "recording_state": state,
            "jobs": list(reversed(page)),
            "next_before": page[-1]["job_id"] if len(jobs) > limit else None,
        }


@router.get("/jobs/{job_id}")
def snapshot(req: Request, job_id: str) -> dict[str, Any]:
    return cast(dict[str, Any], read(req, job_id, None))


@router.get("/jobs/{job_id}/events")
async def events(req: Request, job_id: str) -> StreamingResponse:
    raw = req.headers.get("last-event-id", "0")
    if not re.fullmatch(r"0|[1-9][0-9]{0,15}", raw) or int(raw) > 2**53 - 1:
        raise deny("cursor_invalid", 409)
    cursor = int(raw)
    initial = await run_in_threadpool(read, req, job_id, cursor)

    async def follow() -> AsyncIterator[str]:
        nonlocal cursor
        if not initial and cursor % STRIDE == STRIDE - 1:
            return
        heartbeat = time.monotonic()
        while True:
            try:
                batch = await run_in_threadpool(read, req, job_id, cursor)
            except HTTPException:
                return
            if batch:
                frames = []
                for e in batch:
                    cursor = e["id"]
                    data = json.dumps(e, ensure_ascii=False, separators=(",", ":"))
                    frames.append(f"id: {cursor}\nevent: {e['event']}\ndata: {data}\n\n")
                yield "".join(frames)
                if batch[-1]["event"] in {"completed", "failed"}:
                    return
            elif time.monotonic() - heartbeat >= 10:
                yield ": heartbeat\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(0.15 if batch else 0.35)

    return StreamingResponse(
        follow(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )


@router.put("/recordings/{rid}/parts/{number}")
async def upload_part(req: Request, rid: str, number: int) -> dict[str, Any]:
    from app.modules.channel.browser import content, file_client, parts

    c = container(req)

    def authorize(*, lock: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
        user, origin = authenticated_user_and_origin(req)
        rec = content.recording(c, rid, user=user, origin=origin, lock=lock)
        return rec, content.expected_part(c, rid, number)

    _, expected = await run_in_threadpool(authorize)
    if req.headers.get("content-type", "").split(";")[0].strip().lower() != "application/x-ndjson":
        raise deny("invalid_request", 415)
    wire = bytearray()
    async for chunk in req.stream():
        if len(wire) + len(chunk) > MAX_PART_BYTES + 1024:
            raise deny("quota_exceeded", 413)
        wire.extend(chunk)

    def store() -> dict[str, Any]:
        raw, rows = parts.decode_part(
            bytes(wire), req.headers.get("content-encoding", "identity"), expected
        )
        rec, part = authorize()
        result = {"recording_id": rid, "number": number, "sha256": part["sha256"]}
        if part["received_at"] is not None:
            return result
        try:
            file_client.write_part(c, rec, part, raw)
        except HTTPException:
            _, current = authorize()
            if current["received_at"] is not None:
                return result
            raise
        with c.database.unit_of_work():
            rec, part = authorize(lock=True)
            if part["received_at"] is None:
                if rec["state"] != "uploading":
                    raise deny("manifest_conflict", 409)
                parts.record_index(c.database, rid, number, rows)
        return result

    return await run_in_threadpool(store)


@router.post("/recordings/{rid}/complete")
async def complete_recording(req: Request, rid: str) -> dict[str, Any]:
    async for chunk in req.stream():
        if chunk:
            raise deny("invalid_request", 422)
    return await run_in_threadpool(publish_recording, req, rid)


def publish_recording(req: Request, rid: str) -> dict[str, Any]:
    from app.modules.channel.browser import content, parts
    from app.modules.channel.browser.recordings import progress

    c = container(req)
    with c.database.unit_of_work():
        user, origin = authenticated_user_and_origin(req)
        rec = content.recording(c, rid, user=user, origin=origin, lock=True)
        now = int(time.time())
        result = progress(c.database, rec, now)
        if result["missing_parts"]:
            raise HTTPException(
                409, {"code": "parts_missing", "missing_parts": result["missing_parts"]}
            )
        if rec["state"] != "ready":
            parts.check_coverage(c.database, rec)
            # A long verification may cross the browser credential or staging deadline.
            authenticated_user_and_origin(req)
            content.recording(c, rid, user=user, origin=origin)
            c.database.execute(
                "update browser_recording set state='ready',expires_at=? where id=?",
                (int(time.time()) + c.settings.attachments.retention_days * 86400, rid),
            )
        return {"recording_id": rid, "state": "ready", "missing_parts": []}
