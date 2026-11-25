"""Synthetic accounts and jobs only. Exercise the public routes, session and claim boundaries."""

import asyncio
import base64
import hashlib
import json
import re
import secrets
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.bootstrap import build_test_container
from app.modules.channel.browser.api import events as answer_events, router as browser_router
from app.modules.channel.browser.auth import CLIENT_ID, PREFIX, router as browser_auth_router
from app.modules.job.infrastructure.execution_audit_repository import ExecutionAuditRepository
from app.modules.job.infrastructure.execution_control import JobExecutionControl, WorkerLeaseLost
from app.modules.channel.browser.answers import purge_answers, read_answer
from app.python_runtime.browser_answer import BrowserAnswer
from backend.tests.test_agent_run_audit_repository import _tool_contract_event
from backend.tests.helpers import grant_test_application_access
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
    draft_payload,
)


ORIGIN = "http://testserver"


def publish_browser_agent(c, directions=("ingress", "delivery"), *, tools=()):
    from backend.tests.test_agent_profile_model_connections import (
        ADMIN_ID,
        AGENT_CODE,
        agent_config,
        ready_connection,
    )

    c.model_connection_service.dns_resolver = lambda *_, **__: [(2, 1, 6, "", ("1.1.1.1", 443))]
    config = agent_config(ready_connection(c)["id"])
    config["mcp_tool_ids"] = list(tools)
    for direction in directions:
        config["channels"][direction].append("browser-extension")
    config["channels"]["delivery"].append("connector-dingtalk-stream-default")
    service = c.agent_config_service
    before = service.get(AGENT_CODE)["draft"]["revision"]
    draft = service.save_draft(
        actor_id=ADMIN_ID, agent_code=AGENT_CODE, expected_revision=before, config=config
    )
    return service.publish(actor_id=ADMIN_ID, agent_code=AGENT_CODE, revision_id=draft["id"])


def prepare(*, mixed=False, tools=(), secure_cookies=False):
    settings = control_plane_settings()
    settings = replace(settings, identity=replace(settings.identity, cookie_secure=secure_cookies))
    c = build_test_container(settings, migrate=True, seed=True)
    if mixed:
        from backend.tests.support.channels import ensure_active_dingtalk_test_enterprise

        ensure_active_dingtalk_test_enterprise(c)
    publication = publish_browser_agent(c, tools=tools)
    app_id = create_browser_application(
        c, "browser-demo", publication["id"], mixed=mixed, tools=tools
    )
    api = FastAPI()
    api.state.container = c
    api.include_router(browser_router)
    api.include_router(browser_auth_router)
    password = secrets.token_urlsafe(32)
    c.identity_repository.set_password_hash(
        "user_local_admin", c.auth_service.passwords.hash(password)
    )
    return api, app_id, password


