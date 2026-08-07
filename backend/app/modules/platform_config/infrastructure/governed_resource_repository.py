from __future__ import annotations

import json
from typing import Any

from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound

from .repository import json_text, new_id, now_iso


class GovernedResourceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_resource(
        self,
        *,
        code: str,
        name: str,
        resource_kind: str,
        scope_type: str,
        environment_id: str | None,
        base_id: str | None,
        workshop_id: str | None,
        actor_id: str,
    ) -> dict[str, Any]:
        resource_id = new_id("tool_resource")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into platform_resource
              (id, code, name, resource_kind, scope_type, environment_id,
               base_id, workshop_id, status, revision, created_by,
               created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, 'enabled', 1, ?, ?, ?)
            """,
            (
                resource_id,
                code,
                name,
                resource_kind,
                scope_type,
                environment_id,
                base_id,
                workshop_id,
                actor_id,
                timestamp,
                timestamp,
            ),
        )
        return self.get_resource(resource_id)

    def get_resource(self, resource_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select r.*, e.code as environment_code, b.code as base_code,
                   w.code as workshop_code
            from platform_resource r
            left join platform_environment e on e.id = r.environment_id
            left join platform_base b on b.id = r.base_id
            left join platform_workshop w on w.id = r.workshop_id
            where r.id = ?
            """,
            (resource_id,),
        )
        if not row:
            raise NotFound(f"Platform resource not found: {resource_id}")
        return self._resource(row)

    def get_resource_by_code(self, code: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select r.*, e.code as environment_code, b.code as base_code,
                   w.code as workshop_code
            from platform_resource r
            left join platform_environment e on e.id = r.environment_id
            left join platform_base b on b.id = r.base_id
            left join platform_workshop w on w.id = r.workshop_id
            where r.code = ?
            """,
            (code,),
        )
        return self._resource(row) if row else None

    def list_resources(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select r.*, e.code as environment_code, b.code as base_code,
                   w.code as workshop_code
            from platform_resource r
            left join platform_environment e on e.id = r.environment_id
            left join platform_base b on b.id = r.base_id
            left join platform_workshop w on w.id = r.workshop_id
            order by r.code
            """
        )
        return [self._resource(row) for row in rows]

    def insert_draft(
        self,
        *,
        resource_id: str,
        draft_revision: int,
        provider_type: str,
        config: dict[str, Any],
        secret_refs: dict[str, str],
        content_hash: str,
        actor_id: str,
    ) -> dict[str, Any]:
        draft_id = new_id("resource_draft")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into platform_resource_draft
              (id, resource_id, draft_revision, provider_type, config_json,
               secret_refs_json, content_hash, status, created_by, updated_by,
               created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?)
            """,
            (
                draft_id,
                resource_id,
                draft_revision,
                provider_type,
                json_text(config),
                json_text(secret_refs),
                content_hash,
                actor_id,
                actor_id,
                timestamp,
                timestamp,
            ),
        )
        return self.get_draft(resource_id)

    def update_draft(
        self,
        *,
        resource_id: str,
        expected_revision: int,
        provider_type: str,
        config: dict[str, Any],
        secret_refs: dict[str, str],
        content_hash: str,
        actor_id: str,
    ) -> dict[str, Any]:
        rows = self.database.execute(
            """
            update platform_resource_draft
               set draft_revision = draft_revision + 1,
                   provider_type = ?,
                   config_json = ?,
                   secret_refs_json = ?,
                   content_hash = ?,
                   status = 'DRAFT',
                   updated_by = ?,
                   updated_at = ?
             where resource_id = ? and draft_revision = ?
            returning id
            """,
            (
                provider_type,
                json_text(config),
                json_text(secret_refs),
                content_hash,
                actor_id,
                now_iso(),
                resource_id,
                expected_revision,
            ),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Resource Draft revision conflict",
                safe_message="资源草稿已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )
        return self.get_draft(resource_id)

    def get_draft(self, resource_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from platform_resource_draft where resource_id = ?",
            (resource_id,),
        )
        if not row:
            raise NotFound(f"Platform resource draft not found: {resource_id}")
        return self._draft(row)

    def find_draft(self, resource_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            "select * from platform_resource_draft where resource_id = ?",
            (resource_id,),
        )
        return self._draft(row) if row else None

    def delete_draft(
        self,
        *,
        resource_id: str,
        expected_revision: int,
    ) -> None:
        rows = self.database.execute(
            """
            delete from platform_resource_draft
            where resource_id = ? and draft_revision = ?
            returning id
            """,
            (resource_id, expected_revision),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Resource Draft revision conflict",
                safe_message="资源草稿已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )

    def next_draft_revision(self, resource_id: str) -> int:
        row = self.database.execute_one(
            """
            select coalesce(max(draft_revision), 0) as revision
            from platform_resource_verification
            where resource_id = ?
            """,
            (resource_id,),
        )
        return int(row["revision"] if row else 0) + 1

    def insert_verification(
        self,
        *,
        resource_id: str,
        draft_id: str,
        draft_revision: int,
        content_hash: str,
        status: str,
        provider_contract_version: str,
        checks: dict[str, Any],
        safe_error_summary: str,
        actor_id: str,
    ) -> dict[str, Any]:
        verification_id = new_id("resource_verify")
        rows = self.database.execute(
            """
            insert into platform_resource_verification
              (id, resource_id, draft_id, draft_revision, content_hash, status,
               provider_contract_version, checks_json, safe_error_summary,
               verified_by, verified_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(resource_id, draft_revision, content_hash) do update set
              draft_id = excluded.draft_id,
              status = excluded.status,
              provider_contract_version = excluded.provider_contract_version,
              checks_json = excluded.checks_json,
              safe_error_summary = excluded.safe_error_summary,
              verified_by = excluded.verified_by,
              verified_at = excluded.verified_at
            returning id
            """,
            (
                verification_id,
                resource_id,
                draft_id,
                draft_revision,
                content_hash,
                status,
                provider_contract_version,
                json_text(checks),
                safe_error_summary,
                actor_id,
                now_iso(),
            ),
        )
        verification_id = str(rows[0]["id"])
        rows = self.database.execute(
            """
            update platform_resource_draft
               set status = ?, updated_by = ?, updated_at = ?
             where id = ? and draft_revision = ? and content_hash = ?
            returning id
            """,
            (
                "VERIFIED" if status == "PASSED" else "DRAFT",
                actor_id,
                now_iso(),
                draft_id,
                draft_revision,
                content_hash,
            ),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Resource Draft changed during verification",
                safe_message="资源草稿已变化，请重新验证",
                error_code="resource_verification_stale",
            )
        return self.get_verification(verification_id)

    def get_verification(self, verification_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from platform_resource_verification where id = ?",
            (verification_id,),
        )
        if not row:
            raise NotFound(f"Platform resource verification not found: {verification_id}")
        return self._verification(row)

    def matching_verification(
        self,
        *,
        resource_id: str,
        draft_revision: int,
        content_hash: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from platform_resource_verification
            where resource_id = ? and draft_revision = ? and content_hash = ?
            order by verified_at desc, id desc
            limit 1
            """,
            (resource_id, draft_revision, content_hash),
        )
        return self._verification(row) if row else None

    def next_resource_revision(self, resource_id: str) -> int:
        row = self.database.execute_one(
            """
            select coalesce(max(revision), 0) as revision
            from platform_resource_revision
            where resource_id = ?
            """,
            (resource_id,),
        )
        return int(row["revision"] if row else 0) + 1

    def insert_revision(
        self,
        *,
        resource_id: str,
        revision: int,
        provider_type: str,
        provider_contract_version: str,
        config: dict[str, Any],
        secret_refs: dict[str, str],
        content_hash: str,
        verification_id: str,
        actor_id: str,
    ) -> dict[str, Any]:
        revision_id = new_id("resource_revision")
        self.database.execute(
            """
            insert into platform_resource_revision
              (id, resource_id, revision, provider_type,
               provider_contract_version, config_json, secret_refs_json,
               content_hash, verification_id, status, published_by,
               published_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PUBLISHED', ?, ?)
            """,
            (
                revision_id,
                resource_id,
                revision,
                provider_type,
                provider_contract_version,
                json_text(config),
                json_text(secret_refs),
                content_hash,
                verification_id,
                actor_id,
                now_iso(),
            ),
        )
        return self.get_revision(revision_id)

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from platform_resource_revision where id = ?",
            (revision_id,),
        )
        if not row:
            raise NotFound(f"Platform resource revision not found: {revision_id}")
        return self._revision(row)

    def list_revisions(self, resource_id: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select * from platform_resource_revision
            where resource_id = ?
            order by revision
            """,
            (resource_id,),
        )
        return [self._revision(row) for row in rows]

    def set_revision_status(
        self,
        *,
        revision_id: str,
        status: str,
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.get_revision(revision_id)
        timestamp = now_iso()
        if status == "DISABLED":
            fields = "status = ?, disabled_by = ?, disabled_at = ?"
        else:
            fields = "status = ?, archived_by = ?, archived_at = ?"
        rows = self.database.execute(
            f"""
            update platform_resource_revision
               set {fields}
             where id = ? and status = ?
            returning id
            """,
            (
                status,
                actor_id,
                timestamp,
                revision_id,
                current["status"],
            ),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Resource Revision status conflict",
                safe_message="资源发布版本状态已变化，请刷新后重试",
                error_code="revision_conflict",
            )
        return self.get_revision(revision_id)

    def _resource(self, row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "revision": int(row.get("revision") or 0)}

    def _draft(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "draft_revision": int(row.get("draft_revision") or 0),
            "config": self._json(row.get("config_json") or "{}"),
            "secret_refs": self._json(row.get("secret_refs_json") or "{}"),
        }

    def _verification(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "draft_revision": int(row.get("draft_revision") or 0),
            "checks": self._json(row.get("checks_json") or "{}"),
        }

    def _revision(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "revision": int(row.get("revision") or 0),
            "config": self._json(row.get("config_json") or "{}"),
            "secret_refs": self._json(row.get("secret_refs_json") or "{}"),
        }

    @staticmethod
    def _json(value: str) -> Any:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
