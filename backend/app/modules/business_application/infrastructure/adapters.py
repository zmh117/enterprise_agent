from __future__ import annotations

from app.modules.agent_config.infrastructure import AgentConfigRepository
from app.modules.business_application.application.ports import ComponentReference
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.internal_tools.domain import (
    build_builtin_handler_registry,
)
from app.modules.job.infrastructure.repositories import ConfigurationRepository
from app.modules.workflow.infrastructure import WorkflowRepository
from app.shared.exceptions import NonRetryableExecutionError, NotFound


class AgentPublicationAdapter:
    def __init__(self, repository: AgentConfigRepository) -> None:
        self.repository = repository

    def resolve(self, publication_id: str) -> ComponentReference:
        publication = self.repository.get_publication(publication_id)
        definition = self.repository.get_definition_by_id(str(publication["agent_id"]))
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
            component_type="agent_publication",
        )

    def catalog(self, project_code: str) -> list[ComponentReference]:
        values: list[ComponentReference] = []
        for definition in self.repository.list_definitions(include_disabled=False):
            if str(definition["project_code"]) != project_code:
                continue
            for publication in self.repository.list_publications(str(definition["id"])):
                if str(publication["status"]) == "active":
                    values.append(self.resolve(str(publication["id"])))
        return values

    def allows_capability(self, publication_id: str, capability_code: str) -> bool:
        return capability_code in self.repository.publication_tools(publication_id)


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


class EmptyCapabilityCatalogAdapter:
    @property
    def connected(self) -> bool:
        return False

    def catalog(self) -> list[ComponentReference]:
        return []

    def resolve(self, code: str, version_constraint: str, environment: str) -> ComponentReference:
        del version_constraint, environment
        raise NonRetryableExecutionError(
            f"Capability Catalog is not connected: {code}",
            safe_message="API 能力目录尚未连接",
            error_code="capability_catalog_unavailable",
            field_errors=[
                {
                    "field": "capabilities",
                    "message": f"暂时无法解析能力 {code}",
                }
            ],
        )


class ToolCapabilityCatalogAdapter:
    """Expose enabled read-only runtime tools as business capability codes."""

    def __init__(self, repository: ConfigurationRepository) -> None:
        self.repository = repository
        self.application_handler_codes = {
            definition.handler_id
            for definition in (
                build_builtin_handler_registry().application_catalog()
            )
        }

    @property
    def connected(self) -> bool:
        return True

    def catalog(self) -> list[ComponentReference]:
        result: list[ComponentReference] = []
        for tool in sorted(self.repository.enabled_tools(), key=lambda item: str(item["name"])):
            if (
                not bool(int(tool["read_only"]))
                or str(tool["name"])
                not in self.application_handler_codes
            ):
                continue
            result.append(self._reference(tool))
        return result

    def resolve(self, code: str, version_constraint: str, environment: str) -> ComponentReference:
        del version_constraint, environment
        tool = self.repository.get_tool(code)
        if tool is None:
            raise NonRetryableExecutionError(
                f"Capability is not registered: {code}",
                safe_message="所选业务能力不存在",
                error_code="capability_not_found",
                field_errors=[
                    {
                        "field": "capabilities",
                        "message": f"业务能力不存在：{code}",
                    }
                ],
            )
        enabled = bool(int(tool["enabled"])) and bool(int(tool["read_only"]))
        if not enabled:
            raise NonRetryableExecutionError(
                f"Capability is not enabled and read-only: {code}",
                safe_message="角色只能选择已启用的只读业务能力",
                error_code="capability_not_readonly",
                field_errors=[
                    {
                        "field": "capabilities",
                        "message": f"业务能力不可授权：{code}",
                    }
                ],
            )
        return self._reference(tool)

    @staticmethod
    def _reference(tool: dict[str, object]) -> ComponentReference:
        return ComponentReference(
            id=str(tool["id"]),
            code=str(tool["name"]),
            revision=1,
            project_code="",
            status="enabled",
            config_hash="",
            component_type="readonly_tool_capability",
        )
