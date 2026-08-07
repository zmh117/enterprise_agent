from __future__ import annotations

import json
from typing import Any

from app.modules.internal_tools.application.legacy_migration import (
    MIGRATION_VERSION,
    BuiltinToolLegacyMigrationService,
)
from app.modules.job.application.builtin_tool_snapshot import (
    JobBuiltinToolSnapshotService,
)
from app.modules.platform_config.infrastructure.repository import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError


class BuiltinToolLegacyJobMigrator:
    """Materialize uniquely proven Job snapshots and quarantine every ambiguity."""

    def __init__(
        self,
        database: Database,
        *,
        snapshot_service: JobBuiltinToolSnapshotService,
    ) -> None:
        self.database = database
        self.snapshot_service = snapshot_service
        self.reporter = BuiltinToolLegacyMigrationService(database)

    def migrate(
        self,
        *,
        actor_id: str,
        correlation_id: str,
        source_limit: int = 500,
    ) -> dict[str, Any]:
        if not actor_id.strip():
            raise ValueError("actor_id is required")
        if not correlation_id.strip():
            raise ValueError("correlation_id is required")
        if source_limit < 1 or source_limit > 5_000:
            raise ValueError("source_limit must be between 1 and 5000")
        report = self.reporter.report(detail_limit=5_000)
        job_items = [
            item for item in report["details"] if item["source_type"] == "JOB"
        ]
        selected = job_items[:source_limit]
        materialized: list[dict[str, str]] = []
        quarantined: list[dict[str, str]] = []

        for item in selected:
            if item["candidate_class"] != "ONE":
                quarantined.append(
                    self._quarantine(
                        item,
                        actor_id=actor_id,
                        correlation_id=correlation_id,
                        reason_code=str(item.get("reason_code") or "")
                        or "builtin_tool_legacy_resolution_missing",
                    )
                )
                continue
            try:
                materialized.append(
                    self._materialize(
                        item,
                        correlation_id=correlation_id,
                    )
                )
            except NonRetryableExecutionError as exc:
                quarantined.append(
                    self._quarantine(
                        item,
                        actor_id=actor_id,
                        correlation_id=correlation_id,
                        reason_code=exc.error_code
                        or "builtin_tool_legacy_job_migration_failed",
                    )
                )
            except Exception:
                quarantined.append(
                    self._quarantine(
                        item,
                        actor_id=actor_id,
                        correlation_id=correlation_id,
                        reason_code="builtin_tool_legacy_job_migration_failed",
                    )
                )

        return {
            "schema_version": 1,
            "migration_version": MIGRATION_VERSION,
            "mode": "job_snapshot_migration",
            "materialized": materialized,
            "quarantined": quarantined,
            "materialized_count": len(materialized),
            "quarantined_count": len(quarantined),
            "source_count": len(job_items),
            "source_limit": source_limit,
            "sources_truncated": len(job_items) > source_limit,
            "safe_fields_only": True,
        }

    def _materialize(
        self,
        item: dict[str, Any],
        *,
        correlation_id: str,
    ) -> dict[str, str]:
        job_id = str(item["source_id"])
        release_ids = sorted(
            str(release_id)
            for candidate in item.get("tool_candidates") or []
            for release_id in candidate.get("tool_release_ids") or []
        )
        with self.database.unit_of_work():
            frozen = self.snapshot_service.freeze_legacy_migration(
                job_id=job_id,
                tool_release_ids=release_ids,
                migration_version=MIGRATION_VERSION,
            )
            timestamp = now_iso()
            evidence = {
                "snapshot_id": str(frozen["id"]),
                "application_publication_id": str(
                    frozen["snapshot"]["application_publication"]["id"]
                ),
                "agent_publication_id": str(
                    frozen["snapshot"]["agent_publication_id"]
                ),
                "tool_release_ids": release_ids,
            }
            self.database.execute(
                """
                insert into builtin_tool_legacy_migration
                  (id, source_type, source_id, migration_version,
                   candidate_class, candidate_count, status,
                   quarantine_reason_code, snapshot_hash,
                   evidence_summary_json, correlation_id, created_at, updated_at)
                values (?, 'JOB', ?, ?, 'ONE', 1, 'MATERIALIZED', '',
                        ?, ?, ?, ?, ?)
                on conflict(source_type, source_id, migration_version) do nothing
                """,
                (
                    new_id("builtin_tool_legacy_migration"),
                    job_id,
                    MIGRATION_VERSION,
                    str(frozen["snapshot_hash"]),
                    json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                    correlation_id,
                    timestamp,
                    timestamp,
                ),
            )
            ledger = self._ledger(job_id)
            if (
                ledger is None
                or str(ledger["status"]) != "MATERIALIZED"
                or str(ledger.get("snapshot_hash") or "")
                != str(frozen["snapshot_hash"])
            ):
                raise NonRetryableExecutionError(
                    "Legacy Job migration ledger conflict",
                    safe_message="旧 Job 迁移账本与精确快照不一致",
                    error_code="builtin_tool_legacy_migration_conflict",
                )
        return {
            "job_id": job_id,
            "snapshot_id": str(frozen["id"]),
            "snapshot_hash": str(frozen["snapshot_hash"]),
        }

    def _quarantine(
        self,
        item: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str,
        reason_code: str,
    ) -> dict[str, str]:
        job_id = str(item["source_id"])
        candidate_class = str(item.get("candidate_class") or "ZERO")
        candidate_count = int(item.get("candidate_count") or 0)
        safe_reason = reason_code[:200] or "builtin_tool_legacy_resolution_missing"
        timestamp = now_iso()
        with self.database.unit_of_work():
            self.database.execute(
                """
                insert into builtin_tool_legacy_migration
                  (id, source_type, source_id, migration_version,
                   candidate_class, candidate_count, status,
                   quarantine_reason_code, snapshot_hash,
                   evidence_summary_json, correlation_id, created_at, updated_at)
                values (?, 'JOB', ?, ?, ?, ?, 'QUARANTINED', ?, null,
                        ?, ?, ?, ?)
                on conflict(source_type, source_id, migration_version) do nothing
                """,
                (
                    new_id("builtin_tool_legacy_migration"),
                    job_id,
                    MIGRATION_VERSION,
                    candidate_class,
                    candidate_count,
                    safe_reason,
                    json.dumps(
                        {
                            "recovery_kinds": sorted(
                                str(value)
                                for value in item.get("recovery_kinds") or []
                            ),
                            "operator": actor_id[:200],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    correlation_id,
                    timestamp,
                    timestamp,
                ),
            )
            ledger = self._ledger(job_id)
            if (
                ledger is None
                or str(ledger["status"]) != "QUARANTINED"
                or str(ledger["quarantine_reason_code"]) != safe_reason
            ):
                raise NonRetryableExecutionError(
                    "Legacy Job quarantine ledger conflict",
                    safe_message="旧 Job 隔离账本冲突，请停止并检查",
                    error_code="builtin_tool_legacy_migration_conflict",
                )
            self.database.execute(
                """
                update agent_job
                   set status = 'FAILED', retry_count = max_retry_count,
                       error_message = 'Legacy Built-in Tool facts were quarantined',
                       last_error_code = ?, last_error_at = ?,
                       next_retry_at = null, finished_at = coalesce(finished_at, ?),
                       locked_at = null, locked_by = null
                 where id = ?
                   and not exists (
                     select 1 from agent_job_builtin_tool_snapshot snapshot
                      where snapshot.job_id = agent_job.id
                   )
                """,
                (safe_reason, timestamp, timestamp, job_id),
            )
            self.database.execute(
                """
                update job_dispatch_outbox
                   set status = 'DEAD', attempt_count = max_attempts,
                       replay_count = max_replay_count,
                       claimed_by = '', claimed_at = null,
                       dead_at = coalesce(dead_at, ?),
                       last_error_code = ?,
                       last_error_summary =
                         'Legacy Built-in Tool facts were quarantined',
                       updated_at = ?
                 where job_id = ?
                """,
                (timestamp, safe_reason, timestamp, job_id),
            )
        return {"job_id": job_id, "reason_code": safe_reason}

    def _ledger(self, job_id: str) -> dict[str, Any] | None:
        return self.database.execute_one(
            """
            select * from builtin_tool_legacy_migration
             where source_type = 'JOB' and source_id = ?
               and migration_version = ?
            """,
            (job_id, MIGRATION_VERSION),
        )
