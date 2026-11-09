"""非浏览器、非模型工具的平台内部双身份入口。"""

import json
from typing import Any
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_operation_errors import CODE_OPERATION_MESSAGES

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
from app.modules.knowledge.application.principal import PRINCIPAL_REFRESH_PATH
from app.shared.code_answer_tool_contracts import CODE_HISTORY_PATH


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


class BridgeInputError(ValueError):
    def __init__(self, status: int) -> None:
        self.status = status


async def _read_json(request: Request, limit: int) -> Any:
    if request.headers.getlist("content-type") != ["application/json"]:
        raise BridgeInputError(400)
    lengths = request.headers.getlist("content-length")
    if lengths and (len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit()):
        raise BridgeInputError(400)
    if lengths and int(lengths[0]) > limit:
        raise BridgeInputError(413)
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > limit:
            raise BridgeInputError(413)
    return json.loads(raw, object_pairs_hook=strict_object)


@bounded_knowledge_request
async def check_readability(request: Request) -> JSONResponse:
    runtime = request.app.state.container
    storage_request, refresh_request, code_request = (
        request.url.path == path
        for path in (STORAGE_PATH, PRINCIPAL_REFRESH_PATH, CODE_HISTORY_PATH)
    )
    bridge = getattr(
        runtime,
        "code_history_bridge"
        if code_request
        else "knowledge_storage_broker"
        if storage_request
        else "knowledge_readability_bridge",
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
            value = await _read_json(request, 256 * 1024 if code_request else MAX_REQUEST_BYTES)
            deadline_ms = deadline_from_headers(request.headers.getlist(DEADLINE_HEADER))
            if refresh_request:
                if value != {}:
                    raise ValueError
                status, code = 503, "knowledge_principal_refresh_failed"
                result = await run_in_threadpool(
                    bridge.renew_principal,
                    service_token=service_token,
                    knowledge_token=knowledge_token,
                    deadline_ms=deadline_ms,
                )
            else:
                parser = StorageConnectionRequest if storage_request else ReadabilityRequest
                body = value if code_request else parser.parse(value)
                status, code = 503, "knowledge_readability_failed"
                result = await run_in_threadpool(
                    bridge.check,
                    service_token=service_token,
                    knowledge_token=knowledge_token,
                    request=body,
                    deadline_ms=deadline_ms,
                )
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except BridgeInputError as exc:
            status, code = exc.status, "knowledge_input_invalid"
        except CodeKnowledgeError as exc:
            if code_request and exc.code in CODE_OPERATION_MESSAGES:
                status, code = 409, exc.code
            else:
                status, code = 400, "knowledge_input_invalid"
        except KnowledgeGovernanceError as exc:
            if exc.error_code == "knowledge_readability_busy":
                status, code = 429, "knowledge_readability_busy"
        except (ValueError, UnicodeError, RecursionError, AppError):
            pass
        except Exception:
            status, code = (
                503,
                (
                    "knowledge_principal_refresh_failed"
                    if refresh_request
                    else "knowledge_readability_failed"
                ),
            )
        bridge.audit.record(
            "knowledge.principal.refresh_denied"
            if refresh_request
            else (
                "knowledge.storage.denied" if storage_request else "knowledge.readability.denied"
            ),
            status="denied",
            summary="知识可读性桥拒绝本次请求",
            payload={"error_code": code},
        )
    return JSONResponse(
        {"error_code": code, "message": "知识可读性检查未完成，请检查身份、授权及服务状态"},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


def build_knowledge_readability_router() -> APIRouter:
    router = APIRouter()
    for path in (BRIDGE_PATH, STORAGE_PATH, PRINCIPAL_REFRESH_PATH, CODE_HISTORY_PATH):
        router.add_api_route(path, check_readability, methods=["POST"])
    return router