def create_browser_application(c, code, publication_id, *, name="合成诊断", mixed=False, tools=()):
    service = c.business_application_service
    app = service.create(
        actor_id="user_local_admin",
        code=code,
        name=name,
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    draft = draft_payload(route="bot:diagnostic-bot" if mixed else "")
    draft["agent_publication_id"] = publication_id
    draft["mcp_tools"] = list(tools)
    route = {
        "connector_id": "browser-extension",
        "trigger_type": "browser_extension",
        "routing_key": "application:" + app["id"],
    }
    draft["triggers"] += [
        {**route, "enabled": True, "actor_policy": "CURRENT_SENDER", "config": {}}
    ]
    draft["deliveries"] += [
        {
            "connector_id": "browser-extension",
            "delivery_type": "reply_original",
            "enabled": True,
            "config": {"trigger": route},
        }
    ]
    draft["session_policy"]["continuous_conversation_enabled"] = True
    revision = service.save_draft(
        actor_id="user_local_admin",
        code=code,
        expected_revision=app["revision"],
        payload=draft,
    )
    pub = service.publish(actor_id="user_local_admin", code=code, revision_id=revision["id"])
    grant_test_application_access(
        c, application_id=app["id"], role_code=code + "-role", capabilities=tools
    )
    service.activate(
        actor_id="user_local_admin",
        code=code,
        environment="local",
        publication_id=pub["id"],
        expected_revision=0,
    )
    return app["id"]


def test_channel_catalog_switch_and_mixed_reply_routes():
    from backend.tests.test_business_application_runtime_routing import _stream_payload
    from app.shared.exceptions import NonRetryableExecutionError

    api, app, password = prepare(mixed=True)
    c = api.state.container
    manage = c.managed_channel_service
    connector = "browser-extension"
    try:
        item = manage.get_channel(connector)
        assert item in manage.list_channels() and item in manage.eligible("browser_extension")
        assert any(row["id"] == connector for row in c.agent_config_service.catalog()["connectors"])
        with TestClient(api, base_url=ORIGIN, follow_redirects=False) as client:
            headers = authorize(client, c, password)

            def send():
                scope = client.get(PREFIX + "/applications", headers=headers).json()[0]["scope_ref"]
                result = client.post(
                    PREFIX + "/applications/" + app + "/messages",
                    headers={**headers, "X-Application-Scope": scope},
                    json={"client_message_id": "mixed", "question": "合成问题"},
                )
                assert result.status_code == 202
                return c.agent_repository.get_job(result.json()["job_id"])

            plugin = send()
            ding = c.dingtalk_stream_message_service.handle_callback(
                payload=_stream_payload(message_id="mixed-channel"), correlation_id="mixed-channel"
            )
            other = c.agent_repository.get_job(ding.job_id)
            assert (
                plugin.business_application_publication_id
                == other.business_application_publication_id
            )
            assert plugin.reply_route["type"] == "browser_extension"
            assert other.reply_route["type"] == "dingtalk_stream_session_webhook"
            disabled = manage.set_enabled(
                connector,
                enabled=False,
                expected_revision=item["revision"],
                actor_id="user_local_admin",
            )
            assert disabled in manage.list_channels() and not manage.eligible("browser_extension")
            for path in ("/applications", "/jobs/" + plugin.id):
                denied = client.get(PREFIX + path, headers=headers)
                assert denied.status_code == 403 and denied.json() == {"code": "access_denied"}
            denied = client.get(
                PREFIX + "/auth/authorize",
                params={
                    "client_id": CLIENT_ID,
                    "redirect_uri": f"https://{CLIENT_ID}.chromiumapp.org/",
                    "state": "s" * 32,
                    "code_challenge": "a" * 43,
                    "code_challenge_method": "S256",
                    "prompt": "none",
                },
            )
            assert denied.status_code == 303
            assert parse_qs(urlsplit(denied.headers["location"]).query) == {
                "state": ["s" * 32],
                "error": ["access_denied"],
            }
            with pytest.raises(NonRetryableExecutionError):
                manage.set_enabled(
                    connector,
                    enabled=True,
                    expected_revision=item["revision"],
                    actor_id="user_local_admin",
                )
            manage.set_enabled(
                connector,
                enabled=True,
                expected_revision=disabled["revision"],
                actor_id="user_local_admin",
            )
            assert send().id == plugin.id
    finally:
        c.database.close()


@pytest.mark.parametrize("direction", ["ingress", "delivery"])
def test_one_way_publication_cannot_enable_plugin(direction):
    from app.shared.exceptions import NonRetryableExecutionError

    c = build_test_container(control_plane_settings(), migrate=True, seed=True)
    try:
        publication = publish_browser_agent(c, directions=[direction])
        service = c.business_application_service
        app = service.create(
            actor_id="user_local_admin",
            code="one-way",
            name="单向",
            description="",
            project_code="default",
            owner_user_id="user_local_admin",
        )
        payload = draft_payload()
        payload["agent_publication_id"] = publication["id"]
        route = {
            "trigger_type": "browser_extension",
            "connector_id": "browser-extension",
            "routing_key": "application:" + app["id"],
        }
        payload["triggers"] = [
            {**route, "enabled": True, "actor_policy": "CURRENT_SENDER", "config": {}}
        ]
        payload["deliveries"] = [
            {
                "delivery_type": "reply_original",
                "connector_id": "browser-extension",
                "enabled": True,
                "config": {"trigger": route},
            }
        ]
        draft = service.save_draft(
            actor_id="user_local_admin",
            code="one-way",
            expected_revision=app["revision"],
            payload=payload,
        )
        with pytest.raises(NonRetryableExecutionError) as invalid:
            service.publish(actor_id="user_local_admin", code="one-way", revision_id=draft["id"])
        assert any(error["field"].startswith("triggers.") for error in invalid.value.field_errors)
    finally:
        c.database.close()


def request_code(client, container, password, user_id="user_local_admin", *, silent=False):
    verifier = secrets.token_urlsafe(40)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    callback = f"https://{CLIENT_ID}.chromiumapp.org/"
    qs = {
        "client_id": CLIENT_ID,
        "state": secrets.token_urlsafe(24),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "redirect_uri": callback,
    }
    path = PREFIX + "/auth/authorize"
    if silent:
        qs["prompt"] = "none"
    else:
        name = container.identity_repository.get_user(user_id)["username"]
        login = client.post(
            path,
            params=qs,
            headers={"origin": str(client.base_url).rstrip("/")},
            data={"action": "login", "username": name, "password": password},
        )
        assert login.status_code == 303
    form = client.get(path, params=qs)
    csrf = re.search('name="csrf" value="([^"]+)"', form.text).group(1)
    denied = client.post(
        path,
        params=qs,
        headers={"origin": str(client.base_url).rstrip("/")},
        data={"action": "allow", "csrf": "synthetic-wrong-csrf"},
    )
    assert denied.status_code == 403 and denied.json() == {"code": "access_denied"}
    allow = client.post(
        path,
        params=qs,
        headers={"origin": str(client.base_url).rstrip("/")},
        data={"action": "allow", "csrf": csrf},
    )
    assert allow.status_code == 303
    ret = parse_qs(urlsplit(allow.headers["location"]).query)
    assert ret["state"] == [qs["state"]]
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": callback,
        "code": ret["code"][0],
        "code_verifier": verifier,
    }
    headers = {"origin": f"chrome-extension://{CLIENT_ID}"}
    return params, headers


