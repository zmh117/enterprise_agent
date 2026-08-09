from __future__ import annotations

from dataclasses import dataclass

from app.shared.config import AgentRuntimeSettings
from app.shared.exceptions import NonRetryableExecutionError

PYTHON_RUNTIME = "python-v1"
TYPESCRIPT_RUNTIME = "typescript-v1"
RUNTIME_PROTOCOL_V1 = "1.0"


@dataclass(frozen=True, slots=True)
class FrozenRuntimeSelection:
    runtime_kind: str
    protocol_version: str


class RuntimeMigrationGate:
    """Deployment-owned migration gate; its decision is frozen into each Job."""

    def __init__(self, settings: AgentRuntimeSettings) -> None:
        self._typescript_environments = frozenset(
            value.strip().lower() for value in settings.typescript_environments if value.strip()
        )
        self._typescript_publications = frozenset(
            value.strip()
            for value in settings.typescript_application_publication_ids
            if value.strip()
        )

    def select(
        self,
        *,
        environment: str,
        application_publication_id: str,
    ) -> FrozenRuntimeSelection:
        normalized_environment = environment.strip().lower()
        publication_id = application_publication_id.strip()
        use_typescript = bool(publication_id) and (
            publication_id in self._typescript_publications
            or normalized_environment in self._typescript_environments
        )
        return FrozenRuntimeSelection(
            runtime_kind=TYPESCRIPT_RUNTIME if use_typescript else PYTHON_RUNTIME,
            protocol_version=RUNTIME_PROTOCOL_V1,
        )


def validate_frozen_runtime(runtime_kind: str, protocol_version: str) -> None:
    if runtime_kind not in {PYTHON_RUNTIME, TYPESCRIPT_RUNTIME}:
        raise NonRetryableExecutionError(
            "Job contains an unsupported Agent Runtime kind",
            safe_message="Job 固定的 Agent Runtime 不受支持",
            error_code="agent_runtime_kind_unsupported",
        )
    if protocol_version != RUNTIME_PROTOCOL_V1:
        raise NonRetryableExecutionError(
            "Job contains an unsupported Agent Runtime protocol",
            safe_message="Job 固定的 Agent Runtime 协议不受支持",
            error_code="agent_runtime_protocol_unsupported",
        )
