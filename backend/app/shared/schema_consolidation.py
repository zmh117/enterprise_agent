from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from app.shared.database import Database
from app.shared.migrations import load_migration_catalog
from app.shared.schema_baseline import LEGACY_MANIFEST_FILENAME, load_legacy_manifest
from app.shared.schema_fact_sources import load_fact_source_manifest
from app.modules.platform_config.application.validation import (
    PlatformConfigValidationError,
    normalize_json_object,
    validate_code,
)
from app.modules.workflow.application.graph_facts import (
    canonical_draft_graph,
    parse_legacy_graph,
)
from app.modules.workflow.application.validation import normalize_node_payload, validate_graph


_SAFE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_TERMINAL_JOB_STATUSES = ("SUCCEEDED", "FAILED", "TIMEOUT")


class SchemaConsolidationError(RuntimeError):
    """Safe consolidation failure that never embeds SQL or row contents."""


@dataclass(frozen=True)
class ConsolidationWriteAuthorization:
    phase: str
    expected_head: str
    target_label: str
    evidence_directory: Path


def require_write_authorization(
    *,
    apply: bool,
    phase: str,
    expected_head: str,
    actual_head: str,
    target_label: str,
    confirmed_target: str,
    evidence_directory: Path | None,
    repository_root: Path,
) -> ConsolidationWriteAuthorization | None:
    if not apply:
        return None
    if phase not in {"backfill", "contract/drop"}:
        raise SchemaConsolidationError("Apply mode is not allowed for this phase")
    if expected_head != actual_head:
        raise SchemaConsolidationError("Expected schema head does not match the target ledger")
    if not _SAFE_LABEL.fullmatch(target_label) or confirmed_target != target_label:
        raise SchemaConsolidationError(
            "Apply mode requires the exact non-secret target confirmation"
        )
    if evidence_directory is None or not evidence_directory.is_absolute():
        raise SchemaConsolidationError(
            "Apply mode requires an absolute operator-supplied evidence directory"
        )
    resolved_evidence = evidence_directory.resolve()
    resolved_repository = repository_root.resolve()
    if resolved_evidence == resolved_repository or resolved_repository in resolved_evidence.parents:
        raise SchemaConsolidationError(
            "Consolidation evidence must be stored outside the repository"
        )
    if not resolved_evidence.is_dir():
        raise SchemaConsolidationError("Operator-supplied evidence directory does not exist")
    return ConsolidationWriteAuthorization(
        phase=phase,
        expected_head=expected_head,
        target_label=target_label,
        evidence_directory=resolved_evidence,
    )


def _count(row: dict[str, Any] | None, key: str = "count") -> int:
    return int(row[key]) if row is not None else 0


def _safe_ids(rows: list[dict[str, Any]], *, limit: int = 20) -> list[str]:
    return [str(row["id"]) for row in rows[:limit]]


def _json_object(value: Any) -> dict[str, Any] | None:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def canonical_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    return canonical_draft_graph(nodes=nodes, edges=edges)


