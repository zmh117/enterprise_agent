from __future__ import annotations

import json
from typing import Any

from app.modules.internal_tools.domain import HandlerDefinition
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound

from .repository import json_text, new_id, now_iso


class HandlerGovernanceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def reconcile_installation(
        self,
        definition: HandlerDefinition,
    ) -> dict[str, Any]:
        existing = self.find_installation(
            definition.handler_id,
            definition.handler_version,
        )
        timestamp = now_iso()
        if existing is None:
            self.database.execute(
                """
                insert into handler_installation
                  (handler_id, handler_version, implementation_digest,
                   display_name, description, input_schema_json,
                   output_schema_json, risk_level,
                   required_permissions_json, resource_slots_json,
                   visibility, installation_status, first_seen_at,
                   last_seen_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'INSTALLED', ?, ?)
                """,
                (
                    definition.handler_id,
                    definition.handler_version,
                    definition.implementation_digest,
                    definition.display_name,
                    definition.description,
                    json_text(definition.input_schema),
                    json_text(definition.output_schema),
                    definition.risk_level,
                    json_text(list(definition.required_permissions)),
                    json_text(
                        [
                            slot.public()
                            for slot in definition.resource_slots
                        ]
                    ),
                    definition.visibility,
                    timestamp,
                    timestamp,
                ),
            )
        elif (
            existing["implementation_digest"]
            != definition.implementation_digest
        ):
            self.database.execute(
                """
                update handler_installation
                   set installation_status = 'DRIFTED',
                       last_seen_at = ?
                 where handler_id = ? and handler_version = ?
                """,
                (
                    timestamp,
                    definition.handler_id,
                    definition.handler_version,
                ),
            )
        else:
            self.database.execute(
                """
                update handler_installation
                   set installation_status = 'INSTALLED',
                       last_seen_at = ?
                 where handler_id = ? and handler_version = ?
                """,
                (
                    timestamp,
                    definition.handler_id,
                    definition.handler_version,
                ),
            )
        self._reconcile_builtin_installation(definition, timestamp=timestamp)
        return self.get_installation(
            definition.handler_id,
            definition.handler_version,
        )

    def _reconcile_builtin_installation(
        self,
        definition: HandlerDefinition,
        *,
        timestamp: str,
    ) -> dict[str, Any]:
        projection = self.database.execute_one(
            """
            select * from builtin_tool_manifest_projection
             where tool_identifier = ? and handler_version = ?
            """,
            (definition.tool_identifier, definition.handler_version),
        )
        if projection is None:
            self.database.execute(
                """
                insert into builtin_tool_manifest_projection
                  (tool_identifier, handler_version, implementation_digest,
                   tool_semantic_version, manifest_hash, public_schema_hash,
                   manifest_json, verifier_plan_json, verifier_version,
                   observed_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(tool_identifier, handler_version) do nothing
                """,
                (
                    definition.tool_identifier,
                    definition.handler_version,
                    definition.implementation_digest,
                    definition.tool_semantic_version,
                    definition.manifest_hash,
                    definition.public_schema_hash,
                    json_text(definition.manifest()),
                    json_text(definition.verifier_plan.public()),
                    definition.verifier_plan.verifier_version,
                    timestamp,
                ),
            )
            projection = self.database.execute_one(
                """
                select * from builtin_tool_manifest_projection
                 where tool_identifier = ? and handler_version = ?
                """,
                (definition.tool_identifier, definition.handler_version),
            )
        elif (
            str(projection["implementation_digest"])
            == definition.implementation_digest
        ):
            self.database.execute(
                """
                update builtin_tool_manifest_projection
                   set observed_at = ?
                 where tool_identifier = ? and handler_version = ?
                """,
                (
                    timestamp,
                    definition.tool_identifier,
                    definition.handler_version,
                ),
            )
        assert projection is not None

        installation = self.find_builtin_installation(
            definition.tool_identifier,
            definition.handler_version,
        )
        frozen_digest = str(projection["implementation_digest"])
        status = (
            "INSTALLED"
            if frozen_digest == definition.implementation_digest
            else "DRIFTED"
        )
        safe_health_summary = (
            ""
            if status == "INSTALLED"
            else "code manifest differs from the reconciled installation"
        )
        if installation is None:
            self.database.execute(
                """
                insert into builtin_tool_installation
                  (tool_identifier, handler_version, implementation_digest,
                   installation_status, safe_health_summary, first_seen_at,
                   last_seen_at)
                values (?, ?, ?, ?, ?, ?, ?)
                on conflict(tool_identifier, handler_version) do nothing
                """,
                (
                    definition.tool_identifier,
                    definition.handler_version,
                    frozen_digest,
                    status,
                    safe_health_summary,
                    timestamp,
                    timestamp,
                ),
            )
        else:
            self.database.execute(
                """
                update builtin_tool_installation
                   set installation_status = ?,
                       safe_health_summary = ?,
                       last_seen_at = ?
                 where tool_identifier = ? and handler_version = ?
                """,
                (
                    status,
                    safe_health_summary,
                    timestamp,
                    definition.tool_identifier,
                    definition.handler_version,
                ),
            )
        result = self.find_builtin_installation(
            definition.tool_identifier,
            definition.handler_version,
        )
        assert result is not None
        return result

    def mark_unseen_missing(
        self,
        installed_keys: set[tuple[str, str]],
    ) -> int:
        changed_keys: set[tuple[str, str]] = set()
        for row in self.list_installations():
            key = (row["handler_id"], row["handler_version"])
            if key in installed_keys:
                continue
            if row["installation_status"] != "MISSING":
                self.database.execute(
                    """
                    update handler_installation
                       set installation_status = 'MISSING'
                     where handler_id = ? and handler_version = ?
                    """,
                    key,
                )
                changed_keys.add(key)
        for row in self.list_builtin_installations():
            key = (row["tool_identifier"], row["handler_version"])
            if key in installed_keys:
                continue
            if row["installation_status"] != "MISSING":
                self.database.execute(
                    """
                    update builtin_tool_installation
                       set installation_status = 'MISSING',
                           safe_health_summary =
                             'exact code manifest is missing from this deployment'
                     where tool_identifier = ? and handler_version = ?
                    """,
                    key,
                )
                changed_keys.add(key)
        return len(changed_keys)

    def find_builtin_installation(
        self,
        tool_identifier: str,
        handler_version: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from builtin_tool_installation
             where tool_identifier = ? and handler_version = ?
            """,
            (tool_identifier, handler_version),
        )
        return dict(row) if row else None

    def list_builtin_installations(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.database.execute(
                """
                select * from builtin_tool_installation
                 order by tool_identifier, handler_version
                """
            )
        ]

    def list_builtin_verifications(
        self,
        tool_identifier: str = "",
    ) -> list[dict[str, Any]]:
        sql = "select * from builtin_tool_verification"
        params: tuple[Any, ...] = ()
        if tool_identifier:
            sql += " where tool_identifier = ?"
            params = (tool_identifier,)
        sql += " order by verified_at desc, id"
        return [
            self._builtin_verification(row)
            for row in self.database.execute(sql, params)
        ]

    def list_builtin_releases(
        self,
        tool_identifier: str = "",
    ) -> list[dict[str, Any]]:
        sql = "select * from builtin_tool_release"
        params: tuple[Any, ...] = ()
        if tool_identifier:
            sql += " where tool_identifier = ?"
            params = (tool_identifier,)
        sql += " order by tool_identifier, release_revision desc"
        return [dict(row) for row in self.database.execute(sql, params)]

    def list_builtin_lifecycle_audit(
        self,
        release_id: str,
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.database.execute(
                """
                select id, tool_release_id, previous_status, new_status,
                       reason_code, safe_summary, actor_id, correlation_id,
                       occurred_at
                  from builtin_tool_lifecycle_audit
                 where tool_release_id = ?
                 order by occurred_at, id
                """,
                (release_id,),
            )
        ]

    def find_builtin_verification(
        self,
        *,
        tool_identifier: str,
        handler_version: str,
        implementation_digest: str,
        verifier_version: str,
        normalized_input_hash: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from builtin_tool_verification
             where tool_identifier = ?
               and handler_version = ?
               and implementation_digest = ?
               and verifier_version = ?
               and normalized_input_hash = ?
            """,
            (
                tool_identifier,
                handler_version,
                implementation_digest,
                verifier_version,
                normalized_input_hash,
            ),
        )
        return self._builtin_verification(row) if row else None

    def record_builtin_verification(
        self,
        *,
        tool_identifier: str,
        handler_version: str,
        implementation_digest: str,
        verifier_version: str,
        normalized_input_hash: str,
        status: str,
        result_summary: dict[str, Any],
        safe_error_summary: str,
        actor_id: str,
    ) -> dict[str, Any]:
        existing = self.find_builtin_verification(
            tool_identifier=tool_identifier,
            handler_version=handler_version,
            implementation_digest=implementation_digest,
            verifier_version=verifier_version,
            normalized_input_hash=normalized_input_hash,
        )
        if existing is not None:
            return existing
        verification_id = new_id("builtin_tool_verification")
        self.database.execute(
            """
            insert into builtin_tool_verification
              (id, tool_identifier, handler_version, implementation_digest,
               verifier_version, normalized_input_hash, status,
               result_summary_json, safe_error_summary, verified_by,
               verified_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(
              tool_identifier,
              handler_version,
              implementation_digest,
              verifier_version,
              normalized_input_hash
            ) do nothing
            """,
            (
                verification_id,
                tool_identifier,
                handler_version,
                implementation_digest,
                verifier_version,
                normalized_input_hash,
                status,
                json_text(result_summary),
                safe_error_summary,
                actor_id,
                now_iso(),
            ),
        )
        result = self.find_builtin_verification(
            tool_identifier=tool_identifier,
            handler_version=handler_version,
            implementation_digest=implementation_digest,
            verifier_version=verifier_version,
            normalized_input_hash=normalized_input_hash,
        )
        assert result is not None
        return result

    def find_builtin_verification_by_id(
        self,
        verification_id: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            "select * from builtin_tool_verification where id = ?",
            (verification_id,),
        )
        return self._builtin_verification(row) if row else None

    def find_builtin_release_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            "select * from builtin_tool_release where idempotency_key = ?",
            (idempotency_key,),
        )
        return dict(row) if row else None

    def find_builtin_release_exact(
        self,
        *,
        tool_identifier: str,
        handler_version: str,
        implementation_digest: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from builtin_tool_release
             where tool_identifier = ?
               and handler_version = ?
               and implementation_digest = ?
            """,
            (tool_identifier, handler_version, implementation_digest),
        )
        return dict(row) if row else None

    def get_builtin_release(self, release_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from builtin_tool_release where id = ?",
            (release_id,),
        )
        if row is None:
            raise NotFound(f"Built-in Tool Release not found: {release_id}")
        return dict(row)

    def builtin_release_dependencies(
        self,
        release_id: str,
    ) -> dict[str, int]:
        active_agent = self.database.execute_one(
            """
            select count(*) as count
              from agent_publication_builtin_tool envelope
              join agent_publication publication
                on publication.id = envelope.agent_publication_id
             where envelope.tool_release_id = ?
               and publication.status = 'active'
            """,
            (release_id,),
        )
        active_application = self.database.execute_one(
            """
            select count(*) as count
              from business_application_publication_builtin_tool allowlist
              join business_application_deployment deployment
                on deployment.publication_id = allowlist.application_publication_id
               and deployment.active = 1
             where allowlist.tool_release_id = ?
            """,
            (release_id,),
        )
        recoverable_job = self.database.execute_one(
            """
            select count(*) as count
              from agent_job_builtin_tool_binding binding
              join agent_job_builtin_tool_snapshot snapshot
                on snapshot.id = binding.snapshot_id
              join agent_job job on job.id = snapshot.job_id
             where binding.tool_release_id = ?
               and (
                 job.status in ('PENDING', 'RUNNING')
                 or (
                   job.status = 'FAILED'
                   and job.retry_count < job.max_retry_count
                   and job.result is null
                 )
               )
            """,
            (release_id,),
        )
        return {
            "active_agent_publications": int(
                (active_agent or {"count": 0})["count"]
            ),
            "active_application_publications": int(
                (active_application or {"count": 0})["count"]
            ),
            "recoverable_jobs": int(
                (recoverable_job or {"count": 0})["count"]
            ),
        }

    def set_builtin_release_status(
        self,
        *,
        release_id: str,
        status: str,
        reason_code: str,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        before = self.get_builtin_release(release_id)
        timestamp = now_iso()
        assignments = ["status = ?"]
        values: list[Any] = [status]
        if status == "DEPRECATED":
            assignments.extend(["deprecated_by = ?", "deprecated_at = ?"])
            values.extend([actor_id, timestamp])
        elif status == "DISABLED":
            assignments.extend(["disabled_by = ?", "disabled_at = ?"])
            values.extend([actor_id, timestamp])
        elif status == "ARCHIVED":
            assignments.extend(["archived_by = ?", "archived_at = ?"])
            values.extend([actor_id, timestamp])
        values.extend([release_id, before["status"]])
        changed = self.database.execute(
            f"""
            update builtin_tool_release
               set {', '.join(assignments)}
             where id = ? and status = ?
             returning id
            """,
            tuple(values),
        )
        if not changed:
            raise NonRetryableExecutionError(
                "Built-in Tool Release lifecycle changed concurrently",
                safe_message="Release 生命周期已变化，请刷新后重试",
                error_code="builtin_tool_release_lifecycle_invalid",
            )
        self.database.execute(
            """
            insert into builtin_tool_lifecycle_audit
              (id, tool_release_id, previous_status, new_status, reason_code,
               safe_summary, actor_id, correlation_id, occurred_at)
            values (?, ?, ?, ?, ?, 'Built-in Tool lifecycle changed', ?, ?, ?)
            """,
            (
                new_id("builtin_tool_lifecycle_audit"),
                release_id,
                before["status"],
                status,
                reason_code,
                actor_id,
                correlation_id,
                timestamp,
            ),
        )
        return self.get_builtin_release(release_id)

    def publish_builtin_release(
        self,
        *,
        definition: HandlerDefinition,
        verification_id: str,
        idempotency_key: str,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        by_key = self.find_builtin_release_by_idempotency_key(
            idempotency_key
        )
        if by_key is not None:
            if (
                by_key["tool_identifier"] == definition.tool_identifier
                and by_key["handler_version"] == definition.handler_version
                and by_key["implementation_digest"]
                == definition.implementation_digest
                and by_key["verification_id"] == verification_id
            ):
                return by_key
            raise NonRetryableExecutionError(
                "Built-in Tool publish idempotency key conflicts with another intent",
                safe_message="发布幂等键已用于不同的内置工具内容",
                error_code="builtin_tool_publish_idempotency_conflict",
            )
        exact = self.find_builtin_release_exact(
            tool_identifier=definition.tool_identifier,
            handler_version=definition.handler_version,
            implementation_digest=definition.implementation_digest,
        )
        if exact is not None:
            return exact
        row = self.database.execute_one(
            """
            select coalesce(max(release_revision), 0) + 1 as next_revision
              from builtin_tool_release
             where tool_identifier = ?
            """,
            (definition.tool_identifier,),
        )
        release_revision = int((row or {"next_revision": 1})["next_revision"])
        release_id = new_id("builtin_tool_release")
        timestamp = now_iso()
        created = self.database.execute(
            """
            insert into builtin_tool_release
              (id, tool_identifier, release_revision,
               tool_semantic_version, handler_version,
               implementation_digest, manifest_hash, public_schema_hash,
               verification_id, status, idempotency_key, published_by,
               published_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?)
            on conflict do nothing
            returning id
            """,
            (
                release_id,
                definition.tool_identifier,
                release_revision,
                definition.tool_semantic_version,
                definition.handler_version,
                definition.implementation_digest,
                definition.manifest_hash,
                definition.public_schema_hash,
                verification_id,
                idempotency_key,
                actor_id,
                timestamp,
            ),
        )
        if not created:
            by_key = self.find_builtin_release_by_idempotency_key(
                idempotency_key
            )
            if by_key is not None:
                if (
                    by_key["tool_identifier"] == definition.tool_identifier
                    and by_key["handler_version"] == definition.handler_version
                    and by_key["implementation_digest"]
                    == definition.implementation_digest
                    and by_key["verification_id"] == verification_id
                ):
                    return by_key
                raise NonRetryableExecutionError(
                    "Built-in Tool publish idempotency key conflicts with another intent",
                    safe_message="发布幂等键已用于不同的内置工具内容",
                    error_code="builtin_tool_publish_idempotency_conflict",
                )
            exact = self.find_builtin_release_exact(
                tool_identifier=definition.tool_identifier,
                handler_version=definition.handler_version,
                implementation_digest=definition.implementation_digest,
            )
            if exact is not None:
                return exact
            raise NonRetryableExecutionError(
                "Built-in Tool publish conflicted with concurrent state",
                safe_message="内置工具发布发生并发冲突，请刷新后重试",
                error_code="builtin_tool_publish_idempotency_conflict",
            )
        self.database.execute(
            """
            insert into builtin_tool_lifecycle_audit
              (id, tool_release_id, previous_status, new_status, reason_code,
               safe_summary, actor_id, correlation_id, occurred_at)
            values (?, ?, NULL, 'ACTIVE', 'PUBLISHED',
                    'verified Built-in Tool Release published', ?, ?, ?)
            """,
            (
                new_id("builtin_tool_lifecycle_audit"),
                release_id,
                actor_id,
                correlation_id,
                timestamp,
            ),
        )
        result = self.find_builtin_release_exact(
            tool_identifier=definition.tool_identifier,
            handler_version=definition.handler_version,
            implementation_digest=definition.implementation_digest,
        )
        assert result is not None
        return result

    def find_installation(
        self,
        handler_id: str,
        handler_version: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from handler_installation
             where handler_id = ? and handler_version = ?
            """,
            (handler_id, handler_version),
        )
        return self._installation(row) if row else None

    def get_installation(
        self,
        handler_id: str,
        handler_version: str,
    ) -> dict[str, Any]:
        result = self.find_installation(handler_id, handler_version)
        if result is None:
            raise NotFound(
                f"Handler installation not found: "
                f"{handler_id}@{handler_version}"
            )
        return result

    def list_installations(self) -> list[dict[str, Any]]:
        return [
            self._installation(row)
            for row in self.database.execute(
                """
                select * from handler_installation
                 order by handler_id, handler_version
                """
            )
        ]

    def publish(
        self,
        *,
        handler_id: str,
        handler_version: str,
        actor_id: str,
    ) -> dict[str, Any]:
        installation = self.get_installation(
            handler_id,
            handler_version,
        )
        if installation["installation_status"] != "INSTALLED":
            raise NonRetryableExecutionError(
                "Handler installation is not healthy",
                safe_message="Handler 未安装或代码版本已漂移",
                error_code="handler_installation_unavailable",
            )
        existing = self.find_publication(
            handler_id,
            handler_version,
        )
        if existing is not None:
            raise NonRetryableExecutionError(
                "Handler version was already governed",
                safe_message="该 Handler 版本已发布或已停用，不能重复发布",
                error_code="handler_publication_immutable",
            )
        publication_id = new_id("handler_publication")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into handler_publication
              (id, handler_id, handler_version, status, revision,
               published_by, published_at)
            values (?, ?, ?, 'PUBLISHED', 1, ?, ?)
            """,
            (
                publication_id,
                handler_id,
                handler_version,
                actor_id,
                timestamp,
            ),
        )
        return self.get_publication(publication_id)

    def find_publication(
        self,
        handler_id: str,
        handler_version: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from handler_publication
             where handler_id = ? and handler_version = ?
            """,
            (handler_id, handler_version),
        )
        return dict(row) if row else None

    def get_publication(self, publication_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from handler_publication where id = ?",
            (publication_id,),
        )
        if not row:
            raise NotFound(
                f"Handler publication not found: {publication_id}"
            )
        return dict(row)

    def list_publications(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.database.execute(
                """
                select * from handler_publication
                 order by handler_id, handler_version
                """
            )
        ]

    def set_publication_status(
        self,
        *,
        publication_id: str,
        status: str,
        actor_id: str,
    ) -> dict[str, Any]:
        before = self.get_publication(publication_id)
        normalized = status.upper()
        if normalized not in {"DISABLED", "ARCHIVED"}:
            raise NonRetryableExecutionError(
                "Handler publication cannot be re-enabled or modified",
                safe_message="Handler 发布后只能禁用或归档",
                error_code="handler_publication_immutable",
            )
        if before["status"] == "ARCHIVED" or (
            before["status"] == "DISABLED"
            and normalized == "DISABLED"
        ):
            raise NonRetryableExecutionError(
                "Handler publication status cannot move backwards",
                safe_message="Handler 发布状态不能回退或重复变更",
                error_code="handler_publication_immutable",
            )
        timestamp = now_iso()
        field_actor = (
            "disabled_by"
            if normalized == "DISABLED"
            else "archived_by"
        )
        field_at = (
            "disabled_at"
            if normalized == "DISABLED"
            else "archived_at"
        )
        self.database.execute(
            f"""
            update handler_publication
               set status = ?,
                   revision = revision + 1,
                   {field_actor} = ?,
                   {field_at} = ?
             where id = ?
            """,
            (normalized, actor_id, timestamp, publication_id),
        )
        return self.get_publication(publication_id)

    @staticmethod
    def _installation(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for source, target in (
            ("input_schema_json", "input_schema"),
            ("output_schema_json", "output_schema"),
            ("required_permissions_json", "required_permissions"),
            ("resource_slots_json", "resource_slots"),
        ):
            result[target] = json.loads(result.pop(source))
        return result

    @staticmethod
    def _builtin_verification(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["result_summary"] = json.loads(
            result.pop("result_summary_json")
        )
        return result
