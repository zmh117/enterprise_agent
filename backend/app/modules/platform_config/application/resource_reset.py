from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from typing import Any, Iterable

from app.modules.platform_config.infrastructure.repository import (
    json_text,
    new_id,
    now_iso,
)
from app.modules.platform_config.infrastructure.runtime_generation_repository import (
    RuntimeGenerationRepository,
)
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound


RESET_KINDS = ("database", "redis", "loki")
ACTIVE_RESET_STATES = (
    "PREPARING",
    "PREPARED",
    "CONFIRMED",
    "APPLYING",
)
ACTIVE_RESOURCE_JOB_STATES = (
    "WAITING_INPUT",
    "PENDING",
    "RUNNING",
    "RETRY_WAIT",
)
PROTECTED_COUNT_TABLES = (
    "platform_secret",
    "app_user",
    "rbac_role",
    "rbac_user_role",
    "business_application",
    "business_application_publication",
    "agent_job",
    "agent_job_execution_scope",
    "agent_job_execution_binding",
    "delivery_outbox",
    "audit_event",
    "handler_installation",
    "handler_publication",
    "platform_environment",
    "platform_base",
    "platform_workshop",
    "runtime_snapshot_generation",
)


def resource_reset_in_progress(database: Database) -> bool:
    placeholders = ", ".join("?" for _ in ACTIVE_RESET_STATES)
    row = database.execute_one(
        f"""
        select id
          from resource_reset_operation
         where status in ({placeholders})
         order by created_at desc
         limit 1
        """,
        ACTIVE_RESET_STATES,
    )
    return row is not None


