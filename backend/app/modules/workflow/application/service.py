from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.permission.application.permission_service import PermissionService
from app.shared.exceptions import PermissionDenied

from app.modules.platform_config.application.validation import normalize_json_object, validate_code

from ..infrastructure.repository import WorkflowRepository
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
                safe_message="Workflow config actor is required",
            )
        if not self.permission_service.config_repository.is_allowed(
            subject_code=actor_id,
            resource_type="platform_config",
            resource_code="*",
        ):
            raise PermissionDenied(
                f"User {actor_id} is not allowed to manage workflow config",
                safe_message="User is not allowed to manage workflow config",
            )

    def list_templates(
        self, *, project_code: str | None = None, include_disabled: bool = True
    ) -> list[dict[str, Any]]:
        return self.repository.list_templates(
            project_code=project_code,
            include_disabled=include_disabled,
        )

    def upsert_template(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        self.require_admin(actor_id)
        code = validate_code(str(payload.get("code") or ""))
        entry_node_key = str(payload.get("entry_node_key") or "")
        if entry_node_key:
            validate_code(entry_node_key, field="entry_node_key")
        entity = self.repository.upsert_template(
            code=code,
            name=str(payload.get("name") or code),
            description=str(payload.get("description") or ""),
            project_code=str(payload.get("project_code") or "default"),
            status=validate_workflow_status(str(payload.get("status") or "draft")).value,
            entry_node_key=entry_node_key,
            graph_schema_version=int(payload.get("graph_schema_version") or 1),
            graph=normalize_json_object(payload.get("graph"), field="graph"),
            settings=normalize_json_object(payload.get("settings"), field="settings"),
            created_by=actor_id,
        )
        self._validate_template_graph(code)
        return entity

    def set_template_status(self, code: str, status: str, *, actor_id: str) -> dict[str, Any]:
        self.require_admin(actor_id)
        return self.repository.set_template_status(
            validate_code(code),
            validate_workflow_status(status).value,
        )

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
                safe_message="Workflow edge references a missing node",
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

    def publish(self, template_code: str, *, actor_id: str) -> dict[str, Any]:
        self.require_admin(actor_id)
        template_code = validate_code(template_code)
        graph = self._graph_snapshot(template_code)
        validate_graph(
            entry_node_key=str(graph["template"].get("entry_node_key") or ""),
            nodes=graph["nodes"],
            edges=graph["edges"],
        )
        template = graph["template"]
        version = int(template.get("version") or 0) + 1
        encoded = json.dumps(graph, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return self.repository.create_publication(
            template_id=str(template["id"]),
            version=version,
            graph_snapshot=graph,
            config_hash=hashlib.sha256(encoded).hexdigest(),
            published_by=actor_id,
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
        template = self.repository.get_template_by_code(validate_code(template_code))
        if template is None:
            raise ValueError("Workflow template not found")
        return {
            "template": template,
            "nodes": self.repository.list_nodes(template_code),
            "edges": self.repository.list_edges(template_code),
        }
