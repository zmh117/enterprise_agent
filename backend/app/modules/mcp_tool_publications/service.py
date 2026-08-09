from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound
from services.mcp_common import catalog_entries, get_catalog_entry


_CODE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


class McpToolPublicationService:
    """Govern code-owned MCP contracts without accepting executable definitions."""

    def __init__(
        self,
        database: Database,
        *,
        audit_service: AuditService | None = None,
    ) -> None:
        self.database = database
        self.audit_service = audit_service

    def catalog(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in catalog_entries()]

    def list_tools(self) -> list[dict[str, Any]]:
        rows = self.database.execute("select * from mcp_tool order by code")
        return [self._detail_from_row(row) for row in rows]

    def get(self, code: str) -> dict[str, Any]:
        return self._detail_from_row(self._tool(code))

    def tool_code_for_publication(self, publication_id: str) -> str:
        row = self.database.execute_one(
            """
            select t.code
              from mcp_tool_publication p
              join mcp_tool t on t.id = p.tool_id
             where p.id = ?
            """,
            (publication_id,),
        )
        if row is None:
            raise NotFound(
                "MCP Tool Publication not found",
                safe_message="MCP Tool 发布版本不存在",
            )
        return str(row["code"])

    def create(
        self,
        *,
        code: str,
        name: str,
        catalog_key: str,
        resource_deployment_id: str = "",
        expected_revision: int = 0,
        actor_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if expected_revision != 0:
            raise self._conflict()
        normalized_code = self._code(code)
        normalized_name = name.strip()
        if not 1 <= len(normalized_name) <= 128:
            raise ValueError("MCP Tool name must contain 1-128 characters")
        entry = get_catalog_entry(catalog_key)
        deployment = self._validate_resource(entry.resource_kind, resource_deployment_id)
        payload = {
            "expected_revision": expected_revision,
            "code": normalized_code,
            "name": normalized_name,
            "catalog_key": entry.catalog_key,
            "resource_deployment_id": str((deployment or {}).get("id") or ""),
        }
        normalized_deployment_id = str(payload["resource_deployment_id"])
        request_hash = _hash(payload)
        replay = self._idempotent(idempotency_key, "tool.create", actor_id, request_hash)
        if replay is not None:
            return replay
        timestamp = now_iso()
        tool_id = new_id("mcp_tool")
        draft_id = new_id("mcp_tool_draft")
        with self.database.unit_of_work():
            self.database.execute(
                """
                insert into mcp_tool
                  (id, code, catalog_key, name, lifecycle_status, revision,
                   current_publication_id, created_by, created_at, updated_at)
                values (?, ?, ?, ?, 'ENABLED', 1, null, ?, ?, ?)
                """,
                (
                    tool_id,
                    normalized_code,
                    entry.catalog_key,
                    normalized_name,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
            self.database.execute(
                """
                insert into mcp_tool_draft
                  (id, tool_id, draft_revision, catalog_key, resource_deployment_id,
                   content_hash, status, verification_json, expected_tool_revision,
                   created_by, created_at, updated_at)
                values (?, ?, 1, ?, ?, ?, 'DRAFT', '{}', 1, ?, ?, ?)
                """,
                (
                    draft_id,
                    tool_id,
                    entry.catalog_key,
                    normalized_deployment_id,
                    _hash(self._draft_payload(entry.catalog_key, normalized_deployment_id)),
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
            response = {
                "id": tool_id,
                "code": normalized_code,
                "revision": 1,
                "draft_id": draft_id,
                "draft_status": "DRAFT",
            }
            self._remember(idempotency_key, "tool.create", actor_id, request_hash, response)
        self._audit("mcp.tool.created", actor_id, response)
        return response

    def update_draft(
        self,
        code: str,
        *,
        expected_revision: int,
        catalog_key: str,
        resource_deployment_id: str = "",
        actor_id: str,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        request_hash = _hash(
            {
                "code": code,
                "expected_revision": expected_revision,
                "catalog_key": catalog_key,
                "resource_deployment_id": resource_deployment_id,
            }
        )
        replay = self._idempotent(idempotency_key, "tool.update_draft", actor_id, request_hash)
        if replay is not None:
            return replay
        tool = self._tool(code)
        self._require_editable(tool, expected_revision)
        entry = get_catalog_entry(catalog_key)
        deployment = self._validate_resource(entry.resource_kind, resource_deployment_id)
        deployment_id = str((deployment or {}).get("id") or "")
        content_hash = _hash(self._draft_payload(entry.catalog_key, deployment_id))
        timestamp = now_iso()
        with self.database.unit_of_work():
            self.database.execute(
                """
                update mcp_tool_draft set status = 'DISCARDED', updated_at = ?
                 where tool_id = ? and status in ('DRAFT', 'VERIFIED')
                """,
                (timestamp, tool["id"]),
            )
            row = self.database.execute_one(
                "select coalesce(max(draft_revision), 0) + 1 value from mcp_tool_draft where tool_id = ?",
                (tool["id"],),
            )
            assert row is not None
            draft_id = new_id("mcp_tool_draft")
            self.database.execute(
                """
                insert into mcp_tool_draft
                  (id, tool_id, draft_revision, catalog_key, resource_deployment_id,
                   content_hash, status, verification_json, expected_tool_revision,
                   created_by, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, 'DRAFT', '{}', ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    tool["id"],
                    int(row["value"]),
                    entry.catalog_key,
                    deployment_id,
                    content_hash,
                    expected_revision,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
            self._bump(tool, expected_revision, timestamp)
            response = {
                "code": code,
                "draft_id": draft_id,
                "draft_status": "DRAFT",
                "revision": expected_revision + 1,
                "content_hash": content_hash,
            }
            self._remember(
                idempotency_key,
                "tool.update_draft",
                actor_id,
                request_hash,
                response,
            )
        self._audit("mcp.tool.draft.updated", actor_id, response)
        return response

    def verify(
        self,
        code: str,
        *,
        expected_revision: int,
        actor_id: str,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        request_hash = _hash({"code": code, "expected_revision": expected_revision})
        replay = self._idempotent(idempotency_key, "tool.verify", actor_id, request_hash)
        if replay is not None:
            return replay
        tool, draft = self._open_draft(code, expected_revision=expected_revision)
        entry = get_catalog_entry(str(draft["catalog_key"]))
        deployment = self._validate_resource(
            entry.resource_kind, str(draft.get("resource_deployment_id") or "")
        )
        expected_hash = _hash(
            self._draft_payload(entry.catalog_key, str((deployment or {}).get("id") or ""))
        )
        if expected_hash != str(draft["content_hash"]):
            raise self._integrity("mcp_tool_draft_integrity_failed")
        verification = {
            "catalog_key": entry.catalog_key,
            "server_code": entry.server_code,
            "server_version": entry.server_version,
            "tool_name": entry.tool_name,
            "required_scope": entry.required_scope,
            "tool_schema_hash": entry.tool_schema_hash,
            "resource_kind": entry.resource_kind or "",
            "resource_deployment_id": str((deployment or {}).get("id") or ""),
            "resource_revision_id": str((deployment or {}).get("resource_revision_id") or ""),
        }
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update mcp_tool_draft
                   set status = 'VERIFIED', verification_json = ?, updated_at = ?
                 where id = ? and status = 'DRAFT' and content_hash = ?
                returning id
                """,
                (_json(verification), timestamp, draft["id"], draft["content_hash"]),
            )
            if not rows:
                raise self._conflict()
            response = {
                "code": str(tool["code"]),
                "draft_id": str(draft["id"]),
                "status": "VERIFIED",
                **verification,
            }
            self._remember(
                idempotency_key,
                "tool.verify",
                actor_id,
                request_hash,
                response,
            )
        self._audit("mcp.tool.verified", actor_id, response)
        return response

    def publish(
        self,
        code: str,
        *,
        expected_revision: int,
        actor_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request_hash = _hash({"code": code, "expected_revision": expected_revision})
        replay = self._idempotent(idempotency_key, "tool.publish", actor_id, request_hash)
        if replay is not None:
            return replay
        tool, draft = self._open_draft(code, expected_revision=expected_revision, status="VERIFIED")
        verification = _object(draft["verification_json"])
        entry = get_catalog_entry(str(draft["catalog_key"]))
        deployment = self._validate_resource(
            entry.resource_kind, str(draft.get("resource_deployment_id") or "")
        )
        current = {
            "catalog_key": entry.catalog_key,
            "server_code": entry.server_code,
            "server_version": entry.server_version,
            "tool_name": entry.tool_name,
            "required_scope": entry.required_scope,
            "tool_schema_hash": entry.tool_schema_hash,
            "resource_kind": entry.resource_kind or "",
            "resource_deployment_id": str((deployment or {}).get("id") or ""),
            "resource_revision_id": str((deployment or {}).get("resource_revision_id") or ""),
        }
        if any(str(verification.get(key) or "") != str(value) for key, value in current.items()):
            raise self._integrity("mcp_tool_verification_stale")
        resource_code = str((deployment or {}).get("resource_code") or "")
        immutable = {**current, "resource_code": resource_code}
        config_hash = _hash(immutable)
        duplicate = self.database.execute_one(
            "select id, revision from mcp_tool_publication where tool_id = ? and config_hash = ?",
            (tool["id"], config_hash),
        )
        if duplicate is not None:
            raise NonRetryableExecutionError(
                "MCP Tool configuration was already published",
                safe_message="相同 MCP Tool 配置已发布，请使用历史版本回退",
                error_code="mcp_tool_duplicate_publication",
                diagnostics={
                    "publication_id": str(duplicate["id"]),
                    "publication_revision": int(duplicate["revision"]),
                },
            )
        timestamp = now_iso()
        with self.database.unit_of_work():
            revision = self.database.execute_one(
                "select coalesce(max(revision), 0) + 1 value from mcp_tool_publication where tool_id = ?",
                (tool["id"],),
            )
            assert revision is not None
            publication_id = new_id("mcp_tool_publication")
            rows = self.database.execute(
                """
                update mcp_tool
                   set current_publication_id = ?, revision = revision + 1, updated_at = ?
                 where id = ? and revision = ? and lifecycle_status = 'ENABLED'
                returning id
                """,
                (publication_id, timestamp, tool["id"], expected_revision),
            )
            if not rows:
                raise self._conflict()
            self.database.execute(
                "update mcp_tool_publication set status = 'DISABLED' where tool_id = ? and status = 'PUBLISHED'",
                (tool["id"],),
            )
            self.database.execute(
                """
                insert into mcp_tool_publication
                  (id, tool_id, revision, catalog_key, server_code, server_version,
                   tool_name, required_scope, tool_schema_hash, resource_kind,
                   resource_code, resource_deployment_id, resource_revision_id,
                   config_hash, status, published_by, published_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PUBLISHED', ?, ?)
                """,
                (
                    publication_id,
                    tool["id"],
                    int(revision["value"]),
                    entry.catalog_key,
                    entry.server_code,
                    entry.server_version,
                    entry.tool_name,
                    entry.required_scope,
                    entry.tool_schema_hash,
                    entry.resource_kind or "",
                    resource_code,
                    immutable["resource_deployment_id"],
                    immutable["resource_revision_id"],
                    config_hash,
                    actor_id,
                    timestamp,
                ),
            )
            self.database.execute(
                "update mcp_tool_draft set status = 'DISCARDED', updated_at = ? where id = ?",
                (timestamp, draft["id"]),
            )
            response = {
                "code": code,
                "publication_id": publication_id,
                "publication_revision": int(revision["value"]),
                "config_hash": config_hash,
                "status": "PUBLISHED",
                "revision": expected_revision + 1,
            }
            self._remember(idempotency_key, "tool.publish", actor_id, request_hash, response)
        self._audit("mcp.tool.published", actor_id, response)
        return response

    def disable(
        self,
        code: str,
        *,
        expected_revision: int,
        actor_id: str,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        request_hash = _hash({"code": code, "expected_revision": expected_revision})
        replay = self._idempotent(idempotency_key, "tool.disable", actor_id, request_hash)
        if replay is not None:
            return replay
        tool = self._tool(code)
        self._require_editable(tool, expected_revision)
        current_publication_id = str(tool.get("current_publication_id") or "")
        active_usage = (
            self.active_deployment_usage(current_publication_id) if current_publication_id else []
        )
        if active_usage:
            self._audit(
                "mcp.tool.disable.denied",
                actor_id,
                {
                    "code": code,
                    "expected_revision": expected_revision,
                    "reason_code": "dependency_in_use",
                    "active_application_count": len(active_usage),
                },
                status="DENIED",
            )
            raise NonRetryableExecutionError(
                "MCP Tool Publication is referenced by active Application deployments",
                safe_message="请先停用引用此 MCP Tool 的活动应用环境",
                error_code="dependency_in_use",
                diagnostics={"active_applications": active_usage},
            )
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update mcp_tool
                   set lifecycle_status = 'DISABLED', revision = revision + 1, updated_at = ?
                 where id = ? and revision = ? and lifecycle_status = 'ENABLED'
                returning id
                """,
                (timestamp, tool["id"], expected_revision),
            )
            if not rows:
                raise self._conflict()
            self.database.execute(
                "update mcp_tool_publication set status = 'DISABLED' where tool_id = ? and status = 'PUBLISHED'",
                (tool["id"],),
            )
            response = {
                "code": code,
                "status": "DISABLED",
                "revision": expected_revision + 1,
            }
            self._remember(
                idempotency_key,
                "tool.disable",
                actor_id,
                request_hash,
                response,
            )
        self._audit("mcp.tool.disabled", actor_id, response)
        return response

    def rollback(
        self,
        code: str,
        *,
        publication_id: str,
        expected_revision: int,
        actor_id: str,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        request_hash = _hash(
            {
                "code": code,
                "publication_id": publication_id,
                "expected_revision": expected_revision,
            }
        )
        replay = self._idempotent(idempotency_key, "tool.rollback", actor_id, request_hash)
        if replay is not None:
            return replay
        tool = self._tool(code)
        self._require_editable(tool, expected_revision)
        publication = self.database.execute_one(
            """
            select * from mcp_tool_publication
             where id = ? and tool_id = ?
            """,
            (publication_id, tool["id"]),
        )
        if publication is None:
            raise NotFound(
                "MCP Tool Publication not found",
                safe_message="MCP Tool 发布版本不存在",
            )
        entry = get_catalog_entry(str(publication["catalog_key"]))
        expected = {
            "server_code": entry.server_code,
            "server_version": entry.server_version,
            "tool_name": entry.tool_name,
            "required_scope": entry.required_scope,
            "tool_schema_hash": entry.tool_schema_hash,
            "resource_kind": entry.resource_kind or "",
        }
        if any(str(publication.get(key) or "") != value for key, value in expected.items()):
            raise self._integrity("mcp_tool_catalog_contract_stale")
        deployment = self._validate_resource(
            entry.resource_kind,
            str(publication.get("resource_deployment_id") or ""),
        )
        if deployment is not None and str(deployment["resource_revision_id"]) != str(
            publication.get("resource_revision_id") or ""
        ):
            raise self._integrity("mcp_tool_resource_binding_stale")
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update mcp_tool
                   set current_publication_id = ?, revision = revision + 1, updated_at = ?
                 where id = ? and revision = ? and lifecycle_status = 'ENABLED'
                returning id
                """,
                (publication_id, timestamp, tool["id"], expected_revision),
            )
            if not rows:
                raise self._conflict()
            self.database.execute(
                """
                update mcp_tool_publication set status = 'DISABLED'
                 where tool_id = ? and status = 'PUBLISHED'
                """,
                (tool["id"],),
            )
            self.database.execute(
                "update mcp_tool_publication set status = 'PUBLISHED' where id = ?",
                (publication_id,),
            )
            response = {
                "code": code,
                "publication_id": publication_id,
                "publication_revision": int(publication["revision"]),
                "status": "PUBLISHED",
                "revision": expected_revision + 1,
            }
            self._remember(
                idempotency_key,
                "tool.rollback",
                actor_id,
                request_hash,
                response,
            )
        self._audit("mcp.tool.rolled_back", actor_id, response)
        return response

    def archive(
        self,
        code: str,
        *,
        expected_revision: int,
        actor_id: str,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        request_hash = _hash({"code": code, "expected_revision": expected_revision})
        replay = self._idempotent(idempotency_key, "tool.archive", actor_id, request_hash)
        if replay is not None:
            return replay
        tool = self._tool(code)
        if int(tool["revision"]) != expected_revision:
            raise self._conflict()
        if str(tool["lifecycle_status"]) != "DISABLED":
            raise NonRetryableExecutionError(
                "MCP Tool must be disabled before archive",
                safe_message="MCP Tool 必须先停用才能归档",
                error_code="invalid_lifecycle",
            )
        publication_ids = [
            str(row["id"])
            for row in self.database.execute(
                "select id from mcp_tool_publication where tool_id = ?",
                (tool["id"],),
            )
        ]
        usage = [
            item
            for publication_id in publication_ids
            for category in self.usage(publication_id).values()
            for item in category
        ]
        if usage:
            raise NonRetryableExecutionError(
                "MCP Tool Publication is still referenced",
                safe_message="MCP Tool 仍被 Agent 或业务应用发布版本引用",
                error_code="dependency_in_use",
            )
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                update mcp_tool
                   set lifecycle_status = 'ARCHIVED', revision = revision + 1,
                       updated_at = ?
                 where id = ? and revision = ? and lifecycle_status = 'DISABLED'
                returning id
                """,
                (timestamp, tool["id"], expected_revision),
            )
            if not rows:
                raise self._conflict()
            self.database.execute(
                "update mcp_tool_publication set status = 'ARCHIVED' where tool_id = ?",
                (tool["id"],),
            )
            response = {
                "code": code,
                "status": "ARCHIVED",
                "revision": expected_revision + 1,
            }
            self._remember(
                idempotency_key,
                "tool.archive",
                actor_id,
                request_hash,
                response,
            )
        self._audit("mcp.tool.archived", actor_id, response)
        return response

    def usage(self, publication_id: str) -> dict[str, list[dict[str, Any]]]:
        return {
            "agents": self.database.execute(
                """
                select p.id publication_id, d.code agent_code
                  from agent_publication_mcp_tool b
                  join agent_publication p on p.id = b.agent_publication_id
                  join agent_definition d on d.id = p.agent_id
                 where b.tool_publication_id = ? order by d.code, p.revision
                """,
                (publication_id,),
            ),
            "applications": self.database.execute(
                """
                select p.id publication_id, a.code application_code
                  from business_application_publication_mcp_tool b
                  join business_application_publication p on p.id = b.application_publication_id
                  join business_application a on a.id = p.application_id
                 where b.tool_publication_id = ? order by a.code, p.revision
                """,
                (publication_id,),
            ),
            "active_deployments": self.active_deployment_usage(publication_id),
        }

    def active_deployment_usage(self, publication_id: str) -> list[dict[str, Any]]:
        if not publication_id:
            return []
        return self.database.execute(
            """
            select d.id deployment_id, d.environment, a.code application_code,
                   p.id publication_id, p.revision publication_revision
              from business_application_publication_mcp_tool b
              join business_application_publication p
                on p.id = b.application_publication_id
              join business_application a on a.id = p.application_id
              join business_application_deployment d
                on d.publication_id = p.id and d.application_id = a.id
             where b.tool_publication_id = ? and d.active = 1
             order by a.code, d.environment
            """,
            (publication_id,),
        )

    def bind_agent_publication(
        self, agent_publication_id: str, tool_publication_ids: list[str]
    ) -> None:
        self._bind(
            owner_table="agent_publication",
            owner_id=agent_publication_id,
            binding_table="agent_publication_mcp_tool",
            owner_column="agent_publication_id",
            tool_publication_ids=tool_publication_ids,
        )

    def prepare_agent_selection(self, tool_publication_ids: list[str]) -> list[dict[str, Any]]:
        """Resolve an exact, currently usable set for a new immutable Agent Publication."""
        return self._prepare_selection(tool_publication_ids)

    def prepare_application_selection(
        self,
        agent_publication_id: str,
        tool_publication_ids: list[str],
    ) -> list[dict[str, Any]]:
        allowed = {
            str(row["tool_publication_id"])
            for row in self.database.execute(
                """
                select tool_publication_id from agent_publication_mcp_tool
                 where agent_publication_id = ?
                """,
                (agent_publication_id,),
            )
        }
        requested = set(tool_publication_ids)
        if not requested <= allowed:
            raise NonRetryableExecutionError(
                "Application MCP Tool set exceeds its Agent Publication",
                safe_message="应用选择的 MCP Tool 超出 Agent 允许范围",
                error_code="application_mcp_tool_scope_exceeded",
            )
        return self._prepare_selection(tool_publication_ids)

    def bind_application_publication(
        self,
        application_publication_id: str,
        agent_publication_id: str,
        tool_publication_ids: list[str],
    ) -> None:
        allowed = {
            str(row["tool_publication_id"])
            for row in self.database.execute(
                "select tool_publication_id from agent_publication_mcp_tool where agent_publication_id = ?",
                (agent_publication_id,),
            )
        }
        requested = set(tool_publication_ids)
        if not requested <= allowed:
            raise NonRetryableExecutionError(
                "Application MCP Tool set exceeds its Agent Publication",
                safe_message="应用选择的 MCP Tool 超出 Agent 允许范围",
                error_code="application_mcp_tool_scope_exceeded",
            )
        self._bind(
            owner_table="business_application_publication",
            owner_id=application_publication_id,
            binding_table="business_application_publication_mcp_tool",
            owner_column="application_publication_id",
            tool_publication_ids=tool_publication_ids,
        )

    def _bind(
        self,
        *,
        owner_table: str,
        owner_id: str,
        binding_table: str,
        owner_column: str,
        tool_publication_ids: list[str],
    ) -> None:
        if (
            self.database.execute_one(f"select id from {owner_table} where id = ?", (owner_id,))
            is None
        ):
            raise NotFound("Publication not found", safe_message="发布版本不存在")
        ordered = tuple(dict.fromkeys(tool_publication_ids))
        rows = (
            self.database.execute(
                f"select id from mcp_tool_publication where id in ({','.join('?' for _ in ordered)}) and status = 'PUBLISHED'",
                ordered,
            )
            if ordered
            else []
        )
        if len(rows) != len(ordered):
            raise NonRetryableExecutionError(
                "MCP Tool Publication selection contains unavailable entries",
                safe_message="MCP Tool 发布版本不可用",
                error_code="mcp_tool_publication_unavailable",
            )
        with self.database.unit_of_work():
            self.database.execute(
                f"delete from {binding_table} where {owner_column} = ?", (owner_id,)
            )
            for publication_id in ordered:
                self.database.execute(
                    f"insert into {binding_table} ({owner_column}, tool_publication_id) values (?, ?)",
                    (owner_id, publication_id),
                )

    def _prepare_selection(self, tool_publication_ids: list[str]) -> list[dict[str, Any]]:
        ordered = list(dict.fromkeys(tool_publication_ids))
        if not ordered:
            return []
        rows = self.database.execute(
            f"""
            select p.*, t.code, t.name, t.lifecycle_status
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
                "MCP Tool Publication selection contains unavailable entries",
                safe_message="MCP Tool 发布版本不可用",
                error_code="mcp_tool_publication_unavailable",
            )
        result: list[dict[str, Any]] = []
        for publication_id in ordered:
            row = by_id[publication_id]
            entry = get_catalog_entry(str(row["catalog_key"]))
            expected = {
                "server_code": entry.server_code,
                "server_version": entry.server_version,
                "tool_name": entry.tool_name,
                "required_scope": entry.required_scope,
                "tool_schema_hash": entry.tool_schema_hash,
                "resource_kind": entry.resource_kind or "",
            }
            if any(str(row.get(key) or "") != value for key, value in expected.items()):
                raise self._integrity("mcp_tool_catalog_contract_stale")
            deployment = self._validate_resource(
                entry.resource_kind,
                str(row.get("resource_deployment_id") or ""),
            )
            if deployment is not None and (
                str(deployment["resource_revision_id"])
                != str(row.get("resource_revision_id") or "")
                or str(deployment["resource_code"]) != str(row.get("resource_code") or "")
            ):
                raise self._integrity("mcp_tool_resource_binding_stale")
            result.append(row)
        return result

    def _validate_resource(
        self, resource_kind: str | None, deployment_id: str
    ) -> dict[str, Any] | None:
        if resource_kind is None:
            if deployment_id:
                raise ValueError("ONES MCP Tools cannot bind a shared Resource")
            return None
        if not deployment_id:
            raise ValueError("Data MCP Tools require an exact Resource Deployment")
        row = self.database.execute_one(
            """
            select d.id, d.resource_revision_id, d.status, r.code resource_code,
                   r.kind resource_kind, r.lifecycle_status, rr.revision_status,
                   g.status generation_status,
                   g.resource_revision_id generation_resource_revision_id
              from mcp_resource_deployment d
              join mcp_resource r on r.id = d.resource_id
              join mcp_resource_revision rr on rr.id = d.resource_revision_id
              left join mcp_resource_generation g on g.id = d.current_generation_id
             where d.id = ?
            """,
            (deployment_id,),
        )
        if row is None or any(
            (
                str(row["resource_kind"]) != resource_kind,
                str(row["status"]) != "ACTIVE",
                str(row["lifecycle_status"]) != "ENABLED",
                str(row["revision_status"]) != "PUBLISHED",
                str(row.get("generation_status") or "") != "ACTIVE",
                str(row.get("generation_resource_revision_id") or "")
                != str(row["resource_revision_id"]),
            )
        ):
            raise NonRetryableExecutionError(
                "MCP Tool Resource Deployment is unavailable or mismatched",
                safe_message="MCP Tool 绑定的资源发布不可用",
                error_code="mcp_tool_resource_unavailable",
            )
        return row

    def _detail_from_row(self, tool: dict[str, Any]) -> dict[str, Any]:
        draft = self.database.execute_one(
            "select * from mcp_tool_draft where tool_id = ? and status in ('DRAFT', 'VERIFIED') order by draft_revision desc limit 1",
            (tool["id"],),
        )
        history = self.database.execute(
            "select * from mcp_tool_publication where tool_id = ? order by revision desc",
            (tool["id"],),
        )
        return {
            **tool,
            "revision": int(tool["revision"]),
            "draft": (
                {**draft, "verification": _object(draft["verification_json"])} if draft else None
            ),
            "publications": [{**row, "revision": int(row["revision"])} for row in history],
        }

    def _tool(self, code: str) -> dict[str, Any]:
        row = self.database.execute_one("select * from mcp_tool where code = ?", (code,))
        if row is None:
            raise NotFound("MCP Tool not found", safe_message="MCP Tool 不存在")
        return row

    def _open_draft(
        self,
        code: str,
        *,
        expected_revision: int,
        status: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        tool = self._tool(code)
        self._require_editable(tool, expected_revision)
        statuses = (status,) if status else ("DRAFT", "VERIFIED")
        draft = self.database.execute_one(
            f"select * from mcp_tool_draft where tool_id = ? and status in ({','.join('?' for _ in statuses)}) order by draft_revision desc limit 1",
            (tool["id"], *statuses),
        )
        if draft is None or int(draft["expected_tool_revision"]) > expected_revision:
            raise NotFound("MCP Tool draft not found", safe_message="MCP Tool 草稿不存在")
        return tool, draft

    @staticmethod
    def _draft_payload(catalog_key: str, resource_deployment_id: str) -> dict[str, str]:
        return {
            "catalog_key": catalog_key,
            "resource_deployment_id": resource_deployment_id,
        }

    @staticmethod
    def _code(code: str) -> str:
        if not _CODE.fullmatch(code):
            raise ValueError("MCP Tool code is invalid")
        return code

    @staticmethod
    def _require_editable(tool: dict[str, Any], expected_revision: int) -> None:
        if int(tool["revision"]) != expected_revision:
            raise McpToolPublicationService._conflict(int(tool["revision"]))
        if str(tool["lifecycle_status"]) != "ENABLED":
            raise NonRetryableExecutionError(
                "MCP Tool is not enabled",
                safe_message="MCP Tool 已停用",
                error_code="mcp_tool_disabled",
            )

    def _bump(self, tool: dict[str, Any], expected_revision: int, timestamp: str) -> None:
        rows = self.database.execute(
            "update mcp_tool set revision = revision + 1, updated_at = ? where id = ? and revision = ? returning id",
            (timestamp, tool["id"], expected_revision),
        )
        if not rows:
            raise self._conflict()

    def _idempotent(
        self, key: str, operation: str, actor_id: str, request_hash: str
    ) -> dict[str, Any] | None:
        if not key:
            return None
        if len(key) > 128:
            raise ValueError("Idempotency key is required and bounded")
        row = self.database.execute_one(
            "select * from mcp_operation_idempotency where idempotency_key = ?", (key,)
        )
        if row is None:
            return None
        if (
            str(row["operation"]) != operation
            or str(row["actor_id"]) != actor_id
            or str(row["request_hash"]) != request_hash
        ):
            raise NonRetryableExecutionError(
                "MCP Tool idempotency conflict",
                safe_message="重复请求与原请求不一致",
                error_code="mcp_idempotency_conflict",
            )
        return _object(row["response_json"])

    def _remember(
        self,
        key: str,
        operation: str,
        actor_id: str,
        request_hash: str,
        response: dict[str, Any],
    ) -> None:
        if not key:
            return
        self.database.execute(
            """
            insert into mcp_operation_idempotency
              (idempotency_key, operation, actor_id, request_hash, response_json, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (key, operation, actor_id, request_hash, _json(response), now_iso()),
        )

    def _audit(
        self,
        event: str,
        actor_id: str,
        payload: dict[str, Any],
        *,
        status: str = "SUCCEEDED",
    ) -> None:
        if self.audit_service:
            self.audit_service.record(
                event,
                status=status,
                summary=event.replace(".", " "),
                actor_id=actor_id,
                payload=payload,
            )

    @staticmethod
    def _conflict(current_revision: int | None = None) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "MCP Tool revision conflict",
            safe_message="MCP Tool 已被其他操作修改，请刷新后重试",
            error_code="revision_conflict",
            diagnostics=(
                {"current_revision": current_revision} if current_revision is not None else {}
            ),
        )

    @staticmethod
    def _integrity(code: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "MCP Tool publication integrity check failed",
            safe_message="MCP Tool 发布完整性校验失败",
            error_code=code,
        )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