def authorize(client, container, password, user_id="user_local_admin", *, silent=False):
    params, headers = request_code(client, container, password, user_id, silent=silent)
    exchange = client.post(PREFIX + "/auth/token", json=params, headers=headers)
    assert exchange.status_code == 200
    assert client.post(PREFIX + "/auth/token", json=params, headers=headers).status_code == 401
    return {"Authorization": "Bearer " + exchange.json()["access_token"]}


def test_competing_exchange_parent_deadline_and_revocation():
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime, timedelta
    from threading import Barrier
    from app.shared.exceptions import PermissionDenied

    api, _, password = prepare()
    c = api.state.container
    try:
        with TestClient(api, base_url=ORIGIN, follow_redirects=False) as client:
            params, headers = request_code(client, c, password)
            parent = client.cookies.get("browser_parent")
            principal = c.auth_service.authenticate_session(parent, extension_origin=ORIGIN)
            with pytest.raises(PermissionDenied):
                c.auth_service.authenticate_session(parent)
            deadline = (datetime.now(UTC) + timedelta(seconds=50)).isoformat()
            c.database.execute(
                "update user_session set absolute_expires_at=? where id=?",
                (deadline, principal.session_id),
            )
            token_url = PREFIX + "/auth/token"
            wrong = {**params, "code_verifier": "x" * 50}
            assert client.post(token_url, json=wrong, headers=headers).status_code == 401
            barrier = Barrier(2)

            def exchange():
                barrier.wait(timeout=5)
                return client.post(token_url, json=params, headers=headers)

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [pool.submit(exchange) for _ in range(2)]
                replies = [result.result(timeout=10) for result in results]
            assert sorted(r.status_code for r in replies) == [200, 401]
            access = next(r.json() for r in replies if r.status_code == 200)
            assert 0 < access["expires_in"] <= 50 and access["user_id"] == principal.user_id
            cred = {"Authorization": "Bearer " + access["access_token"]}
            assert client.get(PREFIX + "/applications", headers=cred).status_code == 200
            c.auth_service.logout(principal)
            assert (
                client.get(PREFIX + "/applications", headers=cred).json()["code"]
                == "login_required"
            )
    finally:
        c.database.close()


def make_member(c, password):
    member = c.identity_repository.create_user(username="demo-operator", display_name="合成操作员")
    c.identity_repository.set_password_hash(member["id"], c.auth_service.passwords.hash(password))
    return member


def test_expired_authorization_code_cannot_be_exchanged():
    api, _, password = prepare()
    c = api.state.container
    try:
        with TestClient(api, base_url=ORIGIN, follow_redirects=False) as client:
            params, headers = request_code(client, c, password)
            c.database.execute(
                "update browser_extension_credential set expires_at=0 where kind='code'"
            )
            response = client.post(PREFIX + "/auth/token", json=params, headers=headers)
            assert response.status_code == 401 and response.json() == {"code": "invalid_grant"}
            assert not c.database.execute_one(
                "select 1 from browser_extension_credential where kind='access'"
            )
    finally:
        c.database.close()


