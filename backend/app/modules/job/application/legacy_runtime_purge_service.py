from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.modules.attachments.domain import ObjectStorage
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError


RUNTIME_TABLE_DELETE_ORDER = (
    "attachment_content",
    "message_attachment",
    "delivery_chunk",
    "delivery_attempt",
    "delivery_outbox",
    "agent_tool_call",
    "agent_artifact",
    "agent_step",
    "audit_event",
    "job_dispatch_outbox",
    "webhook_outbox",
    "webhook_event",
    "webhook_replay_nonce",
    "agent_message",
    "agent_runtime_event",
    "agent_job_mcp_tool_snapshot",
    "agent_job",
    "agent_session",
)

RUNTIME_DELETE_SQL = {
    "attachment_content": "delete from attachment_content",
    "message_attachment": "delete from message_attachment",
    "delivery_chunk": "delete from delivery_chunk",
    "delivery_attempt": "delete from delivery_attempt",
    "delivery_outbox": "delete from delivery_outbox",
    "agent_tool_call": "delete from agent_tool_call",
    "agent_artifact": "delete from agent_artifact",
    "agent_step": "delete from agent_step",
    "audit_event": "delete from audit_event where job_id is not null",
    "job_dispatch_outbox": "delete from job_dispatch_outbox",
    "webhook_outbox": "delete from webhook_outbox",
    "webhook_event": "delete from webhook_event",
    "webhook_replay_nonce": "delete from webhook_replay_nonce",
    "agent_message": "delete from agent_message",
    "agent_runtime_event": "delete from agent_runtime_event",
    "agent_job_mcp_tool_snapshot": "delete from agent_job_mcp_tool_snapshot",
    "agent_job": "delete from agent_job",
    "agent_session": "delete from agent_session",
}

PRESERVED_CONTROL_PLANE_TABLES = (
    "app_user",
    "user_external_identity",
    "rbac_role",
    "rbac_user_role",
    "agent_definition",
    "agent_publication",
    "business_application",
    "business_application_publication",
    "business_application_deployment",
    "integration_connector",
    "webhook_trigger_definition",
    "webhook_trigger_publication",
)


@dataclass(frozen=True)
class RuntimeObjectReference:
    bucket: str
    key: str
    source: str

    @property
    def summary(self) -> str:
        return hashlib.sha256(f"{self.bucket}/{self.key}".encode()).hexdigest()[:16]


