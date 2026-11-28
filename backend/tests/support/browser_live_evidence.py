"""Round trip using only generated evidence. External services are opt-in for the isolated trial."""

import base64
import hashlib
import json
import os
import time
from uuid import uuid4

from app.modules.channel.browser import live_loki


def check_transport(client, c, headers, live_path, page, recording_id, monkeypatch):
    path = live_path.removesuffix("live-recordings") + "live-evidence"
    data = json.dumps(
        {"kind": "action", "action": "click", "element": "button", "node_id": 17}
    ).encode()
    event = {
        "event_id": uuid4().hex,
        "seq": 1,
        "observed_ms": int(time.time() * 1000),
        "kind": "action",
        "event_digest": hashlib.sha256(data).hexdigest(),
        "event_bytes": len(data),
        "number": 0,
        "data": base64.b64encode(data).decode(),
    }
    value = {"recording_id": recording_id, "source": page, "parts": [event]}

    def post(body):
        return client.post(path, headers=headers, json=body)

    real = os.environ.get("BROWSER_EVIDENCE_SYNTHETIC_ROUNDTRIP") == "1"
    if not real:
        monkeypatch.setenv("BROWSER_EVIDENCE_WRITE_URL", "http://evidence-alloy:3500")
    writes = []
    actual = live_loki.forward

    def send(payload):
        writes.append(payload)
        if real:
            actual(payload)

    monkeypatch.setattr(live_loki, "forward", send)
    assert post({**value, "owner": "another-user"}).status_code == 422
    assert post({**value, "source": {**page, "tab_id": uuid4().hex}}).status_code == 403
    assert not writes
    assert post(value).json() == {"accepted": 1, "delivery": "forwarded"}
    assert post(value).status_code == 200
    assert writes[0] == writes[1]
    line = json.loads(writes[0]["streams"][0]["values"][0][1])
    assert line["binding_id"] == page["binding_id"] and line["tab_id"] == page["tab_id"]
    assert len(line["owner"]) == len(line["tenant"]) == 64
    assert len(writes[0]["streams"][0]["values"][0][1].encode()) <= live_loki.LINE_BYTES
    assert post({**value, "parts": [{**event, "seq": 2}]}).status_code == 409
    if real:
        row = c.database.execute_one(
            "select * from browser_live_evidence_part where recording_id=? and event_id=?",
            (recording_id, event["event_id"]),
        )
        scope = {
            k: line[k]
            for k in (
                "owner",
                "tenant",
                "application",
                "environment",
                "base",
                "workshop",
                "site",
                "recording_id",
                "tab_id",
                "document_id",
                "binding_id",
                "revision",
            )
        }
        deadline = time.monotonic() + 30
        while live_loki.read_part(scope, row) is None:
            assert time.monotonic() < deadline, (
                "Alloy ACK was received but Loki did not return this evidence"
            )
            time.sleep(0.25)
        assert live_loki.read_part(scope, row) == data
        assert live_loki.read_part({**scope, "owner": "a" * 64}, row) is None
        assert live_loki.read_part({**scope, "tenant": "b" * 64}, row) is None


def query_principals(c, client, app, password, headers):
    from app.modules.channel.browser.auth import PREFIX
    from backend.tests.helpers import grant_test_application_access
    from backend.tests.test_browser_extension_stream import (
        authorize,
        create_browser_application,
        make_member,
    )

    config = c.platform_config_service.repository
    env = config.upsert_environment(code="live-test")
    base = config.upsert_base(environment_code=env["code"], code="plant", engine="mysql")
    shops = [
        config.upsert_workshop(environment_code=env["code"], base_code=base["code"], code=k)
        for k in ("mix", "pack")
    ]
    tools = ("search_recording", "get_recording_evidence")
    pub = c.database.execute_one(
        """select v.agent_publication_id from business_application_active_route r
            join business_application_publication p on p.id=r.publication_id
            join business_application_revision v on v.id=p.revision_id where r.application_id=?""",
        (app,),
    )
    other_app = create_browser_application(
        c, "another-live-app", pub["agent_publication_id"], tools=tools
    )
    other_user = make_member(c, password)["id"]
    paths = []
    for app_id, uid, index in (
        (app, "user_local_admin", 1),
        (other_app, "user_local_admin", 2),
        (app, other_user, 3),
    ):
        grant_test_application_access(
            c,
            application_id=app_id,
            role_code="live-operators-" + str(index),
            user_id=uid,
            capabilities=tools,
            scopes=({"environment_id": env["id"]},),
        )
        if index == 3:
            client.cookies.clear()
        token = headers if index < 3 else authorize(client, c, password, uid)
        scope = next(
            r["scope_ref"]
            for r in client.get(PREFIX + "/applications", headers=token).json()
            if r["id"] == app_id
        )
        paths.append((f"{PREFIX}/applications/{app_id}", {**token, "X-Application-Scope": scope}))

    return env, base, shops, paths


