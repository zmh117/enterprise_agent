"""非浏览器、非模型工具的平台内部双身份入口。"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError, strict_object
from app.modules.knowledge.application.readability import (
    BRIDGE_PATH,
    MAX_REQUEST_BYTES,
    ReadabilityRequest,
)
from app.shared.exceptions import AppError
from app.modules.knowledge.application.retrieval_budget import (
    DEADLINE_HEADER,
    deadline_from_headers,
)
from app.shared.principal_token_contract import MAX_PRINCIPAL_TOKEN_BYTES
from app.modules.knowledge.application.storage_broker import STORAGE_PATH, StorageConnectionRequest
from app.modules.knowledge.api.deadline import bounded_knowledge_request


def _bearer(request: Request, name: str) -> str:
    values = request.headers.getlist(name)
    if (
        len(values) != 1
        or not values[0].startswith("Bearer ")
        or not 0 < len(values[0][7:]) <= MAX_PRINCIPAL_TOKEN_BYTES
        or any(c.isspace() for c in values[0][7:])
    ):
        raise ValueError
    return values[0][7:]


def build_knowledge_readability_router() -> APIRouter:
    router = APIRouter()

    @router.post(BRIDGE_PATH)
    @router.post(STORAGE_PATH)
    @bounded_knowledge_request
    async def check_readability(request: Request) -> JSONResponse:
        runtime = request.app.state.container
        storage_request = request.url.path == STORAGE_PATH
        bridge = getattr(
            runtime,
            "knowledge_storage_broker" if storage_request else "knowledge_readability_bridge",
            None,
        )
        code, status = "knowledge_bridge_unavailable", 503
        if bridge is not None:
            try:
                status, code = 401, "knowledge_bridge_identity_invalid"
                if (
                    request.headers.getlist("host") not in (["api-server"], ["api-server:8000"])
                    or "origin" in request.headers
                    or "cookie" in request.headers
                    or request.url.query
                ):
                    raise ValueError
                service_token = _bearer(request, "authorization")
                knowledge_token = _bearer(request, "x-knowledge-principal")
                await run_in_threadpool(bridge.authenticate, service_token, knowledge_token)
                status, code = 400, "knowledge_input_invalid"
                if request.headers.getlist("content-type") != ["application/json"]:
                    raise ValueError
                lengths = request.headers.getlist("content-length")
                if lengths and (
                    len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit()
                ):
                    raise ValueError
                status = 413
                if lengths and int(lengths[0]) > MAX_REQUEST_BYTES:
                    raise ValueError
                raw = bytearray()
                async for part in request.stream():
                    raw.extend(part)
                    if len(raw) > MAX_REQUEST_BYTES:
                        raise ValueError
                status = 400
                parser = StorageConnectionRequest if storage_request else ReadabilityRequest
                body = parser.parse(json.loads(raw, object_pairs_hook=strict_object))
                deadline_ms = deadline_from_headers(request.headers.getlist(DEADLINE_HEADER))
                status, code = 503, "knowledge_readability_failed"
                result = await run_in_threadpool(
                    bridge.check,
                    service_token=service_token,
                    knowledge_token=knowledge_token,
                    request=body,
                    deadline_ms=deadline_ms,
                )
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
            except KnowledgeGovernanceError as exc:
                if exc.error_code == "knowledge_readability_busy":
                    status, code = 429, "knowledge_readability_busy"
            except (ValueError, UnicodeError, RecursionError, AppError):
                pass
            except Exception:
                status, code = 503, "knowledge_readability_failed"
            bridge.audit.record(
                "knowledge.storage.denied" if storage_request else "knowledge.readability.denied",
                status="denied",
                summary="知识可读性桥拒绝本次请求",
                payload={"error_code": code},
            )
        return JSONResponse(
            {"error_code": code, "message": "知识可读性检查未完成，请检查身份、授权及服务状态"},
            status_code=status,
            headers={"Cache-Control": "no-store"},
        )

    return router
