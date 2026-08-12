from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.agent_config.application.service import (
    agent_config_hash,
    build_initial_agent_config,
)
from app.modules.agent_config.infrastructure import AgentConfigRepository
from app.modules.audit.application.audit_service import AuditService
from app.shared.exceptions import NonRetryableExecutionError


@dataclass(frozen=True)
class BuiltinAgent:
    id: str
    code: str
    name: str
    description: str
    runtime_kind: str


BUILTIN_AGENTS = (
    BuiltinAgent(
        id="agent_default_diagnostic",
        code="default-diagnostic-agent",
        name="默认诊断 Agent",
        description="Enterprise internal read-only diagnostic Agent",
        runtime_kind="python-v1",
    ),
    BuiltinAgent(
        id="agent_typescript_diagnostic",
        code="typescript-diagnostic-agent",
        name="TypeScript 诊断 Agent",
        description="Enterprise internal read-only diagnostic Agent using TypeScript Runtime",
        runtime_kind="typescript-v1",
    ),
)


class AgentConfigBootstrapper:
    def __init__(
        self,
        repository: AgentConfigRepository,
        audit_service: AuditService,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service

    def ensure_builtin_agents(
        self,
        *,
        model: str,
        actor_id: str = "system-bootstrap",
    ) -> dict[str, Any]:
        created: list[str] = []
        drafts_created: list[str] = []
        preserved: list[str] = []
        with self.repository.database.unit_of_work():
            for builtin in BUILTIN_AGENTS:
                config = build_initial_agent_config(
                    name=builtin.name,
                    project_code="default",
                    model=model,
                )
                definition = self.repository.find_definition(builtin.code)
                if definition is None:
                    try:
                        result = self.repository.create_definition_with_initial_draft(
                            agent_id=builtin.id,
                            code=builtin.code,
                            name=builtin.name,
                            description=builtin.description,
                            project_code="default",
                            runtime_kind=builtin.runtime_kind,
                            classification="internal_diagnostic",
                            config=config,
                            config_hash=agent_config_hash(config),
                            actor_id=actor_id,
                        )
                        definition = result["definition"]
                        created.append(builtin.code)
                        drafts_created.append(builtin.code)
                    except NonRetryableExecutionError as exc:
                        if exc.error_code != "agent_code_conflict":
                            raise
                        definition = self.repository.get_definition(builtin.code)
                if str(definition.get("runtime_kind") or "") != builtin.runtime_kind:
                    raise NonRetryableExecutionError(
                        "Builtin Agent runtime kind does not match its fixed contract",
                        safe_message="固定 Agent Runtime 与平台契约不一致",
                        error_code="agent_runtime_kind_mismatch",
                    )
                if builtin.code not in created:
                    _, draft_created = self.repository.create_initial_draft_if_missing(
                        agent_id=str(definition["id"]),
                        config=config,
                        config_hash=agent_config_hash(config),
                        actor_id=actor_id,
                    )
                    if draft_created:
                        drafts_created.append(builtin.code)
                    else:
                        preserved.append(builtin.code)
            if created or drafts_created:
                self.audit_service.record(
                    "agent.definition.bootstrapped",
                    status="SUCCEEDED",
                    summary="Builtin Agent definitions ensured",
                    actor_id=actor_id,
                    payload={
                        "created_agent_codes": created,
                        "created_draft_codes": drafts_created,
                    },
                )
        return {
            "created": created,
            "drafts_created": drafts_created,
            "preserved": preserved,
        }
