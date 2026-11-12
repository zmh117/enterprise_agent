"""真实合成 JWT/HTTP/MCP 接线与加速身份时钟；不代表真实六分钟容量。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from app.modules.knowledge.application.principal import (
    PRINCIPAL_REFRESH_PATH,
    current_principal,
    stable_claims,
)
from app.modules.knowledge.application.readability import BRIDGE_PATH
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.infrastructure import readability_bridge as bridge_module
from app.modules.knowledge.infrastructure.readability_client import KnowledgeReadabilityClient
from app.shared.io_deadline import io_deadline, io_wait_timeout
from services.knowledge_mcp_server import principal as principal_module
from services.knowledge_mcp_server.execution import CallControl
from services.knowledge_mcp_server.principal import InflightPrincipal
from backend.tests.test_knowledge_mcp_server import (
    knowledge_contract,
    readable_fixture,
    bridge_fixture,
    search_fixture,
    mcp_fixture,
    rpc,
    headers as mcp_headers,
)

# Pytest 需要显式导入整条合成 fixture 链。
__all__ = [
    "knowledge_contract",
    "readable_fixture",
    "bridge_fixture",
    "search_fixture",
    "mcp_fixture",
]
SCOPE = "mcp:knowledge-mcp:knowledge_search:invoke"


def test_idle_ping_renews_before_expiry_without_business_tool_or_deadline_change(
    mcp_fixture, monkeypatch
):
    f = mcp_fixture
    clock, old = identity_clock(f, monkeypatch)
    f["tools"].principal_client = local_client(f)
    clock[0] = old["iat"] + 241
    headers = {**mcp_headers(f), "X-Knowledge-Principal-Continuation": "1"}
    response = rpc(f, method="ping", params={}, headers=headers)
    assert response.json()["result"] == {}
    fresh = response.headers["X-Knowledge-Principal-Continuation"]
    new = f["bridge"].gateway.principal.verify(fresh, required_scope=SCOPE)
    assert stable_claims(new) == stable_claims(old) and new["exp"] == clock[0] + 300
    assert f["runtime"].database.execute("select id from mcp_operation_audit") == []
    assert not f["exchanges"]
    clock[0] = old["exp"] + 1
    # Expired credentials cannot be rescued by ping; the renewed one remains valid.
    assert "error" in rpc(f, method="ping", params={}, headers=headers).json()
    headers["authorization"] = "Bearer " + fresh
    assert rpc(f, method="ping", params={}, headers=headers).json()["result"] == {}
    f["runtime"].database.execute(
        "update agent_job set status='SUCCEEDED' where id=?", (f["job"].id,)
    )
    assert "error" in rpc(f, method="ping", params={}, headers=headers).json()


def identity_clock(f, monkeypatch):
    gateway = f["bridge"].gateway
    claims = gateway.principal.verify(f["knowledge_token"], required_scope=SCOPE)
    clock = [claims["iat"]]
    for component in (
        gateway.principal,
        gateway.issuer,
        gateway.service_identity,
        f["service_issuer"],
        f["service"].resolver.verifier,
    ):
        monkeypatch.setattr(component, "_now", lambda: clock[0])
    for module in (bridge_module, principal_module):
        monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: clock[0]))
    return clock, claims


def service_token(f):
    # 仅使用此 fixture 的合成 bootstrap credential。
    return f["service_issuer"].issue("k" * 48).access_token


def refresh(f, *, token=None, body=None, headers=None):
    return f["bridge_client"].post(
        PRINCIPAL_REFRESH_PATH,
        json={} if body is None else body,
        headers=headers
        if headers is not None
        else {
            "authorization": "Bearer " + service_token(f),
            "x-knowledge-principal": "Bearer " + (token or f["knowledge_token"]),
        },
    )


def test_refresh_rechecks_full_binding_without_extending_single_ticket(bridge_fixture, monkeypatch):
    f = bridge_fixture
    clock, old = identity_clock(f, monkeypatch)
    clock[0] += 240
    response = refresh(f)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    value = response.json()
    new = f["bridge"].gateway.principal.verify(value["access_token"], required_scope=SCOPE)
    assert new["exp"] == value["expires_at"] == clock[0] + 300
    assert new["jti"] != old["jti"] and stable_claims(new) == stable_claims(old)
    audit = json.dumps(f["runtime"].database.execute("select * from audit_event"), default=str)
    assert value["access_token"] not in audit and f["knowledge_token"] not in audit
    assert not f["exchanges"]


@pytest.mark.parametrize("field", ["job_id", "sub", "server", "scope", "url"])
def test_refresh_rejects_identity_overrides(bridge_fixture, field):
    assert refresh(bridge_fixture, body={field: "untrusted"}).status_code == 400


@pytest.mark.parametrize("kind", ["service", "business", "origin", "cookie", "host", "role"])
def test_refresh_requires_non_browser_dual_identity(bridge_fixture, kind):
    f = bridge_fixture
    headers = {
        "authorization": "Bearer " + f["service_token"],
        "x-knowledge-principal": "Bearer " + f["knowledge_token"],
    }
    if kind == "service":
        del headers["authorization"]
    elif kind == "business":
        del headers["x-knowledge-principal"]
    elif kind == "role":
        headers["authorization"] = "Bearer " + f["file_token"]
    else:
        headers[kind] = "untrusted"
    assert refresh(f, headers=headers).status_code == 401


@pytest.mark.parametrize("change", ["expired", "job_done", "user_disabled", "revoked"])
def test_refresh_rejects_expiry_even_with_clock_leeway_and_current_revocation(
    bridge_fixture,
    monkeypatch,
    change,
):
    f = bridge_fixture
    clock, old = identity_clock(f, monkeypatch)
    db = f["runtime"].database
    if change == "expired":
        clock[0] = old["exp"]
    elif change == "job_done":
        db.execute("update agent_job set status='SUCCEEDED' where id=?", (f["job"].id,))
    elif change == "user_disabled":
        db.execute("update app_user set status='disabled' where id=?", (f["job"].internal_user_id,))
    else:
        db.execute(
            "delete from rbac_role_application_mcp_tool where tool_identifier='knowledge_search'"
        )
    response = refresh(f)
    assert response.status_code in {401, 503} and "access_token" not in response.json()
    assert f["knowledge_token"] not in response.text


@pytest.mark.parametrize(
    "field",
    [
        "sub",
        "job_id",
        "session_id",
        "application_publication_id",
        "agent_publication_id",
        "authorization_hash",
        "aud",
        "scope",
    ],
)
def test_refresh_rejects_signed_binding_changes(bridge_fixture, field):
    f = bridge_fixture
    claims = f["bridge"].gateway.principal.verify(f["knowledge_token"], required_scope=SCOPE)
    claims[field] = [SCOPE] if field == "scope" else "another"
    assert refresh(f, token=f["key"].sign(claims)).status_code == 401


def local_client(f, observed=None):
    def transport(request):
        assert request.url.path in {PRINCIPAL_REFRESH_PATH, BRIDGE_PATH}
        response = f["bridge_client"].post(
            request.url.path,
            content=request.content,
            headers={
                key: value
                for key, value in request.headers.items()
                if key
                in {
                    "authorization",
                    "x-knowledge-principal",
                    "content-type",
                    "x-knowledge-deadline-ms",
                }
            },
        )
        if observed is not None:
            observed.append((request.url.path, request.headers["x-knowledge-principal"][7:]))
        return httpx.Response(response.status_code, content=response.content)

    return KnowledgeReadabilityClient(
        SimpleNamespace(access_token=lambda: service_token(f)),
        transport=httpx.MockTransport(transport),
    )


def wait_for(predicate):
    until = time.monotonic() + 5
    while not predicate() and time.monotonic() < until:
        threading.Event().wait(0.01)
    assert predicate()


@pytest.mark.parametrize("access_mode", ["online", "offline"])
def test_mcp_crosses_old_300_second_expiry_and_reuses_fresh_identity(
    mcp_fixture, monkeypatch, access_mode
):
    f = mcp_fixture
    clock, old = identity_clock(f, monkeypatch)
    observed = []
    client = local_client(f, observed)
    f["tools"].principal_client = client
    from app.modules.knowledge.domain.models import KnowledgeAccessMode

    f["search"].access_mode = KnowledgeAccessMode(access_mode)
    f["search"].readability = client
    fresh = []
    original_authenticate = f["search"].access.authenticate

    def authenticate(token, tool):
        result = original_authenticate(token, tool)
        actual = current_principal(token)
        if actual != f["knowledge_token"]:
            fresh.append(actual)
        return result

    monkeypatch.setattr(f["search"].access, "authenticate", authenticate)
    started, release, renewed = threading.Event(), threading.Event(), threading.Event()
    original_renew = InflightPrincipal._renew

    def finish_renew(lease):
        original_renew(lease)
        renewed.set()

    monkeypatch.setattr(InflightPrincipal, "_renew", finish_renew)
    original = f["search"].reranker.rank

    def held_rank(*args):
        started.set()
        assert release.wait(6)
        return original(*args)

    monkeypatch.setattr(f["search"].reranker, "rank", held_rank)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(
            rpc, f, headers={**mcp_headers(f), "X-Knowledge-Principal-Continuation": "1"}
        )
        try:
            assert started.wait(5)
            clock[0] = old["iat"] + 241
            wait_for(lambda: any(path == PRINCIPAL_REFRESH_PATH for path, _ in observed))
            # 等续期线程校验并换入新票据，再跨过旧票据到期。
            assert renewed.wait(5)
            clock[0] = old["iat"] + 305
        finally:
            release.set()
        response = result.result(timeout=5)
    payload = response.json()["result"]
    assert not payload.get("isError") and payload["structuredContent"]["documents"]
    assert f["search"].reranker.calls == 1
    assert fresh
    bridge_tokens = [token for path, token in observed if path == BRIDGE_PATH]
    assert bool(bridge_tokens) == (access_mode == "online")
    assert all(token in fresh for token in bridge_tokens)
    safe = response.text + json.dumps(
        f["runtime"].database.execute("select * from audit_event"), default=str
    )
    assert fresh[0] not in safe and f["knowledge_token"] not in safe
    assert not any(t.name == "knowledge-principal-refresh" for t in threading.enumerate())

    _assert_continuation(f, response, fresh)


def _assert_continuation(f, response, fresh):
    continued = response.headers["X-Knowledge-Principal-Continuation"]
    assert continued in fresh and response.headers["cache-control"] == "no-store"
    assert not rpc(f, headers={**mcp_headers(f), "authorization": "Bearer " + continued}).json()[
        "result"
    ]["isError"]
    assert rpc(f).json()["result"]["isError"]  # 已过期初始凭证仍失败关闭。
    assert continued not in json.dumps(
        f["runtime"].database.execute("select * from mcp_operation_audit"), default=str
    )


@pytest.mark.parametrize("kind", ["shape", "signature", "aud", "scope", "ttl", "expiry"])
def test_invalid_refresh_response_cancels_without_leaking(search_fixture, monkeypatch, kind):
    f = search_fixture
    clock, old = identity_clock(f, monkeypatch)
    clock[0] += 241
    claims = {**old, "iat": clock[0], "nbf": clock[0], "exp": clock[0] + 300, "jti": "fresh"}
    if kind == "aud":
        claims["aud"] = "ones-mcp"
    elif kind == "scope":
        claims["scope"] = [SCOPE]
    elif kind == "ttl":
        claims["exp"] += 1
    token = "synthetic-private-sentinel" if kind == "signature" else f["key"].sign(claims)
    value = {"access_token": token, "expires_at": claims["exp"] + (kind == "expiry")}
    if kind == "shape":
        value["extra"] = "private-sentinel"
    client = SimpleNamespace(renew_principal=lambda _: value)
    control = CallControl()
    lease = InflightPrincipal(
        f["knowledge_token"], "knowledge_search", f["search"].access, client, control
    )
    with pytest.raises(KnowledgeGovernanceError) as error:
        with lease:
            pytest.fail("invalid identity accepted")
    assert error.value.error_code == "knowledge_principal_refresh_failed"
    assert token not in str(error.value) and control.cancelled.is_set() and lease._token == ""


def test_refresh_failure_interrupts_pending_io_and_cleans_worker(search_fixture, monkeypatch):
    f = search_fixture
    clock, old = identity_clock(f, monkeypatch)
    control = CallControl()
    deadline = control.deadline
    lease = InflightPrincipal(
        f["knowledge_token"], "knowledge_search", f["search"].access, local_client(f), control
    )
    with lease:
        f["runtime"].database.execute("delete from rbac_role_application_knowledge_base")
        clock[0] = old["iat"] + 241
        with pytest.raises(TimeoutError):
            with io_deadline(10, cancelled=control.cancelled.is_set):
                wait_for(control.cancelled.is_set)
                io_wait_timeout(1)
    assert lease.failed and not lease._worker.is_alive() and control.deadline == deadline


def test_parallel_renewals_are_owned_and_do_not_reset_deadline(search_fixture, monkeypatch):
    f = search_fixture
    clock, old = identity_clock(f, monkeypatch)
    controls = [CallControl() for _ in range(4)]
    deadlines = [c.deadline for c in controls]
    leases = [
        InflightPrincipal(
            f["knowledge_token"], "knowledge_search", f["search"].access, local_client(f), c
        )
        for c in controls
    ]
    with ExitStack() as stack:
        for lease in leases:
            stack.enter_context(lease)
        controls[0].cancelled.set()
        clock[0] = old["iat"] + 241
        wait_for(lambda: all(lease._expires > old["exp"] for lease in leases[1:]))
        assert len({lease.current() for lease in leases[1:]}) == 3
        assert leases[0]._expires == old["exp"]
        assert [c.deadline for c in controls] == deadlines
    assert all(not lease._worker.is_alive() and not lease._token for lease in leases)


def test_ending_request_cancels_renewal_io_without_background_residue(search_fixture, monkeypatch):
    f = search_fixture
    clock, old = identity_clock(f, monkeypatch)
    started = threading.Event()

    def blocked_refresh(_):
        started.set()
        while True:
            io_wait_timeout(5)
            threading.Event().wait(0.01)

    control = CallControl()
    lease = InflightPrincipal(
        f["knowledge_token"],
        "knowledge_search",
        f["search"].access,
        SimpleNamespace(renew_principal=blocked_refresh),
        control,
    )
    with lease:
        clock[0] = old["iat"] + 241
        assert started.wait(5)
        closing = time.monotonic()
    assert time.monotonic() - closing < 1
    assert not lease._worker.is_alive() and not lease._token
    assert not lease.failed and not control.cancelled.is_set()


def test_content_broker_reads_current_ticket_after_old_expiry(search_fixture, monkeypatch):
    from app.modules.knowledge.application.storage_broker import STORAGE_PATH
    from services.knowledge_mcp_server.storage_credentials import (
        BrokerStorageCredentials,
        storage_principal,
    )

    f = search_fixture
    clock, old = identity_clock(f, monkeypatch)
    clock[0] += 241
    config = {"postgres": {"mode": "managed"}, "qdrant": {"api_key_ref": ""}}
    observed = []

    def transport(request):
        assert request.url.path == STORAGE_PATH
        token = request.headers["x-knowledge-principal"][7:]
        f["bridge"].gateway.authenticate(request.headers["authorization"][7:], token)
        observed.append(token)
        body = json.loads(request.content)
        return httpx.Response(200, json={**body, "config": config, "credentials": {}})

    broker = BrokerStorageCredentials(
        KnowledgeReadabilityClient(
            SimpleNamespace(access_token=lambda: service_token(f)),
            transport=httpx.MockTransport(transport),
        )
    )
    with (
        InflightPrincipal(
            f["knowledge_token"],
            "knowledge_search",
            f["search"].access,
            local_client(f),
            CallControl(),
        ) as lease,
        storage_principal(lease.current),
    ):
        clock[0] = old["iat"] + 305
        assert broker(config, "synthetic-base", "synthetic-revision") == {}
        assert observed == [lease.current()] and observed[0] != f["knowledge_token"]


def test_mcp_reports_refresh_failure_and_audits_after_inflight_revocation(mcp_fixture, monkeypatch):
    f = mcp_fixture
    clock, old = identity_clock(f, monkeypatch)
    f["tools"].principal_client = local_client(f)
    started = threading.Event()

    def pending_rank(*_):
        started.set()
        until = time.monotonic() + 5
        while time.monotonic() < until:
            io_wait_timeout(1)
            threading.Event().wait(0.01)
        raise AssertionError("renewal did not cancel pending I/O")

    monkeypatch.setattr(f["search"].reranker, "rank", pending_rank)
    with ThreadPoolExecutor(max_workers=1) as pool:
        response = pool.submit(rpc, f)
        assert started.wait(5)
        f["runtime"].database.execute(
            "delete from rbac_role_application_mcp_tool where tool_identifier='knowledge_search'"
        )
        clock[0] = old["iat"] + 241
        result = response.result(timeout=5).json()["result"]
    assert result["isError"]
    assert result["structuredContent"]["error_code"] == "knowledge_principal_refresh_failed"
    rows = f["runtime"].database.execute(
        "select status,error_code from mcp_operation_audit where tool_identifier='knowledge_search'"
    )
    assert rows[-1]["status"] == "FAILED"
    assert rows[-1]["error_code"] == "knowledge_principal_refresh_failed"
    assert not any(t.name == "knowledge-principal-refresh" for t in threading.enumerate())


def test_original_deadline_is_not_reported_as_identity_failure(search_fixture):
    f = search_fixture
    control = CallControl(seconds=0.1)
    with InflightPrincipal(
        f["knowledge_token"],
        "knowledge_search",
        f["search"].access,
        local_client(f),
        control,
    ) as lease:
        wait_for(lambda: not lease._worker.is_alive())
        assert control.remaining() <= 0 and not lease.failed
        with pytest.raises(KnowledgeGovernanceError, match="knowledge_search_budget_exhausted"):
            control.check()
