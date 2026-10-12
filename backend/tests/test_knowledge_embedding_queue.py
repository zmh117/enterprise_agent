"""在线单槽位/有界排队的合成 ASGI 验收；不加载模型或访问业务数据。"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
import json
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time

import httpx
import pytest
import uvicorn

from app.modules.knowledge.domain.vector_contract import (
    DEADLINE_HEADER,
    MAX_RETRIEVAL_SECONDS,
    VectorError,
    fingerprint,
)
from app.modules.knowledge.infrastructure.embedding_profile import profile
from app.modules.knowledge.infrastructure.vector_clients import EmbeddingClient, QdrantClient
from app.shared.io_deadline import IODeadlineExceeded, io_deadline
from services.knowledge_embedding.api import create_online_app
from services.knowledge_embedding.online_queue import InferenceDeadline, OnlineInferenceQueue

VECTOR = [1.0] + [0.0] * 1023
ROOT = Path(__file__).resolve().parents[2]


class Engine:
    def __init__(self, *, fail=False, block_count=False):
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls, self.encodes = [], []
        self.active = self.peak = 0
        self.fail, self.block_count = fail, block_count

    def count(self, texts):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            self.calls.append(texts[0])
            if self.block_count and texts == ["first"]:
                self.entered.set()
                assert self.release.wait(3)
            return [len(text) + 2 for text in texts]
        finally:
            self.active -= 1

    def encode(self, texts):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            self.encodes.append(texts[0])
            if texts == ["first"]:
                self.entered.set()
                assert self.release.wait(3)
                if self.fail:
                    raise RuntimeError("private synthetic input")
            return [VECTOR[:] for _ in texts]
        finally:
            self.active -= 1


@asynccontextmanager
async def online(engine):
    app = create_online_app(engine)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://synthetic"
        ) as client:
            try:
                yield client
            finally:
                engine.release.set()


async def entered(engine):
    async with asyncio.timeout(1):
        while not engine.entered.is_set():
            await asyncio.sleep(0.005)


def body(text):
    return {"texts": [text], "profile_hash": fingerprint(profile())}


def headers(seconds):
    return {DEADLINE_HEADER: str(int((time.time() + seconds) * 1000))}


async def submit(client, text, *, seconds=2, path="/embed"):
    pending = asyncio.create_task(client.post(path, json=body(text), headers=headers(seconds)))
    # 让请求到达队列，保持测试提交顺序，不依赖 CPU 推理速度。
    await asyncio.sleep(0.01)
    return pending


def test_four_requests_queue_fifo_one_inference_fifth_busy_health_not_queued():
    async def scenario():
        engine = Engine()
        async with online(engine) as client:
            first = await submit(client, "first")
            await entered(engine)
            waiting = [await submit(client, str(i)) for i in range(3)]
            full = await client.post("/embed", json=body("overflow"))
            assert full.status_code == 429
            assert full.json() == {"error_code": "knowledge_embedding_busy"}
            for path in ("/health", "/ready", "/profile"):
                assert (await client.get(path)).status_code == 200
            assert engine.calls == ["first"]
            assert not any(task.done() for task in waiting)
            engine.release.set()
            responses = await asyncio.gather(first, *waiting)
            assert [r.status_code for r in responses] == [200] * 4
            assert all(r.json()["vectors"] == [VECTOR] for r in responses)
            assert engine.calls == ["first", "0", "1", "2"] and engine.peak == 1
            assert (await client.post("/embed", json=body("reused"))).status_code == 200

    asyncio.run(scenario())


def test_queued_timeout_removed_without_model_call_and_capacity_reused():
    async def scenario():
        engine = Engine()
        async with online(engine) as client:
            first = await submit(client, "first")
            await entered(engine)
            started = time.monotonic()
            expired = await client.post("/embed", json=body("expired"), headers=headers(0.08))
            assert expired.status_code == 408 and time.monotonic() - started < 0.5
            assert expired.json() == {"error_code": "knowledge_embedding_read_timeout"}
            waiting = [await submit(client, str(i)) for i in range(3)]
            engine.release.set()
            assert all(r.status_code == 200 for r in await asyncio.gather(first, *waiting))
            assert "expired" not in engine.calls and engine.peak == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("end", ["timeout", "cancel"])
def test_running_request_ends_but_slot_held_until_thread_exits(end):
    async def scenario():
        engine = Engine()
        async with online(engine) as client:
            first = await submit(client, "first", seconds=0.12 if end == "timeout" else 2)
            await entered(engine)
            if end == "timeout":
                assert (await first).status_code == 408
            else:
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
            waiting = [await submit(client, str(i)) for i in range(3)]
            assert (await client.post("/embed", json=body("overflow"))).status_code == 429
            assert engine.calls == ["first"]  # 超时/取消没有提前释放实际推理槽位。
            engine.release.set()
            assert all(r.status_code == 200 for r in await asyncio.gather(*waiting))
            assert engine.calls == ["first", "0", "1", "2"] and engine.peak == 1
            assert (await client.post("/embed", json=body("reused"))).status_code == 200

    asyncio.run(scenario())


def test_queued_cancellation_never_executes_and_releases_waiting_position():
    async def scenario():
        engine = Engine()
        async with online(engine) as client:
            first = await submit(client, "first")
            await entered(engine)
            cancelled = await submit(client, "cancelled")
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            waiting = [await submit(client, str(i)) for i in range(3)]
            engine.release.set()
            assert all(r.status_code == 200 for r in await asyncio.gather(first, *waiting))
            assert "cancelled" not in engine.calls

    asyncio.run(scenario())


@pytest.mark.parametrize("active", [False, True])
def test_disconnect_removes_waiter_but_preserves_running_thread_slot(active):
    async def scenario():
        engine = Engine()
        queue = OnlineInferenceQueue()
        gone = asyncio.Event()

        async def disconnected():
            return gone.is_set()

        async def connected():
            return False

        def work():
            engine.entered.set()
            assert engine.release.wait(3)
            return {"synthetic": True}

        try:
            first = asyncio.create_task(
                queue.run(work, InferenceDeadline([]), disconnected if active else connected)
            )
            await entered(engine)
            if active:
                target = first
            else:
                target = asyncio.create_task(
                    queue.run(
                        lambda: pytest.fail("disconnected waiter executed"),
                        InferenceDeadline([]),
                        disconnected,
                    )
                )
            await asyncio.sleep(0.01)
            gone.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(target, 0.5)
            pending = [
                asyncio.create_task(queue.run(lambda: {}, InferenceDeadline([]), connected))
                for _ in range(3)
            ]
            await asyncio.sleep(0.01)
            with pytest.raises(VectorError, match="knowledge_embedding_busy"):
                await queue.run(lambda: {}, InferenceDeadline([]), connected)
            engine.release.set()
            if not active:
                await first
            assert await asyncio.gather(*pending) == [{}, {}, {}]
        finally:
            engine.release.set()
            await queue.close()

    asyncio.run(scenario())


def test_model_exception_does_not_echo_and_releases_slot_for_waiters():
    async def scenario():
        engine = Engine(fail=True)
        async with online(engine) as client:
            first = await submit(client, "first")
            await entered(engine)
            second = await submit(client, "second")
            engine.release.set()
            failure, success = await asyncio.gather(first, second)
            assert failure.status_code == 500
            assert failure.json() == {"error_code": "knowledge_embedding_failed"}
            assert "private" not in failure.text
            assert success.status_code == 200 and engine.peak == 1

    asyncio.run(scenario())


def test_timeout_in_tokenizer_skips_encode_and_next_request_can_run():
    async def scenario():
        engine = Engine(block_count=True)
        async with online(engine) as client:
            first = await submit(client, "first", seconds=0.1)
            await entered(engine)
            assert (await first).status_code == 408
            second = await submit(client, "second")
            assert engine.calls == ["first"]
            engine.release.set()
            assert (await second).status_code == 200
            assert engine.encodes == ["second"]

    asyncio.run(scenario())


def test_request_body_consumes_same_deadline_before_queueing():
    async def scenario():
        engine = Engine()

        async def slow_body():
            yield b"{"
            await asyncio.sleep(0.2)
            yield b"}"

        async with online(engine) as client:
            started = time.monotonic()
            response = await client.post("/embed", content=slow_body(), headers=headers(0.05))
            assert response.status_code == 408
            assert time.monotonic() - started < 0.15 and not engine.calls
            assert (await client.post("/embed", json=body("after"))).status_code == 200

    asyncio.run(scenario())


def test_online_validation_errors_do_not_leak_slots_or_change_limits():
    async def scenario():
        engine = Engine()
        async with online(engine) as client:
            requests = [
                ({"content": b"{invalid-synthetic"}, 422),
                ({"content": b"x" * (256 * 1024 + 1)}, 413),
                ({"json": body("")}, 422),
                ({"json": body("x" * 4095)}, 422),
                (
                    {"json": {"texts": ["x" * 2000] * 5, "profile_hash": fingerprint(profile())}},
                    422,
                ),
            ]
            for kwargs, expected in requests:
                response = await client.post("/embed", **kwargs)
                assert response.status_code == expected and "synthetic" not in response.text
                assert (await client.post("/embed", json=body("after"))).status_code == 200
            assert engine.peak == 1

    asyncio.run(scenario())


def test_asgi_http_disconnect_removes_queued_request():
    async def scenario():
        engine = Engine()
        async with online(engine) as client:
            first = await submit(client, "first")
            await entered(engine)
            incoming = asyncio.Queue()
            await incoming.put(
                {
                    "type": "http.request",
                    "body": json.dumps(body("gone")).encode(),
                    "more_body": False,
                }
            )
            sent = []

            async def send(message):
                sent.append(message)

            app = client._transport.app
            scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/embed",
                "raw_path": b"/embed",
                "query_string": b"",
                "headers": [(b"content-type", b"application/json")],
                "server": ("synthetic", 80),
                "client": ("synthetic", 1),
            }
            gone = asyncio.create_task(app(scope, incoming.get, send))
            await asyncio.sleep(0.02)
            await incoming.put({"type": "http.disconnect"})
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(gone, 0.5)
            waiting = [await submit(client, str(i)) for i in range(3)]
            engine.release.set()
            assert all(r.status_code == 200 for r in await asyncio.gather(first, *waiting))
            assert "gone" not in engine.calls and sent == []

    asyncio.run(scenario())


def test_queue_shutdown_discards_waiters_and_waits_for_actual_thread_exit():
    async def scenario():
        engine = Engine()
        queue = OnlineInferenceQueue()

        async def connected():
            return False

        def work():
            engine.entered.set()
            assert engine.release.wait(3)
            return {}

        first = asyncio.create_task(queue.run(work, InferenceDeadline([]), connected))
        await entered(engine)
        waiting = asyncio.create_task(
            queue.run(
                lambda: pytest.fail("shutdown waiter executed"), InferenceDeadline([]), connected
            )
        )
        await asyncio.sleep(0.01)
        close = asyncio.create_task(queue.close())
        try:
            with pytest.raises(TimeoutError):
                await waiting
            assert not close.done()
            with pytest.raises(VectorError, match="knowledge_embedding_busy"):
                await queue.run(lambda: {}, InferenceDeadline([]), connected)
        finally:
            engine.release.set()
            await close
            with pytest.raises(TimeoutError):
                await first

    asyncio.run(scenario())


@pytest.mark.parametrize("value", ["bad", "0" * 13, "1" * 12, "１２３４５６７８９０１２３"])
def test_invalid_deadline_never_reaches_model(value):
    async def scenario():
        engine = Engine()
        async with online(engine) as client:
            response = await client.post(
                "/embed", json=body("input"), headers={DEADLINE_HEADER: value}
            )
            assert response.status_code == 422 and not engine.calls

    # 非 ASCII 头通过截止解析器验证；HTTPX 不允许构造这种 HTTP 头。
    if not value.isascii():
        with pytest.raises(VectorError, match="knowledge_embedding_input_invalid"):
            InferenceDeadline([value])
    else:
        asyncio.run(scenario())


def test_duplicate_and_expired_deadlines_rejected_before_inference():
    async def scenario():
        engine = Engine()
        async with online(engine) as client:
            duplicate = [(DEADLINE_HEADER, str(int(time.time() * 1000) + 1000))] * 2
            assert (
                await client.post("/embed", json=body("input"), headers=duplicate)
            ).status_code == 422
            assert (
                await client.post("/embed", json=body("input"), headers=headers(-1))
            ).status_code == 408
            assert not engine.calls

    asyncio.run(scenario())


def test_default_and_far_future_deadline_cannot_exceed_120_seconds():
    assert MAX_RETRIEVAL_SECONDS == 120
    for values in ([], ["9999999999998"]):
        deadline = InferenceDeadline(values)
        assert 119 <= deadline.remaining() <= 120


def test_online_client_propagates_smaller_parent_budget_without_retry_or_fallback():
    requests = []

    def busy(request):
        requests.append(request)
        return httpx.Response(429, json={"error_code": "knowledge_embedding_busy"})

    client = EmbeddingClient(online=True, transport=httpx.MockTransport(busy))
    try:
        before = time.time()
        with io_deadline(0.25), pytest.raises(VectorError, match="knowledge_embedding_busy"):
            client.call(["synthetic"], encode=True)
        assert len(requests) == 1
        request = requests[0]
        assert before < int(request.headers[DEADLINE_HEADER]) / 1000 <= before + 0.26
        assert request.extensions["timeout"]["read"] <= 0.25
        assert request.url.host == "knowledge-embedding-online"
        requests.clear()
        with pytest.raises(VectorError, match="knowledge_embedding_busy"):
            client.call(["synthetic"], encode=True)
        assert len(requests) == 1 and DEADLINE_HEADER in requests[0].headers
        assert requests[0].extensions["timeout"]["read"] <= 120
    finally:
        client.http.close()


def test_online_deadline_header_is_clamped_to_job_budget_in_bounded_http(monkeypatch):
    from types import SimpleNamespace
    from app.modules.knowledge.infrastructure import vector_clients

    captured = []
    expires = int((time.time() + 0.1) * 1000)
    monkeypatch.setattr(
        vector_clients, "current_budget", lambda: SimpleNamespace(deadline_ms=expires)
    )

    def request(method, url, **kwargs):
        captured.append(kwargs)
        return 429, b'{"error_code":"knowledge_embedding_busy"}'

    monkeypatch.setattr(vector_clients, "request_bytes", request)
    client = EmbeddingClient(online=True)
    try:
        with io_deadline(2), pytest.raises(VectorError, match="knowledge_embedding_busy"):
            client.call(["synthetic"], encode=True)
        assert len(captured) == 1
        assert captured[0]["headers"][DEADLINE_HEADER] == str(expires)
    finally:
        client.http.close()


@contextmanager
def loopback_server(engine):
    # 真实 TCP/ASGI 截止验收，仅绑定临时 loopback 端口，不读取部署配置。
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    endpoint = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(
        uvicorn.Config(
            create_online_app(engine),
            log_level="critical",
            access_log=False,
            lifespan="on",
            ws="none",
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        started = time.monotonic()
        while not server.started:
            assert thread.is_alive() and time.monotonic() - started < 3
            time.sleep(0.005)
        yield endpoint
    finally:
        engine.release.set()
        server.should_exit = True
        thread.join(3)
        listener.close()
        assert not thread.is_alive()


def test_real_http_deadline_expires_in_queue_without_late_inference(monkeypatch):
    from app.modules.knowledge.infrastructure import vector_clients

    engine = Engine()
    actual_request = vector_clients.request_bytes
    responses = []
    with loopback_server(engine) as endpoint:
        # 只替换测试目的地址；生产固定路由、截止传播及有界 HTTP 实现保持原样。
        monkeypatch.setattr(
            vector_clients,
            "request_bytes",
            lambda method, url, **kw: actual_request(
                method,
                endpoint + url.removeprefix(vector_clients.RETRIEVAL_EMBEDDING_ENDPOINT),
                **kw,
            ),
        )
        first = threading.Thread(
            target=lambda: responses.append(
                httpx.post(
                    endpoint + "/embed",
                    json=body("first"),
                    headers=headers(2),
                    timeout=2,
                    trust_env=False,
                )
            )
        )
        first.start()
        client = EmbeddingClient(online=True)
        try:
            assert engine.entered.wait(1)
            started = time.monotonic()
            with pytest.raises((IODeadlineExceeded, VectorError)) as caught, io_deadline(0.12):
                client.call(["expired-over-http"], encode=True)
            if isinstance(caught.value, VectorError):
                assert caught.value.code == "knowledge_embedding_read_timeout"
            assert time.monotonic() - started < 0.5
            assert engine.calls == ["first"]
            engine.release.set()
            first.join(2)
            assert not first.is_alive() and responses[0].status_code == 200
            with io_deadline(1):
                assert client.call(["after-http"], encode=True)["vectors"] == [VECTOR]
            assert engine.calls == ["first", "after-http"] and engine.peak == 1
        finally:
            engine.release.set()
            first.join(2)
            client.http.close()


@pytest.mark.parametrize("kind", ["batch", "qdrant"])
def test_deadline_header_only_sent_to_online_embedding(kind):
    seen = []

    def response(request):
        seen.append(request)
        return httpx.Response(
            200, json={"profile": profile(), "profile_hash": fingerprint(profile())}
        )

    transport = httpx.MockTransport(response)
    client = (
        EmbeddingClient(transport=transport)
        if kind == "batch"
        else QdrantClient(transport=transport)
    )
    try:
        with io_deadline(1):
            client.http.request("GET", "/profile")
        assert DEADLINE_HEADER not in seen[0].headers
    finally:
        client.http.close()


def test_embedding_minimum_image_imports_online_factory_without_platform_dependencies(tmp_path):
    for line in (ROOT / "services/knowledge_embedding/Dockerfile").read_text().splitlines():
        if not line.startswith("COPY "):
            continue
        _, *sources, target = shlex.split(line)
        if not target.startswith("/app/"):
            continue
        destination = tmp_path / target.removeprefix("/app/")
        for source_name in sources:
            source = ROOT / source_name
            destination.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(
                    source,
                    destination,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"),
                )
            else:
                shutil.copy2(source, destination / source.name)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from services.knowledge_embedding.api import create_online_app; import sys; assert 'app.shared.database' not in sys.modules; assert 'app.bootstrap' not in sys.modules",
        ],
        cwd=tmp_path,
        env={"PYTHONPATH": f"{tmp_path / 'backend'}:{tmp_path}"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
