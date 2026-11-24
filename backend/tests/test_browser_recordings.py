import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.modules.channel.browser import recordings
from app.modules.channel.browser.auth import PREFIX
from backend.tests.helpers import grant_test_application_access
from backend.tests.test_browser_extension_contract import GOLDEN
from backend.tests.test_browser_extension_stream import (
    ORIGIN,
    authorize,
    create_browser_application,
    make_member,
    prepare,
)


@pytest.fixture
def platform(request):
    api, app, password = prepare(tools=getattr(request, "param", ()))
    c = api.state.container
    with TestClient(api, base_url=ORIGIN, follow_redirects=False) as client:
        headers = authorize(client, c, password)
        scope = client.get(PREFIX + "/applications", headers=headers).json()[0]["scope_ref"]
        try:
            yield api, client, app, password, {**headers, "X-Application-Scope": scope}
        finally:
            c.database.close()


def test_browser_application_environments_follow_current_grants(platform):
    api, client, app, _, headers = platform
    c = api.state.container
    config = c.platform_config_service.repository
    visible = config.upsert_environment(code="capture-test", display_name="联调环境")
    config.upsert_environment(code="capture-private")
    grant_test_application_access(
        c,
        application_id=app,
        role_code="capture-sites",
        scopes=({"environment_id": visible["id"]},),
    )

    def choices():
        apps = client.get(PREFIX + "/applications", headers=headers).json()
        return next(item["environments"] for item in apps if item["id"] == app)

    assert choices() == [{"code": "capture-test", "name": "联调环境"}]
    config.upsert_environment(code="capture-test", status="disabled")
    assert choices() == []


def test_concurrent_init_resume_scope_and_expiry(platform):
    api, client, app, password, headers = platform
    c = api.state.container
    db = c.database
    url = PREFIX + "/applications/" + app + "/recordings"
    init = json.loads((GOLDEN / "init-a.json").read_bytes())
    barrier = Barrier(2)

    def start(attempt):
        barrier.wait(timeout=5)
        return client.post(url, json={**init, "upload_attempt_id": attempt}, headers=headers)

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(start, key) for key in ("first", "other-tab")]
        replies = [task.result(timeout=10) for task in pending]
    assert [r.status_code for r in replies] == [200, 200]
    original = replies[0].json()
    assert (
        original
        == replies[1].json()
        == {"recording_id": original["recording_id"], "state": "uploading", "missing_parts": [0]}
    )
    assert db.execute_one("select count(*) as n from browser_recording")["n"] == 1
    rid = original["recording_id"]
    db.execute("update browser_recording_part set received_at=1 where recording_id=?", (rid,))
    assert client.post(url, json=init, headers=headers).json()["missing_parts"] == []
    changed = copy.deepcopy(init)
    changed["manifest"]["parts"][0]["sha256"] = "e" * 64
    assert client.post(url, json=changed, headers=headers).json() == {"code": "manifest_conflict"}

    member = make_member(c, password)
    grant_test_application_access(
        c, application_id=app, role_code="recordings-second", user_id=member["id"]
    )
    with TestClient(api, base_url=ORIGIN, follow_redirects=False) as other:
        theirs = authorize(other, c, password, member["id"])
        denied = other.post(
            url,
            json=init,
            headers={**theirs, "X-Application-Scope": headers["X-Application-Scope"]},
        )
        assert denied.status_code == 409 and denied.json()["code"] == "scope_changed"
        scope = other.get(PREFIX + "/applications", headers=theirs).json()[0]["scope_ref"]
        separate = other.post(
            url, json=init, headers={**theirs, "X-Application-Scope": scope}
        ).json()
        assert separate["recording_id"] != rid and separate["missing_parts"] == [0]
    db.execute("update browser_recording set expires_at=0 where id=?", (rid,))
    assert client.post(url, json=init, headers=headers).status_code == 410
    replacement = client.post(
        url, json={**init, "upload_attempt_id": "confirmed-again"}, headers=headers
    ).json()
    assert replacement["recording_id"] != rid and replacement["missing_parts"] == [0]
    stale_part = client.put(
        f"{PREFIX}/recordings/{rid}/parts/0",
        content=(GOLDEN / "recording-a.ndjson").read_bytes(),
        headers=headers,
    )
    stale_complete = client.post(f"{PREFIX}/recordings/{rid}/complete", headers=headers)
    for reply in (stale_part, stale_complete):
        assert (reply.status_code, reply.json()["code"]) == (410, "upload_expired")
    assert (
        client.post(
            url, json={**init, "upload_attempt_id": "confirmed-again"}, headers=headers
        ).json()
        == replacement
    )
    assert (
        client.post(
            url, json={**init, "upload_attempt_id": "other-tab"}, headers=headers
        ).status_code
        == 410
    )


