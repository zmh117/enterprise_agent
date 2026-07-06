from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.shared.database import Database
from app.shared.exceptions import NotFound


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class WorkflowRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_template(
        self,
        *,
        code: str,
        name: str,
        description: str = "",
        project_code: str = "default",
        status: str = "draft",
        entry_node_key: str = "",
        graph_schema_version: int = 1,
        graph: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
        created_by: str = "",
    ) -> dict[str, Any]:
        existing = self.get_template_by_code(code)
        timestamp = now_iso()
        if existing:
            self.database.execute(
                """
                update agent_workflow_template
                set name = ?, description = ?, project_code = ?, status = ?,
                    entry_node_key = ?, graph_schema_version = ?, graph_json = ?,
                    settings_json = ?, updated_at = ?
                where id = ?
                """,
                (
                    name,
                    description,
                    project_code,
                    status,
                    entry_node_key,
                    graph_schema_version,
                    json_text(graph or {}),
                    json_text(settings or {}),
                    timestamp,
                    existing["id"],
                ),
            )
            return self.get_template(existing["id"])
        template_id = new_id("workflow")
        self.database.execute(
            """
            insert into agent_workflow_template
              (id, code, name, description, project_code, status, version,
               entry_node_key, graph_schema_version, graph_json, settings_json,
               created_by, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template_id,
                code,
                name,
                description,
                project_code,
                status,
                1,
                entry_node_key,
                graph_schema_version,
                json_text(graph or {}),
                json_text(settings or {}),
                created_by,
                timestamp,
                timestamp,
            ),
        )
        return self.get_template(template_id)

    def list_templates(
        self, *, project_code: str | None = None, include_disabled: bool = True
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_code:
            clauses.append("project_code = ?")
            params.append(project_code)
        if not include_disabled:
            clauses.append("status != 'disabled'")
        where = f"where {' and '.join(clauses)}" if clauses else ""
        rows = self.database.execute(
            f"select * from agent_workflow_template {where} order by project_code, code",
            params,
        )
        return [self._parse_template(row) for row in rows]

    def get_template(self, template_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from agent_workflow_template where id = ?", (template_id,)
        )
        if not row:
            raise NotFound(f"Agent workflow template not found: {template_id}")
        return self._parse_template(row)

    def get_template_by_code(self, code: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            "select * from agent_workflow_template where code = ?", (code,)
        )
        return self._parse_template(row) if row else None

    def set_template_status(self, code: str, status: str) -> dict[str, Any]:
        existing = self.get_template_by_code(code)
        if not existing:
            raise NotFound(f"Agent workflow template not found: {code}")
        self.database.execute(
            "update agent_workflow_template set status = ?, updated_at = ? where id = ?",
            (status, now_iso(), existing["id"]),
        )
        return self.get_template(existing["id"])

    def upsert_node(
        self,
        *,
        template_code: str,
        node_key: str,
        node_type: str,
        title: str = "",
        position: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        ui: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        template = self._require_template(template_code)
        existing = self.get_node_by_key(template_id=str(template["id"]), node_key=node_key)
        timestamp = now_iso()
        if existing:
            self.database.execute(
                """
                update agent_workflow_node
                set node_type = ?, title = ?, position_json = ?, config_json = ?,
                    ui_json = ?, updated_at = ?
                where id = ?
                """,
                (
                    node_type,
                    title,
                    json_text(position or {}),
                    json_text(config or {}),
                    json_text(ui or {}),
                    timestamp,
                    existing["id"],
                ),
            )
            return self.get_node(existing["id"])
        node_id = new_id("wf_node")
        self.database.execute(
            """
            insert into agent_workflow_node
              (id, template_id, node_key, node_type, title, position_json,
               config_json, ui_json, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id,
                template["id"],
                node_key,
                node_type,
                title,
                json_text(position or {}),
                json_text(config or {}),
                json_text(ui or {}),
                timestamp,
                timestamp,
            ),
        )
        return self.get_node(node_id)

    def list_nodes(self, template_code: str) -> list[dict[str, Any]]:
        template = self._require_template(template_code)
        rows = self.database.execute(
            """
            select * from agent_workflow_node
            where template_id = ?
            order by node_key
            """,
            (template["id"],),
        )
        return [self._parse_node(row) for row in rows]

    def get_node(self, node_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from agent_workflow_node where id = ?", (node_id,)
        )
        if not row:
            raise NotFound(f"Agent workflow node not found: {node_id}")
        return self._parse_node(row)

    def get_node_by_key(self, *, template_id: str, node_key: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from agent_workflow_node
            where template_id = ? and node_key = ?
            """,
            (template_id, node_key),
        )
        return self._parse_node(row) if row else None

    def upsert_edge(
        self,
        *,
        template_code: str,
        edge_key: str,
        source_node_key: str,
        target_node_key: str,
        source_port: str = "",
        target_port: str = "",
        condition: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        template = self._require_template(template_code)
        existing = self.get_edge_by_key(template_id=str(template["id"]), edge_key=edge_key)
        timestamp = now_iso()
        if existing:
            self.database.execute(
                """
                update agent_workflow_edge
                set source_node_key = ?, target_node_key = ?, source_port = ?,
                    target_port = ?, condition_json = ?, updated_at = ?
                where id = ?
                """,
                (
                    source_node_key,
                    target_node_key,
                    source_port,
                    target_port,
                    json_text(condition or {}),
                    timestamp,
                    existing["id"],
                ),
            )
            return self.get_edge(existing["id"])
        edge_id = new_id("wf_edge")
        self.database.execute(
            """
            insert into agent_workflow_edge
              (id, template_id, edge_key, source_node_key, target_node_key,
               source_port, target_port, condition_json, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                template["id"],
                edge_key,
                source_node_key,
                target_node_key,
                source_port,
                target_port,
                json_text(condition or {}),
                timestamp,
                timestamp,
            ),
        )
        return self.get_edge(edge_id)

    def list_edges(self, template_code: str) -> list[dict[str, Any]]:
        template = self._require_template(template_code)
        rows = self.database.execute(
            """
            select * from agent_workflow_edge
            where template_id = ?
            order by edge_key
            """,
            (template["id"],),
        )
        return [self._parse_edge(row) for row in rows]

    def get_edge(self, edge_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from agent_workflow_edge where id = ?", (edge_id,)
        )
        if not row:
            raise NotFound(f"Agent workflow edge not found: {edge_id}")
        return self._parse_edge(row)

    def get_edge_by_key(self, *, template_id: str, edge_key: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from agent_workflow_edge
            where template_id = ? and edge_key = ?
            """,
            (template_id, edge_key),
        )
        return self._parse_edge(row) if row else None

    def create_publication(
        self,
        *,
        template_id: str,
        version: int,
        graph_snapshot: dict[str, Any],
        config_hash: str,
        published_by: str,
    ) -> dict[str, Any]:
        publication_id = new_id("wf_pub")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into agent_workflow_publication
              (id, template_id, version, graph_snapshot_json, config_hash,
               published_by, published_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                publication_id,
                template_id,
                version,
                json_text(graph_snapshot),
                config_hash,
                published_by,
                timestamp,
            ),
        )
        self.database.execute(
            """
            update agent_workflow_template
            set status = 'published', version = ?, updated_at = ?
            where id = ?
            """,
            (version, timestamp, template_id),
        )
        return self.get_publication(publication_id)

    def get_publication(self, publication_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from agent_workflow_publication where id = ?", (publication_id,)
        )
        if not row:
            raise NotFound(f"Agent workflow publication not found: {publication_id}")
        return self._parse_publication(row)

    def latest_publication(self, template_code: str) -> dict[str, Any] | None:
        template = self._require_template(template_code)
        row = self.database.execute_one(
            """
            select * from agent_workflow_publication
            where template_id = ?
            order by version desc
            limit 1
            """,
            (template["id"],),
        )
        return self._parse_publication(row) if row else None

    def _require_template(self, code: str) -> dict[str, Any]:
        template = self.get_template_by_code(code)
        if not template:
            raise NotFound(f"Agent workflow template not found: {code}")
        return template

    def _parse_template(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "version": int(row.get("version") or 0),
            "graph_schema_version": int(row.get("graph_schema_version") or 1),
            "graph": self._json_from_text(row.get("graph_json") or "{}"),
            "settings": self._json_from_text(row.get("settings_json") or "{}"),
        }

    def _parse_node(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "position": self._json_from_text(row.get("position_json") or "{}"),
            "config": self._json_from_text(row.get("config_json") or "{}"),
            "ui": self._json_from_text(row.get("ui_json") or "{}"),
        }

    def _parse_edge(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "condition": self._json_from_text(row.get("condition_json") or "{}"),
        }

    def _parse_publication(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "version": int(row.get("version") or 0),
            "graph_snapshot": self._json_from_text(row.get("graph_snapshot_json") or "{}"),
        }

    def _json_from_text(self, value: str) -> Any:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
