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
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from app.bootstrap import Container, build_worker_container
from app.modules.agent.infrastructure.tool_manifest import TOOL_DEFINITIONS
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.api_capability.application import GovernedApiRuntimeExecutor
from app.modules.internal_tools.domain import HandlerRegistryError
from app.modules.job.application.builtin_tool_snapshot import JobBuiltinToolSnapshotService
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.domain.execution_policy import JobExecutionPolicySnapshot
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import AgentRepository
from app.shared.config import load_settings
from app.shared.exceptions import AppError
from app.shared.secret_redaction import sanitize_for_persistence

logger = logging.getLogger(__name__)
SERVER_CODE = "tool-mcp"
SERVER_VERSION = "1.0.0"
SUPPORTED_RUNTIMES = frozenset({"python-v1", "typescript-v1"})
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
    kind: str
    capability_release_id: str = ""


class JobToolService:
    """Expose existing read-only Job tools without an MCP auth/governance layer."""

    def __init__(
        self,
        *,
        repository: AgentRepository,
        tool_registry: ToolRegistry,
        snapshot_service: JobBuiltinToolSnapshotService,
        governed_executor: GovernedApiRuntimeExecutor | None,
    ) -> None:
        self.repository = repository
        self.tool_registry = tool_registry
        self.snapshot_service = snapshot_service
        self.governed_executor = governed_executor

    def require_job(self, job_id: str) -> AgentJob:
        try:
            job = self.repository.get_job(job_id)
        except AppError as exc:
            raise ToolMcpError("tool_mcp_job_invalid", "当前工具请求未绑定有效 Job") from exc
        if (
            job.status != JobStatus.RUNNING
            or job.agent_runtime_kind not in SUPPORTED_RUNTIMES
            or job.agent_runtime_protocol_version != "1.0"
        ):
            raise ToolMcpError("tool_mcp_job_invalid", "当前 Job 不允许调用工具")
        return job

    def catalog(self, job_id: str) -> tuple[ToolDescriptor, ...]:
        job = self.require_job(job_id)
        return (*self._builtin_descriptors(job), *self._capability_descriptors(job))

    def descriptor(self, job_id: str, tool_name: str) -> tuple[AgentJob, ToolDescriptor]:
        job = self.require_job(job_id)
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
        correlation_id: str,
    ) -> dict[str, Any]:
        if descriptor.kind == "builtin":
            result = self.tool_registry.call(
                job_id=job.id,
                user_id=job.internal_user_id or job.user_id,
                project_code=job.project_code,
                tool_name=descriptor.name,
                arguments=arguments,
                record_tool_call=True,
            )
            return _bounded_result(
                {
                    "data": result.summary,
                    "security": {"trust": "untrusted_internal_evidence"},
                }
            )
        executor = self.governed_executor
        if descriptor.kind != "capability" or executor is None:
            raise ToolMcpError("tool_mcp_handler_unavailable", "只读工具执行器不可用")
        started = time.monotonic()
        tool_call_id = self.repository.add_tool_call(
            job_id=job.id,
            tool_name=descriptor.name,
            request_payload=_bounded_summary(arguments),
            response_summary={"status": "STARTED"},
            status="STARTED",
            duration_ms=0,
            risk_level="low",
        )
        try:
            policy = JobExecutionPolicySnapshot.from_dict(job.execution_policy)
            result = executor.execute(
                job_id=job.id,
                tool_call_id=tool_call_id,
                user_id=job.internal_user_id or job.user_id,
                application_publication_id=job.business_application_publication_id,
                agent_publication_id=job.agent_publication_id,
                capability_release_id=descriptor.capability_release_id,
                identifier=descriptor.name,
                agent_input=arguments,
                correlation_id=correlation_id,
                timeout_seconds=float(policy.effective.timeout_seconds),
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            summary = {
                "capability_release_id": descriptor.capability_release_id,
                "data_classification": "INTERNAL",
                "normalized_result_size": len(_encoded(result)),
            }
            self.repository.complete_tool_call(
                tool_call_id,
                response_summary=summary,
                status="SUCCEEDED",
                duration_ms=duration_ms,
            )
            return _bounded_result(
                {
                    "data": result,
                    "security": {
                        "trust": "untrusted_external_business_data",
                        "data_classification": "INTERNAL",
                    },
                }
            )
        except Exception as exc:
            safe_message = str(getattr(exc, "safe_message", "只读工具执行失败"))
            self.repository.complete_tool_call(
                tool_call_id,
                response_summary={"error": safe_message},
                status="FAILED",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            raise ToolMcpError(
                str(getattr(exc, "error_code", "tool_mcp_execution_failed")),
                safe_message,
            ) from exc

    def _builtin_descriptors(self, job: AgentJob) -> tuple[ToolDescriptor, ...]:
        values: list[ToolDescriptor] = []
        for tool_name in self.tool_registry.available_tools():
            if not self.tool_registry.tool_service.is_tool_visible_for_job(
                job_id=job.id,
                tool_name=tool_name,
            ):
                continue
            try:
                definition = self.tool_registry.handler_registry.require(tool_name, "1.0.0")
            except HandlerRegistryError as exc:
                raise ToolMcpError(
                    "tool_mcp_handler_unavailable",
                    "只读工具 Handler 不可用",
                ) from exc
            exact = self.snapshot_service.tool_binding(
                job_id=job.id,
                tool_identifier=tool_name,
            )
            bindings = exact[1] if exact is not None else []
            if not bindings or any(
                str(binding.get("public_schema_hash") or "")
                != definition.public_schema_hash
                for binding in bindings
            ):
                raise ToolMcpError("tool_mcp_schema_mismatch", "只读工具 Schema 不一致")
            values.append(
                ToolDescriptor(
                    name=tool_name,
                    description=str(TOOL_DEFINITIONS[tool_name]["description"]),
                    input_schema=dict(definition.input_schema),
                    kind="builtin",
                )
            )
        return tuple(values)

    def _capability_descriptors(self, job: AgentJob) -> tuple[ToolDescriptor, ...]:
        executor = self.governed_executor
        if (
            executor is None
            or not job.agent_publication_id
            or not job.business_application_publication_id
        ):
            return ()
        rows = executor.execution_repository.database.execute(
            """
            select a.identifier, a.capability_release_id
              from agent_publication_api_capability a
              join business_application_publication_api_capability p
                on p.agent_publication_id = a.agent_publication_id
               and p.capability_release_id = a.capability_release_id
               and p.identifier = a.identifier
              join api_capability_release r on r.id = a.capability_release_id
             where a.agent_publication_id = ?
               and p.application_publication_id = ?
               and r.status in ('ACTIVE', 'DEPRECATED')
             order by a.binding_order
            """,
            (job.agent_publication_id, job.business_application_publication_id),
        )
        values: list[ToolDescriptor] = []
        for row in rows:
            release = executor.resolver.capability_repository.get_release(
                str(row["capability_release_id"])
            )
            schema = release.get("input_schema")
            if (
                str(release.get("operation_semantics") or "") != "QUERY"
                or str(release.get("data_classification") or "") != "INTERNAL"
                or not isinstance(schema, dict)
            ):
                continue
            values.append(
                ToolDescriptor(
                    name=str(row["identifier"]),
                    description=str(release["description"]),
                    input_schema=dict(schema),
                    kind="capability",
                    capability_release_id=str(row["capability_release_id"]),
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
    server = Server(
        "Enterprise Tool MCP",
        version=SERVER_VERSION,
        instructions="Job-frozen read-only tools only.",
    )

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        request = _request(server)
        return [
            types.Tool(
                name=item.name,
                description=item.description,
                inputSchema=item.input_schema,
                annotations=types.ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
            )
            for item in service.catalog(_job_id(request))
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        request = _request(server)
        try:
            job, descriptor = service.descriptor(_job_id(request), name)
            result = await asyncio.to_thread(
                service.invoke,
                job=job,
                descriptor=descriptor,
                arguments=arguments,
                correlation_id=str(request.headers.get("x-correlation-id") or "")[:128],
            )
            return _tool_result(result, is_error=False)
        except (ToolMcpError, AppError) as exc:
            return _tool_result(
                {
                    "error": str(getattr(exc, "safe_message", "只读工具调用被拒绝")),
                    "error_code": str(
                        getattr(exc, "code", getattr(exc, "error_code", "tool_mcp_denied"))
                    ),
                },
                is_error=True,
            )
        except Exception:
            logger.exception("Tool MCP call failed safely tool_name=%s", name)
            return _tool_result(
                {"error": "只读工具暂时不可用", "error_code": "tool_mcp_unavailable"},
                is_error=True,
            )

    return server


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
            return JSONResponse(
                {"status": "ok", "server_code": SERVER_CODE, "database": "ready"}
            )
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
        snapshot_service=runtime.builtin_tool_snapshot_service,
        governed_executor=runtime.governed_api_runtime_executor,
    )


def _request(server: Server) -> Request:
    request = server.request_context.request
    if not isinstance(request, Request):
        raise ToolMcpError("tool_mcp_transport_invalid", "MCP 传输上下文无效")
    return request


def _job_id(request: Request) -> str:
    job_id = str(request.headers.get("x-job-id") or "")
    if not job_id:
        raise ToolMcpError("tool_mcp_job_missing", "MCP 请求缺少 Job 上下文")
    return job_id


def _tool_result(payload: dict[str, Any], *, is_error: bool) -> types.CallToolResult:
    safe = sanitize_for_persistence(payload)
    encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=encoded)],
        structuredContent=safe,
        isError=is_error,
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
    if len(_encoded(safe)) > MAX_RESPONSE_BYTES:
        raise ToolMcpError("tool_mcp_response_too_large", "只读工具响应超过大小限制")
    return safe


def _bounded_summary(value: Any, *, max_chars: int = 4000) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    return {"payload": encoded[:max_chars], "truncated": len(encoded) > max_chars}


def main() -> None:
    uvicorn.run(
        create_default_app(),
        host=os.environ.get("TOOL_MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("TOOL_MCP_PORT", "9103")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
