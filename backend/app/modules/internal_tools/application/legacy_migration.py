from __future__ import annotations

from collections.abc import Iterable
from math import prod
from typing import Any

from app.modules.internal_tools.domain import (
    HandlerRegistry,
    HandlerRegistryError,
    build_builtin_handler_registry,
)
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError
from app.modules.platform_config.infrastructure.repository import new_id, now_iso


MIGRATION_VERSION = "builtin-tool-exact-v1"
_CANDIDATE_CLASSES = ("ZERO", "ONE", "MULTIPLE")


class BuiltinToolLegacyWriteGuard:
    """Fail closed at new-write boundaries while retaining legacy reads."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def reject_agent_name_bindings(
        self,
        tool_names: object,
        *,
        source_id: str,
        correlation_id: str = "",
    ) -> None:
        if not isinstance(tool_names, list) or not tool_names:
            return
        self._reject(
            write_boundary="AGENT_PUBLICATION",
            source_id=source_id,
            correlation_id=correlation_id,
        )

    def reject_application_legacy_bindings(
        self,
        bindings: object,
        *,
        source_id: str,
        correlation_id: str = "",
    ) -> None:
        if not isinstance(bindings, list) or not bindings:
            return
        self._reject(
            write_boundary="APPLICATION_PUBLICATION",
            source_id=source_id,
            correlation_id=correlation_id,
        )

    def reject_legacy_job_snapshot(
        self,
        *,
        agent_publication_id: str,
        application_publication_id: str,
        source_id: str,
        correlation_id: str = "",
    ) -> None:
        if not agent_publication_id:
            return
        legacy = self.database.execute_one(
            """
            select 1 as found
              from agent_tool_binding
             where publication_id = ?
             limit 1
            """,
            (agent_publication_id,),
        )
        if legacy is None:
            return
        exact_application = (
            self.database.execute_one(
                """
                select 1 as found
                  from business_application_publication_builtin_tool_resolution_set
                 where application_publication_id = ?
                 limit 1
                """,
                (application_publication_id,),
            )
            if application_publication_id
            else None
        )
        if exact_application is None:
            self._reject(
                write_boundary="JOB_SNAPSHOT",
                source_id=source_id,
                correlation_id=correlation_id,
            )

    def _reject(
        self,
        *,
        write_boundary: str,
        source_id: str,
        correlation_id: str,
    ) -> None:
        self.database.execute(
            """
            insert into builtin_tool_legacy_write_audit
              (id, write_boundary, source_id, attempted_binding_version,
               decision, reason_code, correlation_id, occurred_at)
            values (?, ?, ?, 'legacy-v1', 'REJECTED',
                    'builtin_tool_legacy_write_forbidden', ?, ?)
            """,
            (
                new_id("builtin_tool_legacy_write_audit"),
                write_boundary,
                source_id or "unknown",
                correlation_id or new_id("correlation"),
                now_iso(),
            ),
        )
        raise NonRetryableExecutionError(
            "New legacy-v1 Built-in Tool bindings are forbidden",
            safe_message=(
                "旧名称级工具绑定已停止新增；请选择精确 Tool Release 并重新发布"
            ),
            error_code="builtin_tool_legacy_write_forbidden",
        )


class BuiltinToolLegacyMigrationService:
    """Build a bounded, read-only preflight report for legacy Tool references."""

    def __init__(
        self,
        database: Database,
        registry: HandlerRegistry | None = None,
    ) -> None:
        self.database = database
        self.registry = registry or build_builtin_handler_registry()

    def report(self, *, detail_limit: int = 500) -> dict[str, Any]:
        if detail_limit < 0 or detail_limit > 5_000:
            raise ValueError("detail_limit must be between 0 and 5000")

        agent_items = self._agent_publications()
        application_items = self._application_publications()
        job_items = self._recoverable_jobs()
        all_items = [*agent_items, *application_items, *job_items]
        counts = self._counts(
            agent_items=agent_items,
            application_items=application_items,
            job_items=job_items,
        )
        classification = {
            source_type: {
                candidate_class: sum(
                    1
                    for item in all_items
                    if item["source_type"] == source_type
                    and item["candidate_class"] == candidate_class
                )
                for candidate_class in _CANDIDATE_CLASSES
            }
            for source_type in (
                "AGENT_PUBLICATION",
                "APPLICATION_PUBLICATION",
                "JOB",
            )
        }
        details = sorted(
            all_items,
            key=lambda item: (str(item["source_type"]), str(item["source_id"])),
        )
        return {
            "schema_version": 1,
            "migration_version": MIGRATION_VERSION,
            "mode": "read_only_report",
            "counts": counts,
            "classification": classification,
            "details": details[:detail_limit],
            "detail_count": len(details),
            "details_truncated": len(details) > detail_limit,
            "candidate_release_lifecycle": "ACTIVE",
            "legacy_write_allowed": False,
            "safe_fields_only": True,
        }

    def _counts(
        self,
        *,
        agent_items: list[dict[str, Any]],
        application_items: list[dict[str, Any]],
        job_items: list[dict[str, Any]],
    ) -> dict[str, int]:
        write_rows = self.database.execute(
            """
            select decision, count(*) as count
              from builtin_tool_legacy_write_audit
             where attempted_binding_version = 'legacy-v1'
             group by decision
            """
        )
        write_counts = {
            str(row["decision"]): int(row["count"]) for row in write_rows
        }
        view_counts = {
            str(row["metric"]): int(row["reference_count"])
            for row in self.database.execute(
                "select metric, reference_count from builtin_tool_legacy_reference_report"
            )
        }
        non_terminal = self._count(
            """
            select count(*) as count
              from agent_job job
              left join agent_job_builtin_tool_snapshot snapshot
                on snapshot.job_id = job.id
             where snapshot.id is null
               and job.status in ('PENDING', 'RUNNING')
            """
        )
        retryable = self._count(
            """
            select count(*) as count
              from agent_job job
              left join agent_job_builtin_tool_snapshot snapshot
                on snapshot.job_id = job.id
             where snapshot.id is null
               and job.status = 'FAILED'
               and job.retry_count < job.max_retry_count
               and job.result is null
            """
        )
        replayable = self._count(
            """
            select count(distinct job.id) as count
              from agent_job job
              join job_dispatch_outbox outbox on outbox.job_id = job.id
              left join agent_job_builtin_tool_snapshot snapshot
                on snapshot.job_id = job.id
             where snapshot.id is null
               and outbox.status = 'DEAD'
               and outbox.replay_count < outbox.max_replay_count
               and job.status = 'PENDING'
            """
        )
        return {
            "new_legacy_write_attempts": sum(write_counts.values()),
            "new_legacy_writes_observed": write_counts.get("OBSERVED", 0),
            "new_legacy_writes_rejected": write_counts.get("REJECTED", 0),
            "all_agent_name_bindings": view_counts.get(
                "all_agent_name_binding", 0
            ),
            "active_agent_name_bindings": view_counts.get(
                "active_agent_name_binding", 0
            ),
            "active_agent_publications_with_legacy": len(agent_items),
            "active_application_publications_with_legacy": len(
                application_items
            ),
            "non_terminal_jobs_without_exact_snapshot": non_terminal,
            "retryable_failed_jobs_without_exact_snapshot": retryable,
            "replayable_jobs_without_exact_snapshot": replayable,
            "recoverable_jobs_without_exact_snapshot": len(job_items),
            "reference_view_recoverable_jobs_without_exact_snapshot": (
                view_counts.get("recoverable_job_without_exact_snapshot", 0)
            ),
        }

    def _agent_publications(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select publication.id, publication.agent_id,
                   count(binding.id) as legacy_binding_count
              from agent_publication publication
              join agent_tool_binding binding
                on binding.publication_id = publication.id
             where publication.status = 'active'
             group by publication.id, publication.agent_id
             order by publication.id
            """
        )
        return [
            self._publication_release_item(
                source_type="AGENT_PUBLICATION",
                source_id=str(row["id"]),
                agent_publication_id=str(row["id"]),
                metadata={
                    "agent_id": str(row["agent_id"]),
                    "legacy_binding_count": int(row["legacy_binding_count"]),
                },
            )
            for row in rows
        ]

    def _application_publications(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select distinct publication.id,
                   publication.application_id,
                   revision.agent_publication_id
              from business_application_deployment deployment
              join business_application_publication publication
                on publication.id = deployment.publication_id
              join business_application_revision revision
                on revision.id = publication.revision_id
             where deployment.active = 1
               and not exists (
                 select 1
                   from business_application_publication_builtin_tool exact_tool
                  where exact_tool.application_publication_id = publication.id
               )
               and exists (
                 select 1
                   from agent_tool_binding legacy_binding
                  where legacy_binding.publication_id = revision.agent_publication_id
               )
             order by publication.id
            """
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            agent_publication_id = str(row.get("agent_publication_id") or "")
            item = self._publication_release_item(
                source_type="APPLICATION_PUBLICATION",
                source_id=str(row["id"]),
                agent_publication_id=agent_publication_id,
                metadata={
                    "application_id": str(row["application_id"]),
                    "agent_publication_id": agent_publication_id,
                },
            )
            if item["candidate_class"] == "ONE" and self._requires_resources(
                item["tool_candidates"]
            ):
                item = self._blocked_item(
                    item,
                    blocker="resource_policy_mapping_missing",
                )
            items.append(item)
        return items

    def _recoverable_jobs(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select distinct job.id, job.status, job.agent_publication_id,
                   scope.application_publication_id,
                   case when job.status in ('PENDING', 'RUNNING')
                        then 1 else 0 end as is_non_terminal,
                   case when job.status = 'FAILED'
                          and job.retry_count < job.max_retry_count
                          and job.result is null
                        then 1 else 0 end as is_retryable_failed,
                   case when outbox.status = 'DEAD'
                          and outbox.replay_count < outbox.max_replay_count
                          and job.status = 'PENDING'
                        then 1 else 0 end as is_dispatch_replayable
              from agent_job job
              left join agent_job_builtin_tool_snapshot snapshot
                on snapshot.job_id = job.id
              left join agent_job_execution_scope scope on scope.job_id = job.id
              left join job_dispatch_outbox outbox on outbox.job_id = job.id
             where snapshot.id is null
               and (
                 job.status in ('PENDING', 'RUNNING')
                 or (
                   job.status = 'FAILED'
                   and job.retry_count < job.max_retry_count
                   and job.result is null
                 )
                 or (
                   outbox.status = 'DEAD'
                   and outbox.replay_count < outbox.max_replay_count
                   and job.status = 'PENDING'
                 )
               )
             order by job.id
            """
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            agent_publication_id = str(row.get("agent_publication_id") or "")
            item = self._publication_release_item(
                source_type="JOB",
                source_id=str(row["id"]),
                agent_publication_id=agent_publication_id,
                metadata={
                    "job_status": str(row["status"]),
                    "recovery_kinds": [
                        kind
                        for kind, enabled in (
                            ("NON_TERMINAL", row["is_non_terminal"]),
                            ("RETRYABLE_FAILED", row["is_retryable_failed"]),
                            ("DISPATCH_REPLAY", row["is_dispatch_replayable"]),
                        )
                        if bool(enabled)
                    ],
                    "agent_publication_id": agent_publication_id,
                    "application_publication_id": str(
                        row.get("application_publication_id") or ""
                    ),
                },
            )
            if not str(row.get("application_publication_id") or ""):
                item = self._blocked_item(
                    item,
                    blocker="execution_scope_missing",
                )
            elif item["candidate_class"] == "ONE" and self._requires_resources(
                item["tool_candidates"]
            ):
                item = self._blocked_item(
                    item,
                    blocker="resource_policy_snapshot_missing",
                )
            items.append(item)
        return items

    def _publication_release_item(
        self,
        *,
        source_type: str,
        source_id: str,
        agent_publication_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        tool_names = [
            str(row["tool_name"])
            for row in self.database.execute(
                """
                select tool_name
                  from agent_tool_binding
                 where publication_id = ?
                 order by tool_name
                """,
                (agent_publication_id,),
            )
        ]
        tool_candidates = [
            self._tool_candidates(
                agent_publication_id=agent_publication_id,
                tool_identifier=tool_name,
            )
            for tool_name in tool_names
        ]
        candidate_count = (
            prod(int(item["candidate_count"]) for item in tool_candidates)
            if tool_candidates
            else 0
        )
        candidate_class = self._candidate_class(candidate_count)
        reason_code = {
            "ZERO": "builtin_tool_legacy_resolution_missing",
            "MULTIPLE": "builtin_tool_legacy_resolution_ambiguous",
        }.get(candidate_class, "")
        return {
            "source_type": source_type,
            "source_id": source_id,
            "candidate_class": candidate_class,
            "candidate_count": candidate_count,
            "reason_code": reason_code,
            "blocking_dimensions": [],
            "tool_candidates": tool_candidates,
            **metadata,
        }

    def _tool_candidates(
        self,
        *,
        agent_publication_id: str,
        tool_identifier: str,
    ) -> dict[str, Any]:
        exact_envelope = self.database.execute(
            """
            select release.id, release.tool_identifier,
                   release.handler_version,
                   release.implementation_digest, release.public_schema_hash
              from agent_publication_builtin_tool envelope
              join builtin_tool_release release
                on release.id = envelope.tool_release_id
              join builtin_tool_installation installation
                on installation.tool_identifier = release.tool_identifier
               and installation.handler_version = release.handler_version
               and installation.implementation_digest =
                   release.implementation_digest
             where envelope.agent_publication_id = ?
               and envelope.tool_identifier = ?
               and release.status = 'ACTIVE'
               and installation.installation_status = 'INSTALLED'
            """,
            (agent_publication_id, tool_identifier),
        )
        candidates = self._code_exact_releases(exact_envelope)
        if not candidates:
            candidates = self._code_exact_releases(
                self.database.execute(
                    """
                    select release.id, release.tool_identifier,
                           release.handler_version,
                           release.implementation_digest,
                           release.public_schema_hash
                      from builtin_tool_release release
                      join builtin_tool_installation installation
                        on installation.tool_identifier = release.tool_identifier
                       and installation.handler_version = release.handler_version
                       and installation.implementation_digest =
                           release.implementation_digest
                     where release.tool_identifier = ?
                       and release.status = 'ACTIVE'
                       and installation.installation_status = 'INSTALLED'
                     order by release.release_revision
                    """,
                    (tool_identifier,),
                )
            )
        candidate_count = len(candidates)
        return {
            "tool_identifier": tool_identifier,
            "candidate_class": self._candidate_class(candidate_count),
            "candidate_count": candidate_count,
            "tool_release_ids": [str(item["id"]) for item in candidates],
        }

    def _code_exact_releases(
        self,
        rows: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        exact: list[dict[str, Any]] = []
        for row in rows:
            try:
                definition = self.registry.require(
                    str(row["tool_identifier"]),
                    str(row["handler_version"]),
                )
            except HandlerRegistryError:
                continue
            if (
                definition.implementation_digest
                == str(row["implementation_digest"])
                and definition.public_schema_hash
                == str(row["public_schema_hash"])
            ):
                exact.append(row)
        return exact

    def _requires_resources(self, tool_candidates: Iterable[dict[str, Any]]) -> bool:
        for item in tool_candidates:
            try:
                definition = self.registry.require(
                    str(item["tool_identifier"]),
                    self._candidate_handler_version(item),
                )
            except HandlerRegistryError:
                return True
            if any(slot.required for slot in definition.resource_slots):
                return True
        return False

    def _candidate_handler_version(self, item: dict[str, Any]) -> str:
        release_ids = list(item.get("tool_release_ids") or [])
        if len(release_ids) != 1:
            return ""
        row = self.database.execute_one(
            "select handler_version from builtin_tool_release where id = ?",
            (str(release_ids[0]),),
        )
        return str(row.get("handler_version") or "") if row else ""

    @staticmethod
    def _blocked_item(item: dict[str, Any], *, blocker: str) -> dict[str, Any]:
        return {
            **item,
            "release_candidate_class": item["candidate_class"],
            "release_candidate_count": item["candidate_count"],
            "candidate_class": "ZERO",
            "candidate_count": 0,
            "reason_code": "builtin_tool_legacy_resolution_missing",
            "blocking_dimensions": [
                *list(item.get("blocking_dimensions") or []),
                blocker,
            ],
        }

    @staticmethod
    def _candidate_class(candidate_count: int) -> str:
        if candidate_count == 0:
            return "ZERO"
        if candidate_count == 1:
            return "ONE"
        return "MULTIPLE"

    def _count(self, sql: str) -> int:
        row = self.database.execute_one(sql)
        return int((row or {"count": 0})["count"])