def test_manifest_admission_budget_and_rejected_input_leave_no_reservations(platform, monkeypatch):
    api, client, app, _, headers = platform
    url = PREFIX + "/applications/" + app + "/recordings"
    init = json.loads((GOLDEN / "init-a.json").read_bytes())
    for field, bad in [("saved", 0), ("shareable", False), ("shareable", 1.0)]:
        payload = copy.deepcopy(init)
        payload["manifest"]["coverage"]["requests"][field] = bad
        reply = client.post(url, json=payload, headers=headers)
        assert reply.status_code == 422 and reply.json() == {"code": "invalid_request"}
    wrong = copy.deepcopy(init)
    wrong["manifest"]["parts"][0]["number"] = 1
    assert client.post(url, json=wrong, headers=headers).status_code == 422
    assert (
        client.post(
            url,
            content=b'{"upload_attempt_id":"synthetic","upload_attempt_id":"synthetic"}',
            headers={**headers, "Content-Type": "application/json"},
        ).status_code
        == 422
    )
    monkeypatch.setattr(recordings, "MAX_MANIFEST_BYTES", 128)
    reply = client.post(url, json=init, headers=headers)
    assert reply.status_code == 413 and reply.json() == {"code": "quota_exceeded"}
    assert client.post(url, json=init).status_code == 401
    assert (
        api.state.container.database.execute_one("select count(*) as n from browser_recording")["n"]
        == 0
    )
    monkeypatch.setattr(recordings, "MAX_MANIFEST_BYTES", 1024 * 1024)
    monkeypatch.setattr(recordings, "MAX_STAGED_RECORDINGS", 1)
    assert client.post(url, json=init, headers=headers).status_code == 200
    second = json.loads((GOLDEN / "init-b.json").read_bytes())
    assert client.post(url, json=second, headers=headers).status_code == 413
    assert client.post(url, json=init, headers=headers).status_code == 200


def test_evidence_uniqueness_and_recording_reference_boundaries(platform):
    api, client, app, _, headers = platform
    db = api.state.container.database
    path = PREFIX + "/applications/" + app
    init = json.loads((GOLDEN / "init-a.json").read_bytes())
    rid = client.post(path + "/recordings", json=init, headers=headers).json()["recording_id"]
    reference = client.post(
        path + "/messages",
        json={"client_message_id": "schema-reference", "question": "合成问题"},
        headers=headers,
    ).json()
    for table, key, id_value in [
        ("browser_job_recording", "job_id", reference["job_id"]),
        ("browser_session_recording", "session_id", reference["session_id"]),
    ]:
        insert = f"insert into {table}({key},recording_id,scope_ref) values(?,?,?)"
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(insert, (id_value, rid, "different-scope"))
        db.execute(insert, (id_value, rid, headers["X-Application-Scope"]))
    sql = "insert into browser_recording_evidence(recording_id,kind,source_id,offset_ms,part_number,line_number) values(?,?,?,?,?,?)"
    db.execute(sql, (rid, "action", "ui:1", 5, 0, 0))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (rid, "action", "ui:1", 6, 0, 1))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (rid, "request", "net:1", 6, 0, 0))