def test_runtime_probe_precedes_atomic_acceptance_and_replay_skips_probe(monkeypatch):
    from app.modules.agent.infrastructure.runtime_readiness import AgentRuntimeReadinessGuard
    from app.shared.database import assert_external_io_allowed

    api, app, password = prepare()
    c = api.state.container
    guard = AgentRuntimeReadinessGuard({})
    attempts = []

    def probe(kind):
        assert_external_io_allowed("browser.acceptance.readiness")
        attempts.append(kind)
        return {"ready": len(attempts) == 1}

    monkeypatch.setattr(guard, "status", probe)
    monkeypatch.setattr(c.create_agent_job_service, "runtime_readiness_guard", guard)
    try:
        with TestClient(api, base_url=ORIGIN, follow_redirects=False) as client:
            headers = authorize(client, c, password)
            scope = client.get(PREFIX + "/applications", headers=headers).json()[0]["scope_ref"]
            headers["X-Application-Scope"] = scope
            path = PREFIX + "/applications/" + app + "/messages"
            body = {"client_message_id": "checked", "question": "合成问题"}
            accepted = client.post(path, headers=headers, json=body)
            assert accepted.status_code == 202
            assert client.post(path, headers=headers, json=body).json() == accepted.json()
            unavailable = client.post(
                path, headers=headers, json={**body, "client_message_id": "later"}
            )
            assert unavailable.status_code == 409 and unavailable.json() == {
                "code": "application_unavailable"
            }
            assert attempts == ["python-v1", "python-v1"]
            assert (
                c.database.execute_one("select count(*) as n from browser_message_receipt")["n"]
                == 1
            )
    finally:
        c.database.close()


@pytest.mark.parametrize("origin", ["http://agent.intra:8080", "https://agent.intra:8443"])
def test_member_uses_system_identity_and_only_active_granted_applications(origin):
    api, app, password = prepare()
    c = api.state.container
    member = make_member(c, password)
    apps = PREFIX + "/applications"
    path = apps + "/" + app + "/messages"
    question = {"client_message_id": "demo-first", "question": "合成提问"}
    try:
        with TestClient(api, base_url=origin, follow_redirects=False) as client:
            headers = authorize(client, c, password, member["id"])
            assert client.get(apps, headers=headers).json() == []
            assert client.post(path, headers=headers, json=question).status_code == 404
            grant_test_application_access(
                c, application_id=app, role_code="operators", user_id=member["id"]
            )
            visible = client.get(apps, headers=headers).json()
            assert [item["id"] for item in visible] == [app]
            submit_headers = {**headers, "X-Application-Scope": visible[0]["scope_ref"]}
            accepted = client.post(path, json=question, headers=submit_headers)
            assert accepted.status_code == 202
            owner = c.database.execute_one(
                "select internal_user_id from agent_job where id=?", (accepted.json()["job_id"],)
            )
            assert owner["internal_user_id"] == member["id"]
            # A different port on the same machine is a different platform origin.
            assert (
                client.get(apps, headers={**headers, "Host": "agent.intra:9999"}).status_code == 401
            )
            c.business_application_service.deactivate(
                actor_id="user_local_admin",
                code="browser-demo",
                environment="local",
                expected_revision=1,
            )
            assert client.get(apps, headers=headers).json() == []
            assert client.post(path, json=question, headers=submit_headers).status_code == 404
    finally:
        c.database.close()


def test_fixed_callback_and_request_origin():
    api, _, _ = prepare()
    path = PREFIX + "/auth/authorize"
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": f"https://{CLIENT_ID}.chromiumapp.org/",
        "state": "s" * 32,
        "code_challenge": "a" * 43,
        "code_challenge_method": "S256",
    }
    try:
        with TestClient(api, base_url="http://testserver", follow_redirects=False) as client:
            for change in ({"client_id": "a" * 32}, {"redirect_uri": "https://example.invalid/"}):
                assert client.get(path, params={**params, **change}).status_code == 400
            malformed = client.post(
                PREFIX + "/auth/token", json={"code_verifier": "synthetic-input"}
            )
            assert malformed.status_code == 422 and malformed.json() == {"code": "invalid_request"}
            assert (
                client.post(
                    path, params=params, headers={"origin": "http://elsewhere.invalid"}
                ).status_code
                == 403
            )
            for host in [
                "testserver/path",
                "name@testserver",
                "testserver:70000",
                "invalid,example",
            ]:
                assert client.get(path, params=params, headers={"host": host}).status_code == 403
    finally:
        api.state.container.database.close()


