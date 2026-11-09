from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.modules.agent.infrastructure.runtime_readiness import AgentRuntimeReadinessGuard
from app.modules.agent_config.application import AgentConfigService
from app.modules.permission.application.permission_service import PermissionService
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied


@dataclass(frozen=True)
class AgentBinding:
    definition_id: str = ""
    publication_id: str = ""
    revision: int = 0
    config_hash: str = ""
    runtime_kind: str = "python-v1"
    runtime_protocol_version: str = "1.5"
    snapshot: dict[str, Any] = field(default_factory=dict)
    model_runtime_provenance: dict[str, Any] = field(
        default_factory=lambda: {"legacy": True, "runtime": "claude_agent_sdk"}
    )


def bind_agent_publication(
    *,
    agent_config_service: AgentConfigService | None,
    permission_service: PermissionService,
    database: Database,
    runtime_readiness_guard: AgentRuntimeReadinessGuard | None,
    agent_code: str,
    requester_id: str,
    agent_permission_required: bool,
    fixed_publication_id: str,
    fixed_revision: int | None,
    fixed_config_hash: str,
    business_application_job: bool,
    source_channel: str,
    source_connector_id: str,
    reply_route: dict[str, Any],
) -> AgentBinding:
    if agent_config_service is None:
        raise NonRetryableExecutionError(
            "Published Agent runtime service is unavailable",
            safe_message="Agent 配置不可用",
        )
    if agent_permission_required:
        permission_service.require_action(
            user_id=requester_id,
            resource_type="agent",
            resource_code=agent_code,
            action="use",
        )
    definition = agent_config_service.repository.get_definition(agent_code)
    publication = (
        agent_config_service.publication(fixed_publication_id)
        if fixed_publication_id
        else agent_config_service.current_publication(agent_code)
    )
    _require_pinned_publication(
        definition=definition,
        publication=publication,
        fixed_revision=fixed_revision,
        fixed_config_hash=fixed_config_hash,
    )
    publication_id = str(publication["id"])
    if not business_application_job and database.execute_one(
        "select tool_identifier from agent_publication_mcp_tool "
        "where agent_publication_id=? and "
        "(server_code='knowledge-mcp' or tool_identifier in "
        "('knowledge_list_bases','knowledge_search')) limit 1",
        (publication_id,),
    ):
        raise PermissionDenied(
            "Knowledge tools require a Business Application Job",
            safe_message="知识库工具仅允许通过已授权的业务应用使用",
            error_code="knowledge_business_application_required",
        )
    revision = int(publication["revision"])
    config_hash = str(publication["config_hash"])
    runtime_kind, snapshot = _require_supported_runtime(publication)
    if runtime_readiness_guard is not None:
        runtime_readiness_guard.require_ready(runtime_kind)
    model_runtime_provenance = _model_runtime_provenance(snapshot)
    _require_connectors_assigned(
        agent_config_service,
        publication_id=publication_id,
        source_channel=source_channel,
        source_connector_id=source_connector_id,
        reply_route=reply_route,
    )
    return AgentBinding(
        definition_id=str(definition["id"]),
        publication_id=publication_id,
        revision=revision,
        config_hash=config_hash,
        runtime_kind=runtime_kind,
        runtime_protocol_version="1.5",
        snapshot=snapshot,
        model_runtime_provenance=model_runtime_provenance,
    )


def _require_pinned_publication(
    *,
    definition: dict[str, Any],
    publication: dict[str, Any],
    fixed_revision: int | None,
    fixed_config_hash: str,
) -> None:
    if str(publication["agent_id"]) != str(definition["id"]):
        raise NonRetryableExecutionError(
            "Pinned Agent publication belongs to another Agent",
            safe_message="固定的 Agent 配置无效",
        )
    if fixed_revision is not None and int(publication["revision"]) != int(fixed_revision):
        raise NonRetryableExecutionError(
            "Pinned Agent revision mismatch",
            safe_message="固定的 Agent 配置完整性校验失败",
        )
    if fixed_config_hash and str(publication["config_hash"]) != fixed_config_hash:
        raise NonRetryableExecutionError(
            "Pinned Agent hash mismatch",
            safe_message="固定的 Agent 配置完整性校验失败",
        )


def _require_supported_runtime(publication: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    runtime_kind = str(publication.get("runtime_kind") or "")
    if runtime_kind != "python-v1":
        raise NonRetryableExecutionError(
            "Pinned Agent publication runtime is unsupported",
            safe_message="固定的 Agent Runtime 配置无效",
            error_code="agent_runtime_kind_unsupported",
        )
    snapshot = dict(publication.get("snapshot") or {})
    supported_protocols = tuple(
        str(item) for item in snapshot.get("supported_runtime_protocol_versions", [])
    )
    if supported_protocols != ("1.5",):
        raise NonRetryableExecutionError(
            "Pinned Agent publication does not support the required Runtime protocol",
            safe_message="固定的 Agent 发布版本不支持文件策略所需 Runtime 协议",
            error_code="agent_runtime_protocol_unsupported",
        )
    return runtime_kind, snapshot


def _model_runtime_provenance(snapshot: dict[str, Any]) -> dict[str, Any]:
    model_connection = snapshot.get("model_connection") or {}
    model_config = model_connection.get("config") or {}
    if not model_connection:
        return {
            "legacy": True,
            "runtime": "claude_agent_sdk",
            "model": str((snapshot.get("model_policy") or {}).get("model") or ""),
        }
    return {
        "legacy": False,
        "runtime": "claude_agent_sdk",
        "connection_id": str(model_connection.get("id") or ""),
        "connection_code": str(model_connection.get("code") or ""),
        "connection_revision_id": str(model_connection.get("revision_id") or ""),
        "connection_revision": int(model_connection.get("revision") or 0),
        "config_hash": str(model_connection.get("config_hash") or ""),
        "provider_host": _provider_host(str(model_config.get("base_url") or "")),
        "model": str(model_config.get("model") or ""),
        "effort_level": str(model_config.get("effort_level") or ""),
    }


def _require_connectors_assigned(
    agent_config_service: AgentConfigService,
    *,
    publication_id: str,
    source_channel: str,
    source_connector_id: str,
    reply_route: dict[str, Any],
) -> None:
    if (
        source_channel != "debug_api"
        and source_connector_id
        and not agent_config_service.connector_allowed(
            publication_id=publication_id,
            direction="ingress",
            connector_id=source_connector_id,
        )
    ):
        raise NonRetryableExecutionError(
            "Source connector is not assigned to the Agent publication",
            safe_message="此渠道无法使用该 Agent",
        )
    delivery_connector_id = str(reply_route.get("connector_id") or "")
    if (
        reply_route.get("type") != "none"
        and delivery_connector_id
        and not agent_config_service.connector_allowed(
            publication_id=publication_id,
            direction="delivery",
            connector_id=delivery_connector_id,
        )
    ):
        raise NonRetryableExecutionError(
            "Delivery connector is not assigned to the Agent publication",
            safe_message="此渠道尚未配置 Agent 结果投递",
        )


def _provider_host(base_url: str) -> str:
    try:
        return (urlsplit(base_url).hostname or "invalid").lower()[:255]
    except ValueError:
        return "invalid"