class SchemaConsolidationPreflight:
    """Read-only, content-safe checks for schema consolidation stage gates."""

    def __init__(self, database: Database, migrations_dir: Path) -> None:
        self.database = database
        self.migrations_dir = migrations_dir

    def run(self, *, expected_head: str = "100") -> dict[str, Any]:
        migration = self._migration_summary(expected_head=expected_head)
        sessions = self._session_summary()
        jobs = self._job_summary()
        messages = self._message_summary()
        workflows = self._workflow_summary()
        operational = self._operational_summary()
        blockers = [
            *([] if migration["status"] == "current" else [str(migration["status"])]),
            *("session_parity" for _ in range(1) if sessions["blocking_count"]),
            *("job_parity" for _ in range(1) if jobs["blocking_count"]),
            *("message_cardinality" for _ in range(1) if messages["blocking_count"]),
            *("workflow_parity" for _ in range(1) if workflows["blocking_count"]),
        ]
        return {
            "mode": "preflight",
            "status": "ready" if not blockers else "blocked",
            "expected_head": expected_head,
            "migration": migration,
            "compatibility": {
                "sessions": sessions,
                "jobs": jobs,
                "messages": messages,
                "workflows": workflows,
            },
            "operational": operational,
            "blocker_codes": blockers,
            "output_policy": "counts-stable-ids-bounded-error-codes-only",
        }

    def _migration_summary(self, *, expected_head: str) -> dict[str, Any]:
        catalog = load_migration_catalog(self.migrations_dir)
        catalog_by_version = {artifact.version: artifact for artifact in catalog}
        if expected_head not in catalog_by_version:
            raise SchemaConsolidationError("Expected schema head is not in the repository catalog")
        try:
            records = self.database.execute(
                """
                select version, name, checksum
                  from schema_migration
                 order by version
                """
            )
        except Exception as exc:
            raise SchemaConsolidationError("Migration ledger could not be read") from exc
        current_head = str(records[-1]["version"]) if records else "none"
        manifest = load_legacy_manifest(self.migrations_dir / LEGACY_MANIFEST_FILENAME)
        legacy_catalog = manifest["catalog"]
        if len(records) == len(legacy_catalog) and all(
            str(row["version"]) == str(entry["version"])
            and str(row["name"]) == str(entry["name"])
            and str(row["checksum"]) == str(entry["checksum"])
            for row, entry in zip(records, legacy_catalog, strict=True)
        ):
            return {
                "status": "baseline_adoption_required",
                "current_head": current_head,
                "repository_head": catalog[-1].version,
                "checksum_valid": True,
            }

        active_records = records
        if records and str(records[0]["version"]) == str(legacy_catalog[0]["version"]):
            if len(records) <= len(legacy_catalog):
                return {
                    "status": "legacy_head_not_adopted",
                    "current_head": current_head,
                    "repository_head": catalog[-1].version,
                    "checksum_valid": False,
                }
            legacy_records = records[: len(legacy_catalog)]
            if any(
                str(row["version"]) != str(entry["version"])
                or str(row["name"]) != str(entry["name"])
                or str(row["checksum"]) != str(entry["checksum"])
                for row, entry in zip(legacy_records, legacy_catalog, strict=True)
            ):
                return {
                    "status": "legacy_checksum_mismatch",
                    "current_head": current_head,
                    "repository_head": catalog[-1].version,
                    "checksum_valid": False,
                }
            active_records = records[len(legacy_catalog) :]

        expected_index = next(
            index for index, artifact in enumerate(catalog) if artifact.version == expected_head
        )
        expected_catalog = catalog[: expected_index + 1]
        checksum_valid = len(active_records) == len(expected_catalog) and all(
            str(row["version"]) == artifact.version
            and str(row["name"]) == artifact.name
            and str(row["checksum"]) == artifact.checksum
            for row, artifact in zip(active_records, expected_catalog, strict=False)
        )
        status = (
            "current"
            if checksum_valid
            and str(active_records[expected_index]["version"]) == expected_head
            and current_head == expected_head
            else "head_or_checksum_mismatch"
        )
        return {
            "status": status,
            "current_head": current_head,
            "repository_head": catalog[-1].version,
            "checksum_valid": checksum_valid,
        }

    def _session_summary(self) -> dict[str, Any]:
        total = _count(self.database.execute_one("select count(*) as count from agent_session"))
        if not self._has_column("agent_session", "dingding_conversation_id"):
            rows = self.database.execute(
                """
                select id
                  from agent_session
                 where source_channel = '' or source_connector_id = ''
                    or external_conversation_id = '' or requester_id = ''
                 order by id
                 limit 20
                """
            )
            blocking_count = _count(
                self.database.execute_one(
                    """
                    select count(*) as count
                      from agent_session
                     where source_channel = '' or source_connector_id = ''
                        or external_conversation_id = '' or requester_id = ''
                    """
                )
            )
            return {
                "total": total,
                "blocking_count": blocking_count,
                "blocking_ids": _safe_ids(rows),
                "compatibility_state": "retired",
            }
        rows = self.database.execute(
            """
            select id
              from agent_session
             where source_channel = ''
                or source_connector_id = ''
                or external_conversation_id = ''
                or requester_id = ''
                or (source is not null and source_channel <> source)
                or (dingding_conversation_id is not null
                    and external_conversation_id <> dingding_conversation_id)
                or (dingding_user_id is not null and requester_id <> dingding_user_id)
             order by id
             limit 20
            """
        )
        blocking_count = _count(
            self.database.execute_one(
                """
                select count(*) as count
                  from agent_session
                 where source_channel = ''
                    or source_connector_id = ''
                    or external_conversation_id = ''
                    or requester_id = ''
                    or (source is not null and source_channel <> source)
                    or (dingding_conversation_id is not null
                        and external_conversation_id <> dingding_conversation_id)
                    or (dingding_user_id is not null and requester_id <> dingding_user_id)
                """
            )
        )
        return {"total": total, "blocking_count": blocking_count, "blocking_ids": _safe_ids(rows)}

    def _job_summary(self) -> dict[str, Any]:
        total = _count(self.database.execute_one("select count(*) as count from agent_job"))
        if not self._has_column("agent_job", "user_id"):
            rows = self.database.execute(
                """
                select id
                  from agent_job
                 where source_channel = '' or source_connector_id = '' or requester_id = ''
                 order by id
                 limit 20
                """
            )
            blocking_count = _count(
                self.database.execute_one(
                    """
                    select count(*) as count
                      from agent_job
                     where source_channel = '' or source_connector_id = '' or requester_id = ''
                    """
                )
            )
            return {
                "total": total,
                "blocking_count": blocking_count,
                "blocking_ids": _safe_ids(rows),
                "compatibility_state": "retired",
            }
        rows = self.database.execute(
            """
            select id
              from agent_job
             where source_channel = ''
                or requester_id = ''
                or (source is not null and source_channel <> source)
                or (user_id is not null and requester_id <> user_id)
             order by id
             limit 20
            """
        )
        blocking_count = _count(
            self.database.execute_one(
                """
                select count(*) as count
                  from agent_job
                 where source_channel = ''
                    or requester_id = ''
                    or (source is not null and source_channel <> source)
                    or (user_id is not null and requester_id <> user_id)
                """
            )
        )
        return {"total": total, "blocking_count": blocking_count, "blocking_ids": _safe_ids(rows)}

    def _message_summary(self) -> dict[str, Any]:
        if self._has_column("agent_job", "input_message_id"):
            return self._linked_message_summary()
        rows = self.database.execute(
            """
            select job.id,
                   count(message.id) as user_message_count,
                   sum(case when message.content = job.user_message then 1 else 0 end)
                     as matching_content_count
              from agent_job job
              left join agent_message message
                on message.job_id = job.id and message.role = 'user'
             group by job.id
            having count(message.id) <> 1
                or sum(case when message.content = job.user_message then 1 else 0 end) <> 1
             order by job.id
             limit 20
            """
        )
        blocking_count = _count(
            self.database.execute_one(
                """
                select count(*) as count
                  from (
                    select job.id
                      from agent_job job
                      left join agent_message message
                        on message.job_id = job.id and message.role = 'user'
                     group by job.id
                    having count(message.id) <> 1
                        or sum(case when message.content = job.user_message then 1 else 0 end) <> 1
                  ) blocked
                """
            )
        )
        return {
            "job_count": _count(
                self.database.execute_one("select count(*) as count from agent_job")
            ),
            "blocking_count": blocking_count,
            "blocking_ids": _safe_ids(rows),
        }

    def _linked_message_summary(self) -> dict[str, Any]:
        predicate = """
            job.input_message_id is null
            or message.id is null
            or (job.user_message is not null and message.content <> job.user_message)
            or (select count(*) from agent_message candidate
                 where candidate.job_id = job.id and candidate.role = 'user') <> 1
        """
        rows = self.database.execute(
            f"""
            select job.id
              from agent_job job
              left join agent_message message
                on message.id = job.input_message_id
               and message.job_id = job.id
               and message.session_id = job.session_id
               and message.role = 'user'
             where {predicate}
             order by job.id
             limit 20
            """
        )
        blocking_count = _count(
            self.database.execute_one(
                f"""
                select count(*) as count
                  from agent_job job
                  left join agent_message message
                    on message.id = job.input_message_id
                   and message.job_id = job.id
                   and message.session_id = job.session_id
                   and message.role = 'user'
                 where {predicate}
                """
            )
        )
        return {
            "job_count": _count(
                self.database.execute_one("select count(*) as count from agent_job")
            ),
            "blocking_count": blocking_count,
            "blocking_ids": _safe_ids(rows),
        }

    def _has_column(self, table: str, column: str) -> bool:
        if self.database.engine == "sqlite":
            return any(
                str(row["name"]) == column
                for row in self.database.execute(f'pragma table_info("{table}")')
            )
        row = self.database.execute_one(
            """
            select 1 as present
              from information_schema.columns
             where table_schema = 'public' and table_name = ? and column_name = ?
            """,
            (table, column),
        )
        return row is not None

    def _workflow_summary(self) -> dict[str, Any]:
        if not self._has_column("agent_workflow_template", "graph_json"):
            template_count = _count(
                self.database.execute_one("select count(*) as count from agent_workflow_template")
            )
            return {
                "template_count": template_count,
                "empty": 0,
                "graph_only": 0,
                "normalized_only": template_count,
                "equivalent": 0,
                "divergent": 0,
                "invalid_legacy": 0,
                "blocking_count": 0,
                "blocking_ids": [],
                "compatibility_state": "retired",
            }
        templates = self.database.execute(
            "select id, graph_json from agent_workflow_template order by id"
        )
        counts = {
            "empty": 0,
            "graph_only": 0,
            "normalized_only": 0,
            "equivalent": 0,
            "divergent": 0,
            "invalid_legacy": 0,
        }
        blocking_ids: list[str] = []
        for template in templates:
            template_id = str(template["id"])
            node_rows = self.database.execute(
                """
                select node_key, node_type, title, position_json, config_json, ui_json
                  from agent_workflow_node
                 where template_id = ?
                 order by node_key
                """,
                (template_id,),
            )
            edge_rows = self.database.execute(
                """
                select edge_key, source_node_key, target_node_key, source_port,
                       target_port, condition_json
                  from agent_workflow_edge
                 where template_id = ?
                 order by edge_key
                """,
                (template_id,),
            )
            normalized = canonical_graph(
                [
                    {
                        **row,
                        "position": _json_object(row["position_json"]) or {},
                        "config": _json_object(row["config_json"]) or {},
                        "ui": _json_object(row["ui_json"]) or {},
                    }
                    for row in node_rows
                ],
                [
                    {
                        **row,
                        "condition": _json_object(row["condition_json"]) or {},
                    }
                    for row in edge_rows
                ],
            )
            legacy = parse_legacy_graph(template["graph_json"])
            if legacy is None:
                counts["invalid_legacy"] += 1
                blocking_ids.append(template_id)
                continue
            legacy_nonempty = bool(legacy["nodes"] or legacy["edges"])
            normalized_nonempty = bool(normalized["nodes"] or normalized["edges"])
            if not legacy_nonempty and not normalized_nonempty:
                counts["empty"] += 1
            elif legacy_nonempty and not normalized_nonempty:
                counts["graph_only"] += 1
            elif normalized_nonempty and not legacy_nonempty:
                counts["normalized_only"] += 1
            elif legacy == normalized:
                counts["equivalent"] += 1
            else:
                counts["divergent"] += 1
                blocking_ids.append(template_id)
        return {
            "template_count": len(templates),
            **counts,
            "blocking_count": counts["divergent"] + counts["invalid_legacy"],
            "blocking_ids": blocking_ids[:20],
        }

    def _operational_summary(self) -> dict[str, int]:
        queries = {
            "webhook_outbox_nonterminal": (
                "select count(*) as count from webhook_outbox "
                "where status not in ('published', 'dead')"
            ),
            "channel_ingress_outbox_nonterminal": (
                "select count(*) as count from channel_ingress_outbox "
                "where status not in ('published', 'dead')"
            ),
            "job_dispatch_outbox_nonterminal": (
                "select count(*) as count from job_dispatch_outbox "
                "where status not in ('PUBLISHED', 'DEAD')"
            ),
            "delivery_outbox_nonterminal": (
                "select count(*) as count from delivery_outbox "
                "where status not in ('SUCCEEDED', 'FAILED', 'DEAD', 'SKIPPED')"
            ),
            "agent_job_nonterminal": (
                "select count(*) as count from agent_job "
                f"where status not in {_TERMINAL_JOB_STATUSES}"
            ),
            "runtime_terminal_ledger": (
                "select count(*) as count from agent_runtime_terminal_ledger"
            ),
            "runtime_invocation_claim": (
                "select count(*) as count from agent_runtime_invocation_claim"
            ),
            "runtime_invocation_event": (
                "select count(*) as count from agent_runtime_invocation_event"
            ),
            "identity_challenge_active": (
                "select count(*) as count from ones_identity_verification_challenge "
                "where status = 'PENDING'"
            ),
            "job_dispatch_cutover_quarantine": (
                "select count(*) as count from job_dispatch_cutover_quarantine"
            ),
        }
        return {name: _count(self.database.execute_one(query)) for name, query in queries.items()}


