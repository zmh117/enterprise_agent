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

    def publication_for_revision(
        self, *, agent_id: str, revision_id: str
    ) -> dict[str, Any] | None:
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
        if snapshot.get("tools"):
            raise NonRetryableExecutionError(
                "New Agent publication cannot persist legacy Tool names",
                safe_message=(
                    "旧名称级工具绑定已停止新增；请选择精确 Tool Release 并重新发布"
                ),
                error_code="builtin_tool_legacy_write_forbidden",
            )
        publication_id = new_id("agent_publication")
        timestamp = now_iso()
        inserted = self.database.execute(
            """
            insert into agent_publication
              (id, agent_id, revision_id, revision, schema_version, snapshot_json,
               config_hash, runtime_kind, status, published_by, published_at)
            values (?, ?, ?, ?, 2, ?, ?, ?, 'active', ?, ?)
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
            raise NotFound(
                "Agent publication not found", safe_message="未找到 Agent 发布版本"
            )
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
        legacy = self.database.execute_one(
            "select 1 as found from agent_tool_binding where publication_id = ? limit 1",
            (publication_id,),
        )
        if legacy is not None:
            raise NonRetryableExecutionError(
                "Legacy Agent publication cannot be reactivated",
                safe_message="legacy-v1 Agent 发布版本只保留历史审计，不能重新激活",
                error_code="builtin_tool_legacy_reactivation_forbidden",
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

    def enabled_tools(self) -> set[str]:
        rows = self.database.execute(
            "select name from tool_definition where enabled = 1 and read_only = 1"
        )
        return {str(row["name"]) for row in rows}

    def publication_tools(self, publication_id: str) -> set[str]:
        rows = self.database.execute(
            """
            select envelope.tool_identifier as tool_name
              from agent_publication_builtin_tool envelope
              join builtin_tool_release release
                on release.id = envelope.tool_release_id
               and release.tool_identifier = envelope.tool_identifier
               and release.handler_version = envelope.handler_version
               and release.implementation_digest = envelope.implementation_digest
              join builtin_tool_installation installation
                on installation.tool_identifier = envelope.tool_identifier
               and installation.handler_version = envelope.handler_version
               and installation.implementation_digest = envelope.implementation_digest
             where envelope.agent_publication_id = ?
               and release.status in ('ACTIVE', 'DEPRECATED')
               and installation.installation_status = 'INSTALLED'
            """,
            (publication_id,),
        )
        return {str(row["tool_name"]) for row in rows}

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
