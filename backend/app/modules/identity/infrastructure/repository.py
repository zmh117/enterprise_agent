from __future__ import annotations

import json
from typing import Any

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


class IdentityRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_user(
        self,
        *,
        username: str,
        display_name: str,
        email: str = "",
        status: str = "enabled",
        account_type: str = "human",
    ) -> dict[str, Any]:
        user_id = new_id("user")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into app_user
              (id, username, display_name, email, status, account_type,
               revision, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                user_id,
                username,
                display_name,
                email,
                status,
                account_type,
                timestamp,
                timestamp,
            ),
        )
        return self.get_user(user_id)

    def list_users(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where status = 'enabled'"
        return self.database.execute(
            f"""
            select id, username, display_name, email, status, account_type,
                   revision, created_at, updated_at
            from app_user {where}
            order by username
            """
        )

    def get_user(self, user_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select id, username, display_name, email, status, account_type,
                   revision, created_at, updated_at
            from app_user where id = ?
            """,
            (user_id,),
        )
        if not row:
            raise NotFound("User not found", safe_message="User not found")
        return row

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        return self.database.execute_one(
            """
            select id, username, display_name, email, status, account_type,
                   revision, created_at, updated_at
            from app_user where username = ?
            """,
            (username,),
        )

    def update_user(
        self,
        user_id: str,
        *,
        expected_revision: int,
        display_name: str,
        email: str,
        status: str,
    ) -> dict[str, Any]:
        rows = self.database.execute(
            """
            update app_user
            set display_name = ?, email = ?, status = ?, revision = revision + 1,
                updated_at = ?
            where id = ? and revision = ?
            returning id
            """,
            (display_name, email, status, now_iso(), user_id, expected_revision),
        )
        if not rows:
            if self.database.execute_one("select id from app_user where id = ?", (user_id,)):
                raise NonRetryableExecutionError(
                    "User revision conflict",
                    safe_message="User was modified; refresh and try again",
                    error_code="revision_conflict",
                )
            raise NotFound("User not found", safe_message="User not found")
        return self.get_user(user_id)

    def set_password_hash(self, user_id: str, password_hash: str) -> None:
        user = self.get_user(user_id)
        if str(user["account_type"]) != "human":
            raise NonRetryableExecutionError(
                "Service accounts cannot have password credentials",
                safe_message="Service accounts cannot have password credentials",
                error_code="service_account_password_forbidden",
            )
        timestamp = now_iso()
        self.database.execute(
            """
            insert into user_password_credential
              (user_id, password_hash, revision, password_changed_at, created_at, updated_at)
            values (?, ?, 1, ?, ?, ?)
            on conflict(user_id) do update set
              password_hash = excluded.password_hash,
              revision = user_password_credential.revision + 1,
              password_changed_at = excluded.password_changed_at,
              updated_at = excluded.updated_at
            """,
            (user_id, password_hash, timestamp, timestamp, timestamp),
        )

    def get_password_hash(self, user_id: str) -> str:
        row = self.database.execute_one(
            "select password_hash from user_password_credential where user_id = ?",
            (user_id,),
        )
        return str(row["password_hash"]) if row else ""

    def bind_external_identity(
        self,
        *,
        user_id: str,
        provider: str,
        tenant_code: str,
        external_subject_id: str,
        connector_id: str,
        display_name: str = "",
        union_id: str = "",
        open_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user = self.get_user(user_id)
        if str(user["account_type"]) != "human":
            raise NonRetryableExecutionError(
                "Service accounts cannot bind external identities",
                safe_message="Service accounts cannot bind external identities",
                error_code="service_account_identity_forbidden",
            )
        existing = self.find_external_identity(
            provider=provider,
            tenant_code=tenant_code,
            external_subject_id=external_subject_id,
            include_disabled=True,
        )
        if existing:
            if str(existing["user_id"]) != user_id:
                raise NonRetryableExecutionError(
                    "External identity already belongs to another user",
                    safe_message="DingTalk identity is already bound",
                    error_code="identity_conflict",
                )
            return existing
        identity_id = new_id("identity")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into user_external_identity
              (id, user_id, provider, tenant_code, external_subject_id, connector_id,
               union_id, open_id, display_name, status, verified_at, last_seen_at,
               metadata_json, revision, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'enabled', ?, ?, ?, 1, ?, ?)
            """,
            (
                identity_id,
                user_id,
                provider,
                tenant_code,
                external_subject_id,
                connector_id,
                union_id,
                open_id,
                display_name,
                timestamp,
                timestamp,
                json.dumps(metadata or {}, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        return self.get_external_identity(identity_id)

    def list_external_identities(self, user_id: str) -> list[dict[str, Any]]:
        self.get_user(user_id)
        rows = self.database.execute(
            """
            select * from user_external_identity where user_id = ?
            order by provider, tenant_code, external_subject_id
            """,
            (user_id,),
        )
        return [self._external_public(row) for row in rows]

    def get_external_identity(self, identity_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from user_external_identity where id = ?", (identity_id,)
        )
        if not row:
            raise NotFound("External identity not found", safe_message="Identity not found")
        return self._external_public(row)

    def find_external_identity(
        self,
        *,
        provider: str,
        tenant_code: str,
        external_subject_id: str,
        include_disabled: bool = False,
    ) -> dict[str, Any] | None:
        status = "" if include_disabled else "and i.status = 'enabled' and u.status = 'enabled'"
        row = self.database.execute_one(
            f"""
            select i.*, u.username, u.display_name as user_display_name,
                   u.status as user_status, u.account_type as user_account_type
            from user_external_identity i
            join app_user u on u.id = i.user_id
            where i.provider = ? and i.tenant_code = ? and i.external_subject_id = ?
              {status}
            """,
            (provider, tenant_code, external_subject_id),
        )
        return self._external_public(row) if row else None

    def touch_external_identity(self, identity_id: str) -> None:
        self.database.execute(
            """
            update user_external_identity
            set last_seen_at = ?, revision = revision + 1, updated_at = ?
            where id = ?
            """,
            (now_iso(), now_iso(), identity_id),
        )

    def set_external_identity_status(
        self, identity_id: str, *, status: str, expected_revision: int
    ) -> dict[str, Any]:
        rows = self.database.execute(
            """
            update user_external_identity
            set status = ?, revision = revision + 1, updated_at = ?
            where id = ? and revision = ?
            returning id, user_id
            """,
            (status, now_iso(), identity_id, expected_revision),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Identity revision conflict",
                safe_message="Identity was modified; refresh and try again",
                error_code="revision_conflict",
            )
        return self.get_external_identity(identity_id)

    def create_role(self, *, code: str, name: str, description: str = "") -> dict[str, Any]:
        role_id = new_id("role")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into rbac_role
              (id, code, name, description, status, revision, created_at, updated_at)
            values (?, ?, ?, ?, 'enabled', 1, ?, ?)
            """,
            (role_id, code, name, description, timestamp, timestamp),
        )
        return self.get_role(role_id)

    def list_roles(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where status = 'enabled'"
        return self.database.execute(f"select * from rbac_role {where} order by code")

    def get_role(self, role_id: str) -> dict[str, Any]:
        row = self.database.execute_one("select * from rbac_role where id = ?", (role_id,))
        if not row:
            raise NotFound("Role not found", safe_message="Role not found")
        return row

    def get_role_by_code(self, code: str) -> dict[str, Any] | None:
        return self.database.execute_one("select * from rbac_role where code = ?", (code,))

    def update_role(
        self,
        role_id: str,
        *,
        expected_revision: int,
        name: str,
        description: str,
        status: str,
    ) -> dict[str, Any]:
        rows = self.database.execute(
            """
            update rbac_role
            set name = ?, description = ?, status = ?, revision = revision + 1,
                updated_at = ?
            where id = ? and revision = ?
            returning id
            """,
            (name, description, status, now_iso(), role_id, expected_revision),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Role revision conflict",
                safe_message="Role was modified; refresh and try again",
                error_code="revision_conflict",
            )
        return self.get_role(role_id)

    def assign_role(
        self,
        *,
        user_id: str,
        role_id: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        self.get_user(user_id)
        self.get_role(role_id)
        existing = self.database.execute_one(
            "select * from rbac_user_role where user_id = ? and role_id = ?",
            (user_id, role_id),
        )
        timestamp = now_iso()
        if existing:
            if expected_revision is not None and int(existing["revision"]) != expected_revision:
                raise NonRetryableExecutionError(
                    "Membership revision conflict",
                    safe_message="Role membership was modified; refresh and try again",
                    error_code="revision_conflict",
                )
            self.database.execute(
                """
                update rbac_user_role
                set status = 'enabled', revision = revision + 1, updated_at = ?
                where id = ?
                """,
                (timestamp, existing["id"]),
            )
            return (
                self.database.execute_one(
                    "select * from rbac_user_role where id = ?", (existing["id"],)
                )
                or {}
            )
        if expected_revision not in (None, 0):
            raise NonRetryableExecutionError(
                "Membership revision conflict",
                safe_message="Role membership was modified; refresh and try again",
                error_code="revision_conflict",
            )
        membership_id = new_id("membership")
        self.database.execute(
            """
            insert into rbac_user_role
              (id, user_id, role_id, status, revision, created_at, updated_at)
            values (?, ?, ?, 'enabled', 1, ?, ?)
            """,
            (membership_id, user_id, role_id, timestamp, timestamp),
        )
        return (
            self.database.execute_one("select * from rbac_user_role where id = ?", (membership_id,))
            or {}
        )

    def remove_role(self, *, user_id: str, role_id: str, expected_revision: int) -> dict[str, Any]:
        rows = self.database.execute(
            """
            update rbac_user_role
            set status = 'disabled', revision = revision + 1, updated_at = ?
            where user_id = ? and role_id = ? and revision = ?
            returning *
            """,
            (now_iso(), user_id, role_id, expected_revision),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "Membership revision conflict",
                safe_message="Role membership was modified; refresh and try again",
                error_code="revision_conflict",
            )
        return rows[0]

    def role_codes_for_user(self, user_id: str) -> tuple[str, ...]:
        rows = self.database.execute(
            """
            select r.code
            from rbac_user_role ur
            join rbac_role r on r.id = ur.role_id
            where ur.user_id = ? and ur.status = 'enabled' and r.status = 'enabled'
            order by r.code
            """,
            (user_id,),
        )
        return tuple(str(row["code"]) for row in rows)

    def list_user_roles(self, user_id: str) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select r.id, r.code, r.name, r.description, r.status,
                   ur.id as membership_id, ur.status as membership_status,
                   ur.revision as membership_revision
            from rbac_user_role ur
            join rbac_role r on r.id = ur.role_id
            where ur.user_id = ? and ur.status = 'enabled'
            order by r.code
            """,
            (user_id,),
        )

    def upsert_policy(
        self,
        *,
        policy_id: str | None,
        subject_type: str,
        subject_code: str,
        resource_type: str,
        resource_code: str,
        action: str,
        effect: str,
        priority: int = 100,
        status: str = "enabled",
        expected_revision: int = 0,
    ) -> dict[str, Any]:
        policy_id = policy_id or new_id("policy")
        timestamp = now_iso()
        existing = self.database.execute_one(
            "select id, revision from permission_policy where id = ?", (policy_id,)
        )
        if existing:
            rows = self.database.execute(
                """
                update permission_policy
                set subject_type = ?, subject_code = ?, resource_type = ?,
                    resource_code = ?, action = ?, effect = ?, priority = ?,
                    status = ?, revision = revision + 1, updated_at = ?
                where id = ? and revision = ?
                returning id
                """,
                (
                    subject_type,
                    subject_code,
                    resource_type,
                    resource_code,
                    action,
                    effect,
                    priority,
                    status,
                    timestamp,
                    policy_id,
                    expected_revision,
                ),
            )
            if not rows:
                raise NonRetryableExecutionError(
                    "Permission revision conflict",
                    safe_message="Permission was modified; refresh and try again",
                    error_code="revision_conflict",
                )
        else:
            if expected_revision != 0:
                raise NonRetryableExecutionError(
                    "Permission revision conflict",
                    safe_message="Permission was modified; refresh and try again",
                    error_code="revision_conflict",
                )
            self.database.execute(
                """
                insert into permission_policy
                  (id, subject_type, subject_code, resource_type, resource_code,
                   effect, action, status, priority, revision, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    policy_id,
                    subject_type,
                    subject_code,
                    resource_type,
                    resource_code,
                    effect,
                    action,
                    status,
                    priority,
                    timestamp,
                    timestamp,
                ),
            )
        return (
            self.database.execute_one("select * from permission_policy where id = ?", (policy_id,))
            or {}
        )

    def get_policy(self, policy_id: str) -> dict[str, Any] | None:
        return self.database.execute_one(
            """
            select id, subject_type, subject_code, resource_type, resource_code,
                   action, effect, priority, status, revision, created_at, updated_at
            from permission_policy where id = ?
            """,
            (policy_id,),
        )

    def policies_for_principals(
        self,
        *,
        user_id: str,
        role_codes: tuple[str, ...],
        resource_type: str,
        resource_code: str,
        action: str,
    ) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select * from permission_policy
            where status = 'enabled'
              and resource_type = ?
              and (resource_code = ? or resource_code = '*')
              and (action = ? or action = '*')
            order by priority, id
            """,
            (resource_type, resource_code, action),
        )
        principals = {("user", user_id)}
        principals.update(("role", code) for code in role_codes)
        return [
            row
            for row in rows
            if (str(row["subject_type"]), str(row["subject_code"])) in principals
        ]

    def platform_grants_for_principals(
        self,
        *,
        user_id: str,
        role_codes: tuple[str, ...],
        environment: str,
        base: str,
        workshop: str = "",
        tool_name: str = "",
    ) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select g.*, e.code as environment_code, b.code as base_code,
                   w.code as workshop_code
            from platform_access_grant g
            left join platform_environment e on e.id = g.environment_id
            left join platform_base b on b.id = g.base_id
            left join platform_workshop w on w.id = g.workshop_id
            where g.status = 'enabled'
            order by g.priority, g.id
            """
        )
        principals = {("user", user_id)}
        principals.update(("role", code) for code in role_codes)
        matched: list[dict[str, Any]] = []
        for row in rows:
            if (str(row["subject_type"]), str(row["subject_code"])) not in principals:
                continue
            if row.get("environment_id") and str(row.get("environment_code") or "") != environment:
                continue
            if row.get("base_id") and str(row.get("base_code") or "") != base:
                continue
            if row.get("workshop_id") and str(row.get("workshop_code") or "") != workshop:
                continue
            tool_scope = _json_list(row.get("tool_scope_json"))
            if tool_name and tool_scope and "*" not in tool_scope and tool_name not in tool_scope:
                continue
            item = dict(row)
            item["tool_scope"] = tool_scope
            item["resource_scope"] = _json_object(row.get("resource_scope_json"))
            item["specificity"] = sum(
                1 for field in ("environment_id", "base_id", "workshop_id") if row.get(field)
            ) + (1 if tool_name and tool_scope and "*" not in tool_scope else 0)
            matched.append(item)
        return sorted(
            matched,
            key=lambda row: (
                -int(row["specificity"]),
                int(row.get("priority") or 100),
                str(row["id"]),
            ),
        )

    def safe_platform_scope_summary(
        self,
        *,
        user_id: str,
        role_codes: tuple[str, ...],
        global_access: bool = False,
    ) -> dict[str, Any]:
        if global_access:
            return {"mode": "global", "grants": []}
        rows = self.database.execute(
            """
            select g.subject_type, g.subject_code, g.effect,
                   e.code as environment_code, b.code as base_code,
                   w.code as workshop_code, g.tool_scope_json
            from platform_access_grant g
            left join platform_environment e on e.id = g.environment_id
            left join platform_base b on b.id = g.base_id
            left join platform_workshop w on w.id = g.workshop_id
            where g.status = 'enabled'
            order by g.priority, g.id
            """
        )
        principals = {("user", user_id)}
        principals.update(("role", code) for code in role_codes)
        grants = [
            {
                "effect": str(row["effect"]),
                "environment": str(row.get("environment_code") or "*"),
                "base": str(row.get("base_code") or "*"),
                "workshop": str(row.get("workshop_code") or "*"),
                "tools": _json_list(row.get("tool_scope_json")),
            }
            for row in rows
            if (str(row["subject_type"]), str(row["subject_code"])) in principals
        ]
        return {"mode": "restricted", "grants": grants}

    def create_session(
        self,
        *,
        user_id: str,
        token_hash: str,
        csrf_hash: str,
        idle_expires_at: str,
        absolute_expires_at: str,
        user_agent_summary: str = "",
        remote_address_summary: str = "",
    ) -> dict[str, Any]:
        user = self.get_user(user_id)
        if str(user["account_type"]) != "human":
            raise NonRetryableExecutionError(
                "Service accounts cannot create login sessions",
                safe_message="Service accounts cannot create login sessions",
                error_code="service_account_session_forbidden",
            )
        session_id = new_id("session_auth")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into user_session
              (id, user_id, token_hash, csrf_hash, status, created_at, last_seen_at,
               idle_expires_at, absolute_expires_at, user_agent_summary,
               remote_address_summary)
            values (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user_id,
                token_hash,
                csrf_hash,
                timestamp,
                timestamp,
                idle_expires_at,
                absolute_expires_at,
                user_agent_summary,
                remote_address_summary,
            ),
        )
        return self.get_session_by_token_hash(token_hash) or {}

    def get_session_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        return self.database.execute_one(
            """
            select s.*, u.username, u.display_name, u.status as user_status,
                   u.account_type as user_account_type
            from user_session s
            join app_user u on u.id = s.user_id
            where s.token_hash = ?
            """,
            (token_hash,),
        )

    def touch_session(self, session_id: str, idle_expires_at: str) -> None:
        self.database.execute(
            """
            update user_session set last_seen_at = ?, idle_expires_at = ?
            where id = ? and status = 'active'
            """,
            (now_iso(), idle_expires_at, session_id),
        )

    def revoke_session(self, session_id: str) -> None:
        self.database.execute(
            """
            update user_session
            set status = 'revoked', revoked_at = ?
            where id = ? and status = 'active'
            """,
            (now_iso(), session_id),
        )

    def revoke_owned_session(self, *, session_id: str, user_id: str) -> bool:
        rows = self.database.execute(
            """
            update user_session
            set status = 'revoked', revoked_at = ?
            where id = ? and user_id = ? and status = 'active'
            returning id
            """,
            (now_iso(), session_id, user_id),
        )
        return bool(rows)

    def revoke_user_sessions(self, user_id: str) -> None:
        self.database.execute(
            """
            update user_session
            set status = 'revoked', revoked_at = ?
            where user_id = ? and status = 'active'
            """,
            (now_iso(), user_id),
        )

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select id, user_id, status, created_at, last_seen_at, idle_expires_at,
                   absolute_expires_at, revoked_at, user_agent_summary,
                   remote_address_summary
            from user_session where user_id = ?
            order by created_at desc
            """,
            (user_id,),
        )

    def admin_count(self) -> int:
        row = self.database.execute_one(
            """
            select count(*) as count
            from rbac_user_role ur
            join rbac_role r on r.id = ur.role_id
            join app_user u on u.id = ur.user_id
            where r.code = 'platform-admin' and r.status = 'enabled'
              and ur.status = 'enabled' and u.status = 'enabled'
              and u.account_type = 'human'
            """
        )
        return int(row["count"]) if row else 0

    def record_migration(
        self,
        *,
        legacy_subject_type: str,
        legacy_subject_code: str,
        tenant_code: str,
        internal_user_id: str | None,
        status: str,
        reason: str,
    ) -> None:
        self.database.execute(
            """
            insert into identity_migration_audit
              (id, legacy_subject_type, legacy_subject_code, tenant_code,
               internal_user_id, status, reason, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("identity_migration"),
                legacy_subject_type,
                legacy_subject_code,
                tenant_code,
                internal_user_id,
                status,
                reason,
                now_iso(),
            ),
        )

    def list_policies(self) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select id, subject_type, subject_code, resource_type, resource_code,
                   action, effect, priority, status, revision, created_at, updated_at
            from permission_policy
            order by subject_type, subject_code, resource_type, resource_code, action
            """
        )

    def list_role_members(self, role_id: str) -> list[dict[str, Any]]:
        self.get_role(role_id)
        return self.database.execute(
            """
            select u.id, u.username, u.display_name, u.email, u.status,
                   ur.id as membership_id, ur.status as membership_status,
                   ur.revision as membership_revision
            from rbac_user_role ur
            join app_user u on u.id = ur.user_id
            where ur.role_id = ?
            order by u.username
            """,
            (role_id,),
        )

    def list_role_policies(self, role_code: str) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select id, subject_type, subject_code, resource_type, resource_code,
                   action, effect, priority, status, revision, created_at, updated_at
            from permission_policy
            where subject_type = 'role' and subject_code = ?
            order by resource_type, resource_code, action, priority, id
            """,
            (role_code,),
        )

    def _external_public(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "provider": row["provider"],
            "tenant_code": row["tenant_code"],
            "external_subject_id": row["external_subject_id"],
            "connector_id": row.get("connector_id") or "",
            "union_id": row.get("union_id") or "",
            "open_id": row.get("open_id") or "",
            "display_name": row.get("display_name") or "",
            "status": row["status"],
            "verified_at": row.get("verified_at"),
            "last_seen_at": row.get("last_seen_at"),
            "revision": int(row.get("revision") or 1),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "username": row.get("username") or "",
            "user_display_name": row.get("user_display_name") or "",
            "user_status": row.get("user_status") or "",
        }


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _json_object(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
