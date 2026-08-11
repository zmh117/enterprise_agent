from __future__ import annotations

from typing import Any

from app.modules.permission.application.permission_service import PermissionService
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import PermissionDenied

from app.modules.platform_config.application.validation import normalize_json_object, validate_code

from ..infrastructure.repository import WorkflowRepository
from .graph_facts import graph_config_hash, publication_snapshot
from .validation import normalize_node_payload, validate_graph, validate_workflow_status


class WorkflowService:
    def __init__(
        self,
        repository: WorkflowRepository,
        permission_service: PermissionService,
    ) -> None:
        self.repository = repository
        self.permission_service = permission_service

    def require_admin(self, actor_id: str) -> None:
        if not actor_id:
            raise PermissionDenied(
                "Workflow config actor is required",
                safe_message="缺少工作流配置操作人",
            )
        self.permission_service.require_action(
            user_id=actor_id,
            resource_type="platform_config",
            resource_code="*",
            action="manage",
        )

    def list_templates(
        self, *, project_code: str | None = None, include_disabled: bool = True
    ) -> list[dict[str, Any]]:
        return self.repository.list_templates(
            project_code=project_code,
            include_disabled=include_disabled,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def upsert_template(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        self.require_admin(actor_id)
        code = validate_code(str(payload.get("code") or ""))
        entry_node_key = str(payload.get("entry_node_key") or "")
        if entry_node_key:
            validate_code(entry_node_key, field="entry_node_key")
        graph_input = normalize_json_object(payload.get("graph"), field="graph")
        if graph_input:
            from app.modules.platform_config.application.validation import (
                PlatformConfigValidationError,
            )

            raise PlatformConfigValidationError(
                "Workflow graph must be edited through normalized node and edge endpoints",
                safe_message="工作流图必须通过节点和连线接口编辑",
            )
        entity = self.repository.upsert_template(
            code=code,
            name=str(payload.get("name") or code),
            description=str(payload.get("description") or ""),
            project_code=str(payload.get("project_code") or "default"),
            status=validate_workflow_status(str(payload.get("status") or "draft")).value,
            entry_node_key=entry_node_key,
            graph_schema_version=int(payload.get("graph_schema_version") or 1),
            settings=normalize_json_object(payload.get("settings"), field="settings"),
            created_by=actor_id,
        )
        self._validate_template_graph(code)
        return entity

    @operation_unit_of_work(lambda service: service.repository.database)
    def set_template_status(self, code: str, status: str, *, actor_id: str) -> dict[str, Any]:
        self.require_admin(actor_id)
        return self.repository.set_template_status(
            validate_code(code),
            validate_workflow_status(status).value,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def upsert_node(
        self, template_code: str, payload: dict[str, Any], *, actor_id: str
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        node = normalize_node_payload(payload)
        entity = self.repository.upsert_node(template_code=validate_code(template_code), **node)
        self._validate_template_graph(template_code)
        return entity

    def list_nodes(self, template_code: str) -> list[dict[str, Any]]:
        return self.repository.list_nodes(validate_code(template_code))

    @operation_unit_of_work(lambda service: service.repository.database)
    def upsert_edge(
        self, template_code: str, payload: dict[str, Any], *, actor_id: str
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        template_code = validate_code(template_code)
        source_node_key = validate_code(
            str(payload.get("source_node_key") or ""),
            field="source_node_key",
        )
        target_node_key = validate_code(
            str(payload.get("target_node_key") or ""),
            field="target_node_key",
        )
        node_keys = {str(node["node_key"]) for node in self.repository.list_nodes(template_code)}
        if source_node_key not in node_keys or target_node_key not in node_keys:
            from app.modules.platform_config.application.validation import (
                PlatformConfigValidationError,
            )

            raise PlatformConfigValidationError(
                "Workflow edge references a missing node",
                safe_message="工作流连线引用了不存在的节点",
            )
        entity = self.repository.upsert_edge(
            template_code=template_code,
            edge_key=validate_code(str(payload.get("edge_key") or ""), field="edge_key"),
            source_node_key=source_node_key,
            target_node_key=target_node_key,
            source_port=str(payload.get("source_port") or ""),
            target_port=str(payload.get("target_port") or ""),
            condition=normalize_json_object(payload.get("condition"), field="condition"),
        )
        self._validate_template_graph(template_code)
        return entity

    def list_edges(self, template_code: str) -> list[dict[str, Any]]:
        return self.repository.list_edges(validate_code(template_code))

    @operation_unit_of_work(lambda service: service.repository.database)
    def publish(self, template_code: str, *, actor_id: str) -> dict[str, Any]:
        self.require_admin(actor_id)
        template_code = validate_code(template_code)
        draft = self.repository.load_normalized_draft(template_code, lock=True)
        graph = publication_snapshot(
            template=draft["template"],
            nodes=draft["nodes"],
            edges=draft["edges"],
        )
        validate_graph(
            entry_node_key=str(graph["template"].get("entry_node_key") or ""),
            nodes=graph["nodes"],
            edges=graph["edges"],
        )
        template = draft["template"]
        version = self.repository.next_publication_version(str(template["id"]))
        return self.repository.create_publication(
            template_id=str(template["id"]),
            version=version,
            graph_snapshot=graph,
            config_hash=graph_config_hash(graph),
            published_by=actor_id,
            expected_updated_at=str(draft["expected_updated_at"]),
        )

    def latest_publication(self, template_code: str) -> dict[str, Any] | None:
        return self.repository.latest_publication(validate_code(template_code))

    def _validate_template_graph(self, template_code: str) -> None:
        graph = self._graph_snapshot(template_code)
        validate_graph(
            entry_node_key=str(graph["template"].get("entry_node_key") or ""),
            nodes=graph["nodes"],
            edges=graph["edges"],
        )

    def _graph_snapshot(self, template_code: str) -> dict[str, Any]:
        draft = self.repository.load_normalized_draft(validate_code(template_code))
        return publication_snapshot(
            template=draft["template"],
            nodes=draft["nodes"],
            edges=draft["edges"],
        )
