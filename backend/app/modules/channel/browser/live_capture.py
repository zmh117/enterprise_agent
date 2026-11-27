from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.channel.browser.http import deny
from app.modules.channel.browser.scope import ScopeKey, scope_key
from app.modules.channel.browser.workshop_bindings import workshop_choices

CaptureId = Annotated[str, Field(pattern=r"^[0-9A-Fa-f-]{32,36}$")]


class LivePage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tab_id: CaptureId
    document_id: CaptureId
    binding_id: CaptureId
    revision: int = Field(ge=1)


class RegisterPages(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    recording_id: CaptureId
    pages: list[LivePage] = Field(min_length=1, max_length=100)


def register(c: Any, user: str, origin: str, app: str, scope_ref: str, body: RegisterPages):
    db = c.database
    allowed = {scope_key(s) for s in workshop_choices(c, user, app)}
    if not allowed:
        raise deny("access_denied", 403)
    db.execute(
        """insert into browser_live_recording(id,origin,user_id,application_id,scope_ref,started_at)
           values(?,?,?,?,?,?) on conflict(id) do nothing""",
        (body.recording_id, origin, user, app, scope_ref, datetime.now(UTC).isoformat()),
    )
    if not db.execute_one(
        """select id from browser_live_recording where id=? and origin=? and user_id=?
           and application_id=? and scope_ref=?""",
        (body.recording_id, origin, user, app, scope_ref),
    ):
        raise deny("access_denied", 403)
    for page in body.pages:
        binding = db.execute_one(
            """select environment_id,base_id,workshop_id from browser_workshop_binding where id=? and revision=?
               and user_id=? and origin=? and application_id=? and is_head=1 and enabled=1""",
            (page.binding_id, page.revision, user, origin, app),
        )
        if not binding or scope_key(binding) not in allowed:
            raise deny("access_denied", 403)
        key = (body.recording_id, page.tab_id, page.document_id)
        db.execute(
            """insert into browser_live_page(recording_id,tab_id,document_id,binding_id,revision)
               values(?,?,?,?,?) on conflict(recording_id,tab_id,document_id) do nothing""",
            (*key, page.binding_id, page.revision),
        )
        if not db.execute_one(
            """select recording_id from browser_live_page where recording_id=? and tab_id=?
               and document_id=? and binding_id=? and revision=?""",
            (*key, page.binding_id, page.revision),
        ):
            raise deny("document_scope_conflict", 409)
    return {"recording_id": body.recording_id, "registered": len(body.pages)}


class QuestionPage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    binding_id: CaptureId
    revision: int = Field(ge=1)
    document_id: CaptureId
    recording_id: CaptureId | None
    tab_id: CaptureId | None
    asked_ms: int = Field(ge=1, le=253402300799999)
    timezone: str = Field(min_length=1, max_length=64)


def question_scope(c: Any, origin: str, user: str, app: str, scope_ref: str, page: QuestionPage):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(page.timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise deny("invalid_request", 422) from None
    if (page.recording_id is None) != (page.tab_id is None):
        raise deny("invalid_request", 422)
    binding = c.database.execute_one(
        """select * from browser_workshop_binding where id=? and revision=? and origin=? and user_id=?
           and application_id=? and enabled=1 and is_head=1""",
        (page.binding_id, page.revision, origin, user, app),
    )
    scope = next(
        (
            s
            for s in workshop_choices(c, user, app)
            if binding and scope_key(s) == scope_key(binding)
        ),
        None,
    )
    if not scope:
        raise deny("access_denied", 403)
    if page.recording_id and not c.database.execute_one(
        """select r.id from browser_live_recording r join browser_live_page p on p.recording_id=r.id
           where r.id=? and r.origin=? and r.user_id=? and r.application_id=? and r.scope_ref=?
           and p.tab_id=? and p.document_id=? and p.binding_id=? and p.revision=?""",
        (
            page.recording_id,
            origin,
            user,
            app,
            scope_ref,
            page.tab_id,
            page.document_id,
            page.binding_id,
            page.revision,
        ),
    ):
        raise deny("access_denied", 403)
    return scope


def conversation_scope(c: Any, session: str) -> ScopeKey | None:
    row = c.database.execute_one(
        """select w.environment_id,w.base_id,w.workshop_id from browser_live_job_page p join agent_job j on j.id=p.job_id
           join browser_workshop_binding w on w.id=p.binding_id and w.revision=p.revision
           where j.session_id=? limit 1""",
        (session,),
    )
    return scope_key(row) if row else None
