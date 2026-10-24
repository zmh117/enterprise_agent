"""Exercise the running, isolated demo; changes ONLY its synthetic SVN repository."""

import concurrent.futures
import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8766"
checks = []
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(path, data=None, expected=200, origin=None):
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(
        BASE + path, data=None if data is None else json.dumps(data).encode(), headers=headers
    )
    try:
        with LOCAL_HTTP.open(request, timeout=15) as response:
            code, body = response.status, response.read()
    except urllib.error.HTTPError as error:
        code, body = error.code, error.read()
    assert code == expected, (path, code, body.decode()[:200])
    return json.loads(body)


def api(path, **data):
    return call("/api/" + path, {"role": "analyst", **data})


def check(label, condition):
    assert condition, label
    checks.append(label)
    print("PASS", label, flush=True)


def run_acceptance():
    api("pause", paused=False)
    api("scenario", scenario="restore")
    initial = api("knowledge")
    initial_count = len(initial["events"])
    changed = api("scenario", scenario="tighten")["revision"]
    current = api("knowledge")
    facts = {f["id"]: f for f in current["facts"]}
    check(
        "真实提交后解析新审批金额与数量",
        "不超过50000" in facts["approval"]["rule"] and "不超过50" in facts["quantity"]["rule"],
    )
    check("查询等待并追上本次目标", current["target"] == changed and current["applied"] >= changed)
    check(
        "两条业务变化保存前后规则",
        len(current["events"]) == min(50, initial_count + 2)
        and all(
            e["revision"] == changed and e["before"] and e["after"] for e in current["events"][:2]
        ),
    )
    api("scenario", scenario="comment")
    comment = api("knowledge")
    check(
        "仅改注释无业务事件",
        len(comment["events"]) == len(current["events"])
        and comment["commits"][0]["outcome"] == "NO_BUSINESS_CHANGE",
    )
    api("scenario", scenario="unrelated")
    unrelated = api("knowledge")
    check(
        "无关目录提交只推进水位",
        unrelated["applied"] > comment["applied"]
        and len(unrelated["events"]) == len(comment["events"]),
    )
    api("scenario", scenario="restore")
    restored = api("knowledge")
    check("规则恢复仍保留原变化", len(restored["events"]) == min(50, initial_count + 4))

    api("pause", paused=True)
    target = api("scenario", scenario="tighten")["revision"]
    with concurrent.futures.ThreadPoolExecutor() as pool:
        pending = pool.submit(api, "query", question="订单审批条件是什么？")
        time.sleep(0.7)
        later = api("scenario", scenario="comment")["revision"]
        api("pause", paused=False)
        answer = pending.result()
    check(
        "查询期间的新提交不移动原目标",
        answer["target"] == target < later and answer["waited_ms"] >= 600,
    )

    api("pause", paused=True)
    api("scenario", scenario="restore")
    started = time.monotonic()
    timeout = call("/api/query", {"role": "analyst", "question": "当前审批条件"}, expected=503)
    check(
        "暂停更新超时且不返回旧规则",
        timeout["error"] == "knowledge_not_ready"
        and "facts" not in timeout
        and 7.5 <= time.monotonic() - started < 13,
    )
    api("pause", paused=False)
    api("knowledge")
    forbidden = call("/api/knowledge", {"role": "visitor"}, expected=403)
    check(
        "未授权演示角色无知识内容",
        forbidden["error"] == "knowledge_forbidden" and "facts" not in forbidden,
    )
    refused = api("query", question="给我源码和 base64")
    check("索要源码只返回拒绝说明", refused["refused"] and not refused["facts"])
    schema = api("query", question="数据库有哪些字段？")
    check(
        "允许表字段元数据",
        schema["facts"][0]["table"] == "orders" and len(schema["facts"][0]["fields"]) == 4,
    )
    unknown = api("query", question="明天会下雨吗？")
    check("未覆盖问题不猜测", not unknown["facts"] and "未被覆盖" in unknown["message"])
    call(
        "/api/query",
        {"role": "analyst", "question": "规则", "source_url": "file:///private"},
        expected=400,
    )
    call(
        "/api/scenario",
        {"role": "analyst", "scenario": "comment"},
        expected=403,
        origin="https://untrusted.example",
    )
    for path in ("/fixtures/OrderPolicy.java", "/private/repository", "/web.py", "/api/source"):
        call(path, expected=404)
    check("禁止额外来源参数、跨站操作及源码路径", True)
    serialized = json.dumps(api("knowledge"), ensure_ascii=False)
    check(
        "所有公开事实和时间轴无源码标记",
        all(
            s not in serialized
            for s in (
                "canApprove",
                "return amountCents",
                "OrderPolicy.java",
                "Deliberately",
                "sha256",
                "condition",
            )
        ),
    )
    print(
        json.dumps({"passed": len(checks), "status": api("status")}, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    try:
        run_acceptance()
    finally:
        api("pause", paused=False)
