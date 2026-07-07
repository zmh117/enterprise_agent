from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.shared.database import Database
from app.shared.exceptions import NotFound


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class PlatformConfigRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_environment(
        self,
        *,
        code: str,
        display_name: str = "",
        status: str = "enabled",
        aliases: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_environment_by_code(code)
        timestamp = now_iso()
        if existing:
            self.database.execute(
                """
                update platform_environment
                set display_name = ?, status = ?, aliases_json = ?, metadata_json = ?,
                    revision = revision + 1, updated_at = ?
                where id = ?
                """,
                (
                    display_name,
                    status,
                    json_text(aliases or []),
                    json_text(metadata or {}),
                    timestamp,
                    existing["id"],
                ),
            )
            return self.get_environment(existing["id"])
        entity_id = new_id("env")
        self.database.execute(
            """
            insert into platform_environment
              (id, code, display_name, status, aliases_json, metadata_json, revision,
               created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                code,
                display_name,
                status,
                json_text(aliases or []),
                json_text(metadata or {}),
                1,
                timestamp,
                timestamp,
            ),
        )
        return self.get_environment(entity_id)

    def list_environments(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where status = 'enabled'"
        rows = self.database.execute(f"select * from platform_environment {where} order by code")
        return [self._parse_environment(row) for row in rows]

    def get_environment(self, environment_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from platform_environment where id = ?", (environment_id,)
        )
        if not row:
            raise NotFound(f"Platform environment not found: {environment_id}")
        return self._parse_environment(row)

    def get_environment_by_code(self, code: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            "select * from platform_environment where code = ?", (code,)
        )
        return self._parse_environment(row) if row else None

    def set_environment_status(self, code: str, status: str) -> dict[str, Any]:
        existing = self.get_environment_by_code(code)
        if not existing:
            raise NotFound(f"Platform environment not found: {code}")
        self.database.execute(
            """
            update platform_environment
            set status = ?, revision = revision + 1, updated_at = ?
            where id = ?
            """,
            (status, now_iso(), existing["id"]),
        )
        return self.get_environment(existing["id"])

    def upsert_base(
        self,
        *,
        environment_code: str,
        code: str,
        engine: str,
        display_name: str = "",
        status: str = "enabled",
        aliases: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        environment = self._require_environment(environment_code)
        existing = self.get_base_by_code(environment_code=environment_code, code=code)
        timestamp = now_iso()
        if existing:
            self.database.execute(
                """
                update platform_base
                set display_name = ?, engine = ?, status = ?, aliases_json = ?,
                    metadata_json = ?, revision = revision + 1, updated_at = ?
                where id = ?
                """,
                (
                    display_name,
                    engine,
                    status,
                    json_text(aliases or []),
                    json_text(metadata or {}),
                    timestamp,
                    existing["id"],
                ),
            )
            return self.get_base(existing["id"])
        entity_id = new_id("base")
        self.database.execute(
            """
            insert into platform_base
              (id, environment_id, code, display_name, engine, status, aliases_json,
               metadata_json, revision, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                environment["id"],
                code,
                display_name,
                engine,
                status,
                json_text(aliases or []),
                json_text(metadata or {}),
                1,
                timestamp,
                timestamp,
            ),
        )
        return self.get_base(entity_id)

    def list_bases(
        self, *, environment_code: str | None = None, include_disabled: bool = True
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if environment_code:
            clauses.append("e.code = ?")
            params.append(environment_code)
        if not include_disabled:
            clauses.append("b.status = 'enabled'")
        where = f"where {' and '.join(clauses)}" if clauses else ""
        rows = self.database.execute(
            f"""
            select b.*, e.code as environment_code
            from platform_base b
            join platform_environment e on e.id = b.environment_id
            {where}
            order by e.code, b.code
            """,
            params,
        )
        return [self._parse_base(row) for row in rows]

    def get_base(self, base_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select b.*, e.code as environment_code
            from platform_base b
            join platform_environment e on e.id = b.environment_id
            where b.id = ?
            """,
            (base_id,),
        )
        if not row:
            raise NotFound(f"Platform base not found: {base_id}")
        return self._parse_base(row)

    def get_base_by_code(self, *, environment_code: str, code: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select b.*, e.code as environment_code
            from platform_base b
            join platform_environment e on e.id = b.environment_id
            where e.code = ? and b.code = ?
            """,
            (environment_code, code),
        )
        return self._parse_base(row) if row else None

    def set_base_status(self, *, environment_code: str, code: str, status: str) -> dict[str, Any]:
        existing = self.get_base_by_code(environment_code=environment_code, code=code)
        if not existing:
            raise NotFound(f"Platform base not found: {environment_code}/{code}")
        self.database.execute(
            "update platform_base set status = ?, revision = revision + 1, updated_at = ? where id = ?",
            (status, now_iso(), existing["id"]),
        )
        return self.get_base(existing["id"])

    def upsert_workshop(
        self,
        *,
        environment_code: str,
        base_code: str,
        code: str,
        display_name: str = "",
        table_prefix: str = "",
        redis_key_prefix: str = "",
        loki_labels: dict[str, str] | None = None,
        status: str = "enabled",
        aliases: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = self._require_base(environment_code=environment_code, code=base_code)
        existing = self.get_workshop_by_code(
            environment_code=environment_code, base_code=base_code, code=code
        )
        timestamp = now_iso()
        if existing:
            self.database.execute(
                """
                update platform_workshop
                set display_name = ?, table_prefix = ?, redis_key_prefix = ?,
                    loki_labels_json = ?, status = ?, aliases_json = ?, metadata_json = ?,
                    revision = revision + 1, updated_at = ?
                where id = ?
                """,
                (
                    display_name,
                    table_prefix,
                    redis_key_prefix,
                    json_text(loki_labels or {}),
                    status,
                    json_text(aliases or []),
                    json_text(metadata or {}),
                    timestamp,
                    existing["id"],
                ),
            )
            return self.get_workshop(existing["id"])
        entity_id = new_id("workshop")
        self.database.execute(
            """
            insert into platform_workshop
              (id, base_id, code, display_name, table_prefix, redis_key_prefix,
               loki_labels_json, status, aliases_json, metadata_json, revision,
               created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                base["id"],
                code,
                display_name,
                table_prefix,
                redis_key_prefix,
                json_text(loki_labels or {}),
                status,
                json_text(aliases or []),
                json_text(metadata or {}),
                1,
                timestamp,
                timestamp,
            ),
        )
        return self.get_workshop(entity_id)

    def list_workshops(
        self,
        *,
        environment_code: str | None = None,
        base_code: str | None = None,
        include_disabled: bool = True,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if environment_code:
            clauses.append("e.code = ?")
            params.append(environment_code)
        if base_code:
            clauses.append("b.code = ?")
            params.append(base_code)
        if not include_disabled:
            clauses.append("w.status = 'enabled'")
        where = f"where {' and '.join(clauses)}" if clauses else ""
        rows = self.database.execute(
            f"""
            select w.*, b.code as base_code, e.code as environment_code
            from platform_workshop w
            join platform_base b on b.id = w.base_id
            join platform_environment e on e.id = b.environment_id
            {where}
            order by e.code, b.code, w.code
            """,
            params,
        )
        return [self._parse_workshop(row) for row in rows]

    def get_workshop(self, workshop_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select w.*, b.code as base_code, e.code as environment_code
            from platform_workshop w
            join platform_base b on b.id = w.base_id
            join platform_environment e on e.id = b.environment_id
            where w.id = ?
            """,
            (workshop_id,),
        )
        if not row:
            raise NotFound(f"Platform workshop not found: {workshop_id}")
        return self._parse_workshop(row)

    def get_workshop_by_code(
        self, *, environment_code: str, base_code: str, code: str
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select w.*, b.code as base_code, e.code as environment_code
            from platform_workshop w
            join platform_base b on b.id = w.base_id
            join platform_environment e on e.id = b.environment_id
            where e.code = ? and b.code = ? and w.code = ?
            """,
            (environment_code, base_code, code),
        )
        return self._parse_workshop(row) if row else None

    def set_workshop_status(
        self, *, environment_code: str, base_code: str, code: str, status: str
    ) -> dict[str, Any]:
        existing = self.get_workshop_by_code(
            environment_code=environment_code, base_code=base_code, code=code
        )
        if not existing:
            raise NotFound(f"Platform workshop not found: {environment_code}/{base_code}/{code}")
        self.database.execute(
            """
            update platform_workshop
            set status = ?, revision = revision + 1, updated_at = ?
            where id = ?
            """,
            (status, now_iso(), existing["id"]),
        )
        return self.get_workshop(existing["id"])

    def upsert_secret_reference(
        self,
        *,
        code: str,
        provider: str,
        ref: str,
        purpose: str = "",
        status: str = "enabled",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_secret_reference_by_code(code)
        timestamp = now_iso()
        if existing:
            self.database.execute(
                """
                update platform_secret_reference
                set provider = ?, ref = ?, purpose = ?, status = ?, metadata_json = ?,
                    revision = revision + 1, updated_at = ?
                where id = ?
                """,
                (
                    provider,
                    ref,
                    purpose,
                    status,
                    json_text(metadata or {}),
                    timestamp,
                    existing["id"],
                ),
            )
            return self.get_secret_reference(existing["id"])
        entity_id = new_id("secret")
        self.database.execute(
            """
            insert into platform_secret_reference
              (id, code, provider, ref, purpose, status, metadata_json, revision,
               created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                code,
                provider,
                ref,
                purpose,
                status,
                json_text(metadata or {}),
                1,
                timestamp,
                timestamp,
            ),
        )
        return self.get_secret_reference(entity_id)

    def list_secret_references(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where status = 'enabled'"
        rows = self.database.execute(
            f"select * from platform_secret_reference {where} order by code"
        )
        return [self._parse_secret_reference(row) for row in rows]

    def get_secret_reference(self, secret_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from platform_secret_reference where id = ?", (secret_id,)
        )
        if not row:
            raise NotFound(f"Platform secret reference not found: {secret_id}")
        return self._parse_secret_reference(row)

    def get_secret_reference_by_code(self, code: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            "select * from platform_secret_reference where code = ?", (code,)
        )
        return self._parse_secret_reference(row) if row else None

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
                set provider = ?, ref = ?, purpose = ?, status = ?, active_version = ?,
                    masked_summary = ?, metadata_json = ?, revision = revision + 1,
                    updated_at = ?
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
            return self.get_platform_secret(existing["id"])
        entity_id = new_id("platform_secret")
        self.database.execute(
            """
            insert into platform_secret
              (id, code, provider, ref, purpose, status, active_version,
               masked_summary, metadata_json, revision, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                1,
                timestamp,
                timestamp,
            ),
        )
        return self.get_platform_secret(entity_id)

    def list_platform_secrets(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where status = 'enabled'"
        rows = self.database.execute(f"select * from platform_secret {where} order by code")
        return [self._parse_platform_secret(row) for row in rows]

    def get_platform_secret(self, secret_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from platform_secret where id = ?", (secret_id,)
        )
        if not row:
            raise NotFound(f"Platform secret not found: {secret_id}")
        return self._parse_platform_secret(row)

    def get_platform_secret_by_code(self, code: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            "select * from platform_secret where code = ?", (code,)
        )
        return self._parse_platform_secret(row) if row else None

    def get_platform_secret_by_ref(self, ref: str) -> dict[str, Any] | None:
        row = self.database.execute_one("select * from platform_secret where ref = ?", (ref,))
        return self._parse_platform_secret(row) if row else None

    def insert_secret_version(
        self,
        *,
        secret_id: str,
        version: int,
        ciphertext: str,
        nonce: str,
        key_id: str,
        algorithm: str,
        status: str = "active",
        created_by: str = "",
    ) -> dict[str, Any]:
        entity_id = new_id("secret_version")
        self.database.execute(
            """
            insert into platform_secret_version
              (id, secret_id, version, ciphertext, nonce, key_id, algorithm, status,
               created_by, created_at)
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

    def get_active_secret_version(self, secret_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select v.*
            from platform_secret_version v
            join platform_secret s on s.id = v.secret_id and s.active_version = v.version
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
    ) -> dict[str, Any]:
        self.database.execute(
            """
            update platform_secret_version
            set status = 'superseded'
            where secret_id = ? and version <> ? and status = 'active'
            """,
            (secret_id, active_version),
        )
        self.database.execute(
            """
            update platform_secret_version
            set status = 'active'
            where secret_id = ? and version = ?
            """,
            (secret_id, active_version),
        )
        self.database.execute(
            """
            update platform_secret
            set active_version = ?, masked_summary = ?, status = 'enabled',
                revision = revision + 1, updated_at = ?
            where id = ?
            """,
            (active_version, masked_summary, now_iso(), secret_id),
        )
        return self.get_platform_secret(secret_id)

    def set_platform_secret_status(self, code: str, status: str) -> dict[str, Any]:
        existing = self.get_platform_secret_by_code(code)
        if not existing:
            raise NotFound(f"Platform secret not found: {code}")
        self.database.execute(
            """
            update platform_secret
            set status = ?, revision = revision + 1, updated_at = ?
            where id = ?
            """,
            (status, now_iso(), existing["id"]),
        )
        if status == "disabled":
            self.database.execute(
                """
                update platform_secret_version
                set status = 'disabled'
                where secret_id = ? and status = 'active'
                """,
                (existing["id"],),
            )
        return self.get_platform_secret(existing["id"])

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
        params = (
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
                set value_type = ?, default_json = ?, sensitive = ?, bootstrap_only = ?,
                    service_names_json = ?, description = ?, status = ?,
                    revision = revision + 1, updated_at = ?
                where id = ?
                """,
                (*params, timestamp, existing["id"]),
            )
            return self._require_runtime_config_definition(key)
        entity_id = new_id("runtime_def")
        self.database.execute(
            """
            insert into platform_runtime_config_definition
              (id, key, value_type, default_json, sensitive, bootstrap_only,
               service_names_json, description, status, revision, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entity_id, key, *params, 1, timestamp, timestamp),
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
        definition = self.get_runtime_config_definition(key)
        if not definition:
            raise NotFound(f"Runtime config definition not found: {key}")
        return definition

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
        definition = self.get_runtime_config_definition(key)
        if not definition:
            raise NotFound(f"Runtime config definition not found: {key}")
        existing = self.find_runtime_config_value(
            key=key, scope_type=scope_type, scope_code=scope_code, service_name=service_name
        )
        timestamp = now_iso()
        params = (
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
                (*params, timestamp, existing["id"]),
            )
            return self.get_runtime_config_value(existing["id"])
        entity_id = new_id("runtime_cfg")
        self.database.execute(
            """
            insert into platform_runtime_config_value
              (id, definition_id, key, scope_type, scope_code, service_name,
               value_json, secret_ref, status, revision, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entity_id, *params, 1, timestamp, timestamp),
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
            where v.key = ? and v.scope_type = ? and v.scope_code = ? and v.service_name = ?
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

    def upsert_resource_binding(
        self,
        *,
        code: str,
        scope_type: str,
        resource_kind: str,
        environment_code: str | None = None,
        base_code: str | None = None,
        workshop_code: str | None = None,
        connector_id: str | None = None,
        engine: str | None = None,
        config: dict[str, Any] | None = None,
        secret_refs: dict[str, str] | None = None,
        status: str = "enabled",
    ) -> dict[str, Any]:
        environment_id, base_id, workshop_id = self.resolve_scope_ids(
            environment_code=environment_code, base_code=base_code, workshop_code=workshop_code
        )
        existing = self.get_resource_binding_by_code(code)
        timestamp = now_iso()
        params = (
            scope_type,
            environment_id,
            base_id,
            workshop_id,
            resource_kind,
            connector_id,
            engine,
            json_text(config or {}),
            json_text(secret_refs or {}),
            status,
        )
        if existing:
            self.database.execute(
                """
                update platform_resource_binding
                set scope_type = ?, environment_id = ?, base_id = ?, workshop_id = ?,
                    resource_kind = ?, connector_id = ?, engine = ?, config_json = ?,
                    secret_refs_json = ?, status = ?, revision = revision + 1,
                    updated_at = ?
                where id = ?
                """,
                (*params, timestamp, existing["id"]),
            )
            return self.get_resource_binding(existing["id"])
        entity_id = new_id("resource")
        self.database.execute(
            """
            insert into platform_resource_binding
              (id, code, scope_type, environment_id, base_id, workshop_id, resource_kind,
               connector_id, engine, config_json, secret_refs_json, status, revision,
               created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entity_id, code, *params, 1, timestamp, timestamp),
        )
        return self.get_resource_binding(entity_id)

    def list_resource_bindings(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where r.status = 'enabled'"
        rows = self.database.execute(
            f"""
            select r.*, e.code as environment_code, b.code as base_code, w.code as workshop_code
            from platform_resource_binding r
            left join platform_environment e on e.id = r.environment_id
            left join platform_base b on b.id = r.base_id
            left join platform_workshop w on w.id = r.workshop_id
            {where}
            order by r.code
            """
        )
        return [self._parse_resource_binding(row) for row in rows]

    def get_resource_binding(self, binding_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select r.*, e.code as environment_code, b.code as base_code, w.code as workshop_code
            from platform_resource_binding r
            left join platform_environment e on e.id = r.environment_id
            left join platform_base b on b.id = r.base_id
            left join platform_workshop w on w.id = r.workshop_id
            where r.id = ?
            """,
            (binding_id,),
        )
        if not row:
            raise NotFound(f"Platform resource binding not found: {binding_id}")
        return self._parse_resource_binding(row)

    def get_resource_binding_by_code(self, code: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select r.*, e.code as environment_code, b.code as base_code, w.code as workshop_code
            from platform_resource_binding r
            left join platform_environment e on e.id = r.environment_id
            left join platform_base b on b.id = r.base_id
            left join platform_workshop w on w.id = r.workshop_id
            where r.code = ?
            """,
            (code,),
        )
        return self._parse_resource_binding(row) if row else None

    def set_resource_binding_status(self, code: str, status: str) -> dict[str, Any]:
        existing = self.get_resource_binding_by_code(code)
        if not existing:
            raise NotFound(f"Platform resource binding not found: {code}")
        self.database.execute(
            """
            update platform_resource_binding
            set status = ?, revision = revision + 1, updated_at = ?
            where id = ?
            """,
            (status, now_iso(), existing["id"]),
        )
        return self.get_resource_binding(existing["id"])

    def upsert_access_grant(
        self,
        *,
        subject_type: str,
        subject_code: str,
        effect: str,
        environment_code: str | None = None,
        base_code: str | None = None,
        workshop_code: str | None = None,
        tool_scope: list[str] | None = None,
        resource_scope: dict[str, Any] | None = None,
        condition: dict[str, Any] | None = None,
        priority: int = 100,
        status: str = "enabled",
    ) -> dict[str, Any]:
        environment_id, base_id, workshop_id = self.resolve_scope_ids(
            environment_code=environment_code,
            base_code=base_code,
            workshop_code=workshop_code,
            allow_wildcard=True,
        )
        existing = self.find_access_grant(
            subject_type=subject_type,
            subject_code=subject_code,
            effect=effect,
            environment_id=environment_id,
            base_id=base_id,
            workshop_id=workshop_id,
        )
        timestamp = now_iso()
        params = (
            subject_type,
            subject_code,
            effect,
            environment_id,
            base_id,
            workshop_id,
            json_text(tool_scope or []),
            json_text(resource_scope or {}),
            json_text(condition or {}),
            priority,
            status,
        )
        if existing:
            self.database.execute(
                """
                update platform_access_grant
                set subject_type = ?, subject_code = ?, effect = ?, environment_id = ?,
                    base_id = ?, workshop_id = ?, tool_scope_json = ?,
                    resource_scope_json = ?, condition_json = ?, priority = ?, status = ?,
                    revision = revision + 1, updated_at = ?
                where id = ?
                """,
                (*params, timestamp, existing["id"]),
            )
            return self.get_access_grant(existing["id"])
        entity_id = new_id("grant")
        self.database.execute(
            """
            insert into platform_access_grant
              (id, subject_type, subject_code, effect, environment_id, base_id,
               workshop_id, tool_scope_json, resource_scope_json, condition_json,
               priority, status, revision, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entity_id, *params, 1, timestamp, timestamp),
        )
        return self.get_access_grant(entity_id)

    def list_access_grants(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where g.status = 'enabled'"
        rows = self.database.execute(
            f"""
            select g.*, e.code as environment_code, b.code as base_code, w.code as workshop_code
            from platform_access_grant g
            left join platform_environment e on e.id = g.environment_id
            left join platform_base b on b.id = g.base_id
            left join platform_workshop w on w.id = g.workshop_id
            {where}
            order by g.subject_code, g.priority, g.id
            """
        )
        return [self._parse_access_grant(row) for row in rows]

    def get_access_grant(self, grant_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select g.*, e.code as environment_code, b.code as base_code, w.code as workshop_code
            from platform_access_grant g
            left join platform_environment e on e.id = g.environment_id
            left join platform_base b on b.id = g.base_id
            left join platform_workshop w on w.id = g.workshop_id
            where g.id = ?
            """,
            (grant_id,),
        )
        if not row:
            raise NotFound(f"Platform access grant not found: {grant_id}")
        return self._parse_access_grant(row)

    def find_access_grant(
        self,
        *,
        subject_type: str,
        subject_code: str,
        effect: str,
        environment_id: str | None,
        base_id: str | None,
        workshop_id: str | None,
    ) -> dict[str, Any] | None:
        scope_clauses: list[str] = []
        scope_params: list[Any] = []
        for column, value in (
            ("g.environment_id", environment_id),
            ("g.base_id", base_id),
            ("g.workshop_id", workshop_id),
        ):
            if value is None:
                scope_clauses.append(f"{column} is null")
            else:
                scope_clauses.append(f"{column} = ?")
                scope_params.append(value)
        row = self.database.execute_one(
            f"""
            select g.*, e.code as environment_code, b.code as base_code, w.code as workshop_code
            from platform_access_grant g
            left join platform_environment e on e.id = g.environment_id
            left join platform_base b on b.id = g.base_id
            left join platform_workshop w on w.id = g.workshop_id
            where g.subject_type = ?
              and g.subject_code = ?
              and g.effect = ?
              and {" and ".join(scope_clauses)}
            limit 1
            """,
            (
                subject_type,
                subject_code,
                effect,
                *scope_params,
            ),
        )
        return self._parse_access_grant(row) if row else None

    def set_access_grant_status(self, grant_id: str, status: str) -> dict[str, Any]:
        self.database.execute(
            """
            update platform_access_grant
            set status = ?, revision = revision + 1, updated_at = ?
            where id = ?
            """,
            (status, now_iso(), grant_id),
        )
        return self.get_access_grant(grant_id)

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
              (id, entity_type, entity_id, action, actor_id, before_json, after_json,
               correlation_id, created_at)
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
            order by created_at desc, id desc
            limit ?
            """,
            (limit,),
        )
        return [self._parse_audit(row) for row in rows]

    def has_enabled_topology(self) -> bool:
        row = self.database.execute_one(
            "select count(*) as count from platform_environment where status = 'enabled'"
        )
        return bool(row and int(row["count"]) > 0)

    def topology_revision(self) -> int:
        row = self.database.execute_one(
            """
            select coalesce(max(revision), 0) as revision from (
              select revision from platform_environment
              union all select revision from platform_base
              union all select revision from platform_workshop
              union all select revision from platform_resource_binding
              union all select revision from platform_access_grant
            ) revisions
            """
        )
        return int(row["revision"]) if row else 0

    def resolve_scope_ids(
        self,
        *,
        environment_code: str | None,
        base_code: str | None,
        workshop_code: str | None,
        allow_wildcard: bool = False,
    ) -> tuple[str | None, str | None, str | None]:
        if allow_wildcard and environment_code in {None, "", "*"}:
            return None, None, None
        environment = self._require_environment(str(environment_code or ""))
        if not base_code or base_code == "*":
            return environment["id"], None, None
        base = self._require_base(environment_code=environment["code"], code=base_code)
        if not workshop_code or workshop_code == "*":
            return environment["id"], base["id"], None
        workshop = self._require_workshop(
            environment_code=environment["code"], base_code=base["code"], code=workshop_code
        )
        return environment["id"], base["id"], workshop["id"]

    def _require_environment(self, code: str) -> dict[str, Any]:
        environment = self.get_environment_by_code(code)
        if not environment:
            raise NotFound(f"Platform environment not found: {code}")
        return environment

    def _require_base(self, *, environment_code: str, code: str) -> dict[str, Any]:
        base = self.get_base_by_code(environment_code=environment_code, code=code)
        if not base:
            raise NotFound(f"Platform base not found: {environment_code}/{code}")
        return base

    def _require_workshop(
        self, *, environment_code: str, base_code: str, code: str
    ) -> dict[str, Any]:
        workshop = self.get_workshop_by_code(
            environment_code=environment_code, base_code=base_code, code=code
        )
        if not workshop:
            raise NotFound(f"Platform workshop not found: {environment_code}/{base_code}/{code}")
        return workshop

    def _parse_environment(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "aliases": self._json_from_text(row.get("aliases_json") or "[]"),
            "metadata": self._json_from_text(row.get("metadata_json") or "{}"),
            "revision": int(row.get("revision") or 0),
        }

    def _parse_base(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "aliases": self._json_from_text(row.get("aliases_json") or "[]"),
            "metadata": self._json_from_text(row.get("metadata_json") or "{}"),
            "revision": int(row.get("revision") or 0),
        }

    def _parse_workshop(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "aliases": self._json_from_text(row.get("aliases_json") or "[]"),
            "metadata": self._json_from_text(row.get("metadata_json") or "{}"),
            "loki_labels": self._json_from_text(row.get("loki_labels_json") or "{}"),
            "revision": int(row.get("revision") or 0),
        }

    def _parse_secret_reference(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "metadata": self._json_from_text(row.get("metadata_json") or "{}"),
            "revision": int(row.get("revision") or 0),
        }

    def _parse_platform_secret(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "active_version": int(row.get("active_version") or 0),
            "metadata": self._json_from_text(row.get("metadata_json") or "{}"),
            "revision": int(row.get("revision") or 0),
            "configured": row.get("status") == "enabled" and int(row.get("active_version") or 0) > 0,
        }

    def _parse_secret_version(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "version": int(row.get("version") or 0),
        }

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

    def _parse_resource_binding(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "config": self._json_from_text(row.get("config_json") or "{}"),
            "secret_refs": self._json_from_text(row.get("secret_refs_json") or "{}"),
            "revision": int(row.get("revision") or 0),
        }

    def _parse_access_grant(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "tool_scope": self._json_from_text(row.get("tool_scope_json") or "[]"),
            "resource_scope": self._json_from_text(row.get("resource_scope_json") or "{}"),
            "condition": self._json_from_text(row.get("condition_json") or "{}"),
            "priority": int(row.get("priority") or 100),
            "revision": int(row.get("revision") or 0),
        }

    def _parse_audit(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "before": self._json_from_text(row.get("before_json") or "{}"),
            "after": self._json_from_text(row.get("after_json") or "{}"),
        }

    def _json_from_text(self, value: str) -> Any:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
