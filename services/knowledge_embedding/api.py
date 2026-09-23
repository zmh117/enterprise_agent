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
    VectorError,
    fingerprint,
    texts_from_request,
)
from app.modules.knowledge.infrastructure.embedding_profile import profile


def create_app(engine: Any = None) -> FastAPI:  # noqa: C901
    gate = threading.Lock()
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
        yield

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
        if current["engine"] is None:
            return JSONResponse({"error_code": "knowledge_model_unavailable"}, status_code=503)
        if not gate.acquire(blocking=False):
            return JSONResponse({"error_code": "knowledge_embedding_busy"}, status_code=429)
        try:
            body = bytearray()
            with anyio.fail_after(15):
                async for part in request.stream():
                    body.extend(part)
                    if len(body) > MAX_BODY_BYTES:
                        return JSONResponse(
                            {"error_code": "knowledge_embedding_body_limit"}, status_code=413
                        )
            try:
                value = json.loads(body)
            except (ValueError, UnicodeError):
                raise VectorError("knowledge_embedding_input_invalid") from None
            texts = texts_from_request(value, profile())
            counts = await run_in_threadpool(current["engine"].count, texts)
            if any(c > MAX_TOKENS for c in counts):
                raise VectorError("knowledge_embedding_token_limit")
            result: dict[str, Any] = {
                "profile_hash": fingerprint(profile()),
                "token_counts": counts,
                "input_hashes": [fingerprint(t) for t in texts],
            }
            if request.url.path == "/embed":
                if sum(counts) > MAX_BATCH_TOKENS:
                    raise VectorError("knowledge_embedding_batch_limit")
                result["vectors"] = await run_in_threadpool(current["engine"].encode, texts)
            return JSONResponse(result)
        except VectorError as exc:
            return JSONResponse({"error_code": exc.code}, status_code=422)
        except TimeoutError:
            return JSONResponse({"error_code": "knowledge_embedding_read_timeout"}, status_code=408)
        except Exception:
            return JSONResponse({"error_code": "knowledge_embedding_failed"}, status_code=500)
        finally:
            gate.release()

    return app