class ResourceResetService:
    """Controlled report/prepare/apply/verify for DB, Redis and Loki."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def report(self) -> dict[str, Any]:
        resources = self.database.execute(
            """
            select id, code, resource_kind, scope_type, revision, status,
                   environment_id, coalesce(base_id, '') as base_id,
                   coalesce(workshop_id, '') as workshop_id
              from platform_resource
             where resource_kind in ('database', 'redis', 'loki')
             order by resource_kind, code, id
            """
        )
        resource_ids = {str(row["id"]) for row in resources}
        drafts = self._for_resources(
            """
            select id, resource_id, draft_revision, status
              from platform_resource_draft
             order by resource_id, draft_revision, id
            """,
            resource_ids,
        )
        verifications = self._for_resources(
            """
            select id, resource_id, draft_revision, status
              from platform_resource_verification
             order by resource_id, draft_revision, id
            """,
            resource_ids,
        )
        revisions = self._for_resources(
            """
            select id, resource_id, revision, status
              from platform_resource_revision
             order by resource_id, revision, id
            """,
            resource_ids,
        )
        revision_ids = {str(row["id"]) for row in revisions}
        legacy_bindings = self.database.execute(
            """
            select id, code, resource_kind, scope_type, revision, status,
                   coalesce(environment_id, '') as environment_id,
                   coalesce(base_id, '') as base_id,
                   coalesce(workshop_id, '') as workshop_id
              from platform_resource_binding
             where resource_kind in ('database', 'redis', 'loki')
             order by resource_kind, code, id
            """
        )
        application_bindings = self._for_revisions(
            """
            select b.id, b.publication_id as application_publication_id,
                   b.resource_revision_id, b.slot_code,
                   p.application_id, a.code as application_code
              from business_application_resource_binding b
              join business_application_publication p
                on p.id = b.publication_id
              join business_application a on a.id = p.application_id
             order by b.publication_id, b.slot_code, b.id
            """,
            revision_ids,
        )
        handler_resource_bindings = self._for_revisions(
            """
            select r.id, r.resource_revision_id, r.resource_slot,
                   h.application_publication_id,
                   p.application_id, a.code as application_code
              from business_application_publication_resource r
              join business_application_publication_handler h
                on h.id = r.application_handler_id
              join business_application_publication p
                on p.id = h.application_publication_id
              join business_application a on a.id = p.application_id
             order by h.application_publication_id,
                      r.resource_slot, r.id
            """,
            revision_ids,
        )
        activations = self._for_resources(
            """
            select id, resource_id, published_revision_id,
                   coalesce(effective_revision_id, '') as effective_revision_id,
                   coalesce(last_known_good_revision_id, '')
                     as last_known_good_revision_id,
                   published_generation, effective_generation, status
              from platform_resource_activation
             order by resource_id, published_generation, id
            """,
            resource_ids,
        )
        runtime_states = self._for_revisions(
            """
            select resource_revision_id, generation_id,
                   coalesce(effective_revision_id, '')
                     as effective_revision_id,
                   status,
                   coalesce(last_known_good_generation_id, '')
                     as last_known_good_generation_id
              from tool_resource_runtime_state
             order by generation_id, resource_revision_id
            """,
            revision_ids,
        )
        affected = self._affected_applications(
            application_bindings,
            handler_resource_bindings,
        )
        active_jobs = self._active_resource_jobs()
        protected_counts = self._protected_counts()
        current_generation = (
            RuntimeGenerationRepository(
                self.database
            ).public_status()
        )
        targets = self._targets(
            resources=resources,
            drafts=drafts,
            verifications=verifications,
            revisions=revisions,
            legacy_bindings=legacy_bindings,
            application_bindings=application_bindings,
            handler_resource_bindings=handler_resource_bindings,
            activations=activations,
            runtime_states=runtime_states,
            affected_applications=affected,
        )
        fingerprint_payload = {
            "targets": targets,
            "active_resource_jobs": active_jobs,
            "effective_generation": current_generation.get(
                "effective_generation"
            ),
        }
        database_fingerprint = self._digest(fingerprint_payload)
        return {
            "generated_at": now_iso(),
            "database_fingerprint": database_fingerprint,
            "target_kinds": list(RESET_KINDS),
            "counts": dict(
                sorted(
                    Counter(
                        str(target["type"]) for target in targets
                    ).items()
                )
            ),
            "resources": resources,
            "drafts": drafts,
            "verifications": verifications,
            "revisions": revisions,
            "legacy_bindings": legacy_bindings,
            "application_bindings": application_bindings,
            "handler_resource_bindings": (
                handler_resource_bindings
            ),
            "activations": activations,
            "runtime_states": runtime_states,
            "effective_snapshot": current_generation,
            "affected_applications": affected,
            "active_resource_jobs": active_jobs,
            "protected_counts": protected_counts,
            "targets": targets,
        }

    def prepare(
        self,
        *,
        actor_id: str,
        backup_reference: str,
        correlation_id: str = "",
        drain_timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.25,
    ) -> dict[str, Any]:
        if not actor_id:
            raise ValueError("Resource reset actor is required")
        backup_reference = str(backup_reference or "").strip()
        if not backup_reference:
            raise ValueError("Verified backup reference is required")
        if drain_timeout_seconds < 0:
            raise ValueError("Drain timeout must be non-negative")
        operation_id = new_id("resource_reset")
        timestamp = now_iso()
        with self.database.unit_of_work():
            if resource_reset_in_progress(self.database):
                raise NonRetryableExecutionError(
                    "Another Resource reset is in progress",
                    safe_message="已有工具资源重置处于维护状态",
                    error_code="resource_reset_conflict",
                )
            self.database.execute(
                """
                insert into resource_reset_operation
                  (id, status, target_kinds_json, inventory_digest,
                   database_fingerprint, backup_reference,
                   impact_summary_json, prepared_by, correlation_id,
                   created_at, updated_at)
                values (?, 'PREPARING', ?, '', '', ?, '{}', ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    json_text(list(RESET_KINDS)),
                    backup_reference,
                    actor_id,
                    correlation_id,
                    timestamp,
                    timestamp,
                ),
            )
        deadline = time.monotonic() + drain_timeout_seconds
        while True:
            active_jobs = self._active_resource_jobs()
            if not active_jobs:
                break
            if time.monotonic() >= deadline:
                self._abort(
                    operation_id,
                    error_code="resource_jobs_not_drained",
                    error_summary="资源依赖 Job 未在维护窗口内排空",
                )
                raise NonRetryableExecutionError(
                    "Resource dependent Jobs did not drain",
                    safe_message="资源依赖任务未排空，重置准备已中止",
                    error_code="resource_jobs_not_drained",
                )
            time.sleep(max(0.01, min(poll_interval_seconds, 1.0)))

        report = self.report()
        if not report["targets"]:
            self._abort(
                operation_id,
                error_code="resource_reset_empty",
                error_summary="没有可重置的 DB、Redis 或 Loki 资源",
            )
            raise NonRetryableExecutionError(
                "Resource reset inventory is empty",
                safe_message="当前没有需要重置的工具资源",
                error_code="resource_reset_empty",
            )
        impact = {
            "counts": report["counts"],
            "affected_applications": report[
                "affected_applications"
            ],
            "protected_counts": report["protected_counts"],
            "active_resource_jobs": [],
        }
        manifest = {
            "operation_id": operation_id,
            "generated_at": report["generated_at"],
            "database_fingerprint": report[
                "database_fingerprint"
            ],
            "backup_reference": backup_reference,
            "targets": report["targets"],
            "impact": impact,
        }
        digest = self._digest(manifest)
        with self.database.unit_of_work():
            operation = self._operation(operation_id)
            if operation["status"] != "PREPARING":
                raise NonRetryableExecutionError(
                    "Resource reset prepare state changed",
                    safe_message="工具资源重置准备状态已变化",
                    error_code="resource_reset_conflict",
                )
            for target in manifest["targets"]:
                self.database.execute(
                    """
                    insert into resource_reset_target
                      (operation_id, target_type, target_id,
                       target_revision, target_code, action,
                       item_digest, apply_status)
                    values (?, ?, ?, ?, ?, ?, ?, 'PENDING')
                    """,
                    (
                        operation_id,
                        target["type"],
                        target["id"],
                        int(target["revision"]),
                        str(target.get("code") or ""),
                        target["action"],
                        target["item_digest"],
                    ),
                )
            self.database.execute(
                """
                update resource_reset_operation
                   set status = 'PREPARED', inventory_digest = ?,
                       database_fingerprint = ?,
                       impact_summary_json = ?, prepared_at = ?,
                       updated_at = ?
                 where id = ? and status = 'PREPARING'
                """,
                (
                    digest,
                    report["database_fingerprint"],
                    json_text(impact),
                    now_iso(),
                    now_iso(),
                    operation_id,
                ),
            )
            self._audit(
                "resource_reset_prepared",
                operation_id=operation_id,
                actor_id=actor_id,
                correlation_id=correlation_id,
                payload={
                    "digest": digest,
                    "target_count": len(manifest["targets"]),
                    "counts": report["counts"],
                },
            )
        return {"manifest": manifest, "digest": digest}

    def apply(
        self,
        *,
        operation_id: str,
        expected_digest: str,
        confirmed_by: str,
    ) -> dict[str, Any]:
        if not confirmed_by:
            raise ValueError("Current confirmation actor is required")
        operation = self._operation(operation_id)
        if operation["status"] != "PREPARED":
            raise NonRetryableExecutionError(
                "Resource reset is not prepared",
                safe_message="工具资源重置未处于可执行状态",
                error_code="resource_reset_not_prepared",
            )
        if (
            len(expected_digest) != 64
            or expected_digest != operation["inventory_digest"]
        ):
            raise NonRetryableExecutionError(
                "Resource reset digest mismatch",
                safe_message="工具资源清单摘要不一致，请重新 report/prepare",
                error_code="resource_reset_digest_changed",
            )
        stored_targets = self._stored_targets(operation_id)
        current = self.report()
        current_targets = {
            (str(item["type"]), str(item["id"])): item
            for item in current["targets"]
        }
        if (
            current["database_fingerprint"]
            != operation["database_fingerprint"]
            or len(current_targets) != len(stored_targets)
            or any(
                current_targets.get(
                    (str(target["target_type"]), str(target["target_id"]))
                )
                is None
                or current_targets[
                    (
                        str(target["target_type"]),
                        str(target["target_id"]),
                    )
                ]["item_digest"]
                != target["item_digest"]
                for target in stored_targets
            )
        ):
            self._abort(
                operation_id,
                error_code="resource_reset_inventory_changed",
                error_summary="prepare 后资源清单发生变化",
            )
            raise NonRetryableExecutionError(
                "Resource reset inventory changed",
                safe_message="工具资源清单已变化，请重新 report/prepare",
                error_code="resource_reset_inventory_changed",
            )

        timestamp = now_iso()
        impact = self._json_object(
            operation.get("impact_summary_json") or "{}"
        )
        affected = impact.get("affected_applications") or []
        with self.database.unit_of_work():
            updated = self.database.execute(
                """
                update resource_reset_operation
                   set status = 'CONFIRMED', confirmed_by = ?,
                       confirmed_at = ?, updated_at = ?
                 where id = ? and status = 'PREPARED'
                returning id
                """,
                (
                    confirmed_by,
                    timestamp,
                    timestamp,
                    operation_id,
                ),
            )
            if not updated:
                raise NonRetryableExecutionError(
                    "Resource reset confirmation raced",
                    safe_message="工具资源重置确认状态已变化",
                    error_code="resource_reset_conflict",
                )
            self.database.execute(
                """
                update resource_reset_operation
                   set status = 'APPLYING', updated_at = ?
                 where id = ? and status = 'CONFIRMED'
                """,
                (now_iso(), operation_id),
            )
            self._delete_targets(stored_targets)
            generation = self._activate_empty_generation(
                operation_id=operation_id,
                affected_applications=affected,
            )
            self.database.execute(
                """
                update resource_reset_target
                   set apply_status = 'APPLIED'
                 where operation_id = ?
                """,
                (operation_id,),
            )
            self.database.execute(
                """
                update resource_reset_operation
                   set status = 'APPLIED', applied_by = ?,
                       applied_at = ?, updated_at = ?
                 where id = ? and status = 'APPLYING'
                """,
                (
                    confirmed_by,
                    now_iso(),
                    now_iso(),
                    operation_id,
                ),
            )
            self._audit(
                "resource_reset_applied",
                operation_id=operation_id,
                actor_id=confirmed_by,
                correlation_id=str(
                    operation.get("correlation_id") or ""
                ),
                payload={
                    "digest": expected_digest,
                    "target_count": len(stored_targets),
                    "generation_id": generation["id"],
                },
            )
        return {
            "operation_id": operation_id,
            "status": "APPLIED",
            "digest": expected_digest,
            "affected_rows": len(stored_targets),
        }

    def verify(
        self,
        *,
        operation_id: str,
        actor_id: str,
    ) -> dict[str, Any]:
        operation = self._operation(operation_id)
        if operation["status"] not in {"APPLIED", "VERIFIED"}:
            raise NonRetryableExecutionError(
                "Resource reset has not been applied",
                safe_message="工具资源重置尚未执行",
                error_code="resource_reset_not_applied",
            )
        impact = self._json_object(
            operation.get("impact_summary_json") or "{}"
        )
        before = impact.get("protected_counts") or {}
        after = self._protected_counts()
        exact_tables = set(PROTECTED_COUNT_TABLES).difference(
            {"audit_event", "runtime_snapshot_generation"}
        )
        protected_ok = all(
            int(after.get(table, -1)) == int(before.get(table, -2))
            for table in exact_tables
        )
        monotonic_ok = all(
            int(after.get(table, -1)) >= int(before.get(table, -2))
            for table in (
                "audit_event",
                "runtime_snapshot_generation",
            )
        )
        emptiness = self._empty_resource_checks()
        blocked_expected = len(
            impact.get("affected_applications") or []
        )
        blocked_row = self.database.execute_one(
            """
            select count(*) as count
              from business_application_runtime_state s
              join runtime_snapshot_generation g
                on g.id = s.generation_id
             where g.status = 'ACTIVE'
               and s.status = 'BLOCKED'
            """
        )
        blocked_actual = int(
            blocked_row["count"] if blocked_row else 0
        )
        checks = {
            **emptiness,
            "protected_counts_exact": protected_ok,
            "protected_counts_monotonic": monotonic_ok,
            "affected_applications_blocked": (
                blocked_actual == blocked_expected
            ),
            "blocked_application_count": blocked_actual,
            "historical_generation_preserved": (
                after["runtime_snapshot_generation"]
                >= before["runtime_snapshot_generation"] + 1
            ),
        }
        passed = all(
            value
            for key, value in checks.items()
            if not key.endswith("_count")
        )
        if not passed:
            raise NonRetryableExecutionError(
                "Resource reset verification failed",
                safe_message="工具资源重置核验失败",
                error_code="resource_reset_verify_failed",
            )
        if operation["status"] != "VERIFIED":
            with self.database.unit_of_work():
                self.database.execute(
                    """
                    update resource_reset_operation
                       set status = 'VERIFIED', verified_by = ?,
                           verified_at = ?, updated_at = ?
                     where id = ? and status = 'APPLIED'
                    """,
                    (
                        actor_id,
                        now_iso(),
                        now_iso(),
                        operation_id,
                    ),
                )
                self._audit(
                    "resource_reset_verified",
                    operation_id=operation_id,
                    actor_id=actor_id,
                    correlation_id=str(
                        operation.get("correlation_id") or ""
                    ),
                    payload={"checks": checks},
                )
        return {
            "operation_id": operation_id,
            "status": "VERIFIED",
            "checks": checks,
            "protected_counts_before": before,
            "protected_counts_after": after,
        }

    def _targets(
        self,
        *,
        resources: list[dict[str, Any]],
        drafts: list[dict[str, Any]],
        verifications: list[dict[str, Any]],
        revisions: list[dict[str, Any]],
        legacy_bindings: list[dict[str, Any]],
        application_bindings: list[dict[str, Any]],
        handler_resource_bindings: list[dict[str, Any]],
        activations: list[dict[str, Any]],
        runtime_states: list[dict[str, Any]],
        affected_applications: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        targets: list[dict[str, Any]] = []
        for row in resources:
            targets.append(
                self._target(
                    "resource",
                    str(row["id"]),
                    int(row["revision"]),
                    "DELETE",
                    str(row["code"]),
                    row,
                )
            )
        for row in drafts:
            targets.append(
                self._target(
                    "draft",
                    str(row["id"]),
                    int(row["draft_revision"]),
                    "DELETE",
                    "",
                    row,
                )
            )
        for row in verifications:
            targets.append(
                self._target(
                    "verification",
                    str(row["id"]),
                    int(row["draft_revision"]),
                    "DELETE",
                    "",
                    row,
                )
            )
        for row in revisions:
            targets.append(
                self._target(
                    "revision",
                    str(row["id"]),
                    int(row["revision"]),
                    "DELETE",
                    "",
                    row,
                )
            )
        for row in legacy_bindings:
            targets.append(
                self._target(
                    "legacy_binding",
                    str(row["id"]),
                    int(row["revision"]),
                    "DELETE",
                    str(row["code"]),
                    row,
                )
            )
        for row in application_bindings:
            targets.append(
                self._target(
                    "application_binding",
                    str(row["id"]),
                    1,
                    "DELETE",
                    str(row["application_code"]),
                    row,
                )
            )
        for row in handler_resource_bindings:
            targets.append(
                self._target(
                    "handler_resource_binding",
                    str(row["id"]),
                    1,
                    "DELETE",
                    str(row["application_code"]),
                    row,
                )
            )
        for row in activations:
            targets.append(
                self._target(
                    "activation",
                    str(row["id"]),
                    int(row["published_generation"]),
                    "DELETE",
                    "",
                    row,
                )
            )
        for row in runtime_states:
            target_id = (
                f"{row['resource_revision_id']}@"
                f"{row['generation_id']}"
            )
            targets.append(
                self._target(
                    "resource_runtime_state",
                    target_id,
                    0,
                    "DELETE",
                    "",
                    row,
                )
            )
        for row in affected_applications:
            targets.append(
                self._target(
                    "application_runtime_state",
                    str(row["application_publication_id"]),
                    0,
                    "BLOCK",
                    str(row["application_code"]),
                    row,
                )
            )
        return sorted(
            targets,
            key=lambda item: (
                str(item["type"]),
                str(item["id"]),
            ),
        )

    def _delete_targets(
        self,
        targets: list[dict[str, Any]],
    ) -> None:
        by_type: dict[str, list[str]] = {}
        for target in targets:
            by_type.setdefault(
                str(target["target_type"]),
                [],
            ).append(str(target["target_id"]))
        table_by_type = {
            "handler_resource_binding": (
                "business_application_publication_resource"
            ),
            "application_binding": (
                "business_application_resource_binding"
            ),
            "legacy_binding": "platform_resource_binding",
            "activation": "platform_resource_activation",
            "revision": "platform_resource_revision",
            "verification": "platform_resource_verification",
            "draft": "platform_resource_draft",
            "resource": "platform_resource",
        }
        for target_type in (
            "handler_resource_binding",
            "application_binding",
            "legacy_binding",
            "activation",
        ):
            self._delete_ids(
                table_by_type[target_type],
                by_type.get(target_type, []),
            )
        for target_id in by_type.get(
            "resource_runtime_state",
            [],
        ):
            revision_id, generation_id = target_id.split("@", 1)
            self.database.execute(
                """
                delete from tool_resource_runtime_state
                 where resource_revision_id = ?
                   and generation_id = ?
                """,
                (revision_id, generation_id),
            )
        for target_type in (
            "revision",
            "verification",
            "draft",
            "resource",
        ):
            self._delete_ids(
                table_by_type[target_type],
                by_type.get(target_type, []),
            )

    def _activate_empty_generation(
        self,
        *,
        operation_id: str,
        affected_applications: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.database.execute(
            """
            update runtime_snapshot_generation
               set status = 'SUPERSEDED'
             where status = 'ACTIVE'
            """
        )
        row = self.database.execute_one(
            """
            select coalesce(max(generation_no), 0) as generation_no
              from runtime_snapshot_generation
            """
        )
        generation_no = int(row["generation_no"] if row else 0) + 1
        generation_id = new_id("runtime_generation")
        published_digest = RuntimeGenerationRepository(
            self.database
        ).published_digest()
        metadata = {
            "operation_id": operation_id,
            "resource_count": 0,
            "applications": [
                {
                    "application_publication_id": str(
                        item["application_publication_id"]
                    ),
                    "status": "BLOCKED",
                    "reason_codes": ["resource_reset"],
                }
                for item in affected_applications
            ],
        }
        snapshot_digest = self._digest(metadata)
        timestamp = now_iso()
        self.database.execute(
            """
            insert into runtime_snapshot_generation
              (id, generation_no, published_digest, snapshot_digest,
               status, resource_count, application_count,
               snapshot_json, error_code, error_summary,
               built_at, activated_at)
            values (?, ?, ?, ?, 'ACTIVE', 0, ?, ?, '', '', ?, ?)
            """,
            (
                generation_id,
                generation_no,
                published_digest,
                snapshot_digest,
                len(affected_applications),
                json_text(metadata),
                timestamp,
                timestamp,
            ),
        )
        for application in affected_applications:
            self.database.execute(
                """
                insert into business_application_runtime_state
                  (application_publication_id, generation_id,
                   effective_application_publication_id, status,
                   last_known_good_generation_id,
                   reason_codes_json, updated_at)
                values (?, ?, null, 'BLOCKED', null, ?, ?)
                """,
                (
                    application["application_publication_id"],
                    generation_id,
                    json_text(["resource_reset"]),
                    timestamp,
                ),
            )
        return {
            "id": generation_id,
            "generation_no": generation_no,
            "snapshot_digest": snapshot_digest,
        }

    def _empty_resource_checks(self) -> dict[str, bool]:
        checks = {
            "resource_identity_empty": (
                self._count(
                    "platform_resource",
                    "resource_kind in ('database', 'redis', 'loki')",
                )
                == 0
            ),
            "resource_draft_empty": (
                self._count("platform_resource_draft") == 0
            ),
            "resource_verification_empty": (
                self._count("platform_resource_verification") == 0
            ),
            "resource_revision_empty": (
                self._count("platform_resource_revision") == 0
            ),
            "legacy_resource_binding_empty": (
                self._count(
                    "platform_resource_binding",
                    "resource_kind in ('database', 'redis', 'loki')",
                )
                == 0
            ),
            "application_resource_binding_empty": (
                self._count(
                    "business_application_resource_binding"
                )
                == 0
            ),
            "handler_resource_binding_empty": (
                self._count(
                    "business_application_publication_resource"
                )
                == 0
            ),
            "resource_activation_empty": (
                self._count("platform_resource_activation") == 0
            ),
            "resource_runtime_state_empty": (
                self._count("tool_resource_runtime_state") == 0
            ),
        }
        return checks

    def _active_resource_jobs(self) -> list[dict[str, Any]]:
        placeholders = ", ".join(
            "?" for _ in ACTIVE_RESOURCE_JOB_STATES
        )
        return self.database.execute(
            f"""
            select distinct j.id, j.status,
                   j.business_application_publication_id
              from agent_job j
              join agent_job_execution_scope s on s.job_id = j.id
              join agent_job_execution_binding b
                on b.execution_scope_id = s.id
             where j.status in ({placeholders})
             order by j.id
            """,
            ACTIVE_RESOURCE_JOB_STATES,
        )

    def _affected_applications(
        self,
        application_bindings: list[dict[str, Any]],
        handler_resource_bindings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        values: dict[str, dict[str, Any]] = {}
        for row in [
            *application_bindings,
            *handler_resource_bindings,
        ]:
            publication_id = str(
                row["application_publication_id"]
            )
            values[publication_id] = {
                "application_publication_id": publication_id,
                "application_id": str(row["application_id"]),
                "application_code": str(row["application_code"]),
                "expected_status": "BLOCKED",
            }
        return [
            values[key]
            for key in sorted(values)
        ]

    def _protected_counts(self) -> dict[str, int]:
        return {
            table: self._count(table)
            for table in PROTECTED_COUNT_TABLES
        }

    def _stored_targets(
        self,
        operation_id: str,
    ) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select * from resource_reset_target
             where operation_id = ?
             order by target_type, target_id
            """,
            (operation_id,),
        )

    def _operation(self, operation_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from resource_reset_operation where id = ?",
            (operation_id,),
        )
        if row is None:
            raise NotFound(
                f"Resource reset operation not found: {operation_id}"
            )
        return row

    def _abort(
        self,
        operation_id: str,
        *,
        error_code: str,
        error_summary: str,
    ) -> None:
        self.database.execute(
            """
            update resource_reset_operation
               set status = 'ABORTED', error_code = ?,
                   error_summary = ?, updated_at = ?
             where id = ?
               and status in (
                 'PREPARING', 'PREPARED', 'CONFIRMED'
               )
            """,
            (
                error_code,
                error_summary,
                now_iso(),
                operation_id,
            ),
        )

    def _audit(
        self,
        event_type: str,
        *,
        operation_id: str,
        actor_id: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> None:
        self.database.execute(
            """
            insert into audit_event
              (id, job_id, event_type, actor_id, status,
               summary, payload_summary, created_at)
            values (?, null, ?, ?, 'SUCCEEDED', ?, ?, ?)
            """,
            (
                new_id("audit"),
                event_type,
                actor_id,
                event_type.replace("_", " "),
                json_text(
                    {
                        "operation_id": operation_id,
                        "correlation_id": correlation_id,
                        **payload,
                    }
                ),
                now_iso(),
            ),
        )

    @staticmethod
    def _target(
        target_type: str,
        target_id: str,
        revision: int,
        action: str,
        code: str,
        facts: dict[str, Any],
    ) -> dict[str, Any]:
        item = {
            "type": target_type,
            "id": target_id,
            "revision": revision,
            "action": action,
            "code": code,
        }
        item["item_digest"] = ResourceResetService._digest(
            {
                **item,
                "facts": facts,
            }
        )
        return item

    def _for_resources(
        self,
        sql: str,
        resource_ids: set[str],
    ) -> list[dict[str, Any]]:
        return [
            row
            for row in self.database.execute(sql)
            if str(row["resource_id"]) in resource_ids
        ]

    def _for_revisions(
        self,
        sql: str,
        revision_ids: set[str],
    ) -> list[dict[str, Any]]:
        return [
            row
            for row in self.database.execute(sql)
            if str(row["resource_revision_id"]) in revision_ids
        ]

    def _delete_ids(
        self,
        table: str,
        target_ids: Iterable[str],
    ) -> None:
        allowed = {
            "business_application_publication_resource",
            "business_application_resource_binding",
            "platform_resource_binding",
            "platform_resource_activation",
            "platform_resource_revision",
            "platform_resource_verification",
            "platform_resource_draft",
            "platform_resource",
        }
        if table not in allowed:
            raise RuntimeError("Resource reset delete table is not allowed")
        for target_id in target_ids:
            self.database.execute(
                f"delete from {table} where id = ?",
                (target_id,),
            )

    def _count(self, table: str, where: str = "") -> int:
        allowed = {
            *PROTECTED_COUNT_TABLES,
            "platform_resource",
            "platform_resource_draft",
            "platform_resource_verification",
            "platform_resource_revision",
            "platform_resource_binding",
            "business_application_resource_binding",
            "business_application_publication_resource",
            "platform_resource_activation",
            "tool_resource_runtime_state",
        }
        if table not in allowed:
            raise RuntimeError("Resource reset count table is not allowed")
        clause = f" where {where}" if where else ""
        row = self.database.execute_one(
            f"select count(*) as count from {table}{clause}"
        )
        return int(row["count"] if row else 0)

    @staticmethod
    def _digest(value: Any) -> str:
        canonical = json.dumps(
            ResourceResetService._canonicalize(value),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonicalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: ResourceResetService._canonicalize(value[key])
                for key in sorted(value)
            }
        if isinstance(value, list):
            normalized = [
                ResourceResetService._canonicalize(item)
                for item in value
            ]
            return sorted(
                normalized,
                key=lambda item: json.dumps(
                    item,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        return value

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        try:
            decoded = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
