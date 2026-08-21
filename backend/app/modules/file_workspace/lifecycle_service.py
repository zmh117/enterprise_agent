from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol
import uuid

from app.modules.file_workspace.domain import (
    CleanupResourceType,
    CleanupStatus,
    StagingStatus,
    WorkspaceStatus,
)
from app.modules.file_workspace.domain_outbox import FileDomainOutboxPublisher
from app.modules.file_workspace.repository import FileWorkspaceRepository


class FileLifecycleStorage(Protocol):
    def delete(self, *, internal_object_key: str) -> None: ...

    def exists(self, *, internal_object_key: str) -> bool: ...

    def list_keys(self) -> list[str]: ...


def _now() -> datetime:
    return datetime.now(UTC)


class FileLifecycleService:
    """Database-led lifecycle worker. Unknown storage objects are report-only."""

    def __init__(
        self,
        repository: FileWorkspaceRepository,
        storage: FileLifecycleStorage,
        *,
        legacy_attachment_storage: FileLifecycleStorage | None = None,
        legacy_attachment_bucket: str = "",
        now: Callable[[], datetime] = _now,
        batch_size: int = 100,
        domain_outbox: FileDomainOutboxPublisher | None = None,
    ) -> None:
        if not 1 <= batch_size <= 1000:
            raise ValueError("File lifecycle batch size is invalid")
        self.repository = repository
        self.storage = storage
        self.legacy_attachment_storage = legacy_attachment_storage
        self.legacy_attachment_bucket = legacy_attachment_bucket
        self.now = now
        self.batch_size = batch_size
        self.domain_outbox = domain_outbox

    def run_once(self, *, worker_id: str = "file-worker") -> dict[str, int | str]:
        timestamp = self.now().isoformat()
        expired, deferred = self._expire_workspaces(timestamp)
        discovered = self._discover_cleanup(timestamp)
        completed, retried, dead = self._process_cleanup(
            timestamp=timestamp, worker_id=worker_id
        )
        unknown, missing = self._reconcile_objects()
        cleaned = self._finish_workspaces()
        outbox = (
            self.domain_outbox.publish_pending(limit=self.batch_size)
            if self.domain_outbox is not None
            else None
        )
        return {
            "status": "SUCCEEDED",
            "workspaces_expired": expired,
            "workspaces_deferred": deferred,
            "workspaces_cleaned": cleaned,
            "cleanup_discovered": discovered,
            "cleanup_completed": completed,
            "cleanup_retried": retried,
            "cleanup_dead": dead,
            "unknown_orphan_objects": unknown,
            "missing_referenced_objects": missing,
            "domain_outbox_published": outbox.published if outbox is not None else 0,
            "domain_outbox_failed": outbox.failed if outbox is not None else 0,
        }

    def metrics(self) -> dict[str, int | str]:
        now = self.now().isoformat()
        counts = self.repository.database.execute_one(
            """
            select
              sum(case when status in ('PENDING', 'RETRY') then 1 else 0 end) as cleanup_backlog,
              sum(case when resource_type = 'STAGING_OBJECT' and status in ('PENDING', 'RETRY') then 1 else 0 end) as staging_backlog,
              sum(case when resource_type = 'ATTACHMENT_CONTENT' and status in ('PENDING', 'RETRY') then 1 else 0 end) as attachment_backlog,
              min(case when status in ('PENDING', 'RETRY') then next_attempt_at end) as earliest_due
            from file_cleanup_fact
            """
        ) or {}
        workspace = self.repository.database.execute_one(
            """
            select count(*) as value from task_workspace
             where status = 'ACTIVE' and expires_at <= ?
            """,
            (now,),
        ) or {}
        retained = self.repository.database.execute_one(
            "select count(*) as value from file_retention_fact where expires_at <= ?",
            (now,),
        ) or {}
        conflicts = self.repository.database.execute_one(
            "select count(*) as value from file_conflict_candidate where status = 'OPEN'",
        ) or {}
        return {
            "cleanup_backlog": int(counts.get("cleanup_backlog") or 0),
            "staging_backlog": int(counts.get("staging_backlog") or 0),
            "attachment_backlog": int(counts.get("attachment_backlog") or 0),
            "expired_workspace_backlog": int(workspace.get("value") or 0),
            "expired_retention_backlog": int(retained.get("value") or 0),
            "conflict_candidate_backlog": int(conflicts.get("value") or 0),
            "earliest_due": str(counts.get("earliest_due") or ""),
            **self.repository.domain_outbox_metrics(),
        }

    def _expire_workspaces(self, timestamp: str) -> tuple[int, int]:
        expired = 0
        deferred = 0
        rows = self.repository.database.execute(
            """
            select id from task_workspace
             where status = 'ACTIVE' and expires_at <= ?
             order by expires_at, id limit ?
            """,
            (timestamp, self.batch_size),
        )
        for row in rows:
            workspace_id = str(row["id"])
            if self._workspace_blocked(workspace_id):
                deferred += 1
                continue
            with self.repository.database.unit_of_work():
                self.repository.transition_workspace(
                    workspace_id, WorkspaceStatus.EXPIRED, at=timestamp
                )
                self.repository.transition_workspace(
                    workspace_id, WorkspaceStatus.CLEANING, at=timestamp
                )
                self.repository.database.execute(
                    """
                    update task_workspace_file
                       set status = 'REMOVED', removed_at = ?, updated_at = ?
                     where workspace_id = ? and status = 'ACTIVE'
                    """,
                    (timestamp, timestamp, workspace_id),
                )
                self.repository.enqueue_cleanup(
                    resource_type=CleanupResourceType.WORKSPACE,
                    resource_id=workspace_id,
                    reason="NATURAL_PERIOD_EXPIRED",
                    due_at=timestamp,
                )
            expired += 1
        return expired, deferred

    def _workspace_blocked(self, workspace_id: str) -> bool:
        row = self.repository.database.execute_one(
            """
            select 1 as blocked
              from agent_job j
             where j.task_workspace_id = ?
               and (
                 j.status in ('PENDING', 'WAITING_INPUT', 'RUNNING')
                 or exists (
                   select 1 from file_commit_intent c
                    where c.job_id = j.id and c.status in ('INTENT', 'UPLOADING')
                 )
                 or exists (
                   select 1 from delivery_outbox d
                    where d.job_id = j.id
                      and d.status in ('PENDING', 'RUNNING', 'RETRY_WAIT')
                 )
               )
             limit 1
            """,
            (workspace_id,),
        )
        return row is not None

    def _discover_cleanup(self, timestamp: str) -> int:
        discovered = 0
        candidates = self.repository.database.execute(
            """
            select v.id
              from managed_file_version v
             where v.status in ('AVAILABLE', 'CONFLICT')
               and not exists (
                 select 1 from task_workspace_file wf
                  where wf.selected_version_id = v.id and wf.status = 'ACTIVE'
               )
               and not exists (
                 select 1 from file_retention_fact r
                  where r.version_id = v.id and r.expires_at > ?
               )
               and not exists (
                 select 1 from file_conflict_candidate c
                  where c.candidate_version_id = v.id and c.status = 'OPEN'
               )
             order by v.created_at, v.id limit ?
            """,
            (timestamp, self.batch_size),
        )
        for row in candidates:
            if self._enqueue_once(
                CleanupResourceType.FILE_VERSION,
                str(row["id"]),
                "UNREFERENCED_CONTENT",
                timestamp,
            ):
                discovered += 1
        staging = self.repository.database.execute(
            """
            select s.id
              from file_object_staging s
              join file_commit_intent c on c.id = s.commit_intent_id
             where s.status = 'CLEANUP_PENDING'
                or (s.status in ('UPLOADING', 'COMPLETE') and c.expires_at <= ?)
             order by s.updated_at, s.id limit ?
            """,
            (timestamp, self.batch_size),
        )
        for row in staging:
            if self._enqueue_once(
                CleanupResourceType.STAGING_OBJECT,
                str(row["id"]),
                "STAGING_EXPIRED",
                timestamp,
            ):
                discovered += 1
        conflicts = self.repository.database.execute(
            """
            select c.id, c.candidate_version_id
              from file_conflict_candidate c
              join file_commit_intent i on i.id = c.commit_intent_id
              join task_workspace w on w.id = i.workspace_id
             where c.status = 'OPEN' and w.status in ('CLEANING', 'CLEANED')
             order by c.created_at, c.id limit ?
            """,
            (self.batch_size,),
        )
        for row in conflicts:
            self.repository.database.execute(
                "update file_conflict_candidate set status = 'EXPIRED' where id = ? and status = 'OPEN'",
                (row["id"],),
            )
            if self._enqueue_once(
                CleanupResourceType.FILE_VERSION,
                str(row["candidate_version_id"]),
                "CONFLICT_EXPIRED",
                timestamp,
            ):
                discovered += 1
        return discovered

    def _enqueue_once(
        self,
        resource_type: CleanupResourceType,
        resource_id: str,
        reason: str,
        due_at: str,
    ) -> bool:
        existing = self.repository.database.execute_one(
            """
            select id from file_cleanup_fact
             where resource_type = ? and resource_id = ? and reason = ?
            """,
            (resource_type.value, resource_id, reason),
        )
        if existing is not None:
            return False
        self.repository.enqueue_cleanup(
            resource_type=resource_type,
            resource_id=resource_id,
            reason=reason,
            due_at=due_at,
        )
        return True

    def _process_cleanup(
        self, *, timestamp: str, worker_id: str
    ) -> tuple[int, int, int]:
        completed = retried = dead = 0
        rows = self.repository.database.execute(
            """
            select id from file_cleanup_fact
             where status in ('PENDING', 'RETRY') and next_attempt_at <= ?
             order by next_attempt_at, id limit ?
            """,
            (timestamp, self.batch_size),
        )
        for row in rows:
            cleanup = self.repository.claim_cleanup(
                str(row["id"]), worker_id=worker_id, now=timestamp
            )
            try:
                outcome = self._execute_cleanup(cleanup, timestamp)
                if outcome == "defer":
                    self.repository.finish_cleanup(
                        str(cleanup["id"]),
                        status=CleanupStatus.RETRY,
                        now=timestamp,
                        next_attempt_at=(self.now() + timedelta(hours=1)).isoformat(),
                        failure_code="resource_still_referenced",
                    )
                    retried += 1
                else:
                    self.repository.finish_cleanup(
                        str(cleanup["id"]),
                        status=CleanupStatus.COMPLETED,
                        now=timestamp,
                    )
                    completed += 1
            except Exception as exc:
                attempts = int(cleanup["attempt_count"])
                target = CleanupStatus.DEAD if attempts >= 8 else CleanupStatus.RETRY
                self.repository.finish_cleanup(
                    str(cleanup["id"]),
                    status=target,
                    now=timestamp,
                    next_attempt_at=(
                        self.now() + timedelta(seconds=min(3600, 2**attempts * 15))
                    ).isoformat(),
                    failure_code=type(exc).__name__[:128],
                )
                if target is CleanupStatus.DEAD:
                    dead += 1
                else:
                    retried += 1
        return completed, retried, dead

    def _execute_cleanup(self, cleanup: dict[str, Any], timestamp: str) -> str:
        resource_type = CleanupResourceType(str(cleanup["resource_type"]))
        resource_id = str(cleanup["resource_id"])
        if resource_type is CleanupResourceType.WORKSPACE:
            if self._workspace_blocked(resource_id):
                return "defer"
            return "complete"
        if resource_type is CleanupResourceType.STAGING_OBJECT:
            staging = self.repository.get_staging(resource_id)
            if str(staging["status"]) == "PUBLISHED":
                return "complete"
            self.storage.delete(internal_object_key=str(staging["object_key"]))
            self.repository.update_staging(
                staging_id=resource_id, status=StagingStatus.DELETED
            )
            return "complete"
        if resource_type is CleanupResourceType.FILE_VERSION:
            if self._version_protected(resource_id, timestamp):
                return "defer"
            version = self.repository.get_version(resource_id)
            if str(version["status"]) in {"CONTENT_UNAVAILABLE", "DELETED"}:
                return "complete"
            self._enqueue_document_private_cleanup(resource_id, timestamp)
            processing_objects = self.repository.database.execute(
                """
                select id, object_key, 'representation' as object_kind
                  from file_representation
                 where source_version_id = ? and status = 'AVAILABLE'
                union all
                select t.id, t.staging_object_key as object_key,
                       'transfer' as object_kind
                  from file_representation_transfer t
                  join file_processing_run r on r.id = t.processing_run_id
                 where r.source_version_id = ?
                   and t.status in ('OPEN', 'UPLOADING', 'STAGED')
                """,
                (resource_id, resource_id),
            )
            for item in processing_objects:
                self.storage.delete(internal_object_key=str(item["object_key"]))
                if str(item["object_kind"]) == "representation":
                    self.repository.database.execute(
                        """
                        update file_representation
                           set status = 'CONTENT_UNAVAILABLE', content_deleted_at = ?
                         where id = ? and status = 'AVAILABLE'
                        """,
                        (timestamp, item["id"]),
                    )
                else:
                    self.repository.database.execute(
                        """
                        update file_representation_transfer
                           set status = 'EXPIRED', error_code = 'source_retired',
                               updated_at = ?
                         where id = ? and status in ('OPEN', 'UPLOADING', 'STAGED')
                        """,
                        (timestamp, item["id"]),
                    )
            self.storage.delete(internal_object_key=str(version["object_key"]))
            self.repository.mark_content_unavailable(version_id=resource_id)
            return "complete"
        if resource_type is CleanupResourceType.ATTACHMENT_CONTENT:
            attachment = self.repository.database.execute_one(
                "select * from message_attachment where id = ?", (resource_id,)
            )
            if attachment is None or str(attachment.get("status")) == "DELETED":
                return "complete"
            if str(attachment.get("expires_at") or "") > timestamp:
                return "defer"
            job_id = str(attachment.get("job_id") or "")
            if self._job_delivery_blocked(job_id):
                return "defer"
            managed_version_id = str(
                attachment.get("managed_file_version_id") or ""
            )
            if managed_version_id and self._version_protected(
                managed_version_id, timestamp
            ):
                return "defer"
            object_key = str(attachment.get("object_key") or "")
            if object_key:
                self._attachment_storage(attachment).delete(
                    internal_object_key=object_key
                )
            self.repository.database.execute(
                """
                update message_attachment
                   set status = 'DELETED', object_bucket = '', object_key = '',
                       content_deleted_at = ?, updated_at = ?
                 where id = ?
                """,
                (timestamp, timestamp, resource_id),
            )
            return "complete"
        return "complete"

    def _version_protected(self, version_id: str, timestamp: str) -> bool:
        row = self.repository.database.execute_one(
            """
            select 1 as protected
             where exists (
               select 1 from task_workspace_file
                where selected_version_id = ? and status = 'ACTIVE'
             ) or exists (
               select 1 from file_retention_fact
                where version_id = ? and expires_at > ?
             ) or exists (
               select 1 from file_conflict_candidate
                where candidate_version_id = ? and status = 'OPEN'
             ) or exists (
               select 1 from file_processing_run
                where source_version_id = ?
                  and status in ('QUEUED', 'SUBMITTED', 'RUNNING', 'RETRY_WAIT')
             )
            """,
            (version_id, version_id, timestamp, version_id, version_id),
        )
        return row is not None

    def _enqueue_document_private_cleanup(self, version_id: str, timestamp: str) -> None:
        rows = self.repository.database.execute(
            """
            select r.id as processing_run_id, 'PARENT_ARTIFACT' as object_kind,
                   p.id as object_id, p.staging_object_key as internal_object_key
              from document_parent_artifact_transfer p
              join file_processing_run r on r.id = p.processing_run_id
             where r.source_version_id = ?
               and p.status in ('OPEN', 'UPLOADING', 'STAGED', 'FINALIZED')
            union all
            select r.id as processing_run_id, 'PICTURE_ASSET' as object_kind,
                   a.id as object_id, a.object_key as internal_object_key
              from document_picture_asset a
              join file_processing_run r on r.id = a.processing_run_id
             where r.source_version_id = ? and a.status in ('STAGING', 'AVAILABLE')
            union all
            select r.id as processing_run_id, 'PICTURE_RESULT' as object_kind,
                   t.id as object_id, t.staging_object_key as internal_object_key
              from document_picture_result_transfer t
              join file_processing_run r on r.id = t.processing_run_id
             where r.source_version_id = ?
               and t.status in ('OPEN', 'UPLOADING', 'STAGED', 'FINALIZED')
            """,
            (version_id, version_id, version_id),
        )
        for row in rows:
            self.repository.database.execute(
                """
                insert into document_picture_cleanup_fact
                  (id, processing_run_id, object_kind, object_id, internal_object_key,
                   reason_code, status, next_attempt_at, created_at, updated_at)
                values (?, ?, ?, ?, ?, 'SOURCE_RETENTION_EXPIRED', 'PENDING', ?, ?, ?)
                on conflict(object_kind, object_id) do nothing
                """,
                (
                    f"document_picture_cleanup_{uuid.uuid4().hex}",
                    row["processing_run_id"],
                    row["object_kind"],
                    row["object_id"],
                    row["internal_object_key"],
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )

    def _job_delivery_blocked(self, job_id: str) -> bool:
        row = self.repository.database.execute_one(
            """
            select 1 as blocked from agent_job j
             where j.id = ? and (
               j.status in ('PENDING', 'WAITING_INPUT', 'RUNNING')
               or exists (
                 select 1 from delivery_outbox d where d.job_id = j.id
                   and d.status in ('PENDING', 'RUNNING', 'RETRY_WAIT')
               )
             )
            """,
            (job_id,),
        )
        return row is not None

    def _reconcile_objects(self) -> tuple[int, int]:
        managed_references = {
            str(row["object_key"])
            for query in (
                "select object_key from managed_file_version where status in ('AVAILABLE', 'CONFLICT')",
                "select object_key from file_object_staging where status <> 'DELETED'",
                "select object_key from file_representation where status = 'AVAILABLE'",
                "select staging_object_key as object_key from file_representation_transfer where status in ('OPEN', 'UPLOADING', 'STAGED')",
                "select staging_object_key as object_key from document_parent_artifact_transfer where status in ('OPEN', 'UPLOADING', 'STAGED', 'FINALIZED')",
                "select object_key from document_picture_asset where status in ('STAGING', 'AVAILABLE')",
                "select staging_object_key as object_key from document_picture_result_transfer where status in ('OPEN', 'UPLOADING', 'STAGED', 'FINALIZED')",
            )
            for row in self.repository.database.execute(query)
            if row.get("object_key")
        }
        attachment_rows = self.repository.database.execute(
            """
            select object_bucket, object_key from message_attachment
             where object_key <> '' and status <> 'DELETED'
            """
        )
        current_attachment_references = {
            str(row["object_key"])
            for row in attachment_rows
            if str(row.get("object_bucket") or "") == "file-service"
        }
        managed_references.update(current_attachment_references)
        stored = set(self.storage.list_keys())
        unknown = len(stored - managed_references)
        missing = sum(
            not self.storage.exists(internal_object_key=key)
            for key in managed_references
        )
        legacy_references = {
            str(row["object_key"])
            for row in attachment_rows
            if self.legacy_attachment_bucket
            and str(row.get("object_bucket") or "") == self.legacy_attachment_bucket
        }
        if self.legacy_attachment_storage is not None:
            legacy_stored = set(self.legacy_attachment_storage.list_keys())
            unknown += len(legacy_stored - legacy_references)
            missing += sum(
                not self.legacy_attachment_storage.exists(internal_object_key=key)
                for key in legacy_references
            )
        else:
            missing += len(legacy_references)
        known_buckets = {"file-service", self.legacy_attachment_bucket}
        missing += sum(
            str(row.get("object_bucket") or "") not in known_buckets
            for row in attachment_rows
        )
        return unknown, missing

    def _attachment_storage(
        self, attachment: dict[str, Any]
    ) -> FileLifecycleStorage:
        bucket = str(attachment.get("object_bucket") or "")
        if bucket == "file-service":
            return self.storage
        if (
            self.legacy_attachment_storage is not None
            and bucket == self.legacy_attachment_bucket
        ):
            return self.legacy_attachment_storage
        raise RuntimeError("Attachment object belongs to an unmanaged storage boundary")

    def _finish_workspaces(self) -> int:
        changed = self.repository.database.execute(
            """
            update task_workspace set status = 'CLEANED', updated_at = ?
             where status = 'CLEANING'
               and not exists (
                 select 1 from task_workspace_file wf
                  where wf.workspace_id = task_workspace.id and wf.status = 'ACTIVE'
               )
               and not exists (
                 select 1 from agent_job j
                  where j.task_workspace_id = task_workspace.id
                    and j.status in ('PENDING', 'WAITING_INPUT', 'RUNNING')
               )
             returning id
            """,
            (self.now().isoformat(),),
        )
        return len(changed)
