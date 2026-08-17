from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import uvicorn
from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from app.bootstrap import Container, build_worker_container
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.modules.mcp_audit import (
    McpAuditContext,
    McpAuditCoordinator,
    McpAuditError,
    McpAuditHandle,
)
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository
from app.shared.config import load_settings
from app.shared.exceptions import AppError, ToolPolicyError
from app.shared.secret_redaction import sanitize_for_persistence

logger = logging.getLogger(__name__)
SERVER_CODE = "tool-mcp"
SERVER_VERSION = "1.0.0"
SUPPORTED_RUNTIMES = frozenset({"python-v1"})
MAX_RESPONSE_BYTES = 512 * 1024


class ToolMcpError(RuntimeError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any]
    schema_hash: str


@dataclass(frozen=True, slots=True)
class ToolInvocationResult:
    payload: dict[str, Any]
    audit_handle: McpAuditHandle


@dataclass(frozen=True, slots=True)
class ToolRequestIdentity:
    invocation_id: str
    app_user_id: str
    project_code: str
    agent_publication_id: str
    application_publication_id: str
    correlation_id: str


class JobToolService:
    """Expose existing read-only Job tools without an MCP auth/governance layer."""

    def __init__(
        self,
        *,
        repository: AgentRepository,
        tool_registry: ToolRegistry,
        snapshot_service: JobMcpToolSnapshotService,
        audit_coordinator: McpAuditCoordinator,
    ) -> None:
        self.repository = repository
        self.tool_registry = tool_registry
        self.snapshot_service = snapshot_service
        self.audit_coordinator = audit_coordinator

    def require_job(self, job_id: str) -> AgentJob:
        try:
            job = self.repository.get_job(job_id)
        except AppError as exc:
            raise ToolMcpError("tool_mcp_job_invalid", "当前工具请求未绑定有效 Job") from exc
        if (
            job.status != JobStatus.RUNNING
            or job.agent_runtime_kind not in SUPPORTED_RUNTIMES
            or job.agent_runtime_protocol_version not in {"1.0", "1.1", "1.2", "1.3"}
        ):
            raise ToolMcpError("tool_mcp_job_invalid", "当前 Job 不允许调用工具")
        return job

    def catalog(self, job_id: str) -> tuple[ToolDescriptor, ...]:
        job = self.require_job(job_id)
        return self._mcp_descriptors(job)

    def descriptor(self, job_id: str, tool_name: str) -> tuple[AgentJob, ToolDescriptor]:
        job = self.require_job(job_id)
        definition = MCP_TOOL_MANIFEST.get(tool_name)
        if definition is None or definition.server_code != SERVER_CODE:
            raise ToolMcpError("tool_mcp_tool_denied", "当前 Job 未发布此只读工具")
        matches = [item for item in self.catalog(job_id) if item.name == tool_name]
        if len(matches) != 1:
            raise ToolMcpError("tool_mcp_tool_denied", "当前 Job 未发布此只读工具")
        return job, matches[0]

    def invoke(
        self,
        *,
        job: AgentJob,
        descriptor: ToolDescriptor,
        arguments: dict[str, Any],
        request_identity: ToolRequestIdentity,
    ) -> ToolInvocationResult:
        definition = MCP_TOOL_MANIFEST.get(descriptor.name)
        if definition is None or definition.server_code != SERVER_CODE:
            raise ToolMcpError("tool_mcp_tool_denied", "当前 Job 未发布此只读工具")
        self._validate_request_identity(job, request_identity)
        handle = self.audit_coordinator.begin(
            McpAuditContext(
                correlation_id=request_identity.correlation_id,
                job_id=job.id,
                session_id=job.session_id,
                invocation_id=request_identity.invocation_id,
                actor_user_id=job.internal_user_id or job.requester_id,
                server_code=SERVER_CODE,
                tool_identifier=descriptor.name,
                tool_schema_hash=descriptor.schema_hash,
                agent_publication_id=job.agent_publication_id,
                application_publication_id=job.business_application_publication_id,
                risk_level=_risk_level(descriptor.name),
            ),
            business_request=arguments,
        )
        started = time.monotonic()
        try:
            result = self.tool_registry.call(
                job_id=job.id,
                user_id=job.internal_user_id or job.requester_id,
                project_code=job.project_code,
                tool_name=descriptor.name,
                arguments=arguments,
                record_tool_call=False,
                persisted_tool_call_id=handle.agent_tool_call_id,
            )
            authorization = str(result.metadata.pop("_authorization_decision", "ALLOW"))
            result.metadata.pop("_persisted_tool_call_id", None)
            self.audit_coordinator.append_event(
                handle,
                event_kind="AUTHORIZATION",
                status="SUCCEEDED",
                authorization_decision=authorization,
                authorization_reason="job_binding_and_scope_allowed",
                business_request={"stage": "tool_call"},
            )
            if result.metadata.get("resource_code") or _is_resource_tool(descriptor.name):
                self.audit_coordinator.append_event(
                    handle,
                    event_kind="RESOURCE",
                    status="SUCCEEDED",
                    resource_code=str(result.metadata.get("resource_code") or ""),
                    resource_revision_id=str(result.metadata.get("resource_revision_id") or ""),
                    resource_placement=str(result.metadata.get("placement") or ""),
                    business_request=_resource_target(arguments),
                    business_response={"resolved": True},
                )
            payload = _bounded_result(
                {
                    "data": result.summary,
                    "metadata": result.metadata,
                    "truncated": result.truncated,
                    "security": {"trust": "untrusted_internal_evidence"},
                }
            )
            self.audit_coordinator.complete(
                handle,
                status="SUCCEEDED",
                business_response=payload,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return ToolInvocationResult(payload=payload, audit_handle=handle)
        except Exception as exc:
            setattr(exc, "mcp_audit_handle", handle)
            if isinstance(exc, McpAuditError):
                raise
            authorization_reached = bool(getattr(exc, "tool_authorization_reached", False))
            try:
                self.audit_coordinator.append_event(
                    handle,
                    event_kind="AUTHORIZATION",
                    status="SUCCEEDED" if authorization_reached else "DENIED",
                    error_code="" if authorization_reached else _error_code(exc),
                    authorization_decision="ALLOW" if authorization_reached else "DENY",
                    authorization_reason=(
                        "job_binding_and_scope_allowed"
                        if authorization_reached
                        else _error_code(exc)
                    ),
                    business_request={"stage": "tool_call"},
                )
                if authorization_reached and _is_resource_tool(descriptor.name):
                    self.audit_coordinator.append_event(
                        handle,
                        event_kind="RESOURCE",
                        status="FAILED",
                        error_code=_error_code(exc),
                        business_request=_resource_target(arguments),
                    )
                denied = isinstance(exc, (ToolMcpError, ToolPolicyError))
                self.audit_coordinator.complete(
                    handle,
                    status="DENIED" if denied else "FAILED",
                    error_code=_error_code(exc),
                    business_response={
                        "error": str(getattr(exc, "safe_message", "只读工具调用失败")),
                        "error_code": _error_code(exc),
                    },
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            except Exception as audit_exc:
                setattr(audit_exc, "mcp_audit_handle", handle)
                raise
            raise

    @staticmethod
    def _validate_request_identity(job: AgentJob, identity: ToolRequestIdentity) -> None:
        expected = {
            "invocation_id": f"{job.id}.attempt-{job.retry_count}",
            "app_user_id": job.internal_user_id or job.requester_id,
            "project_code": job.project_code,
            "agent_publication_id": job.agent_publication_id,
            "application_publication_id": job.business_application_publication_id,
        }
        actual = {
            "invocation_id": identity.invocation_id,
            "app_user_id": identity.app_user_id,
            "project_code": identity.project_code,
            "agent_publication_id": identity.agent_publication_id,
            "application_publication_id": identity.application_publication_id,
        }
        if actual != expected:
            raise ToolMcpError(
                "tool_mcp_provenance_mismatch",
                "MCP 请求与当前 Job 执行上下文不一致",
            )

    def _mcp_descriptors(self, job: AgentJob) -> tuple[ToolDescriptor, ...]:
        values: list[ToolDescriptor] = []
        for tool_name in self.tool_registry.available_tools():
            definition = MCP_TOOL_MANIFEST[tool_name]
            if definition.server_code != SERVER_CODE:
                continue
            if not self.tool_registry.tool_service.is_tool_visible_for_job(
                job_id=job.id,
                tool_name=tool_name,
            ):
                continue
            exact = self.snapshot_service.tool_binding(
                job_id=job.id,
                tool_identifier=tool_name,
            )
            bindings = exact[1] if exact is not None else []
            if not bindings or any(
                str(binding.get("schema_hash") or binding.get("public_schema_hash") or "")
                != definition.schema_hash
                for binding in bindings
            ):
                raise ToolMcpError("tool_mcp_schema_mismatch", "只读工具 Schema 不一致")
            values.append(
                ToolDescriptor(
                    name=tool_name,
                    description=definition.description,
                    input_schema=dict(definition.input_schema),
                    schema_hash=definition.schema_hash,
                )
            )
        return tuple(values)


class CredentialRejectingMiddleware:
    """The MCP transport is private and deliberately has no credential protocol."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers") or []
        }
        if scope.get("type") == "http" and headers.get("authorization"):
            response = JSONResponse(
                {"error": "tool_mcp_credentials_forbidden"},
                status_code=400,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class _StreamableHttpApp:
    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self.manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.manager.handle_request(scope, receive, send)


def create_tool_server(service: JobToolService) -> Server:
    async def list_tools(
        context: ServerRequestContext,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        request = _request(context)
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=item.name,
                    description=item.description,
                    input_schema=item.input_schema,
                    annotations=types.ToolAnnotations(
                        read_only_hint=True,
                        destructive_hint=False,
                        idempotent_hint=False,
                        open_world_hint=False,
                    ),
                )
                for item in service.catalog(_job_id(request))
            ]
        )

    async def call_tool(
        context: ServerRequestContext,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        request = _request(context)
        try:
            job, descriptor = service.descriptor(_job_id(request), params.name)
            result = await asyncio.to_thread(
                service.invoke,
                job=job,
                descriptor=descriptor,
                arguments=params.arguments or {},
                request_identity=_request_identity(request),
            )
            return _tool_result(
                result.payload,
                is_error=False,
                meta=result.audit_handle.result_meta(),
            )
        except (ToolMcpError, AppError) as exc:
            return _tool_result(
                {
                    "error": str(getattr(exc, "safe_message", "只读工具调用被拒绝")),
                    "error_code": str(
                        getattr(exc, "code", getattr(exc, "error_code", "tool_mcp_denied"))
                    ),
                },
                is_error=True,
                meta=_error_meta(exc),
            )
        except Exception as exc:
            logger.exception("Tool MCP call failed safely tool_name=%s", params.name)
            return _tool_result(
                {"error": "只读工具暂时不可用", "error_code": "tool_mcp_unavailable"},
                is_error=True,
                meta=_error_meta(exc),
            )

    return Server(
        "Enterprise Tool MCP",
        version=SERVER_VERSION,
        instructions="Job-frozen tool-mcp read-only tools only.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


def create_app(
    service: JobToolService,
    *,
    allowed_hosts: tuple[str, ...] = ("tool-mcp", "tool-mcp:9103", "127.0.0.1:9103"),
) -> CredentialRejectingMiddleware:
    server = create_tool_server(service)
    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(allowed_hosts),
            allowed_origins=[],
        ),
    )

    async def health(_: Request) -> JSONResponse:
        try:
            service.repository.database.execute_one("select 1 as ready")
            service.audit_coordinator.assert_ready()
            return JSONResponse({"status": "ok", "server_code": SERVER_CODE, "database": "ready"})
        except Exception:
            return JSONResponse(
                {"status": "degraded", "server_code": SERVER_CODE, "database": "unavailable"},
                status_code=503,
            )

    @asynccontextmanager
    async def lifespan(_: Starlette) -> Any:
        async with manager.run():
            yield

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/mcp", endpoint=_StreamableHttpApp(manager)),
        ],
        lifespan=lifespan,
    )
    return CredentialRejectingMiddleware(app)


def create_default_app() -> CredentialRejectingMiddleware:
    settings = load_settings()
    runtime = build_worker_container(
        settings,
        seed=settings.seed_local_config,
        service_name=SERVER_CODE,
    )
    return create_app(_service_from_container(runtime))


def _service_from_container(runtime: Container) -> JobToolService:
    return JobToolService(
        repository=runtime.agent_repository,
        tool_registry=ToolRegistry(runtime.tool_service),
        snapshot_service=runtime.mcp_tool_snapshot_service,
        audit_coordinator=McpAuditCoordinator(
            runtime.database,
            max_payload_bytes=MAX_RESPONSE_BYTES,
            audit_service=runtime.audit_service,
        ),
    )


def _request(context: ServerRequestContext) -> Request:
    request = context.request
    if not isinstance(request, Request):
        raise ToolMcpError("tool_mcp_transport_invalid", "MCP 传输上下文无效")
    return request


def _job_id(request: Request) -> str:
    job_id = str(request.headers.get("x-job-id") or "")
    if not job_id:
        raise ToolMcpError("tool_mcp_job_missing", "MCP 请求缺少 Job 上下文")
    return job_id


def _request_identity(request: Request) -> ToolRequestIdentity:
    values = {
        "invocation_id": str(request.headers.get("x-invocation-id") or ""),
        "app_user_id": str(request.headers.get("x-app-user-id") or ""),
        "project_code": str(request.headers.get("x-project-code") or ""),
        "agent_publication_id": str(request.headers.get("x-agent-publication-id") or ""),
        "application_publication_id": str(
            request.headers.get("x-application-publication-id") or ""
        ),
        "correlation_id": str(request.headers.get("x-correlation-id") or "")[:128],
    }
    if any(not value for value in values.values()):
        raise ToolMcpError("tool_mcp_context_missing", "MCP 请求缺少完整执行上下文")
    return ToolRequestIdentity(**values)


def _tool_result(
    payload: dict[str, Any],
    *,
    is_error: bool,
    meta: dict[str, str],
) -> types.CallToolResult:
    safe = sanitize_for_persistence(payload)
    encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=encoded)],
        structured_content=safe,
        is_error=is_error,
        _meta=meta or None,
    )


def _error_meta(exc: Exception) -> dict[str, str]:
    handle = getattr(exc, "mcp_audit_handle", None)
    return handle.result_meta() if isinstance(handle, McpAuditHandle) else {}


def _error_code(exc: Exception) -> str:
    return str(
        getattr(exc, "error_code", getattr(exc, "code", "tool_mcp_failed")) or "tool_mcp_failed"
    )[:128]


def _is_resource_tool(tool_name: str) -> bool:
    return tool_name in {
        "get_schema_directory",
        "query_database",
        "query_redis_get",
        "query_redis_scan",
        "query_loki",
        "diagnose_loki_labels",
        "diagnose_loki_label_values",
        "diagnose_loki_probe",
    }


def _resource_target(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        key: arguments[key]
        for key in ("environment", "base", "workshop", "placement", "datasource")
        if key in arguments
    }


def _risk_level(tool_name: str) -> str:
    return (
        "medium" if tool_name.startswith("query_redis") or tool_name == "query_database" else "low"
    )


def _encoded(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")


def _bounded_result(value: dict[str, Any]) -> dict[str, Any]:
    safe = sanitize_for_persistence(value)
    if not isinstance(safe, dict):
        raise TypeError("Sanitized MCP tool result must remain an object")
    if len(_encoded(safe)) > MAX_RESPONSE_BYTES:
        raise ToolMcpError("tool_mcp_response_too_large", "只读工具响应超过大小限制")
    return safe


def main() -> None:
    uvicorn.run(
        create_default_app(),
        host=os.environ.get("TOOL_MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("TOOL_MCP_PORT", "9103")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
