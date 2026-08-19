from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from app.modules.file_workspace.domain import (
    CLEANUP_TRANSITIONS,
    COMMIT_TRANSITIONS,
    WORKSPACE_TRANSITIONS,
    CleanupResourceType,
    CleanupStatus,
    CommitDeliveryMode,
    CommitIntentStatus,
    CommitUserIntent,
    ConflictStatus,
    FileAction,
    FileOwner,
    FileSourceKind,
    FileVersionKind,
    FileVersionStatus,
    RetentionPeriod,
    RetentionReason,
    SnapshotSourceKind,
    StagingStatus,
    WorkspaceFileRole,
    WorkspaceStatus,
    ensure_transition,
)
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class FileWorkspaceRepository:
    """Single transactional mapping for the governed task-file aggregate."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_workspace(
        self,
        *,
        workspace_id: str,
        tenant_id: str,
        session_id: str,
        owner: FileOwner,
        publication_id: str,
        retention_period: RetentionPeriod,
        expires_at: str,
        actor_id: str,
    ) -> dict[str, Any]:
        timestamp = _now()
        owner_type, user_id, enterprise_id, connector_id, conversation_id = owner.database_values()
        try:
            self.database.execute(
                """
                insert into task_workspace
                  (id, tenant_id, session_id, owner_type, owner_user_id,
                   owner_enterprise_id, owner_connector_id, owner_conversation_id,
                   business_application_publication_id, retention_period,
                   retention_timezone, status, expires_at, created_by,
                   created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Asia/Shanghai',
                        'ACTIVE', ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    tenant_id,
                    session_id,
                    owner_type,
                    user_id,
                    enterprise_id,
                    connector_id,
                    conversation_id,
                    publication_id,
                    retention_period.value,
                    expires_at,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise NonRetryableExecutionError(
                    "Session already has an active workspace",
                    safe_message="当前会话已存在活动工作区",
                    error_code="workspace_active_conflict",
                ) from exc
            raise
        return self.get_workspace(workspace_id)

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return self._required("task_workspace", workspace_id, "未找到任务工作区")

    def get_active_workspace(self, session_id: str) -> dict[str, Any] | None:
        return self.database.execute_one(
            "select * from task_workspace where session_id = ? and status = 'ACTIVE'",
            (session_id,),
        )

    def transition_workspace(
        self, workspace_id: str, target: WorkspaceStatus, *, at: str | None = None
    ) -> dict[str, Any]:
        row = self.get_workspace(workspace_id)
        current = WorkspaceStatus(str(row["status"]))
        ensure_transition(current=current, target=target, transitions=WORKSPACE_TRANSITIONS)
        timestamp = at or _now()
        closed_at = (
            timestamp
            if target in {WorkspaceStatus.CLOSED, WorkspaceStatus.EXPIRED}
            else row["closed_at"]
        )
        changed = self.database.execute(
            """
            update task_workspace set status = ?, closed_at = ?, updated_at = ?
             where id = ? and status = ? returning id
            """,
            (target.value, closed_at, timestamp, workspace_id, current.value),
        )
        if not changed:
            self._state_conflict()
        return self.get_workspace(workspace_id)

    def create_file(
        self,
        *,
        file_id: str,
        tenant_id: str,
        owner: FileOwner,
        display_name: str,
        actor_id: str,
        source_received_at: str | None = None,
        format_code: str = "TXT",
    ) -> dict[str, Any]:
        timestamp = _now()
        owner_type, user_id, enterprise_id, connector_id, conversation_id = owner.database_values()
        self.database.execute(
            """
            insert into managed_file
              (id, tenant_id, owner_type, owner_user_id, owner_enterprise_id,
               owner_connector_id, owner_conversation_id, display_name, status,
               format_code, created_by, source_received_at, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                tenant_id,
                owner_type,
                user_id,
                enterprise_id,
                connector_id,
                conversation_id,
                display_name,
                format_code,
                actor_id,
                source_received_at,
                timestamp,
                timestamp,
            ),
        )
        return self.get_file(file_id)

    def get_file(self, file_id: str) -> dict[str, Any]:
        return self._required("managed_file", file_id, "未找到文件")

    def get_version(self, version_id: str) -> dict[str, Any]:
        return self._required("managed_file_version", version_id, "未找到文件版本")

    def mark_content_unavailable(
        self,
        *,
        version_id: str,
        deleted_at: str | None = None,
    ) -> dict[str, Any]:
        timestamp = deleted_at or _now()
        with self.database.unit_of_work():
            version = self.get_version(version_id)
            self.database.execute(
                """
                update managed_file_version
                   set status = 'CONTENT_UNAVAILABLE', content_deleted_at = ?
                 where id = ? and status in ('AVAILABLE', 'CONFLICT')
                """,
                (timestamp, version_id),
            )
            self.database.execute(
                """
                update managed_file
                   set status = 'CONTENT_UNAVAILABLE', updated_at = ?
                 where id = ? and current_version_id = ? and status = 'ACTIVE'
                """,
                (timestamp, version["file_id"], version_id),
            )
        return self.get_version(version_id)

    def require_content_available(self, version_id: str) -> dict[str, Any]:
        version = self.get_version(version_id)
        if str(version["status"]) not in {"AVAILABLE", "CONFLICT"}:
            raise NonRetryableExecutionError(
                "Managed file content is no longer available",
                safe_message="文件内容已清理，请重新发送或上传",
                error_code="file_content_unavailable",
            )
        return version

    def create_version(
        self,
        *,
        version_id: str,
        file_id: str,
        version_number: int,
        version_kind: FileVersionKind,
        status: FileVersionStatus,
        media_type: str,
        encoding: str,
        size_bytes: int,
        content_sha256: str,
        object_key: str,
        source_kind: FileSourceKind,
        actor_id: str,
        format_code: str = "TXT",
        parent_version_id: str | None = None,
        base_version_id: str | None = None,
        source_reference_digest: str = "",
        advance_current_from: str | None = None,
    ) -> dict[str, Any]:
        timestamp = _now()
        with self.database.unit_of_work():
            self.database.execute(
                """
                insert into managed_file_version
                  (id, file_id, version_number, parent_version_id, base_version_id,
                   version_kind, status, media_type, encoding, size_bytes,
                   format_code, content_sha256, object_key, source_kind, source_reference_digest,
                   created_by, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    file_id,
                    version_number,
                    parent_version_id,
                    base_version_id,
                    version_kind.value,
                    status.value,
                    media_type,
                    encoding,
                    size_bytes,
                    format_code,
                    content_sha256,
                    object_key,
                    source_kind.value,
                    source_reference_digest,
                    actor_id,
                    timestamp,
                ),
            )
            if advance_current_from is not None:
                changed = self.database.execute(
                    """
                    update managed_file set current_version_id = ?, updated_at = ?
                     where id = ? and coalesce(current_version_id, '') = ? returning id
                    """,
                    (version_id, timestamp, file_id, advance_current_from),
                )
                if not changed:
                    self._state_conflict()
        return self.get_version(version_id)

    def link_workspace_file(
        self,
        *,
        workspace_id: str,
        file_id: str,
        version_id: str,
        logical_name: str,
        role: WorkspaceFileRole,
    ) -> dict[str, Any]:
        link_id = _id("workspace_file")
        timestamp = _now()
        self.database.execute(
            """
            insert into task_workspace_file
              (id, workspace_id, file_id, selected_version_id, logical_name,
               role, status, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
            """,
            (
                link_id,
                workspace_id,
                file_id,
                version_id,
                logical_name,
                role.value,
                timestamp,
                timestamp,
            ),
        )
        return self._required("task_workspace_file", link_id, "未找到工作区文件")

    def add_external_reference(
        self,
        *,
        file_id: str,
        version_id: str,
        provider: str,
        source_type: str,
        source_id: str,
        source_digest: str = "",
    ) -> dict[str, Any]:
        reference_id = _id("file_ref")
        self.database.execute(
            """
            insert into file_external_reference
              (id, file_id, version_id, provider, source_type, source_id,
               source_digest, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference_id,
                file_id,
                version_id,
                provider,
                source_type,
                source_id,
                source_digest,
                _now(),
            ),
        )
        return self._required("file_external_reference", reference_id, "未找到文件来源")

    def create_job_snapshot(
        self,
        *,
        snapshot_id: str,
        job_id: str,
        workspace_id: str,
        tenant_id: str,
        principal_user_id: str,
        publication_id: str,
        retention_period: RetentionPeriod,
        manifest_hash: str,
        items: Iterable[dict[str, Any]],
        file_format_policy_version: str = "text-v1",
    ) -> dict[str, Any]:
        timestamp = _now()
        with self.database.unit_of_work():
            self.database.execute(
                """
                insert into agent_job_file_snapshot
                  (id, job_id, workspace_id, tenant_id, principal_user_id,
                   business_application_publication_id, retention_period,
                   schema_version, file_format_policy_version, manifest_hash, created_at)
                values (?, ?, ?, ?, ?, ?, ?, 4, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    job_id,
                    workspace_id,
                    tenant_id,
                    principal_user_id,
                    publication_id,
                    retention_period.value,
                    file_format_policy_version,
                    manifest_hash,
                    timestamp,
                ),
            )
            for ordinal, item in enumerate(items):
                actions = [
                    FileAction(str(action)).value for action in item.get("allowed_actions", [])
                ]
                source_received_at = (
                    item.get("source_received_at")
                    if "source_received_at" in item
                    else self.get_file(str(item["file_id"])).get("source_received_at")
                )
                version_created_at = str(item.get("version_created_at") or "")
                if not version_created_at:
                    version_created_at = str(
                        self.get_version(str(item["version_id"]))["created_at"]
                    )
                self.database.execute(
                    """
                    insert into agent_job_file_snapshot_item
                      (id, snapshot_id, ordinal, file_id, version_id, display_name,
                       format_code, source_kind, allowed_actions_json, auto_materialize,
                       conflict_candidate, source_received_at, version_created_at,
                       representation_id, representation_kind,
                       representation_size_bytes, representation_sha256,
                       representation_format_code, representation_created_at,
                       created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _id("file_snapshot_item"),
                        snapshot_id,
                        ordinal,
                        str(item["file_id"]),
                        str(item["version_id"]),
                        str(item["display_name"]),
                        str(item.get("format_code") or "TXT"),
                        SnapshotSourceKind(str(item["source_kind"])).value,
                        _json(actions),
                        int(bool(item.get("auto_materialize"))),
                        int(bool(item.get("conflict_candidate"))),
                        source_received_at,
                        version_created_at,
                        item.get("representation_id"),
                        item.get("representation_kind"),
                        item.get("representation_size_bytes"),
                        item.get("representation_sha256"),
                        item.get("representation_format_code"),
                        item.get("representation_created_at"),
                        timestamp,
                    ),
                )
        return self.get_job_snapshot(job_id)

    def register_job_file_request(
        self,
        *,
        job_id: str,
        workspace_id: str,
        tenant_id: str,
        principal_user_id: str,
        publication_id: str,
        retention_period: RetentionPeriod,
        explicit_references: Iterable[dict[str, Any]],
        file_format_policy_version: str = "text-v1",
    ) -> dict[str, Any]:
        timestamp = _now()
        references = [
            {
                "file_id": str(item["file_id"]),
                "version_id": str(item["version_id"]),
                "auto_materialize": bool(item.get("auto_materialize", True)),
            }
            for item in explicit_references
        ]
        self.database.execute(
            """
            insert into agent_job_file_request
              (job_id, workspace_id, tenant_id, principal_user_id,
               business_application_publication_id, retention_period,
               file_format_policy_version, explicit_references_json, status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
            on conflict(job_id) do nothing
            """,
            (
                job_id,
                workspace_id,
                tenant_id,
                principal_user_id,
                publication_id,
                retention_period.value,
                file_format_policy_version,
                _json(references),
                timestamp,
            ),
        )
        request = self.get_job_file_request(job_id)
        expected = {
            "workspace_id": workspace_id,
            "tenant_id": tenant_id,
            "principal_user_id": principal_user_id,
            "business_application_publication_id": publication_id,
            "retention_period": retention_period.value,
            "file_format_policy_version": file_format_policy_version,
            "explicit_references_json": _json(references),
        }
        if any(str(request.get(key) or "") != value for key, value in expected.items()):
            raise NonRetryableExecutionError(
                "Idempotent Job file request does not match",
                safe_message="任务文件请求与已保存记录不一致",
                error_code="file_request_idempotency_conflict",
            )
        return request

    def get_job_file_request(self, job_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from agent_job_file_request where job_id = ?", (job_id,)
        )
        if row is None:
            raise NotFound("Job file request not found", safe_message="未找到任务文件请求")
        try:
            references = json.loads(str(row.get("explicit_references_json") or "[]"))
        except json.JSONDecodeError as exc:
            raise NonRetryableExecutionError(
                "Job file request references are invalid",
                safe_message="任务文件请求无效",
                error_code="file_request_invalid",
            ) from exc
        if not isinstance(references, list):
            raise NonRetryableExecutionError(
                "Job file request references are invalid",
                safe_message="任务文件请求无效",
                error_code="file_request_invalid",
            )
        row["explicit_references"] = references
        return row

    def finalize_job_file_request(self, job_id: str) -> dict[str, Any]:
        timestamp = _now()
        changed = self.database.execute(
            """
            update agent_job_file_request
               set status = 'FINALIZED', finalized_at = ?
             where job_id = ? and status = 'PENDING' returning job_id
            """,
            (timestamp, job_id),
        )
        if not changed:
            current = self.get_job_file_request(job_id)
            if str(current["status"]) != "FINALIZED":
                self._state_conflict()
        return self.get_job_file_request(job_id)

    def get_job_snapshot(self, job_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from agent_job_file_snapshot where job_id = ?", (job_id,)
        )
        if row is None:
            raise NotFound("Job file snapshot not found", safe_message="未找到任务文件清单")
        row["items"] = self.database.execute(
            "select * from agent_job_file_snapshot_item where snapshot_id = ? order by ordinal",
            (row["id"],),
        )
        return row

    def create_commit_intent(
        self,
        *,
        intent_id: str,
        commit_id: str,
        job_id: str,
        workspace_id: str,
        sandbox_entry_handle: str,
        display_name: str,
        user_intent: CommitUserIntent,
        delivery_mode: CommitDeliveryMode,
        metadata_hash: str,
        expires_at: str,
        target_file_id: str | None = None,
        base_version_id: str | None = None,
        file_format_policy_version: str = "text-v1",
        format_code: str = "TXT",
    ) -> dict[str, Any]:
        timestamp = _now()
        self.database.execute(
            """
            insert into file_commit_intent
              (id, commit_id, job_id, workspace_id, target_file_id,
               base_version_id, sandbox_entry_handle, display_name, user_intent,
               delivery_mode, file_format_policy_version, format_code,
               metadata_hash, status, expires_at, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'INTENT', ?, ?, ?)
            """,
            (
                intent_id,
                commit_id,
                job_id,
                workspace_id,
                target_file_id,
                base_version_id,
                sandbox_entry_handle,
                display_name,
                user_intent.value,
                delivery_mode.value,
                file_format_policy_version,
                format_code,
                metadata_hash,
                expires_at,
                timestamp,
                timestamp,
            ),
        )
        return self.get_commit_intent(intent_id)

    def get_commit_intent(self, intent_id: str) -> dict[str, Any]:
        return self._required("file_commit_intent", intent_id, "未找到文件提交意图")

    def get_commit_intent_by_commit_id(self, commit_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from file_commit_intent where commit_id = ?", (commit_id,)
        )
        if row is None:
            raise NotFound("文件提交意图不存在", safe_message="未找到文件提交意图")
        return row

    def begin_commit_upload(
        self,
        *,
        commit_id: str,
        content_sha256: str,
        size_bytes: int,
        now: str,
    ) -> dict[str, Any]:
        """Bind one Commit ID to exactly one validated byte representation."""

        expired = False
        result: dict[str, Any] | None = None
        with self.database.unit_of_work():
            row = self.get_commit_intent_by_commit_id(commit_id)
            if str(row["expires_at"]) <= now and str(row["status"]) == "INTENT":
                self.database.execute(
                    """
                    update file_commit_intent
                       set status = 'EXPIRED', failure_code = 'file_commit_expired',
                           updated_at = ?, finished_at = ?
                     where id = ? and status = 'INTENT'
                    """,
                    (now, now, row["id"]),
                )
                expired = True
            else:
                current_hash = str(row.get("content_sha256") or "")
                current_size = row.get("size_bytes")
                if current_hash and (
                    current_hash != content_sha256 or int(current_size or 0) != size_bytes
                ):
                    raise NonRetryableExecutionError(
                        "Commit ID is bound to different content",
                        safe_message="提交标识已绑定不同内容",
                        error_code="file_commit_idempotency_conflict",
                    )
                status = str(row["status"])
                if status in {"COMMITTED", "CONFLICT"}:
                    result = row
                elif status in {"REJECTED", "EXPIRED"}:
                    raise NonRetryableExecutionError(
                        "File Commit Intent is terminal",
                        safe_message="文件提交意图已失效",
                        error_code=str(row.get("failure_code") or "file_commit_expired"),
                    )
                else:
                    if status == "INTENT":
                        changed = self.database.execute(
                            """
                            update file_commit_intent
                               set status = 'UPLOADING', content_sha256 = ?,
                                   size_bytes = ?, updated_at = ?
                             where id = ? and status = 'INTENT' returning id
                            """,
                            (content_sha256, size_bytes, now, row["id"]),
                        )
                        if not changed:
                            self._state_conflict()
                    elif not current_hash:
                        changed = self.database.execute(
                            """
                            update file_commit_intent
                               set content_sha256 = ?, size_bytes = ?, updated_at = ?
                             where id = ? and status = 'UPLOADING'
                               and content_sha256 is null returning id
                            """,
                            (content_sha256, size_bytes, now, row["id"]),
                        )
                        if not changed:
                            self._state_conflict()
                    result = self.get_commit_intent(str(row["id"]))
        if expired:
            raise NonRetryableExecutionError(
                "File Commit Intent expired",
                safe_message="文件提交意图已过期",
                error_code="file_commit_expired",
            )
        assert result is not None
        return result

    def transition_commit_intent(
        self,
        intent_id: str,
        target: CommitIntentStatus,
        *,
        failure_code: str = "",
        result_version_id: str | None = None,
        conflict_version_id: str | None = None,
    ) -> dict[str, Any]:
        row = self.get_commit_intent(intent_id)
        current = CommitIntentStatus(str(row["status"]))
        ensure_transition(current=current, target=target, transitions=COMMIT_TRANSITIONS)
        timestamp = _now()
        finished_at = (
            timestamp
            if target not in {CommitIntentStatus.INTENT, CommitIntentStatus.UPLOADING}
            else None
        )
        changed = self.database.execute(
            """
            update file_commit_intent
               set status = ?, failure_code = ?, result_version_id = ?,
                   conflict_candidate_version_id = ?, updated_at = ?, finished_at = ?
             where id = ? and status = ? returning id
            """,
            (
                target.value,
                failure_code,
                result_version_id,
                conflict_version_id,
                timestamp,
                finished_at,
                intent_id,
                current.value,
            ),
        )
        if not changed:
            self._state_conflict()
        return self.get_commit_intent(intent_id)

    def create_staging(self, *, intent_id: str, object_key: str) -> dict[str, Any]:
        staging_id = _id("file_staging")
        timestamp = _now()
        self.database.execute(
            """
            insert into file_object_staging
              (id, commit_intent_id, object_key, status, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                staging_id,
                intent_id,
                object_key,
                StagingStatus.UPLOADING.value,
                timestamp,
                timestamp,
            ),
        )
        return self._required("file_object_staging", staging_id, "未找到暂存对象")

    def get_staging_for_intent(self, intent_id: str) -> dict[str, Any] | None:
        return self.database.execute_one(
            "select * from file_object_staging where commit_intent_id = ?",
            (intent_id,),
        )

    def get_staging(self, staging_id: str) -> dict[str, Any]:
        return self._required("file_object_staging", staging_id, "未找到暂存对象")

    def update_staging(
        self,
        *,
        staging_id: str,
        status: StagingStatus,
        size_bytes: int | None = None,
        content_sha256: str | None = None,
        failure_code: str = "",
    ) -> dict[str, Any]:
        current_row = self._required("file_object_staging", staging_id, "未找到暂存对象")
        current = StagingStatus(str(current_row["status"]))
        if current is status:
            return current_row
        allowed = {
            StagingStatus.UPLOADING: {
                StagingStatus.COMPLETE,
                StagingStatus.CLEANUP_PENDING,
                StagingStatus.DELETED,
            },
            StagingStatus.COMPLETE: {
                StagingStatus.PUBLISHED,
                StagingStatus.CLEANUP_PENDING,
                StagingStatus.DELETED,
            },
            StagingStatus.PUBLISHED: set(),
            StagingStatus.CLEANUP_PENDING: {StagingStatus.DELETED},
            StagingStatus.DELETED: set(),
        }
        if status not in allowed[current]:
            if current is StagingStatus.PUBLISHED:
                return current_row
            self._state_conflict()
        timestamp = _now()
        completed_at = (
            timestamp if status in {StagingStatus.COMPLETE, StagingStatus.PUBLISHED} else None
        )
        deleted_at = timestamp if status is StagingStatus.DELETED else None
        changed = self.database.execute(
            """
            update file_object_staging
               set status = ?, size_bytes = coalesce(?, size_bytes),
                   content_sha256 = coalesce(?, content_sha256),
                   failure_code = ?, updated_at = ?,
                   completed_at = coalesce(?, completed_at),
                   deleted_at = coalesce(?, deleted_at)
             where id = ? and status = ? returning id
            """,
            (
                status.value,
                size_bytes,
                content_sha256,
                failure_code,
                timestamp,
                completed_at,
                deleted_at,
                staging_id,
                current.value,
            ),
        )
        if not changed:
            latest = self._required("file_object_staging", staging_id, "未找到暂存对象")
            if str(latest["status"]) == StagingStatus.PUBLISHED.value:
                return latest
            self._state_conflict()
        return self._required("file_object_staging", staging_id, "未找到暂存对象")

    def create_materialization_transfer(
        self,
        *,
        transfer_id: str,
        job_id: str,
        workspace_id: str,
        file_id: str,
        version_id: str,
        sandbox_entry_handle: str,
        relative_path: str,
        expected_size_bytes: int,
        expected_sha256: str,
        expires_at: str,
        format_code: str = "TXT",
    ) -> dict[str, Any]:
        row_id = _id("file_transfer")
        self.database.execute(
            """
            insert into file_materialization_transfer
              (id, transfer_id, job_id, workspace_id, file_id, version_id,
               sandbox_entry_handle, relative_path, expected_size_bytes,
               expected_sha256, format_code, status, expires_at, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'READY', ?, ?)
            """,
            (
                row_id,
                transfer_id,
                job_id,
                workspace_id,
                file_id,
                version_id,
                sandbox_entry_handle,
                relative_path,
                expected_size_bytes,
                expected_sha256,
                format_code,
                expires_at,
                _now(),
            ),
        )
        return self._required("file_materialization_transfer", row_id, "未找到文件物化传输")

    def consume_materialization_transfer(
        self, *, transfer_id: str, job_id: str, now: str
    ) -> dict[str, Any]:
        with self.database.unit_of_work():
            row = self.database.execute_one(
                "select * from file_materialization_transfer where transfer_id = ?",
                (transfer_id,),
            )
            if row is None or str(row["job_id"]) != job_id:
                raise NotFound("文件物化传输不存在", safe_message="未找到文件传输")
            if str(row["expires_at"]) <= now:
                self.database.execute(
                    """
                    update file_materialization_transfer set status = 'EXPIRED'
                     where id = ? and status = 'READY'
                    """,
                    (row["id"],),
                )
                raise NonRetryableExecutionError(
                    "File materialization transfer expired",
                    safe_message="文件传输已过期",
                    error_code="file_transfer_expired",
                )
            changed = self.database.execute(
                """
                update file_materialization_transfer
                   set status = 'CONSUMED', consumed_at = ?
                 where id = ? and status = 'READY' returning id
                """,
                (now, row["id"]),
            )
            if not changed:
                raise NonRetryableExecutionError(
                    "File materialization transfer was already consumed",
                    safe_message="文件传输已使用",
                    error_code="file_transfer_consumed",
                )
            return self._required(
                "file_materialization_transfer", str(row["id"]), "未找到文件物化传输"
            )

    def update_workspace_file_version(
        self,
        *,
        workspace_id: str,
        file_id: str,
        version_id: str,
        role: WorkspaceFileRole,
        logical_name: str,
    ) -> dict[str, Any]:
        timestamp = _now()
        changed = self.database.execute(
            """
            update task_workspace_file
               set selected_version_id = ?, role = ?, logical_name = ?, updated_at = ?
             where workspace_id = ? and file_id = ? and status = 'ACTIVE'
             returning id
            """,
            (version_id, role.value, logical_name, timestamp, workspace_id, file_id),
        )
        if not changed:
            self._state_conflict()
        return self._required("task_workspace_file", str(changed[0]["id"]), "未找到工作区文件")

    def add_domain_outbox(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        outbox_id = _id("file_outbox")
        timestamp = _now()
        self.database.execute(
            """
            insert into file_domain_outbox
              (id, event_type, aggregate_type, aggregate_id, payload_json,
               status, created_at, updated_at)
            values (?, ?, ?, ?, ?, 'PENDING', ?, ?)
            on conflict(event_type, aggregate_id) do nothing
            """,
            (
                outbox_id,
                event_type,
                aggregate_type,
                aggregate_id,
                _json(payload),
                timestamp,
                timestamp,
            ),
        )
        row = self.database.execute_one(
            "select * from file_domain_outbox where event_type = ? and aggregate_id = ?",
            (event_type, aggregate_id),
        )
        if row is None:
            raise RuntimeError("File Outbox insert failed")
        return row

    def claim_domain_outbox(self, *, worker_id: str) -> dict[str, Any] | None:
        """Claim one event inside the caller's Unit of Work.

        Publication currently targets the database-backed unified audit sink,
        so the row lock can cover projection and terminal state atomically.
        """
        if self.database.current_unit_of_work is None:
            raise RuntimeError("File Domain Outbox claim requires a Unit of Work")
        timestamp = _now()
        if self.database.engine == "postgres":
            rows = self.database.execute(
                """
                with candidate as (
                  select id from file_domain_outbox
                   where status in ('PENDING', 'FAILED')
                   order by created_at, id
                   for update skip locked
                   limit 1
                )
                update file_domain_outbox
                   set attempt_count = attempt_count + 1,
                       failure_code = '', updated_at = ?
                 where id = (select id from candidate)
                returning *
                """,
                (timestamp,),
            )
        else:
            rows = self.database.execute(
                """
                update file_domain_outbox
                   set attempt_count = attempt_count + 1,
                       failure_code = '', updated_at = ?
                 where id = (
                   select id from file_domain_outbox
                    where status in ('PENDING', 'FAILED')
                    order by created_at, id limit 1
                 )
                   and status in ('PENDING', 'FAILED')
                returning *
                """,
                (timestamp,),
            )
        return rows[0] if rows else None

    def mark_domain_outbox_published(self, outbox_id: str) -> None:
        timestamp = _now()
        changed = self.database.execute(
            """
            update file_domain_outbox
               set status = 'PUBLISHED', published_at = ?, failure_code = '',
                   updated_at = ?
             where id = ? and status in ('PENDING', 'FAILED')
            returning id
            """,
            (timestamp, timestamp, outbox_id),
        )
        if not changed:
            self._state_conflict()

    def mark_domain_outbox_failed(self, outbox_id: str, *, failure_code: str) -> None:
        timestamp = _now()
        changed = self.database.execute(
            """
            update file_domain_outbox
               set status = 'FAILED', attempt_count = attempt_count + 1,
                   failure_code = ?, updated_at = ?
             where id = ? and status in ('PENDING', 'FAILED')
            returning id
            """,
            (failure_code[:128], timestamp, outbox_id),
        )
        if not changed:
            self._state_conflict()

    def domain_outbox_metrics(self) -> dict[str, int | str]:
        row = (
            self.database.execute_one(
                """
            select
              sum(case when status in ('PENDING', 'FAILED') then 1 else 0 end)
                as backlog,
              min(case when status in ('PENDING', 'FAILED') then created_at end)
                as earliest_created_at
              from file_domain_outbox
            """
            )
            or {}
        )
        failure = (
            self.database.execute_one(
                """
            select failure_code from file_domain_outbox
             where status = 'FAILED'
             order by updated_at desc, id desc
             limit 1
            """
            )
            or {}
        )
        return {
            "domain_outbox_backlog": int(row.get("backlog") or 0),
            "domain_outbox_earliest_created_at": str(row.get("earliest_created_at") or ""),
            "domain_outbox_failure_code": str(failure.get("failure_code") or ""),
        }

    def record_conflict(
        self,
        *,
        intent_id: str,
        file_id: str,
        base_version_id: str,
        current_version_id: str,
        candidate_version_id: str,
    ) -> dict[str, Any]:
        conflict_id = _id("file_conflict")
        self.database.execute(
            """
            insert into file_conflict_candidate
              (id, commit_intent_id, file_id, base_version_id, current_version_id,
               candidate_version_id, status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conflict_id,
                intent_id,
                file_id,
                base_version_id,
                current_version_id,
                candidate_version_id,
                ConflictStatus.OPEN.value,
                _now(),
            ),
        )
        return self._required("file_conflict_candidate", conflict_id, "未找到冲突候选")

    def add_retention(
        self,
        *,
        version_id: str,
        reason: RetentionReason,
        source_id: str,
        starts_at: str,
        expires_at: str,
        retention_days: int = 360,
    ) -> dict[str, Any]:
        retention_id = _id("file_retention")
        self.database.execute(
            """
            insert into file_retention_fact
              (id, version_id, reason, source_id, retention_days, starts_at,
               expires_at, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                retention_id,
                version_id,
                reason.value,
                source_id,
                retention_days,
                starts_at,
                expires_at,
                _now(),
            ),
        )
        return self._required("file_retention_fact", retention_id, "未找到文件保留事实")

    def enqueue_cleanup(
        self,
        *,
        resource_type: CleanupResourceType,
        resource_id: str,
        reason: str,
        due_at: str,
    ) -> dict[str, Any]:
        cleanup_id = _id("file_cleanup")
        timestamp = _now()
        self.database.execute(
            """
            insert into file_cleanup_fact
              (id, resource_type, resource_id, reason, status, due_at,
               next_attempt_at, created_at, updated_at)
            values (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)
            """,
            (
                cleanup_id,
                resource_type.value,
                resource_id,
                reason,
                due_at,
                due_at,
                timestamp,
                timestamp,
            ),
        )
        return self._required("file_cleanup_fact", cleanup_id, "未找到文件清理事实")

    def claim_cleanup(self, cleanup_id: str, *, worker_id: str, now: str) -> dict[str, Any]:
        row = self._required("file_cleanup_fact", cleanup_id, "未找到文件清理事实")
        current = CleanupStatus(str(row["status"]))
        ensure_transition(
            current=current, target=CleanupStatus.CLAIMED, transitions=CLEANUP_TRANSITIONS
        )
        changed = self.database.execute(
            """
            update file_cleanup_fact
               set status = 'CLAIMED', attempt_count = attempt_count + 1,
                   claimed_by = ?, claimed_at = ?, updated_at = ?
             where id = ? and status = ? and next_attempt_at <= ? returning id
            """,
            (worker_id, now, now, cleanup_id, current.value, now),
        )
        if not changed:
            self._state_conflict()
        return self._required("file_cleanup_fact", cleanup_id, "未找到文件清理事实")

    def finish_cleanup(
        self,
        cleanup_id: str,
        *,
        status: CleanupStatus,
        now: str,
        next_attempt_at: str | None = None,
        failure_code: str = "",
    ) -> dict[str, Any]:
        if status not in {CleanupStatus.RETRY, CleanupStatus.COMPLETED, CleanupStatus.DEAD}:
            raise ValueError("Cleanup completion status is invalid")
        row = self._required("file_cleanup_fact", cleanup_id, "未找到文件清理事实")
        current = CleanupStatus(str(row["status"]))
        ensure_transition(current=current, target=status, transitions=CLEANUP_TRANSITIONS)
        changed = self.database.execute(
            """
            update file_cleanup_fact
               set status = ?, next_attempt_at = ?, failure_code = ?,
                   updated_at = ?, completed_at = ?
             where id = ? and status = 'CLAIMED' returning id
            """,
            (
                status.value,
                next_attempt_at or now,
                failure_code,
                now,
                now if status in {CleanupStatus.COMPLETED, CleanupStatus.DEAD} else None,
                cleanup_id,
            ),
        )
        if not changed:
            self._state_conflict()
        return self._required("file_cleanup_fact", cleanup_id, "未找到文件清理事实")

    def bind_attachment(
        self,
        *,
        attachment_id: str,
        file_id: str,
        version_id: str,
        retention_expires_at: str,
    ) -> None:
        with self.database.unit_of_work():
            self.database.execute(
                """
                insert into message_attachment_file_binding
                  (attachment_id, file_id, version_id, retention_expires_at, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (attachment_id, file_id, version_id, retention_expires_at, _now()),
            )
            self.database.execute(
                """
                update message_attachment
                   set managed_file_id = ?, managed_file_version_id = ?,
                       expires_at = ?
                 where id = ?
                """,
                (file_id, version_id, retention_expires_at, attachment_id),
            )

    def _required(self, table: str, identity: str, safe_message: str) -> dict[str, Any]:
        allowed = {
            "task_workspace",
            "managed_file",
            "managed_file_version",
            "task_workspace_file",
            "file_external_reference",
            "file_materialization_transfer",
            "file_commit_intent",
            "file_object_staging",
            "file_conflict_candidate",
            "file_retention_fact",
            "file_cleanup_fact",
            "file_domain_outbox",
        }
        if table not in allowed:
            raise RuntimeError("Unsupported file repository table")
        row = self.database.execute_one(f"select * from {table} where id = ?", (identity,))
        if row is None:
            raise NotFound(f"File resource not found: {table}", safe_message=safe_message)
        return row

    @staticmethod
    def _state_conflict() -> None:
        raise NonRetryableExecutionError(
            "Task file state changed concurrently",
            safe_message="文件状态已变化，请刷新后重试",
            error_code="file_state_conflict",
        )
