from __future__ import annotations

from typing import Any

from app.modules.api_capability.domain.contracts import content_hash
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


class GovernedApiExecutionRepository:
    """Persist only non-secret execution facts for governed external APIs."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def freeze_external_subject(
        self,
        *,
        job_id: str,
        external_identity_id: str,
        external_user_id: str,
        default_team_id: str,
        binding_revision: int,
    ) -> dict[str, Any]:
        snapshot_hash = content_hash(
            {
                "schema_version": 1,
                "provider": "ones",
                "external_identity_id": external_identity_id,
                "external_user_id": external_user_id,
                "default_team_id": default_team_id,
                "binding_revision": binding_revision,
            }
        )
        existing = self.database.execute_one(
            "select * from agent_job_external_subject where job_id = ?",
            (job_id,),
        )
        if existing:
            if str(existing["snapshot_hash"]) != snapshot_hash:
                raise NonRetryableExecutionError(
                    "Job external subject snapshot is immutable",
                    safe_message="Job 外部主体快照已冻结，不能修改",
                    error_code="job_subject_snapshot_immutable",
                )
            return existing
        self.database.execute(
            """
            insert into agent_job_external_subject
              (id, job_id, provider, external_identity_id, external_user_id,
               default_team_id, binding_revision, snapshot_hash, created_at)
            values (?, ?, 'ones', ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("agent_job_external_subject"),
                job_id,
                external_identity_id,
                external_user_id,
                default_team_id,
                binding_revision,
                snapshot_hash,
                now_iso(),
            ),
        )
        return self.get_external_subject(job_id)

    def get_external_subject(self, job_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from agent_job_external_subject where job_id = ?",
            (job_id,),
        )
        if row is None:
            raise NotFound(
                "Job external subject snapshot not found",
                safe_message="当前 Job 缺少外部主体快照",
            )
        return {**row, "binding_revision": int(row["binding_revision"])}

    def record_attempt(
        self,
        *,
        tool_call_id: str,
        job_id: str,
        capability_release_id: str,
        correlation_id: str,
        attempt_no: int,
        status_class: str,
        http_status: int | None,
        duration_ms: int,
        response_size: int,
        request_hash: str = "",
        response_hash: str = "",
        safe_error_code: str = "",
    ) -> dict[str, Any]:
        attempt_id = new_id("agent_tool_call_http_attempt")
        self.database.execute(
            """
            insert into agent_tool_call_http_attempt
              (id, tool_call_id, job_id, capability_release_id,
               correlation_id, attempt_no, status_class, http_status,
               duration_ms, response_size, request_hash, response_hash,
               safe_error_code, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                tool_call_id,
                job_id,
                capability_release_id,
                correlation_id,
                attempt_no,
                status_class,
                http_status,
                max(0, duration_ms),
                max(0, response_size),
                request_hash,
                response_hash,
                safe_error_code,
                now_iso(),
            ),
        )
        return (
            self.database.execute_one(
                "select * from agent_tool_call_http_attempt where id = ?",
                (attempt_id,),
            )
            or {}
        )

    def record_provenance(
        self,
        *,
        tool_call_id: str,
        user_id: str,
        application_publication_id: str,
        agent_publication_id: str,
        capability_release_id: str,
        normalized_result: bytes,
    ) -> dict[str, Any]:
        provenance_id = new_id("agent_tool_call_api_provenance")
        self.database.execute(
            """
            insert into agent_tool_call_api_provenance
              (id, tool_call_id, user_id, application_publication_id,
               agent_publication_id, capability_release_id,
               data_classification, normalized_result_hash,
               normalized_result_size, created_at)
            values (?, ?, ?, ?, ?, ?, 'INTERNAL', ?, ?, ?)
            """,
            (
                provenance_id,
                tool_call_id,
                user_id,
                application_publication_id,
                agent_publication_id,
                capability_release_id,
                content_hash_bytes(normalized_result),
                len(normalized_result),
                now_iso(),
            ),
        )
        return (
            self.database.execute_one(
                "select * from agent_tool_call_api_provenance where id = ?",
                (provenance_id,),
            )
            or {}
        )


def content_hash_bytes(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()
