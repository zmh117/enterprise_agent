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
            with self.database.transaction():
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
                    safe_message="Business Application code already exists",
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
                     where p.application_id = a.id) as latest_publication_revision
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
                safe_message="Business Application not found",
            )
        return self._application(row, include_draft=True)

    def get_by_id(self, application_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from business_application where id = ?", (application_id,)
        )
        if row is None:
            raise NotFound(
                f"Business Application not found: {application_id}",
                safe_message="Business Application not found",
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
                safe_message="Deactivate all environments before archiving",
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
        session_policy: dict[str, Any],
        execution_policy: dict[str, Any],
        triggers: list[dict[str, Any]],
        deliveries: list[dict[str, Any]],
        capabilities: list[dict[str, Any]],
        config_hash: str,
        actor_id: str,
    ) -> dict[str, Any]:
        application = self.get_by_code(code)
        self._expect_revision(application, expected_revision)
        next_revision = expected_revision + 1
        revision_id = new_id("business_app_revision")
        timestamp = now_iso()
        with self.database.transaction():
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
                   workflow_publication_id, session_policy_json,
                   execution_policy_json, validation_json, config_hash,
                   created_by, created_at, updated_at)
                values (?, ?, ?, 'draft', ?, ?, ?, ?,
                        '{"valid":false,"errors":[]}', ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    application["id"],
                    next_revision,
                    agent_publication_id or None,
                    workflow_publication_id or None,
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
            for index, capability in enumerate(capabilities):
                self.database.execute(
                    """
                    insert into business_application_revision_capability
                      (id, revision_id, binding_order, capability_code,
                       version_constraint, enabled, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("business_app_capability"),
                        revision_id,
                        index,
                        capability["capability_code"],
                        capability["version_constraint"],
                        int(bool(capability["enabled"])),
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
                safe_message="Business Application revision not found",
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
        with self.database.transaction():
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
                    json_text(snapshot),
                    config_hash,
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
                safe_message="Business Application publication not found",
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

    def get_deployment(
        self, application_id: str, environment: str
    ) -> dict[str, Any] | None:
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
            with self.database.transaction():
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
                    normalized_routing_key=(
                        routes[0]["normalized_routing_key"] if routes else ""
                    ),
                )
                raise NonRetryableExecutionError(
                    "Business Application route is already active",
                    safe_message="Trigger route is already used by another application",
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
                safe_message="Business Application deployment not found",
            )
        self._expect_revision(existing, expected_revision)
        timestamp = now_iso()
        with self.database.transaction():
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
            safe_message="Business Application was changed by another administrator",
            error_code="revision_conflict",
            diagnostics={"current_revision": current_revision},
        )

    def _expect_revision(self, resource: dict[str, Any], expected_revision: int) -> None:
        current = int(resource["revision"])
        if current != expected_revision:
            raise self.revision_conflict(current)

    def _application(
        self, row: dict[str, Any], *, include_draft: bool
    ) -> dict[str, Any]:
        value = {
            **row,
            "owner_user_id": str(row.get("owner_user_id") or ""),
            "revision": int(row["revision"]),
        }
        if include_draft:
            value["draft"] = self.latest_revision(str(row["id"]))
            value["publications"] = self.list_publications(str(row["id"]))
            value["deployments"] = self.list_deployments(str(row["id"]))
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
        capabilities = self.database.execute(
            """
            select * from business_application_revision_capability
             where revision_id = ? order by binding_order
            """,
            (revision_id,),
        )
        return {
            **row,
            "revision": int(row["revision"]),
            "agent_publication_id": str(row.get("agent_publication_id") or ""),
            "workflow_publication_id": str(row.get("workflow_publication_id") or ""),
            "session_policy": json_value(row.get("session_policy_json"), {}),
            "execution_policy": json_value(row.get("execution_policy_json"), {}),
            "validation": json_value(row.get("validation_json"), {"valid": False, "errors": []}),
            "triggers": [
                {
                    **item,
                    "binding_order": int(item["binding_order"]),
                    "enabled": bool(item["enabled"]),
                    "service_account_user_id": str(
                        item.get("service_account_user_id") or ""
                    ),
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
            "capabilities": [
                {
                    **item,
                    "binding_order": int(item["binding_order"]),
                    "enabled": bool(item["enabled"]),
                }
                for item in capabilities
            ],
        }

    @staticmethod
    def _publication(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "revision": int(row["revision"]),
            "schema_version": int(row["schema_version"]),
            "snapshot": json_value(row.get("snapshot_json"), {}),
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
