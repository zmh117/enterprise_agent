from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from app.modules.platform_config.application.runtime_config import RuntimeConfigSnapshotBuilder
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound


DEFAULT_WORKSPACE_ACTIVE_FILE_LIMIT = 200
HARD_WORKSPACE_ACTIVE_FILE_LIMIT = 1000
DEFAULT_WORKSPACE_BILLABLE_BYTES_LIMIT = 2 * 1024 * 1024 * 1024
HARD_WORKSPACE_BILLABLE_BYTES_LIMIT = 10 * 1024 * 1024 * 1024

# Compatibility names for callers that still import the old constants. Their
# semantics are now governed defaults rather than immutable code-only caps.
MAX_WORKSPACE_FILES = DEFAULT_WORKSPACE_ACTIVE_FILE_LIMIT
MAX_TEMPORARY_BYTES = DEFAULT_WORKSPACE_BILLABLE_BYTES_LIMIT

QuotaOperationType = Literal[
    "ATTACHMENT_IMPORT",
    "FILE_PROCESSING",
    "FILE_COMMIT",
    "DERIVATIVE_WRITE",
]


@dataclass(frozen=True, slots=True)
class WorkspaceQuotaLimits:
    active_file_limit: int
    billable_bytes_limit: int
    config_revision: int
    active_file_limit_source: str
    billable_bytes_limit_source: str


@dataclass(frozen=True, slots=True)
class WorkspaceQuotaUsage:
    active_file_count: int
    billable_bytes: int
    reserved_file_slots: int
    reserved_billable_bytes: int

    @property
    def file_count(self) -> int:
        return self.active_file_count

    @property
    def temporary_bytes(self) -> int:
        return self.billable_bytes


@dataclass(frozen=True, slots=True)
class WorkspaceQuotaSnapshot:
    workspace_id: str
    tenant_id: str
    limits: WorkspaceQuotaLimits
    usage: WorkspaceQuotaUsage


