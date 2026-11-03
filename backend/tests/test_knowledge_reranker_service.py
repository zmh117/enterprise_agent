"""ASGI queue tests with a blocking synthetic engine, never real relevance proof."""

import asyncio
from contextlib import asynccontextmanager
import threading
import time

import httpx
import pytest

from app.modules.knowledge.domain.rerank_contract import MAX_BODY_BYTES
from app.modules.knowledge.domain.vector_contract import DEADLINE_HEADER, fingerprint
from app.modules.knowledge.infrastructure.reranker_profile import profile
from services.knowledge_reranker.api import create_app


class Engine:
    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls = []
        self.active = self.peak = 0

    def rank(self, query, documents, deadline):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            self.calls.append(query)
            if query == "first":
                self.entered.set()
                assert self.release.wait(3)
            deadline.check()
            if query == "fail":
                raise RuntimeError("private synthetic block")
            return {
                "scores": [1.0] * len(documents),
                "token_counts": [5] * len(documents),
                "truncated": [False] * len(documents),
            }
        finally:
            self.active -= 1


def body(query):
    return {"profile_hash": fingerprint(profile()), "query": query, "documents": [["synthetic"]]}


@asynccontextmanager
async def service(engine):
    app = create_app(engine)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            try:
                yield client
            finally:
                engine.release.set()


async def submit(client, query, seconds=2):
    task = asyncio.create_task(
        client.post(
            "/rerank",
            json=body(query),
            headers={DEADLINE_HEADER: str(int((time.time() + seconds) * 1000))},
        )
    )
    await asyncio.sleep(0.015)
    return task


async def entered(engine):
    async with asyncio.timeout(1):
        while not engine.entered.is_set():
            await asyncio.sleep(0.005)


def test_one_running_three_waiting_then_busy_health_outside_queue():
    async def run():
        engine = Engine()
        async with service(engine) as client:
            first = await submit(client, "first")
            await entered(engine)
            waiting = [await submit(client, str(i)) for i in range(3)]
            busy = await client.post("/rerank", json=body("fifth"))
            assert busy.status_code == 429 and busy.json() == {
                "error_code": "knowledge_rerank_busy"
            }
            for path in ("/health", "/ready", "/profile"):
                assert (await client.get(path)).status_code == 200
            engine.release.set()
            assert [r.status_code for r in await asyncio.gather(first, *waiting)] == [200] * 4
            assert engine.peak == 1 and engine.calls == ["first", "0", "1", "2"]

    asyncio.run(run())


@pytest.mark.parametrize("cancel_running", [False, True])
def test_cancel_waiter_or_worker_never_releases_executing_slot_early(cancel_running):
    async def run():
        engine = Engine()
        async with service(engine) as client:
            first = await submit(client, "first")
            await entered(engine)
            cancelled = first if cancel_running else await submit(client, "cancelled")
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            expired = await submit(client, "expired", seconds=0.05)
            assert (await expired).status_code == 408
            waiting = [await submit(client, str(i)) for i in range(3)]
            assert (await client.post("/rerank", json=body("fifth"))).status_code == 429
            assert engine.calls == ["first"] and engine.active == 1
            engine.release.set()
            assert all(r.status_code == 200 for r in await asyncio.gather(*waiting))
            if not cancel_running:
                assert (await first).status_code == 200
            assert engine.calls == ["first", "0", "1", "2"] and engine.peak == 1

    asyncio.run(run())


def test_deadline_body_limit_validation_and_exception_are_safe():
    async def run():
        engine = Engine()
        async with service(engine) as client:
            failed = await client.post("/rerank", json=body("fail"))
            assert failed.status_code == 503
            assert failed.json() == {"error_code": "knowledge_rerank_unavailable"}
            too_big = await client.post("/rerank", content=b"x" * (MAX_BODY_BYTES + 1))
            assert too_big.status_code == 413
            invalid = await client.post("/rerank", json={**body("private"), "extra": "private"})
            assert invalid.status_code == 422 and "private" not in invalid.text
            expired = await client.post(
                "/rerank",
                json=body("expired"),
                headers={DEADLINE_HEADER: str(int((time.time() - 1) * 1000))},
            )
            assert expired.status_code == 408
            duplicate = [(DEADLINE_HEADER, str(int(time.time() * 1000) + 1000))] * 2
            assert (
                await client.post("/rerank", json=body("invalid"), headers=duplicate)
            ).status_code == 422
            assert engine.calls == ["fail"]

    asyncio.run(run())


def test_disconnect_poll_that_consumes_cancellation_still_finishes_cleanup():
    from services.knowledge_embedding.online_queue import InferenceDeadline, OnlineInferenceQueue

    async def run():
        queue = OnlineInferenceQueue(busy_code="knowledge_rerank_busy")
        started, release = threading.Event(), threading.Event()
        consumed = 0

        async def disconnected():
            nonlocal consumed
            started.set()
            release.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                consumed += 1
                if consumed > 1:
                    raise
                return False

        def work():
            assert release.wait(1)
            return {"ok": True}

        try:
            result = await asyncio.wait_for(
                queue.run(work, InferenceDeadline([]), disconnected), 0.5
            )
            assert started.is_set() and consumed == 1 and result == {"ok": True}
        finally:
            release.set()
            await queue.close()

    asyncio.run(run())