def recording_services(platform, monkeypatch):
    import io
    import secrets
    from starlette.applications import Starlette
    from app.modules.channel.browser import file_client
    from app.modules.file_workspace.storage import MinioFileObjectStorage
    from app.modules.identity.application.principal_jwt import PrincipalJwks
    from app.modules.identity.application.service_principal import (
        ServicePrincipalTokenIssuer,
        REQUIRED_SERVICE_PRINCIPAL_ROLES,
        RECORDING_TOOL_PARTY,
    )
    from backend.tests.test_service_principal_identity import _signing_key
    from services.file_service.auth import FileWorkerPrincipalVerifier
    from services.file_service.recordings import RecordingFiles

    api, client, _, _, _ = platform
    c = api.state.container
    keys = {
        role: secrets.token_urlsafe(40)
        for role in (*REQUIRED_SERVICE_PRINCIPAL_ROLES, RECORDING_TOOL_PARTY)
    }
    issuer = ServicePrincipalTokenIssuer(
        signing_key=_signing_key(), audit_service=c.audit_service, bootstrap_credentials=keys
    )
    c.service_principal_token_issuer = issuer
    verifier = FileWorkerPrincipalVerifier(
        PrincipalJwks.from_dict(issuer.signing_key.public_jwks())
    )
    objects = {}

    class Objects:
        recording_key = staticmethod(MinioFileObjectStorage.recording_key)

        def put_recording(self, rid, n, digest, raw):
            objects[self.recording_key(rid, n, digest)] = raw

        def open_stream(self, *, internal_object_key):
            return io.BytesIO(objects[internal_object_key])

        def delete(self, *, internal_object_key):
            del objects[internal_object_key]

        def recording_keys(self, after, limit):
            return list(objects), ""

    files = RecordingFiles(c, Objects(), verifier)
    from app.modules.identity.api.service_principal_controller import build_service_principal_router

    api.include_router(build_service_principal_router())
    fs = TestClient(Starlette(routes=files.routes()))

    def internal(base, hosts, path, token, *, body, media, timeout, method="POST"):
        transport = client if path.startswith("/api/") else fs
        resp = transport.request(
            method,
            path,
            content=body,
            headers={"Authorization": "Bearer " + token, "Content-Type": media},
        )
        assert resp.status_code == 200, (path, resp.status_code)
        return resp.json()

    monkeypatch.setattr(file_client, "internal_request", internal)
    monkeypatch.setattr("app.modules.channel.browser.tools.internal_request", internal)
    return c, files, fs, issuer, keys[RECORDING_TOOL_PARTY], objects


def publish_golden(client, app_path, headers, objects, label="a"):
    import gzip

    manifest = json.loads((GOLDEN / f"init-{label}.json").read_bytes())
    rid = client.post(app_path + "/recordings", json=manifest, headers=headers).json()[
        "recording_id"
    ]
    path = PREFIX + "/recordings/" + rid
    raw = (GOLDEN / f"recording-{label}.ndjson").read_bytes()
    h = {**headers, "Content-Type": "application/x-ndjson", "Content-Encoding": "gzip"}
    assert client.post(path + "/complete", headers=headers).json() == {
        "code": "parts_missing",
        "missing_parts": [0],
    }
    chunk = path + "/parts/0"
    assert client.put(chunk, content=gzip.compress(raw + b"x"), headers=h).status_code == 409
    assert client.put(chunk, content=gzip.compress(raw), headers=h).status_code == 200
    assert (
        client.post(app_path + "/recordings", json=manifest, headers=headers).json()[
            "missing_parts"
        ]
        == []
    )
    assert client.put(chunk, content=gzip.compress(raw), headers=h).status_code == 200
    assert len(objects) >= 1
    assert client.post(path + "/complete", headers=headers).json()["state"] == "ready"
    assert client.post(path + "/complete", headers=headers).status_code == 200
    return rid


