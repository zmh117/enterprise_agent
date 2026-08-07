from __future__ import annotations

import json
from typing import Any

from app.modules.internal_tools.application.legacy_migration import (
    MIGRATION_VERSION,
    BuiltinToolLegacyMigrationService,
)
from app.modules.platform_config.infrastructure.repository import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError


class BuiltinToolLegacyPublicationMigrator:
    """Create exact replacement Publications without modifying legacy history."""

    def __init__(
        self,
        database: Database,
        *,
        agent_config_service: Any,
        business_application_service: Any,
    ) -> None:
        self.database = database
        self.agent_config_service = agent_config_service
        self.business_application_service = business_application_service
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
        publication_items = [
            item
            for item in report["details"]
            if item["source_type"]
            in {"AGENT_PUBLICATION", "APPLICATION_PUBLICATION"}
        ]
        selected = publication_items[:source_limit]
        migrated: list[dict[str, str]] = []
        blocked: list[dict[str, str]] = []

        for source_type in ("AGENT_PUBLICATION", "APPLICATION_PUBLICATION"):
            for item in selected:
                if item["source_type"] != source_type:
                    continue
                if item["candidate_class"] != "ONE":
                    blocked.append(self._blocked_result(item))
                    continue
                try:
                    if source_type == "AGENT_PUBLICATION":
                        migrated.append(
                            self._migrate_agent(
                                item,
                                actor_id=actor_id,
                                correlation_id=correlation_id,
                            )
                        )
                    else:
                        migrated.append(
                            self._migrate_application(
                                item,
                                actor_id=actor_id,
                                correlation_id=correlation_id,
                            )
                        )
                except NonRetryableExecutionError as exc:
                    blocked.append(
                        {
                            "source_type": source_type,
                            "source_id": str(item["source_id"]),
                            "reason_code": (
                                exc.error_code
                                or "builtin_tool_publication_migration_failed"
                            ),
                        }
                    )
                except Exception:
                    blocked.append(
                        {
                            "source_type": source_type,
                            "source_id": str(item["source_id"]),
                            "reason_code": "builtin_tool_publication_migration_failed",
                        }
                    )

        return {
            "schema_version": 1,
            "migration_version": MIGRATION_VERSION,
            "mode": "publication_migration",
            "migrated": migrated,
            "blocked": blocked,
            "migrated_count": len(migrated),
            "blocked_count": len(blocked),
            "source_count": len(publication_items),
            "source_limit": source_limit,
            "sources_truncated": len(publication_items) > source_limit,
            "safe_fields_only": True,
        }

    def _migrate_agent(
        self,
        item: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, str]:
        source_id = str(item["source_id"])
        existing = self._materialized(source_type="AGENT_PUBLICATION", source_id=source_id)
        if existing:
            return existing
        with self.database.unit_of_work():
            source = self.agent_config_service.publication(source_id)
            definition = self.agent_config_service.repository.get_definition_by_id(
                str(source["agent_id"])
            )
            if str(definition.get("current_publication_id") or "") != source_id:
                raise NonRetryableExecutionError(
                    "Legacy Agent publication is no longer current",
                    safe_message="旧 Agent 发布版本已不再活动，请重新生成迁移报告",
                    error_code="builtin_tool_legacy_source_not_active",
                )
            release_ids = self._release_ids(item)
            config = self._agent_config(source, release_ids=release_ids)
            latest = self.agent_config_service.repository.latest_revision(
                str(source["agent_id"])
            )
            if latest is None:
                raise NonRetryableExecutionError(
                    "Agent revision is missing",
                    safe_message="旧 Agent 修订版本缺失",
                    error_code="builtin_tool_legacy_source_missing",
                )
            revision = self.agent_config_service.save_draft(
                actor_id=actor_id,
                agent_code=str(definition["code"]),
                expected_revision=int(latest["revision"]),
                config=config,
                correlation_id=correlation_id,
            )
            target = self.agent_config_service.publish(
                actor_id=actor_id,
                agent_code=str(definition["code"]),
                revision_id=str(revision["id"]),
                correlation_id=correlation_id,
            )
            self._record_materialized(
                item,
                snapshot_hash=str(target["config_hash"]),
                correlation_id=correlation_id,
                evidence={
                    "target_publication_id": str(target["id"]),
                    "target_revision_id": str(target["revision_id"]),
                    "tool_release_ids": release_ids,
                },
            )
        return {
            "source_type": "AGENT_PUBLICATION",
            "source_id": source_id,
            "target_publication_id": str(target["id"]),
        }

    def _migrate_application(
        self,
        item: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, str]:
        source_id = str(item["source_id"])
        existing = self._materialized(
            source_type="APPLICATION_PUBLICATION",
            source_id=source_id,
        )
        if existing:
            return existing
        target_agent_id = self._target_agent_publication(
            str(item["agent_publication_id"]),
            expected_release_ids=self._release_ids(item),
        )
        with self.database.unit_of_work():
            source = self.business_application_service.repository.get_publication(
                source_id
            )
            revision = self.business_application_service.repository.get_revision(
                str(source["revision_id"])
            )
            application = self.business_application_service.repository.get_by_id(
                str(source["application_id"])
            )
            deployments = [
                deployment
                for deployment in application.get("deployments") or []
                if bool(deployment.get("active"))
                and str(deployment.get("publication_id") or "") == source_id
            ]
            if not deployments:
                raise NonRetryableExecutionError(
                    "Legacy Application publication is no longer active",
                    safe_message="旧业务应用发布版本已不再活动，请重新生成迁移报告",
                    error_code="builtin_tool_legacy_source_not_active",
                )
            payload = self._application_payload(
                revision,
                target_agent_publication_id=target_agent_id,
                release_ids=self._release_ids(item),
            )
            target_revision = self.business_application_service.save_draft(
                actor_id=actor_id,
                code=str(application["code"]),
                expected_revision=int(application["revision"]),
                payload=payload,
            )
            target = self.business_application_service.publish(
                actor_id=actor_id,
                code=str(application["code"]),
                revision_id=str(target_revision["id"]),
                correlation_id=correlation_id,
            )
            for deployment in deployments:
                self.business_application_service.activate(
                    actor_id=actor_id,
                    code=str(application["code"]),
                    environment=str(deployment["environment"]),
                    publication_id=str(target["id"]),
                    expected_revision=int(deployment["revision"]),
                )
            self._record_materialized(
                item,
                snapshot_hash=str(target["config_hash"]),
                correlation_id=correlation_id,
                evidence={
                    "target_publication_id": str(target["id"]),
                    "target_revision_id": str(target["revision_id"]),
                    "target_agent_publication_id": target_agent_id,
                    "deployment_count": len(deployments),
                    "tool_release_ids": self._release_ids(item),
                },
            )
        return {
            "source_type": "APPLICATION_PUBLICATION",
            "source_id": source_id,
            "target_publication_id": str(target["id"]),
        }

    def _agent_config(
        self,
        source: dict[str, Any],
        *,
        release_ids: list[str],
    ) -> dict[str, Any]:
        snapshot = dict(source.get("snapshot") or {})
        model_policy = dict(snapshot.get("model_policy") or {})
        frozen_connection = dict(snapshot.get("model_connection") or {})
        if not model_policy.get("model_connection_revision_id") and frozen_connection:
            model_policy["model_connection_revision_id"] = str(
                frozen_connection.get("revision_id") or ""
            )
        capability_release_ids = [
            str(row["capability_release_id"])
            for row in self.database.execute(
                """
                select capability_release_id
                  from agent_publication_api_capability
                 where agent_publication_id = ?
                 order by binding_order
                """,
                (str(source["id"]),),
            )
        ]
        return {
            "business_role": str(snapshot.get("business_role") or ""),
            "business_instructions": str(
                snapshot.get("business_instructions") or ""
            ),
            "model_policy": model_policy,
            "execution": dict(snapshot.get("execution") or {}),
            "tools": [],
            "skills": list(snapshot.get("skills") or []),
            "routing": dict(snapshot.get("routing") or {}),
            "channels": dict(snapshot.get("channels") or {}),
            "api_capability_release_ids": capability_release_ids,
            "builtin_tool_release_ids": release_ids,
        }

    @staticmethod
    def _application_payload(
        revision: dict[str, Any],
        *,
        target_agent_publication_id: str,
        release_ids: list[str],
    ) -> dict[str, Any]:
        return {
            "agent_publication_id": target_agent_publication_id,
            "workflow_publication_id": str(
                revision.get("workflow_publication_id") or ""
            ),
            "session_policy": dict(revision.get("session_policy") or {}),
            "execution_policy": dict(revision.get("execution_policy") or {}),
            "triggers": [
                {
                    key: trigger.get(key)
                    for key in (
                        "trigger_type",
                        "connector_id",
                        "routing_key",
                        "actor_policy",
                        "service_account_user_id",
                        "enabled",
                        "config",
                    )
                }
                for trigger in revision.get("triggers") or []
            ],
            "deliveries": [
                {
                    key: delivery.get(key)
                    for key in (
                        "delivery_type",
                        "connector_id",
                        "enabled",
                        "config",
                    )
                }
                for delivery in revision.get("deliveries") or []
            ],
            "capabilities": [
                {
                    key: capability.get(key)
                    for key in (
                        "capability_code",
                        "version_constraint",
                        "enabled",
                    )
                }
                for capability in revision.get("capabilities") or []
            ],
            "api_capability_release_ids": list(
                revision.get("api_capability_release_ids") or []
            ),
            "builtin_tools": [
                {"tool_release_id": release_id, "resources": []}
                for release_id in release_ids
            ],
            "target_paths": [
                {
                    "target_scope_type": str(target["target_scope_type"]),
                    "environment_code": str(target["environment_code"]),
                    "base_code": str(target.get("base_code") or ""),
                    "workshop_code": str(target.get("workshop_code") or ""),
                }
                for target in revision.get("target_paths") or []
            ],
        }

    def _target_agent_publication(
        self,
        source_agent_publication_id: str,
        *,
        expected_release_ids: list[str],
    ) -> str:
        migrated = self._materialized_row(
            source_type="AGENT_PUBLICATION",
            source_id=source_agent_publication_id,
        )
        if migrated is None:
            raise NonRetryableExecutionError(
                "Legacy Agent publication has not been migrated",
                safe_message="请先迁移业务应用引用的旧 Agent 发布版本",
                error_code="builtin_tool_agent_publication_migration_missing",
            )
        evidence = self._evidence(migrated)
        target_id = str(evidence.get("target_publication_id") or "")
        actual_release_ids = sorted(
            str(row["tool_release_id"])
            for row in self.database.execute(
                """
                select tool_release_id
                 from agent_publication_builtin_tool
                 where agent_publication_id = ?
                 order by tool_identifier
                """,
                (target_id,),
            )
        )
        if not target_id or actual_release_ids != expected_release_ids:
            raise NonRetryableExecutionError(
                "Migrated Agent publication does not match the legacy candidate set",
                safe_message="迁移后的 Agent 精确工具集合与预检结果不一致",
                error_code="builtin_tool_agent_publication_migration_mismatch",
            )
        return target_id

    def _record_materialized(
        self,
        item: dict[str, Any],
        *,
        snapshot_hash: str,
        correlation_id: str,
        evidence: dict[str, Any],
    ) -> None:
        timestamp = now_iso()
        self.database.execute(
            """
            insert into builtin_tool_legacy_migration
              (id, source_type, source_id, migration_version,
               candidate_class, candidate_count, status,
               quarantine_reason_code, snapshot_hash, evidence_summary_json,
               correlation_id, created_at, updated_at)
            values (?, ?, ?, ?, 'ONE', 1, 'MATERIALIZED', '', ?, ?, ?, ?, ?)
            on conflict(source_type, source_id, migration_version) do nothing
            """,
            (
                new_id("builtin_tool_legacy_migration"),
                str(item["source_type"]),
                str(item["source_id"]),
                MIGRATION_VERSION,
                snapshot_hash,
                json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                correlation_id,
                timestamp,
                timestamp,
            ),
        )
        persisted = self._materialized_row(
            source_type=str(item["source_type"]),
            source_id=str(item["source_id"]),
        )
        if persisted is None or str(persisted.get("snapshot_hash") or "") != snapshot_hash:
            raise NonRetryableExecutionError(
                "Legacy publication migration ledger conflict",
                safe_message="迁移账本与本次结果不一致，请停止并检查",
                error_code="builtin_tool_legacy_migration_conflict",
            )

    def _materialized(
        self,
        *,
        source_type: str,
        source_id: str,
    ) -> dict[str, str] | None:
        row = self._materialized_row(
            source_type=source_type,
            source_id=source_id,
        )
        if row is None:
            return None
        target_id = str(self._evidence(row).get("target_publication_id") or "")
        if not target_id:
            raise NonRetryableExecutionError(
                "Legacy publication migration evidence is incomplete",
                safe_message="迁移账本证据不完整，请停止并检查",
                error_code="builtin_tool_legacy_migration_conflict",
            )
        return {
            "source_type": source_type,
            "source_id": source_id,
            "target_publication_id": target_id,
        }

    def _materialized_row(
        self,
        *,
        source_type: str,
        source_id: str,
    ) -> dict[str, Any] | None:
        return self.database.execute_one(
            """
            select *
              from builtin_tool_legacy_migration
             where source_type = ? and source_id = ?
               and migration_version = ? and status = 'MATERIALIZED'
            """,
            (source_type, source_id, MIGRATION_VERSION),
        )

    @staticmethod
    def _evidence(row: dict[str, Any]) -> dict[str, Any]:
        try:
            value = json.loads(str(row.get("evidence_summary_json") or "{}"))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _release_ids(item: dict[str, Any]) -> list[str]:
        return sorted(
            str(release_id)
            for candidate in item.get("tool_candidates") or []
            for release_id in candidate.get("tool_release_ids") or []
        )

    @staticmethod
    def _blocked_result(item: dict[str, Any]) -> dict[str, str]:
        return {
            "source_type": str(item["source_type"]),
            "source_id": str(item["source_id"]),
            "reason_code": str(item.get("reason_code") or "")
            or "builtin_tool_legacy_resolution_missing",
        }
