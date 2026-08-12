from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import quote, urlsplit

import jwt

from app.modules.agent.domain.runtime import (
    AgentRunRequest,
    AgentRunResult,
    McpRuntimeBinding,
)
from app.modules.agent.infrastructure.runtime_protocol import (
    canonical_request_digest,
    validate_execution_request,
    validate_runtime_contract,
)
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import (
    NonRetryableExecutionError,
    RetryableExecutionError,
)

MAX_EVENT_LINE_BYTES = 65_536
MAX_STREAM_BYTES = 2_097_152
MAX_EVENTS = 2_048
IN_PROGRESS_RECOVERY_ATTEMPTS = 12
IN_PROGRESS_RECOVERY_DELAY_SECONDS = 0.5
STANDARD_TOOL_MCP_CODE = "tool-mcp"
ONES_MCP_CODE = "ones-mcp"


def _runtime_event_count(value: object) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


class RuntimeTransport(Protocol):
    def stream(
        self,
        *,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> Iterator[bytes]: ...

    def post(
        self,
        *,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]: ...


class PrincipalTokenIssuerPort(Protocol):
    def issue_for_job(self, *, job_id: str) -> str: ...


class UrlLibRuntimeTransport:
    def stream(
        self,
        *,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> Iterator[bytes]:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                content_type = str(response.headers.get("content-type") or "").lower()
                if response.status != 200 or "application/x-ndjson" not in content_type:
                    raise RetryableExecutionError(
                        "Agent Runtime returned an invalid streaming response",
                        safe_message="Agent Runtime 返回了无效响应",
                        error_code="runtime_transport_invalid_response",
                    )
                yield from response
        except urllib.error.HTTPError as exc:
            if exc.code in {400, 401, 403, 404, 409, 413, 422}:
                raise NonRetryableExecutionError(
                    "Agent Runtime rejected the execution request",
                    safe_message="Agent Runtime 拒绝了执行请求",
                    error_code="runtime_request_rejected",
                ) from exc
            raise RetryableExecutionError(
                "Agent Runtime is temporarily unavailable",
                safe_message="Agent Runtime 暂时不可用",
                error_code="runtime_transport_error",
            ) from exc
        except TimeoutError as exc:
            raise RetryableExecutionError(
                "Agent Runtime transport timed out",
                safe_message="Agent Runtime 通信超时",
                error_code="runtime_transport_error",
                diagnostics={"cancel_reason": "WORKER_TIMEOUT"},
            ) from exc
        except OSError as exc:
            cancel_reason = (
                "WORKER_TIMEOUT"
                if isinstance(getattr(exc, "reason", None), TimeoutError)
                else "CLIENT_DISCONNECTED"
            )
            raise RetryableExecutionError(
                "Agent Runtime transport failed",
                safe_message="Agent Runtime 通信失败",
                error_code="runtime_transport_error",
                diagnostics={"cancel_reason": cancel_reason},
            ) from exc

    def post(
        self,
        *,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                if response.status != 200:
                    raise RetryableExecutionError(
                        "Agent Runtime cancel returned an invalid status",
                        safe_message="Agent Runtime 取消请求失败",
                        error_code="runtime_cancel_failed",
                    )
                payload = json.loads(response.read(65_536).decode("utf-8"))
                return payload if isinstance(payload, dict) else {}
        except (OSError, TimeoutError, ValueError) as exc:
            raise RetryableExecutionError(
                "Agent Runtime cancel transport failed",
                safe_message="Agent Runtime 取消请求失败",
                error_code="runtime_cancel_failed",
            ) from exc


class RuntimeGrantIssuer:
    def __init__(self, private_key: bytes, *, now: Callable[[], int] | None = None) -> None:
        if not private_key.startswith(b"-----BEGIN PRIVATE KEY-----"):
            raise ValueError("Runtime Grant private key must be PKCS8 PEM")
        self._private_key = private_key
        self._now = now or (lambda: int(time.time()))

    @classmethod
    def from_file(cls, path: str) -> RuntimeGrantIssuer:
        configured = path.strip()
        if not configured:
            raise ValueError("RUNTIME_GRANT_PRIVATE_KEY_FILE is required")
        key_path = Path(configured)
        try:
            if not 64 <= key_path.stat().st_size <= 16_384:
                raise ValueError("Runtime Grant private key size is invalid")
            private_key = key_path.read_bytes()
        except OSError as exc:
            raise ValueError("Runtime Grant private key is unreadable") from exc
        return cls(private_key)

    def issue(self, request: dict[str, Any]) -> str:
        now = self._now()
        timeout_seconds = int(request["limits"]["timeout_seconds"])
        ttl_seconds = min(timeout_seconds + 60, 15 * 60)
        claims = {
            "iss": "enterprise-agent-worker",
            "aud": "agent-runtime",
            "azp": "agent-worker",
            "runtime_kind": str(request["runtime_kind"]),
            "sub": str(request["app_user_id"]),
            "job_id": str(request["job_id"]),
            "invocation_id": str(request["invocation_id"]),
            "agent_publication_id": str(request["agent_publication_id"]),
            "application_publication_id": str(request["application_publication_id"]),
            "request_digest": str(request["request_digest"]),
            "iat": now,
            "nbf": now - 1,
            "exp": now + ttl_seconds,
            "jti": f"{request['invocation_id']}.{request['request_digest'][:16]}",
        }
        validate_runtime_contract(
            "RuntimeGrantClaims",
            claims,
            protocol_version=str(request["protocol_version"]),
        )
        return str(
            jwt.encode(
                claims,
                self._private_key,
                algorithm="EdDSA",
                headers={"typ": "JWT"},
            )
        )


@dataclass(frozen=True)
class RuntimeClientSettings:
    base_url: str
    allowed_runtime_hosts: tuple[str, ...]
    runtime_kind: str = "typescript-v1"
    allowed_mcp_server_codes: tuple[str, ...] = (STANDARD_TOOL_MCP_CODE, ONES_MCP_CODE)
    allow_insecure_internal_http: bool = False

    def execution_url(self) -> str:
        normalized = self.base_url.strip().rstrip("/")
        parsed = urlsplit(normalized)
        host = (parsed.hostname or "").lower()
        allowed_hosts = {value.strip().lower() for value in self.allowed_runtime_hosts}
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or host not in allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Agent Runtime URL is outside the deployment boundary")
        if parsed.scheme == "http":
            loopback = host in {"localhost", "127.0.0.1", "::1"}
            if not loopback and not self.allow_insecure_internal_http:
                raise ValueError(
                    "Agent Runtime HTTP requires explicit private-network opt-in; use HTTPS "
                    "for authenticated service identity outside local Compose"
                )
        return f"{normalized}/internal/v1/executions"


def probe_runtime_readiness(settings: RuntimeClientSettings) -> dict[str, Any]:
    """Passive service-identity/readiness probe; never invokes a model or MCP Tool."""

    def get(base_url: str, path: str, *, accepted_statuses: set[int]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{base_url}{path}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        assert_external_io_allowed("agent_runtime.passive_readiness")
        try:
            response = urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as exc:
            if exc.code not in accepted_statuses:
                raise
            response = exc
        with response:
            raw = response.read(65_537)
            if response.status not in accepted_statuses or len(raw) > 65_536:
                raise ValueError("Agent Runtime passive probe returned an invalid response")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Agent Runtime passive probe payload is invalid")
        return payload

    try:
        settings.execution_url()
        base_url = settings.base_url.strip().rstrip("/")
        version = get(base_url, "/version", accepted_statuses={200})
        readiness = get(base_url, "/ready", accepted_statuses={200, 503})
        identity_ready = (
            version.get("runtime") == settings.runtime_kind
            and version.get("protocol_version") in {"1.0", "1.1"}
            and isinstance(version.get("runtime_version"), str)
        )
        dependency_ready = (
            readiness.get("ready") is True
            and readiness.get("database") == "ready"
            and readiness.get("master_key") == "ready"
        )
        return {
            "configured": True,
            "ready": bool(identity_ready and dependency_ready),
            "identity": "verified" if identity_ready else "invalid",
            "database": readiness.get("database", "unavailable"),
            "master_key": readiness.get("master_key", "unavailable"),
            "runtime_version": (str(version.get("runtime_version")) if identity_ready else ""),
            "protocol_version": (str(version.get("protocol_version")) if identity_ready else ""),
            "sdk_version": str(version.get("sdk_version")) if identity_ready else "",
            "cli_version": str(version.get("cli_version")) if identity_ready else "",
            "model_invoked": False,
            "mcp_invoked": False,
        }
    except Exception:
        return {
            "configured": True,
            "ready": False,
            "identity": "unavailable",
            "database": "unavailable",
            "master_key": "unavailable",
            "runtime_version": "",
            "protocol_version": "",
            "sdk_version": "",
            "cli_version": "",
            "model_invoked": False,
            "mcp_invoked": False,
        }


class AgentRuntimeHttpClient:
    def __init__(
        self,
        *,
        settings: RuntimeClientSettings,
        grant_issuer: RuntimeGrantIssuer,
        transport: RuntimeTransport | None = None,
        event_sink: Callable[[str, dict[str, Any]], None] | None = None,
        principal_token_issuer: PrincipalTokenIssuerPort | None = None,
    ) -> None:
        self.settings = settings
        self.execution_url = settings.execution_url()
        self.grant_issuer = grant_issuer
        self.transport = transport or UrlLibRuntimeTransport()
        self.event_sink = event_sink
        self.principal_token_issuer = principal_token_issuer

    def run(self, run_request: AgentRunRequest) -> AgentRunResult:
        request = self._execution_request(run_request)
        grant = self.grant_issuer.issue(request)
        principal_token = self._principal_token(run_request, request)
        try:
            return self._consume_stream(run_request, request, grant, principal_token)
        except RetryableExecutionError as exc:
            if getattr(exc, "error_code", "") not in {
                "runtime_transport_error",
                "runtime_terminal_missing",
            }:
                raise
            observed = _runtime_event_count(exc.diagnostics.get("runtime_events_observed", 0))
            recovery_attempts = IN_PROGRESS_RECOVERY_ATTEMPTS if observed else 1
            recovery_error = exc
            for recovery_attempt in range(recovery_attempts):
                if observed:
                    time.sleep(IN_PROGRESS_RECOVERY_DELAY_SECONDS)
                try:
                    # Every recovery uses the exact same invocation and digest.
                    # Once a stream event was observed, no new Job attempt may
                    # start until this bounded recovery returns a terminal.
                    return self._consume_stream(run_request, request, grant, principal_token)
                except RetryableExecutionError as candidate:
                    recovery_error = candidate
                    observed = max(
                        observed,
                        _runtime_event_count(
                            candidate.diagnostics.get("runtime_events_observed", 0)
                        ),
                    )
                    if getattr(candidate, "error_code", "") not in {
                        "runtime_transport_error",
                        "runtime_terminal_missing",
                    }:
                        raise
                    if recovery_attempt + 1 < recovery_attempts:
                        continue
                if getattr(recovery_error, "error_code", "") not in {
                    "runtime_transport_error",
                    "runtime_terminal_missing",
                }:
                    raise
                reason = str(
                    getattr(recovery_error, "diagnostics", {}).get(
                        "cancel_reason", "CLIENT_DISCONNECTED"
                    )
                )
                if reason not in {
                    "JOB_CANCELLED",
                    "WORKER_TIMEOUT",
                    "CLIENT_DISCONNECTED",
                    "WORKER_SHUTDOWN",
                }:
                    reason = "CLIENT_DISCONNECTED"
                try:
                    self._cancel_prepared(run_request, request, reason)
                except RetryableExecutionError as cancel_error:
                    recovery_error.diagnostics["cancel_error_code"] = getattr(
                        cancel_error, "error_code", "runtime_cancel_failed"
                    )
                if observed:
                    raise NonRetryableExecutionError(
                        "Runtime invocation outcome is unknown after an interrupted stream",
                        safe_message=("Agent Runtime 执行中断；为避免重复模型调用，本次执行已失败"),
                        tool_events=recovery_error.tool_events,
                        error_code="runtime_invocation_outcome_unknown",
                        diagnostics={
                            **recovery_error.diagnostics,
                            "runtime_events_observed": observed,
                        },
                    ) from recovery_error
                raise
            raise recovery_error

    def _consume_stream(
        self,
        run_request: AgentRunRequest,
        request: dict[str, Any],
        grant: str,
        principal_token: str,
    ) -> AgentRunResult:
        body = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {grant}",
            "Content-Type": "application/json",
            "Accept": "application/x-ndjson",
            "X-Correlation-Id": f"job:{run_request.job_id}",
        }
        if principal_token:
            headers["X-MCP-Principal-Token"] = principal_token
        events: list[dict[str, Any]] = []
        tool_events: list[dict[str, Any]] = []
        total_bytes = 0
        terminal: dict[str, Any] | None = None
        expected_sequence = 1
        stream = iter(
            self.transport.stream(
                url=self.execution_url,
                body=body,
                headers=headers,
                timeout_seconds=run_request.context.timeout_seconds + 10,
            )
        )
        while True:
            try:
                raw_line = next(stream)
            except StopIteration:
                break
            except RetryableExecutionError as exc:
                exc.diagnostics["runtime_events_observed"] = len(events)
                if tool_events:
                    exc.tool_events = tool_events
                raise
            total_bytes += len(raw_line)
            if len(raw_line) > MAX_EVENT_LINE_BYTES or total_bytes > MAX_STREAM_BYTES:
                raise self._protocol_error(
                    "Runtime event stream exceeds its byte boundary", tool_events
                )
            if len(events) >= MAX_EVENTS:
                raise self._protocol_error(
                    "Runtime event stream exceeds its event boundary", tool_events
                )
            try:
                event = json.loads(raw_line.decode("utf-8"))
                validate_runtime_contract("RuntimeEvent", event)
            except (UnicodeError, ValueError, TypeError) as exc:
                raise self._protocol_error("Runtime emitted an invalid event", tool_events) from exc
            if (
                event["invocation_id"] != request["invocation_id"]
                or event["request_digest"] != request["request_digest"]
                or event["protocol_version"] != request["protocol_version"]
                or int(event["sequence"]) != expected_sequence
                or terminal is not None
            ):
                raise self._protocol_error(
                    "Runtime event identity or sequence mismatch", tool_events
                )
            expected_sequence += 1
            events.append(event)
            if self.event_sink is not None:
                self.event_sink(run_request.job_id, event)
            if event["event_type"] == "tool_event":
                tool_events.append(
                    {
                        **dict(event["payload"]),
                        "invocation_id": str(event["invocation_id"]),
                    }
                )
            if event["event_type"] == "terminal":
                terminal = dict(event["payload"])
        if terminal is None:
            raise RetryableExecutionError(
                "Agent Runtime stream ended without a terminal result",
                safe_message="Agent Runtime 未返回终态",
                tool_events=tool_events,
                error_code="runtime_terminal_missing",
                diagnostics={"runtime_events_observed": len(events)},
            )
        if int(terminal["last_sequence"]) != expected_sequence - 1:
            raise self._protocol_error("Runtime terminal sequence mismatch", tool_events)
        provenance = dict(terminal["runtime_provenance"])
        if terminal["status"] == "SUCCEEDED":
            return AgentRunResult(
                final_answer=str(terminal["final_answer"]),
                tool_events=tool_events,
                runtime_provenance=provenance,
            )
        failure = dict(terminal.get("failure") or {})
        exception_type = (
            RetryableExecutionError
            if failure.get("retry_class") == "TRANSIENT"
            else NonRetryableExecutionError
        )
        raise exception_type(
            f"Agent Runtime failed with {failure.get('code') or 'runtime_failure'}",
            safe_message=str(failure.get("safe_message") or "Agent Runtime 执行失败"),
            tool_events=tool_events,
            error_code=str(failure.get("code") or "runtime_failure"),
            diagnostics={"runtime_provenance": provenance},
        )

    def cancel(self, run_request: AgentRunRequest, reason: str) -> dict[str, Any]:
        request = self._execution_request(run_request)
        return self._cancel_prepared(run_request, request, reason)

    def _cancel_prepared(
        self,
        run_request: AgentRunRequest,
        request: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        grant = self.grant_issuer.issue(request)
        payload = {
            "protocol_version": request["protocol_version"],
            "invocation_id": request["invocation_id"],
            "request_digest": request["request_digest"],
            "reason": reason,
        }
        validate_runtime_contract("CancelRequest", payload)
        return self.transport.post(
            url=(
                f"{self.settings.base_url.rstrip('/')}/internal/v1/executions/"
                f"{quote(str(request['invocation_id']), safe='')}/cancel"
            ),
            body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {grant}",
                "Content-Type": "application/json",
                "X-Correlation-Id": f"job:{run_request.job_id}",
            },
            timeout_seconds=5,
        )

    def _execution_request(self, run_request: AgentRunRequest) -> dict[str, Any]:
        context = run_request.context
        if context.runtime_kind != self.settings.runtime_kind:
            raise NonRetryableExecutionError(
                "Job runtime kind does not match the fixed Runtime client",
                safe_message="当前 Job 与目标 Runtime 不匹配",
                error_code="runtime_kind_mismatch",
            )
        binding = context.model_runtime_binding
        if binding is None or not binding.connection_revision_id or len(binding.config_hash) != 64:
            raise NonRetryableExecutionError(
                "TypeScript Runtime requires a frozen model connection revision",
                safe_message="当前 Job 缺少固定模型连接",
                error_code="runtime_model_binding_missing",
            )
        if not context.publication_id or not context.application_publication_id:
            raise NonRetryableExecutionError(
                "TypeScript Runtime requires frozen Agent and Application publications",
                safe_message="当前 Job 缺少固定发布版本",
                error_code="runtime_publication_binding_missing",
            )
        grouped: dict[str, list[McpRuntimeBinding]] = {}
        for binding_item in self._runtime_bindings(run_request):
            if binding_item.server_code not in self.settings.allowed_mcp_server_codes:
                raise NonRetryableExecutionError(
                    "Job references an unapproved MCP server",
                    safe_message="当前 Job 引用了未允许的 MCP 服务",
                    error_code="mcp_server_not_allowed",
                )
            grouped.setdefault(binding_item.server_code, []).append(binding_item)
        mcp_servers: list[dict[str, Any]] = []
        for server_code, tool_bindings in sorted(grouped.items()):
            tools = []
            for item in sorted(tool_bindings, key=lambda value: value.tool_name):
                tool = {
                    "tool_name": item.tool_name,
                    "required_scope": item.required_scope,
                    "tool_schema_hash": item.tool_schema_hash,
                }
                for field in (
                    "resource_code",
                    "resource_deployment_id",
                    "resource_revision_id",
                ):
                    value = str(getattr(item, field) or "")
                    if value:
                        tool[field] = value
                tools.append(tool)
            mcp_servers.append(
                {
                    "server_code": server_code,
                    "tools": tools,
                }
            )
        protocol_version = str(context.runtime_protocol_version or "1.0")
        if protocol_version not in {"1.0", "1.1"}:
            raise NonRetryableExecutionError(
                "Job runtime protocol version is unsupported",
                safe_message="当前 Job Runtime 协议版本不受支持",
                error_code="runtime_protocol_unsupported",
            )
        request: dict[str, Any] = {
            "protocol_version": protocol_version,
            "runtime_kind": context.runtime_kind,
            "invocation_id": run_request.invocation_id or f"{run_request.job_id}.attempt-0",
            "request_digest": "0" * 64,
            "job_id": run_request.job_id,
            "app_user_id": run_request.user_id,
            "project_code": run_request.project_code,
            "agent_publication_id": context.publication_id,
            "application_publication_id": context.application_publication_id,
            "model_connection": {
                "revision_id": binding.connection_revision_id,
                "config_hash": binding.config_hash,
            },
            "prompt": {
                "system_role": context.system_role,
                "safety_rules": list(context.safety_rules),
                "business_instructions": context.business_instructions,
                "tool_restrictions": list(context.tool_restrictions),
                "user_question": context.user_question,
                "conversation_summary": context.conversation_summary,
                "retrieved_context": context.retrieved_context,
                "skills": context.skills,
                "mcp_unavailable_notices": [
                    {
                        "tool_name": notice.tool_name,
                        "reason_code": notice.reason_code,
                        "message": notice.message,
                    }
                    for notice in context.mcp_unavailable_notices
                ],
            },
            "limits": {
                "timeout_seconds": context.timeout_seconds,
                "max_turns": context.max_turns,
                "max_tool_calls": context.max_tool_calls,
            },
            "mcp_servers": mcp_servers,
        }
        request["request_digest"] = canonical_request_digest(request)
        return cast(dict[str, Any], validate_execution_request(request))

    def _principal_token(
        self,
        run_request: AgentRunRequest,
        request: dict[str, Any],
    ) -> str:
        requires_principal = any(
            str(server.get("server_code") or "") == ONES_MCP_CODE
            for server in request.get("mcp_servers") or []
        )
        if not requires_principal:
            return ""
        if self.principal_token_issuer is None:
            raise NonRetryableExecutionError(
                "ONES MCP requires a Principal Token issuer",
                safe_message="当前 Job 缺少平台身份凭证签发服务",
                error_code="principal_token_issuer_unavailable",
            )
        return self.principal_token_issuer.issue_for_job(job_id=run_request.job_id)

    @staticmethod
    def _runtime_bindings(run_request: AgentRunRequest) -> tuple[McpRuntimeBinding, ...]:
        context = run_request.context
        if context.mcp_bindings:
            return context.mcp_bindings
        bindings: list[McpRuntimeBinding] = []
        for tool_name in context.allowed_tools:
            definition = MCP_TOOL_MANIFEST.get(tool_name)
            if definition is None:
                raise NonRetryableExecutionError(
                    "Job references an unknown MCP Tool",
                    safe_message="当前 Job 包含未知 MCP 工具",
                    error_code="runtime_tool_mapping_missing",
                )
            bindings.append(
                McpRuntimeBinding(
                    server_code=definition.server_code,
                    tool_name=tool_name,
                    required_scope=f"tool:{tool_name}",
                    tool_schema_hash=definition.schema_hash,
                )
            )
        return tuple(bindings)

    @staticmethod
    def _protocol_error(
        message: str, tool_events: list[dict[str, Any]]
    ) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            message,
            safe_message="Agent Runtime 协议校验失败",
            tool_events=tool_events,
            error_code="runtime_protocol_error",
        )


# Compatibility for callers not yet renamed; implementation is runtime-neutral.
TypeScriptAgentRuntimeClient = AgentRuntimeHttpClient
