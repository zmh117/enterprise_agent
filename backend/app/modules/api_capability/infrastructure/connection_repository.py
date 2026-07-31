from __future__ import annotations

import builtins
import json
from typing import Any

from app.modules.api_capability.domain.contracts import content_hash
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


class ApiConnectionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        *,
        code: str,
        name: str,
        provider: str,
        origin: dict[str, Any],
        authentication: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        connection_id = new_id("api_connection")
        profile_id = new_id("api_auth_profile")
        timestamp = now_iso()
        aggregate_hash = self._aggregate_hash(origin, authentication)
        profile_hash = content_hash(authentication)
        with self.database.unit_of_work():
            self.database.execute(
                """
                insert into api_connection
                  (id, code, name, provider, created_by, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    connection_id,
                    code,
                    name,
                    provider,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
            self.database.execute(
                """
                insert into api_authentication_profile
                  (id, connection_id, code, name, created_by, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    connection_id,
                    f"{code}-authentication",
                    f"{name} Authentication",
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
            self.database.execute(
                """
                insert into api_connection_draft
                  (id, connection_id, draft_revision, origin_scheme,
                   origin_host, origin_port, allow_insecure_local_http,
                   connect_timeout_ms, read_timeout_ms, max_response_bytes,
                   content_hash, status, created_by, updated_by,
                   created_at, updated_at)
                values (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?)
                """,
                (
                    new_id("api_connection_draft"),
                    connection_id,
                    origin["scheme"],
                    origin["host"],
                    int(origin["port"]),
                    int(bool(origin.get("allow_insecure_local_http", False))),
                    int(origin.get("connect_timeout_ms", 3000)),
                    int(origin.get("read_timeout_ms", 10000)),
                    int(origin.get("max_response_bytes", 1048576)),
                    aggregate_hash,
                    actor_id,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
            self.database.execute(
                """
                insert into api_authentication_profile_draft
                  (id, profile_id, draft_revision, config_json, content_hash,
                   status, created_by, updated_by, created_at, updated_at)
                values (?, ?, 1, ?, ?, 'DRAFT', ?, ?, ?, ?)
                """,
                (
                    new_id("api_auth_profile_draft"),
                    profile_id,
                    _json_text(authentication),
                    profile_hash,
                    actor_id,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
        return self.get(connection_id)

    def get(self, connection_id: str) -> dict[str, Any]:
        connection = self.database.execute_one(
            "select * from api_connection where id = ?",
            (connection_id,),
        )
        if connection is None:
            raise NotFound(
                "API Connection not found",
                safe_message="未找到 API Connection",
            )
        profile = self.database.execute_one(
            "select * from api_authentication_profile where connection_id = ?",
            (connection_id,),
        )
        draft = self.database.execute_one(
            "select * from api_connection_draft where connection_id = ?",
            (connection_id,),
        )
        profile_draft = (
            self.database.execute_one(
                """
                select * from api_authentication_profile_draft
                 where profile_id = ?
                """,
                (str(profile["id"]),),
            )
            if profile
            else None
        )
        return {
            **connection,
            "revision": int(connection["revision"]),
            "authentication_profile": profile,
            "draft": self._draft(draft, profile_draft),
            "published_revisions": self.list_revisions(connection_id),
        }

    def list(self) -> list[dict[str, Any]]:
        rows = self.database.execute("select id from api_connection order by code")
        return [self.get(str(row["id"])) for row in rows]

    def list_revisions(
        self,
        connection_id: str,
    ) -> builtins.list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select r.*, p.config_json as authentication_config_json,
                   p.content_hash as authentication_content_hash,
                   p.status as authentication_status
              from api_connection_revision r
              join api_authentication_profile_revision p
                on p.id = r.authentication_profile_revision_id
             where r.connection_id = ?
             order by r.revision desc
            """,
            (connection_id,),
        )
        return [
            {
                **row,
                "revision": int(row["revision"]),
                "authentication": _json_value(row.get("authentication_config_json")),
            }
            for row in rows
        ]

    def latest_published_revision(self) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select r.id
              from api_connection_revision r
              join api_connection c on c.id = r.connection_id
             where c.provider = 'ones' and c.status = 'enabled'
               and r.status = 'PUBLISHED'
             order by r.published_at desc, r.revision desc
             limit 1
            """
        )
        if row is None:
            raise NotFound(
                "Published ONES Connection Revision not found",
                safe_message="尚未发布可用的 ONES Connection",
            )
        return self.get_revision(str(row["id"]))

    def save_draft(
        self,
        connection_id: str,
        *,
        expected_revision: int,
        origin: dict[str, Any],
        authentication: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.get(connection_id)
        draft = current.get("draft") or {}
        if int(draft.get("draft_revision") or 0) != expected_revision:
            raise self._revision_conflict()
        timestamp = now_iso()
        aggregate_hash = self._aggregate_hash(origin, authentication)
        profile = current["authentication_profile"]
        with self.database.unit_of_work():
            updated = self.database.execute(
                """
                update api_connection_draft
                   set draft_revision = draft_revision + 1,
                       origin_scheme = ?, origin_host = ?, origin_port = ?,
                       allow_insecure_local_http = ?,
                       connect_timeout_ms = ?, read_timeout_ms = ?,
                       max_response_bytes = ?, content_hash = ?,
                       status = 'DRAFT', updated_by = ?, updated_at = ?
                 where connection_id = ? and draft_revision = ?
                 returning id
                """,
                (
                    origin["scheme"],
                    origin["host"],
                    int(origin["port"]),
                    int(bool(origin.get("allow_insecure_local_http", False))),
                    int(origin.get("connect_timeout_ms", 3000)),
                    int(origin.get("read_timeout_ms", 10000)),
                    int(origin.get("max_response_bytes", 1048576)),
                    aggregate_hash,
                    actor_id,
                    timestamp,
                    connection_id,
                    expected_revision,
                ),
            )
            if not updated:
                raise self._revision_conflict()
            self.database.execute(
                """
                update api_authentication_profile_draft
                   set draft_revision = draft_revision + 1,
                       config_json = ?, content_hash = ?, status = 'DRAFT',
                       updated_by = ?, updated_at = ?
                 where profile_id = ? and draft_revision = ?
                """,
                (
                    _json_text(authentication),
                    content_hash(authentication),
                    actor_id,
                    timestamp,
                    str(profile["id"]),
                    expected_revision,
                ),
            )
        return self.get(connection_id)

    def record_verification(
        self,
        connection_id: str,
        *,
        draft_revision: int,
        draft_hash: str,
        actor_id: str,
        status: str,
        checks: dict[str, Any],
        safe_error_summary: str = "",
    ) -> dict[str, Any]:
        current = self.get(connection_id)
        draft = current["draft"]
        if (
            int(draft["draft_revision"]) != draft_revision
            or str(draft["content_hash"]) != draft_hash
        ):
            raise self._revision_conflict()
        profile_draft = draft["authentication_profile"]
        verification_id = new_id("api_connection_verification")
        timestamp = now_iso()
        with self.database.unit_of_work():
            self.database.execute(
                """
                insert into api_connection_verification
                  (id, connection_id, connection_draft_id,
                   connection_draft_revision, profile_draft_id,
                   profile_draft_revision, content_hash, status, checks_json,
                   safe_error_summary, verified_by, verified_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verification_id,
                    connection_id,
                    str(draft["id"]),
                    draft_revision,
                    str(profile_draft["id"]),
                    int(profile_draft["draft_revision"]),
                    draft_hash,
                    status,
                    _json_text(checks),
                    safe_error_summary,
                    actor_id,
                    timestamp,
                ),
            )
            next_status = "VERIFIED" if status == "PASSED" else "DRAFT"
            self.database.execute(
                """
                update api_connection_draft set status = ?
                 where id = ? and draft_revision = ? and content_hash = ?
                """,
                (
                    next_status,
                    str(draft["id"]),
                    draft_revision,
                    draft_hash,
                ),
            )
            self.database.execute(
                """
                update api_authentication_profile_draft set status = ?
                 where id = ? and draft_revision = ?
                """,
                (
                    next_status,
                    str(profile_draft["id"]),
                    int(profile_draft["draft_revision"]),
                ),
            )
        return self.get_verification(verification_id)

    def get_verification(self, verification_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from api_connection_verification where id = ?",
            (verification_id,),
        )
        if row is None:
            raise NotFound(
                "API Connection verification not found",
                safe_message="未找到 API Connection 验证记录",
            )
        return {**row, "checks": _json_value(row.get("checks_json"))}

    def publish(
        self,
        connection_id: str,
        *,
        draft_revision: int,
        draft_hash: str,
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.get(connection_id)
        draft = current["draft"]
        if (
            str(draft["status"]) != "VERIFIED"
            or int(draft["draft_revision"]) != draft_revision
            or str(draft["content_hash"]) != draft_hash
        ):
            raise NonRetryableExecutionError(
                "API Connection Draft is not verified",
                safe_message="API Connection 草稿尚未验证或内容已变化",
                error_code="connection_not_verified",
            )
        verification = self.database.execute_one(
            """
            select * from api_connection_verification
             where connection_id = ? and connection_draft_revision = ?
               and content_hash = ? and status = 'PASSED'
             order by verified_at desc limit 1
            """,
            (connection_id, draft_revision, draft_hash),
        )
        if verification is None:
            raise NonRetryableExecutionError(
                "Matching API Connection verification is missing",
                safe_message="缺少与当前草稿匹配的验证证据",
                error_code="connection_verification_missing",
            )
        profile = current["authentication_profile"]
        profile_draft = draft["authentication_profile"]
        timestamp = now_iso()
        with self.database.unit_of_work():
            profile_revision = self._next_revision(
                "api_authentication_profile_revision",
                "profile_id",
                str(profile["id"]),
            )
            profile_revision_id = new_id("api_auth_profile_revision")
            self.database.execute(
                """
                insert into api_authentication_profile_revision
                  (id, profile_id, revision, schema_version, config_json,
                   content_hash, status, published_by, published_at)
                values (?, ?, ?, 1, ?, ?, 'PUBLISHED', ?, ?)
                """,
                (
                    profile_revision_id,
                    str(profile["id"]),
                    profile_revision,
                    _json_text(profile_draft["config"]),
                    str(profile_draft["content_hash"]),
                    actor_id,
                    timestamp,
                ),
            )
            connection_revision = self._next_revision(
                "api_connection_revision",
                "connection_id",
                connection_id,
            )
            revision_id = new_id("api_connection_revision")
            self.database.execute(
                """
                insert into api_connection_revision
                  (id, connection_id, revision, schema_version,
                   origin_scheme, origin_host, origin_port,
                   allow_insecure_local_http, connect_timeout_ms,
                   read_timeout_ms, max_response_bytes,
                   authentication_profile_revision_id, content_hash,
                   verification_id, status, published_by, published_at)
                values (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        'PUBLISHED', ?, ?)
                """,
                (
                    revision_id,
                    connection_id,
                    connection_revision,
                    str(draft["origin_scheme"]),
                    str(draft["origin_host"]),
                    int(draft["origin_port"]),
                    int(draft["allow_insecure_local_http"]),
                    int(draft["connect_timeout_ms"]),
                    int(draft["read_timeout_ms"]),
                    int(draft["max_response_bytes"]),
                    profile_revision_id,
                    draft_hash,
                    str(verification["id"]),
                    actor_id,
                    timestamp,
                ),
            )
        return self.get_revision(revision_id)

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select r.*, p.config_json as authentication_config_json,
                   p.content_hash as authentication_content_hash,
                   p.status as authentication_status
              from api_connection_revision r
              join api_authentication_profile_revision p
                on p.id = r.authentication_profile_revision_id
             where r.id = ?
            """,
            (revision_id,),
        )
        if row is None:
            raise NotFound(
                "API Connection Revision not found",
                safe_message="未找到 API Connection 发布版本",
            )
        return {
            **row,
            "revision": int(row["revision"]),
            "authentication": _json_value(row.get("authentication_config_json")),
        }

    def set_revision_status(
        self,
        revision_id: str,
        *,
        status: str,
        actor_id: str,
    ) -> dict[str, Any]:
        if status not in {"PUBLISHED", "DISABLED", "ARCHIVED"}:
            raise ValueError("Unsupported Connection Revision status")
        current = self.get_revision(revision_id)
        if str(current["status"]) == "ARCHIVED" and status != "ARCHIVED":
            raise NonRetryableExecutionError(
                "Archived Connection Revision cannot be restored",
                safe_message="已归档的 Connection Revision 不能恢复",
                error_code="connection_revision_archived",
            )
        timestamp = now_iso()
        fields = {
            "PUBLISHED": (
                "status = 'PUBLISHED', disabled_by = '', disabled_at = null",
                (),
            ),
            "DISABLED": (
                "status = 'DISABLED', disabled_by = ?, disabled_at = ?",
                (actor_id, timestamp),
            ),
            "ARCHIVED": (
                "status = 'ARCHIVED', archived_by = ?, archived_at = ?",
                (actor_id, timestamp),
            ),
        }
        assignment, params = fields[status]
        profile_revision_id = str(current["authentication_profile_revision_id"])
        with self.database.unit_of_work():
            self.database.execute(
                f"update api_connection_revision set {assignment} where id = ?",
                (*params, revision_id),
            )
            self.database.execute(
                f"""
                update api_authentication_profile_revision
                   set {assignment}
                 where id = ?
                """,
                (*params, profile_revision_id),
            )
        return self.get_revision(revision_id)

    def _next_revision(
        self,
        table: str,
        identity_column: str,
        identity_id: str,
    ) -> int:
        allowed = {
            ("api_connection_revision", "connection_id"),
            ("api_authentication_profile_revision", "profile_id"),
        }
        if (table, identity_column) not in allowed:
            raise ValueError("Unsupported revision table")
        row = self.database.execute_one(
            f"""
            select coalesce(max(revision), 0) + 1 as revision
              from {table} where {identity_column} = ?
            """,
            (identity_id,),
        )
        return int(row["revision"]) if row else 1

    @staticmethod
    def _aggregate_hash(
        origin: dict[str, Any],
        authentication: dict[str, Any],
    ) -> str:
        return content_hash(
            {
                "schema_version": 1,
                "connection": origin,
                "authentication_profile": authentication,
            }
        )

    @staticmethod
    def _draft(
        draft: dict[str, Any] | None,
        profile_draft: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if draft is None or profile_draft is None:
            return None
        return {
            **draft,
            "draft_revision": int(draft["draft_revision"]),
            "allow_insecure_local_http": bool(draft["allow_insecure_local_http"]),
            "authentication_profile": {
                **profile_draft,
                "draft_revision": int(profile_draft["draft_revision"]),
                "config": _json_value(profile_draft.get("config_json")),
            },
        }

    @staticmethod
    def _revision_conflict() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "API Connection Draft revision conflict",
            safe_message="API Connection 草稿已变化，请刷新后重试",
            error_code="revision_conflict",
        )


def _json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_value(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