@pytest.mark.parametrize(
    "platform", [("search_recording", "get_recording_evidence")], indirect=True
)
def test_recording_parts_bound_evidence_and_cleanup(platform, monkeypatch):
    import time
    from app.modules.channel.browser.tools import RecordingTools

    _, client, app, _, headers = platform
    c, files, fs, issuer, tool_identity, objects = recording_services(platform, monkeypatch)
    app_path = PREFIX + "/applications/" + app
    rid = publish_golden(client, app_path, headers, objects)

    def question(key, **fields):
        r = client.post(
            app_path + "/messages",
            json={"client_message_id": key, "question": "合成检查", **fields},
            headers=headers,
        )
        assert r.status_code == 202, r.json()
        return r.json()

    first = question("bound-first", recording_id=rid)
    second = question("bound-next", conversation_id=first["conversation_id"])
    assert second["recording_id"] == first["recording_id"] == rid
    assert (
        question("unbind", conversation_id=first["conversation_id"], recording_id=None)[
            "recording_id"
        ]
        is None
    )
    assert question("bound-first", recording_id=rid) == first
    verify_history(client, headers, first, second)
    job = first["job_id"]
    c.database.execute("update agent_job set status='RUNNING' where id=?", (job,))
    tools = RecordingTools(c)

    class Identity:
        def access_token(self):
            return issuer.issue(tool_identity).access_token

    tools.identity = Identity()
    result = tools.call("search_recording", job, {"limit": 1}).summary
    assert result["hits"][0]["evidence_id"]["kind"] == "action" and result["next_cursor"]
    more = tools.call(
        "search_recording", job, {"limit": 1, "cursor": result["next_cursor"]}
    ).summary
    evidence = more["hits"][0]["evidence_id"]
    assert evidence["kind"] == "request"
    assert (
        tools.call("get_recording_evidence", job, {"evidence_id": evidence}).summary["row"][
            "response_code"
        ]
        == "DEMO_REJECTED"
    )
    verify_runtime_tool(c, tools, job, rid, evidence)
    token = issuer.recording_read(
        scope=headers["X-Application-Scope"],
        recording=rid,
        job=job,
        attempt=0,
        kind="request",
        source=evidence["source_id"],
    )
    target = {
        "recording": rid,
        "job": job,
        "attempt": 0,
        "kind": "request",
        "source": evidence["source_id"],
    }
    for other in [{**target, "source": "net:other"}, {**target, "job": second["job_id"]}]:
        assert (
            fs.post(
                "/internal/v1/browser-recordings/evidence",
                json=other,
                headers={"Authorization": "Bearer " + token},
            ).status_code
            == 403
        )
    c.database.execute("update business_application set status='disabled' where id=?", (app,))
    assert (
        fs.post(
            "/internal/v1/browser-recordings/evidence",
            json=target,
            headers={"Authorization": "Bearer " + token},
        ).status_code
        == 403
    )
    c.database.execute("update business_application set status='enabled' where id=?", (app,))
    c.database.execute("update agent_job set status='SUCCEEDED' where id=?", (job,))
    c.database.execute("update agent_job set status='RUNNING' where id=?", (second["job_id"],))
    assert (
        tools.call("get_recording_evidence", second["job_id"], {"evidence_id": evidence}).summary[
            "evidence_id"
        ]
        == evidence
    )
    from app.shared.exceptions import ToolPolicyError

    with pytest.raises(ToolPolicyError):
        tools.call("search_recording", second["job_id"], {"cursor": result["next_cursor"]})
    c.database.execute("update agent_job set status='RUNNING' where id=?", (job,))
    c.database.execute(
        "update browser_recording set expires_at=? where id=?", (int(time.time()) - 1, rid)
    )
    assert (
        fs.post(
            "/internal/v1/browser-recordings/evidence",
            json=target,
            headers={"Authorization": "Bearer " + token},
        ).status_code
        == 403
    )
    files.cleanup()
    files.cleanup()
    assert not objects
    fs.close()


def verify_runtime_tool(c, tools, job, rid, evidence):
    c.tool_service.recording_tools = tools
    from app.services.tool_mcp import _service_from_container
    from backend.tests.support.tool_mcp import request_identity

    service = _service_from_container(c)
    actual_job, descriptor = service.descriptor(job, "get_recording_evidence")
    answer = service.invoke(
        job=actual_job,
        descriptor=descriptor,
        arguments={"evidence_id": evidence},
        request_identity=request_identity(actual_job, "synthetic-recording-read"),
    )
    assert answer.payload["data"]["evidence_id"] == evidence
    assert answer.payload["data"]["row"]["response_code"] == "DEMO_REJECTED"
    audit = c.database.execute_one(
        "select response_summary from agent_tool_call where job_id=? and tool_name='get_recording_evidence'",
        (job,),
    )
    assert audit and "DEMO_REJECTED" not in audit["response_summary"]
    before_execution = c.agent_executor.context_builder.build(actual_job)
    assert rid in " ".join(before_execution.safety_rules)
    assert "DEMO_REJECTED" not in repr(before_execution)
    assert not before_execution.retrieved_context.get("file_manifest")


