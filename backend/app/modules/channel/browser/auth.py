from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from datetime import UTC, datetime
from html import escape
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.modules.channel.browser.http import BrowserRoute, deny
from app.modules.identity.api.auth_controller import LoginRateLimiter
from app.modules.identity.api.dependencies import container
from app.shared.database import Database
from app.shared.exceptions import PermissionDenied

PREFIX = "/api/browser-extension"
AUTH_PATH = PREFIX + "/auth"
# Derived from the public key in the distributed extension manifest.
CLIENT_ID = "cnofpalbgpkfflagpkbdifgfjmfijfpi"
CALLBACK = f"https://{CLIENT_ID}.chromiumapp.org/"
_limiter = LoginRateLimiter()
headers = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; form-action 'self' https://*.chromiumapp.org; frame-ancestors 'none'; base-uri 'none'",
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def platform_origin(req: Request) -> str:
    # Use the HTTP authority and the scheme resolved by the ASGI server. Forwarding
    # headers from individual requests do not establish a trusted proxy.
    hosts = req.headers.getlist("host")
    scheme = req.scope["scheme"]
    if scheme not in {"http", "https"} or len(hosts) != 1:
        raise deny("access_denied", 403)
    authority = hosts[0].lower()
    if len(authority) > 260 or not re.fullmatch(
        r"(?:[a-z0-9._-]+|\[[0-9a-f:.]+\])(?::[0-9]{1,5})?", authority
    ):
        raise deny("access_denied", 403)
    try:
        url = urlsplit(f"{scheme}://{authority}")
        port = url.port
    except ValueError as exc:
        raise deny("access_denied", 403) from exc
    host = url.hostname
    if not host or port == 0:
        raise deny("access_denied", 403)
    if ":" in host:
        host = f"[{host}]"
    if port is not None and port != (443 if scheme == "https" else 80):
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


def session_row(db: Any, sid: str) -> dict[str, Any]:
    row = db.execute_one(
        """select s.id,s.user_id,s.status,s.idle_expires_at,s.absolute_expires_at,
        u.status as user_status,u.account_type from user_session s join app_user u on u.id=s.user_id
        where s.id=?""",
        (sid,),
    )
    now = int(time.time())
    if not row or row["status"] != "active":
        raise deny("login_required")
    if row["user_status"] != "enabled" or row["account_type"] != "human":
        raise deny("access_denied", 403)
    deadline = min(
        int(datetime.fromisoformat(str(row[k]).replace("Z", "+00:00")).astimezone(UTC).timestamp())
        for k in ("idle_expires_at", "absolute_expires_at")
    )
    if deadline <= now:
        raise deny("login_required")
    return {**row, "deadline": deadline}


def granted(db: Database, session: str, client: str, origin: str) -> bool:
    return bool(
        db.execute_one(
            "select 1 from browser_extension_grant where session_id=? and client_id=? and origin=?",
            (session, client, origin),
        )
    )


def connector_enabled(db: Database) -> bool:
    return bool(
        db.execute_one(
            """select 1 from integration_connector where id='browser-extension'
           and connector_type='browser_extension' and deleted=0 and enabled=1
           and allow_ingress=1 and allow_delivery=1"""
        )
    )


def authenticated_user_and_origin(req: Request) -> tuple[str, str]:
    origin = platform_origin(req)
    value = req.headers.get("authorization", "")
    if not value.startswith("Bearer ") or not (1 <= len(value[7:]) <= 256):
        raise deny("credential_expired")
    if req.headers.get("origin") not in (None, f"chrome-extension://{CLIENT_ID}"):
        raise deny("access_denied", 403)
    db = container(req).database
    if not connector_enabled(db):
        raise deny("access_denied", 403)
    row = db.execute_one(
        """select session_id,expires_at from browser_extension_credential
        where digest=? and kind='access' and client_id=? and origin=?""",
        (digest(value[7:]), CLIENT_ID, origin),
    )
    if not row or int(row["expires_at"]) <= time.time():
        raise deny("credential_expired")
    parent = session_row(db, row["session_id"])
    if not granted(db, row["session_id"], CLIENT_ID, origin):
        raise deny("consent_required")
    return str(parent["user_id"]), origin


