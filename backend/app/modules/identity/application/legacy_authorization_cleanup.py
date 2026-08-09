from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from app.modules.platform_config.infrastructure.repository import (
    json_text,
    new_id,
    now_iso,
)
from app.shared.database import Database
from app.shared.exceptions import (
    NonRetryableExecutionError,
    NotFound,
)


LEGACY_AUTHORIZATION_TABLES = (
    "permission_policy",
    "platform_access_grant",
)


class LegacyAuthorizationCleanupService:
    """Controlled one-time removal of legacy authorization rows."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def report(self) -> dict[str, Any]:
        rows_by_table = {
            table: self.database.execute(f"select * from {table} order by id")
            for table in LEGACY_AUTHORIZATION_TABLES
        }
        targets: list[dict[str, Any]] = []
        breakdown: Counter[str] = Counter()
        for table, rows in rows_by_table.items():
            for row in rows:
                normalized = self._normalized_row(row)
                targets.append(
                    {
                        "table": table,
                        "id": str(row["id"]),
                        "revision": int(row.get("revision") or 1),
                        "item_digest": self._digest(normalized),
                    }
                )
                breakdown[
                    ":".join(
                        (
                            table,
                            str(row.get("subject_type") or ""),
                            str(row.get("effect") or ""),
                            str(row.get("status") or ""),
                        )
                    )
                ] += 1
        targets.sort(key=lambda item: (item["table"], item["id"]))
        counts = {table: len(rows_by_table[table]) for table in LEGACY_AUTHORIZATION_TABLES}
        admins = self._verified_human_admins()
        payload = {
            "counts": counts,
            "breakdown": dict(sorted(breakdown.items())),
            "targets": targets,
        }
        return {
            **payload,
            "digest": self._digest(payload),
            "verified_human_platform_admins": admins,
            "verified_human_platform_admin_count": len(admins),
        }

    def prepare(
        self,
        *,
        actor_id: str,
        backup_reference: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        actor_id = str(actor_id or "").strip()
        backup_reference = str(backup_reference or "").strip()
        if not actor_id:
            raise ValueError("Cleanup actor is required")
        if not backup_reference:
            raise ValueError("Verified backup reference is required")
        report = self.report()
        self._require_two_admins(report)
        if not sum(int(value) for value in report["counts"].values()):
            raise NonRetryableExecutionError(
                "Legacy authorization inventory is empty",
                safe_message="当前没有需要清理的旧授权数据",
                error_code="legacy_authorization_cleanup_empty",
            )
        operation_id = new_id("legacy_auth_cleanup")
        manifest = {
            "operation_id": operation_id,
            "backup_reference": backup_reference,
            "counts": report["counts"],
            "breakdown": report["breakdown"],
            "targets": report["targets"],
        }
        digest = self._digest(
            {
                "counts": report["counts"],
                "breakdown": report["breakdown"],
                "targets": report["targets"],
            }
        )
        timestamp = now_iso()
        with self.database.unit_of_work():
            active = self.database.execute_one(
                """
                select id
                  from legacy_authorization_cleanup_operation
                 where status in ('PREPARED', 'APPLYING')
                 order by created_at desc
                 limit 1
                """
            )
            if active is not None:
                raise NonRetryableExecutionError(
                    "Legacy authorization cleanup already prepared",
                    safe_message="已有旧授权清理操作等待处理",
                    error_code="legacy_authorization_cleanup_conflict",
                )
            self.database.execute(
                """
                insert into legacy_authorization_cleanup_operation
                  (id, status, inventory_digest, backup_reference,
                   manifest_json, prepared_by, prepared_at,
                   correlation_id, created_at, updated_at)
                values (?, 'PREPARED', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    digest,
                    backup_reference,
                    json_text(manifest),
                    actor_id,
                    timestamp,
                    correlation_id,
                    timestamp,
                    timestamp,
                ),
            )
            self._audit(
                "legacy_authorization_cleanup_prepared",
                operation_id=operation_id,
                actor_id=actor_id,
                correlation_id=correlation_id,
                payload={
                    "digest": digest,
                    "counts": report["counts"],
                    "backup_reference": backup_reference,
                },
            )
        return {
            "operation_id": operation_id,
            "status": "PREPARED",
            "digest": digest,
            "manifest": manifest,
            "verified_human_platform_admins": report["verified_human_platform_admins"],
        }

    def apply(
        self,
        *,
        operation_id: str,
        expected_digest: str,
        confirmed_by: str,
    ) -> dict[str, Any]:
        confirmed_by = str(confirmed_by or "").strip()
        if not confirmed_by:
            raise ValueError("Cleanup confirmer is required")
        operation = self._operation(operation_id)
        if operation["status"] != "PREPARED":
            raise NonRetryableExecutionError(
                "Legacy authorization cleanup is not prepared",
                safe_message="旧授权清理操作不处于待确认状态",
                error_code="legacy_authorization_cleanup_not_prepared",
            )
        if not expected_digest or expected_digest != str(operation["inventory_digest"]):
            raise NonRetryableExecutionError(
                "Legacy authorization cleanup digest mismatch",
                safe_message="旧授权清理摘要不匹配，请重新生成清单",
                error_code="legacy_authorization_cleanup_digest_mismatch",
            )
        with self.database.unit_of_work():
            claimed = self.database.execute(
                """
                update legacy_authorization_cleanup_operation
                   set status = 'APPLYING', confirmed_by = ?,
                       confirmed_at = ?, updated_at = ?
                 where id = ? and status = 'PREPARED'
                returning id
                """,
                (
                    confirmed_by,
                    now_iso(),
                    now_iso(),
                    operation_id,
                ),
            )
            if not claimed:
                raise NonRetryableExecutionError(
                    "Legacy authorization cleanup claim failed",
                    safe_message="旧授权清理状态已变化，请重新检查",
                    error_code="legacy_authorization_cleanup_conflict",
                )
            current = self.report()
            self._require_two_admins(current)
            if current["digest"] != expected_digest:
                raise NonRetryableExecutionError(
                    "Legacy authorization inventory changed",
                    safe_message="旧授权清单已变化，请重新生成并确认",
                    error_code="legacy_authorization_cleanup_inventory_changed",
                )
            counts = dict(current["counts"])
            for table in LEGACY_AUTHORIZATION_TABLES:
                self.database.execute(f"delete from {table}")
            timestamp = now_iso()
            self.database.execute(
                """
                update legacy_authorization_cleanup_operation
                   set status = 'APPLIED', applied_by = ?,
                       applied_at = ?, updated_at = ?
                 where id = ? and status = 'APPLYING'
                """,
                (
                    confirmed_by,
                    timestamp,
                    timestamp,
                    operation_id,
                ),
            )
            self._audit(
                "legacy_authorization_cleanup_applied",
                operation_id=operation_id,
                actor_id=confirmed_by,
                correlation_id=str(operation.get("correlation_id") or ""),
                payload={
                    "digest": expected_digest,
                    "deleted_counts": counts,
                },
            )
        return {
            "operation_id": operation_id,
            "status": "APPLIED",
            "digest": expected_digest,
            "deleted_counts": counts,
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
                "Legacy authorization cleanup has not been applied",
                safe_message="旧授权清理尚未执行",
                error_code="legacy_authorization_cleanup_not_applied",
            )
        report = self.report()
        self._require_two_admins(report)
        checks = {
            "permission_policy_empty": (int(report["counts"]["permission_policy"]) == 0),
            "platform_access_grant_empty": (int(report["counts"]["platform_access_grant"]) == 0),
            "two_human_platform_admins_verified": (
                report["verified_human_platform_admin_count"] >= 2
            ),
        }
        if not all(checks.values()):
            raise NonRetryableExecutionError(
                "Legacy authorization cleanup verification failed",
                safe_message="旧授权清理核验失败",
                error_code="legacy_authorization_cleanup_verify_failed",
            )
        if operation["status"] != "VERIFIED":
            with self.database.unit_of_work():
                timestamp = now_iso()
                self.database.execute(
                    """
                    update legacy_authorization_cleanup_operation
                       set status = 'VERIFIED', verified_by = ?,
                           verified_at = ?, updated_at = ?
                     where id = ? and status = 'APPLIED'
                    """,
                    (
                        actor_id,
                        timestamp,
                        timestamp,
                        operation_id,
                    ),
                )
                self._audit(
                    "legacy_authorization_cleanup_verified",
                    operation_id=operation_id,
                    actor_id=actor_id,
                    correlation_id=str(operation.get("correlation_id") or ""),
                    payload={"checks": checks},
                )
        return {
            "operation_id": operation_id,
            "status": "VERIFIED",
            "checks": checks,
            "verified_human_platform_admins": report["verified_human_platform_admins"],
        }

    def _verified_human_admins(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select u.id, u.username,
                   count(distinct s.id) as active_session_count,
                   count(distinct a.id) as successful_login_count
              from app_user u
              join rbac_user_role ur
                on ur.user_id = u.id and ur.status = 'enabled'
              join rbac_role r
                on r.id = ur.role_id and r.code = 'platform-admin'
               and r.status = 'enabled'
              join user_password_credential pc on pc.user_id = u.id
              join user_session s
                on s.user_id = u.id and s.status = 'active'
               and s.idle_expires_at > ?
               and s.absolute_expires_at > ?
              join audit_event a
                on a.actor_id = u.id
               and a.event_type = 'auth.login.succeeded'
               and a.status = 'SUCCEEDED'
             where u.status = 'enabled' and u.account_type = 'human'
             group by u.id, u.username
             order by u.username, u.id
            """,
            (now_iso(), now_iso()),
        )
        return [
            {
                "id": str(row["id"]),
                "username": str(row["username"]),
                "active_session_count": int(row["active_session_count"]),
                "successful_login_count": int(row["successful_login_count"]),
            }
            for row in rows
        ]

    @staticmethod
    def _require_two_admins(report: dict[str, Any]) -> None:
        if int(report["verified_human_platform_admin_count"]) < 2:
            raise NonRetryableExecutionError(
                "At least two verified human platform admins are required",
                safe_message="旧授权清理前必须验证至少两名人类平台管理员",
                error_code="two_platform_admins_required",
            )

    def _operation(self, operation_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select *
              from legacy_authorization_cleanup_operation
             where id = ?
            """,
            (operation_id,),
        )
        if row is None:
            raise NotFound(f"Legacy authorization cleanup operation not found: {operation_id}")
        return row

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

    @classmethod
    def _normalized_row(
        cls,
        value: Any,
    ) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._normalized_row(child) for key, child in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [cls._normalized_row(child) for child in value]
        if isinstance(value, bytes):
            return value.hex()
        return value

    @staticmethod
    def _digest(payload: Any) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
