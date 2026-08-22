from __future__ import annotations

from typing import Protocol

from app.modules.agent.domain.runtime import AgentRunRequest, AgentRunResult
from app.shared.exceptions import NonRetryableExecutionError

SUPPORTED_RUNTIME_PROTOCOLS = frozenset({"1.3"})
SUPPORTED_RUNTIME_KIND = "python-v1"


class AgentRuntimeClient(Protocol):
    """Application-owned port for the deployment-fixed Agent Runtime."""

    def run(self, request: AgentRunRequest) -> AgentRunResult: ...

    def cancel(self, request: AgentRunRequest, reason: str) -> dict[str, object]: ...


class GuardedAgentRuntimeClient:
    """Fail closed before delegating to the single configured Python Runtime."""

    def __init__(self, delegate: AgentRuntimeClient | None) -> None:
        self._delegate = delegate

    def _resolve(self, request: AgentRunRequest) -> AgentRuntimeClient:
        runtime_kind = request.context.runtime_kind
        protocol_version = request.context.runtime_protocol_version
        if runtime_kind != SUPPORTED_RUNTIME_KIND:
            raise NonRetryableExecutionError(
                "Job contains an unsupported Agent Runtime kind",
                safe_message="Job 固定的 Agent Runtime 不受支持",
                error_code="agent_runtime_kind_unsupported",
            )
        if protocol_version not in SUPPORTED_RUNTIME_PROTOCOLS:
            raise NonRetryableExecutionError(
                "Job contains an unsupported Agent Runtime protocol",
                safe_message="Job 固定的 Agent Runtime 协议不受支持",
                error_code="agent_runtime_protocol_unsupported",
            )
        if self._delegate is None:
            raise NonRetryableExecutionError(
                f"{runtime_kind} Agent Runtime is not configured",
                safe_message="所选 Agent Runtime 尚未配置",
                error_code="agent_runtime_unconfigured",
            )
        return self._delegate

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        return self._resolve(request).run(request)

    def cancel(self, request: AgentRunRequest, reason: str) -> dict[str, object]:
        cancel = getattr(self._resolve(request), "cancel", None)
        if not callable(cancel):
            raise NonRetryableExecutionError(
                "Selected Agent Runtime client does not implement cancellation",
                safe_message="所选 Agent Runtime 取消能力不可用",
                error_code="agent_runtime_cancel_unavailable",
            )
        result = cancel(request, reason)
        return dict(result) if isinstance(result, dict) else {}
