from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.modules.document_processing.domain import (
    PROCESSING_TERMINAL_STATUSES,
    ProcessingRunStatus,
    RepresentationKind,
    require_processing_transition,
)
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound, PermissionDenied


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


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
        profile_hash: str,
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
        run_id = _id("file_processing_run")
        timestamp = _now()
        inserted = self.database.execute(
            """
            insert into file_processing_run
              (id, tenant_id, source_file_id, source_version_id, processor_code,
               processor_version, processor_build_digest, profile_code, profile_hash,
               status, source_size_bytes, created_by, created_at, updated_at)
            values (?, ?, ?, ?, 'docling-serve', ?, ?, 'docling-text-v1', ?,
                    'QUEUED', ?, ?, ?, ?)
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
                profile_hash,
                int(source["size_bytes"]),
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
        ):
            self._deny("document_processing_identity_conflict", "文档处理身份冲突")
        return existing, False

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
        if set(outputs) != {RepresentationKind.MARKDOWN, RepresentationKind.DOCLING_JSON}:
            self._deny(
                "document_representation_incomplete",
                "文档派生表示尚未完整",
            )
        with self.database.unit_of_work():
            run = self.get_run(run_id)
            if str(run["status"]) in {"SUCCEEDED", "PARTIAL"}:
                return self.list_representations(run_id)
            current = ProcessingRunStatus(str(run["status"]))
            require_processing_transition(current, terminal_status)
            timestamp = _now()
            for kind in (RepresentationKind.MARKDOWN, RepresentationKind.DOCLING_JSON):
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
        return {
            "groups": [
                {
                    "tenant_id": str(row["tenant_id"]),
                    "profile_code": str(row["profile_code"]),
                    "status": str(row["status"]),
                    "count": int(row["count"]),
                }
                for row in rows
            ]
        }

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
                    self.database.execute(
                        "delete from attachment_content where attachment_id = ?",
                        (str(row["id"]),),
                    )
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