class Exchange(BaseModel):
    code: str = Field(min_length=32, max_length=128)
    client_id: str = Field(max_length=64)
    redirect_uri: str = Field(max_length=256)
    code_verifier: str = Field(pattern=r"^[a-zA-Z0-9._~-]{43,128}$")


router = APIRouter(prefix=AUTH_PATH, route_class=BrowserRoute)


@router.get("/continue.js")
def script() -> Response:
    return Response(
        "document.forms[0].requestSubmit()",
        media_type="application/javascript",
        headers=headers,
    )


def page(fields: str, auto: bool = False) -> HTMLResponse:
    return HTMLResponse(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Enterprise Agent 插件授权</title>'
        '<h1>连接 Enterprise Agent</h1><form method="post">'
        + fields
        + "</form>"
        + ('<script src="' + AUTH_PATH + '/continue.js"></script>' if auto else "")
        + "</html>",
        headers=headers,
    )


def login_page(req: Request, form: dict[str, list[str]], origin: str) -> Response:
    c = container(req)
    if req.method == "POST" and form.get("action") == ["login"]:
        username = form.get("username", [""])[0][:120]
        key = f"{username.lower()}:{req.client.host if req.client else ''}"
        _limiter.require(key)
        scoped = origin.startswith("http://")
        try:
            _, tok, csrf_value = c.auth_service.login(
                username=username,
                password=form.get("password", [""])[0],
                extension_origin=origin if scoped else "",
            )
        except PermissionDenied:
            _limiter.record_failure(key)
            raise deny("invalid_credentials") from None
        _limiter.clear(key)
        response = RedirectResponse(req.url.path + "?" + req.url.query, 303, headers=headers)
        cfg = c.settings.identity
        names = (
            ("browser_parent", "browser_csrf")
            if scoped
            else (cfg.session_cookie_name, cfg.csrf_cookie_name)
        )
        for name, value in zip(names, (tok, csrf_value), strict=True):
            response.set_cookie(
                name,
                value,
                secure=origin.startswith("https:"),
                httponly=scoped or name == cfg.session_cookie_name,
                samesite="lax",
                path=AUTH_PATH if scoped else "/",
                max_age=cfg.session_absolute_seconds,
            )
        return response
    return page(
        '<label>平台账号 <input name="username" autocomplete="username" required></label> '
        '<label>密码 <input type="password" name="password" autocomplete="current-password" required></label>'
        '<button name="action" value="login">登录</button>'
    )


async def authorization_form(req: Request, origin: str) -> dict[str, list[str]]:
    form: dict[str, list[str]] = {}
    if req.method == "POST":
        if req.headers.get("origin") != origin:
            raise deny("access_denied", 403)
        if req.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
            raise deny("invalid_request", 400)
        body = bytearray()
        async for chunk in req.stream():
            body.extend(chunk)
            if len(body) > 8192:
                raise deny("invalid_request", 413)
        try:
            form = parse_qs(body.decode("utf8"), max_num_fields=10)
        except ValueError as exc:
            raise deny("invalid_request", 400) from exc

    return form


@router.get("/authorize", operation_id="browser_extension_authorize_form")
@router.post("/authorize", operation_id="browser_extension_authorize_submit")
async def authorize(req: Request) -> Response:
    origin = platform_origin(req)
    form = await authorization_form(req, origin)
    return await run_in_threadpool(authorize_form, req, origin, form)


