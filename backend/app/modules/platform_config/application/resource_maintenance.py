from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from app.modules.platform_config.infrastructure.repository import json_text, new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound


ACTIVE_RESET_STATES = ("PREPARING", "PREPARED", "CONFIRMED", "APPLYING")
ACTIVE_JOB_STATES = ("WAITING_INPUT", "PENDING", "QUEUED", "RUNNING", "RETRY_WAIT", "RETRYING")
RESOURCE_KINDS = ("database", "redis", "loki")
PROTECTED_TABLES = (
    "platform_secret",
    "platform_environment",
    "platform_base",
    "platform_workshop",
    "app_user",
    "rbac_role",
    "rbac_user_role",
    "business_application",
    "business_application_publication",
    "agent_job",
    "delivery_outbox",
)


def resource_reset_in_progress(database: Database) -> bool:
    placeholders = ", ".join("?" for _ in ACTIVE_RESET_STATES)
    return (
        database.execute_one(
            f"""
            select id
              from resource_reset_operation
             where status in ({placeholders})
             order by created_at desc
             limit 1
            """,
            ACTIVE_RESET_STATES,
        )
        is not None
    )


class ResourceResetService:
    """Backup-gated reset for versioned MCP Tool Resources only."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def report(self) -> dict[str, Any]:
        resources = self.database.execute(
            """
            select id, code, resource_kind, scope_type, revision, status,
                   coalesce(environment_id, '') as environment_id,
                   coalesce(base_id, '') as base_id,
                   coalesce(workshop_id, '') as workshop_id,
                   coalesce(placement, '') as placement
              from platform_resource
             where resource_kind in ('database', 'redis', 'loki')
             order by resource_kind, code, id
            """
        )
        resource_ids = tuple(str(item["id"]) for item in resources)
        drafts = self._children(
            "platform_resource_draft",
            "select id, resource_id, draft_revision as revision, status "
            "from platform_resource_draft",
            resource_ids,
        )
        verifications = self._children(
            "platform_resource_verification",
            "select id, resource_id, draft_revision as revision, status "
            "from platform_resource_verification",
            resource_ids,
        )
        revisions = self._children(
            "platform_resource_revision",
            "select id, resource_id, revision, status from platform_resource_revision",
            resource_ids,
        )
        targets: list[dict[str, Any]] = []
        for target_type, rows in (
            ("draft", drafts),
            ("verification", verifications),
            ("revision", revisions),
            ("resource", resources),
        ):
            for row in rows:
                item = {
                    "type": target_type,
                    "id": str(row["id"]),
                    "revision": int(row.get("revision") or 0),
                    "code": str(row.get("code") or ""),
                    "action": "DELETE",
                }
                item["item_digest"] = self._digest(item)
                targets.append(item)
        counts = {
            "resources": len(resources),
            "drafts": len(drafts),
            "verifications": len(verifications),
            "revisions": len(revisions),
        }
        fingerprint = self._digest({"targets": targets, "protected": self._protected_counts()})
        return {
            "generated_at": now_iso(),
            "database_fingerprint": fingerprint,
            "counts": counts,
            "targets": targets,
            "protected_counts": self._protected_counts(),
            "active_resource_jobs": self._active_resource_jobs(),
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
                   database_fingerprint, backup_reference, impact_summary_json,
                   prepared_by, correlation_id, created_at, updated_at)
                values (?, 'PREPARING', ?, '', '', ?, '{}', ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    json_text(list(RESOURCE_KINDS)),
                    backup_reference,
                    actor_id,
                    correlation_id,
                    timestamp,
                    timestamp,
                ),
            )
        deadline = time.monotonic() + drain_timeout_seconds
        while self._active_resource_jobs():
            if time.monotonic() >= deadline:
                self._abort(operation_id, "resource_jobs_not_drained", "资源依赖 Job 未排空")
                raise NonRetryableExecutionError(
                    "Resource dependent Jobs did not drain",
                    safe_message="资源依赖任务未排空，重置准备已中止",
                    error_code="resource_jobs_not_drained",
                )
            time.sleep(max(0.01, min(poll_interval_seconds, 1.0)))
        report = self.report()
        if not report["targets"]:
            self._abort(operation_id, "resource_reset_empty", "没有可重置的工具资源")
            raise NonRetryableExecutionError(
                "Resource reset inventory is empty",
                safe_message="当前没有需要重置的工具资源",
                error_code="resource_reset_empty",
            )
        impact = {"counts": report["counts"], "protected_counts": report["protected_counts"]}
        manifest = {
            "operation_id": operation_id,
            "generated_at": report["generated_at"],
            "database_fingerprint": report["database_fingerprint"],
            "backup_reference": backup_reference,
            "targets": report["targets"],
            "impact": impact,
        }
        digest = self._digest(manifest)
        with self.database.unit_of_work():
            for target in report["targets"]:
                self.database.execute(
                    """
                    insert into resource_reset_target
                      (operation_id, target_type, target_id, target_revision,
                       target_code, action, item_digest, apply_status)
                    values (?, ?, ?, ?, ?, 'DELETE', ?, 'PENDING')
                    """,
                    (
                        operation_id,
                        target["type"],
                        target["id"],
                        target["revision"],
                        target["code"],
                        target["item_digest"],
                    ),
                )
            self.database.execute(
                """
                update resource_reset_operation
                   set status = 'PREPARED', inventory_digest = ?,
                       database_fingerprint = ?, impact_summary_json = ?,
                       prepared_at = ?, updated_at = ?
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
        return {"manifest": manifest, "digest": digest}

    def apply(
        self, *, operation_id: str, expected_digest: str, confirmed_by: str
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
        if expected_digest != str(operation["inventory_digest"]):
            raise NonRetryableExecutionError(
                "Resource reset digest mismatch",
                safe_message="工具资源清单摘要不一致，请重新 report/prepare",
                error_code="resource_reset_digest_changed",
            )
        report = self.report()
        stored = self._stored_targets(operation_id)
        current = {(item["type"], item["id"]): item["item_digest"] for item in report["targets"]}
        expected = {
            (str(item["target_type"]), str(item["target_id"])): str(item["item_digest"])
            for item in stored
        }
        if (
            report["database_fingerprint"] != operation["database_fingerprint"]
            or current != expected
        ):
            self._abort(
                operation_id, "resource_reset_inventory_changed", "prepare 后资源清单发生变化"
            )
            raise NonRetryableExecutionError(
                "Resource reset inventory changed",
                safe_message="工具资源清单已变化，请重新 report/prepare",
                error_code="resource_reset_inventory_changed",
            )
        with self.database.unit_of_work():
            updated = self.database.execute(
                """
                update resource_reset_operation
                   set status = 'APPLYING', confirmed_by = ?, confirmed_at = ?, updated_at = ?
                 where id = ? and status = 'PREPARED'
                returning id
                """,
                (confirmed_by, now_iso(), now_iso(), operation_id),
            )
            if not updated:
                raise NonRetryableExecutionError(
                    "Resource reset confirmation raced",
                    safe_message="工具资源重置确认状态已变化",
                    error_code="resource_reset_conflict",
                )
            ids_by_type = {
                target_type: tuple(
                    str(item["target_id"]) for item in stored if item["target_type"] == target_type
                )
                for target_type in ("draft", "verification", "revision", "resource")
            }
            for table, target_type in (
                ("platform_resource_revision", "revision"),
                ("platform_resource_verification", "verification"),
                ("platform_resource_draft", "draft"),
                ("platform_resource", "resource"),
            ):
                self._delete_ids(table, ids_by_type[target_type])
            self.database.execute(
                "update resource_reset_target set apply_status = 'APPLIED' where operation_id = ?",
                (operation_id,),
            )
            self.database.execute(
                """
                update resource_reset_operation
                   set status = 'APPLIED', applied_by = ?, applied_at = ?, updated_at = ?
                 where id = ? and status = 'APPLYING'
                """,
                (confirmed_by, now_iso(), now_iso(), operation_id),
            )
        return {
            "operation_id": operation_id,
            "status": "APPLIED",
            "digest": expected_digest,
            "affected_rows": len(stored),
        }

    def verify(self, *, operation_id: str, actor_id: str) -> dict[str, Any]:
        operation = self._operation(operation_id)
        if operation["status"] not in {"APPLIED", "VERIFIED"}:
            raise NonRetryableExecutionError(
                "Resource reset has not been applied",
                safe_message="工具资源重置尚未执行",
                error_code="resource_reset_not_applied",
            )
        impact = self._json_object(operation.get("impact_summary_json"))
        before = impact.get("protected_counts") or {}
        after = self._protected_counts()
        protected = all(
            int(after.get(key, -1)) == int(before.get(key, -2)) for key in PROTECTED_TABLES
        )
        counts = self.report()["counts"]
        empty = all(int(value) == 0 for value in counts.values())
        if not protected or not empty:
            raise NonRetryableExecutionError(
                "Resource reset verification failed",
                safe_message="工具资源重置核验失败",
                error_code="resource_reset_verify_failed",
            )
        if operation["status"] != "VERIFIED":
            self.database.execute(
                """
                update resource_reset_operation
                   set status = 'VERIFIED', verified_by = ?, verified_at = ?, updated_at = ?
                 where id = ? and status = 'APPLIED'
                """,
                (actor_id, now_iso(), now_iso(), operation_id),
            )
        return {
            "operation_id": operation_id,
            "status": "VERIFIED",
            "checks": {"resources_empty": empty, "protected_counts_exact": protected},
            "protected_counts_before": before,
            "protected_counts_after": after,
        }

    def _children(
        self, table: str, query: str, resource_ids: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        del table
        if not resource_ids:
            return []
        placeholders = ", ".join("?" for _ in resource_ids)
        return self.database.execute(
            f"{query} where resource_id in ({placeholders}) order by resource_id, id",
            resource_ids,
        )

    def _active_resource_jobs(self) -> list[dict[str, Any]]:
        placeholders = ", ".join("?" for _ in ACTIVE_JOB_STATES)
        return self.database.execute(
            f"""
            select distinct j.id, j.status
              from agent_job j
              join agent_job_mcp_tool_snapshot s on s.job_id = j.id
             where j.status in ({placeholders})
             order by j.id
            """,
            ACTIVE_JOB_STATES,
        )

    def _protected_counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in PROTECTED_TABLES:
            row = self.database.execute_one(f"select count(*) as count from {table}")
            result[table] = int(row["count"] if row else 0)
        return result

    def _stored_targets(self, operation_id: str) -> list[dict[str, Any]]:
        return self.database.execute(
            "select * from resource_reset_target where operation_id = ? order by target_type, target_id",
            (operation_id,),
        )

    def _operation(self, operation_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from resource_reset_operation where id = ?",
            (operation_id,),
        )
        if row is None:
            raise NotFound(
                "Resource reset operation not found", safe_message="未找到工具资源重置操作"
            )
        return row

    def _abort(self, operation_id: str, error_code: str, error_summary: str) -> None:
        self.database.execute(
            """
            update resource_reset_operation
               set status = 'ABORTED', error_code = ?, error_summary = ?, updated_at = ?
             where id = ?
            """,
            (error_code, error_summary, now_iso(), operation_id),
        )

    def _delete_ids(self, table: str, identifiers: tuple[str, ...]) -> None:
        if not identifiers:
            return
        placeholders = ", ".join("?" for _ in identifiers)
        self.database.execute(f"delete from {table} where id in ({placeholders})", identifiers)

    @staticmethod
    def _digest(value: object) -> str:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _json_object(value: object) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