def test_part_rollback_retries_and_rejects_oversized_input(platform, monkeypatch):
    import gzip
    from app.modules.channel.browser import parts
    from app.modules.channel.browser.http import deny

    _, client, app, _, headers = platform
    c, files, fs, _, _, objects = recording_services(platform, monkeypatch)
    init = json.loads((GOLDEN / "init-a.json").read_bytes())
    endpoint = PREFIX + "/applications/" + app + "/recordings"
    rid = client.post(endpoint, json=init, headers=headers).json()["recording_id"]
    path = PREFIX + "/recordings/" + rid
    part = path + "/parts/0"
    raw = (GOLDEN / "recording-a.ndjson").read_bytes()
    wire = gzip.compress(raw)
    h = {**headers, "Content-Type": "application/x-ndjson", "Content-Encoding": "gzip"}
    assert (
        client.put(
            part, content=gzip.compress(b"x" * (parts.MAX_PART_BYTES + 1)), headers=h
        ).status_code
        == 413
    )
    assert client.put(part, content=wire + wire, headers=h).status_code == 422
    assert client.post(path + "/complete", content=b"x", headers=headers).status_code == 422
    original = parts.record_index

    def interrupt(*args):
        original(*args)
        raise deny("application_unavailable", 503)

    with monkeypatch.context() as m:
        m.setattr(parts, "record_index", interrupt)
        assert client.put(part, content=wire, headers=h).status_code == 503
    assert len(objects) == 1
    assert client.post(endpoint, json=init, headers=headers).json()["missing_parts"] == [0]
    assert not c.database.execute(
        "select 1 from browser_recording_evidence where recording_id=?", (rid,)
    )
    assert client.post(path + "/complete", headers=headers).status_code == 409
    assert client.put(part, content=wire, headers=h).status_code == 200
    assert client.post(path + "/complete", headers=headers).status_code == 200
    assert len(objects) == 1
    fs.close()


@pytest.mark.parametrize("invalid", ["duplicate", "missing", "unordered"])
def test_manifest_cannot_publish_incomplete_or_conflicting_index(platform, monkeypatch, invalid):
    import hashlib

    _, client, app, _, h = platform
    c, _, fs, _, _, _ = recording_services(platform, monkeypatch)
    init = json.loads((GOLDEN / "init-a.json").read_bytes())
    a, b = (GOLDEN / "recording-a.ndjson").read_bytes().splitlines(keepends=True)
    parts = {"duplicate": [a, a], "missing": [a], "unordered": [b, a]}[invalid]
    init["manifest"]["parts"] = [
        {"number": n, "uncompressed_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        for n, raw in enumerate(parts)
    ]
    url = PREFIX + "/applications/" + app
    rid = client.post(url + "/recordings", json=init, headers=h).json()["recording_id"]
    path = PREFIX + "/recordings/" + rid
    for n, raw in enumerate(parts):
        reply = client.put(
            path + "/parts/" + str(n),
            content=raw,
            headers={**h, "Content-Type": "application/x-ndjson"},
        )
        assert reply.status_code == (409 if invalid == "duplicate" and n else 200)
    assert client.post(path + "/complete", headers=h).status_code == 409
    r = client.post(
        url + "/messages",
        json={"client_message_id": "test", "question": "合成问题", "recording_id": rid},
        headers=h,
    )
    assert r.status_code == 403
    assert not c.database.execute("select 1 from browser_message_receipt")
    fs.close()


def verify_history(client, headers, first, second):
    path = PREFIX + "/conversations/" + first["conversation_id"]
    page = client.get(path, params={"limit": 2}, headers=headers).json()
    assert recordings.contract("ConversationPage").is_valid(page)
    assert page["recording_state"] == "none"
    assert page["next_before"] == second["job_id"]
    earlier = client.get(path, params={"before": page["next_before"]}, headers=headers).json()
    assert [item["job_id"] for item in earlier["jobs"]] == [first["job_id"]]
    assert earlier["next_before"] is None
    assert client.get(path, params={"before": "different-job"}, headers=headers).status_code == 409
    assert client.get(path).status_code == 401


@pytest.mark.parametrize(
    "platform", [("search_recording", "get_recording_evidence")], indirect=True
)
def test_switch_freezes_each_job_and_concurrent_replay_deduplicates(platform, monkeypatch):
    c, _, fs, _, _, objects = recording_services(platform, monkeypatch)
    _, client, app, _, headers = platform
    path = PREFIX + "/applications/" + app
    a = publish_golden(client, path, headers, objects)
    b = publish_golden(client, path, headers, objects, label="b")

    def submit(key, **options):
        response = client.post(
            path + "/messages",
            json={"client_message_id": key, "question": "合成", **options},
            headers=headers,
        )
        assert response.status_code == 202
        return response.json()

    first = submit("choose-a", recording_id=a)
    conversation = first["conversation_id"]
    barrier = Barrier(2)

    def retry_b():
        barrier.wait(timeout=5)
        return submit("choose-b", recording_id=b, conversation_id=conversation)

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: retry_b(), range(2)))
    assert receipts[0] == receipts[1]
    third = submit("inherit-b", conversation_id=conversation)
    assert third["recording_id"] == receipts[0]["recording_id"] == b
    prior = client.get(path + "/messages/choose-a", headers=headers).json()
    assert prior == first and prior["recording_id"] == a
    assert c.database.execute_one("select count(*) as n from browser_job_recording")["n"] == 3
    from app.modules.channel.browser.tools import RecordingTools
    from app.shared.exceptions import ToolPolicyError

    tools = RecordingTools(c)
    old, new = first["job_id"], third["job_id"]
    c.database.execute("update agent_job set status='RUNNING', retry_count=1 where id=?", (old,))
    c.database.execute("update agent_job set status='RUNNING' where id=?", (new,))
    page_a = tools.call("search_recording", old, {"limit": 1}).summary
    page_b = tools.call("search_recording", new, {}).summary
    assert page_a["hits"][0]["evidence_id"]["recording_id"] == a
    assert page_b["hits"][0]["evidence_id"]["recording_id"] == b
    assert page_a["next_cursor"]
    with pytest.raises(ToolPolicyError, match="Recording evidence unavailable"):
        tools.call("search_recording", new, {"cursor": page_a["next_cursor"]})
    original = tools.search

    def revoke_after_query(*args):
        data = original(*args)
        c.database.execute("update business_application set status='disabled' where id=?", (app,))
        return data

    monkeypatch.setattr(tools, "search", revoke_after_query)
    with pytest.raises(ToolPolicyError, match="Recording evidence unavailable"):
        tools.call("search_recording", old, {})

    fs.close()