def query_transport(monkeypatch):
    lines = {}
    real = os.environ.get("BROWSER_EVIDENCE_SYNTHETIC_ROUNDTRIP") == "1"
    if not real:
        monkeypatch.setenv("BROWSER_EVIDENCE_WRITE_URL", "http://evidence-alloy:3500")

        def send(payload):
            for stream in payload["streams"]:
                for _, raw in stream["values"]:
                    line = json.loads(raw)
                    lines[line["recording_id"], line["event_id"], line["number"]] = line

        def read(scope, row):
            line = lines.get((row["recording_id"], row["event_id"], row["part_number"]))
            return (
                base64.b64decode(line["data"])
                if line and all(line[k] == v for k, v in scope.items())
                else None
            )

        monkeypatch.setattr(live_loki, "forward", send)
        monkeypatch.setattr(live_loki, "read_part", read)

    return lines, real


def query_clients(c, client, paths, env, base, shops, instant):
    def page(who, shop, rid, path, *, environment_only=False):
        prefix, h = paths[who]
        rule = {"origin": "https://mes.invalid", "path": path}
        body = {
            "rule": rule,
            "environment_id": env["id"],
            "base_id": None if environment_only else base["id"],
            "workshop_id": shops[shop]["id"] if shop is not None else None,
            "expected_revision": 0,
        }
        saved = client.put(prefix + "/workshop-bindings", headers=h, json=body)
        assert saved.status_code == 200
        p = {
            "binding_id": saved.json()["id"],
            "revision": 1,
            "document_id": uuid4().hex,
            "tab_id": uuid4().hex,
        }
        assert (
            client.post(
                prefix + "/live-recordings", headers=h, json={"recording_id": rid, "pages": [p]}
            ).status_code
            == 200
        )
        return who, rid, p

    def event(target, value, observed=instant):
        who, rid, p = target
        event_id = uuid4().hex
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        parts = [
            {
                "event_id": event_id,
                "seq": 1,
                "observed_ms": observed,
                "kind": value["kind"],
                "event_digest": hashlib.sha256(data).hexdigest(),
                "event_bytes": len(data),
                "number": i,
                "data": base64.b64encode(data[start : start + live_loki.PART_BYTES]).decode(),
            }
            for i, start in enumerate(range(0, len(data), live_loki.PART_BYTES))
        ]
        prefix, h = paths[who]
        for start in range(0, len(parts), 8):
            resp = client.post(
                prefix + "/live-evidence",
                headers=h,
                json={"recording_id": rid, "source": p, "parts": parts[start : start + 8]},
            )
            assert resp.status_code == 200
        return event_id, data

    def question(target):
        who, rid, p = target
        prefix, h = paths[who]
        res = client.post(
            prefix + "/messages",
            headers=h,
            json={
                "question": "合成检索",
                "client_message_id": uuid4().hex,
                "page": {**p, "recording_id": rid, "asked_ms": instant, "timezone": "UTC"},
            },
        )
        assert res.status_code == 202
        job = res.json()["job_id"]
        c.database.execute("update agent_job set status='RUNNING' where id=?", (job,))
        return job

    return page, event, question


def verify_large_detail(get, ref, raw):
    chunks = bytearray()
    reply = get(ref)
    assert reply["truncated"]
    while True:
        assert len(json.dumps(reply, ensure_ascii=False).encode()) < 256 * 1024
        for part in reply["parts"]:
            data = base64.b64decode(part["data"])
            assert part["sha256"] == hashlib.sha256(data).hexdigest()
            chunks.extend(data)
        if not reply["next_cursor"]:
            break
        reply = get(ref, cursor=reply["next_cursor"])
    assert bytes(chunks) == raw and hashlib.sha256(chunks).hexdigest() == reply["sha256"]


