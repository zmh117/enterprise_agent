from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.modules.document_processing.domain import (
    PROCESSING_TERMINAL_STATUSES,
    PICTURE_ITEM_TERMINAL_STATUSES,
    PictureItemStatus,
    ProcessingRunStatus,
    RepresentationKind,
    decode_required_representation_kinds,
    require_processing_transition,
)
from app.modules.document_processing.profile import require_document_processing_profile
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound, PermissionDenied


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _safe_metric_error_code(value: object) -> str:
    code = str(value or "")[:128]
    if not code:
        return ""
    return code if code.replace("_", "").isalnum() else "unknown_error"


class DocumentProcessingRepository:
    """Durable File Service mapping for processing runs and representations."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_or_get_run(
        self,
        *,
        tenant_id: str,
        source_file_id: str,
        source_version_id: str,
        processor_version: str,
        processor_build_digest: str,
        profile_code: str,
        profile_hash: str,
        required_output_kinds: tuple[str, ...],
        run_deadline_at: str | None,
        actor_id: str,
    ) -> tuple[dict[str, Any], bool]:
        source = self.database.execute_one(
            """
            select v.*, f.tenant_id, f.status as file_status
              from managed_file_version v
              join managed_file f on f.id = v.file_id
             where v.id = ? and v.file_id = ?
            """,
            (source_version_id, source_file_id),
        )
        if source is None:
            raise NotFound(
                "Document processing source version not found",
                safe_message="未找到待处理文件版本",
            )
        if str(source["tenant_id"]) != tenant_id:
            raise PermissionDenied(
                "Cross-tenant document processing denied",
                safe_message="不能跨租户处理文件",
            )
        if str(source["status"]) != "AVAILABLE" or str(source["file_status"]) != "ACTIVE":
            self._deny("document_source_unavailable", "待处理文件内容不可用")
        profile = require_document_processing_profile(profile_code, profile_hash=profile_hash)
        if tuple(required_output_kinds) != profile.output_kinds:
            self._deny("document_representation_set_invalid", "文档派生表示集合无效")
        required_output_kinds_json = json.dumps(
            list(required_output_kinds), separators=(",", ":")
        )
        run_id = _id("file_processing_run")
        timestamp = _now()
        inserted = self.database.execute(
            """
            insert into file_processing_run
              (id, tenant_id, source_file_id, source_version_id, processor_code,
               processor_version, processor_build_digest, profile_code, profile_hash,
               status, source_size_bytes, required_output_kinds_json,
               run_deadline_at, assembly_status, created_by, created_at, updated_at)
            values (?, ?, ?, ?, 'docling-serve', ?, ?, ?, ?, 'QUEUED', ?, ?, ?, ?,
                    ?, ?, ?)
            on conflict(source_version_id, processor_build_digest, profile_hash)
            do nothing
            returning *
            """,
            (
                run_id,
                tenant_id,
                source_file_id,
                source_version_id,
                processor_version,
                processor_build_digest,
                profile.code.value,
                profile_hash,
                int(source["size_bytes"]),
                required_output_kinds_json,
                run_deadline_at,
                (
                    "PENDING"
                    if profile.layout_ocr_options is not None
                    else "NOT_REQUIRED"
                ),
                actor_id,
                timestamp,
                timestamp,
            ),
        )
        if inserted:
            return inserted[0], True
        existing = self.database.execute_one(
            """
            select * from file_processing_run
             where source_version_id = ? and processor_build_digest = ?
               and profile_hash = ?
            """,
            (source_version_id, processor_build_digest, profile_hash),
        )
        if existing is None:
            raise RuntimeError("Document processing idempotency lookup failed")
        if (
            str(existing["tenant_id"]) != tenant_id
            or str(existing["source_file_id"]) != source_file_id
            or str(existing["profile_code"]) != profile.code.value
            or str(existing["profile_hash"]) != profile_hash
            or str(existing["required_output_kinds_json"]) != required_output_kinds_json
        ):
            self._deny("document_processing_identity_conflict", "文档处理身份冲突")
        return existing, False

    def required_output_kinds(self, run: dict[str, Any] | str) -> tuple[RepresentationKind, ...]:
        row = self.get_run(run) if isinstance(run, str) else run
        profile = require_document_processing_profile(
            row["profile_code"], profile_hash=row["profile_hash"]
        )
        kinds = decode_required_representation_kinds(row["required_output_kinds_json"])
        if tuple(kind.value for kind in kinds) != profile.output_kinds:
            self._deny("document_representation_set_invalid", "文档派生表示集合无效")
        return kinds

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.database.execute_one("select * from file_processing_run where id = ?", (run_id,))
        if row is None:
            raise NotFound(
                "Document processing run not found",
                safe_message="未找到文档处理任务",
            )
        return row

    def get_source_version_for_run(self, run_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select v.*, f.display_name, r.tenant_id, r.profile_code, r.profile_hash,
                   r.source_file_id, r.source_version_id
              from file_processing_run r
              join managed_file_version v
                on v.id = r.source_version_id and v.file_id = r.source_file_id
              join managed_file f on f.id = r.source_file_id
             where r.id = ?
            """,
            (run_id,),
        )
        if row is None:
            raise NotFound(
                "Document processing source not found",
                safe_message="未找到待处理文件版本",
            )
        return row

    def processing_context(self, run_id: str) -> dict[str, Any]:
        """Return safe attribution only; never project names, object keys or content."""
        run = self.get_run(run_id)
        attachment = self.database.execute_one(
            """
            select a.job_id, j.business_application_id,
                   j.business_application_code,
                   j.business_application_publication_id
              from message_attachment a
              join agent_job j on j.id = a.job_id
             where a.file_processing_run_id = ?
             order by a.updated_at desc, a.id desc
             limit 1
            """,
            (run_id,),
        )
        return {
            "job_id": str((attachment or {}).get("job_id") or ""),
            "business_application_id": str(
                (attachment or {}).get("business_application_id") or ""
            ),
            "business_application_code": str(
                (attachment or {}).get("business_application_code") or ""
            ),
            "business_application_publication_id": str(
                (attachment or {}).get("business_application_publication_id") or ""
            ),
            "tenant_id": str(run["tenant_id"]),
        }

    def claim_run(self, run_id: str) -> tuple[dict[str, Any], bool]:
        """Claim one message-addressed run without following arbitrary queue input."""
        timestamp = _now()
        changed = self.database.execute(
            """
            update file_processing_run
               set status = 'RUNNING', attempt = attempt + 1,
                   error_code = '', next_retry_at = null,
                   started_at = coalesce(started_at, ?), updated_at = ?
             where id = ?
               and (
                 status = 'QUEUED'
                 or (status = 'RETRY_WAIT' and next_retry_at <= ?)
               )
            returning *
            """,
            (timestamp, timestamp, run_id, timestamp),
        )
        if changed:
            return changed[0], True
        run = self.get_run(run_id)
        return run, False

    def mark_submitted(self, run_id: str, *, external_task_id: str) -> dict[str, Any]:
        if not external_task_id or len(external_task_id) > 256:
            self._deny("document_processor_task_id_invalid", "处理器任务身份无效")
        run = self.get_run(run_id)
        if str(run["status"]) == ProcessingRunStatus.SUBMITTED.value:
            if str(run["external_task_id"]) != external_task_id:
                self._deny("document_processor_task_id_conflict", "处理器任务身份冲突")
            return run
        return self.transition_run(
            run_id,
            target=ProcessingRunStatus.SUBMITTED,
            external_task_id=external_task_id,
        )

    def schedule_retry(
        self,
        run_id: str,
        *,
        error_code: str,
        next_retry_at: str,
        clear_external_task: bool = False,
    ) -> dict[str, Any]:
        return self.transition_run(
            run_id,
            target=ProcessingRunStatus.RETRY_WAIT,
            error_code=error_code,
            next_retry_at=next_retry_at,
            external_task_id="" if clear_external_task else None,
        )

    def claim_due_run(self, *, worker_id: str) -> dict[str, Any] | None:
        del worker_id
        timestamp = _now()
        if self.database.engine == "postgres":
            rows = self.database.execute(
                """
                with candidate as (
                  select id from file_processing_run
                   where status = 'QUEUED'
                      or (status = 'RETRY_WAIT' and next_retry_at <= ?)
                   order by created_at, id
                   for update skip locked limit 1
                )
                update file_processing_run
                   set status = 'RUNNING', attempt = attempt + 1,
                       external_task_id = '', error_code = '', next_retry_at = null,
                       started_at = coalesce(started_at, ?), updated_at = ?
                 where id = (select id from candidate)
                returning *
                """,
                (timestamp, timestamp, timestamp),
            )
        else:
            rows = self.database.execute(
                """
                update file_processing_run
                   set status = 'RUNNING', attempt = attempt + 1,
                       external_task_id = '', error_code = '', next_retry_at = null,
                       started_at = coalesce(started_at, ?), updated_at = ?
                 where id = (
                   select id from file_processing_run
                    where status = 'QUEUED'
                       or (status = 'RETRY_WAIT' and next_retry_at <= ?)
                    order by created_at, id limit 1
                 )
                   and status in ('QUEUED', 'RETRY_WAIT')
                returning *
                """,
                (timestamp, timestamp, timestamp),
            )
        return rows[0] if rows else None

    def transition_run(
        self,
        run_id: str,
        *,
        target: ProcessingRunStatus,
        external_task_id: str | None = None,
        error_code: str = "",
        next_retry_at: str | None = None,
        page_count: int | None = None,
        processing_time_ms: int | None = None,
    ) -> dict[str, Any]:
        run = self.get_run(run_id)
        current = ProcessingRunStatus(str(run["status"]))
        if current is target:
            return run
        require_processing_transition(current, target)
        terminal = target in PROCESSING_TERMINAL_STATUSES
        timestamp = _now()
        changed = self.database.execute(
            """
            update file_processing_run
               set status = ?, external_task_id = ?, error_code = ?,
                   next_retry_at = ?, page_count = coalesce(?, page_count),
                   processing_time_ms = coalesce(?, processing_time_ms),
                   completed_at = ?, updated_at = ?
             where id = ? and status = ?
            returning *
            """,
            (
                target.value,
                str(run["external_task_id"] if external_task_id is None else external_task_id),
                error_code[:128],
                next_retry_at,
                page_count,
                processing_time_ms,
                timestamp if terminal else None,
                timestamp,
                run_id,
                current.value,
            ),
        )
        if not changed:
            self._deny(
                "document_processing_state_conflict",
                "文档处理状态已变化，请刷新后重试",
            )
        return changed[0]

    def create_or_get_transfer(
        self,
        *,
        run_id: str,
        kind: RepresentationKind,
        token_hash: str,
        expected_size_bytes: int,
        expected_sha256: str,
        staging_object_key: str,
        expires_at: str,
    ) -> tuple[dict[str, Any], bool]:
        run = self.get_run(run_id)
        if str(run["status"]) not in {"RUNNING", "SUBMITTED"}:
            self._deny(
                "document_processing_state_conflict",
                "当前处理任务不能创建上传通道",
            )
        transfer_id = _id("representation_transfer")
        timestamp = _now()
        inserted = self.database.execute(
            """
            insert into file_representation_transfer
              (id, processing_run_id, kind, token_hash, expected_size_bytes,
               expected_sha256, staging_object_key, status, expires_at,
               created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
            on conflict(processing_run_id, kind) do nothing
            returning *
            """,
            (
                transfer_id,
                run_id,
                kind.value,
                token_hash,
                expected_size_bytes,
                expected_sha256,
                staging_object_key,
                expires_at,
                timestamp,
                timestamp,
            ),
        )
        if inserted:
            return inserted[0], True
        existing = self.database.execute_one(
            """
            select * from file_representation_transfer
             where processing_run_id = ? and kind = ?
            """,
            (run_id, kind.value),
        )
        if existing is None:
            raise RuntimeError("Representation transfer idempotency lookup failed")
        if (
            int(existing.get("expected_size_bytes") or -1) != expected_size_bytes
            or str(existing.get("expected_sha256") or "") != expected_sha256
        ):
            self._deny(
                "document_representation_transfer_conflict",
                "派生表示上传元数据冲突",
            )
        return existing, False

    def get_transfer(self, transfer_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from file_representation_transfer where id = ?", (transfer_id,)
        )
        if row is None:
            raise NotFound(
                "Representation transfer not found",
                safe_message="未找到派生表示上传通道",
            )
        return row

    def rotate_open_transfer(
        self,
        transfer_id: str,
        *,
        token_hash: str,
        staging_object_key: str,
        expires_at: str,
    ) -> dict[str, Any]:
        changed = self.database.execute(
            """
            update file_representation_transfer
               set token_hash = ?, staging_object_key = ?, expires_at = ?, updated_at = ?
             where id = ? and status = 'OPEN'
            returning *
            """,
            (token_hash, staging_object_key, expires_at, _now(), transfer_id),
        )
        if not changed:
            self._deny(
                "document_representation_transfer_conflict",
                "派生表示上传通道不能重新签发",
            )
        return changed[0]

    def mark_transfer_staged(
        self,
        transfer_id: str,
        *,
        received_size_bytes: int,
        received_sha256: str,
    ) -> dict[str, Any]:
        timestamp = _now()
        changed = self.database.execute(
            """
            update file_representation_transfer
               set status = 'STAGED', received_size_bytes = ?,
                   received_sha256 = ?, error_code = '', updated_at = ?
             where id = ? and status in ('OPEN', 'UPLOADING')
            returning *
            """,
            (received_size_bytes, received_sha256, timestamp, transfer_id),
        )
        if changed:
            return changed[0]
        existing = self.get_transfer(transfer_id)
        if (
            str(existing["status"]) in {"STAGED", "FINALIZED"}
            and int(existing["received_size_bytes"]) == received_size_bytes
            and str(existing["received_sha256"]) == received_sha256
        ):
            return existing
        self._deny("document_representation_transfer_conflict", "派生表示上传状态冲突")

    def finalize_representations(
        self,
        *,
        run_id: str,
        terminal_status: ProcessingRunStatus,
        outputs: dict[RepresentationKind, dict[str, Any]],
        page_count: int | None,
        processing_time_ms: int | None,
    ) -> list[dict[str, Any]]:
        if terminal_status not in {
            ProcessingRunStatus.SUCCEEDED,
            ProcessingRunStatus.PARTIAL,
        }:
            self._deny(
                "document_processing_terminal_invalid",
                "文档处理完成状态无效",
            )
        with self.database.unit_of_work():
            run = self.get_run(run_id)
            required_kinds = self.required_output_kinds(run)
            if set(outputs) != set(required_kinds):
                self._deny(
                    "document_representation_incomplete",
                    "文档派生表示尚未完整",
                )
            if str(run["status"]) in {"SUCCEEDED", "PARTIAL"}:
                return self.list_representations(run_id)
            current = ProcessingRunStatus(str(run["status"]))
            require_processing_transition(current, terminal_status)
            timestamp = _now()
            for kind in required_kinds:
                output = outputs[kind]
                transfer = self.get_transfer(str(output["transfer_id"]))
                if (
                    str(transfer["processing_run_id"]) != run_id
                    or str(transfer["kind"]) != kind.value
                    or str(transfer["status"]) != "STAGED"
                    or int(transfer["received_size_bytes"]) != int(output["size_bytes"])
                    or str(transfer["received_sha256"]) != str(output["content_sha256"])
                ):
                    self._deny(
                        "document_representation_transfer_conflict",
                        "派生表示上传状态冲突",
                    )
                self.database.execute(
                    """
                    insert into file_representation
                      (id, processing_run_id, tenant_id, source_file_id,
                       source_version_id, kind, media_type, encoding, status,
                       size_bytes, content_sha256, object_key, profile_hash,
                       created_at)
                    values (?, ?, ?, ?, ?, ?, ?, 'utf-8', 'AVAILABLE',
                            ?, ?, ?, ?, ?)
                    on conflict(processing_run_id, kind) do nothing
                    """,
                    (
                        str(output["representation_id"]),
                        run_id,
                        run["tenant_id"],
                        run["source_file_id"],
                        run["source_version_id"],
                        kind.value,
                        str(output["media_type"]),
                        int(output["size_bytes"]),
                        str(output["content_sha256"]),
                        str(output["object_key"]),
                        run["profile_hash"],
                        timestamp,
                    ),
                )
                self.database.execute(
                    """
                    update file_representation_transfer
                       set status = 'FINALIZED', finalized_at = ?, updated_at = ?
                     where id = ? and status = 'STAGED'
                    """,
                    (timestamp, timestamp, transfer["id"]),
                )
            changed = self.database.execute(
                """
                update file_processing_run
                   set status = ?, page_count = ?, processing_time_ms = ?,
                       completed_at = ?, updated_at = ?
                 where id = ? and status = ?
                returning id
                """,
                (
                    terminal_status.value,
                    page_count,
                    processing_time_ms,
                    timestamp,
                    timestamp,
                    run_id,
                    current.value,
                ),
            )
            if not changed:
                self._deny(
                    "document_processing_state_conflict",
                    "文档处理状态已变化，请刷新后重试",
                )
        return self.list_representations(run_id)

    def list_representations(self, run_id: str) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select * from file_representation
             where processing_run_id = ? order by kind
            """,
            (run_id,),
        )

    def expire_open_transfers(self, *, now: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            update file_representation_transfer
               set status = 'EXPIRED', error_code = 'transfer_expired', updated_at = ?
             where id in (
               select id from file_representation_transfer
                where status in ('OPEN', 'UPLOADING', 'STAGED') and expires_at <= ?
                order by expires_at, id limit ?
             )
            returning *
            """,
            (now, now, max(1, min(int(limit), 1000))),
        )

    def processing_summary(self) -> dict[str, Any]:
        rows = self.database.execute(
            """
            select tenant_id, profile_code, status, count(*) as count
              from file_processing_run
             group by tenant_id, profile_code, status
             order by tenant_id, profile_code, status
            """
        )
        stage_rows = self.database.execute(
            """
            select profile_code, stage_code, status, count(*) as count,
                   min(created_at) as earliest_created_at, max(attempt) as max_attempt
              from file_processing_run
             where status not in ('SUCCEEDED', 'PARTIAL', 'NO_TEXT', 'FAILED')
             group by profile_code, stage_code, status
             order by profile_code, stage_code, status
            """
        )
        picture_rows = self.database.execute(
            """
            select r.profile_code, i.status, i.error_code, count(*) as count,
                   min(i.created_at) as earliest_created_at, max(i.attempt) as max_attempt
              from document_picture_processing_item i
              join file_processing_run r on r.id = i.processing_run_id
             group by r.profile_code, i.status, i.error_code
             order by r.profile_code, i.status, i.error_code
            """
        )
        outbox_rows = self.database.execute(
            """
            select r.profile_code, o.event_type, o.status, o.error_code,
                   count(*) as count, min(o.next_attempt_at) as earliest_next_attempt_at,
                   max(o.attempt) as max_attempt
              from document_processing_stage_outbox o
              join file_processing_run r on r.id = o.processing_run_id
             group by r.profile_code, o.event_type, o.status, o.error_code
             order by r.profile_code, o.event_type, o.status, o.error_code
            """
        )
        staging_rows = self.database.execute(
            """
            select 'PARENT_ARTIFACT' as resource_type,
                   r.profile_code as profile_code, t.status as status,
                   count(*) as count, min(t.created_at) as earliest_created_at
              from document_parent_artifact_transfer t
              join file_processing_run r on r.id = t.processing_run_id
             group by r.profile_code, t.status
            union all
            select 'PICTURE_ASSET', r.profile_code, t.status,
                   count(*), min(t.created_at)
              from document_picture_asset_transfer t
              join file_processing_run r on r.id = t.processing_run_id
             group by r.profile_code, t.status
            union all
            select 'PICTURE_RESULT', r.profile_code, t.status,
                   count(*), min(t.created_at)
              from document_picture_result_transfer t
              join file_processing_run r on r.id = t.processing_run_id
             group by r.profile_code, t.status
            union all
            select 'REPRESENTATION', r.profile_code, t.status,
                   count(*), min(t.created_at)
              from file_representation_transfer t
              join file_processing_run r on r.id = t.processing_run_id
             group by r.profile_code, t.status
             order by resource_type, profile_code, status
            """
        )
        cleanup_rows = self.database.execute(
            """
            select r.profile_code, c.object_kind, c.status, c.error_code,
                   count(*) as count, min(c.next_attempt_at) as earliest_next_attempt_at,
                   max(c.attempt) as max_attempt
              from document_picture_cleanup_fact c
              join file_processing_run r on r.id = c.processing_run_id
             group by r.profile_code, c.object_kind, c.status, c.error_code
             order by r.profile_code, c.object_kind, c.status, c.error_code
            """
        )
        return {
            "groups": [
                {
                    "tenant_id": str(row["tenant_id"]),
                    "profile_code": str(row["profile_code"]),
                    "status": str(row["status"]),
                    "count": int(row["count"]),
                }
                for row in rows
            ],
            "stage_backlog": [
                {
                    "profile_code": str(row["profile_code"]),
                    "stage_code": str(row["stage_code"]),
                    "status": str(row["status"]),
                    "count": int(row["count"]),
                    "earliest_created_at": str(row["earliest_created_at"]),
                    "max_attempt": int(row["max_attempt"]),
                }
                for row in stage_rows
            ],
            "picture_items": [
                {
                    "profile_code": str(row["profile_code"]),
                    "status": str(row["status"]),
                    "error_code": _safe_metric_error_code(row["error_code"]),
                    "count": int(row["count"]),
                    "earliest_created_at": str(row["earliest_created_at"]),
                    "max_attempt": int(row["max_attempt"]),
                }
                for row in picture_rows
            ],
            "stage_outbox": [
                {
                    "profile_code": str(row["profile_code"]),
                    "event_type": str(row["event_type"]),
                    "status": str(row["status"]),
                    "error_code": _safe_metric_error_code(row["error_code"]),
                    "count": int(row["count"]),
                    "earliest_next_attempt_at": str(row["earliest_next_attempt_at"]),
                    "max_attempt": int(row["max_attempt"]),
                }
                for row in outbox_rows
            ],
            "staging": [
                {
                    "resource_type": str(row["resource_type"]),
                    "profile_code": str(row["profile_code"]),
                    "status": str(row["status"]),
                    "count": int(row["count"]),
                    "earliest_created_at": str(row["earliest_created_at"]),
                }
                for row in staging_rows
            ],
            "cleanup": [
                {
                    "profile_code": str(row["profile_code"]),
                    "resource_type": str(row["object_kind"]),
                    "status": str(row["status"]),
                    "error_code": _safe_metric_error_code(row["error_code"]),
                    "count": int(row["count"]),
                    "earliest_next_attempt_at": str(row["earliest_next_attempt_at"]),
                    "max_attempt": int(row["max_attempt"]),
                }
                for row in cleanup_rows
            ],
        }

    def create_or_get_picture_asset(
        self,
        *,
        run_id: str,
        normalized_sha256: str,
        media_type: str,
        original_width_pixels: int,
        original_height_pixels: int,
        width_pixels: int,
        height_pixels: int,
        normalization_transform_json: str,
        size_bytes: int,
        object_key: str,
    ) -> tuple[dict[str, Any], bool]:
        run = self.get_run(run_id)
        profile = require_document_processing_profile(
            run["profile_code"], profile_hash=run["profile_hash"]
        )
        if profile.layout_ocr_options is None:
            self._deny("document_picture_profile_invalid", "当前Profile不处理内嵌图片")
        if media_type not in {"image/png", "image/jpeg", "image/webp"}:
            self._deny("document_picture_media_type_invalid", "内嵌图片媒体类型无效")
        if len(normalized_sha256) != 64:
            self._deny("document_picture_digest_invalid", "内嵌图片摘要无效")
        picture_id = _id("document_picture_asset")
        timestamp = _now()
        inserted = self.database.execute(
            """
            insert into document_picture_asset
              (id, processing_run_id, tenant_id, source_file_id, source_version_id,
               profile_code, profile_hash, normalized_sha256, media_type,
               original_width_pixels, original_height_pixels, width_pixels,
               height_pixels, normalization_transform_json, size_bytes,
               object_key, status,
               created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'STAGING', ?, ?)
            on conflict(processing_run_id, normalized_sha256) do nothing
            returning *
            """,
            (
                picture_id,
                run_id,
                run["tenant_id"],
                run["source_file_id"],
                run["source_version_id"],
                run["profile_code"],
                run["profile_hash"],
                normalized_sha256,
                media_type,
                original_width_pixels,
                original_height_pixels,
                width_pixels,
                height_pixels,
                normalization_transform_json,
                size_bytes,
                object_key,
                timestamp,
                timestamp,
            ),
        )
        if inserted:
            return inserted[0], True
        existing = self.database.execute_one(
            """
            select * from document_picture_asset
             where processing_run_id = ? and normalized_sha256 = ?
            """,
            (run_id, normalized_sha256),
        )
        if existing is None:
            raise RuntimeError("Picture asset idempotency lookup failed")
        expected = {
            "tenant_id": str(run["tenant_id"]),
            "source_file_id": str(run["source_file_id"]),
            "source_version_id": str(run["source_version_id"]),
            "profile_code": str(run["profile_code"]),
            "profile_hash": str(run["profile_hash"]),
            "media_type": media_type,
            "original_width_pixels": original_width_pixels,
            "original_height_pixels": original_height_pixels,
            "width_pixels": width_pixels,
            "height_pixels": height_pixels,
            "normalization_transform_json": normalization_transform_json,
            "size_bytes": size_bytes,
        }
        if any(str(existing[key]) != str(value) for key, value in expected.items()):
            self._deny("document_picture_asset_conflict", "内嵌图片资产身份冲突")
        return existing, False

    def get_picture_asset(self, picture_asset_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from document_picture_asset where id = ?", (picture_asset_id,)
        )
        if row is None:
            raise NotFound("Picture asset not found", safe_message="未找到内嵌图片资产")
        return row

    def create_or_get_picture_asset_transfer(
        self,
        *,
        picture_asset_id: str,
        token_hash: str,
        staging_object_key: str,
        expires_at: str,
    ) -> tuple[dict[str, Any], bool]:
        asset = self.get_picture_asset(picture_asset_id)
        transfer_id = _id("picture_asset_transfer")
        timestamp = _now()
        inserted = self.database.execute(
            """
            insert into document_picture_asset_transfer
              (id, picture_asset_id, processing_run_id, token_hash,
               expected_media_type, expected_width_pixels, expected_height_pixels,
               expected_size_bytes, expected_sha256, staging_object_key, status,
               expires_at, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
            on conflict(picture_asset_id) do nothing returning *
            """,
            (
                transfer_id,
                picture_asset_id,
                asset["processing_run_id"],
                token_hash,
                asset["media_type"],
                asset["width_pixels"],
                asset["height_pixels"],
                asset["size_bytes"],
                asset["normalized_sha256"],
                staging_object_key,
                expires_at,
                timestamp,
                timestamp,
            ),
        )
        if inserted:
            return inserted[0], True
        existing = self.database.execute_one(
            "select * from document_picture_asset_transfer where picture_asset_id = ?",
            (picture_asset_id,),
        )
        if existing is None:
            raise RuntimeError("Picture asset transfer idempotency lookup failed")
        return existing, False

    def get_picture_asset_transfer(self, transfer_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from document_picture_asset_transfer where id = ?", (transfer_id,)
        )
        if row is None:
            raise NotFound(
                "Picture asset transfer not found",
                safe_message="未找到内嵌图片上传通道",
            )
        return row

    def finalize_picture_asset_transfer(
        self,
        *,
        transfer_id: str,
        received_size_bytes: int,
        received_sha256: str,
    ) -> dict[str, Any]:
        with self.database.unit_of_work():
            transfer = self.get_picture_asset_transfer(transfer_id)
            if (
                int(transfer["expected_size_bytes"]) != received_size_bytes
                or str(transfer["expected_sha256"]) != received_sha256
            ):
                self._deny("document_picture_digest_mismatch", "内嵌图片大小或摘要不一致")
            timestamp = _now()
            changed = self.database.execute(
                """
                update document_picture_asset_transfer
                   set status = 'FINALIZED', received_size_bytes = ?,
                       received_sha256 = ?, error_code = '', finalized_at = ?, updated_at = ?
                 where id = ? and status in ('OPEN', 'UPLOADING', 'STAGED')
                returning *
                """,
                (
                    received_size_bytes,
                    received_sha256,
                    timestamp,
                    timestamp,
                    transfer_id,
                ),
            )
            if not changed and str(transfer["status"]) != "FINALIZED":
                self._deny("document_picture_transfer_conflict", "内嵌图片上传状态冲突")
            self.database.execute(
                """
                update document_picture_asset
                   set status = 'AVAILABLE', updated_at = ?
                 where id = ? and status in ('STAGING', 'AVAILABLE')
                """,
                (timestamp, transfer["picture_asset_id"]),
            )
        return self.get_picture_asset(str(transfer["picture_asset_id"]))

    def create_or_get_picture_occurrence(
        self,
        *,
        run_id: str,
        picture_asset_id: str,
        occurrence_index: int,
        source_format: str,
        picture_ref: str,
        parent_ref: str,
        parent_label: str,
        parent_ordinal: int,
        slide_no: int | None,
        parent_bbox_json: str,
        selection_status: str = "SELECTED",
    ) -> tuple[dict[str, Any], bool]:
        asset = self.get_picture_asset(picture_asset_id)
        if str(asset["processing_run_id"]) != run_id:
            self._deny("document_picture_run_mismatch", "内嵌图片不属于当前处理任务")
        occurrence_id = _id("document_picture_occurrence")
        inserted = self.database.execute(
            """
            insert into document_picture_occurrence
              (id, processing_run_id, picture_asset_id, occurrence_index,
               source_format, picture_ref, parent_ref, parent_label,
               parent_ordinal, slide_no, parent_bbox_json, selection_status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(processing_run_id, picture_ref) do nothing returning *
            """,
            (
                occurrence_id,
                run_id,
                picture_asset_id,
                occurrence_index,
                source_format,
                picture_ref,
                parent_ref,
                parent_label[:128],
                parent_ordinal,
                slide_no,
                parent_bbox_json,
                selection_status,
                _now(),
            ),
        )
        if inserted:
            return inserted[0], True
        existing = self.database.execute_one(
            """
            select * from document_picture_occurrence
             where processing_run_id = ? and picture_ref = ?
            """,
            (run_id, picture_ref),
        )
        if existing is None:
            raise RuntimeError("Picture occurrence idempotency lookup failed")
        if (
            str(existing["picture_asset_id"]) != picture_asset_id
            or int(existing["occurrence_index"]) != occurrence_index
            or str(existing["selection_status"]) != selection_status
        ):
            self._deny("document_picture_occurrence_conflict", "内嵌图片位置身份冲突")
        return existing, False

    def create_or_get_picture_item(
        self,
        *,
        run_id: str,
        picture_asset_id: str,
        occurrence_count: int,
        ocr_engine_code: str,
        model_revision: str,
        model_digest: str,
        correlation_id: str,
    ) -> tuple[dict[str, Any], bool]:
        asset = self.get_picture_asset(picture_asset_id)
        if str(asset["processing_run_id"]) != run_id:
            self._deny("document_picture_run_mismatch", "内嵌图片不属于当前处理任务")
        item_id = _id("document_picture_item")
        timestamp = _now()
        inserted = self.database.execute(
            """
            insert into document_picture_processing_item
              (id, processing_run_id, picture_asset_id, status, occurrence_count,
               attempt, ocr_engine_code, model_revision, model_digest,
               created_at, updated_at)
            values (?, ?, ?, 'QUEUED', ?, 0, ?, ?, ?, ?, ?)
            on conflict(processing_run_id, picture_asset_id) do nothing returning *
            """,
            (
                item_id,
                run_id,
                picture_asset_id,
                occurrence_count,
                ocr_engine_code,
                model_revision,
                model_digest,
                timestamp,
                timestamp,
            ),
        )
        item = inserted[0] if inserted else self.database.execute_one(
            """
            select * from document_picture_processing_item
             where processing_run_id = ? and picture_asset_id = ?
            """,
            (run_id, picture_asset_id),
        )
        if item is None:
            raise RuntimeError("Picture item idempotency lookup failed")
        if not inserted and (
            int(item["occurrence_count"]) != occurrence_count
            or str(item["ocr_engine_code"]) != ocr_engine_code
            or str(item["model_revision"]) != model_revision
            or str(item["model_digest"]) != model_digest
        ):
            self._deny("document_picture_item_conflict", "内嵌图片处理身份冲突")
        run = self.get_run(run_id)
        payload = self.safe_stage_message_payload(
            contract_version="file-picture-processing/v1",
            run_id=run_id,
            picture_item_id=str(item["id"]),
            profile_hash=str(run["profile_hash"]),
            attempt=int(item["attempt"]),
            correlation_id=correlation_id,
        )
        self.create_stage_outbox(
            event_key=f"picture-ocr:{item['id']}",
            run_id=run_id,
            picture_item_id=str(item["id"]),
            event_type="PICTURE_OCR_REQUESTED",
            payload=payload,
        )
        return item, bool(inserted)

    def get_picture_item(self, picture_item_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from document_picture_processing_item where id = ?",
            (picture_item_id,),
        )
        if row is None:
            raise NotFound("Picture item not found", safe_message="未找到内嵌图片处理任务")
        return row

    def claim_picture_item(
        self,
        *,
        picture_item_id: str,
        claim_token: str,
        claim_expires_at: str,
    ) -> tuple[dict[str, Any], bool]:
        timestamp = _now()
        changed = self.database.execute(
            """
            update document_picture_processing_item
               set status = 'CLAIMED', attempt = attempt + 1, claim_token = ?,
                   claimed_at = ?, claim_expires_at = ?, next_retry_at = null,
                   error_code = '', updated_at = ?
             where id = ? and (
               status = 'QUEUED'
               or (status = 'RETRY_WAIT' and next_retry_at <= ?)
             )
            returning *
            """,
            (
                claim_token[:128],
                timestamp,
                claim_expires_at,
                timestamp,
                picture_item_id,
                timestamp,
            ),
        )
        if changed:
            item = changed[0]
            self.database.execute(
                """
                insert into document_picture_processing_attempt
                  (id, picture_item_id, attempt_no, status, started_at)
                values (?, ?, ?, 'CLAIMED', ?)
                on conflict(picture_item_id, attempt_no) do nothing
                """,
                (_id("document_picture_attempt"), picture_item_id, item["attempt"], timestamp),
            )
            return item, True
        return self.get_picture_item(picture_item_id), False

    def mark_picture_item_submitted(
        self,
        *,
        picture_item_id: str,
        external_task_id: str,
    ) -> dict[str, Any]:
        item = self.get_picture_item(picture_item_id)
        if str(item["status"]) == "SUBMITTED":
            if str(item["external_task_id"]) != external_task_id:
                self._deny("document_picture_task_conflict", "内嵌图片外部任务冲突")
            return item
        changed = self.database.execute(
            """
            update document_picture_processing_item
               set status = 'SUBMITTED', external_task_id = ?, updated_at = ?
             where id = ? and status = 'CLAIMED' returning *
            """,
            (external_task_id[:256], _now(), picture_item_id),
        )
        if not changed:
            self._deny("document_picture_state_conflict", "内嵌图片处理状态已变化")
        return changed[0]

    def schedule_picture_item_retry(
        self,
        *,
        picture_item_id: str,
        error_code: str,
        next_retry_at: str,
        clear_external_task: bool,
    ) -> dict[str, Any]:
        item = self.get_picture_item(picture_item_id)
        changed = self.database.execute(
            """
            update document_picture_processing_item
               set status = 'RETRY_WAIT', next_retry_at = ?, error_code = ?,
                   external_task_id = ?, claim_token = '', claimed_at = null,
                   claim_expires_at = null, updated_at = ?
             where id = ? and status in ('CLAIMED', 'SUBMITTED') returning *
            """,
            (
                next_retry_at,
                error_code[:128],
                "" if clear_external_task else str(item["external_task_id"]),
                _now(),
                picture_item_id,
            ),
        )
        if not changed:
            self._deny("document_picture_state_conflict", "内嵌图片处理状态已变化")
        self.database.execute(
            """
            update document_picture_processing_attempt
               set status = 'RETRYABLE_FAILED', external_task_id = ?,
                   error_code = ?, completed_at = ?
             where picture_item_id = ? and attempt_no = ?
            """,
            (
                str(item["external_task_id"]),
                error_code[:128],
                _now(),
                picture_item_id,
                item["attempt"],
            ),
        )
        return changed[0]

    def complete_picture_item(
        self,
        *,
        picture_item_id: str,
        status: PictureItemStatus,
        result_size_bytes: int | None = None,
        result_sha256: str = "",
        error_code: str = "",
        correlation_id: str,
    ) -> dict[str, Any]:
        if status not in PICTURE_ITEM_TERMINAL_STATUSES:
            self._deny("document_picture_terminal_invalid", "内嵌图片完成状态无效")
        with self.database.unit_of_work():
            item = self.get_picture_item(picture_item_id)
            if PictureItemStatus(str(item["status"])) in PICTURE_ITEM_TERMINAL_STATUSES:
                if str(item["status"]) != status.value:
                    self._deny("document_picture_state_conflict", "内嵌图片处理状态已变化")
                return item
            timestamp = _now()
            changed = self.database.execute(
                """
                update document_picture_processing_item
                   set status = ?, result_size_bytes = ?, result_sha256 = ?,
                       error_code = ?, claim_token = '', claim_expires_at = null,
                       completed_at = ?, updated_at = ?
                 where id = ? and status in ('CLAIMED', 'SUBMITTED', 'QUEUED')
                returning *
                """,
                (
                    status.value,
                    result_size_bytes,
                    result_sha256,
                    error_code[:128],
                    timestamp,
                    timestamp,
                    picture_item_id,
                ),
            )
            if not changed:
                self._deny("document_picture_state_conflict", "内嵌图片处理状态已变化")
            item = changed[0]
            self.database.execute(
                """
                update document_picture_processing_attempt
                   set status = ?, external_task_id = ?, error_code = ?, completed_at = ?
                 where picture_item_id = ? and attempt_no = ?
                """,
                (
                    "SUCCEEDED" if status in {PictureItemStatus.AVAILABLE, PictureItemStatus.NO_TEXT} else "FAILED",
                    str(item["external_task_id"]),
                    error_code[:128],
                    timestamp,
                    picture_item_id,
                    item["attempt"],
                ),
            )
            remaining = self.database.execute_one(
                """
                select count(*) as count from document_picture_processing_item
                 where processing_run_id = ? and status not in (
                   'AVAILABLE', 'NO_TEXT', 'SKIPPED_LIMIT', 'FAILED'
                 )
                """,
                (item["processing_run_id"],),
            )
            run = self.get_run(str(item["processing_run_id"]))
            if (
                str(run["stage_code"]) != "PARENT_PARSE"
                and int((remaining or {}).get("count") or 0) == 0
            ):
                payload = self.safe_stage_message_payload(
                    contract_version="file-processing-assembly/v1",
                    run_id=str(run["id"]),
                    picture_item_id=None,
                    profile_hash=str(run["profile_hash"]),
                    attempt=int(run["assembly_attempt"]),
                    correlation_id=correlation_id,
                )
                self.create_stage_outbox(
                    event_key=f"assembly:{run['id']}",
                    run_id=str(run["id"]),
                    picture_item_id=None,
                    event_type="ASSEMBLY_REQUESTED",
                    payload=payload,
                )
        return item

    def create_stage_outbox(
        self,
        *,
        event_key: str,
        run_id: str,
        picture_item_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.validate_safe_stage_message_payload(payload)
        outbox_id = _id("document_processing_outbox")
        timestamp = _now()
        inserted = self.database.execute(
            """
            insert into document_processing_stage_outbox
              (id, event_key, processing_run_id, picture_item_id, item_key,
               event_type, payload_json, status, next_attempt_at, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
            on conflict(event_key) do nothing returning *
            """,
            (
                outbox_id,
                event_key,
                run_id,
                picture_item_id,
                picture_item_id or "",
                event_type,
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        row = inserted[0] if inserted else self.database.execute_one(
            "select * from document_processing_stage_outbox where event_key = ?",
            (event_key,),
        )
        if row is None:
            raise RuntimeError("Document stage outbox idempotency lookup failed")
        return row

    def claim_assembly(
        self,
        *,
        run_id: str,
        claim_token: str,
    ) -> tuple[dict[str, Any], bool]:
        timestamp = _now()
        changed = self.database.execute(
            """
            update file_processing_run
               set stage_code = 'ASSEMBLING', assembly_status = 'CLAIMED',
                   assembly_attempt = assembly_attempt + 1,
                   assembly_claim_token = ?, assembly_claimed_at = ?, updated_at = ?
             where id = ? and assembly_status = 'PENDING'
               and not exists (
                 select 1 from document_picture_processing_item i
                  where i.processing_run_id = file_processing_run.id
                    and i.status not in ('AVAILABLE', 'NO_TEXT', 'SKIPPED_LIMIT', 'FAILED')
               )
            returning *
            """,
            (claim_token[:128], timestamp, timestamp, run_id),
        )
        if changed:
            return changed[0], True
        return self.get_run(run_id), False

    def complete_parent_parse(self, *, run_id: str, correlation_id: str) -> dict[str, Any]:
        with self.database.unit_of_work():
            run = self.get_run(run_id)
            require_document_processing_profile(
                run["profile_code"], profile_hash=run["profile_hash"]
            )
            parent = self.parent_artifact_for_run(run_id)
            docling = self.database.execute_one(
                """
                select * from file_representation_transfer
                 where processing_run_id = ? and kind = 'DOCLING_JSON'
                """,
                (run_id,),
            )
            if (
                str(parent["status"]) != "FINALIZED"
                or docling is None
                or str(docling["status"]) not in {"STAGED", "FINALIZED"}
            ):
                self._deny("document_parent_artifact_incomplete", "父文档解析结果尚未完整")
            counts = self.database.execute_one(
                """
                select count(*) as total,
                       sum(case when status not in (
                         'AVAILABLE', 'NO_TEXT', 'SKIPPED_LIMIT', 'FAILED'
                       ) then 1 else 0 end) as remaining
                  from document_picture_processing_item
                 where processing_run_id = ?
                """,
                (run_id,),
            ) or {"total": 0, "remaining": 0}
            remaining = int(counts.get("remaining") or 0)
            target_stage = "PICTURE_OCR" if remaining else "ASSEMBLING"
            self.database.execute(
                """
                update file_processing_run set stage_code = ?, updated_at = ?
                 where id = ? and status in ('RUNNING', 'SUBMITTED')
                """,
                (target_stage, _now(), run_id),
            )
            if remaining == 0:
                payload = self.safe_stage_message_payload(
                    contract_version="file-processing-assembly/v1",
                    run_id=run_id,
                    picture_item_id=None,
                    profile_hash=str(run["profile_hash"]),
                    attempt=int(run["assembly_attempt"]),
                    correlation_id=correlation_id,
                )
                self.create_stage_outbox(
                    event_key=f"assembly:{run_id}",
                    run_id=run_id,
                    picture_item_id=None,
                    event_type="ASSEMBLY_REQUESTED",
                    payload=payload,
                )
        return self.get_run(run_id)

    def finish_assembly(self, *, run_id: str, succeeded: bool) -> dict[str, Any]:
        changed = self.database.execute(
            """
            update file_processing_run
               set assembly_status = ?, assembly_claim_token = '',
                   assembly_claimed_at = null, updated_at = ?
             where id = ? and assembly_status = 'CLAIMED' returning *
            """,
            ("COMPLETED" if succeeded else "FAILED", _now(), run_id),
        )
        if not changed:
            run = self.get_run(run_id)
            expected = "COMPLETED" if succeeded else "FAILED"
            if str(run["assembly_status"]) == expected:
                return run
            self._deny("document_assembly_state_conflict", "文档组装状态已变化")
        return changed[0]

    def retry_assembly(self, *, run_id: str) -> dict[str, Any]:
        changed = self.database.execute(
            """
            update file_processing_run
               set assembly_status = 'PENDING', assembly_claim_token = '',
                   assembly_claimed_at = null, updated_at = ?
             where id = ? and assembly_status = 'CLAIMED' returning *
            """,
            (_now(), run_id),
        )
        if not changed:
            self._deny("document_assembly_state_conflict", "文档组装状态已变化")
        return changed[0]

    def create_or_get_picture_result_transfer(
        self,
        *,
        picture_item_id: str,
        token_hash: str,
        expected_size_bytes: int,
        expected_sha256: str,
        staging_object_key: str,
        expires_at: str,
    ) -> tuple[dict[str, Any], bool]:
        item = self.get_picture_item(picture_item_id)
        if str(item["status"]) not in {"CLAIMED", "SUBMITTED"}:
            self._deny("document_picture_state_conflict", "当前图片任务不能上传OCR结果")
        transfer_id = _id("picture_result_transfer")
        timestamp = _now()
        inserted = self.database.execute(
            """
            insert into document_picture_result_transfer
              (id, picture_item_id, processing_run_id, token_hash,
               expected_size_bytes, expected_sha256, staging_object_key,
               status, expires_at, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
            on conflict(picture_item_id) do nothing returning *
            """,
            (
                transfer_id,
                picture_item_id,
                item["processing_run_id"],
                token_hash,
                expected_size_bytes,
                expected_sha256,
                staging_object_key,
                expires_at,
                timestamp,
                timestamp,
            ),
        )
        if inserted:
            return inserted[0], True
        existing = self.database.execute_one(
            "select * from document_picture_result_transfer where picture_item_id = ?",
            (picture_item_id,),
        )
        if existing is None:
            raise RuntimeError("Picture result transfer idempotency lookup failed")
        if (
            int(existing["expected_size_bytes"]) != expected_size_bytes
            or str(existing["expected_sha256"]) != expected_sha256
        ):
            self._deny("document_picture_result_conflict", "内嵌图片OCR结果身份冲突")
        return existing, False

    def create_or_get_parent_artifact_transfer(
        self,
        *,
        run_id: str,
        token_hash: str,
        expected_size_bytes: int,
        expected_sha256: str,
        staging_object_key: str,
        expires_at: str,
    ) -> tuple[dict[str, Any], bool]:
        run = self.get_run(run_id)
        profile = require_document_processing_profile(
            run["profile_code"], profile_hash=run["profile_hash"]
        )
        if profile.layout_ocr_options is None:
            self._deny("document_parent_artifact_profile_invalid", "当前Profile不暂存父Markdown")
        transfer_id = _id("parent_artifact_transfer")
        timestamp = _now()
        inserted = self.database.execute(
            """
            insert into document_parent_artifact_transfer
              (id, processing_run_id, kind, token_hash, expected_size_bytes,
               expected_sha256, staging_object_key, status, expires_at,
               created_at, updated_at)
            values (?, ?, 'PARENT_MARKDOWN', ?, ?, ?, ?, 'OPEN', ?, ?, ?)
            on conflict(processing_run_id, kind) do nothing returning *
            """,
            (
                transfer_id,
                run_id,
                token_hash,
                expected_size_bytes,
                expected_sha256,
                staging_object_key,
                expires_at,
                timestamp,
                timestamp,
            ),
        )
        if inserted:
            return inserted[0], True
        existing = self.database.execute_one(
            """
            select * from document_parent_artifact_transfer
             where processing_run_id = ? and kind = 'PARENT_MARKDOWN'
            """,
            (run_id,),
        )
        if existing is None:
            raise RuntimeError("Parent artifact transfer idempotency lookup failed")
        if (
            int(existing["expected_size_bytes"]) != expected_size_bytes
            or str(existing["expected_sha256"]) != expected_sha256
        ):
            self._deny("document_parent_artifact_conflict", "父Markdown暂存身份冲突")
        return existing, False

    def get_parent_artifact_transfer(self, transfer_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from document_parent_artifact_transfer where id = ?", (transfer_id,)
        )
        if row is None:
            raise NotFound(
                "Parent artifact transfer not found",
                safe_message="未找到父Markdown暂存通道",
            )
        return row

    def parent_artifact_for_run(self, run_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select * from document_parent_artifact_transfer
             where processing_run_id = ? and kind = 'PARENT_MARKDOWN'
            """,
            (run_id,),
        )
        if row is None:
            raise NotFound("Parent artifact not found", safe_message="未找到父Markdown暂存内容")
        return row

    def finalize_parent_artifact_transfer(
        self,
        *,
        transfer_id: str,
        received_size_bytes: int,
        received_sha256: str,
    ) -> dict[str, Any]:
        transfer = self.get_parent_artifact_transfer(transfer_id)
        if (
            int(transfer["expected_size_bytes"]) != received_size_bytes
            or str(transfer["expected_sha256"]) != received_sha256
        ):
            self._deny("document_parent_artifact_digest_mismatch", "父Markdown大小或摘要不一致")
        timestamp = _now()
        changed = self.database.execute(
            """
            update document_parent_artifact_transfer
               set status = 'FINALIZED', received_size_bytes = ?, received_sha256 = ?,
                   error_code = '', finalized_at = ?, updated_at = ?
             where id = ? and status in ('OPEN', 'UPLOADING') returning *
            """,
            (received_size_bytes, received_sha256, timestamp, timestamp, transfer_id),
        )
        if changed:
            return changed[0]
        if str(transfer["status"]) == "FINALIZED":
            return transfer
        self._deny("document_parent_artifact_conflict", "父Markdown暂存状态冲突")

    def get_picture_result_transfer(self, transfer_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from document_picture_result_transfer where id = ?", (transfer_id,)
        )
        if row is None:
            raise NotFound(
                "Picture result transfer not found",
                safe_message="未找到内嵌图片OCR结果上传通道",
            )
        return row

    def finalize_picture_result_transfer(
        self,
        *,
        transfer_id: str,
        received_size_bytes: int,
        received_sha256: str,
    ) -> dict[str, Any]:
        transfer = self.get_picture_result_transfer(transfer_id)
        if (
            int(transfer["expected_size_bytes"]) != received_size_bytes
            or str(transfer["expected_sha256"]) != received_sha256
        ):
            self._deny("document_picture_result_digest_mismatch", "图片OCR结果大小或摘要不一致")
        timestamp = _now()
        changed = self.database.execute(
            """
            update document_picture_result_transfer
               set status = 'FINALIZED', received_size_bytes = ?, received_sha256 = ?,
                   error_code = '', finalized_at = ?, updated_at = ?
             where id = ? and status in ('OPEN', 'UPLOADING', 'STAGED') returning *
            """,
            (received_size_bytes, received_sha256, timestamp, timestamp, transfer_id),
        )
        if changed:
            return changed[0]
        if str(transfer["status"]) == "FINALIZED":
            return transfer
        self._deny("document_picture_result_conflict", "图片OCR结果上传状态冲突")

    def claim_stage_outbox(
        self,
        *,
        claim_token: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        timestamp = _now()
        bounded = max(1, min(int(limit), 1000))
        if self.database.engine == "postgres":
            return self.database.execute(
                """
                with candidates as (
                  select id from document_processing_stage_outbox
                   where status = 'PENDING' and next_attempt_at <= ?
                   order by created_at, id for update skip locked limit ?
                )
                update document_processing_stage_outbox
                   set status = 'CLAIMED', claim_token = ?, claimed_at = ?,
                       attempt = attempt + 1, updated_at = ?
                 where id in (select id from candidates) returning *
                """,
                (timestamp, bounded, claim_token[:128], timestamp, timestamp),
            )
        return self.database.execute(
            """
            update document_processing_stage_outbox
               set status = 'CLAIMED', claim_token = ?, claimed_at = ?,
                   attempt = attempt + 1, updated_at = ?
             where id in (
               select id from document_processing_stage_outbox
                where status = 'PENDING' and next_attempt_at <= ?
                order by created_at, id limit ?
             ) and status = 'PENDING' returning *
            """,
            (claim_token[:128], timestamp, timestamp, timestamp, bounded),
        )

    def mark_stage_outbox_published(self, *, outbox_id: str, claim_token: str) -> dict[str, Any]:
        timestamp = _now()
        changed = self.database.execute(
            """
            update document_processing_stage_outbox
               set status = 'PUBLISHED', published_at = ?, updated_at = ?,
                   claim_token = '', claimed_at = null, error_code = ''
             where id = ? and status = 'CLAIMED' and claim_token = ? returning *
            """,
            (timestamp, timestamp, outbox_id, claim_token[:128]),
        )
        if not changed:
            self._deny("document_stage_outbox_conflict", "文档阶段消息状态已变化")
        return changed[0]

    def mark_stage_outbox_failed(
        self,
        *,
        outbox_id: str,
        claim_token: str,
        error_code: str,
        retry_at: str,
        max_attempts: int = 8,
    ) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from document_processing_stage_outbox where id = ?", (outbox_id,)
        )
        if row is None:
            raise NotFound("Stage outbox not found", safe_message="未找到文档阶段消息")
        target = "DEAD" if int(row["attempt"]) >= max_attempts else "PENDING"
        changed = self.database.execute(
            """
            update document_processing_stage_outbox
               set status = ?, next_attempt_at = ?, error_code = ?,
                   claim_token = '', claimed_at = null, updated_at = ?
             where id = ? and status = 'CLAIMED' and claim_token = ? returning *
            """,
            (target, retry_at, error_code[:128], _now(), outbox_id, claim_token[:128]),
        )
        if not changed:
            self._deny("document_stage_outbox_conflict", "文档阶段消息状态已变化")
        return changed[0]

    def enqueue_picture_cleanup(
        self,
        *,
        run_id: str,
        object_kind: str,
        object_id: str,
        internal_object_key: str,
        reason_code: str,
        due_at: str,
    ) -> dict[str, Any]:
        cleanup_id = _id("document_picture_cleanup")
        timestamp = _now()
        inserted = self.database.execute(
            """
            insert into document_picture_cleanup_fact
              (id, processing_run_id, object_kind, object_id, internal_object_key,
               reason_code, status, next_attempt_at, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
            on conflict(object_kind, object_id) do nothing returning *
            """,
            (
                cleanup_id,
                run_id,
                object_kind,
                object_id,
                internal_object_key,
                reason_code[:128],
                due_at,
                timestamp,
                timestamp,
            ),
        )
        row = inserted[0] if inserted else self.database.execute_one(
            """
            select * from document_picture_cleanup_fact
             where object_kind = ? and object_id = ?
            """,
            (object_kind, object_id),
        )
        if row is None:
            raise RuntimeError("Picture cleanup idempotency lookup failed")
        return row

    def enqueue_terminal_picture_cleanup(
        self,
        *,
        run_id: str,
        due_at: str,
    ) -> list[dict[str, Any]]:
        """Freeze cleanup facts only after the complete layout output set is visible."""
        run = self.get_run(run_id)
        profile = require_document_processing_profile(
            run["profile_code"],
            profile_hash=run["profile_hash"],
        )
        if profile.layout_ocr_options is None:
            return []
        required = {kind.value for kind in self.required_output_kinds(run)}
        available = {
            str(row["kind"])
            for row in self.database.execute(
                """
                select kind from file_representation
                 where processing_run_id = ? and status = 'AVAILABLE'
                """,
                (run_id,),
            )
        }
        if required != available or str(run["status"]) not in {"SUCCEEDED", "PARTIAL"}:
            self._deny(
                "document_picture_cleanup_not_ready",
                "文档图片处理内容尚未满足清理条件",
            )
        nonterminal = self.database.execute_one(
            """
            select 1 as pending from document_picture_processing_item
             where processing_run_id = ?
               and status not in ('AVAILABLE', 'NO_TEXT', 'SKIPPED_LIMIT', 'FAILED')
             limit 1
            """,
            (run_id,),
        )
        if nonterminal is not None:
            self._deny(
                "document_picture_cleanup_not_ready",
                "文档图片处理内容尚未满足清理条件",
            )
        timestamp = _now()
        self.database.execute(
            """
            update document_parent_artifact_transfer
               set status = 'FINALIZED', finalized_at = ?, updated_at = ?
             where processing_run_id = ? and status = 'STAGED'
            """,
            (timestamp, timestamp, run_id),
        )
        self.database.execute(
            """
            update document_picture_result_transfer
               set status = 'FINALIZED', finalized_at = ?, updated_at = ?
             where processing_run_id = ? and status = 'STAGED'
            """,
            (timestamp, timestamp, run_id),
        )
        objects = self.database.execute(
            """
            select 'PARENT_ARTIFACT' as object_kind, id as object_id,
                   staging_object_key as internal_object_key
              from document_parent_artifact_transfer
             where processing_run_id = ? and status = 'FINALIZED'
            union all
            select 'PICTURE_ASSET' as object_kind, id as object_id,
                   object_key as internal_object_key
              from document_picture_asset
             where processing_run_id = ? and status = 'AVAILABLE'
            union all
            select 'PICTURE_RESULT' as object_kind, id as object_id,
                   staging_object_key as internal_object_key
              from document_picture_result_transfer
             where processing_run_id = ? and status = 'FINALIZED'
            """,
            (run_id, run_id, run_id),
        )
        return [
            self.enqueue_picture_cleanup(
                run_id=run_id,
                object_kind=str(row["object_kind"]),
                object_id=str(row["object_id"]),
                internal_object_key=str(row["internal_object_key"]),
                reason_code="PARENT_TERMINAL",
                due_at=due_at,
            )
            for row in objects
        ]

    def claim_picture_cleanup(self, *, limit: int = 100) -> list[dict[str, Any]]:
        timestamp = _now()
        return self.database.execute(
            """
            update document_picture_cleanup_fact
               set status = 'RUNNING', attempt = attempt + 1, updated_at = ?
             where id in (
               select id from document_picture_cleanup_fact
                where status in ('PENDING', 'RETRY_WAIT') and next_attempt_at <= ?
                order by next_attempt_at, id limit ?
             ) and status in ('PENDING', 'RETRY_WAIT') returning *
            """,
            (timestamp, timestamp, max(1, min(int(limit), 1000))),
        )

    def complete_picture_cleanup(self, *, cleanup_id: str) -> dict[str, Any]:
        timestamp = _now()
        with self.database.unit_of_work():
            row = self.database.execute_one(
                "select * from document_picture_cleanup_fact where id = ?", (cleanup_id,)
            )
            if row is None:
                raise NotFound("Picture cleanup not found", safe_message="未找到图片清理任务")
            if str(row["object_kind"]) == "PICTURE_ASSET":
                self.database.execute(
                    """
                    update document_picture_asset
                       set status = 'CONTENT_UNAVAILABLE', content_deleted_at = ?,
                           cleanup_error_code = '', updated_at = ?
                     where id = ? and status <> 'DELETED'
                    """,
                    (timestamp, timestamp, row["object_id"]),
                )
            elif str(row["object_kind"]) == "PARENT_ARTIFACT":
                self.database.execute(
                    """
                    update document_parent_artifact_transfer
                       set status = 'EXPIRED', error_code = 'content_cleaned',
                           content_deleted_at = ?, updated_at = ?
                     where id = ? and status in ('OPEN', 'UPLOADING', 'STAGED', 'FINALIZED')
                    """,
                    (timestamp, timestamp, row["object_id"]),
                )
            elif str(row["object_kind"]) == "PICTURE_RESULT":
                self.database.execute(
                    """
                    update document_picture_result_transfer
                       set status = 'EXPIRED', error_code = 'content_cleaned', updated_at = ?
                     where id = ? and status in ('OPEN', 'UPLOADING', 'STAGED', 'FINALIZED')
                    """,
                    (timestamp, row["object_id"]),
                )
            changed = self.database.execute(
                """
                update document_picture_cleanup_fact
                   set status = 'SUCCEEDED', error_code = '', completed_at = ?, updated_at = ?
                 where id = ? and status = 'RUNNING' returning *
                """,
                (timestamp, timestamp, cleanup_id),
            )
        if not changed:
            self._deny("document_picture_cleanup_conflict", "图片清理状态已变化")
        return changed[0]

    def retry_picture_cleanup(
        self,
        *,
        cleanup_id: str,
        error_code: str,
        next_attempt_at: str,
        max_attempts: int = 8,
    ) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from document_picture_cleanup_fact where id = ?", (cleanup_id,)
        )
        if row is None:
            raise NotFound("Picture cleanup not found", safe_message="未找到图片清理任务")
        target = "DEAD" if int(row["attempt"]) >= max_attempts else "RETRY_WAIT"
        changed = self.database.execute(
            """
            update document_picture_cleanup_fact
               set status = ?, next_attempt_at = ?, error_code = ?, updated_at = ?
             where id = ? and status = 'RUNNING' returning *
            """,
            (target, next_attempt_at, error_code[:128], _now(), cleanup_id),
        )
        if not changed:
            self._deny("document_picture_cleanup_conflict", "图片清理状态已变化")
        if str(row["object_kind"]) == "PICTURE_ASSET":
            self.database.execute(
                """
                update document_picture_asset
                   set cleanup_error_code = ?, updated_at = ?
                 where id = ? and status = 'AVAILABLE'
                """,
                (error_code[:128], _now(), row["object_id"]),
            )
        return changed[0]

    @staticmethod
    def safe_stage_message_payload(
        *,
        contract_version: str,
        run_id: str,
        picture_item_id: str | None,
        profile_hash: str,
        attempt: int,
        correlation_id: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contract_version": contract_version,
            "run_id": run_id,
            "profile_hash": profile_hash,
            "attempt": attempt,
            "correlation_id": correlation_id[:128],
        }
        if picture_item_id is not None:
            payload["picture_item_id"] = picture_item_id
        return payload

    @staticmethod
    def validate_safe_stage_message_payload(payload: dict[str, Any]) -> dict[str, Any]:
        contract = str(payload.get("contract_version") or "")
        expected = {
            "file-picture-processing/v1": {
                "contract_version",
                "run_id",
                "picture_item_id",
                "profile_hash",
                "attempt",
                "correlation_id",
            },
            "file-processing-assembly/v1": {
                "contract_version",
                "run_id",
                "profile_hash",
                "attempt",
                "correlation_id",
            },
        }
        if contract not in expected or set(payload) != expected[contract]:
            raise ValueError("Unsafe document processing stage message")
        encoded = json.dumps(payload, ensure_ascii=False).lower()
        forbidden = (
            "base64",
            "object_key",
            "bucket",
            "filename",
            "file_name",
            "ocr_text",
            "coordinates",
            "bbox",
            "token",
            "url",
        )
        if any(marker in encoded for marker in forbidden):
            raise ValueError("Unsafe document processing stage message")
        if len(str(payload["profile_hash"])) != 64 or int(payload["attempt"]) < 0:
            raise ValueError("Invalid document processing stage message")
        return dict(payload)

    def reconcile_attachment_readability(self, *, limit: int = 100) -> dict[str, Any]:
        """Project terminal processing runs onto attachment readiness.

        Eligible waiting Jobs are returned on every scan until their status changes,
        so a worker crash between projection and release cannot lose the wake-up.
        """
        bounded_limit = max(1, min(int(limit), 1000))
        candidates = self.database.execute(
            """
            select a.id, a.job_id, r.status, r.error_code
              from message_attachment a
              join file_processing_run r on r.id = a.file_processing_run_id
             where a.readability_status = 'PENDING'
               and r.status in ('SUCCEEDED', 'PARTIAL', 'NO_TEXT', 'FAILED')
             order by a.updated_at, a.id limit ?
            """,
            (bounded_limit,),
        )
        mapping = {
            "SUCCEEDED": "AVAILABLE",
            "PARTIAL": "PARTIAL",
            "NO_TEXT": "NO_TEXT",
            "FAILED": "UNAVAILABLE",
        }
        timestamp = _now()
        reconciled = 0
        with self.database.unit_of_work():
            for row in candidates:
                readability = mapping[str(row["status"])]
                error_code = (
                    str(row.get("error_code") or "") if readability == "UNAVAILABLE" else ""
                )
                changed = self.database.execute(
                    """
                    update message_attachment
                       set readability_status = ?, readability_error_code = ?,
                           readability_updated_at = ?, updated_at = ?
                     where id = ? and readability_status = 'PENDING'
                    """,
                    (readability, error_code[:128], timestamp, timestamp, str(row["id"])),
                )
                if changed:
                    reconciled += 1
        release_rows = self.database.execute(
            """
            select distinct a.job_id
              from message_attachment a
              join agent_job j on j.id = a.job_id
             where j.status = 'WAITING_INPUT'
               and not exists (
                 select 1 from message_attachment pending
                  where pending.job_id = a.job_id
                    and pending.status not in (
                      'READY', 'REJECTED', 'FAILED', 'stored_not_interpreted'
                    )
               )
             order by a.job_id limit ?
            """,
            (bounded_limit,),
        )
        return {
            "reconciled": reconciled,
            "release_job_ids": [str(row["job_id"]) for row in release_rows if row.get("job_id")],
        }

    @staticmethod
    def safe_message_payload(
        *,
        run_id: str,
        source_version_id: str,
        profile_hash: str,
        attempt: int,
        correlation_id: str,
    ) -> dict[str, Any]:
        return {
            "contract_version": "file-processing/v1",
            "run_id": run_id,
            "source_version_id": source_version_id,
            "profile_hash": profile_hash,
            "attempt": attempt,
            "correlation_id": correlation_id[:128],
        }

    @staticmethod
    def validate_safe_message_payload(payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "contract_version",
            "run_id",
            "source_version_id",
            "profile_hash",
            "attempt",
            "correlation_id",
        }
        if set(payload) != allowed or payload.get("contract_version") != "file-processing/v1":
            raise ValueError("Unsafe document processing message")
        encoded = json.dumps(payload, ensure_ascii=False)
        if any(marker in encoded.lower() for marker in ("base64", "object_key", "token", "url")):
            raise ValueError("Unsafe document processing message")
        if len(str(payload["profile_hash"])) != 64 or int(payload["attempt"]) < 0:
            raise ValueError("Invalid document processing message")
        return dict(payload)

    @staticmethod
    def _deny(code: str, safe_message: str) -> None:
        raise NonRetryableExecutionError(
            "Document processing request denied",
            safe_message=safe_message,
            error_code=code,
        )