class LegacyRuntimePurgeService:
    """One-time destructive maintenance for pre-policy test runtime data."""

    def __init__(
        self,
        *,
        database: Database,
        storage: ObjectStorage,
        storage_bucket: str,
    ) -> None:
        self.database = database
        self.storage = storage
        self.storage_bucket = storage_bucket

    def report(self) -> dict[str, Any]:
        objects = self._object_references()
        return {
            "runtime_rows": self._counts(RUNTIME_TABLE_DELETE_ORDER),
            "preserved_control_plane_rows": self._counts(PRESERVED_CONTROL_PLANE_TABLES),
            "preserved_unattributed_audit_rows": self._unattributed_audit_count(),
            "object_count": len(objects),
            "object_summaries": [item.summary for item in objects],
            "delete_order": list(RUNTIME_TABLE_DELETE_ORDER),
            "apply_required": True,
        }

    def purge(self) -> dict[str, Any]:
        before = self.report()
        objects = self._object_references()
        for item in objects:
            if item.bucket != self.storage_bucket:
                raise NonRetryableExecutionError(
                    f"Runtime object uses unexpected bucket: {item.bucket}",
                    safe_message=(
                        "旧运行数据包含不属于当前对象存储桶的文件，清理已停止，"
                        f"对象摘要：{item.summary}"
                    ),
                    error_code="legacy_runtime_object_bucket_mismatch",
                )
            try:
                self.storage.delete(key=item.key)
            except Exception as exc:
                raise NonRetryableExecutionError(
                    f"Could not delete runtime object {item.summary}",
                    safe_message=(
                        f"旧运行数据对象清理失败，数据库尚未删除，对象摘要：{item.summary}"
                    ),
                    error_code="legacy_runtime_object_delete_failed",
                ) from exc
        try:
            remaining_keys = set(self.storage.list_keys())
        except Exception as exc:
            raise NonRetryableExecutionError(
                "Could not verify runtime object deletion",
                safe_message="无法验证旧运行数据对象是否已清理，数据库尚未删除。",
                error_code="legacy_runtime_object_verification_failed",
            ) from exc
        remaining = [item for item in objects if item.key in remaining_keys]
        if remaining:
            summaries = ", ".join(item.summary for item in remaining[:10])
            raise NonRetryableExecutionError(
                f"Runtime objects remain after deletion: {summaries}",
                safe_message=(f"旧运行数据对象删除后仍可见，数据库尚未删除，对象摘要：{summaries}"),
                error_code="legacy_runtime_object_verification_failed",
            )

        with self.database.unit_of_work():
            self.database.execute(
                "update agent_job set webhook_event_id = null where webhook_event_id is not null"
            )
            for table in RUNTIME_TABLE_DELETE_ORDER:
                self.database.execute(RUNTIME_DELETE_SQL[table])
            if self.database.engine == "postgres":
                self.database.execute(
                    """
                    alter table agent_job
                    alter column execution_policy_json set not null
                    """
                )
            else:
                self._install_sqlite_policy_guards()

        after = {
            "runtime_rows": self._counts(RUNTIME_TABLE_DELETE_ORDER),
            "preserved_control_plane_rows": self._counts(PRESERVED_CONTROL_PLANE_TABLES),
            "preserved_unattributed_audit_rows": self._unattributed_audit_count(),
        }
        return {
            "applied": True,
            "before": before,
            "after": after,
            "deleted_object_count": len(objects),
        }

    def _object_references(self) -> list[RuntimeObjectReference]:
        references: dict[tuple[str, str], RuntimeObjectReference] = {}
        for row in self.database.execute(
            """
            select object_bucket, object_key
            from message_attachment
            where object_key <> ''
            """
        ):
            bucket = str(row.get("object_bucket") or self.storage_bucket)
            key = str(row.get("object_key") or "")
            if key:
                references[(bucket, key)] = RuntimeObjectReference(
                    bucket=bucket,
                    key=key,
                    source="message_attachment",
                )
        for row in self.database.execute(
            """
            select file_path from agent_artifact
            where file_path is not null and file_path <> ''
            """
        ):
            parsed = _object_path(str(row.get("file_path") or ""))
            if parsed is not None:
                bucket, key = parsed
                references[(bucket, key)] = RuntimeObjectReference(
                    bucket=bucket,
                    key=key,
                    source="agent_artifact",
                )
        return sorted(references.values(), key=lambda item: (item.bucket, item.key))

    def _counts(self, tables: tuple[str, ...]) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in tables:
            sql = (
                "select count(*) as count from audit_event where job_id is not null"
                if table == "audit_event"
                else f"select count(*) as count from {table}"
            )
            row = self.database.execute_one(sql)
            result[table] = int(row["count"] if row else 0)
        return result

    def _unattributed_audit_count(self) -> int:
        row = self.database.execute_one(
            "select count(*) as count from audit_event where job_id is null"
        )
        return int(row["count"] if row else 0)

    def _install_sqlite_policy_guards(self) -> None:
        self.database.execute(
            """
            create trigger if not exists trg_agent_job_execution_policy_insert
            before insert on agent_job
            when new.execution_policy_json is null
              or trim(new.execution_policy_json) = ''
            begin
              select raise(abort, 'execution_policy_json is required');
            end
            """
        )
        self.database.execute(
            """
            create trigger if not exists trg_agent_job_execution_policy_update
            before update of execution_policy_json on agent_job
            when new.execution_policy_json is null
              or trim(new.execution_policy_json) = ''
            begin
              select raise(abort, 'execution_policy_json is required');
            end
            """
        )


def _object_path(value: str) -> tuple[str, str] | None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"s3", "minio"} or not parsed.netloc:
        return None
    key = parsed.path.lstrip("/")
    return (parsed.netloc, key) if key else None
