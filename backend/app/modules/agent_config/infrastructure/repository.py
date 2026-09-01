from __future__ import annotations

import json
from typing import Any

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


class AgentConfigRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_definitions(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where status = 'enabled'"
        return self.database.execute(f"select * from agent_definition {where} order by code")

    def find_definition(self, code: str) -> dict[str, Any] | None:
        return self.database.execute_one(
            "select * from agent_definition where code = ?",
            (code,),
        )

    def get_definition(self, code: str) -> dict[str, Any]:
        row = self.find_definition(code)
        if not row:
            raise NotFound("Agent not found", safe_message="未找到 Agent")
        return row

    def get_definition_by_id(self, agent_id: str) -> dict[str, Any]:
        row = self.database.execute_one("select * from agent_definition where id = ?", (agent_id,))
        if not row:
            raise NotFound("Agent not found", safe_message="未找到 Agent")
        return row

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

    def create_definition_with_initial_draft(
        self,
        *,
        code: str,
        name: str,
        description: str,
        project_code: str,
        runtime_kind: str,
        classification: str,
        config: dict[str, Any],
        config_hash: str,
        actor_id: str,
        agent_id: str | None = None,
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        resolved_agent_id = agent_id or new_id("agent_definition")
        inserted = self.database.execute(
            """
            insert into agent_definition
              (id, code, name, description, project_code, status,
               current_publication_id, revision, created_by, created_at,
               updated_at, classification, runtime_kind)
            values (?, ?, ?, ?, ?, 'enabled', null, 1, ?, ?, ?, ?, ?)
            on conflict(code) do nothing
            returning id
            """,
            (
                resolved_agent_id,
                code,
                name,
                description,
                project_code,
                actor_id,
                timestamp,
                timestamp,
                classification,
                runtime_kind,
            ),
        )
        if not inserted:
            raise NonRetryableExecutionError(
                "Agent code already exists",
                safe_message="Agent 编码已存在",
                error_code="agent_code_conflict",
                field_errors=[{"field": "code", "message": "Agent 编码已存在"}],
            )
        resolved_revision_id = revision_id or new_id("agent_revision")
        self.database.execute(
            """
            insert into agent_revision
              (id, agent_id, revision, status, config_json, config_hash,
               validation_json, created_by, created_at, updated_at)
            values (?, ?, 1, 'draft', ?, ?, '{}', ?, ?, ?)
            """,
            (
                resolved_revision_id,
                resolved_agent_id,
                json.dumps(config, ensure_ascii=False, sort_keys=True),
                config_hash,
                actor_id,
                timestamp,
                timestamp,
            ),
        )
        return {
            "definition": self.get_definition(code),
            "draft": self.get_revision(resolved_revision_id),
        }

    def create_initial_draft_if_missing(
        self,
        *,
        agent_id: str,
        config: dict[str, Any],
        config_hash: str,
        actor_id: str,
    ) -> tuple[dict[str, Any], bool]:
        existing = self.latest_revision(agent_id)
        if existing is not None:
            return existing, False
        revision_id = new_id("agent_revision")
        timestamp = now_iso()
        inserted = self.database.execute(
            """
            insert into agent_revision
              (id, agent_id, revision, status, config_json, config_hash,
               validation_json, created_by, created_at, updated_at)
            values (?, ?, 1, 'draft', ?, ?, '{}', ?, ?, ?)
            on conflict(agent_id, revision) do nothing
            returning id
            """,
            (
                revision_id,
                agent_id,
                json.dumps(config, ensure_ascii=False, sort_keys=True),
                config_hash,
                actor_id,
                timestamp,
                timestamp,
            ),
        )
        if inserted:
            return self.get_revision(revision_id), True
        concurrent = self.latest_revision(agent_id)
        if concurrent is None:
            raise NonRetryableExecutionError(
                "Agent initial draft conflict could not be resolved",
                safe_message="Agent 初始草稿创建冲突，请重试",
                error_code="revision_conflict",
            )
        return concurrent, False

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
        runtime_kind: str,
        snapshot: dict[str, Any],
        config_hash: str,
        actor_id: str,
    ) -> dict[str, Any]:
        publication_id = new_id("agent_publication")
        timestamp = now_iso()
        inserted = self.database.execute(
            """
            insert into agent_publication
              (id, agent_id, revision_id, revision, schema_version, snapshot_json,
               config_hash, runtime_kind, status, published_by, published_at)
            values (?, ?, ?, ?, 3, ?, ?, ?, 'active', ?, ?)
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
                runtime_kind,
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
        self.database.execute(
            """
            update agent_definition
            set current_publication_id = ?, revision = revision + 1, updated_at = ?
            where id = ?
            """,
            (publication_id, timestamp, agent_id),
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

    def set_current_publication(self, *, agent_id: str, publication_id: str) -> dict[str, Any]:
        publication = self.get_publication(publication_id)
        if str(publication["agent_id"]) != agent_id:
            raise NonRetryableExecutionError(
                "Publication belongs to another Agent",
                safe_message="发布版本不属于此 Agent",
            )
        timestamp = now_iso()
        with self.database.unit_of_work():
            self.database.execute(
                """
                update agent_publication
                   set status = case when id = ? then 'active' else 'inactive' end
                 where agent_id = ?
                """,
                (publication_id, agent_id),
            )
            self.database.execute(
                """
                update agent_definition
                set current_publication_id = ?, revision = revision + 1, updated_at = ?
                where id = ?
                """,
                (publication_id, timestamp, agent_id),
            )
        return self.get_publication(publication_id)

    def publication_tools(self, publication_id: str) -> set[str]:
        rows = self.database.execute(
            """
            select tool_identifier as tool_name
              from agent_publication_mcp_tool
             where agent_publication_id = ?
            """,
            (publication_id,),
        )
        return {str(row["tool_name"]) for row in rows}

    def freeze_mcp_tools(
        self,
        *,
        agent_publication_id: str,
        envelopes: list[dict[str, Any]],
    ) -> None:
        existing = self.database.execute_one(
            "select 1 as present from agent_publication_mcp_tool where agent_publication_id = ? limit 1",
            (agent_publication_id,),
        )
        if existing is not None:
            self.verify_mcp_tools(
                agent_publication_id=agent_publication_id,
                envelopes=envelopes,
            )
            return
        timestamp = now_iso()
        for index, envelope in enumerate(envelopes):
            self.database.execute(
                """
                insert into agent_publication_mcp_tool
                  (agent_publication_id, server_code, tool_identifier,
                   schema_hash, model_description, selection_order, created_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_publication_id,
                    str(envelope["server_code"]),
                    str(envelope["tool_identifier"]),
                    str(envelope["schema_hash"]),
                    str(envelope.get("description") or ""),
                    index,
                    timestamp,
                ),
            )

    def verify_mcp_tools(
        self,
        *,
        agent_publication_id: str,
        envelopes: list[dict[str, Any]],
    ) -> None:
        self.verify_mcp_tool_facts(
            agent_publication_id=agent_publication_id,
            envelopes=envelopes,
        )
        self.verify_mcp_tool_policy(envelopes=envelopes)

    def verify_mcp_tool_facts(
        self,
        *,
        agent_publication_id: str,
        envelopes: list[dict[str, Any]],
    ) -> None:
        rows = self.database.execute(
            """
            select server_code, tool_identifier, schema_hash
              from agent_publication_mcp_tool
             where agent_publication_id = ?
             order by selection_order
            """,
            (agent_publication_id,),
        )
        expected = [
            {
                "server_code": str(item["server_code"]),
                "tool_identifier": str(item["tool_identifier"]),
                "schema_hash": str(item["schema_hash"]),
            }
            for item in envelopes
        ]
        actual = [
            {
                "server_code": str(row["server_code"]),
                "tool_identifier": str(row["tool_identifier"]),
                "schema_hash": str(row["schema_hash"]),
            }
            for row in rows
        ]
        if actual != expected:
            raise NonRetryableExecutionError(
                "Agent MCP Tool publication facts differ from its snapshot",
                safe_message="Agent MCP 工具发布事实完整性校验失败",
                error_code="agent_mcp_tool_envelope_mismatch",
            )

    @staticmethod
    def verify_mcp_tool_policy(*, envelopes: list[dict[str, Any]]) -> None:
        for envelope in envelopes:
            identifier = str(envelope["tool_identifier"])
            definition = MCP_TOOL_MANIFEST.get(identifier)
            if definition is None:
                raise NonRetryableExecutionError(
                    "Agent MCP Tool is not in the code manifest",
                    safe_message="Agent MCP 工具已退役，请创建新发布版本",
                    error_code="agent_mcp_tool_policy_incompatible",
                )
            declared = {
                "effect": definition.effect,
                "confirmation_policy": definition.confirmation_policy,
                "operation_code": definition.operation_code,
                "risk_level": definition.risk_level,
                "target_policy": definition.target_policy,
            }
            if any(
                key in envelope and str(envelope.get(key) or "") != expected_value
                for key, expected_value in declared.items()
            ):
                raise NonRetryableExecutionError(
                    "Agent MCP Tool execution metadata differs from the code manifest",
                    safe_message="Agent MCP 工具执行策略已变化，请创建新发布版本",
                    error_code="agent_mcp_tool_policy_incompatible",
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
