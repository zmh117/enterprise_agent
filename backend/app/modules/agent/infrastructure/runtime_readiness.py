from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.agent.infrastructure.typescript_runtime_client import (
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
        configured: dict[str, RuntimeClientSettings] = {}
        for runtime_kind, base_url, allowed_hosts in (
            (
                "python-v1",
                settings.agent_runtime.python_base_url,
                settings.agent_runtime.python_allowed_hosts,
            ),
            (
                "typescript-v1",
                settings.agent_runtime.typescript_base_url,
                settings.agent_runtime.typescript_allowed_hosts,
            ),
        ):
            if base_url:
                configured[runtime_kind] = RuntimeClientSettings(
                    base_url=base_url,
                    allowed_runtime_hosts=allowed_hosts,
                    runtime_kind=runtime_kind,
                    allow_insecure_internal_http=(
                        settings.agent_runtime.allow_insecure_internal_http
                    ),
                )
        return cls(configured) if configured else None

    def status(self, runtime_kind: str) -> dict[str, Any]:
        runtime = self._runtimes.get(runtime_kind)
        if runtime is None:
            return {
                "configured": False,
                "ready": False,
                "identity": "not_configured",
            }
        return probe_runtime_readiness(runtime)

    def require_ready(self, runtime_kind: str) -> None:
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