def test_login_reuses_platform_session_on_https_and_isolates_http_parent_by_port():
    api, _, password = prepare()
    c = api.state.container
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": f"https://{CLIENT_ID}.chromiumapp.org/",
        "state": "s" * 32,
        "code_challenge": "a" * 43,
        "code_challenge_method": "S256",
        "prompt": "none",
    }
    path = PREFIX + "/auth/authorize"
    try:
        with TestClient(api, base_url="https://demo.intra", follow_redirects=False) as client:
            member = make_member(c, password)
            _, session, _ = c.auth_service.login(username=member["username"], password=password)
            client.cookies.set(c.settings.identity.session_cookie_name, session)
            result = client.get(path, params=params)
            assert parse_qs(urlsplit(result.headers["location"]).query)["error"] == [
                "consent_required"
            ]
        with TestClient(api, base_url="http://demo.intra:8080", follow_redirects=False) as client:
            authorize(client, c, password, member["id"])
            assert client.get(path, params=params).status_code == 200
            other_port = client.get("http://demo.intra:8081" + path, params=params)
            assert parse_qs(urlsplit(other_port.headers["location"]).query)["error"] == [
                "login_required"
            ]
    finally:
        c.database.close()


def start_events(c, job, attempt=0):
    sink = ExecutionAuditRepository(c.database)
    event = _tool_contract_event(
        invocation_id=f"{job}.attempt-{attempt}", request_digest="a" * 64, status="MATCH"
    )
    header = {
        "protocol_version": "1.5",
        "invocation_id": f"{job}.attempt-{attempt}",
        "request_digest": "a" * 64,
    }
    sink.record_runtime_event(
        job, {**header, "sequence": 1, "event_type": "execution_started", "payload": {}}
    )
    sink.record_runtime_event(job, {**event, **header, "sequence": 2})


def emit_delta(c, job, sequence, text, *, phase=None):
    row = c.database.execute_one(
        "select locked_by,worker_claim_version,retry_count from agent_job where id=?", (job,)
    )
    with JobExecutionControl(c.database).transaction(
        job, row["locked_by"], row["worker_claim_version"]
    ):
        ExecutionAuditRepository(c.database).record_runtime_event(
            job,
            {
                "protocol_version": "1.5",
                "invocation_id": f"{job}.attempt-{row['retry_count']}",
                "request_digest": "a" * 64,
                "sequence": sequence,
                "event_type": "assistant_text",
                "payload": {"text": text, **({"phase": phase} if phase else {})},
            },
        )


def assert_lease_and_attempt_rollback(c, job, session_id, cursor, final):
    with pytest.raises(WorkerLeaseLost):
        with JobExecutionControl(c.database).transaction(job, "stale-worker", 0):
            pytest.fail("失权 Worker 获得了写权限")
    with pytest.raises(RuntimeError, match="模拟回滚"):
        with c.database.unit_of_work():
            c.database.execute("update agent_job set retry_count=1 where id=?", (job,))
            retried = c.database.execute_one("select * from agent_job where id=?", (job,))
            replay = read_answer(c.database, retried, cursor)
            assert [e["event"] for e in replay] == ["reset", "status"]
            assert replay[-1]["status"] == "analyzing"
            assert read_answer(c.database, retried, None)["draft"] == ""
            c.session_repository.add_message(
                session_id=session_id, job_id=job, role="assistant", content=final
            )
            c.database.execute("update agent_job set status='SUCCEEDED' where id=?", (job,))
            raise RuntimeError("模拟回滚")


def assert_other_reader_excluded(c, api, app, password, path):
    other = c.identity_repository.create_user(username="synthetic-reader", display_name="合成用户")
    c.identity_repository.set_password_hash(other["id"], c.auth_service.passwords.hash(password))
    grant_test_application_access(
        c, application_id=app, role_code="second-reader", user_id=other["id"]
    )
    with TestClient(api, base_url=ORIGIN, follow_redirects=False) as second_client:
        other_headers = authorize(second_client, c, password, other["id"])
        assert second_client.get(path, headers=other_headers).status_code == 404
        assert second_client.get(path + "/events", headers=other_headers).status_code == 404
        assert second_client.get(path + "/activity", headers=other_headers).status_code == 404
        assert (
            second_client.get(PREFIX + "/conversations", headers=other_headers).json()["items"]
            == []
        )


