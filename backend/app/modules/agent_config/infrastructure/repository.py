from __future__ import annotations

import json
from typing import Any

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


class AgentConfigRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_definitions(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where status = 'enabled'"
        return self.database.execute(f"select * from agent_definition {where} order by code")

    def get_definition(self, code: str) -> dict[str, Any]:
        row = self.database.execute_one("select * from agent_definition where code = ?", (code,))
        if not row:
            raise NotFound("Agent not found", safe_message="未找到 Agent")
        return row

    def get_definition_by_id(self, agent_id: str) -> dict[str, Any]:
        row = self.database.execute_one("select * from agent_definition where id = ?", (agent_id,))
        if not row:
            raise NotFound("Agent not found", safe_message="未找到 Agent")
        return row

    def create_definition(
        self,
        *,
        code: str,
        name: str,
        description: str,
        project_code: str,
        actor_id: str,
    ) -> dict[str, Any]:
        agent_id = new_id("agent")
        timestamp = now_iso()
        try:
            self.database.execute(
                """
                insert into agent_definition
                  (id, code, name, description, project_code, status,
                   current_publication_id, revision, created_by, created_at, updated_at)
                values (?, ?, ?, ?, ?, 'enabled', null, 1, ?, ?, ?)
                """,
                (
                    agent_id,
                    code,
                    name,
                    description,
                    project_code,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
        except Exception as exc:
            if self.get_optional_definition(code) is not None:
                raise NonRetryableExecutionError(
                    "Agent code already exists",
                    safe_message="Agent 编码已存在",
                    error_code="agent_code_conflict",
                ) from exc
            raise
        return self.get_definition(code)

    def get_optional_definition(self, code: str) -> dict[str, Any] | None:
        return self.database.execute_one("select * from agent_definition where code = ?", (code,))

    def update_definition(
        self,
        *,
        code: str,
        expected_revision: int,
        name: str,
        description: str,
        project_code: str,
        status: str,
    ) -> dict[str, Any]:
        rows = self.database.execute(
            """
            update agent_definition
               set name = ?, description = ?, project_code = ?, status = ?,
                   revision = revision + 1, updated_at = ?
             where code = ? and revision = ?
            returning id
            """,
            (
                name,
                description,
                project_code,
                status,
                now_iso(),
                code,
                expected_revision,
            ),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Agent revision conflict",
                safe_message="Agent 已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )
        return self.get_definition(code)

    def latest_revision(self, agent_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from agent_revision
            where agent_id = ? order by revision desc limit 1
            """,
            (agent_id,),
        )
        return self._revision(row) if row else None

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        row = self.database.execute_one("select * from agent_revision where id = ?", (revision_id,))
        if not row:
            raise NotFound("Agent revision not found", safe_message="未找到 Agent 修订版本")
        return self._revision(row)

    def save_draft(
        self,
        *,
        agent_id: str,
        expected_revision: int,
        config: dict[str, Any],
        config_hash: str,
        actor_id: str,
    ) -> dict[str, Any]:
        latest = self.latest_revision(agent_id)
        if latest and int(latest["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Agent revision conflict",
                safe_message="Agent 草稿已发生变化，请刷新后重试",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(latest["revision"])},
            )
        next_revision = expected_revision + 1
        revision_id = new_id("agent_revision")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into agent_revision
              (id, agent_id, revision, status, config_json, config_hash,
               validation_json, created_by, created_at, updated_at)
            values (?, ?, ?, 'draft', ?, ?, '{}', ?, ?, ?)
            """,
            (
                revision_id,
                agent_id,
                next_revision,
                json.dumps(config, ensure_ascii=False, sort_keys=True),
                config_hash,
                actor_id,
                timestamp,
                timestamp,
            ),
        )
        self.database.execute(
            """
            update agent_definition
            set revision = revision + 1, updated_at = ?
            where id = ?
            """,
            (timestamp, agent_id),
        )
        return self.get_revision(revision_id)

    def set_validation(
        self, revision_id: str, *, valid: bool, errors: list[dict[str, str]]
    ) -> dict[str, Any]:
        self.database.execute(
            """
            update agent_revision
            set status = case when status = 'published' then 'published' else ? end,
                validation_json = ?,
                updated_at = ?
            where id = ?
            """,
            (
                "validated" if valid else "draft",
                json.dumps({"valid": valid, "errors": errors}, ensure_ascii=False),
                now_iso(),
                revision_id,
            ),
        )
        return self.get_revision(revision_id)

    def publication_for_revision(self, *, agent_id: str, revision_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from agent_publication
            where agent_id = ? and revision_id = ?
            """,
            (agent_id, revision_id),
        )
        return self._publication(row) if row else None

    def mark_revision_published(self, revision_id: str) -> None:
        self.database.execute(
            """
            update agent_revision
            set status = 'published', updated_at = ?
            where id = ? and status <> 'published'
            """,
            (now_iso(), revision_id),
        )

    def create_publication(
        self,
        *,
        agent_id: str,
        revision_id: str,
        revision: int,
        snapshot: dict[str, Any],
        config_hash: str,
        actor_id: str,
        mcp_tool_publication_ids: list[str] | None = None,
        expected_definition_revision: int,
    ) -> dict[str, Any]:
        publication_id = new_id("agent_publication")
        timestamp = now_iso()
        inserted = self.database.execute(
            """
            insert into agent_publication
              (id, agent_id, revision_id, revision, schema_version, snapshot_json,
               config_hash, status, published_by, published_at)
            values (?, ?, ?, ?, 1, ?, ?, 'active', ?, ?)
            on conflict(agent_id, revision) do nothing
            returning id
            """,
            (
                publication_id,
                agent_id,
                revision_id,
                revision,
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                config_hash,
                actor_id,
                timestamp,
            ),
        )
        if not inserted:
            existing = self.database.execute_one(
                """
                select * from agent_publication
                where agent_id = ? and revision = ?
                """,
                (agent_id, revision),
            )
            if existing:
                return self._publication(existing)
            raise NonRetryableExecutionError(
                "Agent publication conflict could not be resolved",
                safe_message="Agent 发布冲突，请刷新后重试",
                error_code="revision_conflict",
            )
        self.database.execute(
            """
            update agent_revision set status = 'published', updated_at = ?
            where id = ?
            """,
            (timestamp, revision_id),
        )
        updated = self.database.execute(
            """
            update agent_definition
            set current_publication_id = ?, revision = revision + 1, updated_at = ?
            where id = ? and revision = ?
            returning id
            """,
            (publication_id, timestamp, agent_id, expected_definition_revision),
        )
        if not updated:
            raise NonRetryableExecutionError(
                "Agent revision conflict",
                safe_message="Agent 已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )
        self.database.execute(
            """
            update agent_publication
               set status = 'inactive'
             where agent_id = ? and id <> ? and status = 'active'
            """,
            (agent_id, publication_id),
        )
        for skill_code in snapshot.get("skills") or []:
            self.database.execute(
                """
                insert into agent_skill_binding (id, publication_id, skill_code, created_at)
                values (?, ?, ?, ?)
                """,
                (new_id("agent_skill_binding"), publication_id, str(skill_code), timestamp),
            )
        channels = snapshot.get("channels") or {}
        if isinstance(channels, dict):
            for direction in ("ingress", "delivery"):
                values = channels.get(direction) or []
                for connector_id in values:
                    self.database.execute(
                        """
                        insert into agent_channel_binding
                          (id, publication_id, direction, connector_id, config_json, created_at)
                        values (?, ?, ?, ?, '{}', ?)
                        """,
                        (
                            new_id("agent_channel_binding"),
                            publication_id,
                            direction,
                            str(connector_id),
                            timestamp,
                        ),
                    )
        for tool_publication_id in dict.fromkeys(mcp_tool_publication_ids or []):
            self.database.execute(
                """
                insert into agent_publication_mcp_tool
                  (agent_publication_id, tool_publication_id)
                values (?, ?)
                """,
                (publication_id, tool_publication_id),
            )
        return self.get_publication(publication_id)

    def get_publication(self, publication_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from agent_publication where id = ?", (publication_id,)
        )
        if not row:
            raise NotFound("Agent publication not found", safe_message="未找到 Agent 发布版本")
        return self._publication(row)

    def current_publication(self, agent_code: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select p.*
            from agent_definition a
            join agent_publication p on p.id = a.current_publication_id
            where a.code = ? and a.status = 'enabled' and p.status = 'active'
            """,
            (agent_code,),
        )
        if not row:
            raise NotFound(
                "Agent has no active publication",
                safe_message="Agent 配置尚未发布",
            )
        return self._publication(row)

    def list_publications(self, agent_id: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select * from agent_publication
            where agent_id = ? order by revision desc
            """,
            (agent_id,),
        )
        return [self._publication(row) for row in rows]

    def active_application_usage(self, agent_publication_id: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select a.code, a.name, d.environment,
                   p.id application_publication_id, p.snapshot_json
              from business_application_deployment d
              join business_application a on a.id = d.application_id
              join business_application_publication p on p.id = d.publication_id
             where d.active = 1
             order by a.code, d.environment
            """,
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            snapshot = _json(str(row.get("snapshot_json") or "{}"))
            agent = snapshot.get("agent") if isinstance(snapshot, dict) else {}
            if not isinstance(agent, dict) or str(agent.get("id") or "") != agent_publication_id:
                continue
            result.append(
                {
                    "code": row["code"],
                    "name": row["name"],
                    "environment": row["environment"],
                    "application_publication_id": row["application_publication_id"],
                    "href": f"/applications/{row['code']}",
                }
            )
        return result

    def active_usage_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        publications = self.database.execute(
            "select id from agent_publication where agent_id = ?",
            (agent_id,),
        )
        result: list[dict[str, Any]] = []
        for publication in publications:
            result.extend(self.active_application_usage(str(publication["id"])))
        unique = {
            (str(item["application_publication_id"]), str(item["environment"])): item
            for item in result
        }
        return list(unique.values())

    def set_current_publication(
        self,
        *,
        agent_id: str,
        publication_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        publication = self.get_publication(publication_id)
        if str(publication["agent_id"]) != agent_id:
            raise NonRetryableExecutionError(
                "Publication belongs to another Agent",
                safe_message="发布版本不属于此 Agent",
            )
        timestamp = now_iso()
        with self.database.unit_of_work():
            updated = self.database.execute(
                """
                update agent_definition
                   set current_publication_id = ?, revision = revision + 1, updated_at = ?
                 where id = ? and revision = ?
                returning id
                """,
                (publication_id, timestamp, agent_id, expected_revision),
            )
            if not updated:
                raise NonRetryableExecutionError(
                    "Agent revision conflict",
                    safe_message="Agent 已发生变化，请刷新后重试",
                    error_code="revision_conflict",
                )
            self.database.execute(
                """
                update agent_publication
                   set status = case when id = ? then 'active' else 'inactive' end
                 where agent_id = ?
                """,
                (publication_id, agent_id),
            )
        return self.get_publication(publication_id)

    def mcp_tool_catalog(self) -> list[dict[str, object]]:
        return self.database.execute(
            """
            select p.id, t.code, t.name, p.server_code, p.server_version,
                   p.tool_name, p.required_scope, p.tool_schema_hash,
                   p.resource_kind, p.resource_code, p.resource_deployment_id,
                   p.resource_revision_id, p.config_hash, p.revision, p.status
              from mcp_tool_publication p
              join mcp_tool t on t.id = p.tool_id
             where p.status = 'PUBLISHED' and t.lifecycle_status = 'ENABLED'
             order by p.server_code, p.tool_name, p.resource_code
            """
        )

    def validate_mcp_tool_publications(self, publication_ids: list[str]) -> list[dict[str, Any]]:
        ordered = list(dict.fromkeys(publication_ids))
        if not ordered:
            return []
        rows = self.database.execute(
            f"""
            select p.*, t.code, t.lifecycle_status
              from mcp_tool_publication p
              join mcp_tool t on t.id = p.tool_id
             where p.id in ({",".join("?" for _ in ordered)})
               and p.status = 'PUBLISHED'
               and t.lifecycle_status = 'ENABLED'
            """,
            tuple(ordered),
        )
        by_id = {str(row["id"]): row for row in rows}
        if len(by_id) != len(ordered):
            raise NonRetryableExecutionError(
                "Agent selected unavailable MCP Tool Publications",
                safe_message="Agent 选择了不可用的 MCP Tool 发布版本",
                error_code="mcp_tool_publication_unavailable",
            )
        return [by_id[value] for value in ordered]

    def publication_mcp_tools(self, publication_id: str) -> list[dict[str, object]]:
        return self.database.execute(
            """
            select p.id, p.server_code, p.tool_name, p.required_scope,
                   p.tool_schema_hash, p.resource_code, p.resource_deployment_id,
                   p.resource_revision_id, p.revision, p.status
              from mcp_tool_publication p
              join agent_publication_mcp_tool binding
                on binding.tool_publication_id = p.id
             where binding.agent_publication_id = ?
             order by server_code, tool_name, resource_code
            """,
            (publication_id,),
        )

    def publication_connectors(self, publication_id: str, direction: str) -> set[str]:
        rows = self.database.execute(
            """
            select connector_id from agent_channel_binding
            where publication_id = ? and direction = ?
            """,
            (publication_id, direction),
        )
        return {str(row["connector_id"]) for row in rows}

    def connector_catalog(self) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select id, connector_type, name, enabled, allow_ingress, allow_delivery
            from integration_connector
            where enabled = 1
            order by name, id
            """
        )

    def connector_exists(self, connector_id: str, direction: str) -> bool:
        column = "allow_ingress" if direction == "ingress" else "allow_delivery"
        row = self.database.execute_one(
            f"""
            select id from integration_connector
            where id = ? and enabled = 1 and {column} = 1
            """,
            (connector_id,),
        )
        return row is not None

    def _revision(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "revision": int(row["revision"]),
            "config": _json(str(row.get("config_json") or "{}")),
            "validation": _json(str(row.get("validation_json") or "{}")),
        }

    def _publication(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "revision": int(row["revision"]),
            "schema_version": int(row["schema_version"]),
            "snapshot": _json(str(row["snapshot_json"])),
        }


def _json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}
