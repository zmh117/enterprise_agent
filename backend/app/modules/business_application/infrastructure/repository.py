from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_value(value: object, fallback: Any) -> Any:
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return fallback


class BusinessApplicationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

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
        timestamp = now_iso()
        application_id = new_id("business_app")
        revision_id = new_id("business_app_revision")
        try:
            with self.database.unit_of_work():
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
                self.database.execute(
                    """
                    insert into business_application_revision
                      (id, application_id, revision, status, session_policy_json,
                       execution_policy_json, validation_json, created_by,
                       created_at, updated_at)
                    values (?, ?, 1, 'draft', '{}', '{}',
                            '{"valid":false,"errors":[]}', ?, ?, ?)
                    """,
                    (revision_id, application_id, actor_id, timestamp, timestamp),
                )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise NonRetryableExecutionError(
                    f"Business Application code already exists: {code}",
                    safe_message="业务应用编码已存在",
                    error_code="revision_conflict",
                ) from exc
            raise
        return self.get_by_code(code)

    def list_applications(
        self,
        *,
        project_codes: set[str] | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if not include_archived:
            clauses.append("a.status != 'archived'")
        if project_codes is not None:
            if not project_codes:
                return []
            placeholders = ",".join("?" for _ in project_codes)
            clauses.append(f"a.project_code in ({placeholders})")
            params.extend(sorted(project_codes))
        where = f"where {' and '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        rows = self.database.execute(
            f"""
            select a.*,
                   (select max(p.revision)
                      from business_application_publication p
                     where p.application_id = a.id) as latest_publication_revision,
                   coalesce(
                     (select r.task_workspace_retention_period
                        from business_application_revision r
                       where r.application_id = a.id
                       order by r.revision desc limit 1),
                     'WEEK'
                   ) as task_workspace_retention_period,
                   coalesce(
                     (select r.document_processing_profile_code
                        from business_application_revision r
                       where r.application_id = a.id
                       order by r.revision desc limit 1),
                     'NONE'
                   ) as document_processing_profile_code
              from business_application a
              {where}
             order by a.updated_at desc, a.code
             limit ? offset ?
            """,
            params,
        )
        return [self._application(row, include_draft=False) for row in rows]

    def get_by_code(self, code: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from business_application where code = ?", (code,)
        )
        if row is None:
            raise NotFound(
                f"Business Application not found: {code}",
                safe_message="未找到业务应用",
            )
        return self._application(row, include_draft=True)

    def get_by_id(self, application_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from business_application where id = ?", (application_id,)
        )
        if row is None:
            raise NotFound(
                f"Business Application not found: {application_id}",
                safe_message="未找到业务应用",
            )
        return self._application(row, include_draft=True)

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
        application = self.get_by_code(code)
        self._expect_revision(application, expected_revision)
        if status == "archived" and self.has_active_deployment(str(application["id"])):
            raise NonRetryableExecutionError(
                "Cannot archive an active Business Application",
                safe_message="归档前请先停用所有环境",
                error_code="application_active",
            )
        next_revision = expected_revision + 1
        self.database.execute(
            """
            update business_application
               set name = ?, description = ?, project_code = ?,
                   owner_user_id = ?, status = ?, revision = ?, updated_at = ?
             where id = ? and revision = ?
            """,
            (
                name,
                description,
                project_code,
                owner_user_id or None,
                status,
                next_revision,
                now_iso(),
                application["id"],
                expected_revision,
            ),
        )
        refreshed = self.get_by_code(code)
        if int(refreshed["revision"]) != next_revision:
            raise self.revision_conflict(int(refreshed["revision"]))
        return refreshed

    def save_revision(
        self,
        *,
        code: str,
        expected_revision: int,
        agent_publication_id: str,
        workflow_publication_id: str,
        task_workspace_retention_period: str,
        file_format_policy_version: str,
        document_processing_profile_code: str,
        task_file_features: dict[str, bool],
        session_policy: dict[str, Any],
        execution_policy: dict[str, Any],
        triggers: list[dict[str, Any]],
        deliveries: list[dict[str, Any]],
        config_hash: str,
        actor_id: str,
    ) -> dict[str, Any]:
        application = self.get_by_code(code)
        self._expect_revision(application, expected_revision)
        next_revision = expected_revision + 1
        revision_id = new_id("business_app_revision")
        timestamp = now_iso()
        with self.database.unit_of_work():
            self.database.execute(
                """
                update business_application
                   set revision = ?, updated_at = ?
                 where id = ? and revision = ?
                """,
                (next_revision, timestamp, application["id"], expected_revision),
            )
            changed = self.database.execute_one(
                "select revision from business_application where id = ?",
                (application["id"],),
            )
            if changed is None or int(changed["revision"]) != next_revision:
                raise self.revision_conflict(int(changed["revision"]) if changed else 0)
            self.database.execute(
                """
                insert into business_application_revision
                  (id, application_id, revision, status, agent_publication_id,
                   workflow_publication_id, task_workspace_retention_period,
                   file_format_policy_version,
                   document_processing_profile_code,
                   task_file_features_json,
                   session_policy_json,
                   execution_policy_json, validation_json, config_hash,
                   created_by, created_at, updated_at)
                values (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?,
                        '{"valid":false,"errors":[]}', ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    application["id"],
                    next_revision,
                    agent_publication_id or None,
                    workflow_publication_id or None,
                    task_workspace_retention_period,
                    file_format_policy_version,
                    document_processing_profile_code,
                    json_text(task_file_features),
                    json_text(session_policy),
                    json_text(execution_policy),
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
                        new_id("business_app_trigger"),
                        revision_id,
                        index,
                        trigger["trigger_type"],
                        trigger["connector_id"],
                        trigger["routing_key"],
                        trigger["normalized_routing_key"],
                        trigger["actor_policy"],
                        trigger["service_account_user_id"] or None,
                        int(bool(trigger["enabled"])),
                        json_text(trigger["config"]),
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
                        new_id("business_app_delivery"),
                        revision_id,
                        index,
                        delivery["delivery_type"],
                        delivery["connector_id"],
                        int(bool(delivery["enabled"])),
                        json_text(delivery["config"]),
                        timestamp,
                    ),
                )
        return self.get_revision(revision_id)

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from business_application_revision where id = ?", (revision_id,)
        )
        if row is None:
            raise NotFound(
                f"Business Application revision not found: {revision_id}",
                safe_message="未找到业务应用修订版本",
            )
        return self._revision(row)

    def latest_revision(self, application_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from business_application_revision
             where application_id = ?
             order by revision desc limit 1
            """,
            (application_id,),
        )
        return self._revision(row) if row else None

    def list_revisions(self, application_id: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select * from business_application_revision
             where application_id = ? order by revision desc
            """,
            (application_id,),
        )
        return [self._revision(row) for row in rows]

    def set_validation(
        self, revision_id: str, *, valid: bool, errors: list[dict[str, str]]
    ) -> dict[str, Any]:
        self.database.execute(
            """
            update business_application_revision
               set status = ?, validation_json = ?, updated_at = ?
             where id = ?
            """,
            (
                "validated" if valid else "draft",
                json_text({"valid": valid, "errors": errors}),
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
    ) -> dict[str, Any]:
        existing = self.database.execute_one(
            """
            select * from business_application_publication
             where application_id = ? and revision = ?
            """,
            (application_id, revision),
        )
        if existing:
            return self._publication(existing)
        publication_id = new_id("business_app_publication")
        timestamp = now_iso()
        with self.database.unit_of_work():
            self.database.execute(
                """
                insert into business_application_publication
                  (id, application_id, revision_id, revision, schema_version,
                   task_workspace_retention_period, file_format_policy_version,
                   document_processing_profile_code,
                   document_processing_profile_version,
                   document_processing_profile_hash,
                   snapshot_json, config_hash,
                   task_file_features_json,
                   published_by, published_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    publication_id,
                    application_id,
                    revision_id,
                    revision,
                    int(snapshot["schema_version"]),
                    str(snapshot["task_workspace_retention_period"]),
                    str(snapshot["file_format_policy_version"]),
                    str(snapshot["document_processing_profile"]["code"]),
                    str(snapshot["document_processing_profile"]["version"]),
                    str(snapshot["document_processing_profile"]["hash"]),
                    json_text(snapshot),
                    config_hash,
                    json_text(snapshot["task_file_features"]),
                    actor_id,
                    timestamp,
                ),
            )
            self.database.execute(
                """
                update business_application_revision
                   set status = 'published', updated_at = ?
                 where id = ?
                """,
                (timestamp, revision_id),
            )
        return self.get_publication(publication_id)

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

    def list_publications(self, application_id: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select * from business_application_publication
             where application_id = ? order by revision desc
            """,
            (application_id,),
        )
        return [self._publication(row) for row in rows]

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

    def get_deployment(self, application_id: str, environment: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from business_application_deployment
             where application_id = ? and environment = ?
            """,
            (application_id, environment),
        )
        return self._deployment(row) if row else None

    def activate(
        self,
        *,
        application_id: str,
        environment: str,
        publication_id: str,
        expected_revision: int,
        actor_id: str,
        routes: list[dict[str, str]],
    ) -> dict[str, Any]:
        existing = self.get_deployment(application_id, environment)
        if (
            existing
            and bool(existing["active"])
            and str(existing["publication_id"]) == publication_id
        ):
            return existing
        current_revision = int(existing["revision"]) if existing else 0
        if current_revision != expected_revision:
            raise self.revision_conflict(current_revision)
        timestamp = now_iso()
        deployment_id = str(existing["id"]) if existing else new_id("business_app_deployment")
        try:
            with self.database.unit_of_work():
                if existing:
                    self.database.execute(
                        """
                        update business_application_deployment
                           set publication_id = ?, active = 1, revision = ?,
                               activated_by = ?, activated_at = ?,
                               deactivated_by = '', deactivated_at = null,
                               updated_at = ?
                         where id = ? and revision = ?
                        """,
                        (
                            publication_id,
                            expected_revision + 1,
                            actor_id,
                            timestamp,
                            timestamp,
                            deployment_id,
                            expected_revision,
                        ),
                    )
                else:
                    self.database.execute(
                        """
                        insert into business_application_deployment
                          (id, application_id, environment, publication_id, active,
                           revision, activated_by, activated_at, updated_at)
                        values (?, ?, ?, ?, 1, 1, ?, ?, ?)
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
                self.database.execute(
                    "delete from business_application_active_route where deployment_id = ?",
                    (deployment_id,),
                )
                for route in routes:
                    self.database.execute(
                        """
                        insert into business_application_active_route
                          (id, deployment_id, application_id, publication_id,
                           environment, trigger_type, connector_id,
                           normalized_routing_key, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_id("business_app_route"),
                            deployment_id,
                            application_id,
                            publication_id,
                            environment,
                            route["trigger_type"],
                            route["connector_id"],
                            route["normalized_routing_key"],
                            timestamp,
                        ),
                    )
        except Exception as exc:
            if "unique" in str(exc).lower():
                conflict = self.find_route(
                    environment=environment,
                    trigger_type=routes[0]["trigger_type"] if routes else "",
                    connector_id=routes[0]["connector_id"] if routes else "",
                    normalized_routing_key=(routes[0]["normalized_routing_key"] if routes else ""),
                )
                raise NonRetryableExecutionError(
                    "Business Application route is already active",
                    safe_message="触发器路由已被其他业务应用使用",
                    error_code="route_conflict",
                    diagnostics={"conflict_application_id": (conflict or {}).get("application_id")},
                ) from exc
            raise
        result = self.get_deployment(application_id, environment)
        if result is None:
            raise RuntimeError("Deployment activation did not persist")
        return result

    def deactivate(
        self,
        *,
        application_id: str,
        environment: str,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        existing = self.get_deployment(application_id, environment)
        if existing is None:
            raise NotFound(
                "Business Application deployment not found",
                safe_message="未找到业务应用部署",
            )
        self._expect_revision(existing, expected_revision)
        timestamp = now_iso()
        with self.database.unit_of_work():
            self.database.execute(
                "delete from business_application_active_route where deployment_id = ?",
                (existing["id"],),
            )
            self.database.execute(
                """
                update business_application_deployment
                   set active = 0, revision = ?, deactivated_by = ?,
                       deactivated_at = ?, updated_at = ?
                 where id = ? and revision = ?
                """,
                (
                    expected_revision + 1,
                    actor_id,
                    timestamp,
                    timestamp,
                    existing["id"],
                    expected_revision,
                ),
            )
        result = self.get_deployment(application_id, environment)
        if result is None:
            raise RuntimeError("Deployment deactivation did not persist")
        return result

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

    def has_active_deployment(self, application_id: str) -> bool:
        return (
            self.database.execute_one(
                """
                select id from business_application_deployment
                 where application_id = ? and active = 1 limit 1
                """,
                (application_id,),
            )
            is not None
        )

    @staticmethod
    def revision_conflict(current_revision: int) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "Business Application revision conflict",
            safe_message="业务应用已被其他管理员修改，请刷新后重试",
            error_code="revision_conflict",
            diagnostics={"current_revision": current_revision},
        )

    def _expect_revision(self, resource: dict[str, Any], expected_revision: int) -> None:
        current = int(resource["revision"])
        if current != expected_revision:
            raise self.revision_conflict(current)

    def _application(self, row: dict[str, Any], *, include_draft: bool) -> dict[str, Any]:
        value = {
            **row,
            "owner_user_id": str(row.get("owner_user_id") or ""),
            "revision": int(row["revision"]),
        }
        if include_draft:
            value["draft"] = self.latest_revision(str(row["id"]))
            value["publications"] = self.list_publications(str(row["id"]))
            value["deployments"] = self.list_deployments(str(row["id"]))
            value["task_workspace_retention_period"] = str(
                (value["draft"] or {}).get("task_workspace_retention_period", "WEEK")
            )
            value["file_format_policy_version"] = str(
                (value["draft"] or {}).get("file_format_policy_version", "text-v1")
            )
            value["document_processing_profile_code"] = str(
                (value["draft"] or {}).get("document_processing_profile_code", "NONE")
            )
        else:
            value["task_workspace_retention_period"] = str(
                row.get("task_workspace_retention_period") or "WEEK"
            )
            value["file_format_policy_version"] = str(
                row.get("file_format_policy_version") or "text-v1"
            )
            value["document_processing_profile_code"] = str(
                row.get("document_processing_profile_code") or "NONE"
            )
        return value

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
        mcp_tools = self.database.execute(
            """
            select server_code, tool_identifier, schema_hash, selection_order
              from business_application_revision_mcp_tool
             where application_revision_id = ?
             order by selection_order
            """,
            (revision_id,),
        )
        return {
            **row,
            "revision": int(row["revision"]),
            "agent_publication_id": str(row.get("agent_publication_id") or ""),
            "workflow_publication_id": str(row.get("workflow_publication_id") or ""),
            "task_workspace_retention_period": str(
                row.get("task_workspace_retention_period") or "WEEK"
            ),
            "file_format_policy_version": str(row.get("file_format_policy_version") or "text-v1"),
            "document_processing_profile_code": str(
                row.get("document_processing_profile_code") or "NONE"
            ),
            "task_file_features": json_value(
                row.get("task_file_features_json"),
                {
                    "default_file_delivery_enabled": False,
                    "file_mcp_enabled": False,
                    "runtime_file_edit_enabled": False,
                    "workspace_enabled": False,
                },
            ),
            "session_policy": json_value(row.get("session_policy_json"), {}),
            "execution_policy": json_value(row.get("execution_policy_json"), {}),
            "validation": json_value(row.get("validation_json"), {"valid": False, "errors": []}),
            "triggers": [
                {
                    **item,
                    "binding_order": int(item["binding_order"]),
                    "enabled": bool(item["enabled"]),
                    "service_account_user_id": str(item.get("service_account_user_id") or ""),
                    "config": json_value(item.get("config_json"), {}),
                }
                for item in triggers
            ],
            "deliveries": [
                {
                    **item,
                    "binding_order": int(item["binding_order"]),
                    "enabled": bool(item["enabled"]),
                    "config": json_value(item.get("config_json"), {}),
                }
                for item in deliveries
            ],
            "mcp_tools": [
                {
                    **tool,
                    "selection_order": int(tool["selection_order"]),
                }
                for tool in mcp_tools
            ],
        }

    @staticmethod
    def _publication(row: dict[str, Any]) -> dict[str, Any]:
        snapshot = json_value(row.get("snapshot_json"), {})
        source = (
            "publication_snapshot"
            if "task_workspace_retention_period" in snapshot
            else "legacy_default"
        )
        feature_source = (
            "publication_snapshot" if "task_file_features" in snapshot else "legacy_default"
        )
        policy_source = (
            "publication_snapshot" if "file_format_policy_version" in snapshot else "legacy_default"
        )
        document_profile = snapshot.get("document_processing_profile")
        document_profile_source = (
            "publication_snapshot"
            if isinstance(document_profile, dict)
            else "legacy_default"
        )
        if not isinstance(document_profile, dict):
            document_profile = {"code": "NONE", "version": "", "hash": ""}
        task_file_features = snapshot.get("task_file_features") or {
            "default_file_delivery_enabled": False,
            "file_mcp_enabled": False,
            "runtime_file_edit_enabled": False,
            "workspace_enabled": False,
        }
        return {
            **row,
            "revision": int(row["revision"]),
            "schema_version": int(row["schema_version"]),
            "snapshot": snapshot,
            "task_workspace_retention_period": str(
                snapshot.get("task_workspace_retention_period") or "WEEK"
            ),
            "task_workspace_retention_source": source,
            "file_format_policy_version": str(
                snapshot.get("file_format_policy_version") or "text-v1"
            ),
            "file_format_policy_source": policy_source,
            "document_processing_profile_code": str(document_profile.get("code") or "NONE"),
            "document_processing_profile_version": str(document_profile.get("version") or ""),
            "document_processing_profile_hash": str(document_profile.get("hash") or ""),
            "document_processing_profile_source": document_profile_source,
            "task_file_features": task_file_features,
            "task_file_features_source": feature_source,
        }

    @staticmethod
    def _deployment(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "publication_id": str(row.get("publication_id") or ""),
            "active": bool(row["active"]),
            "revision": int(row["revision"]),
            "activated_at": str(row.get("activated_at") or ""),
            "deactivated_at": str(row.get("deactivated_at") or ""),
        }
