from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request as FastAPIRequest

from ..application.platform_service import PlatformService
from ..domain.errors import (
    AuthorizationError,
    PlatformError,
    PolicyViolation,
    ResolutionError,
)
from ..domain.results import ToolResponse
from ..domain.topology import ResourceKind


def _user_id(request: FastAPIRequest) -> str:
    return request.headers.get("x-agent-user-id", "").strip()


def _job_id(request: FastAPIRequest) -> str:
    return request.headers.get("x-agent-job-id", "").strip()


def _project_code(request: FastAPIRequest) -> str:
    return request.headers.get("x-agent-project-code", "").strip()


def _application_id(request: FastAPIRequest) -> str:
    return request.headers.get("x-agent-application-id", "").strip()


def _tool_call_id(request: FastAPIRequest) -> str:
    return request.headers.get("x-agent-tool-call-id", "").strip()


def _correlation_id(request: FastAPIRequest) -> str:
    return request.headers.get("x-correlation-id", "").strip()


def _require(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PolicyViolation(f"Field '{key}' is required")
    return value.strip()


def _optional(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PolicyViolation(f"Field '{key}' must be a non-empty string when provided")
    return value.strip()


def _target(
    request: FastAPIRequest,
    payload: dict[str, Any],
) -> tuple[str, str, str | None]:
    _assert_no_authoritative_fact_overrides(payload)
    environment = _require(payload, "environment")
    base = _require(payload, "base")
    workshop = _optional(payload, "workshop")
    expected = {
        "x-agent-environment": environment,
        "x-agent-base": base,
        "x-agent-workshop": workshop or "",
    }
    for header, expected_value in expected.items():
        supplied = request.headers.get(header, "").strip()
        if supplied and supplied != expected_value:
            raise AuthorizationError("Agent Job authorization context is invalid")
    return environment, base, workshop


_AUTHORITATIVE_FACT_FIELDS = frozenset(
    {
        "tool_release_id",
        "handler_version",
        "implementation_digest",
        "public_schema_hash",
        "resource_revision_id",
        "workshop_partition_policy_revision_id",
        "loki_scope_policy_revision_id",
        "database_table_prefix",
        "table_prefix",
        "redis_prefix",
        "redis_prefixes",
        "tenant",
        "tenant_id",
        "mandatory_selector",
        "effective_selector",
    }
)


def _assert_no_authoritative_fact_overrides(
    payload: dict[str, Any],
) -> None:
    if _AUTHORITATIVE_FACT_FIELDS.intersection(payload):
        raise AuthorizationError(
            "Agent request cannot override frozen Job facts"
        )


def _placement(payload: dict[str, Any]) -> str:
    value = payload.get("placement")
    if value is None:
        return ""
    if not isinstance(value, str) or value.strip().lower() not in {
        "cloud",
        "edge",
    }:
        raise PolicyViolation("Placement must be cloud or edge")
    return value.strip().lower()


def _envelope(request: FastAPIRequest, started: float, result: ToolResponse) -> dict[str, Any]:
    result.metadata.setdefault("request_id", request.headers.get("x-correlation-id", "-"))
    result.metadata["duration_ms"] = int((time.monotonic() - started) * 1000)
    return {
        "summary": result.summary,
        "raw": result.raw,
        "truncated": result.truncated,
        "metadata": result.metadata,
    }


def register_routes(app: FastAPI, *, service: PlatformService) -> None:
    @app.get("/health")
    async def health() -> dict[str, Any]:
        config = service.config_status()
        return {
            "status": "ok" if config["valid"] else "degraded",
            "mode": "internal-api-platform",
            "config": config,
        }

    @app.post("/tools/context/er")
    async def er_context(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            _assert_no_authoritative_fact_overrides(payload)
            result = service.er_context(
                user_id=_user_id(request),
                job_id=_job_id(request),
                project_code=_project_code(request),
                application_id=_application_id(request),
                query=str(payload.get("query", "")),
                tool_call_id=_tool_call_id(request),
                correlation_id=_correlation_id(request),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/context/business-flow")
    async def business_flow_context(
        request: FastAPIRequest, payload: dict[str, Any]
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            _assert_no_authoritative_fact_overrides(payload)
            result = service.business_flow_context(
                user_id=_user_id(request),
                job_id=_job_id(request),
                project_code=_project_code(request),
                application_id=_application_id(request),
                query=str(payload.get("query", "")),
                tool_call_id=_tool_call_id(request),
                correlation_id=_correlation_id(request),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/resolve")
    async def resolve(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            environment, base, workshop = _target(request, payload)
            result = service.describe_target(
                user_id=_user_id(request),
                job_id=_job_id(request),
                project_code=_project_code(request),
                application_id=_application_id(request),
                environment=environment,
                base=base,
                workshop=workshop,
                kind=_resource_kind(payload.get("kind", "database")),
                placement=_placement(payload),
                tool_call_id=_tool_call_id(request),
                correlation_id=_correlation_id(request),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/database/query")
    async def database_query(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            environment, base, workshop = _target(request, payload)
            result = service.query_database(
                user_id=_user_id(request),
                job_id=_job_id(request),
                project_code=_project_code(request),
                application_id=_application_id(request),
                environment=environment,
                base=base,
                workshop=workshop,
                sql=_require(payload, "sql"),
                limit=_int_or_none(payload.get("limit")),
                placement=_placement(payload),
                tool_call_id=_tool_call_id(request),
                correlation_id=_correlation_id(request),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/schema/directory")
    async def schema_directory(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            environment, base, workshop = _target(request, payload)
            result = service.schema_directory(
                user_id=_user_id(request),
                job_id=_job_id(request),
                project_code=_project_code(request),
                application_id=_application_id(request),
                environment=environment,
                base=base,
                workshop=workshop,
                query=str(payload.get("query", "")),
                limit=_int_or_none(payload.get("limit")),
                placement=_placement(payload),
                tool_call_id=_tool_call_id(request),
                correlation_id=_correlation_id(request),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/redis/get")
    async def redis_get(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            environment, base, workshop = _target(request, payload)
            result = service.redis_get(
                user_id=_user_id(request),
                job_id=_job_id(request),
                project_code=_project_code(request),
                application_id=_application_id(request),
                environment=environment,
                base=base,
                workshop=workshop,
                key=_require(payload, "key"),
                placement=_placement(payload),
                tool_call_id=_tool_call_id(request),
                correlation_id=_correlation_id(request),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/redis/scan")
    async def redis_scan(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            environment, base, workshop = _target(request, payload)
            result = service.redis_scan(
                user_id=_user_id(request),
                job_id=_job_id(request),
                project_code=_project_code(request),
                application_id=_application_id(request),
                environment=environment,
                base=base,
                workshop=workshop,
                pattern=_require(payload, "pattern"),
                limit=_int_or_none(payload.get("limit")),
                placement=_placement(payload),
                tool_call_id=_tool_call_id(request),
                correlation_id=_correlation_id(request),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/loki/query")
    async def loki_query(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            environment, base, workshop = _target(request, payload)
            result = service.query_loki(
                user_id=_user_id(request),
                job_id=_job_id(request),
                project_code=_project_code(request),
                application_id=_application_id(request),
                environment=environment,
                base=base,
                workshop=workshop,
                selector=_selector(payload),
                query=str(payload.get("query", "")),
                minutes=_int_or_none(payload.get("minutes")) or 15,
                limit=_int_or_none(payload.get("limit")) or 100,
                tool_call_id=_tool_call_id(request),
                correlation_id=_correlation_id(request),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/loki/labels")
    async def loki_labels(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            environment, base, workshop = _target(request, payload)
            result = service.loki_labels(
                user_id=_user_id(request),
                job_id=_job_id(request),
                project_code=_project_code(request),
                application_id=_application_id(request),
                environment=environment,
                base=base,
                workshop=workshop,
                minutes=_int_or_none(payload.get("minutes")) or 15,
                limit=_int_or_none(payload.get("limit")) or 100,
                tool_call_id=_tool_call_id(request),
                correlation_id=_correlation_id(request),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/loki/label-values")
    async def loki_label_values(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            environment, base, workshop = _target(request, payload)
            result = service.loki_label_values(
                user_id=_user_id(request),
                job_id=_job_id(request),
                project_code=_project_code(request),
                application_id=_application_id(request),
                environment=environment,
                base=base,
                workshop=workshop,
                label=_require(payload, "label"),
                minutes=_int_or_none(payload.get("minutes")) or 15,
                limit=_int_or_none(payload.get("limit")) or 100,
                tool_call_id=_tool_call_id(request),
                correlation_id=_correlation_id(request),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)

    @app.post("/tools/loki/probe")
    async def loki_probe(request: FastAPIRequest, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            environment, base, workshop = _target(request, payload)
            result = service.loki_probe(
                user_id=_user_id(request),
                job_id=_job_id(request),
                project_code=_project_code(request),
                application_id=_application_id(request),
                environment=environment,
                base=base,
                workshop=workshop,
                selector=_selector(payload),
                query=str(payload.get("query", "")),
                minutes=_int_or_none(payload.get("minutes")) or 15,
                limit=_int_or_none(payload.get("limit")) or 100,
                tool_call_id=_tool_call_id(request),
                correlation_id=_correlation_id(request),
            )
        except PlatformError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.body) from exc
        return _envelope(request, started, result)


def _resource_kind(value: Any) -> ResourceKind:
    try:
        return ResourceKind(str(value))
    except ValueError as exc:
        raise ResolutionError(f"Unknown resource kind: {value}") from exc


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PolicyViolation("Numeric field must be an integer") from exc


def _selector(payload: dict[str, Any]) -> dict[str, str]:
    selector = payload.get("selector")
    if not isinstance(selector, dict):
        return {}
    return {str(k): str(v) for k, v in selector.items()}
