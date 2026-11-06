from __future__ import annotations

from typing import Any

from app.modules.agent_config.infrastructure import AgentConfigRepository
from app.modules.business_application.application.ports import ComponentReference
from app.modules.business_application.domain.policies import snapshot_hash
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.workflow.infrastructure import WorkflowRepository
from app.shared.exceptions import AppError, NonRetryableExecutionError, NotFound


class AgentPublicationAdapter:
    def __init__(self, repository: AgentConfigRepository) -> None:
        self.repository = repository

    def resolve(self, publication_id: str) -> ComponentReference:
        publication = self.repository.get_publication(publication_id)
        definition = self.repository.get_definition_by_id(str(publication["agent_id"]))
        schema_version = int(publication.get("schema_version") or 0)
        runtime_kind = str(publication.get("runtime_kind") or "")
        definition_runtime_kind = str(definition.get("runtime_kind") or "")
        snapshot = publication.get("snapshot") or {}
        integrity_valid = (
            schema_version == 3
            and runtime_kind == "python-v1"
            and definition_runtime_kind == runtime_kind
            and snapshot_hash(snapshot) == str(publication.get("config_hash") or "")
            and snapshot.get("runtime_kind") == runtime_kind
            and snapshot.get("supported_runtime_protocol_versions") == ["1.5"]
        )
        if not integrity_valid:
            raise NonRetryableExecutionError(
                "Agent publication integrity verification failed",
                safe_message="Agent 发布版本完整性校验失败",
                error_code="agent_publication_integrity_error",
            )
        return ComponentReference(
            id=str(publication["id"]),
            code=str(definition["code"]),
            revision=int(publication["revision"]),
            project_code=str(definition["project_code"]),
            status=(
                "enabled"
                if str(definition["status"]) == "enabled" and str(publication["status"]) == "active"
                else "disabled"
            ),
            config_hash=str(publication["config_hash"]),
            runtime_kind=runtime_kind,
            ingress_connector_ids=tuple(
                sorted(self.repository.publication_connectors(publication_id, "ingress"))
            ),
            runtime_protocol_versions=("1.5",),
            component_type="agent_publication",
        )

    def catalog(self) -> list[ComponentReference]:
        values: list[ComponentReference] = []
        for definition in self.repository.list_definitions(include_disabled=False):
            publication_id = str(definition.get("current_publication_id") or "")
            if not publication_id:
                continue
            publication = self.resolve(publication_id)
            if publication.status == "enabled":
                values.append(publication)
        return values


class WorkflowPublicationAdapter:
    def __init__(self, repository: WorkflowRepository) -> None:
        self.repository = repository

    def resolve(self, publication_id: str) -> ComponentReference:
        publication = self.repository.get_publication(publication_id)
        template = self.repository.get_template(str(publication["template_id"]))
        return ComponentReference(
            id=str(publication["id"]),
            code=str(template["code"]),
            revision=int(publication["version"]),
            project_code=str(template["project_code"]),
            status="enabled" if str(template["status"]) == "published" else "disabled",
            config_hash=str(publication["config_hash"]),
            component_type="workflow_publication",
        )

    def catalog(self, project_code: str) -> list[ComponentReference]:
        values: list[ComponentReference] = []
        for template in self.repository.list_templates(
            project_code=project_code, include_disabled=False
        ):
            publication = self.repository.latest_publication(str(template["code"]))
            if publication:
                values.append(self.resolve(str(publication["id"])))
        return values


class ChannelConnectorAdapter:
    def __init__(self, registry: ConnectorRegistry) -> None:
        self.registry = registry

    def resolve(
        self, connector_id: str, direction: str, trigger_type: str = ""
    ) -> ComponentReference:
        connector = self.registry.get(connector_id)
        if connector is None:
            raise NotFound(
                f"Channel connector not found: {connector_id}",
                safe_message="未找到渠道连接器",
            )
        allowed = connector.allow_ingress if direction == "ingress" else connector.allow_delivery
        if direction == "ingress" and trigger_type in {
            "dingtalk_private",
            "dingtalk_group",
        }:
            allowed = allowed and connector.connector_type == "dingtalk_enterprise_stream"
            capability = (
                "allow_private_chat" if trigger_type == "dingtalk_private" else "allow_group_chat"
            )
            allowed = allowed and bool(connector.metadata.get(capability, True))
        elif direction == "ingress" and trigger_type == "webhook":
            allowed = allowed and connector.connector_type != "dingtalk_enterprise_stream"
        if direction == "delivery" and trigger_type == "dingtalk_private":
            self.registry.require_dingtalk_robot_delivery(connector_id)
            allowed = True
        if direction == "delivery" and trigger_type in {"webhook_callback", "dingtalk_group"}:
            expected = (
                "webhook" if trigger_type == "webhook_callback" else "dingtalk_enterprise_robot"
            )
            allowed = allowed and connector.connector_type == expected
        if direction == "ingress" and trigger_type == "reply_original":
            allowed = allowed and connector.connector_type == "dingtalk_enterprise_stream"
        row = self.registry.repository.get_connector(connector_id) or {}
        return ComponentReference(
            id=connector.id,
            code=connector.name,
            revision=int(row.get("revision", 1)),
            project_code="",
            status="enabled" if connector.enabled and allowed else "disabled",
            config_hash="",
            direction=direction,
            component_type=connector.connector_type,
        )

    def webhook_trigger(self, connector_id: str) -> dict[str, Any]:
        rows = self.registry.repository.database.execute(
            """select d.id, d.service_account_id from webhook_trigger_definition d
                 join webhook_trigger_publication p on p.id=d.current_publication_id
                where d.connector_id=? and d.status='enabled'
                  and p.status='active' and p.schema_version=2""",
            (connector_id,),
        )
        if len(rows) != 1:
            raise NonRetryableExecutionError(
                "Webhook is not enabled and published",
                safe_message="请选择已发布并启用的 Webhook",
                error_code="validation_failed",
            )
        row = rows[0]
        return {
            "trigger_type": "webhook",
            "connector_id": connector_id,
            "routing_key": f"webhook:{row['id']}",
            "actor_policy": "SERVICE_ACCOUNT",
            "service_account_user_id": str(row["service_account_id"]),
            "config": {"webhook_definition_id": str(row["id"])},
        }

    def catalog(self) -> list[ComponentReference]:
        rows = self.registry.repository.database.execute(
            """
            select id from integration_connector
             where enabled = 1 and deleted = 0 order by name, id
            """
        )
        result: list[ComponentReference] = []
        for row in rows:
            connector = self.registry.get(str(row["id"]))
            if connector is None:
                continue
            if connector.allow_ingress:
                result.append(self.resolve(connector.id, "ingress"))
            if connector.allow_delivery:
                result.append(self.resolve(connector.id, "delivery"))
            elif connector.connector_type == "dingtalk_enterprise_stream":
                try:
                    result.append(self.resolve(connector.id, "delivery", "dingtalk_private"))
                except AppError:
                    pass
        return result


class IdentitySubjectAdapter:
    def __init__(self, repository: IdentityRepository) -> None:
        self.repository = repository

    def resolve_service_account(self, user_id: str) -> ComponentReference:
        user = self.repository.get_user(user_id)
        status = (
            "enabled"
            if str(user["status"]) == "enabled" and str(user["account_type"]) == "service"
            else "disabled"
        )
        return ComponentReference(
            id=str(user["id"]),
            code=str(user["username"]),
            revision=int(user["revision"]),
            project_code="",
            status=status,
            config_hash="",
            component_type="service_account",
        )