async def assert_grant_revoked_midstream(api, c, headers, job):
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "query_string": b"",
            "app": api,
            "headers": [
                (b"host", b"testserver"),
                (b"authorization", headers["Authorization"].encode()),
            ],
        }
    )
    stream = (await answer_events(request, job)).body_iterator
    assert "answer_delta" in await anext(stream)
    c.database.execute("delete from browser_extension_grant")
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


def assert_consent_required(client, path, headers):
    # Revocation cascades to issued credentials. The next silent authorization
    # distinguishes a revoked grant from a dead platform session.
    assert client.get(path, headers=headers).json()["code"] == "credential_expired"
    silent = client.get(
        PREFIX + "/auth/authorize",
        params={
            "client_id": CLIENT_ID,
            "redirect_uri": f"https://{CLIENT_ID}.chromiumapp.org/",
            "state": "s" * 32,
            "code_challenge": "a" * 43,
            "code_challenge_method": "S256",
            "prompt": "none",
        },
    )
    assert parse_qs(urlsplit(silent.headers["location"]).query)["error"] == ["consent_required"]


def test_granted_question_snapshot_resume_and_revoke():
    api, app, password = prepare()
    c = api.state.container
    with TestClient(api, base_url=ORIGIN, follow_redirects=False) as client:
        headers = authorize(client, c, password)
        apps = client.get(PREFIX + "/applications", headers=headers).json()
        assert [a["id"] for a in apps] == [app]
        submit = {**headers, "X-Application-Scope": apps[0]["scope_ref"]}
        req = {"client_message_id": "synthetic-1", "question": "合成问题"}
        url = PREFIX + "/applications/" + app + "/messages"
        accepted = client.post(url, headers=submit, json=req)
        assert accepted.status_code == 202, accepted.json().get("detail")
        result = accepted.json()
        assert client.post(url, headers=submit, json=req).json() == result
        job = result["job_id"]
        path = PREFIX + "/jobs/" + job
        assert client.get(path).status_code == 401
        assert (
            client.get(path + "/events", headers={**headers, "Last-Event-ID": "12345"}).status_code
            == 409
        )
        claim = c.database.execute_one("select id from agent_job where id=?", (job,))
        assert claim
        queued = client.get(path, headers=headers).json()
        assert queued["state"] == "queued"
        c.database.execute(
            """update agent_job set status='RUNNING',locked_by='synthetic-worker',worker_claim_version=1,
             worker_lease_until='2099-01-01T00:00:00+00:00' where id=?""",
            (job,),
        )
        start_events(c, job)
        running = client.get(path, headers=headers).json()
        assert running["state"] == "analyzing"
        row = {"id": job, "retry_count": 0, "status": "RUNNING"}
        transition = read_answer(c.database, row, queued["through_cursor"])
        assert [(e["status"], e["id"]) for e in transition] == [
            ("analyzing", running["through_cursor"])
        ]
        assert read_answer(c.database, row, running["through_cursor"]) == []
        emit_delta(c, job, 3, "说明。\n\n**缺")
        snap = client.get(path, headers=headers).json()
        assert snap["draft"] == "说明。\n\n**缺"
        emit_delta(c, job, 4, "少批号**")
        emit_delta(c, job, 4, "少批号**")
        emit_delta(c, job, 5, "。")
        final = "说明。\n\n**缺少批号**。"
        asyncio.run(assert_grant_revoked_midstream(api, c, headers, job))
        assert_consent_required(client, path, headers)
        client.cookies.clear()
        headers = authorize(client, c, password)
        assert_lease_and_attempt_rollback(
            c, job, result["session_id"], snap["through_cursor"], final
        )
        assert client.get(path, headers=headers).json()["state"] == "analyzing"
        with c.database.unit_of_work():
            answer_id = c.session_repository.add_message(
                session_id=result["session_id"], job_id=job, role="assistant", content=final
            )
            c.database.execute(
                """update agent_job set status='SUCCEEDED',result=?,created_at='2026-11-25T02:30:00Z',
                   finished_at='2026-11-25T02:31:05.125Z' where id=?""",
                (final, job),
            )
            answered_at = "2026-11-25T02:31:05.100Z"
            c.database.execute(
                "update agent_message set created_at=? where id=?", (answered_at, answer_id)
            )
        stream = client.get(
            path + "/events", headers={**headers, "Last-Event-ID": str(snap["through_cursor"])}
        )
        events = [json.loads(s[6:]) for s in stream.text.splitlines() if s.startswith("data: ")]
        assert [e["event"] for e in events] == ["answer_delta", "answer_delta", "completed"]
        assert (
            snap["draft"] + "".join(e.get("text", "") for e in events)
            == events[-1]["final_answer"]
            == final
        )
        completed = client.get(path, headers=headers).json()
        for response in (completed, events[-1]):
            assert response["final_answer"] == final
            assert response["answered_at"] == answered_at
            assert response["duration_ms"] == 65_125
        page = client.get(
            PREFIX + "/conversations/" + result["conversation_id"], headers=headers
        ).json()
        asked_at = c.database.execute_one(
            "select m.created_at from agent_job j join agent_message m on m.id=j.input_message_id where j.id=?",
            (job,),
        )["created_at"]
        assert page["jobs"][0]["asked_at"] == asked_at
        c.database.execute(
            "update agent_job set finished_at='2000-01-01T00:00:00+00:00' where id=?", (job,)
        )
        purge_answers(c.database)
        assert (
            client.get(
                path + "/events", headers={**headers, "Last-Event-ID": str(snap["through_cursor"])}
            ).status_code
            == 409
        )
        assert client.get(path, headers=headers).json()["final_answer"] == final
        assert_other_reader_excluded(c, api, app, password, path)
        c.identity_repository.revoke_user_sessions("user_local_admin")
        assert client.get(path, headers=headers).status_code == 401
    c.database.close()


