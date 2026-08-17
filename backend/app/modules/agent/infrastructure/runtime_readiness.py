from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.agent.infrastructure.runtime_http_client import (
    RuntimeClientSettings,
    probe_runtime_readiness,
)
from app.shared.exceptions import NonRetryableExecutionError


class AgentRuntimeReadinessGuard:
    """Fail closed for the selected fixed Runtime without coupling their health."""

    def __init__(self, runtimes: Mapping[str, RuntimeClientSettings]) -> None:
        self._runtimes = dict(runtimes)

    @classmethod
    def from_settings(cls, settings: Any) -> AgentRuntimeReadinessGuard | None:
        retired_keys = tuple(settings.agent_runtime.retired_configuration_keys)
        if retired_keys:
            raise ValueError(
                "retired TypeScript Agent Runtime configuration is present: "
                + ",".join(retired_keys)
            )
        configured: dict[str, RuntimeClientSettings] = {}
        base_url = settings.agent_runtime.python_base_url
        if base_url:
            configured["python-v1"] = RuntimeClientSettings(
                base_url=base_url,
                allowed_runtime_hosts=settings.agent_runtime.python_allowed_hosts,
                runtime_kind="python-v1",
                allow_insecure_internal_http=(settings.agent_runtime.allow_insecure_internal_http),
            )
        return cls(configured) if configured else None

    def status(self, runtime_kind: str) -> dict[str, Any]:
        if runtime_kind == "typescript-v1":
            return {
                "configured": False,
                "ready": False,
                "identity": "retired",
                "error_code": "typescript_agent_runtime_retired",
            }
        runtime = self._runtimes.get(runtime_kind)
        if runtime is None:
            return {
                "configured": False,
                "ready": False,
                "identity": "not_configured",
            }
        return probe_runtime_readiness(runtime)

    def require_ready(self, runtime_kind: str) -> None:
        if runtime_kind == "typescript-v1":
            raise NonRetryableExecutionError(
                "Selected TypeScript Agent Runtime is retired",
                safe_message="所选 TypeScript Agent Runtime 已退役",
                error_code="typescript_agent_runtime_retired",
            )
        status = self.status(runtime_kind)
        if not bool(status.get("ready")):
            raise NonRetryableExecutionError(
                f"Selected Agent Runtime is not ready: {runtime_kind}",
                safe_message="所选 Agent Runtime 当前未就绪",
                error_code="agent_runtime_unavailable",
                field_errors=[
                    {
                        "field": "agent_publication_id",
                        "message": f"{runtime_kind} Runtime 当前未就绪",
                    }
                ],
            )
