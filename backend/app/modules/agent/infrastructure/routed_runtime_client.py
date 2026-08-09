from __future__ import annotations

from app.modules.agent.application.runtime_migration_gate import (
    PYTHON_RUNTIME,
    RUNTIME_PROTOCOL_V1,
    TYPESCRIPT_RUNTIME,
    validate_frozen_runtime,
)
from app.modules.agent.domain.runtime import AgentRunRequest, AgentRunResult
from app.modules.agent.infrastructure.claude_code_agent_client import ClaudeCodeAgentClient
from app.shared.exceptions import NonRetryableExecutionError


class RoutedAgentRuntimeClient:
    """Route once from immutable Job facts; never fail over between runtimes."""

    def __init__(
        self,
        *,
        python_client: ClaudeCodeAgentClient,
        typescript_client: ClaudeCodeAgentClient | None,
    ) -> None:
        self.python_client = python_client
        self.typescript_client = typescript_client

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        runtime_kind = request.context.runtime_kind
        protocol_version = request.context.runtime_protocol_version
        validate_frozen_runtime(runtime_kind, protocol_version)
        if protocol_version != RUNTIME_PROTOCOL_V1:
            raise NonRetryableExecutionError(
                "Agent Runtime protocol is not supported by this Worker",
                safe_message="Agent Runtime 协议不受支持",
                error_code="agent_runtime_protocol_unsupported",
            )
        if runtime_kind == PYTHON_RUNTIME:
            return self.python_client.run(request)
        if runtime_kind == TYPESCRIPT_RUNTIME:
            if self.typescript_client is None:
                raise NonRetryableExecutionError(
                    "TypeScript Agent Runtime is selected but not configured",
                    safe_message="TypeScript Agent Runtime 尚未配置",
                    error_code="typescript_runtime_unconfigured",
                )
            return self.typescript_client.run(request)
        raise AssertionError("validated runtime kind was not routed")

    def cancel(self, request: AgentRunRequest, reason: str) -> dict[str, object]:
        runtime_kind = request.context.runtime_kind
        protocol_version = request.context.runtime_protocol_version
        validate_frozen_runtime(runtime_kind, protocol_version)
        if protocol_version != RUNTIME_PROTOCOL_V1:
            raise NonRetryableExecutionError(
                "Agent Runtime protocol is not supported by this Worker",
                safe_message="Agent Runtime 协议不受支持",
                error_code="agent_runtime_protocol_unsupported",
            )
        if runtime_kind == PYTHON_RUNTIME:
            raise NonRetryableExecutionError(
                "The legacy Python Runtime cannot accept out-of-band cancellation",
                safe_message="旧 Python Runtime 不支持运行中取消",
                error_code="python_runtime_cancel_unsupported",
            )
        if runtime_kind != TYPESCRIPT_RUNTIME:
            raise AssertionError("validated runtime kind was not routed")
        if self.typescript_client is None:
            raise NonRetryableExecutionError(
                "TypeScript Agent Runtime is selected but not configured",
                safe_message="TypeScript Agent Runtime 尚未配置",
                error_code="typescript_runtime_unconfigured",
            )
        cancel = getattr(self.typescript_client, "cancel", None)
        if not callable(cancel):
            raise NonRetryableExecutionError(
                "TypeScript Agent Runtime client does not implement cancellation",
                safe_message="TypeScript Agent Runtime 取消能力不可用",
                error_code="typescript_runtime_cancel_unavailable",
            )
        result = cancel(request, reason)
        return dict(result) if isinstance(result, dict) else {}
