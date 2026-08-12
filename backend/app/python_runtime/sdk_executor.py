from __future__ import annotations

import importlib.metadata
import os
import threading
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunRequest,
    McpRuntimeBinding,
)
from app.python_runtime.claude_agent_sdk_adapter import (
    RealClaudeCodeAgentClient,
    _append_cli_stderr,
    _build_system_prompt,
)
from app.shared.config import ExecutionSettings
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError

from .model_binding import PythonModelBindingResolver


class InvocationSecretContextPort(Protocol):
    @property
    def principal_token(self) -> str: ...


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
    """Python SDK adapter with two code-owned, deployment-fixed MCP servers."""

    def __init__(
        self,
        *,
        limits: ExecutionSettings,
        api_key: str,
        mcp_server_url: str,
        ones_mcp_server_url: str = "http://ones-mcp:9104/mcp",
        principal_token: str = "",
    ) -> None:
        super().__init__(
            model="",
            tool_registry=None,  # type: ignore[arg-type]
            limits=limits,
            api_key="",
            secret_resolver=lambda _ref: api_key,
        )
        self._mcp_server_url = mcp_server_url
        self._ones_mcp_server_url = ones_mcp_server_url
        self._principal_token = principal_token

    def _build_mcp_server(self, request: AgentRunRequest) -> dict[str, dict[str, Any]]:
        shared_headers = {
            "X-Correlation-Id": f"job:{request.job_id}",
            "X-Job-Id": request.job_id,
            "X-App-User-Id": request.user_id,
            "X-Project-Code": request.project_code,
            "X-Invocation-Id": request.invocation_id,
            "X-Agent-Publication-Id": request.context.publication_id,
            "X-Application-Publication-Id": (request.context.application_publication_id),
        }
        servers: dict[str, dict[str, Any]] = {}
        server_codes = {binding.server_code for binding in request.context.mcp_bindings} or (
            {"tool-mcp"} if request.context.allowed_tools else set()
        )
        if "tool-mcp" in server_codes:
            servers["tool_mcp"] = {
                "type": "http",
                "url": self._mcp_server_url,
                "headers": dict(shared_headers),
            }
        if "ones-mcp" in server_codes:
            if not self._principal_token:
                raise NonRetryableExecutionError(
                    "Python Runtime ONES MCP Principal Token is missing",
                    safe_message="当前调用缺少平台身份凭证",
                    error_code="runtime_principal_token_missing",
                )
            servers["ones_mcp"] = {
                "type": "http",
                "url": self._ones_mcp_server_url,
                "headers": {
                    **shared_headers,
                    "Authorization": f"Bearer {self._principal_token}",
                },
            }
        return servers

    def _build_options(
        self,
        sdk: Any,
        context: AgentExecutionContext,
        server: Any,
        cli_stderr: list[str],
        binding: Any,
    ) -> Any:
        exact_tools = []
        for item in context.mcp_bindings:
            alias = "ones_mcp" if item.server_code == "ones-mcp" else "tool_mcp"
            exact_tools.append(f"mcp__{alias}__{item.tool_name}")
        if not context.mcp_bindings:
            exact_tools = [f"mcp__tool_mcp__{name}" for name in context.allowed_tools]
        return sdk.options(
            model=binding.model,
            system_prompt=_build_system_prompt(context),
            mcp_servers=server,
            allowed_tools=exact_tools,
            disallowed_tools=[
                "Bash",
                "Write",
                "Edit",
                "WebFetch",
                "WebSearch",
                "NotebookEdit",
            ],
            permission_mode="dontAsk",
            max_turns=context.max_turns,
            stderr=lambda line: _append_cli_stderr(
                cli_stderr,
                line,
                self.limits.max_tool_response_chars,
            ),
        )


class PythonRuntimeSdkExecutor:
    def __init__(
        self,
        binding_resolver: PythonModelBindingResolver,
        *,
        limits: ExecutionSettings,
        mcp_server_url: str,
        ones_mcp_server_url: str = "http://ones-mcp:9104/mcp",
        sdk_version: str | None = None,
        cli_version: str | None = None,
        fake_provider_mode: bool = False,
    ) -> None:
        self._bindings = binding_resolver
        self._limits = limits
        self._mcp_server_url = _fixed_mcp_server_url(mcp_server_url)
        self._ones_mcp_server_url = _fixed_mcp_server_url(
            ones_mcp_server_url,
            server_code="ones-mcp",
        )
        self._sdk_version: str = sdk_version or importlib.metadata.version("claude-agent-sdk")
        self._cli_version: str = (
            cli_version or os.getenv("PYTHON_AGENT_RUNTIME_CLI_VERSION", "2.1.226") or "2.1.226"
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
            return self._execute_fake_provider(request, cancel_event, provenance)
        run_request = _agent_request(request, resolved.binding)
        client = RemoteMcpClaudeCodeAgentClient(
            limits=self._limits,
            api_key=resolved.api_key,
            mcp_server_url=self._mcp_server_url,
            ones_mcp_server_url=self._ones_mcp_server_url,
            principal_token=(secret_context.principal_token if secret_context else ""),
        )
        try:
            result = client.run(run_request)
        except RetryableExecutionError as exc:
            return PythonExecutionOutcome(
                status="FAILED",
                usage={"input_tokens": 0, "output_tokens": 0},
                runtime_provenance=provenance,
                tool_events=_normalize_tool_events(exc.tool_events, request),
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
                tool_events=_normalize_tool_events(exc.tool_events, request),
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
            tool_events=_normalize_tool_events(result.tool_events, request),
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
            client = RemoteMcpClaudeCodeAgentClient(
                limits=self._limits,
                api_key=resolved.api_key,
                mcp_server_url=self._mcp_server_url,
                ones_mcp_server_url=self._ones_mcp_server_url,
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


def _fixed_mcp_server_url(raw: str, *, server_code: str = "tool-mcp") -> str:
    parsed = urlsplit(raw.strip())
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or host not in {server_code, "localhost", "127.0.0.1", "::1"}
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


def _normalize_tool_events(
    events: list[dict[str, Any]],
    request: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    published = {
        str(tool["tool_name"]): str(server["server_code"])
        for server in request.get("mcp_servers") or []
        for tool in server.get("tools") or []
    }
    normalized: list[dict[str, Any]] = []
    for index, event in enumerate(events[:128], start=1):
        tool_name = str(event.get("tool_name") or "unknown_tool")
        alias_server = ""
        if tool_name.startswith("mcp__"):
            parts = tool_name.split("__", 2)
            if len(parts) == 3:
                alias_server = {
                    "tool_mcp": "tool-mcp",
                    "ones_mcp": "ones-mcp",
                }.get(parts[1], "")
                tool_name = parts[2]
        server_code = published.get(tool_name, alias_server or "tool-mcp")
        raw_status = str(event.get("status") or "FAILED").upper()
        status = {
            "REJECTED": "DENIED",
            "STARTED": "STARTED",
            "SUCCEEDED": "SUCCEEDED",
            "FAILED": "FAILED",
        }.get(raw_status, "FAILED")
        item: dict[str, Any] = {
            "tool_call_id": str(event.get("tool_call_id") or f"python-tool-{index}"),
            "server_code": server_code,
            "tool_name": tool_name,
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
