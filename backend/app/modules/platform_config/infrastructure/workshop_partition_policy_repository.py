from __future__ import annotations

from typing import Any

from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound

from .repository import json_text, new_id, now_iso


class WorkshopPartitionPolicyRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        *,
        code: str,
        workshop_id: str,
        draft: dict[str, Any],
        content_hash: str,
        actor_id: str,
    ) -> dict[str, Any]:
        policy_id = new_id("workshop_partition_policy")
        timestamp = now_iso()
        try:
            self.database.execute(
                """
                insert into workshop_partition_policy
                  (id, code, workshop_id, status, revision, created_by,
                   created_at, updated_at)
                values (?, ?, ?, 'enabled', 1, ?, ?, ?)
                """,
                (policy_id, code, workshop_id, actor_id, timestamp, timestamp),
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
                "Workshop Partition Policy code or Workshop already exists",
                safe_message="该车间已存在分区策略，或策略编码已被使用",
                error_code="workshop_partition_policy_conflict",
            ) from exc
        return self.get_by_code(code)

    def get_by_code(self, code: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select policy.*, workshop.code as workshop_code,
                   base.code as base_code, environment.code as environment_code
              from workshop_partition_policy policy
              join platform_workshop workshop
                on workshop.id = policy.workshop_id
              join platform_base base on base.id = workshop.base_id
              join platform_environment environment
                on environment.id = base.environment_id
             where policy.code = ?
            """,
            (code,),
        )
        if row is None:
            raise NotFound(
                f"Workshop Partition Policy not found: {code}",
                safe_message="未找到车间分区策略",
            )
        return {**row, "revision": int(row["revision"])}

    def list_policies(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select policy.*, workshop.code as workshop_code,
                   base.code as base_code, environment.code as environment_code
              from workshop_partition_policy policy
              join platform_workshop workshop
                on workshop.id = policy.workshop_id
              join platform_base base on base.id = workshop.base_id
              join platform_environment environment
                on environment.id = base.environment_id
             order by environment.code, base.code, workshop.code
            """
        )
        return [{**row, "revision": int(row["revision"])} for row in rows]

    def get_draft(self, policy_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            "select * from workshop_partition_policy_draft where policy_id = ?",
            (policy_id,),
        )
        if row is None:
            return None
        return self._draft(row)

    def replace_draft(
        self,
        *,
        policy_id: str,
        expected_draft_revision: int,
        draft: dict[str, Any],
        content_hash: str,
        actor_id: str,
    ) -> dict[str, Any]:
        next_revision = expected_draft_revision + 1
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update workshop_partition_policy_draft
               set draft_revision = ?, database_rule_enabled = ?,
                   database_table_prefix = ?, redis_rule_enabled = ?,
                   content_hash = ?, status = 'DRAFT', updated_by = ?,
                   updated_at = ?
             where policy_id = ? and draft_revision = ?
            returning policy_id
            """,
            (
                next_revision,
                int(draft["database_rule_enabled"]),
                draft["database_table_prefix"],
                int(draft["redis_rule_enabled"]),
                content_hash,
                actor_id,
                timestamp,
                policy_id,
                expected_draft_revision,
            ),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Workshop Partition Policy Draft revision conflict",
                safe_message="车间分区策略草稿已变化，请刷新后重试",
                error_code="workshop_partition_policy_revision_conflict",
            )
        self.database.execute(
            "delete from workshop_partition_policy_draft_redis_prefix where policy_id = ?",
            (policy_id,),
        )
        self._insert_draft_prefixes(policy_id, draft["redis_prefixes"])
        result = self.get_draft(policy_id)
        assert result is not None
        return result

    def insert_verification(
        self,
        *,
        policy_id: str,
        draft_revision: int,
        content_hash: str,
        verifier_version: str,
        status: str,
        redis_resource_revision_id: str | None,
        database_summary: dict[str, Any],
        redis_summary: dict[str, Any],
        zero_match_warning: bool,
        safe_error_summary: str,
        actor_id: str,
    ) -> dict[str, Any]:
        existing = self._verification_for_input(
            policy_id=policy_id,
            draft_revision=draft_revision,
            content_hash=content_hash,
            verifier_version=verifier_version,
            redis_resource_revision_id=redis_resource_revision_id,
        )
        timestamp = now_iso()
        if existing is None:
            verification_id = new_id("workshop_partition_verification")
            self.database.execute(
                """
                insert into workshop_partition_policy_verification
                  (id, policy_id, draft_revision, content_hash, verifier_version,
                   redis_resource_revision_id, status, database_summary_json,
                   redis_summary_json, zero_match_warning, safe_error_summary,
                   verified_by, verified_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verification_id,
                    policy_id,
                    draft_revision,
                    content_hash,
                    verifier_version,
                    redis_resource_revision_id,
                    status,
                    json_text(database_summary),
                    json_text(redis_summary),
                    int(zero_match_warning),
                    safe_error_summary,
                    actor_id,
                    timestamp,
                ),
            )
        else:
            verification_id = str(existing["id"])
            self.database.execute(
                """
                update workshop_partition_policy_verification
                   set status = ?, database_summary_json = ?,
                       redis_summary_json = ?, zero_match_warning = ?,
                       safe_error_summary = ?, verified_by = ?, verified_at = ?
                 where id = ?
                """,
                (
                    status,
                    json_text(database_summary),
                    json_text(redis_summary),
                    int(zero_match_warning),
                    safe_error_summary,
                    actor_id,
                    timestamp,
                    verification_id,
                ),
            )
        rows = self.database.execute(
            """
            update workshop_partition_policy_draft
               set status = ?, updated_by = ?, updated_at = ?
             where policy_id = ? and draft_revision = ? and content_hash = ?
            returning policy_id
            """,
            (
                "VERIFIED" if status == "PASSED" else "DRAFT",
                actor_id,
                timestamp,
                policy_id,
                draft_revision,
                content_hash,
            ),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Workshop Partition Policy Draft changed during verification",
                safe_message="车间分区策略草稿已变化，请重新验证",
                error_code="workshop_partition_policy_verification_stale",
            )
        return self.get_verification(verification_id)

    def _verification_for_input(
        self,
        *,
        policy_id: str,
        draft_revision: int,
        content_hash: str,
        verifier_version: str,
        redis_resource_revision_id: str | None,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from workshop_partition_policy_verification
             where policy_id = ? and draft_revision = ? and content_hash = ?
               and verifier_version = ?
               and coalesce(redis_resource_revision_id, '') = ?
             limit 1
            """,
            (
                policy_id,
                draft_revision,
                content_hash,
                verifier_version,
                redis_resource_revision_id or "",
            ),
        )
        return self._verification(row) if row else None

    def matching_verification(
        self,
        *,
        policy_id: str,
        draft_revision: int,
        content_hash: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from workshop_partition_policy_verification
             where policy_id = ? and draft_revision = ? and content_hash = ?
               and status = 'PASSED'
             order by verified_at desc, id desc
             limit 1
            """,
            (policy_id, draft_revision, content_hash),
        )
        return self._verification(row) if row else None

    def get_verification(self, verification_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from workshop_partition_policy_verification where id = ?",
            (verification_id,),
        )
        if row is None:
            raise NotFound(
                f"Workshop Partition Policy verification not found: {verification_id}",
                safe_message="未找到车间分区策略验证证据",
            )
        return self._verification(row)

    def find_revision_by_verification(
        self,
        verification_id: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from workshop_partition_policy_revision
             where verification_id = ?
            """,
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
        if int(policy["revision"]) != expected_policy_revision:
            raise NonRetryableExecutionError(
                "Workshop Partition Policy revision conflict",
                safe_message="车间分区策略已发布新版本，请刷新后重试",
                error_code="workshop_partition_policy_revision_conflict",
            )
        existing = self.find_revision_by_verification(str(verification["id"]))
        if existing is not None:
            return existing
        row = self.database.execute_one(
            """
            select coalesce(max(revision), 0) as revision
              from workshop_partition_policy_revision
             where policy_id = ?
            """,
            (policy["id"],),
        )
        revision_number = int(row["revision"] if row else 0) + 1
        revision_id = new_id("workshop_partition_revision")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into workshop_partition_policy_revision
              (id, policy_id, revision, database_rule_enabled,
               database_table_prefix, redis_rule_enabled, content_hash,
               verification_id, status, published_by, published_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, 'PUBLISHED', ?, ?)
            """,
            (
                revision_id,
                policy["id"],
                revision_number,
                int(draft["database_rule_enabled"]),
                draft["database_table_prefix"],
                int(draft["redis_rule_enabled"]),
                draft["content_hash"],
                verification["id"],
                actor_id,
                timestamp,
            ),
        )
        for position, prefix in enumerate(draft["redis_prefixes"]):
            self.database.execute(
                """
                insert into workshop_partition_policy_revision_redis_prefix
                  (policy_revision_id, prefix, position)
                values (?, ?, ?)
                """,
                (revision_id, prefix, position),
            )
        rows = self.database.execute(
            """
            update workshop_partition_policy
               set revision = ?, updated_at = ?
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
            raise NonRetryableExecutionError(
                "Workshop Partition Policy changed during publication",
                safe_message="车间分区策略已变化，请刷新后重试",
                error_code="workshop_partition_policy_revision_conflict",
            )
        self.database.execute(
            "delete from workshop_partition_policy_draft where policy_id = ?",
            (policy["id"],),
        )
        return self.get_revision(revision_id)

    def copy_revision_to_draft(
        self,
        *,
        policy: dict[str, Any],
        revision: dict[str, Any],
        expected_policy_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        if int(policy["revision"]) != expected_policy_revision:
            raise NonRetryableExecutionError(
                "Workshop Partition Policy revision conflict",
                safe_message="车间分区策略已发布新版本，请刷新后重试",
                error_code="workshop_partition_policy_revision_conflict",
            )
        if self.get_draft(str(policy["id"])) is not None:
            raise NonRetryableExecutionError(
                "Workshop Partition Policy already has a Draft",
                safe_message="该策略已有可编辑草稿",
                error_code="workshop_partition_policy_conflict",
            )
        max_draft = self.database.execute_one(
            """
            select coalesce(max(draft_revision), 0) as draft_revision
              from workshop_partition_policy_verification
             where policy_id = ?
            """,
            (policy["id"],),
        )
        draft_revision = (
            max(
                int(max_draft["draft_revision"] if max_draft else 0),
                int(revision["revision"]),
            )
            + 1
        )
        timestamp = now_iso()
        self._insert_draft(
            policy_id=str(policy["id"]),
            draft_revision=draft_revision,
            draft=revision,
            content_hash=str(revision["content_hash"]),
            actor_id=actor_id,
            timestamp=timestamp,
        )
        result = self.get_draft(str(policy["id"]))
        assert result is not None
        return result

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from workshop_partition_policy_revision where id = ?",
            (revision_id,),
        )
        if row is None:
            raise NotFound(
                f"Workshop Partition Policy revision not found: {revision_id}",
                safe_message="未找到车间分区策略发布版本",
            )
        return self._revision(row)

    def list_revisions(self, policy_id: str) -> list[dict[str, Any]]:
        return [
            self._revision(row)
            for row in self.database.execute(
                """
                select * from workshop_partition_policy_revision
                 where policy_id = ?
                 order by revision desc
                """,
                (policy_id,),
            )
        ]

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
            insert into workshop_partition_policy_draft
              (policy_id, draft_revision, database_rule_enabled,
               database_table_prefix, redis_rule_enabled, content_hash,
               status, updated_by, updated_at)
            values (?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?)
            """,
            (
                policy_id,
                draft_revision,
                int(draft["database_rule_enabled"]),
                draft["database_table_prefix"],
                int(draft["redis_rule_enabled"]),
                content_hash,
                actor_id,
                timestamp,
            ),
        )
        self._insert_draft_prefixes(policy_id, draft["redis_prefixes"])

    def _insert_draft_prefixes(
        self,
        policy_id: str,
        prefixes: list[str],
    ) -> None:
        for position, prefix in enumerate(prefixes):
            self.database.execute(
                """
                insert into workshop_partition_policy_draft_redis_prefix
                  (policy_id, prefix, position)
                values (?, ?, ?)
                """,
                (policy_id, prefix, position),
            )

    def _draft(self, row: dict[str, Any]) -> dict[str, Any]:
        prefixes = self.database.execute(
            """
            select prefix
              from workshop_partition_policy_draft_redis_prefix
             where policy_id = ?
             order by position
            """,
            (row["policy_id"],),
        )
        return {
            **row,
            "draft_revision": int(row["draft_revision"]),
            "database_rule_enabled": bool(row["database_rule_enabled"]),
            "redis_rule_enabled": bool(row["redis_rule_enabled"]),
            "redis_prefixes": [str(item["prefix"]) for item in prefixes],
        }

    def _revision(self, row: dict[str, Any]) -> dict[str, Any]:
        prefixes = self.database.execute(
            """
            select prefix
              from workshop_partition_policy_revision_redis_prefix
             where policy_revision_id = ?
             order by position
            """,
            (row["id"],),
        )
        return {
            **row,
            "revision": int(row["revision"]),
            "database_rule_enabled": bool(row["database_rule_enabled"]),
            "redis_rule_enabled": bool(row["redis_rule_enabled"]),
            "redis_prefixes": [str(item["prefix"]) for item in prefixes],
        }

    @staticmethod
    def _verification(row: dict[str, Any]) -> dict[str, Any]:
        import json

        return {
            **row,
            "draft_revision": int(row["draft_revision"]),
            "zero_match_warning": bool(row["zero_match_warning"]),
            "database_summary": json.loads(row["database_summary_json"] or "{}"),
            "redis_summary": json.loads(row["redis_summary_json"] or "{}"),
        }
