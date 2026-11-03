"""只接受固定 profile 和有界候选的内部重排 API，无正文日志。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
from typing import Any

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.modules.knowledge.domain.rerank_contract import (
    MAX_BODY_BYTES,
    SAFE_ERRORS,
    checked_request,
    checked_result,
    input_hashes,
)
from app.modules.knowledge.domain.vector_contract import DEADLINE_HEADER, VectorError, fingerprint
from app.modules.knowledge.infrastructure.reranker_profile import profile
from services.knowledge_embedding.online_queue import InferenceDeadline, OnlineInferenceQueue


async def read_request(
    request: Request, deadline: InferenceDeadline
) -> tuple[str, list[list[str]]]:
    body = bytearray()
    with anyio.fail_after(min(15, deadline.remaining())):
        async for part in request.stream():
            body.extend(part)
            if len(body) > MAX_BODY_BYTES:
                raise VectorError("knowledge_rerank_input_limit")
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        raise VectorError("knowledge_rerank_input_invalid") from None
    return checked_request(value, fingerprint(profile()))


def infer(
    engine: Any, query: str, documents: list[list[str]], deadline: InferenceDeadline
) -> dict[str, Any]:
    deadline.check()
    result = engine.rank(query, documents, deadline)
    deadline.check()
    value = {
        **result,
        "profile_hash": fingerprint(profile()),
        "input_hashes": input_hashes(query, documents),
    }
    return checked_result(
        value, profile_hash=fingerprint(profile()), query=query, documents=documents
    )


def create_app(engine: Any = None) -> FastAPI:
    queue = OnlineInferenceQueue(busy_code="knowledge_rerank_busy", thread_name="knowledge-rerank")
    current: dict[str, Any] = {"engine": engine}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if current["engine"] is None:
            try:
                from services.knowledge_reranker.engine import RerankerEngine

                current["engine"] = await run_in_threadpool(RerankerEngine)
            except Exception:
                print(
                    '{"event":"reranker_start_failed","error_code":"knowledge_rerank_unavailable"}',
                    flush=True,
                )
        try:
            yield
        finally:
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
    async def describe() -> JSONResponse:
        if current["engine"] is None:
            return JSONResponse({"error_code": "knowledge_rerank_unavailable"}, status_code=503)
        return JSONResponse({"profile": profile(), "profile_hash": fingerprint(profile())})

    @app.post("/rerank")
    async def process(request: Request) -> JSONResponse:
        if current["engine"] is None:
            return JSONResponse({"error_code": "knowledge_rerank_unavailable"}, status_code=503)
        try:
            deadline = InferenceDeadline(
                request.headers.getlist(DEADLINE_HEADER),
                invalid_code="knowledge_rerank_input_invalid",
            )
            query, documents = await read_request(request, deadline)
            value = await queue.run(
                lambda: infer(current["engine"], query, documents, deadline),
                deadline,
                request.is_disconnected,
            )
            return JSONResponse(value)
        except VectorError as exc:
            code = exc.code if exc.code in SAFE_ERRORS else "knowledge_rerank_unavailable"
            status = 429 if code == "knowledge_rerank_busy" else 422
            if code == "knowledge_rerank_input_limit":
                status = 413
            return JSONResponse({"error_code": code}, status_code=status)
        except TimeoutError:
            return JSONResponse({"error_code": "knowledge_rerank_read_timeout"}, status_code=408)
        except Exception:
            return JSONResponse({"error_code": "knowledge_rerank_unavailable"}, status_code=503)

    return app
