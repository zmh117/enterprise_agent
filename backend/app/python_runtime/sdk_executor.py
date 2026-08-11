from __future__ import annotations

import importlib.metadata
import os
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunRequest,
    McpRuntimeBinding,
)
from app.python_runtime.claude_agent_sdk_adapter import (
    RealClaudeCodeAgentClient,
)
from app.shared.config import ExecutionSettings
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError

from .model_binding import PythonModelBindingResolver

PYTHON_RUNTIME_VERSION = "0.1.0"
PYTHON_RUNTIME_KIND = "python-v1"
PROTOCOL_VERSION = "1.0"


@dataclass(frozen=True)
class PythonExecutionOutcome:
    status: str
    usage: dict[str, int]
    runtime_provenance: dict[str, Any]
    final_answer: str = ""
    tool_events: tuple[dict[str, Any], ...] = ()
    failure: dict[str, str] | None = None


class RemoteMcpClaudeCodeAgentClient(RealClaudeCodeAgentClient):
    """Existing Python SDK adapter with only a deployment-fixed remote MCP server."""

    def __init__(
        self,
        *,
        limits: ExecutionSettings,
        api_key: str,
        mcp_server_url: str,
    ) -> None:
        super().__init__(
            model="",
            tool_registry=None,  # type: ignore[arg-type]
            limits=limits,
            api_key="",
            secret_resolver=lambda _ref: api_key,
        )
        self._mcp_server_url = mcp_server_url

    def _build_internal_server(
        self,
        _sdk: Any,
        request: AgentRunRequest,
        _tool_events: list[dict[str, Any]],
        _tool_budget: Any,
    ) -> dict[str, Any]:
        return {
            "type": "http",
            "url": self._mcp_server_url,
            "headers": {
                "X-Correlation-Id": f"job:{request.job_id}",
                "X-Job-Id": request.job_id,
                "X-App-User-Id": request.user_id,
                "X-Project-Code": request.project_code,
                "X-Invocation-Id": request.invocation_id,
                "X-Agent-Publication-Id": request.context.publication_id,
                "X-Application-Publication-Id": (
                    request.context.application_publication_id
                ),
            },
        }


class PythonRuntimeSdkExecutor:
    def __init__(
        self,
        binding_resolver: PythonModelBindingResolver,
        *,
        limits: ExecutionSettings,
        mcp_server_url: str,
        sdk_version: str | None = None,
        cli_version: str | None = None,
        fake_provider_mode: bool = False,
    ) -> None:
        self._bindings = binding_resolver
        self._limits = limits
        self._mcp_server_url = _fixed_mcp_server_url(mcp_server_url)
        self._sdk_version = sdk_version or importlib.metadata.version("claude-agent-sdk")
        self._cli_version = cli_version or os.getenv(
            "PYTHON_AGENT_RUNTIME_CLI_VERSION", "2.1.226"
        )
        self._fake_provider_mode = fake_provider_mode

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
    ) -> PythonExecutionOutcome:
        resolved = self._bindings.resolve(
            str(request["model_connection"]["revision_id"]),
            str(request["model_connection"]["config_hash"]),
        )
        provenance = self._provenance(request)
        if cancel_event.is_set():
            return self._cancelled(provenance)
        if self._fake_provider_mode:
            return self._execute_fake_provider(request, cancel_event, provenance)
        run_request = _agent_request(request, resolved.binding)
        client = RemoteMcpClaudeCodeAgentClient(
            limits=self._limits,
            api_key=resolved.api_key,
            mcp_server_url=self._mcp_server_url,
        )
        try:
            result = client.run(run_request)
        except RetryableExecutionError as exc:
            return PythonExecutionOutcome(
                status="FAILED",
                usage={"input_tokens": 0, "output_tokens": 0},
                runtime_provenance=provenance,
                tool_events=_normalize_tool_events(exc.tool_events),
                failure={
                    "code": str(exc.error_code or "runtime_transport_error"),
                    "retry_class": "TRANSIENT",
                    "safe_message": str(exc.safe_message or "模型运行暂时失败"),
                },
            )
        except NonRetryableExecutionError as exc:
            return PythonExecutionOutcome(
                status="FAILED",
                usage={"input_tokens": 0, "output_tokens": 0},
                runtime_provenance=provenance,
                tool_events=_normalize_tool_events(exc.tool_events),
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
            tool_events=_normalize_tool_events(result.tool_events),
        )

    def probe(self, request: dict[str, Any]) -> dict[str, Any]:
        resolved = self._bindings.resolve(
            str(request["model_connection"]["revision_id"]),
            str(request["model_connection"]["config_hash"]),
        )
        if not self._fake_provider_mode:
            client = RemoteMcpClaudeCodeAgentClient(
                limits=self._limits,
                api_key=resolved.api_key,
                mcp_server_url=self._mcp_server_url,
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
    ) -> PythonExecutionOutcome:
        question = str(request["prompt"]["user_question"])
        if "[smoke:restart-slow]" in question:
            cancel_event.wait(timeout=30)
        elif "[smoke:slow]" in question:
            cancel_event.wait(timeout=5)
        if cancel_event.is_set():
            return self._cancelled(provenance)
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

    def _provenance(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "runtime_kind": PYTHON_RUNTIME_KIND,
            "runtime_version": PYTHON_RUNTIME_VERSION,
            "protocol_version": PROTOCOL_VERSION,
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


def _fixed_mcp_server_url(raw: str) -> str:
    parsed = urlsplit(raw.strip())
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or host not in {"tool-mcp", "localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/mcp"
    ):
        raise ValueError("MCP Tool Server URL is outside the fixed deployment boundary")
    return raw.strip().rstrip("/")


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
        runtime_protocol_version=PROTOCOL_VERSION,
    )
    return AgentRunRequest(
        job_id=str(request["job_id"]),
        user_id=str(request["app_user_id"]),
        project_code=str(request["project_code"]),
        context=context,
        invocation_id=str(request["invocation_id"]),
    )


def _normalize_tool_events(events: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    normalized: list[dict[str, Any]] = []
    for index, event in enumerate(events[:128], start=1):
        raw_status = str(event.get("status") or "FAILED").upper()
        status = {
            "REJECTED": "DENIED",
            "STARTED": "STARTED",
            "SUCCEEDED": "SUCCEEDED",
            "FAILED": "FAILED",
        }.get(raw_status, "FAILED")
        item: dict[str, Any] = {
            "tool_call_id": str(event.get("tool_call_id") or f"python-tool-{index}"),
            "server_code": "tool-mcp",
            "tool_name": str(event.get("tool_name") or "unknown_tool"),
            "status": status,
            "request_summary": {"available": bool(event.get("request_payload"))},
            "response_summary": {"available": bool(event.get("response_summary"))},
            "duration_ms": max(0, int(event.get("duration_ms") or 0)),
        }
        if status in {"FAILED", "DENIED"}:
            item["failure"] = {
                "code": str(event.get("error_code") or "runtime_tool_failed"),
                "retry_class": "NEVER" if status == "DENIED" else "TRANSIENT",
                "safe_message": "工具调用未获授权" if status == "DENIED" else "工具调用失败",
            }
        normalized.append(item)
    return tuple(normalized)
