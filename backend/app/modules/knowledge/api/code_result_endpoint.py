"""Transient Worker responses; API service identity plus current operation authorization."""

from collections.abc import Callable
import asyncio
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_json import parse_json
from app.modules.knowledge.infrastructure.code_result_buffer import CodeResultBuffer
from app.shared.code_result_contract import CODE_RESULT_PATH, CODE_RESULT_HOSTS


class ResultVerifier(Protocol):
    def verify(self, token: str) -> None: ...


def code_result_app(
    *,
    verifier: ResultVerifier,
    buffer: CodeResultBuffer,
    authorize: Callable[[str, int], dict[str, Any]],
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}

    @app.post(CODE_RESULT_PATH)
    async def result(request: Request) -> JSONResponse:
        try:
            if (
                len(request.headers.getlist("host")) != 1
                or request.headers["host"] not in CODE_RESULT_HOSTS
                or "origin" in request.headers
                or "cookie" in request.headers
                or request.url.query
                or request.headers.getlist("content-type") != ["application/json"]
                or len(request.headers.getlist("authorization")) != 1
            ):
                raise CodeKnowledgeError("CODE_RESULT_DENIED")
            authorization = request.headers["authorization"]
            if not authorization.startswith("Bearer ") or len(authorization) > 32768:
                raise CodeKnowledgeError("CODE_RESULT_DENIED")
            await run_in_threadpool(verifier.verify, authorization[7:])
            body = bytearray()
            async with asyncio.timeout(5):
                async for part in request.stream():
                    if len(body) + len(part) > 2048:
                        raise CodeKnowledgeError("CODE_RESULT_DENIED")
                    body.extend(part)
            value = parse_json(body.decode("utf-8"))
            if (
                not isinstance(value, dict)
                or set(value) != {"operation_id", "claim_version"}
                or not isinstance(value["operation_id"], str)
                or not 1 <= len(value["operation_id"]) <= 128
                or type(value["claim_version"]) is not int
                or value["claim_version"] < 1
            ):
                raise CodeKnowledgeError("CODE_RESULT_DENIED")
            operation_id, claim = value["operation_id"], value["claim_version"]
            before = await run_in_threadpool(authorize, operation_id, claim)
            payload = buffer.get(operation_id, claim, expected_hash=before["result_hash"])
            after = await run_in_threadpool(authorize, operation_id, claim)
            if before != after:
                raise CodeKnowledgeError("CODE_RESULT_AUTHORIZATION_CHANGED")
            # A slow authorization recheck must not return an already expired buffer.
            buffer.get(operation_id, claim, expected_hash=after["result_hash"])
            return JSONResponse(payload, headers=headers)
        except CodeKnowledgeError as exc:
            allowed = {
                "CODE_RESULT_EXPIRED": 410,
                "CODE_RESULT_BUFFER_FULL": 503,
                "CODE_HISTORY_RESULT_CHANGED": 409,
            }
            code = exc.code if exc.code in allowed else "CODE_RESULT_DENIED"
            return JSONResponse({"error_code": code}, allowed.get(code, 403), headers=headers)
        except Exception:
            # Authentication/DB errors may contain payloads or credentials. Never log them.
            return JSONResponse({"error_code": "CODE_RESULT_DENIED"}, 403, headers=headers)

    return app
