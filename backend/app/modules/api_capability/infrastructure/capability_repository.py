from __future__ import annotations

import json
from typing import Any

from app.modules.api_capability.domain import CapabilityIdentifier
from app.modules.api_capability.domain.contracts import content_hash
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


class ApiCapabilityRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        *,
        identifier: str,
        name: str,
        connection_revision_id: str,
        authentication_profile_revision_id: str,
        capability: dict[str, Any],
        handler: dict[str, Any],
        mapping_ast: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        CapabilityIdentifier(identifier)
        capability_id = new_id("api_capability")
        handler_id = new_id("api_handler")
        timestamp = now_iso()
        aggregate_hash = self.draft_content_hash(
            capability=capability,
            handler=handler,
            mapping_ast=mapping_ast,
            connection_revision_id=connection_revision_id,
            authentication_profile_revision_id=(authentication_profile_revision_id),
        )
        with self.database.unit_of_work():
            self.database.execute(
                """
                insert into api_capability
                  (id, identifier, name, created_by, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    capability_id,
                    identifier,
                    name,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
            self.database.execute(
                """
                insert into api_handler
                  (id, capability_id, executor_id, created_by,
                   created_at, updated_at)
                values (?, ?, 'http-json-v1', ?, ?, ?)
                """,
                (
                    handler_id,
                    capability_id,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
            self.database.execute(
                """
                insert into api_capability_draft
                  (id, capability_id, handler_id, draft_revision,
                   connection_revision_id,
                   authentication_profile_revision_id,
                   capability_json, handler_json, mapping_ast_json,
                   content_hash, status, created_by, updated_by,
                   created_at, updated_at)
                values (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?)
                """,
                (
                    new_id("api_capability_draft"),
                    capability_id,
                    handler_id,
                    connection_revision_id,
                    authentication_profile_revision_id,
                    _json_text(capability),
                    _json_text(handler),
                    _json_text(mapping_ast),
                    aggregate_hash,
                    actor_id,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
        return self.get(capability_id)

    def get(self, capability_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from api_capability where id = ?",
            (capability_id,),
        )
        if row is None:
            raise NotFound(
                "API Capability not found",
                safe_message="未找到 API Capability",
            )
        handler = self.database.execute_one(
            "select * from api_handler where capability_id = ?",
            (capability_id,),
        )
        draft = self.database.execute_one(
            "select * from api_capability_draft where capability_id = ?",
            (capability_id,),
        )
        return {
            **row,
            "revision": int(row["revision"]),
            "handler": handler,
            "draft": self._draft(draft),
            "releases": self.list_releases(capability_id),
        }

    def get_by_identifier(self, identifier: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select id from api_capability where identifier = ?",
            (identifier,),
        )
        if row is None:
            raise NotFound(
                "API Capability not found",
                safe_message="未找到 API Capability",
            )
        return self.get(str(row["id"]))

    def save_draft(
        self,
        capability_id: str,
        *,
        expected_revision: int,
        connection_revision_id: str,
        authentication_profile_revision_id: str,
        capability: dict[str, Any],
        handler: dict[str, Any],
        mapping_ast: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        aggregate_hash = self.draft_content_hash(
            capability=capability,
            handler=handler,
            mapping_ast=mapping_ast,
            connection_revision_id=connection_revision_id,
            authentication_profile_revision_id=(authentication_profile_revision_id),
        )
        rows = self.database.execute(
            """
            update api_capability_draft
               set draft_revision = draft_revision + 1,
                   connection_revision_id = ?,
                   authentication_profile_revision_id = ?,
                   capability_json = ?, handler_json = ?,
                   mapping_ast_json = ?, content_hash = ?,
                   status = 'DRAFT', updated_by = ?, updated_at = ?
             where capability_id = ? and draft_revision = ?
             returning id
            """,
            (
                connection_revision_id,
                authentication_profile_revision_id,
                _json_text(capability),
                _json_text(handler),
                _json_text(mapping_ast),
                aggregate_hash,
                actor_id,
                now_iso(),
                capability_id,
                expected_revision,
            ),
        )
        if not rows:
            raise self._revision_conflict()
        return self.get(capability_id)

    def record_verification(
        self,
        capability_id: str,
        *,
        draft_revision: int,
        draft_hash: str,
        external_identity_id: str,
        external_user_id: str,
        default_team_id: str,
        actor_id: str,
        status: str,
        result_summary: dict[str, Any],
        result_hash: str = "",
    ) -> dict[str, Any]:
        current = self.get(capability_id)
        draft = current["draft"]
        if (
            int(draft["draft_revision"]) != draft_revision
            or str(draft["content_hash"]) != draft_hash
        ):
            raise self._revision_conflict()
        verification_id = new_id("api_capability_verification")
        with self.database.unit_of_work():
            self.database.execute(
                """
                insert into api_capability_verification
                  (id, capability_id, draft_id, draft_revision, content_hash,
                   external_identity_id, external_user_id, default_team_id,
                   status, result_summary_json, result_hash,
                   verified_by, verified_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verification_id,
                    capability_id,
                    str(draft["id"]),
                    draft_revision,
                    draft_hash,
                    external_identity_id,
                    external_user_id,
                    default_team_id,
                    status,
                    _json_text(result_summary),
                    result_hash,
                    actor_id,
                    now_iso(),
                ),
            )
            self.database.execute(
                """
                update api_capability_draft set status = ?
                 where id = ? and draft_revision = ? and content_hash = ?
                """,
                (
                    "VERIFIED" if status == "PASSED" else "DRAFT",
                    str(draft["id"]),
                    draft_revision,
                    draft_hash,
                ),
            )
        return self.get_verification(verification_id)

    def get_verification(self, verification_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from api_capability_verification where id = ?",
            (verification_id,),
        )
        if row is None:
            raise NotFound(
                "Capability verification not found",
                safe_message="未找到 Capability 验证记录",
            )
        return {
            **row,
            "result_summary": _json_value(row.get("result_summary_json")),
        }

    def create_release(
        self,
        capability_id: str,
        *,
        draft_revision: int,
        draft_hash: str,
        idempotency_key: str,
        compiled_plan: dict[str, Any],
        compiled_plan_hash: str,
        actor_id: str,
        release_note: str = "",
    ) -> dict[str, Any]:
        existing = self.database.execute_one(
            """
            select id from api_capability_release
             where publication_idempotency_key = ?
            """,
            (idempotency_key,),
        )
        if existing:
            release = self.get_release(str(existing["id"]))
            if (
                str(release["capability_id"]) != capability_id
                or str(release["config_hash"]) != draft_hash
            ):
                raise NonRetryableExecutionError(
                    "Publication idempotency key was reused for other content",
                    safe_message="发布幂等键已用于其他 Capability 内容",
                    error_code="publication_idempotency_conflict",
                )
            return release
        current = self.get(capability_id)
        draft = current["draft"]
        if (
            str(draft["status"]) != "VERIFIED"
            or int(draft["draft_revision"]) != draft_revision
            or str(draft["content_hash"]) != draft_hash
        ):
            raise NonRetryableExecutionError(
                "Capability Draft is not verified",
                safe_message="Capability 草稿尚未验证或内容已变化",
                error_code="capability_not_verified",
            )
        verification = self.database.execute_one(
            """
            select id from api_capability_verification
             where capability_id = ? and draft_revision = ?
               and content_hash = ? and status = 'PASSED'
             order by verified_at desc limit 1
            """,
            (capability_id, draft_revision, draft_hash),
        )
        if verification is None:
            raise NonRetryableExecutionError(
                "Matching Capability verification is missing",
                safe_message="缺少与当前 Capability 草稿匹配的验证证据",
                error_code="capability_verification_missing",
            )
        timestamp = now_iso()
        capability_config = draft["capability"]
        handler_config = draft["handler"]
        with self.database.unit_of_work():
            self._lock_capability(capability_id)
            existing = self.database.execute_one(
                """
                select id from api_capability_release
                 where publication_idempotency_key = ?
                """,
                (idempotency_key,),
            )
            if existing:
                release = self.get_release(str(existing["id"]))
                if (
                    str(release["capability_id"]) != capability_id
                    or str(release["config_hash"]) != draft_hash
                ):
                    raise NonRetryableExecutionError(
                        "Publication idempotency key was reused for other content",
                        safe_message="发布幂等键已用于其他 Capability 内容",
                        error_code="publication_idempotency_conflict",
                    )
                return release
            capability_revision_id = self._find_or_create_capability_revision(
                capability_id=capability_id,
                identity=current,
                config=capability_config,
                actor_id=actor_id,
                timestamp=timestamp,
            )
            mapping_plan_id = self._find_or_create_mapping_plan(
                ast=draft["mapping_ast"],
                plan=compiled_plan,
                plan_hash=compiled_plan_hash,
                actor_id=actor_id,
                timestamp=timestamp,
            )
            handler_revision_id = self._create_handler_revision(
                handler_id=str(current["handler"]["id"]),
                draft=draft,
                config=handler_config,
                mapping_plan_id=mapping_plan_id,
                actor_id=actor_id,
                timestamp=timestamp,
            )
            release_revision = self._next_revision(
                "api_capability_release",
                "release_revision",
                "capability_id",
                capability_id,
            )
            release_id = new_id("api_capability_release")
            self.database.execute(
                """
                insert into api_capability_release
                  (id, capability_id, identifier, release_revision,
                   capability_revision_id, handler_revision_id,
                   connection_revision_id,
                   authentication_profile_revision_id, mapping_plan_id,
                   verification_id, config_hash,
                   publication_idempotency_key, status, release_note,
                   published_by, published_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?)
                """,
                (
                    release_id,
                    capability_id,
                    str(current["identifier"]),
                    release_revision,
                    capability_revision_id,
                    handler_revision_id,
                    str(draft["connection_revision_id"]),
                    str(draft["authentication_profile_revision_id"]),
                    mapping_plan_id,
                    str(verification["id"]),
                    draft_hash,
                    idempotency_key,
                    release_note,
                    actor_id,
                    timestamp,
                ),
            )
        return self.get_release(release_id)

    def _lock_capability(self, capability_id: str) -> None:
        suffix = " for update" if self.database.engine == "postgres" else ""
        row = self.database.execute_one(
            f"select id from api_capability where id = ?{suffix}",
            (capability_id,),
        )
        if row is None:
            raise NotFound(
                "API Capability not found",
                safe_message="未找到 API Capability",
            )

    def get_release(self, release_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select r.*, c.name, c.description, c.input_schema_json,
                   c.output_schema_json, c.operation_semantics,
                   c.data_classification, h.executor_id, h.method,
                   h.relative_path, h.graphql_document, p.plan_json,
                   p.schema_version as mapping_schema_version
              from api_capability_release r
              join api_capability_revision c
                on c.id = r.capability_revision_id
              join api_handler_revision h on h.id = r.handler_revision_id
              join api_compiled_mapping_plan p on p.id = r.mapping_plan_id
             where r.id = ?
            """,
            (release_id,),
        )
        if row is None:
            raise NotFound(
                "Capability Release not found",
                safe_message="未找到 Capability Release",
            )
        return {
            **row,
            "release_revision": int(row["release_revision"]),
            "input_schema": _json_value(row.get("input_schema_json")),
            "output_schema": _json_value(row.get("output_schema_json")),
            "mapping_plan": _json_value(row.get("plan_json")),
        }

    def list_releases(self, capability_id: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select id from api_capability_release
             where capability_id = ? order by release_revision desc
            """,
            (capability_id,),
        )
        return [self.get_release(str(row["id"])) for row in rows]

    def list_catalog(
        self,
        *,
        selectable_only: bool = False,
    ) -> list[dict[str, Any]]:
        clause = "where status = 'ACTIVE'" if selectable_only else ""
        rows = self.database.execute(
            f"""
            select id from api_capability_release
             {clause}
             order by identifier, release_revision desc
            """
        )
        return [self.get_release(str(row["id"])) for row in rows]

    def set_release_status(
        self,
        release_id: str,
        *,
        status: str,
        actor_id: str,
        reason: str = "",
        replacement_release_id: str = "",
    ) -> dict[str, Any]:
        if status not in {
            "ACTIVE",
            "DEPRECATED",
            "DISABLED",
            "ARCHIVED",
        }:
            raise ValueError("Unsupported Capability Release status")
        current = self.get_release(release_id)
        if str(current["status"]) == "ARCHIVED" and status != "ARCHIVED":
            raise NonRetryableExecutionError(
                "Archived Capability Release cannot be restored",
                safe_message="已归档的 Capability Release 不能恢复",
                error_code="capability_release_archived",
            )
        if status in {"DEPRECATED", "ARCHIVED"} and not reason.strip():
            raise NonRetryableExecutionError(
                "Release status reason is required",
                safe_message="请填写 Release 状态变更原因",
                error_code="release_status_reason_required",
            )
        replacement: dict[str, Any] | None = None
        if replacement_release_id:
            replacement = self.get_release(replacement_release_id)
            if (
                str(replacement["identifier"]) != str(current["identifier"])
                or str(replacement["status"]) != "ACTIVE"
            ):
                raise NonRetryableExecutionError(
                    "Replacement Release must be ACTIVE with same Identifier",
                    safe_message="替代 Release 必须是同 Identifier 的 ACTIVE 版本",
                    error_code="replacement_release_invalid",
                )
        if status == "ARCHIVED":
            dependency = self.database.execute_one(
                """
                select id from agent_publication_api_capability
                 where capability_release_id = ?
                union all
                select id
                  from business_application_publication_api_capability
                 where capability_release_id = ?
                limit 1
                """,
                (release_id, release_id),
            )
            if dependency:
                raise NonRetryableExecutionError(
                    "Capability Release is referenced by a publication",
                    safe_message="该 Release 已被发布快照引用，不能归档",
                    error_code="capability_release_in_use",
                )
        self.database.execute(
            """
            update api_capability_release
               set status = ?, deprecation_reason = ?,
                   replacement_release_id = ?,
                   status_updated_by = ?, status_updated_at = ?
             where id = ?
            """,
            (
                status,
                reason.strip(),
                replacement_release_id or None,
                actor_id,
                now_iso(),
                release_id,
            ),
        )
        return self.get_release(release_id)

    def copy_release_to_draft(
        self,
        release_id: str,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        release = self.get_release(release_id)
        mapping_plan = release["mapping_plan"]
        mapping_ast = {
            "schema_version": 1,
            "request": mapping_plan["request_plan"],
            "response": mapping_plan["response_plan"],
        }
        return self.save_draft(
            str(release["capability_id"]),
            expected_revision=expected_revision,
            connection_revision_id=str(release["connection_revision_id"]),
            authentication_profile_revision_id=str(release["authentication_profile_revision_id"]),
            capability={
                "name": str(release["name"]),
                "description": str(release["description"]),
                "operation_semantics": str(release["operation_semantics"]),
                "data_classification": str(release["data_classification"]),
                "input_schema": release["input_schema"],
                "output_schema": release["output_schema"],
            },
            handler={
                "method": str(release["method"]),
                "relative_path": str(release["relative_path"]),
                "graphql_document": str(release.get("graphql_document") or ""),
            },
            mapping_ast=mapping_ast,
            actor_id=actor_id,
        )

    @staticmethod
    def draft_content_hash(
        *,
        capability: dict[str, Any],
        handler: dict[str, Any],
        mapping_ast: dict[str, Any],
        connection_revision_id: str,
        authentication_profile_revision_id: str,
    ) -> str:
        return content_hash(
            {
                "schema_version": 1,
                "capability": capability,
                "handler": handler,
                "mapping_ast": mapping_ast,
                "connection_revision_id": connection_revision_id,
                "authentication_profile_revision_id": (authentication_profile_revision_id),
            }
        )

    def _find_or_create_capability_revision(
        self,
        *,
        capability_id: str,
        identity: dict[str, Any],
        config: dict[str, Any],
        actor_id: str,
        timestamp: str,
    ) -> str:
        revision_hash = content_hash(
            {
                "schema_version": 1,
                "identifier": str(identity["identifier"]),
                **config,
            }
        )
        existing = self.database.execute_one(
            """
            select id from api_capability_revision
             where capability_id = ? and content_hash = ?
            """,
            (capability_id, revision_hash),
        )
        if existing:
            return str(existing["id"])
        revision = self._next_revision(
            "api_capability_revision",
            "revision",
            "capability_id",
            capability_id,
        )
        revision_id = new_id("api_capability_revision")
        self.database.execute(
            """
            insert into api_capability_revision
              (id, capability_id, revision, schema_version, identifier,
               name, description, operation_semantics, data_classification,
               input_schema_json, output_schema_json, content_hash,
               published_by, published_at)
            values (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                capability_id,
                revision,
                str(identity["identifier"]),
                str(config["name"]),
                str(config["description"]),
                str(config["operation_semantics"]),
                str(config["data_classification"]),
                _json_text(config["input_schema"]),
                _json_text(config["output_schema"]),
                revision_hash,
                actor_id,
                timestamp,
            ),
        )
        return revision_id

    def _find_or_create_mapping_plan(
        self,
        *,
        ast: dict[str, Any],
        plan: dict[str, Any],
        plan_hash: str,
        actor_id: str,
        timestamp: str,
    ) -> str:
        existing = self.database.execute_one(
            """
            select id from api_compiled_mapping_plan where content_hash = ?
            """,
            (plan_hash,),
        )
        if existing:
            return str(existing["id"])
        plan_id = new_id("api_mapping_plan")
        self.database.execute(
            """
            insert into api_compiled_mapping_plan
              (id, schema_version, ast_hash, plan_json, content_hash,
               compiled_by, compiled_at)
            values (?, 1, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                content_hash(ast),
                _json_text(plan),
                plan_hash,
                actor_id,
                timestamp,
            ),
        )
        return plan_id

    def _create_handler_revision(
        self,
        *,
        handler_id: str,
        draft: dict[str, Any],
        config: dict[str, Any],
        mapping_plan_id: str,
        actor_id: str,
        timestamp: str,
    ) -> str:
        revision = self._next_revision(
            "api_handler_revision",
            "revision",
            "handler_id",
            handler_id,
        )
        revision_id = new_id("api_handler_revision")
        handler_hash = content_hash(
            {
                "schema_version": 1,
                **config,
                "connection_revision_id": draft["connection_revision_id"],
                "authentication_profile_revision_id": draft["authentication_profile_revision_id"],
                "mapping_plan_id": mapping_plan_id,
            }
        )
        self.database.execute(
            """
            insert into api_handler_revision
              (id, handler_id, revision, schema_version, executor_id,
               connection_revision_id, authentication_profile_revision_id,
               method, relative_path, graphql_document, mapping_plan_id,
               content_hash, published_by, published_at)
            values (?, ?, ?, 1, 'http-json-v1', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                handler_id,
                revision,
                str(draft["connection_revision_id"]),
                str(draft["authentication_profile_revision_id"]),
                str(config["method"]),
                str(config["relative_path"]),
                str(config.get("graphql_document") or ""),
                mapping_plan_id,
                handler_hash,
                actor_id,
                timestamp,
            ),
        )
        return revision_id

    def _next_revision(
        self,
        table: str,
        revision_column: str,
        identity_column: str,
        identity_id: str,
    ) -> int:
        allowed = {
            ("api_capability_revision", "revision", "capability_id"),
            ("api_handler_revision", "revision", "handler_id"),
            (
                "api_capability_release",
                "release_revision",
                "capability_id",
            ),
        }
        if (table, revision_column, identity_column) not in allowed:
            raise ValueError("Unsupported revision table")
        row = self.database.execute_one(
            f"""
            select coalesce(max({revision_column}), 0) + 1 as revision
              from {table} where {identity_column} = ?
            """,
            (identity_id,),
        )
        return int(row["revision"]) if row else 1

    @staticmethod
    def _draft(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            **row,
            "draft_revision": int(row["draft_revision"]),
            "capability": _json_value(row.get("capability_json")),
            "handler": _json_value(row.get("handler_json")),
            "mapping_ast": _json_value(row.get("mapping_ast_json")),
        }

    @staticmethod
    def _revision_conflict() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "Capability Draft revision conflict",
            safe_message="Capability 草稿已变化，请刷新后重试",
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