def test_binding_without_recording_tool_grants_rolls_back(platform, monkeypatch):
    c, _, fs, _, _, objects = recording_services(platform, monkeypatch)
    _, client, app, _, headers = platform
    path = PREFIX + "/applications/" + app
    version = publish_golden(client, path, headers, objects)
    question = {"client_message_id": "denied", "question": "合成问题", "recording_id": version}
    assert client.post(path + "/messages", json=question, headers=headers).status_code == 403
    assert not c.database.execute("select 1 from browser_message_receipt")
    assert not c.database.execute("select 1 from agent_job")
    fs.close()


def test_orphan_cleanup_retries_and_preserves_referenced_parts(platform, monkeypatch):
    import hashlib
    from uuid import uuid4

    _, files, fs, _, _, objects = recording_services(platform, monkeypatch)
    _, client, app, _, headers = platform
    path = PREFIX + "/applications/" + app
    rid = publish_golden(client, path, headers, objects)
    raw = b"synthetic-orphan"
    files.store.put_recording(uuid4().hex, 0, hashlib.sha256(raw).hexdigest(), raw)
    original = files.store.delete

    def interrupted(*, internal_object_key):
        assert rid not in internal_object_key
        raise OSError("synthetic interrupted reclamation")

    with monkeypatch.context() as m:
        m.setattr(files.store, "delete", interrupted)
        with pytest.raises(OSError, match="synthetic interrupted"):
            files.cleanup()
    assert len(objects) == 2
    assert files.store.delete == original
    files.cleanup()
    assert len(objects) == 1
    fs.close()


def test_secret_input_cannot_be_carried_in_an_action_projection():
    from app.modules.channel.browser.parts import validate_row

    row = json.loads((GOLDEN / "recording-a.ndjson").read_bytes().splitlines()[0])
    for target in ({"type": "password"}, {"autocomplete": "one-time-code"}):
        row["details"]["value"] = {"target": target, "after": {"value": "synthetic-marker"}}
        with pytest.raises(ValueError, match="protected input"):
            validate_row(row)