class WorkspaceQuotaService:
    """Governed workspace quota reader and transactional reservation owner."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def effective_limits(self, workspace_id: str) -> WorkspaceQuotaLimits:
        workspace = self.database.execute_one(
            "select tenant_id from task_workspace where id = ?", (workspace_id,)
        )
        if workspace is None:
            raise NotFound("Workspace not found", safe_message="未找到任务工作区")
        snapshot = RuntimeConfigSnapshotBuilder(
            PlatformConfigRepository(self.database)
        ).build_snapshot(
            service_name="file-service",
            scopes={"tenant": str(workspace["tenant_id"])},
        )
        effective = snapshot.get("effective") or {}
        file_entry = effective.get("FILE_WORKSPACE_ACTIVE_FILE_LIMIT") or {}
        bytes_entry = effective.get("FILE_WORKSPACE_BILLABLE_BYTES_LIMIT") or {}
        return WorkspaceQuotaLimits(
            active_file_limit=self._bounded_int(
                file_entry.get("value"),
                default=DEFAULT_WORKSPACE_ACTIVE_FILE_LIMIT,
                hard_limit=HARD_WORKSPACE_ACTIVE_FILE_LIMIT,
            ),
            billable_bytes_limit=self._bounded_int(
                bytes_entry.get("value"),
                default=DEFAULT_WORKSPACE_BILLABLE_BYTES_LIMIT,
                hard_limit=HARD_WORKSPACE_BILLABLE_BYTES_LIMIT,
            ),
            config_revision=max(0, int(snapshot.get("revision") or 0)),
            active_file_limit_source=self._safe_source(file_entry.get("source")),
            billable_bytes_limit_source=self._safe_source(bytes_entry.get("source")),
        )

    def usage(self, workspace_id: str, *, now: str) -> WorkspaceQuotaUsage:
        count = self.database.execute_one(
            """
            select count(*) as value from task_workspace_file
             where workspace_id = ? and status = 'ACTIVE'
            """,
            (workspace_id,),
        )
        billable = self.database.execute_one(
            """
            select coalesce(sum(size_bytes), 0) as value
              from (
                select 'object:' || coalesce(v.object_key, 'sha256:' || v.content_sha256)
                       as object_identity, v.size_bytes
                  from managed_file_version v
                  join task_workspace_file wf on wf.file_id = v.file_id
                 where wf.workspace_id = ? and wf.status = 'ACTIVE'
                   and v.status in ('AVAILABLE', 'CONFLICT')
                   and not exists (
                     select 1 from file_retention_fact retention
                      where retention.version_id = v.id and retention.expires_at > ?
                   )
                union
                select 'object:' || coalesce(v.object_key, 'sha256:' || v.content_sha256),
                       v.size_bytes
                  from managed_file_version v
                  join file_conflict_candidate c on c.candidate_version_id = v.id
                  join file_commit_intent i on i.id = c.commit_intent_id
                 where i.workspace_id = ? and c.status = 'OPEN'
                   and v.status = 'CONFLICT'
                union
                select 'object:' || staging.object_key,
                       coalesce(staging.size_bytes, intent.size_bytes, 0)
                  from file_object_staging staging
                  join file_commit_intent intent
                    on intent.id = staging.commit_intent_id
                 where intent.workspace_id = ?
                   and staging.status in ('UPLOADING', 'COMPLETE', 'CLEANUP_PENDING')
                union
                select 'object:' || representation.object_key,
                       representation.size_bytes
                  from file_representation representation
                  join task_workspace_file wf
                    on wf.file_id = representation.source_file_id
                 where wf.workspace_id = ? and wf.status = 'ACTIVE'
                   and representation.status = 'AVAILABLE'
                union
                select 'object:' || transfer.staging_object_key,
                       transfer.received_size_bytes
                  from file_representation_transfer transfer
                  join file_processing_run run on run.id = transfer.processing_run_id
                  join task_workspace_file wf on wf.file_id = run.source_file_id
                 where wf.workspace_id = ? and wf.status = 'ACTIVE'
                   and transfer.status in ('UPLOADING', 'STAGED')
                union
                select 'object:' || transfer.staging_object_key,
                       transfer.received_size_bytes
                  from document_parent_artifact_transfer transfer
                  join file_processing_run run on run.id = transfer.processing_run_id
                  join task_workspace_file wf on wf.file_id = run.source_file_id
                 where wf.workspace_id = ? and wf.status = 'ACTIVE'
                   and transfer.status in ('UPLOADING', 'FINALIZED')
                union
                select 'object:' || asset.object_key, asset.size_bytes
                  from document_picture_asset asset
                  join task_workspace_file wf on wf.file_id = asset.source_file_id
                 where wf.workspace_id = ? and wf.status = 'ACTIVE'
                   and asset.status = 'AVAILABLE'
                union
                select 'object:' || transfer.staging_object_key,
                       transfer.received_size_bytes
                  from document_picture_asset_transfer transfer
                  join file_processing_run run on run.id = transfer.processing_run_id
                  join task_workspace_file wf on wf.file_id = run.source_file_id
                 where wf.workspace_id = ? and wf.status = 'ACTIVE'
                   and transfer.status in ('UPLOADING', 'STAGED')
                union
                select 'object:' || transfer.staging_object_key,
                       transfer.received_size_bytes
                  from document_picture_result_transfer transfer
                  join file_processing_run run on run.id = transfer.processing_run_id
                  join task_workspace_file wf on wf.file_id = run.source_file_id
                 where wf.workspace_id = ? and wf.status = 'ACTIVE'
                   and transfer.status in ('UPLOADING', 'STAGED', 'FINALIZED')
              ) billable_objects
            """,
            (workspace_id, now, *(workspace_id for _ in range(8))),
        )
        reserved = self.database.execute_one(
            """
            select coalesce(sum(logical_file_slots), 0) as file_slots,
                   coalesce(sum(billable_bytes), 0) as billable_bytes
              from task_workspace_quota_reservation
             where workspace_id = ? and status = 'RESERVED' and expires_at > ?
            """,
            (workspace_id, now),
        )
        return WorkspaceQuotaUsage(
            active_file_count=int((count or {}).get("value") or 0),
            billable_bytes=int((billable or {}).get("value") or 0),
            reserved_file_slots=int((reserved or {}).get("file_slots") or 0),
            reserved_billable_bytes=int((reserved or {}).get("billable_bytes") or 0),
        )

    def snapshot(self, workspace_id: str, *, now: str) -> WorkspaceQuotaSnapshot:
        workspace = self.database.execute_one(
            "select tenant_id from task_workspace where id = ?", (workspace_id,)
        )
        if workspace is None:
            raise NotFound("Workspace not found", safe_message="未找到任务工作区")
        return WorkspaceQuotaSnapshot(
            workspace_id=workspace_id,
            tenant_id=str(workspace["tenant_id"]),
            limits=self.effective_limits(workspace_id),
            usage=self.usage(workspace_id, now=now),
        )

    def reserve(
        self,
        *,
        workspace_id: str,
        operation_type: QuotaOperationType,
        operation_id: str,
        logical_file_slots: int,
        billable_bytes: int,
        expires_at: str,
        now: str,
    ) -> dict[str, object]:
        if logical_file_slots not in {0, 1} or billable_bytes < 0:
            self._deny("file_size_invalid", "文件配额预留参数无效")
        if not operation_id or len(operation_id) > 128:
            self._deny("file_quota_operation_invalid", "文件配额操作标识无效")
        with self.database.unit_of_work():
            self._lock_workspace(workspace_id)
            workspace = self.database.execute_one(
                "select tenant_id from task_workspace where id = ?", (workspace_id,)
            )
            if workspace is None:
                raise NotFound("Workspace not found", safe_message="未找到任务工作区")
            self.expire_reservations(workspace_id=workspace_id, now=now)
            existing = self.database.execute_one(
                """
                select * from task_workspace_quota_reservation
                 where workspace_id = ? and operation_type = ? and operation_id = ?
                """,
                (workspace_id, operation_type, operation_id),
            )
            if existing is not None:
                if (
                    int(existing["logical_file_slots"]) != logical_file_slots
                    or int(existing["billable_bytes"]) != billable_bytes
                ):
                    self._deny(
                        "file_quota_reservation_conflict",
                        "文件配额预留与原请求不一致",
                    )
                if str(existing["status"]) in {"RESERVED", "COMMITTED"}:
                    return existing
            limits = self.effective_limits(workspace_id)
            usage = self.usage(workspace_id, now=now)
            next_count = (
                usage.active_file_count + usage.reserved_file_slots + logical_file_slots
            )
            next_bytes = (
                usage.billable_bytes + usage.reserved_billable_bytes + billable_bytes
            )
            if next_count > limits.active_file_limit:
                self._deny(
                    "workspace_file_limit_exceeded",
                    f"工作区ACTIVE文件数量已达到 {limits.active_file_limit} 个上限",
                )
            if next_bytes > limits.billable_bytes_limit:
                self._deny(
                    "workspace_quota_exceeded",
                    "工作区计费内容已达到容量上限",
                )
            if existing is None:
                reservation_id = f"workspace_quota_{uuid.uuid4().hex}"
                self.database.execute(
                    """
                    insert into task_workspace_quota_reservation
                      (id, workspace_id, tenant_id, operation_type, operation_id,
                       logical_file_slots, billable_bytes, status, expires_at,
                       created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, 'RESERVED', ?, ?, ?)
                    """,
                    (
                        reservation_id,
                        workspace_id,
                        str(workspace["tenant_id"]),
                        operation_type,
                        operation_id,
                        logical_file_slots,
                        billable_bytes,
                        expires_at,
                        now,
                        now,
                    ),
                )
            else:
                reservation_id = str(existing["id"])
                self.database.execute(
                    """
                    update task_workspace_quota_reservation
                       set status = 'RESERVED', expires_at = ?, updated_at = ?,
                           finalized_at = null
                     where id = ? and status in ('RELEASED', 'EXPIRED')
                    """,
                    (expires_at, now, reservation_id),
                )
            return self._reservation(reservation_id)

    def finalize_operation(
        self,
        *,
        workspace_id: str,
        operation_type: QuotaOperationType,
        operation_id: str,
        committed: bool,
        now: str,
    ) -> dict[str, object]:
        row = self.database.execute_one(
            """
            select id from task_workspace_quota_reservation
             where workspace_id = ? and operation_type = ? and operation_id = ?
            """,
            (workspace_id, operation_type, operation_id),
        )
        if row is None:
            raise NotFound("Quota reservation not found", safe_message="未找到文件配额预留")
        return self.finalize_reservation(
            str(row["id"]), committed=committed, now=now
        )

    def finalize_reservation(
        self,
        reservation_id: str,
        *,
        committed: bool,
        now: str,
    ) -> dict[str, object]:
        target = "COMMITTED" if committed else "RELEASED"
        with self.database.unit_of_work():
            row = self._reservation(reservation_id)
            if str(row["status"]) == target:
                return row
            if str(row["status"]) != "RESERVED":
                self._deny(
                    "file_quota_reservation_terminal",
                    "文件配额预留已经终结",
                )
            self.database.execute(
                """
                update task_workspace_quota_reservation
                   set status = ?, updated_at = ?, finalized_at = ?
                 where id = ? and status = 'RESERVED'
                """,
                (target, now, now, reservation_id),
            )
            return self._reservation(reservation_id)

    def expire_reservations(self, *, workspace_id: str, now: str) -> int:
        rows = self.database.execute(
            """
            update task_workspace_quota_reservation
               set status = 'EXPIRED', updated_at = ?, finalized_at = ?
             where workspace_id = ? and status = 'RESERVED' and expires_at <= ?
            returning id
            """,
            (now, now, workspace_id, now),
        )
        return len(rows)

    def require_commit_capacity(
        self,
        *,
        workspace_id: str,
        incoming_bytes: int,
        creates_logical_file: bool,
        now: str,
    ) -> WorkspaceQuotaUsage:
        """Read-only compatibility guard; writers must use ``reserve``."""
        if incoming_bytes < 0:
            self._deny("file_size_invalid", "文件大小无效")
        limits = self.effective_limits(workspace_id)
        usage = self.usage(workspace_id, now=now)
        next_count = (
            usage.active_file_count
            + usage.reserved_file_slots
            + int(creates_logical_file)
        )
        if next_count > limits.active_file_limit:
            self._deny(
                "workspace_file_limit_exceeded",
                f"工作区ACTIVE文件数量已达到 {limits.active_file_limit} 个上限",
            )
        if (
            usage.billable_bytes
            + usage.reserved_billable_bytes
            + incoming_bytes
            > limits.billable_bytes_limit
        ):
            self._deny("workspace_quota_exceeded", "工作区计费内容已达到容量上限")
        return usage

    def _lock_workspace(self, workspace_id: str) -> None:
        suffix = " for update" if self.database.engine == "postgres" else ""
        row = self.database.execute_one(
            f"select id from task_workspace where id = ?{suffix}", (workspace_id,)
        )
        if row is None:
            raise NotFound("Workspace not found", safe_message="未找到任务工作区")

    def _reservation(self, reservation_id: str) -> dict[str, object]:
        row = self.database.execute_one(
            "select * from task_workspace_quota_reservation where id = ?",
            (reservation_id,),
        )
        if row is None:
            raise NotFound("Quota reservation not found", safe_message="未找到文件配额预留")
        return row

    @staticmethod
    def _bounded_int(value: object, *, default: int, hard_limit: int) -> int:
        if isinstance(value, bool):
            return default
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default
        return min(hard_limit, max(1, parsed))

    @staticmethod
    def _safe_source(value: object) -> str:
        source = str(value or "definition-default")
        return source[:128] or "definition-default"

    @staticmethod
    def _deny(code: str, message: str) -> None:
        raise NonRetryableExecutionError(
            "Workspace quota rejected the operation",
            safe_message=message,
            error_code=code,
        )
