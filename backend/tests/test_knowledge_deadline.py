"""合成截止时间传播与本机临时 HTTP 慢响应测试，不调用真实业务服务。"""

from app.modules.knowledge.infrastructure.reader_access import job_budget

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import threading
import time
from types import SimpleNamespace

import pytest

from app.modules.identity.application.service_principal import ServicePrincipalTokenClient
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.application.readability import BRIDGE_PATH, READABILITY_PATH
from app.modules.knowledge.application.retrieval_budget import DEADLINE_HEADER
from app.shared.bounded_read_http import request_bytes
from app.shared.exceptions import AppError, RetryableExecutionError
from app.shared.ones_io_budget import ones_io_budget, ones_io_timeout
from app.shared.database import Database
from backend.tests.test_knowledge_search import (
    knowledge_contract as knowledge_contract,
    readable_fixture as readable_fixture,
    bridge_fixture as bridge_fixture,
    search_fixture as search_fixture,
    search,
)


@contextmanager
def local_server():
    stopped, disconnected = threading.Event(), threading.Event()
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            paths.append(self.path)
            try:
                if self.path == "/stall":
                    stopped.wait(1)
                status = 302 if self.path == "/redirect" else 200
                self.send_response(status)
                if status == 302:
                    self.send_header("Location", "/forbidden")
                if self.path == "/encoding":
                    self.send_header("Content-Encoding", "gzip")
                self.end_headers()
                if self.path == "/drip":
                    for _ in range(100):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        if stopped.wait(0.02):
                            break
                else:
                    self.wfile.write(
                        self.headers["Host"].encode() if self.path == "/host" else b"{}"
                    )
            except (BrokenPipeError, ConnectionResetError):
                disconnected.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", paths, disconnected
    finally:
        stopped.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=1)
        assert not worker.is_alive()


@pytest.mark.parametrize("path", ["/drip", "/stall"])
def test_total_http_timeout_cancels_slow_stream_not_only_idle_read(path):
    with local_server() as (url, paths, disconnected):
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            request_bytes("GET", url + path, headers={}, content=None, timeout=0.25, max_bytes=1024)
        assert time.monotonic() - started < 0.8
        assert paths == [path]
        if path == "/drip":
            assert disconnected.wait(0.5)


@pytest.mark.parametrize("path,maximum", [("/encoding", 1024), ("/ok", 1)])
def test_http_encoding_and_size_fail_closed(path, maximum):
    with local_server() as (url, _, _):
        with pytest.raises(ValueError):
            request_bytes("GET", url + path, headers={}, content=None, timeout=1, max_bytes=maximum)


def test_http_no_redirect_or_ambient_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    with local_server() as (url, paths, _):
        status, body = request_bytes(
            "GET", url + "/redirect", headers={}, content=None, timeout=1, max_bytes=1024
        )
        assert status == 302 and body == b"{}" and paths == ["/redirect"]


def test_http_library_logs_do_not_expose_candidate_urls_or_auth(caplog):
    caplog.set_level(logging.DEBUG)
    with local_server() as (url, _, _):
        request_bytes(
            "GET",
            url + "/synthetic-private-candidate",
            content=None,
            headers={"Authorization": "Bearer synthetic-only-token"},
            timeout=1,
            max_bytes=1024,
        )
    assert "synthetic-private-candidate" not in caplog.text
    assert "synthetic-only-token" not in caplog.text
    assert not [r for r in caplog.records if r.name.startswith(("httpx", "httpcore"))]
    logging.getLogger("httpx").info("synthetic-ordinary-call")
    assert "synthetic-ordinary-call" in caplog.text


def identity_client(monkeypatch, exchange):
    from app.modules.identity.application import service_principal

    monkeypatch.setattr(
        service_principal, "_read_bootstrap_credential", lambda *a, **k: "synthetic-only"
    )
    return ServicePrincipalTokenClient(
        base_url="http://api-server:8000",
        allowed_hosts=("api-server",),
        bootstrap_credential_file="synthetic-not-read",
        transport=SimpleNamespace(exchange=exchange),
    )


