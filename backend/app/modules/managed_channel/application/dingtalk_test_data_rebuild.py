from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Iterable

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError


CONFIRMATION_TEXT = "确认清空钉钉测试数据"
NON_PRODUCTION_ENVIRONMENTS = {
    "local",
    "test",
    "testing",
    "dev",
    "development",
    "stage",
    "staging",
    "qa",
}
TARGET_ORDER = (
    "governance_audits",
    "nickname_audits",
    "application_observations",
    "candidate_messages",
    "candidates",
    "ingress_outbox",
    "ingress_events",
    "connector_runtime",
    "runtime_leases",
    "dingtalk_identities",
    "active_routes",
    "dedicated_secrets",
    "connectors",
    "enterprises",
)
PROTECTED_COUNT_QUERIES = {
    "users": "select count(*) as count from app_user",
    "user_sessions": "select count(*) as count from user_session",
    "roles": "select count(*) as count from rbac_role",
    "role_memberships": "select count(*) as count from rbac_user_role",
    "ones_identities": (
        "select count(*) as count from user_external_identity where provider = 'ones'"
    ),
    "agents": "select count(*) as count from agent_definition",
    "agent_publications": "select count(*) as count from agent_publication",
    "business_applications": ("select count(*) as count from business_application"),
    "application_revisions": ("select count(*) as count from business_application_revision"),
    "application_publications": ("select count(*) as count from business_application_publication"),
    "agent_jobs": "select count(*) as count from agent_job",
    "agent_tool_calls": "select count(*) as count from agent_tool_call",
    "delivery_attempts": "select count(*) as count from delivery_attempt",
    "delivery_outbox": "select count(*) as count from delivery_outbox",
}


