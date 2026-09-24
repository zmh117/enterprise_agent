from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Scope

from app.shared.exceptions import AppError
from services.file_service.auth import FilePrincipalError


MAX_TOOL_RESPONSE_BYTES = 256 * 1024


def header_values(scope: Scope) -> dict[str, list[str]]:
    headers: dict[str, list[str]] = {}
    for key, value in scope.get("headers") or []:
        headers.setdefault(key.decode("latin-1").lower(), []).append(value.decode("latin-1"))
    return headers


def bearer_from_headers(headers: dict[str, list[str]]) -> str | None:
    values = headers.get("authorization") or []
    if len(values) != 1 or not values[0].startswith("Bearer "):
        return None
    token = values[0].removeprefix("Bearer ").strip()
    if not token or len(token.encode()) > 8192 or "\r" in token or "\n" in token:
        return None
    return token


def bearer_token(request: Request) -> str:
    token = bearer_from_headers({"authorization": request.headers.getlist("authorization")})
    if token is None:
        raise FilePrincipalError(
            "File Service bearer token is missing",
            safe_message="平台文件身份凭证缺失",
            error_code="file_principal_token_missing",
        )
    return token


def safe_result(value: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    if len(encoded) > MAX_TOOL_RESPONSE_BYTES:
        raise ValueError("File Service response exceeds its safe bound")
    forbidden = ("object_key", "bucket", "access_key", "secret_key", "presigned_url")
    if any(key in value for key in forbidden):
        raise ValueError("File Service response contains infrastructure fields")
    return value


async def request_json_exact(
    request: Request,
    required_fields: set[str],
) -> dict[str, Any]:
    content_type = str(request.headers.get("content-type") or "").split(";", 1)[0]
    if content_type != "application/json":
        raise FilePrincipalError(
            "Document processing request media type is invalid",
            safe_message="文档处理请求媒体类型无效",
            error_code="document_processing_request_media_type_invalid",
        )
    raw = await request.body()
    if not raw or len(raw) > 16 * 1024:
        raise FilePrincipalError(
            "Document processing request size is invalid",
            safe_message="文档处理请求大小无效",
            error_code="document_processing_request_size_invalid",
        )
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FilePrincipalError(
            "Document processing request JSON is invalid",
            safe_message="文档处理请求无效",
            error_code="document_processing_request_json_invalid",
        ) from exc
    if not isinstance(value, dict) or set(value) != required_fields:
        raise FilePrincipalError(
            "Document processing request schema is invalid",
            safe_message="文档处理请求结构无效",
            error_code="document_processing_request_schema_invalid",
        )
    return value


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise FilePrincipalError(
            "Document processing metric is invalid",
            safe_message="文档处理指标无效",
            error_code="document_processing_metric_invalid",
        )
    return value


def safe_processing_run(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": str(value["id"]),
        "status": str(value["status"]),
        "attempt": int(value["attempt"]),
        "error_code": str(value["error_code"] or ""),
        "external_task_id": str(value["external_task_id"] or ""),
    }


def safe_error(exc: AppError) -> JSONResponse:
    return JSONResponse(
        {"error": exc.safe_message, "error_code": exc.error_code or "file_service_denied"},
        status_code=403,
    )
