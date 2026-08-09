from __future__ import annotations

import json
from typing import Any

from app.shared.database import Database
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.exceptions import NonRetryableExecutionError, NotFound


class BusinessApplicationRepository:
    """Persist governed Application drafts and read immutable routing publications."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def get_by_code(self, code: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from business_application where code = ?", (code,)
        )
        if row is None:
            raise NotFound(
                f"Business Application not found: {code}",
                safe_message="未找到业务应用",
            )
        return self._application(row)

    def list_applications(
        self,
        *,
        project_code: str = "",
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[object] = []
        if project_code:
            clauses.append("a.project_code = ?")
            params.append(project_code)
        if not include_archived:
            clauses.append("a.status <> 'archived'")
        where = f"where {' and '.join(clauses)}" if clauses else ""
        rows = self.database.execute(
            f"""
            select a.*,
                   (select max(p.revision) from business_application_publication p
                     where p.application_id = a.id) latest_publication_revision
              from business_application a
              {where}
             order by a.code
             limit ? offset ?
            """,
            tuple([*params, limit, offset]),
        )
        return [self._with_deployment_summary(self._application(row)) for row in rows]

    def create(
        self,
        *,
        code: str,
        name: str,
        description: str,
        project_code: str,
        owner_user_id: str,
        actor_id: str,
    ) -> dict[str, Any]:
        application_id = new_id("business_application")
        timestamp = now_iso()
        try:
            self.database.execute(
                """
                insert into business_application
                  (id, code, name, description, project_code, owner_user_id,
                   status, revision, created_by, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, 'enabled', 1, ?, ?, ?)
                """,
                (
                    application_id,
                    code,
                    name,
                    description,
                    project_code,
                    owner_user_id or None,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
        except Exception as exc:
            if self.database.execute_one(
                "select id from business_application where code = ?", (code,)
            ):
                raise NonRetryableExecutionError(
                    "Business Application code already exists",
                    safe_message="业务应用编码已存在",
                    error_code="application_code_conflict",
                ) from exc
            raise
        return self.get_by_code(code)

    def update_metadata(
        self,
        *,
        code: str,
        expected_revision: int,
        name: str,
        description: str,
        project_code: str,
        owner_user_id: str,
        status: str,
    ) -> dict[str, Any]:
        rows = self.database.execute(
            """
            update business_application
               set name = ?, description = ?, project_code = ?, owner_user_id = ?,
                   status = ?, revision = revision + 1, updated_at = ?
             where code = ? and revision = ?
            returning id
            """,
            (
                name,
                description,
                project_code,
                owner_user_id or None,
                status,
                now_iso(),
                code,
                expected_revision,
            ),
        )
        if not rows:
            raise self._conflict()
        return self.get_by_code(code)

    def get_by_id(self, application_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from business_application where id = ?", (application_id,)
        )
        if row is None:
            raise NotFound(
                f"Business Application not found: {application_id}",
                safe_message="未找到业务应用",
            )
        return self._application(row)

    def get_publication(self, publication_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from business_application_publication where id = ?",
            (publication_id,),
        )
        if row is None:
            raise NotFound(
                f"Business Application publication not found: {publication_id}",
                safe_message="未找到业务应用发布版本",
            )
        return self._publication(row)

    def latest_revision(self, application_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from business_application_revision
             where application_id = ? order by revision desc limit 1
            """,
            (application_id,),
        )
        return self._revision(row) if row else None

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from business_application_revision where id = ?",
            (revision_id,),
        )
        if row is None:
            raise NotFound(
                "Business Application revision not found",
                safe_message="未找到业务应用修订版本",
            )
        return self._revision(row)

    def save_revision(
        self,
        *,
        application: dict[str, Any],
        expected_revision: int,
        actor_id: str,
        config_hash: str,
        agent_publication_id: str,
        session_policy: dict[str, Any],
        execution_policy: dict[str, Any],
        triggers: list[dict[str, Any]],
        deliveries: list[dict[str, Any]],
        mcp_tool_publication_ids: list[str],
    ) -> dict[str, Any]:
        if int(application["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Business Application revision conflict",
                safe_message="业务应用已发生变化，请刷新后重试",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(application["revision"])},
            )
        revision_number = int(
            (
                self.database.execute_one(
                    "select coalesce(max(revision), 0) + 1 value from business_application_revision where application_id = ?",
                    (application["id"],),
                )
                or {"value": 1}
            )["value"]
        )
        revision_id = new_id("business_application_revision")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into business_application_revision
              (id, application_id, revision, status, agent_publication_id,
               workflow_publication_id, session_policy_json, execution_policy_json,
               validation_json, config_hash, created_by, created_at, updated_at)
            values (?, ?, ?, 'draft', ?, null, ?, ?,
                    '{"valid":false,"errors":[]}', ?, ?, ?, ?)
            """,
            (
                revision_id,
                application["id"],
                revision_number,
                agent_publication_id,
                json.dumps(session_policy, ensure_ascii=False, sort_keys=True),
                json.dumps(execution_policy, ensure_ascii=False, sort_keys=True),
                config_hash,
                actor_id,
                timestamp,
                timestamp,
            ),
        )
        for index, trigger in enumerate(triggers):
            self.database.execute(
                """
                insert into business_application_revision_trigger
                  (id, revision_id, binding_order, trigger_type, connector_id,
                   routing_key, normalized_routing_key, actor_policy,
                   service_account_user_id, enabled, config_json, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("application_trigger"),
                    revision_id,
                    index,
                    trigger["trigger_type"],
                    trigger["connector_id"],
                    trigger["routing_key"],
                    trigger["normalized_routing_key"],
                    trigger["actor_policy"],
                    trigger.get("service_account_user_id") or None,
                    1 if trigger.get("enabled", True) else 0,
                    json.dumps(trigger.get("config") or {}, ensure_ascii=False, sort_keys=True),
                    timestamp,
                ),
            )
        for index, delivery in enumerate(deliveries):
            self.database.execute(
                """
                insert into business_application_revision_delivery
                  (id, revision_id, binding_order, delivery_type, connector_id,
                   enabled, config_json, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("application_delivery"),
                    revision_id,
                    index,
                    delivery["delivery_type"],
                    delivery["connector_id"],
                    1 if delivery.get("enabled", True) else 0,
                    json.dumps(delivery.get("config") or {}, ensure_ascii=False, sort_keys=True),
                    timestamp,
                ),
            )
        for index, publication_id in enumerate(dict.fromkeys(mcp_tool_publication_ids)):
            self.database.execute(
                """
                insert into business_application_revision_mcp_tool
                  (application_revision_id, tool_publication_id, binding_order)
                values (?, ?, ?)
                """,
                (revision_id, publication_id, index),
            )
        rows = self.database.execute(
            """
            update business_application
               set revision = revision + 1, updated_at = ?
             where id = ? and revision = ?
            returning id
            """,
            (timestamp, application["id"], expected_revision),
        )
        if not rows:
            raise self._conflict()
        return self.get_revision(revision_id)

    def set_validation(
        self, revision_id: str, *, valid: bool, errors: list[dict[str, str]]
    ) -> dict[str, Any]:
        self.database.execute(
            """
            update business_application_revision
               set status = case when status = 'published' then 'published' else ? end,
                   validation_json = ?, updated_at = ?
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

    def create_publication(
        self,
        *,
        application_id: str,
        revision_id: str,
        revision: int,
        snapshot: dict[str, Any],
        config_hash: str,
        actor_id: str,
        tool_publication_ids: list[str],
    ) -> dict[str, Any]:
        existing = self.database.execute_one(
            "select * from business_application_publication where revision_id = ?",
            (revision_id,),
        )
        if existing:
            publication = self._publication(existing)
            if str(publication["config_hash"]) != config_hash:
                raise NonRetryableExecutionError(
                    "Application publication is immutable",
                    safe_message="业务应用修订版本已使用不同内容发布",
                    error_code="publication_binding_conflict",
                )
            return publication
        publication_id = new_id("business_application_publication")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into business_application_publication
              (id, application_id, revision_id, revision, schema_version,
               snapshot_json, config_hash, published_by, published_at)
            values (?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                publication_id,
                application_id,
                revision_id,
                revision,
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                config_hash,
                actor_id,
                timestamp,
            ),
        )
        for tool_publication_id in dict.fromkeys(tool_publication_ids):
            self.database.execute(
                """
                insert into business_application_publication_mcp_tool
                  (application_publication_id, tool_publication_id)
                values (?, ?)
                """,
                (publication_id, tool_publication_id),
            )
        self.database.execute(
            """
            update business_application_revision
               set status = 'published', updated_at = ? where id = ?
            """,
            (timestamp, revision_id),
        )
        return self.get_publication(publication_id)

    def list_publications(self, application_id: str) -> list[dict[str, Any]]:
        return [
            self._publication(row)
            for row in self.database.execute(
                """
                select * from business_application_publication
                 where application_id = ? order by revision desc
                """,
                (application_id,),
            )
        ]

    def list_deployments(self, application_id: str) -> list[dict[str, Any]]:
        return [
            self._deployment(row)
            for row in self.database.execute(
                """
                select * from business_application_deployment
                 where application_id = ? order by environment
                """,
                (application_id,),
            )
        ]

    def activate(
        self,
        *,
        application_id: str,
        environment: str,
        publication_id: str,
        expected_revision: int,
        actor_id: str,
        triggers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        current = self.get_deployment(application_id, environment)
        actual_revision = int((current or {}).get("revision") or 0)
        if actual_revision != expected_revision:
            raise self._conflict()
        timestamp = now_iso()
        deployment_id = str((current or {}).get("id") or new_id("application_deployment"))
        if current is None:
            self.database.execute(
                """
                insert into business_application_deployment
                  (id, application_id, environment, publication_id, active,
                   revision, activated_by, activated_at, deactivated_by,
                   deactivated_at, updated_at)
                values (?, ?, ?, ?, 1, 1, ?, ?, '', null, ?)
                """,
                (
                    deployment_id,
                    application_id,
                    environment,
                    publication_id,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
        else:
            rows = self.database.execute(
                """
                update business_application_deployment
                   set publication_id = ?, active = 1, revision = revision + 1,
                       activated_by = ?, activated_at = ?, deactivated_by = '',
                       deactivated_at = null, updated_at = ?
                 where id = ? and revision = ?
                returning id
                """,
                (
                    publication_id,
                    actor_id,
                    timestamp,
                    timestamp,
                    deployment_id,
                    expected_revision,
                ),
            )
            if not rows:
                raise self._conflict()
        self.database.execute(
            "delete from business_application_active_route where deployment_id = ?",
            (deployment_id,),
        )
        for trigger in triggers:
            if not trigger.get("enabled", True):
                continue
            try:
                self.database.execute(
                    """
                    insert into business_application_active_route
                      (id, deployment_id, application_id, publication_id, environment,
                       trigger_type, connector_id, normalized_routing_key, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("application_route"),
                        deployment_id,
                        application_id,
                        publication_id,
                        environment,
                        trigger["trigger_type"],
                        trigger["connector_id"],
                        trigger["normalized_routing_key"],
                        timestamp,
                    ),
                )
            except Exception as exc:
                raise NonRetryableExecutionError(
                    "Business Application route conflict",
                    safe_message="已有其他活动应用使用相同入口路由",
                    error_code="route_conflict",
                ) from exc
        deployment = self.get_deployment(application_id, environment)
        assert deployment is not None
        return deployment

    def deactivate(
        self,
        *,
        application_id: str,
        environment: str,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.get_deployment(application_id, environment)
        if current is None:
            raise NotFound("Deployment not found", safe_message="未找到应用环境部署")
        rows = self.database.execute(
            """
            update business_application_deployment
               set active = 0, revision = revision + 1, deactivated_by = ?,
                   deactivated_at = ?, updated_at = ?
             where id = ? and revision = ? and active = 1
            returning id
            """,
            (actor_id, now_iso(), now_iso(), current["id"], expected_revision),
        )
        if not rows:
            raise self._conflict()
        self.database.execute(
            "delete from business_application_active_route where deployment_id = ?",
            (current["id"],),
        )
        deployment = self.get_deployment(application_id, environment)
        assert deployment is not None
        return deployment

    def get_deployment(
        self,
        application_id: str,
        environment: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from business_application_deployment
             where application_id = ? and environment = ?
            """,
            (application_id, environment),
        )
        if row is None:
            return None
        return {
            **row,
            "active": bool(row.get("active")),
            "revision": int(row.get("revision") or 0),
        }

    def find_route(
        self,
        *,
        environment: str,
        trigger_type: str,
        connector_id: str,
        normalized_routing_key: str,
    ) -> dict[str, Any] | None:
        return self.database.execute_one(
            """
            select * from business_application_active_route
             where environment = ? and trigger_type = ? and connector_id = ?
               and normalized_routing_key = ?
            """,
            (environment, trigger_type, connector_id, normalized_routing_key),
        )

    @staticmethod
    def _application(row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "revision": int(row.get("revision") or 0)}

    def _with_deployment_summary(self, application: dict[str, Any]) -> dict[str, Any]:
        deployments = self.list_deployments(str(application["id"]))
        return {
            **application,
            "active_environments": [
                str(value["environment"]) for value in deployments if value["active"]
            ],
        }

    def detail(self, code: str) -> dict[str, Any]:
        application = self.get_by_code(code)
        application_id = str(application["id"])
        return {
            **self._with_deployment_summary(application),
            "draft": self.latest_revision(application_id),
            "publications": self.list_publications(application_id),
            "deployments": self.list_deployments(application_id),
        }

    def _revision(self, row: dict[str, Any]) -> dict[str, Any]:
        revision_id = str(row["id"])
        triggers = self.database.execute(
            """
            select * from business_application_revision_trigger
             where revision_id = ? order by binding_order
            """,
            (revision_id,),
        )
        deliveries = self.database.execute(
            """
            select * from business_application_revision_delivery
             where revision_id = ? order by binding_order
            """,
            (revision_id,),
        )
        tools = self.database.execute(
            """
            select tool_publication_id from business_application_revision_mcp_tool
             where application_revision_id = ? order by binding_order
            """,
            (revision_id,),
        )
        return {
            **row,
            "revision": int(row["revision"]),
            "agent_publication_id": str(row.get("agent_publication_id") or ""),
            "session_policy": self._json(row.get("session_policy_json")),
            "execution_policy": self._json(row.get("execution_policy_json")),
            "validation": self._json(row.get("validation_json")),
            "triggers": [
                {
                    **item,
                    "enabled": bool(item.get("enabled")),
                    "service_account_user_id": str(item.get("service_account_user_id") or ""),
                    "config": self._json(item.get("config_json")),
                }
                for item in triggers
            ],
            "deliveries": [
                {
                    **item,
                    "enabled": bool(item.get("enabled")),
                    "config": self._json(item.get("config_json")),
                }
                for item in deliveries
            ],
            "mcp_tool_publication_ids": [str(item["tool_publication_id"]) for item in tools],
        }

    def _publication(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "revision": int(row["revision"]),
            "schema_version": int(row["schema_version"]),
            "snapshot": self._json(row.get("snapshot_json")),
        }

    @staticmethod
    def _deployment(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "active": bool(row.get("active")),
            "revision": int(row.get("revision") or 0),
            "publication_id": str(row.get("publication_id") or ""),
        }

    @staticmethod
    def _conflict() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "Business Application revision conflict",
            safe_message="业务应用已发生变化，请刷新后重试",
            error_code="revision_conflict",
        )

    @staticmethod
    def _json(raw: object) -> dict[str, Any]:
        try:
            value = json.loads(str(raw or "{}"))
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}
