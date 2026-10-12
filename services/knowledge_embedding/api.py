"""内部、无正文日志的有界 HTTP 入口；不接受用户指定模型或远程地址。"""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import json
import threading
from typing import Any

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.modules.knowledge.domain.vector_contract import (
    MAX_BATCH_TOKENS,
    MAX_BODY_BYTES,
    MAX_TOKENS,
    DEADLINE_HEADER,
    VectorError,
    fingerprint,
    texts_from_request,
)
from app.modules.knowledge.infrastructure.embedding_profile import profile
from services.knowledge_embedding.online_queue import InferenceDeadline, OnlineInferenceQueue


async def _texts(request: Request, seconds: float = 15) -> list[str]:
    body = bytearray()
    with anyio.fail_after(min(15, seconds)):
        async for part in request.stream():
            body.extend(part)
            if len(body) > MAX_BODY_BYTES:
                raise VectorError("knowledge_embedding_body_limit")
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        raise VectorError("knowledge_embedding_input_invalid") from None
    return texts_from_request(value, profile())


def _infer(
    engine: Any, texts: list[str], encode: bool, deadline: InferenceDeadline | None = None
) -> dict[str, Any]:
    if deadline is not None:
        deadline.check()
    counts = engine.count(texts)
    if deadline is not None:
        deadline.check()
    if any(c > MAX_TOKENS for c in counts):
        raise VectorError("knowledge_embedding_token_limit")
    result: dict[str, Any] = {
        "profile_hash": fingerprint(profile()),
        "token_counts": counts,
        "input_hashes": [fingerprint(t) for t in texts],
    }
    if encode:
        if sum(counts) > MAX_BATCH_TOKENS:
            raise VectorError("knowledge_embedding_batch_limit")
        result["vectors"] = engine.encode(texts)
    if deadline is not None:
        deadline.check()
    return result


def create_online_app(engine: Any = None) -> FastAPI:
    return create_app(engine, online=True)


async def _process(
    request: Request, engine: Any, queue: OnlineInferenceQueue | None, gate: Any
) -> JSONResponse:
    if engine is None:
        return JSONResponse({"error_code": "knowledge_model_unavailable"}, status_code=503)
    if queue is None and not gate.acquire(blocking=False):
        return JSONResponse({"error_code": "knowledge_embedding_busy"}, status_code=429)
    try:
        encode = request.url.path == "/embed"
        if queue is not None:
            deadline = InferenceDeadline(request.headers.getlist(DEADLINE_HEADER))
            texts = await _texts(request, deadline.remaining())
            result = await queue.run(
                lambda: _infer(engine, texts, encode, deadline), deadline, request.is_disconnected
            )
        else:
            texts = await _texts(request)
            result = await run_in_threadpool(_infer, engine, texts, encode)
        return JSONResponse(result)
    except VectorError as exc:
        status = 429 if exc.code == "knowledge_embedding_busy" else 422
        if exc.code == "knowledge_embedding_body_limit":
            status = 413
        return JSONResponse({"error_code": exc.code}, status_code=status)
    except TimeoutError:
        return JSONResponse({"error_code": "knowledge_embedding_read_timeout"}, status_code=408)
    except Exception:
        return JSONResponse({"error_code": "knowledge_embedding_failed"}, status_code=500)
    finally:
        if queue is None:
            gate.release()


def create_app(engine: Any = None, *, online: bool = False) -> FastAPI:
    gate = threading.Lock()
    queue = OnlineInferenceQueue() if online else None
    current: dict[str, Any] = {"engine": engine}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if current["engine"] is None:
            try:
                from services.knowledge_embedding.engine import EmbeddingEngine

                current["engine"] = await run_in_threadpool(EmbeddingEngine)
            except Exception:
                print(
                    '{"event":"embedding_start_failed","error_code":"knowledge_model_unavailable"}',
                    flush=True,
                )
        try:
            yield
        finally:
            if queue is not None:
                await queue.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        return JSONResponse(
            {"ready": current["engine"] is not None},
            status_code=200 if current["engine"] is not None else 503,
        )

    @app.get("/profile")
    async def describe() -> Any:
        if current["engine"] is None:
            return JSONResponse({"error_code": "knowledge_model_unavailable"}, status_code=503)
        return {"profile": profile(), "profile_hash": fingerprint(profile())}

    @app.post("/tokenize")
    @app.post("/embed")
    async def process(request: Request) -> JSONResponse:
        return await _process(request, current["engine"], queue, gate)

    return app