def test_service_identity_refresh_lock_is_bounded_and_reusable(monkeypatch):
    calls = []

    def exchange(**kwargs):
        calls.append(kwargs["timeout_seconds"])
        return {"access_token": "synthetic-token", "token_type": "Bearer", "expires_in": 300}

    client = identity_client(monkeypatch, exchange)
    client._lock.acquire()
    try:
        with pytest.raises(AppError):
            with ones_io_budget(0.05):
                client.access_token()
        assert not calls
    finally:
        client._lock.release()
    with ones_io_budget(0.5):
        assert client.access_token() == "synthetic-token"
    assert 0 < calls[0] <= 0.5 and ones_io_timeout(5) == 5


def test_service_identity_late_refresh_cannot_fallback_or_cache(monkeypatch):
    from app.shared import ones_io_budget as io

    tick = [10.0]
    monkeypatch.setattr(io, "time", SimpleNamespace(monotonic=lambda: tick[0]))

    def exchange(**kwargs):
        tick[0] += 2
        raise RetryableExecutionError("synthetic-failure")

    client = identity_client(monkeypatch, exchange)
    client._token, client._expires_at = "synthetic-previous", client._now() + 30
    with pytest.raises(AppError, match="budget exhausted"):
        with ones_io_budget(1):
            client.access_token()
    assert client._token == "synthetic-previous" and not client._lock.locked()


def test_same_deadline_crosses_both_http_hops_and_limits_provider(search_fixture, monkeypatch):

    f, observed, provider_limits = search_fixture, [], []
    deadline = int(time.time() * 1000) + 1500
    monkeypatch.setattr(
        f["search"].access,
        "budget",
        lambda job: job_budget(f["runtime"].database, job, deadline_ms=deadline),
    )
    for target in (f["bridge"], f["endpoint"]):
        original = target.check

        def check(*, _original=original, **kwargs):
            observed.append(kwargs["deadline_ms"])
            return _original(**kwargs)

        monkeypatch.setattr(target, "check", check)
    original_provider = f["provider_http"]._open_response

    def provider(request, timeout):
        provider_limits.append(timeout)
        return original_provider(request, timeout)

    f["provider_http"]._open_response = provider
    assert search(f)["documents"]
    assert len(observed) == 2 and observed[1] <= observed[0] <= deadline
    assert all(0 < seconds <= 1.5 for seconds in provider_limits)


@pytest.mark.parametrize("destination", ["bridge", "ones"])
@pytest.mark.parametrize(
    "header", ["", "nan", "0", "9" * 100, "1234567890123,1234567890123", "duplicate", "expired"]
)
def test_invalid_or_expired_deadline_never_reaches_provider(bridge_fixture, destination, header):
    f = bridge_fixture
    path = BRIDGE_PATH if destination == "bridge" else READABILITY_PATH
    client = f["bridge_client"] if destination == "bridge" else f["client"]
    headers = [
        ("content-type", "application/json"),
        (
            "authorization",
            "Bearer " + (f["service_token"] if destination == "bridge" else f["token"]),
        ),
    ]
    if destination == "bridge":
        headers.append(("X-Knowledge-Principal", "Bearer " + f["knowledge_token"]))
    value = str(int(time.time() * 1000) - 1000) if header == "expired" else header
    if header == "duplicate":
        value = str(int(time.time() * 1000) + 1000)
        headers.append((DEADLINE_HEADER, value))
    headers.append((DEADLINE_HEADER, value))
    response = client.post(path, content=json.dumps(f["body"]), headers=headers)
    assert response.status_code == (503 if header == "expired" else 400)
    assert not f["calls"] and not f["exchanges"]


def test_future_deadline_cannot_expand_local_budget(search_fixture):
    f = search_fixture
    budget = job_budget(f["runtime"].database, f["job"].id, deadline_ms=9_999_999_999_999)
    assert 0 < budget.remaining() <= 120
    with pytest.raises(KnowledgeGovernanceError):
        job_budget(f["runtime"].database, f["job"].id, deadline_ms=int(time.time() * 1000) - 1)