def test_main_markdown_around_tools():
    visible = []
    out = BrowserAnswer(visible.append)
    out.observe({"type": "system", "subtype": "init", "data": {"session_id": "main"}})
    for i, text in enumerate(["同一句", "同一句"]):

        def stream(ev, **meta):
            out.observe({"type": "stream_event", "session_id": "main", "event": ev, **meta})

        stream({"type": "message_start", "message": {"role": "assistant", "id": str(i)}})
        stream(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            }
        )
        stream(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "排除"},
            },
            parent_tool_use_id="child",
        )
        stream(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            }
        )
        stream({"type": "content_block_stop", "index": 0})
        stream(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": "排除"},
            }
        )
        message = {
            "type": "assistant",
            "session_id": "main",
            "message_id": str(i),
            "uuid": str(i),
            "content": [{"type": "text", "text": text}],
        }
        out.observe(message)
        out.observe(message)
    assert out.final("同一句") == "".join(visible) == "同一句\n\n同一句"


@pytest.mark.parametrize(
    "high_limits,separate_budget,structured",
    [(False, False, False), (True, False, False), (True, True, False), (True, True, True)],
)
def test_runtime_emits_only_after_contract_and_replays_once(
    tmp_path, high_limits, separate_budget, structured
):
    from app.modules.agent.infrastructure.runtime_protocol import canonical_request_digest
    from backend.tests.test_python_agent_runtime import (
        FakePythonExecutor,
        _client,
        _current_request,
        _dependencies,
        _prepare,
        _token,
    )
    import json

    class StreamingExecutor(FakePythonExecutor):
        def execute(
            self,
            request,
            cancel_event,
            secret_context,
            tool_contract_observer=None,
            answer_observer=None,
            process_observer=None,
        ):
            assert bool(process_observer) == structured
            assert answer_observer
            answer_observer("排除未校验的预览")
            outcome = super().execute(request, cancel_event, secret_context, tool_contract_observer)
            if process_observer:
                process_observer("查询公开记录。")
            answer_observer("**合")
            answer_observer("成**")
            return replace(outcome, final_answer="**合成**")

    executor = StreamingExecutor()
    deps, private = _dependencies(tmp_path, executor)
    req = _current_request()
    req["prompt"]["retrieved_context"]["response_presentation"] = "browser-markdown"
    if structured:
        req["prompt"]["retrieved_context"]["browser_answer_parts"] = "turns-v1"
    if separate_budget:
        req["prompt"]["retrieved_context"]["browser_preview_budget"] = "separate-v1"
    if high_limits:
        req["limits"]["max_turns"] = 100
        req["limits"]["max_tool_calls"] = 500
    req["request_digest"] = canonical_request_digest(req)
    _prepare(deps.database, req)
    client = _client(deps)
    hdr = {"Authorization": "Bearer " + _token(private, req)}

    def read():
        res = client.post("/internal/v1/executions", json=req, headers=hdr)
        assert res.status_code == 200
        return [json.loads(line) for line in res.text.splitlines()]

    events = read()
    assert read() == events and len(executor.requests) == 1
    previews = [e["payload"] for e in events if e["event_type"] == "assistant_text"]
    assert [p["text"] for p in previews if p.get("phase") == "process"] == (
        ["查询公开记录。"] if structured else []
    )
    assert [p["text"] for p in previews if "phase" not in p] == (
        ["**合", "成**"] if separate_budget or not high_limits else []
    )
    assert events[-1]["payload"]["final_answer"] == "**合成**"