class SessionJobMessageBackfill:
    """Content-safe, bounded linkage backfill for canonical execution facts."""

    _PHASE = "session-job-message"

    def __init__(self, database: Database) -> None:
        self.database = database

    def run(
        self,
        *,
        apply: bool = False,
        after_session_id: str = "",
        after_job_id: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        bounded_limit = min(max(int(limit), 1), 1000)
        if apply:
            after_session_id = self._checkpoint("agent_session") or after_session_id
            after_job_id = self._checkpoint("agent_job") or after_job_id
        sessions = self._session_plans(after_session_id, bounded_limit)
        jobs = self._job_plans(after_job_id, bounded_limit)
        blockers = [
            *(plan for plan in sessions["plans"] if bool(plan["blocked"])),
            *(plan for plan in jobs["plans"] if bool(plan["blocked"])),
        ]
        updated_sessions = 0
        updated_jobs = 0
        if apply and not blockers:
            with self.database.unit_of_work():
                for plan in sessions["plans"]:
                    if self._apply_session(plan):
                        updated_sessions += 1
                for plan in jobs["plans"]:
                    if self._apply_job(plan):
                        updated_jobs += 1
                self._save_checkpoint(
                    target_object="agent_session",
                    high_water=str(sessions["high_water_mark"]),
                    scanned=len(sessions["plans"]),
                    updated=updated_sessions,
                )
                self._save_checkpoint(
                    target_object="agent_job",
                    high_water=str(jobs["high_water_mark"]),
                    scanned=len(jobs["plans"]),
                    updated=updated_jobs,
                )
        session_counts = _classification_counts(sessions["plans"])
        job_counts = _classification_counts(jobs["plans"])
        safe_payload = {
            "mode": "apply" if apply else "dry-run",
            "status": "blocked" if blockers else "ready",
            "processed_count": len(sessions["plans"]) + len(jobs["plans"]),
            "applied_count": updated_sessions + updated_jobs,
            "session": {
                "classification_counts": session_counts,
                "high_water_mark": sessions["high_water_mark"],
                "truncated": sessions["truncated"],
                "next_after_id": sessions["next_after_id"],
            },
            "job_message": {
                "classification_counts": job_counts,
                "high_water_mark": jobs["high_water_mark"],
                "truncated": jobs["truncated"],
                "next_after_id": jobs["next_after_id"],
            },
            "blocking_ids": [str(plan["id"]) for plan in blockers[:20]],
        }
        return {**safe_payload, "evidence_digest": _evidence_digest(safe_payload)}

    def _session_plans(self, after_id: str, limit: int) -> dict[str, Any]:
        rows = self.database.execute(
            """
            select id,
                   source_channel, source_connector_id, external_conversation_id,
                   requester_id, source, dingding_conversation_id, dingding_user_id,
                   business_application_id, application_publication_id,
                   execution_scope_hash, history_read_only
              from agent_session
             where id > ?
             order by id
             limit ?
            """,
            (after_id, limit + 1),
        )
        truncated = len(rows) > limit
        rows = rows[:limit]
        plans: list[dict[str, Any]] = []
        for row in rows:
            source_channel = str(row.get("source_channel") or row.get("source") or "")
            conversation_id = str(
                row.get("external_conversation_id") or row.get("dingding_conversation_id") or ""
            )
            requester_id = str(row.get("requester_id") or row.get("dingding_user_id") or "")
            missing_identity = not all(
                (
                    source_channel,
                    str(row.get("source_connector_id") or ""),
                    conversation_id,
                    requester_id,
                )
            )
            application_unattributed = bool(row.get("business_application_id")) and not all(
                (
                    row.get("application_publication_id"),
                    row.get("execution_scope_hash"),
                )
            )
            needs_update = (
                source_channel != str(row.get("source_channel") or "")
                or conversation_id != str(row.get("external_conversation_id") or "")
                or requester_id != str(row.get("requester_id") or "")
                or (application_unattributed and not bool(row.get("history_read_only")))
            )
            classification = (
                "missing_identity"
                if missing_identity
                else "historical_read_only"
                if application_unattributed
                else "backfillable"
                if needs_update
                else "canonical"
            )
            plans.append(
                {
                    "id": str(row["id"]),
                    "classification": classification,
                    "blocked": missing_identity,
                    "source_channel": source_channel,
                    "external_conversation_id": conversation_id,
                    "requester_id": requester_id,
                    "history_read_only": application_unattributed
                    or bool(row.get("history_read_only")),
                    "needs_update": needs_update,
                }
            )
        return _page(plans, after_id=after_id, truncated=truncated)

    def _job_plans(self, after_id: str, limit: int) -> dict[str, Any]:
        rows = self.database.execute(
            """
            select job.id, job.session_id, job.input_message_id, job.user_message,
                   job.status, job.source_channel, job.source, job.requester_id, job.user_id,
                   job.source_connector_id,
                   count(message.id) as user_message_count,
                   min(message.id) as candidate_message_id,
                   sum(case when job.user_message is null
                                  or message.content = job.user_message
                            then 1 else 0 end) as compatible_message_count
              from agent_job job
              left join agent_message message
                on message.job_id = job.id
               and message.session_id = job.session_id
               and message.role = 'user'
             where job.id > ?
             group by job.id, job.session_id, job.input_message_id, job.user_message,
                      job.status, job.source_channel, job.source, job.requester_id,
                      job.user_id, job.source_connector_id
             order by job.id
             limit ?
            """,
            (after_id, limit + 1),
        )
        truncated = len(rows) > limit
        rows = rows[:limit]
        plans: list[dict[str, Any]] = []
        for row in rows:
            source_channel = str(row.get("source_channel") or row.get("source") or "")
            requester_id = str(row.get("requester_id") or row.get("user_id") or "")
            provenance_missing = not all(
                (
                    source_channel,
                    str(row.get("source_connector_id") or ""),
                    requester_id,
                )
            )
            message_count = int(row.get("user_message_count") or 0)
            existing_link = str(row.get("input_message_id") or "")
            candidate = str(row.get("candidate_message_id") or "")
            compatible = int(row.get("compatible_message_count") or 0)
            if existing_link:
                message_blocked = message_count != 1 or candidate != existing_link
                classification = "linked" if not message_blocked else "invalid_link"
            elif message_count == 1 and compatible == 1:
                message_blocked = False
                classification = "linkable"
            elif message_count == 0:
                message_blocked = True
                classification = "missing_message"
            else:
                message_blocked = True
                classification = "ambiguous_message"
            plans.append(
                {
                    "id": str(row["id"]),
                    "classification": (
                        "missing_provenance" if provenance_missing else classification
                    ),
                    "blocked": provenance_missing or message_blocked,
                    "source_channel": source_channel,
                    "requester_id": requester_id,
                    "input_message_id": existing_link or candidate,
                    "needs_update": (
                        not existing_link
                        or source_channel != str(row.get("source_channel") or "")
                        or requester_id != str(row.get("requester_id") or "")
                    ),
                }
            )
        return _page(plans, after_id=after_id, truncated=truncated)

    def _apply_session(self, plan: dict[str, Any]) -> bool:
        if not plan["needs_update"]:
            return False
        changed = self.database.execute(
            """
            update agent_session
               set source_channel = ?, external_conversation_id = ?, requester_id = ?,
                   history_read_only = ?
             where id = ?
            returning id
            """,
            (
                plan["source_channel"],
                plan["external_conversation_id"],
                plan["requester_id"],
                1 if plan["history_read_only"] else 0,
                plan["id"],
            ),
        )
        return bool(changed)

    def _apply_job(self, plan: dict[str, Any]) -> bool:
        if not plan["needs_update"]:
            return False
        changed = self.database.execute(
            """
            update agent_job
               set source_channel = ?, requester_id = ?, input_message_id = ?
             where id = ?
               and (input_message_id is null or input_message_id = ?)
            returning id
            """,
            (
                plan["source_channel"],
                plan["requester_id"],
                plan["input_message_id"],
                plan["id"],
                plan["input_message_id"],
            ),
        )
        if not changed:
            raise SchemaConsolidationError("Job input linkage changed during backfill")
        return True

    def _checkpoint(self, target_object: str) -> str:
        row = self.database.execute_one(
            """
            select last_id
              from schema_consolidation_checkpoint
             where phase = ? and target_object = ?
            """,
            (self._PHASE, target_object),
        )
        return str(row["last_id"]) if row else ""

    def _save_checkpoint(
        self,
        *,
        target_object: str,
        high_water: str,
        scanned: int,
        updated: int,
    ) -> None:
        payload = {
            "phase": self._PHASE,
            "target_object": target_object,
            "last_id": high_water,
            "scanned_count": scanned,
            "updated_count": updated,
            "blocked_count": 0,
        }
        self.database.execute(
            """
            insert into schema_consolidation_checkpoint
              (phase, target_object, last_id, scanned_count, updated_count,
               blocked_count, evidence_digest, updated_at)
            values (?, ?, ?, ?, ?, 0, ?, ?)
            on conflict(phase, target_object) do update set
              last_id = excluded.last_id,
              scanned_count = schema_consolidation_checkpoint.scanned_count
                              + excluded.scanned_count,
              updated_count = schema_consolidation_checkpoint.updated_count
                              + excluded.updated_count,
              evidence_digest = excluded.evidence_digest,
              updated_at = excluded.updated_at
            """,
            (
                self._PHASE,
                target_object,
                high_water,
                scanned,
                updated,
                _evidence_digest(payload),
                datetime.now(UTC).isoformat(),
            ),
        )


class WorkflowGraphBackfill:
    """Re-runnable normalized graph backfill with safe, external checkpoints."""

    _PHASE = "workflow-graph"
    _TARGET_OBJECT = "agent_workflow_template"

    def __init__(self, database: Database) -> None:
        self.database = database

    def run(
        self,
        *,
        apply: bool = False,
        after_id: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        bounded_limit = min(max(int(limit), 1), 1000)
        if apply:
            after_id = self._checkpoint() or after_id
        templates = self.database.execute(
            """
            select id, entry_node_key, graph_json
              from agent_workflow_template
             where id > ?
             order by id
             limit ?
            """,
            (after_id, bounded_limit + 1),
        )
        truncated = len(templates) > bounded_limit
        templates = templates[:bounded_limit]
        plans = [self._plan_template(row) for row in templates]
        blocking = [
            plan for plan in plans if plan["classification"] in {"divergent", "invalid_legacy"}
        ]
        applied_count = 0
        if apply and not blocking:
            with self.database.unit_of_work():
                applied_count = sum(1 for plan in plans if self._apply_template(plan))
                self._save_checkpoint(
                    high_water=(str(plans[-1]["template_id"]) if plans else after_id),
                    scanned=len(plans),
                    updated=applied_count,
                )
        counts: dict[str, int] = {}
        for plan in plans:
            classification = str(plan["classification"])
            counts[classification] = counts.get(classification, 0) + 1
        safe_payload = {
            "mode": "apply" if apply else "dry-run",
            "status": "blocked" if blocking else "ready",
            "processed_count": len(plans),
            "applied_count": applied_count,
            "classification_counts": dict(sorted(counts.items())),
            "blocking_ids": [str(plan["template_id"]) for plan in blocking[:20]],
            "high_water_mark": str(plans[-1]["template_id"]) if plans else after_id,
            "truncated": truncated,
            "next_after_id": str(plans[-1]["template_id"]) if truncated and plans else "",
        }
        digest = hashlib.sha256(
            json.dumps(
                safe_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {**safe_payload, "evidence_digest": digest}

    def _plan_template(self, row: dict[str, Any]) -> dict[str, Any]:
        template_id = str(row["id"])
        normalized = self._normalized_graph(template_id)
        legacy = parse_legacy_graph(row["graph_json"])
        if legacy is None:
            classification = "invalid_legacy"
        else:
            legacy_nonempty = bool(legacy["nodes"] or legacy["edges"])
            normalized_nonempty = bool(normalized["nodes"] or normalized["edges"])
            if not legacy_nonempty and not normalized_nonempty:
                classification = "empty"
            elif legacy_nonempty and not normalized_nonempty:
                classification = "graph_only"
            elif normalized_nonempty and not legacy_nonempty:
                classification = "normalized_only"
            elif legacy == normalized:
                classification = "equivalent"
            else:
                classification = "divergent"
        plan: dict[str, Any] = {
            "template_id": template_id,
            "entry_node_key": str(row.get("entry_node_key") or ""),
            "classification": classification,
            "legacy": legacy,
        }
        if classification == "graph_only":
            assert legacy is not None
            try:
                nodes = [normalize_node_payload(dict(node)) for node in legacy["nodes"]]
                edges = [self._normalize_edge(dict(edge)) for edge in legacy["edges"]]
                validate_graph(
                    entry_node_key=str(plan["entry_node_key"]),
                    nodes=nodes,
                    edges=edges,
                )
            except (KeyError, PlatformConfigValidationError, ValueError, TypeError):
                plan["classification"] = "invalid_legacy"
            else:
                plan["backfill_nodes"] = nodes
                plan["backfill_edges"] = edges
        return plan

    def _normalized_graph(self, template_id: str) -> dict[str, list[dict[str, Any]]]:
        node_rows = self.database.execute(
            """
            select node_key, node_type, title, position_json, config_json, ui_json
              from agent_workflow_node
             where template_id = ?
             order by node_key
            """,
            (template_id,),
        )
        edge_rows = self.database.execute(
            """
            select edge_key, source_node_key, target_node_key, source_port,
                   target_port, condition_json
              from agent_workflow_edge
             where template_id = ?
             order by edge_key
            """,
            (template_id,),
        )
        return canonical_draft_graph(
            nodes=[
                {
                    **row,
                    "position": _json_object(row["position_json"]) or {},
                    "config": _json_object(row["config_json"]) or {},
                    "ui": _json_object(row["ui_json"]) or {},
                }
                for row in node_rows
            ],
            edges=[
                {**row, "condition": _json_object(row["condition_json"]) or {}} for row in edge_rows
            ],
        )

    def _apply_template(self, plan: dict[str, Any]) -> bool:
        if plan["classification"] != "graph_only":
            return False
        nodes = plan["backfill_nodes"]
        edges = plan["backfill_edges"]
        timestamp = datetime.now(UTC).isoformat()
        template_id = str(plan["template_id"])
        normalized = self._normalized_graph(template_id)
        if normalized["nodes"] or normalized["edges"]:
            raise SchemaConsolidationError("Workflow normalized graph changed during backfill")
        for node in nodes:
            self.database.execute(
                """
                insert into agent_workflow_node
                  (id, template_id, node_key, node_type, title, position_json,
                   config_json, ui_json, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _stable_backfill_id("wf_node", template_id, str(node["node_key"])),
                    template_id,
                    node["node_key"],
                    node["node_type"],
                    node["title"],
                    _json_text(node["position"]),
                    _json_text(node["config"]),
                    _json_text(node["ui"]),
                    timestamp,
                    timestamp,
                ),
            )
        for edge in edges:
            self.database.execute(
                """
                insert into agent_workflow_edge
                  (id, template_id, edge_key, source_node_key, target_node_key,
                   source_port, target_port, condition_json, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _stable_backfill_id("wf_edge", template_id, str(edge["edge_key"])),
                    template_id,
                    edge["edge_key"],
                    edge["source_node_key"],
                    edge["target_node_key"],
                    edge["source_port"],
                    edge["target_port"],
                    _json_text(edge["condition"]),
                    timestamp,
                    timestamp,
                ),
            )
        self.database.execute(
            "update agent_workflow_template set updated_at = ? where id = ?",
            (timestamp, template_id),
        )
        return True

    def _checkpoint(self) -> str:
        row = self.database.execute_one(
            """
            select last_id
              from schema_consolidation_checkpoint
             where phase = ? and target_object = ?
            """,
            (self._PHASE, self._TARGET_OBJECT),
        )
        return str(row["last_id"]) if row else ""

    def _save_checkpoint(
        self,
        *,
        high_water: str,
        scanned: int,
        updated: int,
    ) -> None:
        payload = {
            "phase": self._PHASE,
            "target_object": self._TARGET_OBJECT,
            "last_id": high_water,
            "scanned_count": scanned,
            "updated_count": updated,
            "blocked_count": 0,
        }
        self.database.execute(
            """
            insert into schema_consolidation_checkpoint
              (phase, target_object, last_id, scanned_count, updated_count,
               blocked_count, evidence_digest, updated_at)
            values (?, ?, ?, ?, ?, 0, ?, ?)
            on conflict(phase, target_object) do update set
              last_id = excluded.last_id,
              scanned_count = schema_consolidation_checkpoint.scanned_count
                              + excluded.scanned_count,
              updated_count = schema_consolidation_checkpoint.updated_count
                              + excluded.updated_count,
              evidence_digest = excluded.evidence_digest,
              updated_at = excluded.updated_at
            """,
            (
                self._PHASE,
                self._TARGET_OBJECT,
                high_water,
                scanned,
                updated,
                _evidence_digest(payload),
                datetime.now(UTC).isoformat(),
            ),
        )

    def _normalize_edge(self, edge: dict[str, Any]) -> dict[str, Any]:
        return {
            "edge_key": validate_code(str(edge.get("edge_key") or ""), field="edge_key"),
            "source_node_key": validate_code(
                str(edge.get("source_node_key") or ""),
                field="source_node_key",
            ),
            "target_node_key": validate_code(
                str(edge.get("target_node_key") or ""),
                field="target_node_key",
            ),
            "source_port": str(edge.get("source_port") or ""),
            "target_port": str(edge.get("target_port") or ""),
            "condition": normalize_json_object(edge.get("condition"), field="condition"),
        }


def _stable_backfill_id(prefix: str, template_id: str, key: str) -> str:
    digest = hashlib.sha256(f"{prefix}:{template_id}:{key}".encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:32]}"


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _evidence_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(_json_text(value).encode("utf-8")).hexdigest()


def _classification_counts(plans: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for plan in plans:
        classification = str(plan["classification"])
        counts[classification] = counts.get(classification, 0) + 1
    return dict(sorted(counts.items()))


def _page(
    plans: list[dict[str, Any]],
    *,
    after_id: str,
    truncated: bool,
) -> dict[str, Any]:
    high_water = str(plans[-1]["id"]) if plans else after_id
    return {
        "plans": plans,
        "high_water_mark": high_water,
        "truncated": truncated,
        "next_after_id": high_water if truncated and plans else "",
    }


def expected_head_from_manifest(*, phase: str = "preflight") -> str:
    manifest = load_fact_source_manifest()
    if phase == "preflight":
        return str(manifest["baseline_predecessor"])
    if phase == "backfill":
        return str(manifest["migration_plan"]["backfill_checkpoint_candidate"])
    if phase == "contract/drop":
        return str(manifest["migration_plan"]["backfill_checkpoint_candidate"])
    raise SchemaConsolidationError("Unknown consolidation phase")
