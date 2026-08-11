from __future__ import annotations

import json
from typing import Any
from datetime import UTC, datetime, timedelta

from app.modules.identity.domain import ExternalIdentityProvider
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
        try:
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
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise NonRetryableExecutionError(
                    "Username already exists",
                    safe_message="用户名已被使用",
                    error_code="username_conflict",
                    field_errors=[
                        {"field": "username", "message": "用户名已被使用"}
                    ],
                ) from exc
            raise
        return self.get_user(user_id)

    def list_users(
        self,
        *,
        include_disabled: bool = True,
        search: str = "",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where_sql, params = self._user_search_clause(
            include_disabled=include_disabled,
            search=search,
        )
        pagination = ""
        if limit is not None:
            pagination = "limit ? offset ?"
            params.extend((limit, offset))
        return self.database.execute(
            f"""
            select u.id, u.username, u.display_name, u.email, u.status, u.account_type,
                   revision, created_at, updated_at
            from app_user u
            {where_sql}
            order by lower(u.username), u.id
            {pagination}
            """,
            tuple(params),
        )

    def count_users(self, *, include_disabled: bool = True, search: str = "") -> int:
        where_sql, params = self._user_search_clause(
            include_disabled=include_disabled,
            search=search,
        )
        row = self.database.execute_one(
            f"select count(*) as count from app_user u {where_sql}",
            tuple(params),
        )
        return int(row["count"]) if row else 0

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
            raise NotFound("User not found", safe_message="未找到用户")
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
                    safe_message="用户信息已发生变化，请刷新后重试",
                    error_code="revision_conflict",
                )
            raise NotFound("User not found", safe_message="未找到用户")
        return self.get_user(user_id)

    def delete_user(self, user_id: str, *, expected_revision: int) -> dict[str, Any]:
        current = self.get_user(user_id)
        if int(current["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "User revision conflict",
                safe_message="用户信息已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )
        self.database.execute(
            "update identity_migration_audit set internal_user_id = null where internal_user_id = ?",
            (user_id,),
        )
        self.database.execute(
            "delete from user_external_identity where user_id = ?", (user_id,)
        )
        self.database.execute("delete from user_session where user_id = ?", (user_id,))
        self.database.execute(
            "delete from user_password_credential where user_id = ?", (user_id,)
        )
        self.database.execute("delete from rbac_user_role where user_id = ?", (user_id,))
        rows = self.database.execute(
            "delete from app_user where id = ? and revision = ? returning id",
            (user_id, expected_revision),
        )
        if not rows:
            raise NonRetryableExecutionError(
                "User revision conflict",
                safe_message="用户信息已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )
        return current

    def set_password_hash(self, user_id: str, password_hash: str) -> None:
        user = self.get_user(user_id)
        if str(user["account_type"]) != "human":
            raise NonRetryableExecutionError(
                "Service accounts cannot have password credentials",
                safe_message="服务账号不能设置密码凭据",
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
        normalized_provider = ExternalIdentityProvider.require_supported(provider).value
        normalized_metadata = self._identity_metadata(
            normalized_provider,
            metadata or {},
        )
        user = self.get_user(user_id)
        if str(user["account_type"]) != "human":
            raise NonRetryableExecutionError(
                "Service accounts cannot bind external identities",
                safe_message="服务账号不能绑定外部身份",
                error_code="service_account_identity_forbidden",
            )
        existing = self.find_external_identity(
            provider=normalized_provider,
            tenant_code=tenant_code,
            external_subject_id=external_subject_id,
            include_disabled=True,
        )
        if existing:
            if str(existing["user_id"]) != user_id:
                raise NonRetryableExecutionError(
                    "External identity already belongs to another user",
                    safe_message="此外部身份已绑定其他用户",
                    error_code="identity_conflict",
                )
            if normalized_provider == ExternalIdentityProvider.ONES.value:
                self.database.execute(
                    """
                    update user_external_identity
                    set display_name = ?, metadata_json = ?, verified_at = ?,
                        status = 'enabled', revision = revision + 1, updated_at = ?
                    where id = ?
                    """,
                    (
                        display_name,
                        json.dumps(normalized_metadata, ensure_ascii=False, sort_keys=True),
                        now_iso(),
                        now_iso(),
                        existing["id"],
                    ),
                )
                return self.get_external_identity(str(existing["id"]))
            if str(existing["status"]) != "enabled":
                self.database.execute(
                    """
                    update user_external_identity
                    set display_name = ?, union_id = ?, open_id = ?,
                        metadata_json = ?, status = 'enabled', verified_at = ?,
                        revision = revision + 1, updated_at = ?
                    where id = ?
                    """,
                    (
                        display_name,
                        union_id,
                        open_id,
                        json.dumps(normalized_metadata, ensure_ascii=False, sort_keys=True),
                        now_iso(),
                        now_iso(),
                        existing["id"],
                    ),
                )
                return self.get_external_identity(str(existing["id"]))
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
                normalized_provider,
                tenant_code,
                external_subject_id,
                connector_id,
                union_id,
                open_id,
                display_name,
                timestamp,
                timestamp
                if normalized_provider == ExternalIdentityProvider.DINGTALK.value
                else None,
                json.dumps(normalized_metadata, ensure_ascii=False, sort_keys=True),
                timestamp,
                timestamp,
            ),
        )
        return self.get_external_identity(identity_id)

    def list_external_identities(self, user_id: str) -> list[dict[str, Any]]:
        self.get_user(user_id)
        rows = self.database.execute(
            """
            select i.*
              from user_external_identity i
             where i.user_id = ?
            order by provider, tenant_code, external_subject_id
            """,
            (user_id,),
        )
        return [self._external_public(row) for row in rows]

    def get_external_identity(self, identity_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select i.*
              from user_external_identity i
             where i.id = ?
            """,
            (identity_id,),
        )
        if not row:
            raise NotFound("External identity not found", safe_message="未找到身份")
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

    def find_dingtalk_identity(
        self,
        *,
        dingtalk_enterprise_id: str,
        external_subject_id: str,
        include_disabled: bool = False,
    ) -> dict[str, Any] | None:
        status = "" if include_disabled else "and i.status = 'enabled' and u.status = 'enabled'"
        row = self.database.execute_one(
            f"""
            select i.*, u.username, u.display_name as user_display_name,
                   u.status as user_status, u.account_type as user_account_type,
                   e.name as dingtalk_enterprise_name,
                   e.corp_id as dingtalk_enterprise_corp_id,
                   e.status as dingtalk_enterprise_status,
                   null as credential_status
              from user_external_identity i
              join app_user u on u.id = i.user_id
              join dingtalk_enterprise e on e.id = i.dingtalk_enterprise_id
             where i.provider = 'dingtalk'
               and i.dingtalk_enterprise_id = ?
               and i.external_subject_id = ?
               {status}
            """,
            (dingtalk_enterprise_id, external_subject_id),
        )
        return self._external_public(row) if row else None

    def bind_dingtalk_identity(
        self,
        *,
        user_id: str,
        dingtalk_enterprise_id: str,
        external_subject_id: str,
        display_name: str,
        source_connector_id: str,
        source_ingress_event_id: str,
        observed_at: str,
        replace_current: bool,
        restore_historical: bool = False,
    ) -> dict[str, Any]:
        existing = self.find_dingtalk_identity(
            dingtalk_enterprise_id=dingtalk_enterprise_id,
            external_subject_id=external_subject_id,
            include_disabled=True,
        )
        if existing:
            if str(existing["user_id"]) != user_id:
                raise NonRetryableExecutionError(
                    "DingTalk identity has a historical owner",
                    safe_message="该钉钉身份已有历史归属，只能由原人员恢复",
                    error_code="identity_restore_required",
                )
            if (
                str(existing["status"]) in {"unbound", "disabled"}
                and not restore_historical
            ):
                raise NonRetryableExecutionError(
                    "Historical DingTalk identity requires explicit restore",
                    safe_message="请通过匹配的受信候选恢复该钉钉身份",
                    error_code="identity_restore_required",
                )
            if str(existing["status"]) == "enabled":
                return existing
        current = self.database.execute_one(
            """
            select * from user_external_identity
             where provider = 'dingtalk' and user_id = ?
               and dingtalk_enterprise_id = ?
               and status in ('enabled', 'disabled')
            """,
            (user_id, dingtalk_enterprise_id),
        )
        timestamp = now_iso()
        replacing_other = bool(
            current
            and (
                existing is None
                or str(current["id"]) != str(existing["id"])
            )
        )
        if replacing_other and not replace_current:
            raise NonRetryableExecutionError(
                "Explicit confirmation is required to replace DingTalk identity",
                safe_message="该人员在此钉钉企业已有身份，请确认换绑影响",
                error_code="dingtalk_rebind_confirmation_required",
            )
        if replacing_other and current:
            self.database.execute(
                """
                update user_external_identity
                   set status = 'unbound', revision = revision + 1, updated_at = ?
                 where id = ? and status in ('enabled', 'disabled')
                """,
                (timestamp, current["id"]),
            )
        if existing is not None:
            self.database.execute(
                """
                update user_external_identity
                   set status = 'enabled', verified_at = ?,
                       metadata_json = ?, revision = revision + 1,
                       updated_at = ?
                 where id = ? and user_id = ?
                """,
                (
                    timestamp,
                    json.dumps(
                        {"verification_method": "trusted_candidate_restore"},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    timestamp,
                    existing["id"],
                    user_id,
                ),
            )
            if source_ingress_event_id:
                self.record_dingtalk_message_facts(
                    identity_id=str(existing["id"]),
                    connector_id=source_connector_id,
                    source_ingress_event_id=source_ingress_event_id,
                    nickname=display_name.strip(),
                    occurred_at=observed_at,
                    received_at=observed_at,
                )
            return self.get_external_identity(str(existing["id"]))
        identity_id = new_id("identity")
        nickname = display_name.strip()
        nickname_time = observed_at or timestamp
        self.database.execute(
            """
            insert into user_external_identity
              (id, user_id, provider, tenant_code, external_subject_id,
               connector_id, union_id, open_id, display_name, status,
               verified_at, last_seen_at, metadata_json, revision,
               created_at, updated_at, dingtalk_enterprise_id,
               display_name_observed_at, display_name_event_id,
               display_name_source_connector_id)
            values (?, ?, 'dingtalk', ?, ?, '', '', '', ?, 'enabled',
                    ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
            """,
            (
                identity_id,
                user_id,
                dingtalk_enterprise_id,
                external_subject_id,
                nickname,
                timestamp,
                nickname_time,
                json.dumps(
                    {"verification_method": "trusted_candidate"},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                timestamp,
                timestamp,
                dingtalk_enterprise_id,
                nickname_time if nickname else None,
                source_ingress_event_id if nickname else "",
                source_connector_id if nickname else "",
            ),
        )
        if source_ingress_event_id:
            self.record_dingtalk_message_facts(
                identity_id=identity_id,
                connector_id=source_connector_id,
                source_ingress_event_id=source_ingress_event_id,
                nickname=nickname,
                occurred_at=nickname_time,
                received_at=nickname_time,
            )
        return self.get_external_identity(identity_id)

    def record_dingtalk_message_facts(
        self,
        *,
        identity_id: str,
        connector_id: str,
        source_ingress_event_id: str,
        nickname: str,
        occurred_at: str,
        received_at: str,
    ) -> None:
        timestamp = now_iso()
        observed_at = _trusted_dingtalk_event_time(
            occurred_at=occurred_at,
            received_at=received_at,
        )
        self.database.execute(
            """
            update user_external_identity
               set last_seen_at = case
                     when last_seen_at is null or last_seen_at < ? then ?
                     else last_seen_at end,
                   revision = revision + 1,
                   updated_at = ?
             where id = ? and provider = 'dingtalk'
            """,
            (observed_at, observed_at, timestamp, identity_id),
        )
        observation = self.database.execute_one(
            """
            select * from dingtalk_identity_application_observation
             where external_identity_id = ? and connector_id = ?
            """,
            (identity_id, connector_id),
        )
        if observation is None:
            self.database.execute(
                """
                insert into dingtalk_identity_application_observation
                  (id, external_identity_id, connector_id, first_observed_at,
                   last_observed_at, last_ingress_event_id, revision,
                   created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    new_id("dingtalk_identity_observation"),
                    identity_id,
                    connector_id,
                    observed_at,
                    observed_at,
                    source_ingress_event_id,
                    timestamp,
                    timestamp,
                ),
            )
        elif (
            str(observation["last_ingress_event_id"]) != source_ingress_event_id
            and (observed_at, source_ingress_event_id)
            > (
                str(observation["last_observed_at"]),
                str(observation["last_ingress_event_id"]),
            )
        ):
            self.database.execute(
                """
                update dingtalk_identity_application_observation
                   set first_observed_at = case
                         when first_observed_at > ? then ? else first_observed_at end,
                       last_observed_at = ?, last_ingress_event_id = ?,
                       revision = revision + 1, updated_at = ?
                 where id = ?
                """,
                (
                    observed_at,
                    observed_at,
                    observed_at,
                    source_ingress_event_id,
                    timestamp,
                    observation["id"],
                ),
            )
        normalized_nickname = nickname.strip()
        if not normalized_nickname:
            return
        identity = self.database.execute_one(
            "select * from user_external_identity where id = ?",
            (identity_id,),
        )
        if identity is None:
            raise NotFound("External identity not found", safe_message="未找到身份")
        current_cursor = (
            str(identity.get("display_name_observed_at") or ""),
            str(identity.get("display_name_event_id") or ""),
        )
        incoming_cursor = (observed_at, source_ingress_event_id)
        if incoming_cursor <= current_cursor:
            return
        previous = str(identity.get("display_name") or "")
        if previous != normalized_nickname:
            self.database.execute(
                """
                insert into dingtalk_identity_nickname_audit
                  (id, external_identity_id, connector_id,
                   source_ingress_event_id, previous_nickname,
                   current_nickname, observed_at, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(source_ingress_event_id) do nothing
                """,
                (
                    new_id("dingtalk_nickname_audit"),
                    identity_id,
                    connector_id,
                    source_ingress_event_id,
                    previous,
                    normalized_nickname,
                    observed_at,
                    timestamp,
                ),
            )
        self.database.execute(
            """
            update user_external_identity
               set display_name = ?, display_name_observed_at = ?,
                   display_name_event_id = ?,
                   display_name_source_connector_id = ?,
                   revision = revision + 1, updated_at = ?
             where id = ?
               and (coalesce(display_name_observed_at, ''), display_name_event_id)
                   < (?, ?)
            """,
            (
                normalized_nickname,
                observed_at,
                source_ingress_event_id,
                connector_id,
                timestamp,
                identity_id,
                observed_at,
                source_ingress_event_id,
            ),
        )

    def list_dingtalk_application_observations(
        self, identity_id: str
    ) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select o.first_observed_at, o.last_observed_at,
                   c.name as application_name
              from dingtalk_identity_application_observation o
              join integration_connector c on c.id = o.connector_id
             where o.external_identity_id = ?
             order by c.name, c.id
            """,
            (identity_id,),
        )

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
        if status not in {"enabled", "disabled"}:
            raise NonRetryableExecutionError(
                "Invalid external identity status",
                safe_message="身份状态无效",
                error_code="identity_status_invalid",
            )
        current = self.get_external_identity(identity_id)
        if (
            current["provider"] == "dingtalk"
            and current["status"] == "unbound"
            and status == "enabled"
        ):
            raise NonRetryableExecutionError(
                "Unbound DingTalk identity requires a trusted candidate",
                safe_message="已解绑钉钉身份只能通过匹配的受信候选恢复",
                error_code="identity_restore_required",
            )
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
                safe_message="身份信息已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )
        return self.get_external_identity(identity_id)

    def unbind_external_identity(
        self,
        identity_id: str,
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        rows = self.database.execute(
            """
            update user_external_identity
            set status = 'unbound', revision = revision + 1, updated_at = ?
            where id = ? and revision = ?
            returning id
            """,
            (now_iso(), identity_id, expected_revision),
        )
        if not rows:
            if self.database.execute_one(
                "select id from user_external_identity where id = ?",
                (identity_id,),
            ):
                raise NonRetryableExecutionError(
                    "Identity revision conflict",
                    safe_message="身份信息已发生变化，请刷新后重试",
                    error_code="revision_conflict",
                )
            raise NotFound("External identity not found", safe_message="未找到身份")
        return self.get_external_identity(identity_id)

    def create_role(
        self,
        *,
        code: str,
        name: str,
        description: str = "",
        origin: str = "custom",
        protected: bool = False,
        purpose_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        role_id = new_id("role")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into rbac_role
              (id, code, name, description, status, revision, origin, protected,
               purpose_tags_json, metadata_revision, admin_revision,
               business_revision, membership_revision, created_at, updated_at)
            values (?, ?, ?, ?, 'enabled', 1, ?, ?, ?, 1, 1, 1, 1, ?, ?)
            """,
            (
                role_id,
                code,
                name,
                description,
                origin,
                int(protected),
                json.dumps(purpose_tags or [], ensure_ascii=False, separators=(",", ":")),
                timestamp,
                timestamp,
            ),
        )
        return self.get_role(role_id)

    def list_roles(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where status = 'enabled'"
        return self.database.execute(f"select * from rbac_role {where} order by code")

    def get_role(self, role_id: str) -> dict[str, Any]:
        row = self.database.execute_one("select * from rbac_role where id = ?", (role_id,))
        if not row:
            raise NotFound("Role not found", safe_message="未找到角色")
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
        current = self.get_role(role_id)
        if bool(current.get("protected")) and status != str(current["status"]):
            raise NonRetryableExecutionError(
                "Protected role status cannot be changed",
                safe_message="受保护系统角色不能停用",
                error_code="protected_role",
            )
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
                safe_message="角色已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )
        return self.get_role(role_id)

    def assign_role(
        self,
        *,
        user_id: str,
        role_id: str,
        expected_revision: int | None = None,
        expires_at: str | None = None,
        assigned_by: str = "",
        assignment_source: str = "manual",
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
                    safe_message="角色成员关系已发生变化，请刷新后重试",
                    error_code="revision_conflict",
                )
            self.database.execute(
                """
                update rbac_user_role
                set status = 'enabled', expires_at = ?, assigned_by = ?,
                    assignment_source = ?, revision = revision + 1, updated_at = ?
                where id = ?
                """,
                (
                    expires_at,
                    assigned_by,
                    assignment_source,
                    timestamp,
                    existing["id"],
                ),
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
                safe_message="角色成员关系已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )
        membership_id = new_id("membership")
        self.database.execute(
            """
            insert into rbac_user_role
              (id, user_id, role_id, status, revision, expires_at, assigned_by,
               assignment_source, created_at, updated_at)
            values (?, ?, ?, 'enabled', 1, ?, ?, ?, ?, ?)
            """,
            (
                membership_id,
                user_id,
                role_id,
                expires_at,
                assigned_by,
                assignment_source,
                timestamp,
                timestamp,
            ),
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
                safe_message="角色成员关系已发生变化，请刷新后重试",
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
              and (ur.expires_at is null or ur.expires_at > ?)
            order by r.code
            """,
            (user_id, now_iso()),
        )
        return tuple(str(row["code"]) for row in rows)

    def list_user_roles(self, user_id: str) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select r.id, r.code, r.name, r.description, r.status, r.origin,
                   r.protected, r.purpose_tags_json,
                   ur.id as membership_id, ur.status as membership_status,
                   ur.revision as membership_revision, ur.expires_at,
                   ur.assigned_by, ur.assignment_source
            from rbac_user_role ur
            join rbac_role r on r.id = ur.role_id
            where ur.user_id = ?
            order by r.code
            """,
            (user_id,),
        )

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
                safe_message="服务账号不能创建登录会话",
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
              and (ur.expires_at is null or ur.expires_at > ?)
            """
            ,
            (now_iso(),),
        )
        return int(row["count"]) if row else 0

    def lock_platform_admin_invariant(self) -> None:
        if self.database.engine == "postgres":
            self.database.execute(
                """
                select id
                  from rbac_role
                 where code = 'platform-admin'
                   for update
                """
            )
            return
        # SQLite has no row-level FOR UPDATE. A no-op write acquires its
        # database write lock so independent application connections serialize
        # the check-and-mutate sequence.
        self.database.execute(
            """
            update rbac_role
               set updated_at = updated_at
             where code = 'platform-admin'
            """
        )

    def is_verified_human_platform_admin(self, user_id: str) -> bool:
        return (
            self.database.execute_one(
                """
                select u.id
                  from app_user u
                  join rbac_user_role ur on ur.user_id = u.id
                  join rbac_role r on r.id = ur.role_id
                 where u.id = ?
                   and u.status = 'enabled'
                   and u.account_type = 'human'
                   and r.code = 'platform-admin'
                   and r.status = 'enabled'
                   and ur.status = 'enabled'
                   and (ur.expires_at is null or ur.expires_at > ?)
                   and exists (
                       select 1
                         from user_password_credential pc
                        where pc.user_id = u.id
                          and pc.password_hash <> ''
                   )
                   and exists (
                       select 1
                         from user_session s
                        where s.user_id = u.id
                   )
                """,
                (user_id, now_iso()),
            )
            is not None
        )

    def verified_human_platform_admin_count(self) -> int:
        row = self.database.execute_one(
            """
            select count(*) as count
              from app_user u
              join rbac_user_role ur on ur.user_id = u.id
              join rbac_role r on r.id = ur.role_id
             where u.status = 'enabled'
               and u.account_type = 'human'
               and r.code = 'platform-admin'
               and r.status = 'enabled'
               and ur.status = 'enabled'
               and (ur.expires_at is null or ur.expires_at > ?)
               and exists (
                   select 1
                     from user_password_credential pc
                    where pc.user_id = u.id
                      and pc.password_hash <> ''
               )
               and exists (
                   select 1
                     from user_session s
                    where s.user_id = u.id
               )
            """,
            (now_iso(),),
        )
        return int(row["count"]) if row else 0

    def require_verified_human_platform_admins(self, minimum: int = 2) -> None:
        if self.verified_human_platform_admin_count() < minimum:
            raise NonRetryableExecutionError(
                "Platform administrator invariant would be violated",
                safe_message="系统必须至少保留两名已完成登录验证的启用人类平台管理员",
                error_code="platform_admin_invariant",
            )

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

    def list_role_members(self, role_id: str) -> list[dict[str, Any]]:
        self.get_role(role_id)
        return self.database.execute(
            """
            select u.id, u.username, u.display_name, u.email, u.status,
                   u.account_type,
                   ur.id as membership_id, ur.status as membership_status,
                   ur.revision as membership_revision, ur.expires_at,
                   ur.assigned_by, ur.assignment_source
            from rbac_user_role ur
            join app_user u on u.id = ur.user_id
            where ur.role_id = ?
            order by u.username
            """,
            (role_id,),
        )

    def _external_public(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "provider": row["provider"],
            "tenant_code": row["tenant_code"],
            "dingtalk_enterprise_id": str(
                row.get("dingtalk_enterprise_id") or ""
            ),
            "external_subject_id": row["external_subject_id"],
            "connector_id": row.get("connector_id") or "",
            "union_id": row.get("union_id") or "",
            "open_id": row.get("open_id") or "",
            "display_name": row.get("display_name") or "",
            "status": row["status"],
            "verified_at": row.get("verified_at"),
            "last_seen_at": row.get("last_seen_at"),
            "metadata": self._identity_metadata(
                str(row["provider"]),
                _json_object(row.get("metadata_json")),
            ),
            "revision": int(row.get("revision") or 1),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "username": row.get("username") or "",
            "user_display_name": row.get("user_display_name") or "",
            "user_status": row.get("user_status") or "",
        }

    @staticmethod
    def _identity_metadata(provider: str, metadata: dict[str, Any]) -> dict[str, Any]:
        normalized_provider = ExternalIdentityProvider.require_supported(provider).value
        verification_method = str(metadata.get("verification_method") or "")
        result: dict[str, Any] = {}
        if verification_method:
            result["verification_method"] = verification_method
        if normalized_provider == ExternalIdentityProvider.ONES.value:
            team_uuids = metadata.get("team_uuids")
            normalized_team_ids: list[str] = []
            if isinstance(team_uuids, (list, tuple)):
                normalized_team_ids = list(
                    dict.fromkeys(
                        str(value).strip()
                        for value in team_uuids
                        if str(value).strip()
                    )
                )
                result["team_uuids"] = normalized_team_ids
            teams = metadata.get("teams")
            normalized_teams: list[dict[str, str]] = []
            seen_team_ids: set[str] = set()
            if isinstance(teams, (list, tuple)):
                for team in teams:
                    if not isinstance(team, dict):
                        continue
                    team_id = str(team.get("id") or "").strip()
                    if not team_id or team_id in seen_team_ids:
                        continue
                    seen_team_ids.add(team_id)
                    normalized_teams.append(
                        {
                            "id": team_id,
                            "name": str(team.get("name") or "").strip(),
                        }
                    )
            for team_id in normalized_team_ids:
                if team_id not in seen_team_ids:
                    normalized_teams.append({"id": team_id, "name": ""})
            if normalized_teams:
                result["teams"] = normalized_teams
            default_team_id = str(metadata.get("default_team_id") or "").strip()
            if default_team_id:
                result["default_team_id"] = default_team_id
        return result

    @staticmethod
    def _user_search_clause(
        *,
        include_disabled: bool,
        search: str,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if not include_disabled:
            clauses.append("u.status = 'enabled'")
        term = search.strip().lower()
        if term:
            pattern = f"%{term}%"
            clauses.append(
                """
                (
                  lower(u.username) like ?
                  or lower(u.display_name) like ?
                  or lower(u.email) like ?
                  or exists (
                    select 1
                    from user_external_identity i
                    where i.user_id = u.id
                      and (
                        lower(i.display_name) like ?
                        or lower(i.external_subject_id) like ?
                      )
                  )
                )
                """
            )
            params.extend((pattern, pattern, pattern, pattern, pattern))
        return (
            f"where {' and '.join(clauses)}" if clauses else "",
            params,
        )


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


def _trusted_dingtalk_event_time(*, occurred_at: str, received_at: str) -> str:
    received = _parse_utc(received_at) or datetime.now(UTC)
    occurred = _parse_utc(occurred_at)
    if occurred is None or abs(occurred - received) > timedelta(hours=24):
        occurred = received
    return occurred.isoformat()


def _parse_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
