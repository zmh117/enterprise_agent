from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class PlatformConfigRepository:
    """Persistence retained for encrypted Secrets and runtime bootstrap facts only."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_platform_secret(
        self,
        *,
        code: str,
        provider: str,
        ref: str,
        purpose: str = "",
        status: str = "enabled",
        active_version: int = 0,
        masked_summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_platform_secret_by_code(code)
        timestamp = now_iso()
        if existing:
            self.database.execute(
                """
                update platform_secret
                   set provider = ?, ref = ?, purpose = ?, status = ?,
                       active_version = ?, masked_summary = ?, metadata_json = ?,
                       revision = revision + 1, updated_at = ?
                 where id = ?
                """,
                (
                    provider,
                    ref,
                    purpose,
                    status,
                    active_version,
                    masked_summary,
                    json_text(metadata or {}),
                    timestamp,
                    existing["id"],
                ),
            )
            return self.get_platform_secret(str(existing["id"]))
        entity_id = new_id("platform_secret")
        self.database.execute(
            """
            insert into platform_secret
              (id, code, provider, ref, purpose, status, active_version,
               masked_summary, metadata_json, revision, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                entity_id,
                code,
                provider,
                ref,
                purpose,
                status,
                active_version,
                masked_summary,
                json_text(metadata or {}),
                timestamp,
                timestamp,
            ),
        )
        return self.get_platform_secret(entity_id)

    def list_platform_secrets(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where s.status = 'enabled'"
        rows = self.database.execute(
            f"""
            select s.*,
              exists(
                select 1 from platform_secret_version v
                 where v.secret_id = s.id
                   and v.version = s.active_version
                   and v.status = 'active'
              ) as active_version_present
              from platform_secret s
              {where}
             order by s.code
            """
        )
        return [self._parse_platform_secret(row) for row in rows]

    def get_platform_secret(self, secret_id: str) -> dict[str, Any]:
        row = self._get_platform_secret("s.id = ?", secret_id)
        if not row:
            raise NotFound(f"Platform secret not found: {secret_id}")
        return self._parse_platform_secret(row)

    def get_platform_secret_by_code(self, code: str) -> dict[str, Any] | None:
        row = self._get_platform_secret("s.code = ?", code)
        return self._parse_platform_secret(row) if row else None

    def get_platform_secret_by_ref(self, ref: str) -> dict[str, Any] | None:
        row = self._get_platform_secret("s.ref = ?", ref)
        return self._parse_platform_secret(row) if row else None

    def _get_platform_secret(self, predicate: str, value: str) -> dict[str, Any] | None:
        return self.database.execute_one(
            f"""
            select s.*,
              exists(
                select 1 from platform_secret_version v
                 where v.secret_id = s.id
                   and v.version = s.active_version
                   and v.status = 'active'
              ) as active_version_present
              from platform_secret s
             where {predicate}
            """,
            (value,),
        )

    def insert_secret_version(
        self,
        *,
        secret_id: str,
        version: int,
        ciphertext: str,
        nonce: str,
        key_id: str,
        algorithm: str,
        status: str = "staged",
        created_by: str = "",
    ) -> dict[str, Any]:
        entity_id = new_id("secret_version")
        self.database.execute(
            """
            insert into platform_secret_version
              (id, secret_id, version, ciphertext, nonce, key_id, algorithm,
               status, created_by, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                secret_id,
                version,
                ciphertext,
                nonce,
                key_id,
                algorithm,
                status,
                created_by,
                now_iso(),
            ),
        )
        return self.get_secret_version(entity_id)

    def get_secret_version(self, version_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from platform_secret_version where id = ?", (version_id,)
        )
        if not row:
            raise NotFound(f"Platform secret version not found: {version_id}")
        return self._parse_secret_version(row)

    def get_secret_version_number(self, *, secret_id: str, version: int) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from platform_secret_version
             where secret_id = ? and version = ?
            """,
            (secret_id, version),
        )
        return self._parse_secret_version(row) if row else None

    def get_active_secret_version(self, secret_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select v.* from platform_secret_version v
              join platform_secret s
                on s.id = v.secret_id and s.active_version = v.version
             where v.secret_id = ? and v.status = 'active'
            """,
            (secret_id,),
        )
        return self._parse_secret_version(row) if row else None

    def set_secret_active_version(
        self,
        *,
        secret_id: str,
        active_version: int,
        masked_summary: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        staged = self.get_secret_version_number(secret_id=secret_id, version=active_version)
        if not staged or staged["status"] not in {"staged", "active"}:
            raise NotFound(
                f"Staged platform secret version not found: {secret_id}/{active_version}"
            )
        self.database.execute(
            """
            update platform_secret_version set status = 'superseded'
             where secret_id = ? and version <> ? and status = 'active'
            """,
            (secret_id, active_version),
        )
        self.database.execute(
            """
            update platform_secret_version set status = 'active'
             where secret_id = ? and version = ?
            """,
            (secret_id, active_version),
        )
        where = "id = ?" if expected_revision is None else "id = ? and revision = ?"
        params: tuple[Any, ...] = (
            active_version,
            masked_summary,
            now_iso(),
            secret_id,
            *((expected_revision,) if expected_revision is not None else ()),
        )
        changed = self.database.execute(
            f"""
            update platform_secret
               set active_version = ?, masked_summary = ?, status = 'enabled',
                   revision = revision + 1, updated_at = ?
             where {where}
             returning id
            """,
            params,
        )
        if not changed:
            raise self._revision_conflict()
        return self.get_platform_secret(secret_id)

    def set_platform_secret_status(
        self, code: str, status: str, *, expected_revision: int | None = None
    ) -> dict[str, Any]:
        existing = self.get_platform_secret_by_code(code)
        if not existing:
            raise NotFound(f"Platform secret not found: {code}")
        where = "id = ?" if expected_revision is None else "id = ? and revision = ?"
        changed = self.database.execute(
            f"""
            update platform_secret
               set status = ?, revision = revision + 1, updated_at = ?
             where {where}
             returning id
            """,
            (
                status,
                now_iso(),
                existing["id"],
                *((expected_revision,) if expected_revision is not None else ()),
            ),
        )
        if not changed:
            raise self._revision_conflict()
        if status == "disabled":
            self.database.execute(
                """
                update platform_secret_version set status = 'disabled'
                 where secret_id = ? and status = 'active'
                """,
                (existing["id"],),
            )
        return self.get_platform_secret(str(existing["id"]))

    def insert_secret_change_event(
        self, *, secret_id: str, secret_revision: int, action: str
    ) -> dict[str, Any]:
        event_id = new_id("secret_change")
        self.database.execute(
            """
            insert into platform_secret_change_event
              (id, secret_id, secret_revision, action, status, attempt_count,
               error_summary, created_at)
            values (?, ?, ?, ?, 'PENDING', 0, '', ?)
            on conflict(secret_id, secret_revision, action) do nothing
            """,
            (event_id, secret_id, secret_revision, action, now_iso()),
        )
        row = self.database.execute_one(
            """
            select * from platform_secret_change_event
             where secret_id = ? and secret_revision = ? and action = ?
            """,
            (secret_id, secret_revision, action),
        )
        if not row:
            raise NotFound("Platform secret change event was not persisted")
        return row

    def claim_secret_change_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        pending = self.database.execute(
            """
            select id from platform_secret_change_event
             where status = 'PENDING'
             order by created_at, id limit ?
            """,
            (max(1, min(int(limit), 200)),),
        )
        claimed: list[dict[str, Any]] = []
        for item in pending:
            rows = self.database.execute(
                """
                update platform_secret_change_event
                   set status = 'RUNNING', attempt_count = attempt_count + 1,
                       claimed_at = ?
                 where id = ? and status = 'PENDING'
                 returning *
                """,
                (now_iso(), item["id"]),
            )
            if rows:
                claimed.append(rows[0])
        return claimed

    def complete_secret_change_event(
        self, *, event_id: str, succeeded: bool, error_summary: str = ""
    ) -> None:
        self.database.execute(
            """
            update platform_secret_change_event
               set status = ?, error_summary = ?, processed_at = ?
             where id = ? and status = 'RUNNING'
            """,
            (
                "SUCCEEDED" if succeeded else "FAILED",
                "" if succeeded else str(error_summary or "resource reload failed")[:200],
                now_iso(),
                event_id,
            ),
        )

    def list_secret_change_events(self, *, secret_id: str | None = None) -> list[dict[str, Any]]:
        if secret_id:
            return self.database.execute(
                """
                select * from platform_secret_change_event
                 where secret_id = ? order by created_at, id
                """,
                (secret_id,),
            )
        return self.database.execute(
            "select * from platform_secret_change_event order by created_at, id"
        )

    def upsert_runtime_config_definition(
        self,
        *,
        key: str,
        value_type: str,
        default: Any = None,
        sensitive: bool = False,
        bootstrap_only: bool = False,
        service_names: list[str] | None = None,
        description: str = "",
        status: str = "enabled",
    ) -> dict[str, Any]:
        existing = self.get_runtime_config_definition(key)
        timestamp = now_iso()
        values = (
            value_type,
            json_text(default),
            int(sensitive),
            int(bootstrap_only),
            json_text(service_names or []),
            description,
            status,
        )
        if existing:
            self.database.execute(
                """
                update platform_runtime_config_definition
                   set value_type = ?, default_json = ?, sensitive = ?,
                       bootstrap_only = ?, service_names_json = ?,
                       description = ?, status = ?, revision = revision + 1,
                       updated_at = ?
                 where id = ?
                """,
                (*values, timestamp, existing["id"]),
            )
        else:
            self.database.execute(
                """
                insert into platform_runtime_config_definition
                  (id, key, value_type, default_json, sensitive, bootstrap_only,
                   service_names_json, description, status, revision,
                   created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (new_id("runtime_def"), key, *values, timestamp, timestamp),
            )
        return self._require_runtime_config_definition(key)

    def list_runtime_config_definitions(
        self, *, include_disabled: bool = True
    ) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where status = 'enabled'"
        rows = self.database.execute(
            f"select * from platform_runtime_config_definition {where} order by key"
        )
        return [self._parse_runtime_config_definition(row) for row in rows]

    def get_runtime_config_definition(self, key: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            "select * from platform_runtime_config_definition where key = ?", (key,)
        )
        return self._parse_runtime_config_definition(row) if row else None

    def _require_runtime_config_definition(self, key: str) -> dict[str, Any]:
        value = self.get_runtime_config_definition(key)
        if not value:
            raise NotFound(f"Runtime config definition not found: {key}")
        return value

    def upsert_runtime_config_value(
        self,
        *,
        key: str,
        scope_type: str = "global",
        scope_code: str = "*",
        service_name: str = "",
        value: Any = None,
        secret_ref: str = "",
        status: str = "enabled",
    ) -> dict[str, Any]:
        definition = self._require_runtime_config_definition(key)
        existing = self.find_runtime_config_value(
            key=key,
            scope_type=scope_type,
            scope_code=scope_code,
            service_name=service_name,
        )
        timestamp = now_iso()
        values = (
            definition["id"],
            key,
            scope_type,
            scope_code,
            service_name,
            json_text(value),
            secret_ref,
            status,
        )
        if existing:
            self.database.execute(
                """
                update platform_runtime_config_value
                   set definition_id = ?, key = ?, scope_type = ?, scope_code = ?,
                       service_name = ?, value_json = ?, secret_ref = ?, status = ?,
                       revision = revision + 1, updated_at = ?
                 where id = ?
                """,
                (*values, timestamp, existing["id"]),
            )
            return self.get_runtime_config_value(str(existing["id"]))
        entity_id = new_id("runtime_cfg")
        self.database.execute(
            """
            insert into platform_runtime_config_value
              (id, definition_id, key, scope_type, scope_code, service_name,
               value_json, secret_ref, status, revision, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (entity_id, *values, timestamp, timestamp),
        )
        return self.get_runtime_config_value(entity_id)

    def list_runtime_config_values(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where v.status = 'enabled'"
        rows = self.database.execute(
            f"""
            select v.*, d.value_type, d.sensitive, d.bootstrap_only, d.default_json
              from platform_runtime_config_value v
              join platform_runtime_config_definition d on d.id = v.definition_id
              {where}
             order by v.key, v.scope_type, v.scope_code, v.service_name
            """
        )
        return [self._parse_runtime_config_value(row) for row in rows]

    def get_runtime_config_value(self, value_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select v.*, d.value_type, d.sensitive, d.bootstrap_only, d.default_json
              from platform_runtime_config_value v
              join platform_runtime_config_definition d on d.id = v.definition_id
             where v.id = ?
            """,
            (value_id,),
        )
        if not row:
            raise NotFound(f"Runtime config value not found: {value_id}")
        return self._parse_runtime_config_value(row)

    def find_runtime_config_value(
        self, *, key: str, scope_type: str, scope_code: str, service_name: str
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select v.*, d.value_type, d.sensitive, d.bootstrap_only, d.default_json
              from platform_runtime_config_value v
              join platform_runtime_config_definition d on d.id = v.definition_id
             where v.key = ? and v.scope_type = ? and v.scope_code = ?
               and v.service_name = ?
            """,
            (key, scope_type, scope_code, service_name),
        )
        return self._parse_runtime_config_value(row) if row else None

    def set_runtime_config_value_status(self, value_id: str, status: str) -> dict[str, Any]:
        self.database.execute(
            """
            update platform_runtime_config_value
               set status = ?, revision = revision + 1, updated_at = ?
             where id = ?
            """,
            (status, now_iso(), value_id),
        )
        return self.get_runtime_config_value(value_id)

    def runtime_config_revision(self) -> int:
        row = self.database.execute_one(
            """
            select coalesce(max(revision), 0) as revision from (
              select revision from platform_runtime_config_definition
              union all select revision from platform_runtime_config_value
              union all select revision from platform_secret
            ) revisions
            """
        )
        return int(row["revision"]) if row else 0

    def record_config_audit(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        actor_id: str = "",
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        correlation_id: str = "",
    ) -> str:
        audit_id = new_id("config_audit")
        self.database.execute(
            """
            insert into platform_config_audit
              (id, entity_type, entity_id, action, actor_id, before_json,
               after_json, correlation_id, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                entity_type,
                entity_id,
                action,
                actor_id,
                json_text(before or {}),
                json_text(after or {}),
                correlation_id,
                now_iso(),
            ),
        )
        return audit_id

    def list_config_audit(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select * from platform_config_audit
             order by created_at desc, id desc limit ?
            """,
            (max(1, min(int(limit), 500)),),
        )
        return [self._parse_audit(row) for row in rows]

    @staticmethod
    def _revision_conflict() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "Platform Secret revision conflict",
            safe_message="凭据已被其他操作更新，请重新读取后重试",
            error_code="revision_conflict",
        )

    def _parse_platform_secret(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "active_version": int(row.get("active_version") or 0),
            "metadata": self._json_from_text(row.get("metadata_json") or "{}"),
            "revision": int(row.get("revision") or 0),
            "configured": row.get("status") == "enabled"
            and bool(row.get("active_version_present")),
        }

    @staticmethod
    def _parse_secret_version(row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "version": int(row.get("version") or 0)}

    def _parse_runtime_config_definition(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "default": self._json_from_text(row.get("default_json") or "null"),
            "sensitive": bool(int(row.get("sensitive") or 0)),
            "bootstrap_only": bool(int(row.get("bootstrap_only") or 0)),
            "service_names": self._json_from_text(row.get("service_names_json") or "[]"),
            "revision": int(row.get("revision") or 0),
        }

    def _parse_runtime_config_value(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "value": self._json_from_text(row.get("value_json") or "null"),
            "sensitive": bool(int(row.get("sensitive") or 0)),
            "bootstrap_only": bool(int(row.get("bootstrap_only") or 0)),
            "default": self._json_from_text(row.get("default_json") or "null"),
            "revision": int(row.get("revision") or 0),
        }

    def _parse_audit(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "before": self._json_from_text(row.get("before_json") or "{}"),
            "after": self._json_from_text(row.get("after_json") or "{}"),
        }

    @staticmethod
    def _json_from_text(value: str) -> Any:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
