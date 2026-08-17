from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.metadata
import json
import os
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol
from urllib.request import Request, urlopen

from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunRequest,
    McpRuntimeBinding,
)
from app.modules.agent.infrastructure.runtime_protocol import (
    CURRENT_RUNTIME_PROTOCOL_VERSION,
)
from app.shared.mcp_server_policy import (
    FILE_MCP_SERVER_CODE,
    MCP_SERVER_POLICIES,
    ONES_MCP_SERVER_CODE,
    TOOL_MCP_SERVER_CODE,
    McpServerAuthMode,
    McpServerPolicy,
    mcp_sdk_server_alias,
    require_mcp_server_policy,
    validate_mcp_server_policies,
)
from app.python_runtime.job_sandbox import JobSandboxManager
from app.python_runtime.mcp_config import (
    FixedMcpClaudeSdkClient,
    fixed_mcp_server_url,
)
from app.python_runtime.tool_policy import normalize_tool_events
from app.shared.config import ExecutionSettings
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError

from .model_binding import PythonModelBindingResolver


class InvocationSecretContextPort(Protocol):
    @property
    def mcp_principal_tokens(self) -> Mapping[str, str]: ...

    @property
    def file_principal_token(self) -> str: ...


PYTHON_RUNTIME_VERSION = "0.1.0"
PYTHON_RUNTIME_KIND = "python-v1"
PROTOCOL_VERSION = CURRENT_RUNTIME_PROTOCOL_VERSION
MCP_CALL_ID_META_KEY = "enterprise-agent/mcp-call-id"
AGENT_TOOL_CALL_ID_META_KEY = "enterprise-agent/agent-tool-call-id"


@dataclass(frozen=True)
class PythonExecutionOutcome:
    status: str
    usage: dict[str, int | None]
    runtime_provenance: dict[str, Any]
    final_answer: str = ""
    runtime_events: tuple[dict[str, Any], ...] = ()
    tool_events: tuple[dict[str, Any], ...] = ()
    accounting: dict[str, Any] | None = None
    failure: dict[str, str] | None = None