def authorize_form(req: Request, origin: str, form: dict[str, list[str]]) -> Response:
    q = req.query_params
    state, challenge = q.get("state", ""), q.get("code_challenge", "")
    if (
        q.get("client_id") != CLIENT_ID
        or q.get("redirect_uri") != CALLBACK
        or q.get("code_challenge_method") != "S256"
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge)
        or not re.fullmatch(r"[A-Za-z0-9._~-]{16,128}", state)
    ):
        raise deny("invalid_request", 400)

    def redirect(**params: str) -> RedirectResponse:
        return RedirectResponse(
            CALLBACK + "?" + urlencode({"state": state, **params}),
            status_code=303,
            headers=headers,
        )

    silent = q.get("prompt") == "none"
    c = container(req)
    if not connector_enabled(c.database):
        return redirect(error="access_denied")
    identity = c.settings.identity
    scoped = origin.startswith("http://")
    session_cookie, csrf_cookie = (
        ("browser_parent", "browser_csrf")
        if scoped
        else (identity.session_cookie_name, identity.csrf_cookie_name)
    )
    token, csrf = req.cookies.get(session_cookie, ""), req.cookies.get(csrf_cookie, "")
    try:
        parent = c.auth_service.authenticate_session(
            token, extension_origin=origin if scoped else ""
        )
    except PermissionDenied:
        parent = None
    if not parent:
        return redirect(error="login_required") if silent else login_page(req, form, origin)
    grant_args = (parent.session_id, CLIENT_ID, origin)

    if silent and not granted(c.database, *grant_args):
        return redirect(error="consent_required")
    if req.method == "GET":
        return page(
            "<p>使用 " + escape(parent.display_name) + " 的平台权限提问并查看本人的回答。</p>"
            '<input type="hidden" name="csrf" value="' + escape(csrf, quote=True) + '">'
            '<button name="action" value="allow">同意连接</button>',
            silent,
        )
    if (
        not csrf
        or form.get("csrf") != [csrf]
        or not c.auth_service.verify_csrf(token, csrf, extension_origin=origin if scoped else "")
    ):
        raise deny("access_denied", 403)
    with c.database.unit_of_work():
        session_row(c.database, parent.session_id)
        if not connector_enabled(c.database):
            return redirect(error="access_denied")
        if not silent and form.get("action") == ["allow"]:
            c.database.execute(
                """insert into browser_extension_grant(session_id,client_id,origin) values(?,?,?)
                on conflict(session_id,client_id,origin) do nothing""",
                grant_args,
            )
        if not granted(c.database, *grant_args):
            return redirect(error="consent_required")
        code = secrets.token_urlsafe(32)
        c.database.execute(
            """insert into browser_extension_credential(digest,kind,session_id,client_id,origin,challenge,expires_at)
            values(?,'code',?,?,?,?,?)""",
            (digest(code), *grant_args, challenge, int(time.time()) + 60),
        )
    return redirect(code=code)


@router.post("/token")
def exchange(req: Request, body: Exchange, response: Response) -> dict[str, Any]:
    origin = platform_origin(req)
    if (
        req.headers.get("origin") != f"chrome-extension://{CLIENT_ID}"
        or body.redirect_uri != CALLBACK
        or body.client_id != CLIENT_ID
    ):
        raise deny("access_denied", 403)
    db = container(req).database
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(body.code_verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    now = int(time.time())
    with db.unit_of_work():
        if not connector_enabled(db):
            raise deny("access_denied", 403)
        row = db.execute_one(
            """delete from browser_extension_credential where kind='code' and digest=? and
            challenge=? and client_id=? and origin=? and expires_at>? returning session_id""",
            (digest(body.code), challenge, CLIENT_ID, origin, now),
        )
        if not row:
            raise deny("invalid_grant")
        parent = session_row(db, row["session_id"])
        if not granted(db, row["session_id"], CLIENT_ID, origin):
            raise deny("consent_required")
        token = secrets.token_urlsafe(32)
        exp = min(now + 900, parent["deadline"])
        db.execute(
            """insert into browser_extension_credential(digest,kind,session_id,client_id,origin,challenge,expires_at)
            values(?,'access',?,?,?,'',?)""",
            (digest(token), row["session_id"], CLIENT_ID, origin, exp),
        )
    response.headers["Cache-Control"] = "no-store"
    return {
        "access_token": token,
        "expires_in": exp - now,
        "tenant_id": origin,
        "user_id": parent["user_id"],
    }