def verify_reference_isolation(c, other_job, action, search, get, event, target):
    import pytest
    from fastapi import HTTPException
    from app.modules.channel.browser import live_query

    initial = search()
    ref = initial["hits"][0]["reference"]
    assert get(ref)["value"] == action
    with pytest.raises(HTTPException) as denied:
        live_query.run(c, other_job, 0, "get_recording_evidence", {"reference": ref})
    with pytest.raises(HTTPException) as invalid:
        get("bogus")
    assert (denied.value.status_code, denied.value.detail) == (
        invalid.value.status_code,
        invalid.value.detail,
    )
    with pytest.raises(HTTPException):
        search(scope="today", cursor=initial["next_cursor"])
    late, _ = event(target, action)
    assert [r["event_id"] for r in search(cursor=initial["next_cursor"])["hits"]] == [late]


def verify_diagnostic_context(c, job, tools):
    builder = c.agent_executor.context_builder
    bound = c.agent_repository.get_job(job)
    prompts = builder._recording_context(bound, [*tools, "query_loki", "knowledge_search"])
    assert any("request_id 或 trace_id" in p and "已发布日志资源" in p for p in prompts)
    assert any("未选择的层级只匹配空值" in p for p in prompts)
    assert any("运行版本未知" in p and "SVN revision" in p for p in prompts)
    assert any("日志无命中" in p and "时间相近不足以归因" in p for p in prompts)
    assert all("query_loki" not in p for p in builder._recording_context(bound, list(tools)))


def verify_partial_scopes(c, env, base, rid, action, page, event, question):
    from app.modules.channel.browser import live_query

    # All three levels share an owner, application, environment and recording.
    env_page = page(0, None, rid, "/environment", environment_only=True)
    base_page = page(0, None, rid, "/base")
    env_event, _ = event(env_page, action)
    base_event, _ = event(base_page, action)
    for target, expected, base_code in [
        (env_page, env_event, ""),
        (base_page, base_event, base["code"]),
    ]:
        scoped_job = question(target)
        route = c.agent_repository.get_job(scoped_job).routing_context
        assert (route["environment"], route["base"], route["workshop"]) == (
            env["code"],
            base_code,
            "",
        )
        for mode in ("page", "recording", "today"):
            result = live_query.run(c, scoped_job, 0, "search_recording", {"scope": mode})
            assert [hit["event_id"] for hit in result["hits"]] == [expected]


def verify_live_queries(api, client, app, password, headers, monkeypatch):
    import pytest
    from fastapi import HTTPException
    from app.modules.channel.browser import live_query

    c = api.state.container
    env, base, shops, paths = query_principals(c, client, app, password, headers)
    tools = ("search_recording", "get_recording_evidence")

    instant = int(time.time() * 1000)
    lines, real = query_transport(monkeypatch)
    page, event, question = query_clients(c, client, paths, env, base, shops, instant)
    rid = uuid4().hex
    C = page(0, 0, rid, "/c")
    A = page(0, 0, rid, "/a")
    B = page(0, 1, rid, "/b")
    earlier = page(0, 0, uuid4().hex, "/earlier")
    other = page(2, 0, uuid4().hex, "/c")
    separate_app = page(1, 0, uuid4().hex, "/other-app")
    action = {"kind": "action", "action": "click", "element": "button", "node_id": 17}
    ids = [event(t, action)[0] for t in (C, A, B, earlier, other, separate_app)]
    verify_partial_scopes(c, env, base, rid, action, page, event, question)
    event(C, action, instant + 10000)
    job = question(C)
    other_job = question(other)

    def search(**args):
        return live_query.run(c, job, 0, tools[0], args)

    def get(ref, **args):
        return live_query.run(c, job, 0, tools[1], {"reference": ref, **args})

    assert c.tool_service.is_tool_visible_for_job(job_id=job, tool_name=tools[0])
    verify_diagnostic_context(c, job, tools)

    def hits(mode):
        deadline = time.monotonic() + 20
        while True:
            reply = search(scope=mode)
            if reply["coverage"] == "open":
                return reply
            assert time.monotonic() < deadline
            time.sleep(0.2)

    for mode, expected in (
        ("page", [ids[0]]),
        ("recording", [ids[0], ids[1]]),
        ("today", [ids[0], ids[1], ids[3]]),
    ):
        assert {r["event_id"] for r in hits(mode)["hits"]} == set(expected)
    verify_reference_isolation(c, other_job, action, search, get, event, C)
    req = uuid4().hex
    item, raw = event(
        C,
        {
            "kind": "body",
            "request_key": req,
            "status": "captured",
            "value": {"order": "合成工单", "rows": "材料" * 44000},
        },
    )
    candidates = hits("page")["hits"]
    ref = next(r["reference"] for r in candidates if r["event_id"] == item)
    assert [r["event_id"] for r in search(request_key=req)["hits"]] == [item]
    verify_large_detail(get, ref, raw)
    if not real:
        lines.pop((rid, item, 1))
        assert get(ref)["coverage"] == "missing_part"
        c.database.execute(
            "update browser_live_evidence_part set received_ns=1 where recording_id=? and event_id=?",
            (rid, item),
        )
        assert get(ref)["coverage"] == "expired"
    c.database.execute(
        "update platform_workshop set status='disabled' where id=?", (shops[0]["id"],)
    )
    with pytest.raises(HTTPException):
        get(ref)


