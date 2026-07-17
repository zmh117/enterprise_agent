from __future__ import annotations

from typing import Any

from app.modules.identity.infrastructure import IdentityRepository
from app.modules.job.infrastructure.repositories import new_id, now_iso


class LegacyIdentityMigrationService:
    """Reconciles legacy user subjects without guessing tenant or user ownership."""

    def __init__(self, repository: IdentityRepository) -> None:
        self.repository = repository

    def reconcile(self, *, apply: bool = False) -> dict[str, Any]:
        database = self.repository.database
        legacy_subjects = database.execute(
            """
            select distinct subject_code
            from permission_policy
            where subject_type = 'user'
            union
            select distinct subject_code
            from platform_access_grant
            where subject_type = 'user'
            order by subject_code
            """
        )
        results: list[dict[str, Any]] = []
        for row in legacy_subjects:
            subject_code = str(row["subject_code"])
            if database.execute_one("select id from app_user where id = ?", (subject_code,)):
                results.append(
                    {
                        "legacy_subject_code": subject_code,
                        "status": "already_internal",
                    }
                )
                continue
            matches = database.execute(
                """
                select i.id, i.user_id, i.tenant_code
                from user_external_identity i
                join app_user u on u.id = i.user_id
                where i.external_subject_id = ?
                  and i.status = 'enabled' and u.status = 'enabled'
                order by i.tenant_code, i.user_id
                """,
                (subject_code,),
            )
            unique = {
                (str(item["tenant_code"]), str(item["user_id"])) for item in matches
            }
            if len(unique) != 1:
                status = "unmatched" if not unique else "ambiguous"
                if apply:
                    self.repository.record_migration(
                        legacy_subject_type="user",
                        legacy_subject_code=subject_code,
                        tenant_code="",
                        internal_user_id=None,
                        status=status,
                        reason="No unique provider tenant and internal user mapping",
                    )
                results.append(
                    {
                        "legacy_subject_code": subject_code,
                        "status": status,
                        "candidate_count": len(unique),
                    }
                )
                continue
            tenant_code, user_id = next(iter(unique))
            if apply:
                with database.transaction():
                    self._copy_policies(subject_code, user_id)
                    self._copy_platform_grants(subject_code, user_id)
                    self.repository.record_migration(
                        legacy_subject_type="user",
                        legacy_subject_code=subject_code,
                        tenant_code=tenant_code,
                        internal_user_id=user_id,
                        status="migrated",
                        reason="Unique enabled external identity mapping",
                    )
            results.append(
                {
                    "legacy_subject_code": subject_code,
                    "tenant_code": tenant_code,
                    "internal_user_id": user_id,
                    "status": "migrated" if apply else "ready",
                }
            )
        return {
            "apply": apply,
            "subjects": results,
            "summary": {
                status: sum(1 for item in results if item["status"] == status)
                for status in {
                    "already_internal",
                    "ready",
                    "migrated",
                    "unmatched",
                    "ambiguous",
                }
            },
        }

    def _copy_policies(self, legacy_subject: str, user_id: str) -> None:
        rows = self.repository.database.execute(
            "select * from permission_policy where subject_type = 'user' and subject_code = ?",
            (legacy_subject,),
        )
        for row in rows:
            existing = self.repository.database.execute_one(
                """
                select id from permission_policy
                where subject_type = 'user' and subject_code = ?
                  and resource_type = ? and resource_code = ? and action = ?
                  and effect = ?
                """,
                (
                    user_id,
                    row["resource_type"],
                    row["resource_code"],
                    row["action"],
                    row["effect"],
                ),
            )
            if existing:
                continue
            self.repository.database.execute(
                """
                insert into permission_policy
                  (id, subject_type, subject_code, resource_type, resource_code,
                   effect, action, status, priority, revision, created_at, updated_at)
                values (?, 'user', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    new_id("policy"),
                    user_id,
                    row["resource_type"],
                    row["resource_code"],
                    row["effect"],
                    row["action"],
                    row["status"],
                    row["priority"],
                    now_iso(),
                    now_iso(),
                ),
            )

    def _copy_platform_grants(self, legacy_subject: str, user_id: str) -> None:
        rows = self.repository.database.execute(
            """
            select * from platform_access_grant
            where subject_type = 'user' and subject_code = ?
            """,
            (legacy_subject,),
        )
        for row in rows:
            existing = self.repository.database.execute_one(
                """
                select id from platform_access_grant
                where subject_type = 'user' and subject_code = ?
                  and effect = ?
                  and coalesce(environment_id, '') = coalesce(?, '')
                  and coalesce(base_id, '') = coalesce(?, '')
                  and coalesce(workshop_id, '') = coalesce(?, '')
                  and tool_scope_json = ? and resource_scope_json = ?
                """,
                (
                    user_id,
                    row["effect"],
                    row.get("environment_id"),
                    row.get("base_id"),
                    row.get("workshop_id"),
                    row["tool_scope_json"],
                    row["resource_scope_json"],
                ),
            )
            if existing:
                continue
            self.repository.database.execute(
                """
                insert into platform_access_grant
                  (id, subject_type, subject_code, effect, environment_id, base_id,
                   workshop_id, tool_scope_json, resource_scope_json, condition_json,
                   priority, status, revision, created_at, updated_at)
                values (?, 'user', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    new_id("platform_access_grant"),
                    user_id,
                    row["effect"],
                    row.get("environment_id"),
                    row.get("base_id"),
                    row.get("workshop_id"),
                    row["tool_scope_json"],
                    row["resource_scope_json"],
                    row["condition_json"],
                    row["priority"],
                    row["status"],
                    now_iso(),
                    now_iso(),
                ),
            )