class DingTalkTestDataRebuildService:
    """Plan and apply an explicit non-production DingTalk data rebuild."""

    def __init__(self, database: Database, *, environment: str) -> None:
        self.database = database
        self.environment = str(environment or "").strip().lower()

    def report(self) -> dict[str, Any]:
        self._require_non_production()
        targets = self._targets()
        protected_counts = self._protected_counts()
        historical_references = self._historical_references(self._target_ids(targets, "connectors"))
        protected_blockers = self._protected_blockers(
            identity_ids=self._target_ids(targets, "dingtalk_identities"),
            audit_ids=self._target_ids(targets, "governance_audits"),
        )
        write_stop = self._write_stop_evidence()
        counts = {name: len(targets.get(name, [])) for name in TARGET_ORDER}
        stable_inventory = {
            "schema_head": self._schema_head(),
            "database_locator_hash": self._database_locator_hash(),
            "targets": targets,
            "historical_references": historical_references,
            "protected_counts": protected_counts,
            "protected_blockers": protected_blockers,
            "write_stop_evidence": write_stop,
        }
        database_fingerprint = self._digest(stable_inventory)
        plan_payload = {
            "environment": self.environment,
            "database_engine": self.database.engine,
            "database_fingerprint": database_fingerprint,
            "counts": counts,
            "targets": targets,
            "historical_references": historical_references,
            "protected_counts": protected_counts,
            "protected_blockers": protected_blockers,
            "write_stop_evidence": write_stop,
        }
        return {
            "mode": "PREVIEW",
            "generated_at": now_iso(),
            **plan_payload,
            "plan_hash": self._digest(plan_payload),
            "empty": not any(counts.values()),
            "confirmation_text": CONFIRMATION_TEXT,
            "preserved_categories": list(PROTECTED_COUNT_QUERIES),
            "required_execution_guards": [
                "non_production_environment",
                "verified_backup_reference",
                "dingtalk_writes_stopped",
                "matching_plan_hash",
                "fixed_confirmation_text",
            ],
        }

    def apply(
        self,
        *,
        expected_plan_hash: str,
        confirmation: str,
        backup_reference: str,
        writes_stopped: bool,
        actor_id: str,
    ) -> dict[str, Any]:
        self._require_non_production()
        if confirmation != CONFIRMATION_TEXT:
            raise NonRetryableExecutionError(
                "DingTalk rebuild confirmation mismatch",
                safe_message=(f"执行钉钉测试数据重建必须输入固定确认文字：{CONFIRMATION_TEXT}"),
                error_code="dingtalk_rebuild_confirmation_required",
            )
        if not str(backup_reference or "").strip():
            raise NonRetryableExecutionError(
                "DingTalk rebuild backup reference is required",
                safe_message="执行前必须提供已验证的数据库备份引用",
                error_code="dingtalk_rebuild_backup_required",
            )
        if not writes_stopped:
            raise NonRetryableExecutionError(
                "DingTalk writes are not confirmed stopped",
                safe_message="必须先停止钉钉 Runtime、Ingress 和 Outbox Worker",
                error_code="dingtalk_rebuild_writes_not_stopped",
            )
        if len(str(expected_plan_hash or "")) != 64:
            raise NonRetryableExecutionError(
                "DingTalk rebuild plan hash is invalid",
                safe_message="必须提供本次只读预检生成的 plan_hash",
                error_code="dingtalk_rebuild_plan_hash_required",
            )
        if not str(actor_id or "").strip():
            raise ValueError("DingTalk rebuild actor is required")

        with self.database.unit_of_work():
            self._lock_write_tables()
            current = self.report()
            if current["plan_hash"] != expected_plan_hash:
                raise NonRetryableExecutionError(
                    "DingTalk rebuild inventory changed",
                    safe_message="钉钉重建计划已变化，请重新运行只读预检",
                    error_code="dingtalk_rebuild_plan_changed",
                )
            if current["protected_blockers"]:
                raise NonRetryableExecutionError(
                    "DingTalk rebuild has protected references",
                    safe_message="待清数据仍被受保护历史引用，拒绝执行",
                    error_code="dingtalk_rebuild_protected_reference",
                )
            if not current["write_stop_evidence"]["safe_to_apply"]:
                raise NonRetryableExecutionError(
                    "DingTalk writers are still active",
                    safe_message="检测到仍在写入的钉钉租约或任务，请停止后重新预检",
                    error_code="dingtalk_rebuild_writers_active",
                )
            if current["empty"]:
                return {
                    "status": "NOOP",
                    "plan_hash": expected_plan_hash,
                    "counts": current["counts"],
                    "protected_counts": current["protected_counts"],
                    "message": "当前没有需要清理的钉钉测试数据",
                }

            before_protected = dict(current["protected_counts"])
            self._apply_targets(current["targets"])
            after_protected = self._protected_counts()
            if after_protected != before_protected:
                raise NonRetryableExecutionError(
                    "Protected data changed during DingTalk rebuild",
                    safe_message="受保护数据数量发生变化，事务已回滚",
                    error_code="dingtalk_rebuild_protected_data_changed",
                )
            remaining = self.report()
            if not remaining["empty"]:
                raise NonRetryableExecutionError(
                    "DingTalk rebuild verification failed",
                    safe_message="钉钉测试数据清理后复核失败，事务已回滚",
                    error_code="dingtalk_rebuild_verify_failed",
                )
            self._record_audit(
                actor_id=str(actor_id),
                plan_hash=expected_plan_hash,
                backup_reference=str(backup_reference),
                counts=dict(current["counts"]),
            )
            return {
                "status": "APPLIED",
                "plan_hash": expected_plan_hash,
                "counts": current["counts"],
                "remaining_counts": remaining["counts"],
                "protected_counts": after_protected,
                "historical_references_preserved": current["historical_references"],
            }

    def _targets(self) -> dict[str, list[dict[str, Any]]]:
        connectors = self.database.execute(
            """
            select id, name, enabled, deleted, revision,
                   coalesce(dingtalk_enterprise_id, '') as enterprise_id,
                   coalesce(secret_ref, '') as secret_ref,
                   metadata
              from integration_connector
             where connector_type = 'dingtalk_enterprise_stream'
               and (
                 deleted = 0
                 or dingtalk_enterprise_id is not null
                 or coalesce(secret_ref, '') <> ''
               )
             order by id
            """
        )
        connector_ids = {str(row["id"]) for row in connectors}
        connector_refs = {
            str(row.get("secret_ref") or "")
            for row in connectors
            if str(row.get("secret_ref") or "").startswith("secret://platform/")
        }
        enterprises = self.database.execute(
            """
            select id, name, status, revision,
                   coalesce(corp_id, '') as corp_id
              from dingtalk_enterprise
             order by id
            """
        )
        identities = self.database.execute(
            """
            select id, user_id, status, revision,
                   coalesce(dingtalk_enterprise_id, '') as enterprise_id
              from user_external_identity
             where provider = 'dingtalk'
             order by id
            """
        )
        candidates = self.database.execute(
            """
            select id, revision,
                   coalesce(dingtalk_enterprise_id, '') as enterprise_id
              from dingtalk_identity_candidate
             order by id
            """
        )
        candidate_messages = self.database.execute(
            """
            select id, candidate_id, source_ingress_event_id, connector_id
              from dingtalk_identity_candidate_message
             order by id
            """
        )
        ingress_events = self._by_values(
            """
            select id, connector_id, external_event_id, status
              from channel_ingress_event
             where connector_id in ({placeholders})
             order by id
            """,
            connector_ids,
        )
        ingress_event_ids = {str(row["id"]) for row in ingress_events}
        ingress_outbox = self._by_values(
            """
            select id, channel_event_id, status
              from channel_ingress_outbox
             where channel_event_id in ({placeholders})
             order by id
            """,
            ingress_event_ids,
        )
        connector_runtime = self._by_values(
            """
            select connector_id as id, runtime_id, runtime_status,
                   connected, registered
              from channel_connector_runtime
             where connector_id in ({placeholders})
             order by connector_id
            """,
            connector_ids,
        )
        runtime_leases = self.database.execute(
            """
            select lease_name as id, runtime_id, expires_at
              from channel_runtime_lease
             where lower(lease_name) like ?
             order by lease_name
            """,
            ("dingtalk%",),
        )
        observations = self.database.execute(
            """
            select id, external_identity_id, connector_id,
                   last_ingress_event_id, revision
              from dingtalk_identity_application_observation
             order by id
            """
        )
        nickname_audits = self.database.execute(
            """
            select id, external_identity_id, connector_id,
                   source_ingress_event_id
              from dingtalk_identity_nickname_audit
             order by id
            """
        )
        active_routes = self._by_values(
            """
            select r.id, r.connector_id, r.deployment_id,
                   r.application_id, a.code as application_code,
                   a.name as application_name,
                   r.publication_id, r.trigger_type
              from business_application_active_route r
              join business_application a on a.id = r.application_id
             where r.connector_id in ({placeholders})
             order by r.id
            """,
            connector_ids,
        )
        dedicated_secrets = self._dedicated_secrets(
            connector_refs=connector_refs,
            target_connector_ids=connector_ids,
        )
        governance_audits = self._governance_audits(
            connector_ids=connector_ids,
            enterprise_ids={str(row["id"]) for row in enterprises},
        )
        return {
            "governance_audits": self._safe_rows(
                governance_audits,
                ("id", "event_type", "status"),
            ),
            "nickname_audits": self._safe_rows(
                nickname_audits,
                (
                    "id",
                    "external_identity_id",
                    "connector_id",
                    "source_ingress_event_id",
                ),
            ),
            "application_observations": self._safe_rows(
                observations,
                (
                    "id",
                    "external_identity_id",
                    "connector_id",
                    "last_ingress_event_id",
                    "revision",
                ),
            ),
            "candidate_messages": self._safe_rows(
                candidate_messages,
                (
                    "id",
                    "candidate_id",
                    "source_ingress_event_id",
                    "connector_id",
                ),
            ),
            "candidates": self._safe_rows(candidates, ("id", "enterprise_id", "revision")),
            "ingress_outbox": self._safe_rows(ingress_outbox, ("id", "channel_event_id", "status")),
            "ingress_events": self._safe_rows(
                ingress_events,
                ("id", "connector_id", "external_event_id", "status"),
            ),
            "connector_runtime": self._safe_rows(
                connector_runtime,
                (
                    "id",
                    "runtime_id",
                    "runtime_status",
                    "connected",
                    "registered",
                ),
            ),
            "runtime_leases": self._safe_rows(runtime_leases, ("id", "runtime_id", "expires_at")),
            "dingtalk_identities": self._safe_rows(
                identities,
                ("id", "user_id", "enterprise_id", "status", "revision"),
            ),
            "active_routes": self._safe_rows(
                active_routes,
                (
                    "id",
                    "connector_id",
                    "deployment_id",
                    "application_id",
                    "application_code",
                    "application_name",
                    "publication_id",
                    "trigger_type",
                ),
            ),
            "dedicated_secrets": self._safe_rows(
                dedicated_secrets,
                ("id", "code", "ref", "status", "revision"),
            ),
            "connectors": [
                {
                    **self._safe_row(
                        row,
                        (
                            "id",
                            "name",
                            "enabled",
                            "deleted",
                            "revision",
                            "enterprise_id",
                            "secret_ref",
                        ),
                    ),
                    "metadata_digest": self._digest(self._json_object(row.get("metadata") or "{}")),
                }
                for row in connectors
            ],
            "enterprises": self._safe_rows(
                enterprises, ("id", "name", "corp_id", "status", "revision")
            ),
        }

    def _apply_targets(self, targets: dict[str, list[dict[str, Any]]]) -> None:
        self._before_step("governance_audits")
        self._delete_ids("audit_event", self._target_ids(targets, "governance_audits"))
        self._before_step("nickname_audits")
        self._delete_ids(
            "dingtalk_identity_nickname_audit",
            self._target_ids(targets, "nickname_audits"),
        )
        self._before_step("application_observations")
        self._delete_ids(
            "dingtalk_identity_application_observation",
            self._target_ids(targets, "application_observations"),
        )
        self._before_step("candidate_messages")
        self._delete_ids(
            "dingtalk_identity_candidate_message",
            self._target_ids(targets, "candidate_messages"),
        )
        self._before_step("candidates")
        self._delete_ids(
            "dingtalk_identity_candidate",
            self._target_ids(targets, "candidates"),
        )
        self._before_step("ingress_outbox")
        self._delete_ids(
            "channel_ingress_outbox",
            self._target_ids(targets, "ingress_outbox"),
        )
        self._before_step("ingress_events")
        self._delete_ids(
            "channel_ingress_event",
            self._target_ids(targets, "ingress_events"),
        )
        self._before_step("connector_runtime")
        self._delete_ids(
            "channel_connector_runtime",
            self._target_ids(targets, "connector_runtime"),
            id_column="connector_id",
        )
        self._before_step("runtime_leases")
        self._delete_ids(
            "channel_runtime_lease",
            self._target_ids(targets, "runtime_leases"),
            id_column="lease_name",
        )
        self._before_step("dingtalk_identities")
        self._delete_ids(
            "user_external_identity",
            self._target_ids(targets, "dingtalk_identities"),
        )
        self._before_step("active_routes")
        route_ids = self._target_ids(targets, "active_routes")
        deployment_ids = {str(row["deployment_id"]) for row in targets["active_routes"]}
        self._delete_ids("business_application_active_route", route_ids)
        self._deactivate_deployments(deployment_ids)
        self._before_step("dedicated_secrets")
        self._revoke_secrets(targets["dedicated_secrets"])
        self._before_step("connectors")
        self._soft_delete_connectors(targets["connectors"])
        self._before_step("enterprises")
        self._delete_ids(
            "dingtalk_enterprise",
            self._target_ids(targets, "enterprises"),
        )

    def _soft_delete_connectors(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            connector_id = str(row["id"])
            current = self.database.execute_one(
                "select metadata from integration_connector where id = ?",
                (connector_id,),
            )
            metadata = self._json_object((current or {}).get("metadata") or "{}")
            metadata.update(
                {
                    "historical_source_status": "UNAVAILABLE",
                    "historical_source_reason": "DINGTALK_TEST_DATA_REBUILD",
                }
            )
            self.database.execute(
                """
                update integration_connector
                   set enabled = 0, deleted = 1, allow_ingress = 0,
                       allow_delivery = 0, secret_ref = '', endpoint_ref = '',
                       dingtalk_enterprise_id = null, metadata = ?,
                       revision = revision + 1, updated_at = ?
                 where id = ?
                """,
                (
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    now_iso(),
                    connector_id,
                ),
            )

    def _revoke_secrets(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            secret_id = str(row["id"])
            self.database.execute(
                """
                update platform_secret_version
                   set status = 'disabled'
                 where secret_id = ? and status in ('active', 'staged')
                """,
                (secret_id,),
            )
            self.database.execute(
                """
                update platform_secret
                   set status = 'disabled', revision = revision + 1,
                       updated_at = ?
                 where id = ?
                """,
                (now_iso(), secret_id),
            )

    def _deactivate_deployments(self, deployment_ids: set[str]) -> None:
        if not deployment_ids:
            return
        placeholders = self._placeholders(deployment_ids)
        self.database.execute(
            f"""
            update business_application_deployment
               set active = 0, deactivated_by = 'dingtalk-test-data-rebuild',
                   deactivated_at = ?, revision = revision + 1,
                   updated_at = ?
             where id in ({placeholders}) and active = 1
            """,
            (now_iso(), now_iso(), *sorted(deployment_ids)),
        )

    def _dedicated_secrets(
        self,
        *,
        connector_refs: set[str],
        target_connector_ids: set[str],
    ) -> list[dict[str, Any]]:
        rows = self._by_values(
            """
            select id, code, ref, purpose, status, revision, metadata_json
              from platform_secret
             where ref in ({placeholders})
             order by id
            """,
            connector_refs,
        )
        dedicated: list[dict[str, Any]] = []
        for row in rows:
            metadata = self._json_object(row.get("metadata_json") or "{}")
            if (
                str(row.get("purpose") or "") != "dingtalk_stream_client_secret"
                or str(metadata.get("managed_by") or "") != "managed_channel"
            ):
                continue
            non_target = self.database.execute_one(
                """
                select id from integration_connector
                 where secret_ref = ? and id not in ({placeholders})
                 limit 1
                """.format(placeholders=self._placeholders(target_connector_ids)),
                (str(row["ref"]), *sorted(target_connector_ids)),
            )
            if non_target is None:
                dedicated.append(row)
        return dedicated

    def _governance_audits(
        self,
        *,
        connector_ids: set[str],
        enterprise_ids: set[str],
    ) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select id, event_type, status, payload_summary
              from audit_event
             where event_type like ?
                or event_type like ?
             order by id
            """,
            ("managed_channel.%", "dingtalk_enterprise.%"),
        )
        selected: list[dict[str, Any]] = []
        for row in rows:
            payload = self._json_object(row.get("payload_summary") or "{}")
            if (
                str(payload.get("connector_id") or "") in connector_ids
                or str(payload.get("dingtalk_enterprise_id") or "") in enterprise_ids
            ):
                selected.append(row)
        return selected

    def _historical_references(self, connector_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
        revision_triggers = self._by_values(
            """
            select t.id, t.connector_id, t.revision_id,
                   r.application_id, r.revision
              from business_application_revision_trigger t
              join business_application_revision r on r.id = t.revision_id
             where t.connector_id in ({placeholders})
             order by t.id
            """,
            connector_ids,
        )
        revision_deliveries = self._by_values(
            """
            select d.id, d.connector_id, d.revision_id,
                   r.application_id, r.revision
              from business_application_revision_delivery d
              join business_application_revision r on r.id = d.revision_id
             where d.connector_id in ({placeholders})
             order by d.id
            """,
            connector_ids,
        )
        agent_bindings = self._by_values(
            """
            select id, publication_id, direction, connector_id
              from agent_channel_binding
             where connector_id in ({placeholders})
             order by id
            """,
            connector_ids,
        )
        return {
            "application_revision_triggers": revision_triggers,
            "application_revision_deliveries": revision_deliveries,
            "agent_publication_channel_bindings": agent_bindings,
        }

    def _protected_blockers(
        self,
        *,
        identity_ids: set[str],
        audit_ids: set[str],
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        del identity_ids
        audit_refs = self._by_values(
            """
            select id, audit_id
              from agent_tool_call
             where audit_id in ({placeholders})
             order by id
            """,
            audit_ids,
        )
        blockers.extend(
            {"type": "agent_tool_call_audit", "id": str(row["id"])} for row in audit_refs
        )
        return blockers

    def _write_stop_evidence(self) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        active_leases = self.database.execute(
            """
            select lease_name as id, runtime_id, expires_at
              from channel_runtime_lease
             where lower(lease_name) like ?
               and expires_at > ?
             order by lease_name
            """,
            ("dingtalk%", now),
        )
        active_outbox = self.database.execute(
            """
            select o.id, o.status
              from channel_ingress_outbox o
              join channel_ingress_event e on e.id = o.channel_event_id
              join integration_connector c on c.id = e.connector_id
             where c.connector_type = 'dingtalk_enterprise_stream'
               and o.status = 'publishing'
             order by o.id
            """
        )
        dispatching_events = self.database.execute(
            """
            select e.id, e.status
              from channel_ingress_event e
              join integration_connector c on c.id = e.connector_id
             where c.connector_type = 'dingtalk_enterprise_stream'
               and e.status = 'DISPATCHING'
             order by e.id
            """
        )
        return {
            "active_runtime_leases": self._safe_rows(
                active_leases, ("id", "runtime_id", "expires_at")
            ),
            "publishing_ingress_outbox": self._safe_rows(active_outbox, ("id", "status")),
            "dispatching_ingress_events": self._safe_rows(dispatching_events, ("id", "status")),
            "safe_to_apply": not (active_leases or active_outbox or dispatching_events),
        }

    def _protected_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for name, sql in PROTECTED_COUNT_QUERIES.items():
            row = self.database.execute_one(sql)
            counts[name] = int((row or {}).get("count") or 0)
        return counts

    def _record_audit(
        self,
        *,
        actor_id: str,
        plan_hash: str,
        backup_reference: str,
        counts: dict[str, int],
    ) -> None:
        self.database.execute(
            """
            insert into audit_event
              (id, job_id, event_type, actor_id, status, summary,
               payload_summary, created_at)
            values (?, null, 'dingtalk_test_data_rebuild.applied', ?,
                    'SUCCEEDED', 'DingTalk test data rebuild applied', ?, ?)
            """,
            (
                new_id("audit"),
                actor_id,
                json.dumps(
                    {
                        "plan_hash": plan_hash,
                        "backup_reference_digest": self._digest(backup_reference),
                        "counts": counts,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now_iso(),
            ),
        )

    def _schema_head(self) -> str:
        row = self.database.execute_one("select version from schema_migration limit 1")
        return str((row or {}).get("version") or "")

    def _database_locator_hash(self) -> str:
        dsn = str(self.database.dsn)
        if "://" in dsn:
            scheme, remainder = dsn.split("://", 1)
            locator = remainder.rsplit("@", 1)[-1]
            safe_locator = f"{scheme}://{locator}"
        else:
            safe_locator = dsn
        return self._digest(safe_locator)

    def _lock_write_tables(self) -> None:
        if self.database.engine != "postgres":
            return
        self.database.execute(
            """
            lock table channel_runtime_lease, channel_connector_runtime,
                       channel_ingress_event, channel_ingress_outbox,
                       dingtalk_identity_candidate,
                       dingtalk_identity_candidate_message,
                       user_external_identity,
                       dingtalk_identity_application_observation,
                       dingtalk_identity_nickname_audit,
                       integration_connector,
                       business_application_active_route,
                       business_application_deployment,
                       dingtalk_enterprise
              in access exclusive mode
            """
        )

    def _require_non_production(self) -> None:
        if self.environment not in NON_PRODUCTION_ENVIRONMENTS:
            raise NonRetryableExecutionError(
                "DingTalk test data rebuild requires an explicit non-production environment",
                safe_message="仅明确标记为本机、测试、开发、预发布或 QA 的环境允许运行钉钉测试数据重建命令",
                error_code="dingtalk_rebuild_production_forbidden",
            )

    def _delete_ids(
        self,
        table: str,
        ids: set[str],
        *,
        id_column: str = "id",
    ) -> None:
        if not ids:
            return
        self.database.execute(
            f"delete from {table} where {id_column} in ({self._placeholders(ids)})",
            tuple(sorted(ids)),
        )

    def _by_values(self, sql: str, values: Iterable[str]) -> list[dict[str, Any]]:
        normalized = sorted({str(value) for value in values if str(value)})
        if not normalized:
            return []
        return self.database.execute(
            sql.format(placeholders=self._placeholders(normalized)),
            tuple(normalized),
        )

    @staticmethod
    def _target_ids(targets: dict[str, list[dict[str, Any]]], name: str) -> set[str]:
        return {str(row["id"]) for row in targets.get(name, [])}

    @staticmethod
    def _placeholders(values: Iterable[object]) -> str:
        return ", ".join("?" for _ in values)

    @staticmethod
    def _safe_row(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
        return {field: row.get(field) for field in fields}

    def _safe_rows(
        self, rows: Iterable[dict[str, Any]], fields: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        return [self._safe_row(row, fields) for row in rows]

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _digest(value: Any) -> str:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _before_step(self, step: str) -> None:
        del step


__all__ = [
    "CONFIRMATION_TEXT",
    "DingTalkTestDataRebuildService",
]