def test_history_and_public_activity_are_scoped_and_keep_turn_boundaries():
    from app.modules.job.infrastructure.run_audit_repository import RunAuditRepository
    from backend.tests.test_browser_extension_contract import validator

    api, app, password = prepare()
    c = api.state.container
    try:
        with TestClient(api, base_url=ORIGIN, follow_redirects=False) as client:
            headers = authorize(client, c, password)
            scope = client.get(PREFIX + "/applications", headers=headers).json()[0]["scope_ref"]

            def ask(key, question, **extra):
                response = client.post(
                    PREFIX + f"/applications/{app}/messages",
                    headers={**headers, "X-Application-Scope": scope},
                    json={"client_message_id": key, "question": question, **extra},
                )
                assert response.status_code == 202
                return response.json()

            first = ask("first", "第一个会话")
            second = ask("second", "另一个会话")
            follow = ask("follow", "继续第一个问题", conversation_id=first["conversation_id"])
            assert (
                first["conversation_id"] == follow["conversation_id"] != second["conversation_id"]
            )
            listing = client.get(
                PREFIX + "/conversations", params={"limit": 1}, headers=headers
            ).json()
            validator("ConversationList").validate(listing)
            more = client.get(
                PREFIX + "/conversations",
                params={"before": listing["next_before"]},
                headers=headers,
            ).json()
            assert {r["title"] for r in listing["items"] + more["items"]} == {
                "第一个会话",
                "另一个会话",
            }
            job = first["job_id"]
            path = PREFIX + "/jobs/" + job
            db = c.database
            db.execute(
                """update agent_job set status='RUNNING',locked_by='synthetic-worker',worker_claim_version=1,
                          worker_lease_until='2099-01-01T00:00:00+00:00' where id=?""",
                (job,),
            )
            start_events(c, job)
            emit_delta(c, job, 3, "先检查")
            emit_delta(c, job, 4, "先检查", phase="process")
            emit_delta(c, job, 5, "结论")
            RunAuditRepository(db).add_tool_call(
                job_id=job,
                tool_name="lookup",
                status="SUCCEEDED",
                duration_ms=13,
                risk_level="low",
                request_payload={"input": "PRIVATE"},
                response_summary={"returned": 3, "rows": ["PRIVATE"], "error": "PRIVATE"},
            )
            assert client.get(path, headers=headers).json()["draft"] == "结论"
            items = read_answer(db, {"id": job, "retry_count": 0, "status": "RUNNING"}, 4)
            assert items[0]["replace"] and items[0]["text"] == ""
            validator("AnswerEvent").validate(items[0])
            activity = client.get(path + "/activity", headers=headers).json()
            validator("JobActivity").validate(activity)
            assert activity["process"] == "先检查"
            assert activity["tools"][0]["summary"] == {"returned": 3}
            assert "PRIVATE" not in str(activity)
            db.execute(
                "update agent_job set status='SUCCEEDED',finished_at='2000-01-01' where id=?",
                (job,),
            )
            purge_answers(db)
            assert client.get(path + "/activity", headers=headers).json() == activity
            assert_other_reader_excluded(c, api, app, password, path)
    finally:
        c.database.close()


def test_structured_browser_answer_separates_public_process_from_final():
    chunks, process = [], []
    answer = BrowserAnswer(chunks.append, process.append)
    answer.observe({"type": "system", "subtype": "init", "data": {"session_id": "main"}})
    for mid, blocks in [
        ("one", [{"type": "text", "text": "先查一下。"}, {"type": "tool_use"}]),
        ("two", [{"type": "text", "text": "结论。"}]),
    ]:
        item = {
            "type": "assistant",
            "session_id": "main",
            "message_id": mid,
            "uuid": mid,
            "content": blocks,
        }
        answer.observe(item)
        answer.observe(item)
    assert answer.final("结论。") == "结论。"
    assert process == ["先查一下。"]