class PythonRuntimeExecutor:
    def __init__(
        self,
        binding_resolver: PythonModelBindingResolver,
        *,
        limits: ExecutionSettings,
        mcp_server_url: str,
        business_mcp_server_urls: Mapping[str, str] | None = None,
        file_mcp_server_url: str = "http://file-service:9105/mcp",
        server_policies: Mapping[str, McpServerPolicy] | None = None,
        sdk_version: str | None = None,
        cli_version: str | None = None,
        fake_provider_mode: bool = False,
        sandbox_manager: JobSandboxManager | None = None,
    ) -> None:
        self._bindings = binding_resolver
        self._limits = limits
        self._mcp_server_url = fixed_mcp_server_url(mcp_server_url)
        self._server_policies = MappingProxyType(
            dict(MCP_SERVER_POLICIES if server_policies is None else server_policies)
        )
        validate_mcp_server_policies(self._server_policies)
        raw_business_urls = (
            {ONES_MCP_SERVER_CODE: "http://ones-mcp:9104/mcp"}
            if business_mcp_server_urls is None
            else dict(business_mcp_server_urls)
        )
        for server_code in raw_business_urls:
            policy = require_mcp_server_policy(
                server_code,
                policies=self._server_policies,
            )
            if policy.auth_mode is not McpServerAuthMode.BUSINESS_PRINCIPAL_JWT:
                raise ValueError("Business MCP URL configured for a non-business Server")
        self._business_mcp_server_urls = MappingProxyType(
            {
                server_code: fixed_mcp_server_url(url, server_code=server_code)
                for server_code, url in raw_business_urls.items()
            }
        )
        self._file_mcp_server_url = fixed_mcp_server_url(
            file_mcp_server_url,
            server_code="file-service",
        )
        self._sdk_version: str = sdk_version or importlib.metadata.version("claude-agent-sdk")
        self._cli_version: str = (
            cli_version or os.getenv("PYTHON_AGENT_RUNTIME_CLI_VERSION", "2.1.226") or "2.1.226"
        )
        self._fake_provider_mode = fake_provider_mode
        self._sandbox_manager = sandbox_manager

    @property
    def sdk_version(self) -> str:
        return self._sdk_version

    @property
    def cli_version(self) -> str:
        return self._cli_version

    def execute(
        self,
        request: dict[str, Any],
        cancel_event: threading.Event,
        secret_context: InvocationSecretContextPort | None = None,
    ) -> PythonExecutionOutcome:
        resolved = self._bindings.resolve(
            str(request["model_connection"]["revision_id"]),
            str(request["model_connection"]["config_hash"]),
        )
        provenance = self._provenance(request)
        if cancel_event.is_set():
            return self._cancelled(provenance)
        if self._fake_provider_mode:
            return self._execute_fake_provider(
                request,
                cancel_event,
                provenance,
                secret_context,
            )
        run_request = _agent_request(request, resolved.binding)
        client = FixedMcpClaudeSdkClient(
            limits=self._limits,
            api_key=resolved.api_key,
            mcp_server_url=self._mcp_server_url,
            business_mcp_server_urls=self._business_mcp_server_urls,
            mcp_principal_tokens=(secret_context.mcp_principal_tokens if secret_context else {}),
            file_mcp_server_url=self._file_mcp_server_url,
            file_principal_token=(secret_context.file_principal_token if secret_context else ""),
            server_policies=self._server_policies,
            sandbox_manager=self._sandbox_manager,
            cancellation_event=cancel_event,
        )
        try:
            result = client.run(run_request)
        except RetryableExecutionError as exc:
            return PythonExecutionOutcome(
                status="FAILED",
                usage={"input_tokens": 0, "output_tokens": 0},
                runtime_provenance=provenance,
                runtime_events=tuple(client.last_runtime_events),
                accounting=dict(client.last_accounting),
                tool_events=normalize_tool_events(
                    exc.tool_events,
                    request,
                    server_policies=self._server_policies,
                ),
                failure={
                    "code": str(exc.error_code or "runtime_transport_error"),
                    "retry_class": "TRANSIENT",
                    "safe_message": str(exc.safe_message or "模型运行暂时失败"),
                },
            )
        except NonRetryableExecutionError as exc:
            if str(exc.error_code or "") == "runtime_cancelled":
                return self._cancelled(provenance)
            return PythonExecutionOutcome(
                status="FAILED",
                usage={"input_tokens": 0, "output_tokens": 0},
                runtime_provenance=provenance,
                runtime_events=tuple(client.last_runtime_events),
                accounting=dict(client.last_accounting),
                tool_events=normalize_tool_events(
                    exc.tool_events,
                    request,
                    server_policies=self._server_policies,
                ),
                failure={
                    "code": str(exc.error_code or "runtime_configuration_error"),
                    "retry_class": "CONFIGURATION",
                    "safe_message": str(exc.safe_message or "模型运行配置不可用"),
                },
            )
        if cancel_event.is_set():
            return self._cancelled(provenance)
        return PythonExecutionOutcome(
            status="SUCCEEDED",
            final_answer=result.final_answer,
            usage={"input_tokens": 0, "output_tokens": 0},
            runtime_provenance=provenance,
            runtime_events=tuple(client.last_runtime_events),
            accounting=dict(client.last_accounting),
            tool_events=normalize_tool_events(
                result.tool_events,
                request,
                server_policies=self._server_policies,
            ),
        )

    def probe(self, request: dict[str, Any]) -> dict[str, Any]:
        resolved = self._bindings.resolve(
            str(request["model_connection"]["revision_id"]),
            str(request["model_connection"]["config_hash"]),
        )
        return self._probe_resolved(request, resolved)

    def probe_draft(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._probe_resolved(request, self._bindings.resolve_draft(request))

    def _probe_resolved(self, request: dict[str, Any], resolved: Any) -> dict[str, Any]:
        if not self._fake_provider_mode:
            client = FixedMcpClaudeSdkClient(
                limits=self._limits,
                api_key=resolved.api_key,
                mcp_server_url=self._mcp_server_url,
                business_mcp_server_urls=self._business_mcp_server_urls,
                server_policies=self._server_policies,
            )
            client.test_connection(
                resolved.binding,
                resolved.api_key,
                int(request["timeout_seconds"]),
            )
        return {
            "protocol_version": PROTOCOL_VERSION,
            "runtime_kind": PYTHON_RUNTIME_KIND,
            "probe_id": request["probe_id"],
            "success": True,
            "connection_revision_id": resolved.binding.connection_revision_id,
            "provider_host": resolved.binding.provider_host,
            "model": resolved.binding.model,
            "runtime_version": PYTHON_RUNTIME_VERSION,
            "sdk_version": self._sdk_version,
            "duration_ms": 0,
        }

    def _execute_fake_provider(
        self,
        request: dict[str, Any],
        cancel_event: threading.Event,
        provenance: dict[str, Any],
        secret_context: InvocationSecretContextPort | None,
    ) -> PythonExecutionOutcome:
        question = str(request["prompt"]["user_question"])
        if "[smoke:restart-slow]" in question:
            cancel_event.wait(timeout=30)
        elif "[smoke:slow]" in question:
            cancel_event.wait(timeout=5)
        if cancel_event.is_set():
            return self._cancelled(provenance)
        if "[smoke:mcp:tool-mcp]" in question:
            return self._execute_fake_mcp(
                request,
                provenance,
                server_code="tool-mcp",
                tool_name="get_er_context",
                arguments={"query": "enterprise agent acceptance"},
                bearer_token="",
                call_count=1,
            )
        if "[smoke:mcp:file-service]" in question:
            file_principal_token = secret_context.file_principal_token if secret_context else ""
            if not file_principal_token:
                return PythonExecutionOutcome(
                    status="FAILED",
                    usage={"input_tokens": 0, "output_tokens": 0},
                    runtime_provenance=provenance,
                    failure={
                        "code": "runtime_file_principal_token_missing",
                        "retry_class": "CONFIGURATION",
                        "safe_message": "当前文件调用缺少平台身份凭证",
                    },
                )
            return self._execute_fake_mcp(
                request,
                provenance,
                server_code="file-service",
                tool_name="task_workspace_get",
                arguments={},
                bearer_token=file_principal_token,
                call_count=1,
            )
        business_server_code = next(
            (
                server_code
                for server_code in sorted(self._business_mcp_server_urls)
                if f"[smoke:mcp:{server_code}" in question
            ),
            "",
        )
        if business_server_code:
            mcp_principal_tokens = secret_context.mcp_principal_tokens if secret_context else {}
            bearer_token = mcp_principal_tokens.get(business_server_code, "")
            if not bearer_token:
                return PythonExecutionOutcome(
                    status="FAILED",
                    usage={"input_tokens": 0, "output_tokens": 0},
                    runtime_provenance=provenance,
                    failure={
                        "code": "runtime_principal_token_missing",
                        "retry_class": "CONFIGURATION",
                        "safe_message": "当前调用缺少平台身份凭证",
                    },
                )
            return self._execute_fake_mcp(
                request,
                provenance,
                server_code=business_server_code,
                tool_name=(
                    "ones_work_item_search"
                    if business_server_code == ONES_MCP_SERVER_CODE
                    else self._first_frozen_tool(request, business_server_code)
                ),
                arguments=(
                    {"keyword": "traceability", "issue_type": "demand", "limit": 5}
                    if business_server_code == ONES_MCP_SERVER_CODE
                    else {}
                ),
                bearer_token=bearer_token,
                call_count=(
                    2 if f"[smoke:mcp:{business_server_code}-concurrent]" in question else 1
                ),
            )
        if "[smoke:retry-once]" in question and str(request["invocation_id"]).endswith(
            ".attempt-0"
        ):
            return PythonExecutionOutcome(
                status="FAILED",
                usage={"input_tokens": 0, "output_tokens": 0},
                runtime_provenance=provenance,
                failure={
                    "code": "runtime_fake_transient",
                    "retry_class": "TRANSIENT",
                    "safe_message": "Fake provider 暂时不可用",
                },
            )
        if "[smoke:dead]" in question:
            return PythonExecutionOutcome(
                status="FAILED",
                usage={"input_tokens": 0, "output_tokens": 0},
                runtime_provenance=provenance,
                failure={
                    "code": "runtime_fake_permanent",
                    "retry_class": "NEVER",
                    "safe_message": "Fake provider 请求失败",
                },
            )
        return PythonExecutionOutcome(
            status="SUCCEEDED",
            final_answer="Python Runtime fake-provider smoke completed.",
            usage={"input_tokens": 1, "output_tokens": 1},
            runtime_provenance=provenance,
        )

    def _execute_fake_mcp(
        self,
        request: dict[str, Any],
        provenance: dict[str, Any],
        *,
        server_code: str,
        tool_name: str,
        arguments: dict[str, Any],
        bearer_token: str,
        call_count: int,
    ) -> PythonExecutionOutcome:
        binding = next(
            (
                tool
                for server in request.get("mcp_servers") or []
                if server.get("server_code") == server_code
                for tool in server.get("tools") or []
                if tool.get("tool_name") == tool_name
            ),
            None,
        )
        if binding is None:
            return PythonExecutionOutcome(
                status="FAILED",
                usage={"input_tokens": 0, "output_tokens": 0},
                runtime_provenance=provenance,
                failure={
                    "code": "runtime_fake_mcp_binding_missing",
                    "retry_class": "CONFIGURATION",
                    "safe_message": "确定性 MCP 验收缺少冻结工具绑定",
                },
            )
        alias = mcp_sdk_server_alias(server_code, policies=self._server_policies)
        full_tool_name = f"mcp__{alias}__{tool_name}"
        calls = [
            {
                "index": index,
                "tool_call_id": f"fake-{server_code}-{uuid.uuid4().hex}",
                "correlation_id": f"fake-{server_code}-{uuid.uuid4().hex}",
            }
            for index in range(call_count)
        ]
        started_events = tuple(
            {
                "tool_call_id": call["tool_call_id"],
                "tool_name": full_tool_name,
                "status": "STARTED",
                "request_payload": arguments,
                "response_summary": {},
                "duration_ms": 0,
            }
            for call in calls
        )

        def invoke(call: dict[str, Any]) -> dict[str, Any]:
            started = time.monotonic()
            result = self._call_fake_mcp(
                request,
                server_code=server_code,
                tool_name=tool_name,
                arguments=arguments,
                bearer_token=bearer_token,
                correlation_id=str(call["correlation_id"]),
            )
            return {
                "tool_call_id": call["tool_call_id"],
                "tool_name": full_tool_name,
                "status": "SUCCEEDED",
                "request_payload": arguments,
                "response_summary": {"is_error": False},
                "duration_ms": int((time.monotonic() - started) * 1000),
                "mcp_call_id": result["mcp_call_id"],
                "persisted_tool_call_id": result["agent_tool_call_id"],
            }

        completed_events: tuple[dict[str, Any], ...]
        try:
            if call_count == 1:
                completed_events = (invoke(calls[0]),)
            else:
                with ThreadPoolExecutor(max_workers=call_count) as executor:
                    completed_events = tuple(executor.map(invoke, calls))
        except Exception:
            failed_events = tuple(
                {
                    "tool_call_id": call["tool_call_id"],
                    "tool_name": full_tool_name,
                    "status": "FAILED",
                    "request_payload": arguments,
                    "response_summary": {},
                    "duration_ms": 0,
                    "error_code": "runtime_fake_mcp_failed",
                }
                for call in calls
            )
            return PythonExecutionOutcome(
                status="FAILED",
                usage={"input_tokens": 0, "output_tokens": 0},
                runtime_provenance=provenance,
                tool_events=normalize_tool_events(
                    [*started_events, *failed_events],
                    request,
                    server_policies=self._server_policies,
                ),
                failure={
                    "code": "runtime_fake_mcp_failed",
                    "retry_class": "NEVER",
                    "safe_message": "确定性 MCP 验收调用失败",
                },
            )
        return PythonExecutionOutcome(
            status="SUCCEEDED",
            final_answer=f"Python Runtime {server_code} MCP smoke completed.",
            usage={"input_tokens": 1, "output_tokens": 1},
            runtime_provenance=provenance,
            tool_events=normalize_tool_events(
                [*started_events, *completed_events],
                request,
                server_policies=self._server_policies,
            ),
        )

    def _call_fake_mcp(
        self,
        request: dict[str, Any],
        *,
        server_code: str,
        tool_name: str,
        arguments: dict[str, Any],
        bearer_token: str,
        correlation_id: str,
    ) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-Invocation-Id": str(request["invocation_id"]),
            "X-Correlation-Id": correlation_id,
        }
        policy = require_mcp_server_policy(server_code, policies=self._server_policies)
        if policy.auth_mode is McpServerAuthMode.BUSINESS_PRINCIPAL_JWT:
            url = self._business_mcp_server_urls.get(server_code, "")
            if not url or not bearer_token:
                raise RuntimeError("deterministic Business MCP configuration is missing")
            headers["Authorization"] = f"Bearer {bearer_token}"
        elif policy.auth_mode is McpServerAuthMode.FILE_PRINCIPAL_JWT:
            if server_code != FILE_MCP_SERVER_CODE or not bearer_token:
                raise RuntimeError("deterministic File MCP configuration is missing")
            headers["Authorization"] = f"Bearer {bearer_token}"
            url = self._file_mcp_server_url
        elif policy.auth_mode is McpServerAuthMode.JOB_CONTEXT:
            if server_code != TOOL_MCP_SERVER_CODE:
                raise RuntimeError("deterministic Job-context MCP configuration is invalid")
            headers.update(
                {
                    "X-Job-Id": str(request["job_id"]),
                    "X-App-User-Id": str(request["app_user_id"]),
                    "X-Project-Code": str(request["project_code"]),
                    "X-Agent-Publication-Id": str(request["agent_publication_id"]),
                    "X-Application-Publication-Id": str(request["application_publication_id"]),
                }
            )
            url = self._mcp_server_url
        else:
            raise RuntimeError("deterministic MCP authentication mode is unsupported")
        self._fake_mcp_post(
            url,
            headers,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "runtime-acceptance", "version": "1"},
                },
            },
        )
        result = self._fake_mcp_post(
            url,
            {**headers, "MCP-Protocol-Version": "2025-06-18"},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        ).get("result")
        if not isinstance(result, dict) or result.get("isError") is True:
            raise RuntimeError("deterministic MCP Tool returned an error")
        meta = result.get("_meta")
        if not isinstance(meta, dict):
            raise RuntimeError("deterministic MCP Tool metadata is missing")
        mcp_call_id = str(meta.get(MCP_CALL_ID_META_KEY) or "")
        agent_tool_call_id = str(meta.get(AGENT_TOOL_CALL_ID_META_KEY) or "")
        if not mcp_call_id or not agent_tool_call_id:
            raise RuntimeError("deterministic MCP Tool metadata is incomplete")
        return {
            "mcp_call_id": mcp_call_id,
            "agent_tool_call_id": agent_tool_call_id,
        }

    @staticmethod
    def _first_frozen_tool(request: dict[str, Any], server_code: str) -> str:
        tools = next(
            (
                server.get("tools")
                for server in request.get("mcp_servers") or []
                if server.get("server_code") == server_code
            ),
            None,
        )
        if not isinstance(tools, list) or not tools:
            return ""
        return str(tools[0].get("tool_name") or "")

    @staticmethod
    def _fake_mcp_post(
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        request = Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            body = response.read(1024 * 1024 + 1)
            content_type = str(response.headers.get("content-type") or "")
        if len(body) > 1024 * 1024:
            raise RuntimeError("deterministic MCP response is too large")
        text = body.decode("utf-8")
        if "text/event-stream" in content_type:
            data_lines = [
                line.removeprefix("data:").strip()
                for line in text.splitlines()
                if line.startswith("data:")
            ]
            if not data_lines:
                raise RuntimeError("deterministic MCP SSE response is empty")
            text = data_lines[-1]
        decoded = json.loads(text)
        if not isinstance(decoded, dict):
            raise RuntimeError("deterministic MCP response is invalid")
        return decoded

    def _provenance(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "runtime_kind": PYTHON_RUNTIME_KIND,
            "runtime_version": PYTHON_RUNTIME_VERSION,
            "protocol_version": request["protocol_version"],
            "sdk_version": self._sdk_version,
            "cli_version": self._cli_version,
            "model_connection_revision_id": request["model_connection"]["revision_id"],
            "model_connection_config_hash": request["model_connection"]["config_hash"],
        }

    @staticmethod
    def _cancelled(provenance: dict[str, Any]) -> PythonExecutionOutcome:
        return PythonExecutionOutcome(
            status="CANCELLED",
            usage={"input_tokens": 0, "output_tokens": 0},
            runtime_provenance=provenance,
            failure={
                "code": "runtime_cancelled",
                "retry_class": "NEVER",
                "safe_message": "Agent 执行已取消",
            },
        )


def _agent_request(request: dict[str, Any], binding: Any) -> AgentRunRequest:
    tools = tuple(
        McpRuntimeBinding(
            server_code=str(server["server_code"]),
            tool_name=str(tool["tool_name"]),
            required_scope=str(tool["required_scope"]),
            tool_schema_hash=str(tool["tool_schema_hash"]),
            resource_code=str(tool.get("resource_code") or ""),
            resource_deployment_id=str(tool.get("resource_deployment_id") or ""),
            resource_revision_id=str(tool.get("resource_revision_id") or ""),
        )
        for server in request["mcp_servers"]
        for tool in server["tools"]
    )
    prompt = request["prompt"]
    limits = request["limits"]
    context = AgentExecutionContext(
        system_role=str(prompt["system_role"]),
        safety_rules=list(prompt["safety_rules"]),
        business_instructions=str(prompt["business_instructions"]),
        user_question=str(prompt["user_question"]),
        project_code=str(request["project_code"]),
        allowed_tools=[item.tool_name for item in tools],
        tool_restrictions=list(prompt["tool_restrictions"]),
        skills=dict(prompt.get("skills") or {}),
        retrieved_context=dict(prompt["retrieved_context"]),
        conversation_summary=str(prompt["conversation_summary"]),
        max_turns=int(limits["max_turns"]),
        timeout_seconds=int(limits["timeout_seconds"]),
        max_tool_calls=int(limits["max_tool_calls"]),
        publication_id=str(request["agent_publication_id"]),
        application_publication_id=str(request["application_publication_id"]),
        model_runtime_binding=binding,
        mcp_bindings=tools,
        runtime_kind=PYTHON_RUNTIME_KIND,
        runtime_protocol_version=str(request["protocol_version"]),
        file_format_policy_version=str(
            (request.get("file_context") or {}).get("file_format_policy_version", "text-v1")
        ),
    )
    return AgentRunRequest(
        job_id=str(request["job_id"]),
        user_id=str(request["app_user_id"]),
        project_code=str(request["project_code"]),
        context=context,
        invocation_id=str(request["invocation_id"]),
    )