def test_credential_expires_after_object_write_and_resumes_from_committed_receipts(
    platform, monkeypatch
):
    from app.modules.channel.browser import file_client

    api, client, app, password, headers = platform
    c, _, fs, _, _, objects = recording_services(platform, monkeypatch)
    base = PREFIX + "/applications/" + app + "/recordings"
    init = json.loads((GOLDEN / "init-a.json").read_bytes())
    rid = client.post(base, json=init, headers=headers).json()["recording_id"]
    path = PREFIX + "/recordings/" + rid
    raw = (GOLDEN / "recording-a.ndjson").read_bytes()

    def put(h):
        return client.put(
            path + "/parts/0", content=raw, headers={**h, "Content-Type": "application/x-ndjson"}
        )

    write = file_client.write_part

    def cross_expiry(*args):
        write(*args)
        c.database.execute(
            "update browser_extension_credential set expires_at=0 where kind='access'"
        )

    with monkeypatch.context() as m:
        m.setattr(file_client, "write_part", cross_expiry)
        fail = put(headers)
    assert fail.status_code == 401 and fail.json()["code"] == "credential_expired"
    assert len(objects) == 1
    renewed = {
        **authorize(client, c, password, silent=True),
        "X-Application-Scope": headers["X-Application-Scope"],
    }
    assert client.post(base, json=init, headers=renewed).json()["missing_parts"] == [0]
    assert put(renewed).status_code == 200
    second = make_member(c, password)
    grant_test_application_access(
        c, application_id=app, role_code="recording-second", user_id=second["id"]
    )
    with TestClient(api, base_url=ORIGIN, follow_redirects=False) as other:
        outsider = authorize(other, c, password, second["id"])
        denied = other.put(
            path + "/parts/0",
            content=raw,
            headers={**outsider, "Content-Type": "application/x-ndjson"},
        )
        assert denied.status_code == 404
        assert other.post(path + "/complete", headers=outsider).status_code == 404
    assert client.post(path + "/complete", headers=renewed).status_code == 200
    assert len(objects) == 1
    fs.close()


@pytest.mark.parametrize(
    "platform", [("search_recording", "get_recording_evidence")], indirect=True
)
def test_receipts_conversation_and_recordings_follow_current_application(platform, monkeypatch):
    api, client, app, _, headers = platform
    c, _, fs, _, _, objects = recording_services(platform, monkeypatch)
    publication = c.database.execute_one(
        """select rev.agent_publication_id from business_application_active_route r
        join business_application_publication p on p.id=r.publication_id
        join business_application_revision rev on rev.id=p.revision_id where r.application_id=?""",
        (app,),
    )
    other = create_browser_application(
        c,
        "second-browser-app",
        publication["agent_publication_id"],
        tools=("search_recording", "get_recording_evidence"),
    )
    scopes = {
        r["id"]: r["scope_ref"]
        for r in client.get(PREFIX + "/applications", headers=headers).json()
    }
    assert set(scopes) == {app, other}
    first_path = f"{PREFIX}/applications/{app}"
    second_path = f"{PREFIX}/applications/{other}"
    other_headers = {**headers, "X-Application-Scope": scopes[other]}
    rid = publish_golden(client, first_path, headers, objects)
    question = {"client_message_id": "first", "question": "合成用例", "recording_id": rid}
    receipt = client.post(first_path + "/messages", json=question, headers=headers)
    assert receipt.status_code == 202
    job, conversation = receipt.json()["job_id"], receipt.json()["conversation_id"]
    assert client.get(second_path + "/messages/first", headers=other_headers).status_code == 404
    assert (
        client.post(second_path + "/messages", json=question, headers=other_headers).status_code
        == 403
    )
    plain = {"client_message_id": "first", "question": "合成用例"}
    reply = client.post(
        second_path + "/messages",
        json={**plain, "conversation_id": conversation},
        headers=other_headers,
    )
    assert reply.status_code == 404
    second = client.post(second_path + "/messages", json=plain, headers=other_headers)
    assert second.status_code == 202 and second.json()["job_id"] != job
    assert (
        client.get(
            f"{PREFIX}/conversations/{conversation}",
            params={"before": second.json()["job_id"]},
            headers=headers,
        ).status_code
        == 409
    )
    c.database.execute("update business_application set status='disabled' where id=?", (app,))
    assert [r["id"] for r in client.get(PREFIX + "/applications", headers=headers).json()] == [
        other
    ]
    for path in [
        first_path + "/messages/first",
        f"{PREFIX}/conversations/{conversation}",
        f"{PREFIX}/jobs/{job}",
        f"{PREFIX}/jobs/{job}/events",
    ]:
        assert client.get(path, headers=headers).status_code == 404
    assert client.post(first_path + "/messages", json=question, headers=headers).status_code == 404
    assert client.post(f"{PREFIX}/recordings/{rid}/complete", headers=headers).status_code == 404
    assert (
        client.get(second_path + "/messages/first", headers=other_headers).json() == second.json()
    )
    fs.close()
