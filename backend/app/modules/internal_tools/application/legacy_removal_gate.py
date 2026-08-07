from __future__ import annotations

from typing import Any

from app.modules.business_application.domain.policies import snapshot_hash
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


class BuiltinToolLegacyRemovalGate:
    REQUIRED_CONSECUTIVE_ZERO_REPORTS = 2

    def __init__(
        self,
        database: Database,
        *,
        snapshot_service: JobBuiltinToolSnapshotService,
    ) -> None:
        self.database = database
        self.snapshot_service = snapshot_service
        self.reporter = BuiltinToolLegacyMigrationService(database)

    def observe(
        self,
        *,
        actor_id: str,
        correlation_id: str,
        job_id: str = "",
        tool_call_id: str = "",
        delivery_attempt_id: str = "",
    ) -> dict[str, Any]:
        if not actor_id.strip():
            raise ValueError("actor_id is required")
        if not correlation_id.strip():
            raise ValueError("correlation_id is required")
        evidence_ids = (job_id, tool_call_id, delivery_attempt_id)
        if any(evidence_ids) and not all(evidence_ids):
            raise ValueError(
                "job_id, tool_call_id and delivery_attempt_id must be supplied together"
            )
        report = self.reporter.report(detail_limit=0)
        counts = report["counts"]
        observation_facts = {
            "migration_version": MIGRATION_VERSION,
            "new_legacy_writes_observed": int(
                counts["new_legacy_writes_observed"]
            ),
            "active_agent_references": int(
                counts["active_agent_publications_with_legacy"]
            ),
            "active_application_references": int(
                counts["active_application_publications_with_legacy"]
            ),
            "recoverable_job_references": int(
                counts["recoverable_jobs_without_exact_snapshot"]
            ),
        }
        zero_references = all(
            value == 0
            for key, value in observation_facts.items()
            if key != "migration_version"
        )
        report_hash = snapshot_hash(observation_facts)
        timestamp = now_iso()
        with self.database.unit_of_work():
            observation_id = self._record_observation(
                facts=observation_facts,
                report_hash=report_hash,
                zero_references=zero_references,
                actor_id=actor_id,
                correlation_id=correlation_id,
                timestamp=timestamp,
            )
            acceptance_id = ""
            if all(evidence_ids):
                acceptance_id = self._record_acceptance(
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                    job_id=job_id,
                    tool_call_id=tool_call_id,
                    delivery_attempt_id=delivery_attempt_id,
                    timestamp=timestamp,
                )
            if not acceptance_id:
                acceptance = self.database.execute_one(
                    """
                    select id
                      from builtin_tool_legacy_removal_acceptance
                     where migration_version = ?
                     order by verified_at desc, id desc
                     limit 1
                    """,
                    (MIGRATION_VERSION,),
                )
                acceptance_id = str((acceptance or {}).get("id") or "")
            consecutive_zero_count = self._consecutive_zero_count()
            blockers: list[str] = []
            if not zero_references:
                blockers.append("active_legacy_references")
            if (
                consecutive_zero_count
                < self.REQUIRED_CONSECUTIVE_ZERO_REPORTS
            ):
                blockers.append("consecutive_zero_reports")
            if not acceptance_id:
                blockers.append("runtime_tool_delivery_acceptance")
            decision = "READY" if not blockers else "BLOCKED"
            reason_code = (
                "" if decision == "READY" else "builtin_tool_legacy_removal_gate_failed"
            )
            gate_id = self._record_gate(
                observation_id=observation_id,
                acceptance_id=acceptance_id,
                consecutive_zero_count=consecutive_zero_count,
                decision=decision,
                reason_code=reason_code,
                actor_id=actor_id,
                correlation_id=correlation_id,
                timestamp=timestamp,
            )
        return {
            "schema_version": 1,
            "migration_version": MIGRATION_VERSION,
            "gate_id": gate_id,
            "decision": decision,
            "reason_code": reason_code,
            "blocking_dimensions": blockers,
            "consecutive_zero_count": consecutive_zero_count,
            "required_zero_count": self.REQUIRED_CONSECUTIVE_ZERO_REPORTS,
            "observation_id": observation_id,
            "report_hash": report_hash,
            "zero_references": zero_references,
            "acceptance_id": acceptance_id,
            "counts": {
                key: value
                for key, value in observation_facts.items()
                if key != "migration_version"
            },
            "safe_fields_only": True,
        }

    def require_ready(self) -> dict[str, Any]:
        gate = self.database.execute_one(
            """
            select * from builtin_tool_legacy_removal_gate
             where migration_version = ?
             order by evaluated_at desc, id desc
             limit 1
            """,
            (MIGRATION_VERSION,),
        )
        if gate is None or str(gate["decision"]) != "READY":
            raise NonRetryableExecutionError(
                "Built-in Tool legacy removal gate is not ready",
                safe_message="legacy-v1 移除门禁尚未满足",
                error_code="builtin_tool_legacy_removal_gate_failed",
            )
        return {
            "gate_id": str(gate["id"]),
            "decision": "READY",
            "consecutive_zero_count": int(gate["consecutive_zero_count"]),
            "required_zero_count": int(gate["required_zero_count"]),
            "acceptance_id": str(gate.get("acceptance_id") or ""),
        }

    def _record_observation(
        self,
        *,
        facts: dict[str, Any],
        report_hash: str,
        zero_references: bool,
        actor_id: str,
        correlation_id: str,
        timestamp: str,
    ) -> str:
        observation_id = new_id("builtin_tool_removal_observation")
        self.database.execute(
            """
            insert into builtin_tool_legacy_removal_observation
              (id, migration_version, report_hash,
               new_legacy_writes_observed, active_agent_references,
               active_application_references, recoverable_job_references,
               zero_references, correlation_id, observed_by, observed_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(migration_version, correlation_id) do nothing
            """,
            (
                observation_id,
                MIGRATION_VERSION,
                report_hash,
                facts["new_legacy_writes_observed"],
                facts["active_agent_references"],
                facts["active_application_references"],
                facts["recoverable_job_references"],
                int(zero_references),
                correlation_id,
                actor_id[:200],
                timestamp,
            ),
        )
        row = self.database.execute_one(
            """
            select id, report_hash
              from builtin_tool_legacy_removal_observation
             where migration_version = ? and correlation_id = ?
            """,
            (MIGRATION_VERSION, correlation_id),
        )
        if row is None or str(row["report_hash"]) != report_hash:
            raise NonRetryableExecutionError(
                "Removal observation idempotency conflict",
                safe_message="移除门禁观察记录与本次报告不一致",
                error_code="builtin_tool_legacy_removal_gate_failed",
            )
        return str(row["id"])

    def _record_acceptance(
        self,
        *,
        actor_id: str,
        correlation_id: str,
        job_id: str,
        tool_call_id: str,
        delivery_attempt_id: str,
        timestamp: str,
    ) -> str:
        frozen = self.snapshot_service.verify(job_id)
        if not frozen:
            raise NonRetryableExecutionError(
                "Removal acceptance Job has no exact Built-in Tool Snapshot",
                safe_message="验收 Job 缺少精确内置工具快照",
                error_code="builtin_tool_legacy_removal_gate_failed",
            )
        row = self.database.execute_one(
            """
            select job.status as job_status,
                   tool_call.status as tool_call_status,
                   fact.snapshot_id as fact_snapshot_id,
                   fact.authorization_decision,
                   fact.tool_release_id,
                   fact.resource_revision_id,
                   delivery.status as delivery_status
              from agent_job job
              join agent_tool_call tool_call
                on tool_call.job_id = job.id and tool_call.id = ?
              join agent_tool_call_builtin_tool_fact fact
                on fact.tool_call_id = tool_call.id
              join delivery_attempt delivery
                on delivery.job_id = job.id and delivery.id = ?
             where job.id = ?
            """,
            (tool_call_id, delivery_attempt_id, job_id),
        )
        if (
            row is None
            or str(row["job_status"]) != "SUCCEEDED"
            or str(row["tool_call_status"]) != "SUCCEEDED"
            or str(row["authorization_decision"]) != "ALLOWED"
            or str(row["delivery_status"]) != "SUCCEEDED"
            or str(row["fact_snapshot_id"]) != str(frozen["id"])
        ):
            raise NonRetryableExecutionError(
                "Removal acceptance chain is incomplete or unsuccessful",
                safe_message="真实运行、工具调用或投递验收证据不完整",
                error_code="builtin_tool_legacy_removal_gate_failed",
            )
        acceptance_facts = {
            "migration_version": MIGRATION_VERSION,
            "job_id": job_id,
            "snapshot_id": str(frozen["id"]),
            "snapshot_hash": str(frozen["snapshot_hash"]),
            "tool_call_id": tool_call_id,
            "tool_release_id": str(row["tool_release_id"]),
            "resource_revision_id": str(row.get("resource_revision_id") or ""),
            "delivery_attempt_id": delivery_attempt_id,
        }
        acceptance_hash = snapshot_hash(acceptance_facts)
        acceptance_id = new_id("builtin_tool_removal_acceptance")
        self.database.execute(
            """
            insert into builtin_tool_legacy_removal_acceptance
              (id, migration_version, job_id, snapshot_id, tool_call_id,
               delivery_attempt_id, acceptance_hash, correlation_id,
               verified_by, verified_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(migration_version, job_id, tool_call_id,
                        delivery_attempt_id) do nothing
            """,
            (
                acceptance_id,
                MIGRATION_VERSION,
                job_id,
                str(frozen["id"]),
                tool_call_id,
                delivery_attempt_id,
                acceptance_hash,
                correlation_id,
                actor_id[:200],
                timestamp,
            ),
        )
        persisted = self.database.execute_one(
            """
            select id, acceptance_hash
              from builtin_tool_legacy_removal_acceptance
             where migration_version = ? and job_id = ?
               and tool_call_id = ? and delivery_attempt_id = ?
            """,
            (MIGRATION_VERSION, job_id, tool_call_id, delivery_attempt_id),
        )
        if persisted is None or str(persisted["acceptance_hash"]) != acceptance_hash:
            raise NonRetryableExecutionError(
                "Removal acceptance evidence conflicts with an existing record",
                safe_message="移除门禁验收证据冲突",
                error_code="builtin_tool_legacy_removal_gate_failed",
            )
        return str(persisted["id"])

    def _consecutive_zero_count(self) -> int:
        count = 0
        rows = self.database.execute(
            """
            select zero_references
              from builtin_tool_legacy_removal_observation
             where migration_version = ?
             order by observed_at desc, id desc
            """,
            (MIGRATION_VERSION,),
        )
        for row in rows:
            if not bool(row["zero_references"]):
                break
            count += 1
        return count

    def _record_gate(
        self,
        *,
        observation_id: str,
        acceptance_id: str,
        consecutive_zero_count: int,
        decision: str,
        reason_code: str,
        actor_id: str,
        correlation_id: str,
        timestamp: str,
    ) -> str:
        gate_id = new_id("builtin_tool_removal_gate")
        self.database.execute(
            """
            insert into builtin_tool_legacy_removal_gate
              (id, migration_version, observation_id, acceptance_id,
               consecutive_zero_count, required_zero_count, decision,
               reason_code, correlation_id, evaluated_by, evaluated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(migration_version, correlation_id) do nothing
            """,
            (
                gate_id,
                MIGRATION_VERSION,
                observation_id,
                acceptance_id or None,
                consecutive_zero_count,
                self.REQUIRED_CONSECUTIVE_ZERO_REPORTS,
                decision,
                reason_code,
                correlation_id,
                actor_id[:200],
                timestamp,
            ),
        )
        row = self.database.execute_one(
            """
            select id, observation_id, acceptance_id, decision
              from builtin_tool_legacy_removal_gate
             where migration_version = ? and correlation_id = ?
            """,
            (MIGRATION_VERSION, correlation_id),
        )
        if (
            row is None
            or str(row["observation_id"]) != observation_id
            or str(row.get("acceptance_id") or "") != acceptance_id
            or str(row["decision"]) != decision
        ):
            raise NonRetryableExecutionError(
                "Removal gate idempotency conflict",
                safe_message="移除门禁判定与既有记录不一致",
                error_code="builtin_tool_legacy_removal_gate_failed",
            )
        return str(row["id"])
