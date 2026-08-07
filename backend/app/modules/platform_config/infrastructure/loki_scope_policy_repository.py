from __future__ import annotations

import json
from typing import Any

from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound

from .repository import json_text, new_id, now_iso


class LokiScopePolicyRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        *,
        code: str,
        environment_id: str,
        base_id: str | None,
        draft: dict[str, Any],
        content_hash: str,
        actor_id: str,
    ) -> dict[str, Any]:
        policy_id = new_id("loki_scope_policy")
        timestamp = now_iso()
        try:
            self.database.execute(
                """
                insert into loki_scope_policy
                  (id, code, environment_id, base_id, status, revision,
                   created_by, created_at, updated_at)
                values (?, ?, ?, ?, 'enabled', 1, ?, ?, ?)
                """,
                (
                    policy_id,
                    code,
                    environment_id,
                    base_id,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
            self._insert_draft(
                policy_id=policy_id,
                draft_revision=1,
                draft=draft,
                content_hash=content_hash,
                actor_id=actor_id,
                timestamp=timestamp,
            )
        except Exception as exc:
            raise NonRetryableExecutionError(
                "Loki Scope Policy identity conflicts with existing data",
                safe_message="Loki 范围策略编码冲突或目标无效",
                error_code="loki_scope_policy_conflict",
            ) from exc
        return self.get_by_code(code)

    def get_by_code(self, code: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select policy.*, environment.code as environment_code,
                   base.code as base_code
              from loki_scope_policy policy
              join platform_environment environment
                on environment.id = policy.environment_id
              left join platform_base base on base.id = policy.base_id
             where policy.code = ?
            """,
            (code,),
        )
        if row is None:
            raise NotFound(
                f"Loki Scope Policy not found: {code}",
                safe_message="未找到 Loki 范围策略",
            )
        return {**row, "revision": int(row["revision"])}

    def list_policies(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select policy.*, environment.code as environment_code,
                   base.code as base_code
              from loki_scope_policy policy
              join platform_environment environment
                on environment.id = policy.environment_id
              left join platform_base base on base.id = policy.base_id
             order by environment.code, base.code, policy.code
            """
        )
        relations = self.database.execute(
            """
            select draft.policy_id, revision.resource_id,
                   draft.resource_revision_id, 0 as policy_revision,
                   'draft' as relation_kind
              from loki_scope_policy_draft draft
              join platform_resource_revision revision
                on revision.id = draft.resource_revision_id
            union all
            select published.policy_id, revision.resource_id,
                   published.resource_revision_id,
                   published.revision as policy_revision,
                   'published' as relation_kind
              from loki_scope_policy_revision published
              join platform_resource_revision revision
                on revision.id = published.resource_revision_id
            """
        )
        by_policy: dict[str, dict[str, Any]] = {}
        for relation in relations:
            policy_id = str(relation["policy_id"])
            summary = by_policy.setdefault(
                policy_id,
                {
                    "resource_ids": set(),
                    "draft_resource_revision_id": "",
                    "published_resource_revision_id": "",
                    "published_policy_revision": 0,
                },
            )
            summary["resource_ids"].add(str(relation["resource_id"]))
            if str(relation["relation_kind"]) == "draft":
                summary["draft_resource_revision_id"] = str(
                    relation["resource_revision_id"]
                )
                continue
            policy_revision = int(relation["policy_revision"])
            if policy_revision > int(summary["published_policy_revision"]):
                summary["published_policy_revision"] = policy_revision
                summary["published_resource_revision_id"] = str(
                    relation["resource_revision_id"]
                )
        result: list[dict[str, Any]] = []
        for row in rows:
            summary = by_policy.get(
                str(row["id"]),
                {
                    "resource_ids": set(),
                    "draft_resource_revision_id": "",
                    "published_resource_revision_id": "",
                    "published_policy_revision": 0,
                },
            )
            result.append(
                {
                    **row,
                    "revision": int(row["revision"]),
                    **summary,
                    "resource_ids": sorted(summary["resource_ids"]),
                }
            )
        return result

    def get_draft(self, policy_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select draft.*, revision.resource_id,
                   resource.code as resource_code,
                   revision.revision as resource_revision
              from loki_scope_policy_draft draft
              join platform_resource_revision revision
                on revision.id = draft.resource_revision_id
              join platform_resource resource
                on resource.id = revision.resource_id
             where draft.policy_id = ?
            """,
            (policy_id,),
        )
        return self._draft(row) if row else None

    def replace_draft(
        self,
        *,
        policy_id: str,
        expected_draft_revision: int,
        draft: dict[str, Any],
        content_hash: str,
        actor_id: str,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update loki_scope_policy_draft
               set draft_revision = ?, resource_revision_id = ?,
                   content_hash = ?, status = 'DRAFT', updated_by = ?,
                   updated_at = ?
             where policy_id = ? and draft_revision = ?
            returning policy_id
            """,
            (
                expected_draft_revision + 1,
                draft["resource_revision_id"],
                content_hash,
                actor_id,
                timestamp,
                policy_id,
                expected_draft_revision,
            ),
        )
        if not rows:
            raise self._revision_conflict()
        self.database.execute(
            "delete from loki_scope_policy_draft_condition where policy_id = ?",
            (policy_id,),
        )
        self._insert_conditions(
            "loki_scope_policy_draft_condition",
            "policy_id",
            policy_id,
            draft["conditions"],
        )
        result = self.get_draft(policy_id)
        assert result is not None
        return result

    def insert_verification(
        self,
        *,
        policy_id: str,
        draft_revision: int,
        resource_revision_id: str,
        content_hash: str,
        verifier_version: str,
        status: str,
        match_count: int,
        truncated: bool,
        zero_match_warning: bool,
        result_summary: dict[str, Any],
        safe_error_summary: str,
        actor_id: str,
    ) -> dict[str, Any]:
        existing = self.database.execute_one(
            """
            select id from loki_scope_policy_verification
             where policy_id = ? and draft_revision = ? and resource_revision_id = ?
               and content_hash = ? and verifier_version = ?
            """,
            (
                policy_id,
                draft_revision,
                resource_revision_id,
                content_hash,
                verifier_version,
            ),
        )
        verification_id = str(existing["id"]) if existing else new_id("loki_scope_verification")
        timestamp = now_iso()
        if existing:
            self.database.execute(
                """
                update loki_scope_policy_verification
                   set status = ?, match_count = ?, truncated = ?,
                       zero_match_warning = ?, result_summary_json = ?,
                       safe_error_summary = ?, verified_by = ?, verified_at = ?
                 where id = ?
                """,
                (
                    status,
                    match_count,
                    int(truncated),
                    int(zero_match_warning),
                    json_text(result_summary),
                    safe_error_summary,
                    actor_id,
                    timestamp,
                    verification_id,
                ),
            )
        else:
            self.database.execute(
                """
                insert into loki_scope_policy_verification
                  (id, policy_id, draft_revision, resource_revision_id, content_hash,
                   verifier_version, status, match_count, truncated,
                   zero_match_warning, result_summary_json,
                   safe_error_summary, verified_by, verified_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verification_id,
                    policy_id,
                    draft_revision,
                    resource_revision_id,
                    content_hash,
                    verifier_version,
                    status,
                    match_count,
                    int(truncated),
                    int(zero_match_warning),
                    json_text(result_summary),
                    safe_error_summary,
                    actor_id,
                    timestamp,
                ),
            )
        rows = self.database.execute(
            """
            update loki_scope_policy_draft
               set status = ?, updated_by = ?, updated_at = ?
             where policy_id = ? and resource_revision_id = ?
               and draft_revision = ? and content_hash = ?
            returning policy_id
            """,
            (
                "VERIFIED" if status == "PASSED" else "DRAFT",
                actor_id,
                timestamp,
                policy_id,
                resource_revision_id,
                draft_revision,
                content_hash,
            ),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Loki Scope Policy Draft changed during verification",
                safe_message="Loki 范围策略草稿已变化，请重新验证",
                error_code="loki_scope_policy_verification_stale",
            )
        return self.get_verification(verification_id)

    def get_verification(self, verification_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from loki_scope_policy_verification where id = ?",
            (verification_id,),
        )
        if row is None:
            raise NotFound(
                f"Loki Scope Policy verification not found: {verification_id}",
                safe_message="未找到 Loki 范围策略验证证据",
            )
        return self._verification(row)

    def find_revision_by_verification(self, verification_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            "select * from loki_scope_policy_revision where verification_id = ?",
            (verification_id,),
        )
        return self._revision(row) if row else None

    def publish(
        self,
        *,
        policy: dict[str, Any],
        draft: dict[str, Any],
        verification: dict[str, Any],
        expected_policy_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        existing = self.find_revision_by_verification(str(verification["id"]))
        if existing is not None:
            return existing
        if int(policy["revision"]) != expected_policy_revision:
            raise self._revision_conflict()
        maximum = self.database.execute_one(
            "select coalesce(max(revision), 0) as revision from loki_scope_policy_revision where policy_id = ?",
            (policy["id"],),
        )
        revision_number = int(maximum["revision"] if maximum else 0) + 1
        revision_id = new_id("loki_scope_revision")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into loki_scope_policy_revision
              (id, policy_id, revision, resource_revision_id, content_hash,
               verification_id, status, health_status, published_by,
               published_at)
            values (?, ?, ?, ?, ?, ?, 'PUBLISHED', ?, ?, ?)
            """,
            (
                revision_id,
                policy["id"],
                revision_number,
                draft["resource_revision_id"],
                draft["content_hash"],
                verification["id"],
                "EMPTY" if verification["zero_match_warning"] else "HEALTHY",
                actor_id,
                timestamp,
            ),
        )
        self._insert_conditions(
            "loki_scope_policy_revision_condition",
            "policy_revision_id",
            revision_id,
            draft["conditions"],
        )
        rows = self.database.execute(
            """
            update loki_scope_policy set revision = ?, updated_at = ?
             where id = ? and revision = ?
            returning id
            """,
            (
                revision_number,
                timestamp,
                policy["id"],
                expected_policy_revision,
            ),
        )
        if not rows:
            raise self._revision_conflict()
        self.database.execute(
            "delete from loki_scope_policy_draft where policy_id = ?",
            (policy["id"],),
        )
        return self.get_revision(revision_id)

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select published.*, resource_revision.resource_id,
                   resource.code as resource_code,
                   resource_revision.revision as resource_revision
              from loki_scope_policy_revision published
              join platform_resource_revision resource_revision
                on resource_revision.id = published.resource_revision_id
              join platform_resource resource
                on resource.id = resource_revision.resource_id
             where published.id = ?
            """,
            (revision_id,),
        )
        if row is None:
            raise NotFound(
                f"Loki Scope Policy Revision not found: {revision_id}",
                safe_message="未找到 Loki 范围策略发布版本",
            )
        return self._revision(row)

    def list_revisions(self, policy_id: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select published.*, resource_revision.resource_id,
                   resource.code as resource_code,
                   resource_revision.revision as resource_revision
              from loki_scope_policy_revision published
              join platform_resource_revision resource_revision
                on resource_revision.id = published.resource_revision_id
              join platform_resource resource
                on resource.id = resource_revision.resource_id
             where published.policy_id = ?
             order by published.revision desc
            """,
            (policy_id,),
        )
        return [self._revision(row) for row in rows]

    def list_application_usages(self, policy_id: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select distinct policy_revision.id as policy_revision_id,
                   policy_revision.revision as policy_revision,
                   application.id as application_id,
                   application.code as application_code,
                   application.name as application_name,
                   publication.id as application_publication_id,
                   publication.revision as application_publication_revision,
                   binding.resource_slot, binding.target_key,
                   coalesce(deployment.environment, '') as deployment_environment,
                   coalesce(deployment.active, 0) as active
              from loki_scope_policy_revision policy_revision
              join business_application_publication_builtin_tool_resource binding
                on binding.loki_scope_policy_revision_id = policy_revision.id
              join business_application_publication_builtin_tool tool
                on tool.id = binding.application_tool_id
              join business_application_publication publication
                on publication.id = tool.application_publication_id
              join business_application application
                on application.id = publication.application_id
             left join business_application_deployment deployment
                on deployment.publication_id = publication.id
             where policy_revision.policy_id = ?
             order by application_code, application_publication_revision,
                      policy_revision, resource_slot, target_key,
                      deployment_environment
            """,
            (policy_id,),
        )
        return [
            {
                **row,
                "policy_revision": int(row["policy_revision"]),
                "application_publication_revision": int(
                    row["application_publication_revision"]
                ),
                "active": bool(row["active"]),
            }
            for row in rows
        ]

    def record_health_observation(
        self,
        *,
        policy_revision_id: str,
        health_status: str,
        match_count: int,
        truncated: bool,
        result_summary: dict[str, Any],
        safe_error_summary: str,
        actor_id: str,
    ) -> dict[str, Any]:
        observation_id = new_id("loki_scope_health")
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update loki_scope_policy_revision
               set health_status = ?
             where id = ? and status = 'PUBLISHED'
            returning id
            """,
            (health_status, policy_revision_id),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Loki Scope Policy Revision is not Published",
                safe_message="Loki 范围策略发布版本不可执行健康探测",
                error_code="loki_scope_policy_health_unavailable",
            )
        self.database.execute(
            """
            insert into loki_scope_policy_health_observation
              (id, policy_revision_id, health_status, match_count, truncated,
               result_summary_json, safe_error_summary, observed_by,
               observed_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation_id,
                policy_revision_id,
                health_status,
                match_count,
                int(truncated),
                json_text(result_summary),
                safe_error_summary,
                actor_id,
                timestamp,
            ),
        )
        return self.get_health_observation(observation_id)

    def get_health_observation(self, observation_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from loki_scope_policy_health_observation where id = ?",
            (observation_id,),
        )
        if row is None:
            raise NotFound(
                f"Loki Scope Policy health observation not found: {observation_id}",
                safe_message="未找到 Loki 范围策略健康观测",
            )
        return {
            **row,
            "match_count": int(row["match_count"]),
            "truncated": bool(row["truncated"]),
            "result_summary": json.loads(row["result_summary_json"] or "{}"),
        }

    def copy_revision_to_draft(
        self,
        *,
        policy: dict[str, Any],
        draft: dict[str, Any],
        content_hash: str,
        expected_policy_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        if int(policy["revision"]) != expected_policy_revision:
            raise self._revision_conflict()
        if self.get_draft(str(policy["id"])) is not None:
            raise NonRetryableExecutionError(
                "Loki Scope Policy already has a Draft",
                safe_message="该 Loki 范围策略已有可编辑草稿",
                error_code="loki_scope_policy_conflict",
            )
        maximum = self.database.execute_one(
            "select coalesce(max(draft_revision), 0) as draft_revision from loki_scope_policy_verification where policy_id = ?",
            (policy["id"],),
        )
        draft_revision = int(maximum["draft_revision"] if maximum else 0) + 1
        self._insert_draft(
            policy_id=str(policy["id"]),
            draft_revision=draft_revision,
            draft=draft,
            content_hash=content_hash,
            actor_id=actor_id,
            timestamp=now_iso(),
        )
        result = self.get_draft(str(policy["id"]))
        assert result is not None
        return result

    def _insert_draft(
        self,
        *,
        policy_id: str,
        draft_revision: int,
        draft: dict[str, Any],
        content_hash: str,
        actor_id: str,
        timestamp: str,
    ) -> None:
        self.database.execute(
            """
            insert into loki_scope_policy_draft
              (policy_id, draft_revision, resource_revision_id, content_hash,
               status, updated_by, updated_at)
            values (?, ?, ?, ?, 'DRAFT', ?, ?)
            """,
            (
                policy_id,
                draft_revision,
                draft["resource_revision_id"],
                content_hash,
                actor_id,
                timestamp,
            ),
        )
        self._insert_conditions(
            "loki_scope_policy_draft_condition",
            "policy_id",
            policy_id,
            draft["conditions"],
        )

    def _insert_conditions(
        self,
        table: str,
        owner_column: str,
        owner_id: str,
        conditions: list[dict[str, str]],
    ) -> None:
        if table not in {
            "loki_scope_policy_draft_condition",
            "loki_scope_policy_revision_condition",
        } or owner_column not in {"policy_id", "policy_revision_id"}:
            raise ValueError("Unsupported Loki Scope Policy condition table")
        for position, condition in enumerate(conditions):
            self.database.execute(
                f"""
                insert into {table}
                  ({owner_column}, label_key, label_value, position)
                values (?, ?, ?, ?)
                """,
                (
                    owner_id,
                    condition["key"],
                    condition["value"],
                    position,
                ),
            )

    def _conditions(self, table: str, owner_column: str, owner_id: str) -> list[dict[str, str]]:
        rows = self.database.execute(
            f"select label_key, label_value from {table} where {owner_column} = ? order by position",
            (owner_id,),
        )
        return [{"key": str(row["label_key"]), "value": str(row["label_value"])} for row in rows]

    def _draft(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "draft_revision": int(row["draft_revision"]),
            "conditions": self._conditions(
                "loki_scope_policy_draft_condition",
                "policy_id",
                str(row["policy_id"]),
            ),
        }

    def _revision(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "revision": int(row["revision"]),
            "conditions": self._conditions(
                "loki_scope_policy_revision_condition",
                "policy_revision_id",
                str(row["id"]),
            ),
        }

    @staticmethod
    def _verification(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "match_count": int(row["match_count"]),
            "truncated": bool(row["truncated"]),
            "zero_match_warning": bool(row["zero_match_warning"]),
            "result_summary": json.loads(row["result_summary_json"] or "{}"),
        }

    @staticmethod
    def _revision_conflict() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "Loki Scope Policy revision conflict",
            safe_message="Loki 范围策略已变化，请刷新后重试",
            error_code="loki_scope_policy_revision_conflict",
        )
