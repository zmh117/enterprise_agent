from __future__ import annotations

import asyncio
import hashlib
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
from app.modules.agent.application.runtime_migration_gate import TYPESCRIPT_RUNTIME
from app.modules.agent.infrastructure.claude_code_agent_client import TOOL_DEFINITIONS
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.agent.infrastructure.runtime_tool_token import (
    RuntimeToolTokenError,
    RuntimeToolTokenVerifier,
)
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
SERVER_CODE = "runtime-tool-mcp"
SERVER_VERSION = "0.1.0"
_MAX_RESPONSE_BYTES = 512 * 1024


class RuntimeToolAuthorizationError(RuntimeError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True, slots=True)
class RuntimeToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any]
    schema_hash: str
    required_scope: str
    kind: str
    capability_release_id: str = ""
    resource_revision_ids: tuple[str, ...] = ()


class RuntimeToolAuthorizer:
    """Revalidate signed Worker claims against immutable Job governance facts."""

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

    def authorize_request(self, claims: dict[str, Any]) -> AgentJob:
        job_id = str(claims.get("job_id") or "")
        try:
            job = self.repository.get_job(job_id)
        except AppError as exc:
            raise RuntimeToolAuthorizationError(
                "runtime_tool_job_invalid",
                "当前 Runtime Tool 请求未绑定有效 Job",
            ) from exc
        expected_user = job.internal_user_id or job.user_id
        checks = (
            (job.status == JobStatus.RUNNING, "runtime_tool_job_not_running"),
            (job.agent_runtime_kind == TYPESCRIPT_RUNTIME, "runtime_tool_runtime_mismatch"),
            (job.agent_runtime_protocol_version == "1.0", "runtime_tool_protocol_mismatch"),
            (str(claims.get("sub") or "") == expected_user, "runtime_tool_subject_mismatch"),
            (
                str(claims.get("application_publication_id") or "")
                == job.business_application_publication_id,
                "runtime_tool_application_mismatch",
            ),
            (
                str(claims.get("project_code") or "") == job.project_code,
                "runtime_tool_project_mismatch",
            ),
        )
        failed = next((code for allowed, code in checks if not allowed), "")
        if failed:
            raise RuntimeToolAuthorizationError(
                failed,
                "Runtime Tool 请求与冻结 Job 事实不一致",
            )
        return job

    def catalog(self, claims: dict[str, Any]) -> tuple[RuntimeToolDescriptor, ...]:
        job = self.authorize_request(claims)
        available = {
            descriptor.name: descriptor
            for descriptor in (
                *self._builtin_descriptors(job),
                *self._governed_descriptors(job),
            )
        }
        requested = claims.get("tool_bindings") or []
        if not isinstance(requested, list):
            raise RuntimeToolAuthorizationError(
                "runtime_tool_binding_invalid",
                "Runtime Tool 绑定无效",
            )
        selected: list[RuntimeToolDescriptor] = []
        for binding in requested:
            if not isinstance(binding, dict):
                raise RuntimeToolAuthorizationError(
                    "runtime_tool_binding_invalid",
                    "Runtime Tool 绑定无效",
                )
            name = str(binding.get("tool_name") or "")
            descriptor = available.get(name)
            if (
                descriptor is None
                or str(binding.get("required_scope") or "") != descriptor.required_scope
                or str(binding.get("tool_schema_hash") or "") != descriptor.schema_hash
            ):
                raise RuntimeToolAuthorizationError(
                    "runtime_tool_binding_denied",
                    "Runtime Tool 绑定与冻结发布事实不一致",
                )
            revision_id = str(binding.get("resource_revision_id") or "")
            if revision_id and revision_id not in descriptor.resource_revision_ids:
                raise RuntimeToolAuthorizationError(
                    "runtime_tool_resource_binding_denied",
                    "Runtime Tool 资源绑定与冻结 Job 不一致",
                )
            selected.append(descriptor)
        return tuple(selected)

    def descriptor(
        self,
        claims: dict[str, Any],
        tool_name: str,
    ) -> tuple[AgentJob, RuntimeToolDescriptor]:
        job = self.authorize_request(claims)
        matches = [item for item in self.catalog(claims) if item.name == tool_name]
        if len(matches) != 1:
            raise RuntimeToolAuthorizationError(
                "runtime_tool_not_authorized",
                "当前 Job 未授权此 Runtime Tool",
            )
        return job, matches[0]

    def invoke(
        self,
        *,
        claims: dict[str, Any],
        descriptor: RuntimeToolDescriptor,
        arguments: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        job = self.authorize_request(claims)
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
                    "security": {
                        "trust": "untrusted_internal_evidence",
                        "job_bound": True,
                    },
                }
            )
        if descriptor.kind != "capability" or self.governed_executor is None:
            raise RuntimeToolAuthorizationError(
                "runtime_tool_handler_unavailable",
                "Runtime Tool 执行器不可用",
            )
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
            result = self.governed_executor.execute(
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
                        "capability_release_id": descriptor.capability_release_id,
                    },
                }
            )
        except Exception as exc:
            safe_message = str(getattr(exc, "safe_message", "Runtime Tool 执行失败"))
            self.repository.complete_tool_call(
                tool_call_id,
                response_summary={
                    "error": safe_message,
                    "capability_release_id": descriptor.capability_release_id,
                },
                status="FAILED",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            raise RuntimeToolAuthorizationError(
                str(getattr(exc, "error_code", "runtime_tool_execution_failed")),
                safe_message,
            ) from exc

    def _builtin_descriptors(self, job: AgentJob) -> tuple[RuntimeToolDescriptor, ...]:
        values: list[RuntimeToolDescriptor] = []
        for tool_name in self.tool_registry.available_tools():
            if not self.tool_registry.tool_service.is_tool_visible_for_job(
                job_id=job.id,
                tool_name=tool_name,
            ):
                continue
            try:
                definition = self.tool_registry.handler_registry.require(tool_name, "1.0.0")
            except HandlerRegistryError as exc:
                raise RuntimeToolAuthorizationError(
                    "runtime_tool_handler_unavailable",
                    "Runtime Tool Handler 不可用",
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
                raise RuntimeToolAuthorizationError(
                    "runtime_tool_schema_mismatch",
                    "Runtime Tool Schema 与冻结 Job 不一致",
                )
            revision_ids = {
                str(candidate.get("resource_revision_id") or "")
                for binding in bindings
                for candidate in binding.get("candidates") or []
            } - {""}
            values.append(
                RuntimeToolDescriptor(
                    name=tool_name,
                    description=str(TOOL_DEFINITIONS[tool_name]["description"]),
                    input_schema=dict(definition.input_schema),
                    schema_hash=definition.public_schema_hash,
                    required_scope=f"tool:{tool_name}",
                    kind="builtin",
                    resource_revision_ids=tuple(sorted(revision_ids)),
                )
            )
        return tuple(values)

    def _governed_descriptors(self, job: AgentJob) -> tuple[RuntimeToolDescriptor, ...]:
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
              join api_capability_release r
                on r.id = a.capability_release_id
             where a.agent_publication_id = ?
               and p.application_publication_id = ?
               and r.status in ('ACTIVE', 'DEPRECATED')
             order by a.binding_order
            """,
            (job.agent_publication_id, job.business_application_publication_id),
        )
        values: list[RuntimeToolDescriptor] = []
        for row in rows:
            release = executor.resolver.capability_repository.get_release(
                str(row["capability_release_id"])
            )
            if (
                str(release.get("operation_semantics") or "") != "QUERY"
                or str(release.get("data_classification") or "") != "INTERNAL"
            ):
                continue
            try:
                executor.assert_subject_available(
                    job_id=job.id,
                    user_id=job.internal_user_id or job.user_id,
                    connection_revision_id=str(release["connection_revision_id"]),
                )
            except AppError:
                continue
            schema = release.get("input_schema")
            if not isinstance(schema, dict):
                continue
            release_id = str(row["capability_release_id"])
            values.append(
                RuntimeToolDescriptor(
                    name=str(row["identifier"]),
                    description=str(release["description"]),
                    input_schema=dict(schema),
                    schema_hash=_schema_hash(schema),
                    required_scope=f"capability:{release_id}",
                    kind="capability",
                    capability_release_id=release_id,
                )
            )
        return tuple(values)


class RuntimeToolBearerMiddleware:
    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        verifier: RuntimeToolTokenVerifier,
        authorizer: RuntimeToolAuthorizer,
    ) -> None:
        self.app = app
        self.verifier = verifier
        self.authorizer = authorizer

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or not str(scope.get("path") or "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers") or []
        }
        token = _bearer(headers.get("authorization", ""))
        try:
            claims = self.verifier.verify(token)
            self.authorizer.authorize_request(claims)
        except (RuntimeToolTokenError, RuntimeToolAuthorizationError):
            await _send_json_error(send, status=401, code="runtime_tool_authentication_failed")
            return
        scope.setdefault("state", {})["runtime_tool_claims"] = claims
        scope.setdefault("state", {})["runtime_tool_token"] = token
        await self.app(scope, receive, send)


class _StreamableHttpApp:
    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self.manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.manager.handle_request(scope, receive, send)


def create_runtime_tool_server(
    *,
    verifier: RuntimeToolTokenVerifier,
    authorizer: RuntimeToolAuthorizer,
) -> Server:
    server = Server(
        "Enterprise Runtime Tool MCP",
        version=SERVER_VERSION,
        instructions="Only exact Job-bound read-only Tools are exposed.",
    )

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        request, claims, _ = _request_facts(server)
        del request
        return [
            types.Tool(
                name=descriptor.name,
                description=descriptor.description,
                inputSchema=descriptor.input_schema,
                annotations=types.ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
            )
            for descriptor in authorizer.catalog(claims)
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        request, claims, token = _request_facts(server)
        try:
            _, descriptor = authorizer.descriptor(claims, name)
            verifier.verify(
                token,
                required_scope=descriptor.required_scope,
                tool_name=descriptor.name,
                tool_schema_hash=descriptor.schema_hash,
            )
            payload = await asyncio.to_thread(
                authorizer.invoke,
                claims=claims,
                descriptor=descriptor,
                arguments=arguments,
                correlation_id=str(request.headers.get("x-correlation-id") or "")[:128],
            )
            return _tool_result(payload, is_error=False)
        except (RuntimeToolTokenError, RuntimeToolAuthorizationError, AppError) as exc:
            safe_message = str(getattr(exc, "safe_message", "Runtime Tool 调用被拒绝"))
            code = str(getattr(exc, "code", getattr(exc, "error_code", "runtime_tool_denied")))
            return _tool_result(
                {"error": safe_message, "error_code": code},
                is_error=True,
            )
        except Exception:
            logger.exception("Runtime Tool call failed safely tool_name=%s", name)
            return _tool_result(
                {"error": "Runtime Tool 暂时不可用", "error_code": "runtime_tool_unavailable"},
                is_error=True,
            )

    return server


def create_app(
    *,
    verifier: RuntimeToolTokenVerifier,
    authorizer: RuntimeToolAuthorizer,
    allowed_hosts: tuple[str, ...] = (
        "runtime-tool-mcp",
        "runtime-tool-mcp:9103",
        "127.0.0.1:9103",
    ),
) -> RuntimeToolBearerMiddleware:
    server = create_runtime_tool_server(verifier=verifier, authorizer=authorizer)
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
            authorizer.repository.database.execute_one("select 1 as ready")
            return JSONResponse(
                {
                    "status": "ok",
                    "server_code": SERVER_CODE,
                    "server_version": SERVER_VERSION,
                    "database": "ready",
                    "tool_invoked": False,
                }
            )
        except Exception:
            return JSONResponse(
                {
                    "status": "degraded",
                    "server_code": SERVER_CODE,
                    "server_version": SERVER_VERSION,
                    "database": "unavailable",
                    "tool_invoked": False,
                },
                status_code=503,
            )

    @asynccontextmanager
    async def lifespan(_: Starlette):
        async with manager.run():
            yield

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/mcp", endpoint=_StreamableHttpApp(manager)),
        ],
        lifespan=lifespan,
    )
    return RuntimeToolBearerMiddleware(
        app,
        verifier=verifier,
        authorizer=authorizer,
    )


def create_default_app() -> RuntimeToolBearerMiddleware:
    settings = load_settings()
    runtime = build_worker_container(
        settings,
        seed=settings.seed_local_config,
        service_name=SERVER_CODE,
    )
    return create_app(
        verifier=RuntimeToolTokenVerifier.from_file(
            settings.runtime_tool_mcp.token_signing_key_file
        ),
        authorizer=_authorizer_from_container(runtime),
        allowed_hosts=settings.runtime_tool_mcp.allowed_hosts,
    )


def _authorizer_from_container(runtime: Container) -> RuntimeToolAuthorizer:
    return RuntimeToolAuthorizer(
        repository=runtime.agent_repository,
        tool_registry=ToolRegistry(runtime.tool_service),
        snapshot_service=runtime.builtin_tool_snapshot_service,
        governed_executor=runtime.governed_api_runtime_executor,
    )


def _request_facts(server: Server) -> tuple[Request, dict[str, Any], str]:
    request = server.request_context.request
    if not isinstance(request, Request):
        raise RuntimeToolAuthorizationError(
            "runtime_tool_transport_invalid",
            "Runtime Tool 传输上下文无效",
        )
    claims = getattr(request.state, "runtime_tool_claims", None)
    token = str(getattr(request.state, "runtime_tool_token", "") or "")
    if not isinstance(claims, dict) or not token:
        raise RuntimeToolAuthorizationError(
            "runtime_tool_authentication_failed",
            "Runtime Tool 身份无效",
        )
    return request, claims, token


def _bearer(authorization: str) -> str:
    scheme, separator, token = authorization.partition(" ")
    return token if separator and scheme.lower() == "bearer" else ""


async def _send_json_error(send: Send, *, status: int, code: str) -> None:
    body = json.dumps({"error": code}, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _tool_result(payload: dict[str, Any], *, is_error: bool) -> types.CallToolResult:
    safe = sanitize_for_persistence(payload)
    encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=encoded)],
        structuredContent=safe,
        isError=is_error,
    )


def _schema_hash(schema: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            schema,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


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
    if len(_encoded(safe)) > _MAX_RESPONSE_BYTES:
        raise RuntimeToolAuthorizationError(
            "runtime_tool_response_too_large",
            "Runtime Tool 响应超过大小限制",
        )
    return safe


def _bounded_summary(value: Any, *, max_chars: int = 4000) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    return {
        "payload": encoded[:max_chars],
        "truncated": len(encoded) > max_chars,
    }


def main() -> None:
    uvicorn.run(
        create_default_app(),
        host=os.environ.get("RUNTIME_TOOL_MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("RUNTIME_TOOL_MCP_PORT", "9103")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