def test_ones_refresh_budget_failure_does_not_revoke_existing_credential(readable_fixture):
    f = readable_fixture

    def unauthorized(*args):
        raise f["provider_http"].status_error(401)

    def expired(**kwargs):
        raise RetryableExecutionError("synthetic-expired", error_code="ones_read_budget_exhausted")

    f["provider_http"]._open_response = unauthorized
    f["login"].verify = expired
    response = f["client"].post(
        READABILITY_PATH, json=f["body"], headers={"Authorization": "Bearer " + f["token"]}
    )
    assert response.status_code == 503
    row = f["runtime"].database.execute_one(
        "select status from external_identity_credential where provider='ones'"
    )
    assert row["status"] == "ACTIVE"


def test_production_bridge_clients_keep_fixed_headers_and_deadline(search_fixture, monkeypatch):
    from app.modules.knowledge.infrastructure import readability_client, readability_bridge

    f, urls = search_fixture, []

    def bounded(method, url, *, headers, content, timeout, max_bytes):
        assert method == "POST" and DEADLINE_HEADER in headers
        assert 0 < timeout <= 120 and max_bytes == 64 * 1024
        urls.append(url)
        if url == "http://api-server:8000" + BRIDGE_PATH:
            response = f["bridge_client"].post(BRIDGE_PATH, content=content, headers=headers)
        else:
            assert url == "http://ones-mcp:9104" + READABILITY_PATH
            response = f["client"].post(READABILITY_PATH, content=content, headers=headers)
        return response.status_code, response.content

    monkeypatch.setattr(readability_client, "request_bytes", bounded)
    monkeypatch.setattr(readability_bridge, "request_bytes", bounded)
    f["search"].readability._transport = None
    f["bridge"].gateway._transport = None
    assert search(f)["documents"]
    assert len(urls) == 2 and f["calls"] == ["POST"]


def test_online_vector_client_uses_total_http_budget(search_fixture, monkeypatch):
    from app.modules.knowledge.infrastructure import vector_clients

    f, requests = search_fixture, []

    def bounded(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return 200, b'{"result":{}}'

    monkeypatch.setattr(vector_clients, "request_bytes", bounded)
    client = vector_clients.InternalHttp("http://knowledge-qdrant:6333")
    try:
        with job_budget(f["runtime"].database, f["job"].id).activate():
            assert client.request("GET", "/collections") == {"result": {}}
        assert len(requests) == 1 and requests[0][1] == "http://knowledge-qdrant:6333/collections"
        assert requests[0][2]["timeout"] <= 120
    finally:
        client.close()


@pytest.mark.parametrize("destination", ["bridge", "ones"])
def test_http_entry_budget_precedes_first_authentication(bridge_fixture, monkeypatch, destination):
    # Import lazily: the blocking helpers themselves reuse local_server from this module.
    from backend.tests.test_knowledge_io_cancellation import held_connection

    f = bridge_fixture
    blocked = Database("sqlite:///:memory:", pool_max_size=1, pool_timeout_seconds=3)
    target = f["bridge"] if destination == "bridge" else f["endpoint"].detail
    original = target.authenticate

    def authenticate(*args):
        blocked.execute("select 1")
        return original(*args)

    monkeypatch.setattr(target, "authenticate", authenticate)
    path = BRIDGE_PATH if destination == "bridge" else READABILITY_PATH
    client = f["bridge_client"] if destination == "bridge" else f["client"]
    headers = {
        "Authorization": "Bearer " + (f["service_token"] if destination == "bridge" else f["token"])
    }
    if destination == "bridge":
        headers["X-Knowledge-Principal"] = "Bearer " + f["knowledge_token"]
    try:
        with held_connection(blocked):
            started = time.monotonic()
            response = client.post(
                path,
                json=f["body"],
                headers={**headers, DEADLINE_HEADER: str(int(time.time() * 1000) + 100)},
            )
            assert time.monotonic() - started < 0.8
            assert response.status_code == 503
            assert not f["calls"]
        assert client.post(path, json=f["body"], headers=headers).status_code == 200
    finally:
        blocked.close()