def check_floating_read(c):
    """Invoke the published tools while the Chrome capture is still active."""
    job = c.database.execute_one("""select p.job_id,p.tab_id,j.internal_user_id,j.project_code
        from browser_live_job_page p join agent_job j on j.id=p.job_id""")
    c.database.execute("update agent_job set status='RUNNING' where id=?", (job["job_id"],))

    def tool(name, arguments):
        return c.tool_service.call_tool(
            job_id=job["job_id"],
            user_id=job["internal_user_id"],
            project_code=job["project_code"],
            tool_name=name,
            arguments={"live": arguments},
        ).summary

    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        requests = tool("search_recording", {"api_path": "/api/save"})["hits"]
        if requests:
            key = requests[0]["request_key"]
            related = tool("search_recording", {"request_key": key})["hits"]
            response = next((r for r in related if r["kind"] == "response"), None)
            body = next(
                (r for r in related if r["kind"] == "body" and r.get("side") == "response"), None
            )
            if response and body:
                detail = tool("get_recording_evidence", {"reference": body["reference"]})
                if "value_json" in detail:
                    actions = tool("search_recording", {"kind": "action", "limit": 32})["hits"]
                    ordered = sorted(actions, key=lambda a: a["source_seq"])
                    names = [a.get("target_text") for a in ordered]
                    menu = next((a for a in ordered if a.get("target_text") == "计划工单"), None)
                    edit = next(
                        (
                            a
                            for a in ordered
                            if a.get("target_text") == "编辑" and "WO-C" in a.get("row_text", "")
                        ),
                        None,
                    )
                    change = next(
                        (
                            a
                            for a in ordered
                            if a.get("action") == "change" and a.get("field_label") == "计划数量"
                        ),
                        None,
                    )
                    if not menu or not edit or not change or "保存" not in names:
                        time.sleep(0.2)
                        continue
                    changed = tool("get_recording_evidence", {"reference": change["reference"]})[
                        "value"
                    ]
                    operations = (
                        menu["source_seq"] < edit["source_seq"] < change["source_seq"]
                        and edit["page_title"] == "合成工单列表"
                        and "WO-A" not in edit["row_text"]
                        and changed["before_value"] == "8"
                        and changed["value"] == "12"
                    )
                    page_text = []
                    for kind in ("baseline", "mutation"):
                        for hit in tool("search_recording", {"kind": kind, "limit": 32})["hits"]:
                            value = tool(
                                "get_recording_evidence", {"reference": hit["reference"]}
                            ).get("value", {})
                            page_text.extend(
                                n["text"] for n in value.get("nodes", []) if "text" in n
                            )
                    if "保存被退回" not in page_text:
                        time.sleep(0.2)
                        continue
                    return {
                        "observedSave": any(
                            a.get("target_text") == "保存"
                            and a["source_seq"] > change["source_seq"]
                            for a in actions
                        ),
                        "operationContext": operations,
                        "observed": {
                            "menu": menu["target_text"],
                            "page": edit["page_title"],
                            "row": edit["row_text"],
                            "row_position": edit["row_position"],
                            "field": changed["field_label"],
                            "before": changed["before_value"],
                            "after": changed["value"],
                            "result": next(text for text in page_text if text == "保存被退回"),
                        },
                        "pageState": "本班次待检验" in page_text
                        and "WO-A" in page_text
                        and not any(
                            "synthetic-" in text and "marker" in text for text in page_text
                        ),
                        "sameTab": all(r["tab_id"] == job["tab_id"] for r in actions + related),
                        "body": json.loads(detail["value_json"])["value"]
                        == {
                            "workOrder": "WO-C",
                            "orderId": 9876543210123456789,
                            "code": "BATCH_REQUIRED",
                        },
                        "status": response["status"],
                    }
        time.sleep(0.3)
    raise AssertionError("the published Job tools did not observe the synthetic save in time")
