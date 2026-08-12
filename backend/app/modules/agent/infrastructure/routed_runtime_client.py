from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from app.modules.agent.domain.runtime import AgentRunRequest, AgentRunResult
from app.shared.exceptions import NonRetryableExecutionError

SUPPORTED_RUNTIME_PROTOCOLS = frozenset({"1.0", "1.1", "1.2"})
SUPPORTED_RUNTIME_KINDS = frozenset({"python-v1", "typescript-v1"})


class AgentRuntimeClient(Protocol):
    def run(self, request: AgentRunRequest) -> AgentRunResult: ...

    def cancel(self, request: AgentRunRequest, reason: str) -> dict[str, object]: ...


class RuntimeClientRegistry:
    """Resolve an immutable Job runtime kind to a deployment-owned client.

    Runtime URLs live inside the registered clients. Agent, Application and
    execution request data can select only a supported runtime kind and can
    never provide or override a URL.
    """

    def __init__(self, clients: Mapping[str, AgentRuntimeClient]) -> None:
        unknown = set(clients) - SUPPORTED_RUNTIME_KINDS
        if unknown:
            raise ValueError(f"unsupported Runtime client registrations: {sorted(unknown)}")
        self._clients = dict(clients)

    def _resolve(self, request: AgentRunRequest) -> AgentRuntimeClient:
        runtime_kind = request.context.runtime_kind
        protocol_version = request.context.runtime_protocol_version
        if runtime_kind not in SUPPORTED_RUNTIME_KINDS:
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
        client = self._clients.get(runtime_kind)
        if client is None:
            raise NonRetryableExecutionError(
                f"{runtime_kind} Agent Runtime is not configured",
                safe_message="所选 Agent Runtime 尚未配置",
                error_code="agent_runtime_unconfigured",
            )
        return client

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


# Transitional import compatibility. New assembly code uses RuntimeClientRegistry.
RoutedAgentRuntimeClient = RuntimeClientRegistry
