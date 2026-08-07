from __future__ import annotations

from typing import Any

from app.modules.business_application.domain.policies import (
    snapshot_hash,
)
from app.modules.internal_tools.domain import (
    HandlerRegistry,
    build_builtin_handler_registry,
)
from app.modules.job.application.builtin_tool_snapshot import (
    JobBuiltinToolSnapshotService,
)
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError

from ..application.job_authorization import AuthorizedJobContext
from ..domain.addressing import TargetRef
from ..domain.errors import AuthorizationError


class BusinessApplicationJobAccessAuthorizer:
    """Authorize only from immutable facts pinned to a persisted running Job."""

    def __init__(
        self,
        database: Database,
        registry: HandlerRegistry | None = None,
    ) -> None:
        self.database = database
        self.registry = registry or build_builtin_handler_registry()
        self.builtin_tool_snapshot_service = JobBuiltinToolSnapshotService(
            database,
            registry=self.registry,
        )

    def authorize(
        self,
        *,
        job_id: str,
        user_id: str,
        project_code: str,
        application_id: str,
        capability_code: str,
        target: TargetRef,
        placement: str = "",
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> AuthorizedJobContext:
        if not job_id or not capability_code:
            raise self._denied()
        job = self.database.execute_one(
            """
            select id, user_id, internal_user_id, project_code,
                   business_application_id, business_application_publication_id,
                   business_application_config_hash,
                   business_application_route_decision_json,
                   execution_scope_id, execution_scope_hash, status
              from agent_job
             where id = ?
            """,
            (job_id,),
        )
        if job is None or str(job.get("status") or "") != "RUNNING":
            raise self._denied()

        authoritative_user_id = str(
            job.get("internal_user_id") or job.get("user_id") or ""
        )
        authoritative_project_code = str(job.get("project_code") or "")
        if (
            not authoritative_user_id
            or (user_id and user_id != authoritative_user_id)
            or (project_code and project_code != authoritative_project_code)
        ):
            raise self._denied()

        authoritative_application_id = str(
            job.get("business_application_id") or ""
        )
        if application_id and application_id != authoritative_application_id:
            raise self._denied()
        exact_snapshot = self._exact_snapshot(job_id)
        if exact_snapshot:
            return self._authorize_builtin_snapshot(
                job=job,
                frozen=exact_snapshot,
                target=target,
                capability_code=capability_code,
                authoritative_user_id=authoritative_user_id,
                authoritative_project_code=authoritative_project_code,
                authoritative_application_id=authoritative_application_id,
                placement=placement,
                tool_call_id=tool_call_id,
                correlation_id=correlation_id,
            )
        # Removal stage: a runtime Job is callable only from its immutable exact
        # Built-in Tool Snapshot. Historical route-decision and legacy-v1 facts
        # remain stored for audit/migration evidence, but are never interpreted.
        raise self._denied()

    def _exact_snapshot(self, job_id: str) -> dict[str, Any]:
        try:
            return self.builtin_tool_snapshot_service.verify(job_id)
        except NonRetryableExecutionError as exc:
            raise self._denied() from exc

    def _authorize_builtin_snapshot(
        self,
        *,
        job: dict[str, Any],
        frozen: dict[str, Any],
        target: TargetRef,
        capability_code: str,
        authoritative_user_id: str,
        authoritative_project_code: str,
        authoritative_application_id: str,
        placement: str,
        tool_call_id: str,
        correlation_id: str,
    ) -> AuthorizedJobContext:
        snapshot = frozen.get("snapshot")
        if not isinstance(snapshot, dict):
            raise self._denied()
        frozen_target = snapshot.get("target")
        publication = snapshot.get("application_publication")
        if (
            not isinstance(frozen_target, dict)
            or not isinstance(publication, dict)
            or str(publication.get("id") or "")
            != str(job.get("business_application_publication_id") or "")
            or not self._target_matches_exact(target, frozen_target)
        ):
            raise self._denied()
        bindings = [
            value
            for value in snapshot.get("bindings") or []
            if isinstance(value, dict)
            and str(value.get("tool_identifier") or "")
            == capability_code
        ]
        if not bindings:
            raise self._denied()
        self._require_tool_call(
            tool_call_id=tool_call_id,
            job_id=str(job["id"]),
            tool_identifier=capability_code,
        )
        resource_bindings = [
            value
            for value in bindings
            if str(value.get("resource_slot") or "")
        ]
        if not resource_bindings:
            if len(bindings) != 1:
                raise self._denied()
            binding = bindings[0]
            candidate: dict[str, Any] = {}
        else:
            matching = [
                value
                for value in resource_bindings
                if any(
                    isinstance(candidate, dict)
                    and str(candidate.get("resource_kind") or "")
                    == target.kind.value
                    for candidate in value.get("candidates") or []
                )
            ]
            if len(matching) != 1:
                raise self._denied()
            binding = matching[0]
            candidates = [
                dict(value)
                for value in binding.get("candidates") or []
                if isinstance(value, dict)
                and str(value.get("resource_kind") or "")
                == target.kind.value
            ]
        persisted_binding = self.database.execute_one(
            """
            select id from agent_job_builtin_tool_binding
             where snapshot_id = ? and tool_identifier = ?
               and resource_slot = ? and target_key = ?
            """,
            (
                frozen["id"],
                capability_code,
                str(binding.get("resource_slot") or ""),
                str(frozen_target.get("target_key") or ""),
            ),
        )
        if persisted_binding is None:
            raise self._denied()
        if resource_bindings:
            candidate, denied_reason = self._select_candidate(
                candidates=candidates,
                placement=placement,
            )
            if denied_reason:
                self._record_builtin_fact(
                    tool_call_id=tool_call_id,
                    frozen=frozen,
                    binding=binding,
                    persisted_binding_id=str(persisted_binding["id"]),
                    target=frozen_target,
                    candidate={},
                    decision="DENIED",
                    reason_code=denied_reason,
                    correlation_id=correlation_id,
                )
                raise self._denied()
        elif placement:
            self._record_builtin_fact(
                tool_call_id=tool_call_id,
                frozen=frozen,
                binding=binding,
                persisted_binding_id=str(persisted_binding["id"]),
                target=frozen_target,
                candidate={},
                decision="DENIED",
                reason_code="placement_not_supported",
                correlation_id=correlation_id,
            )
            raise self._denied()
        workshop_policy = self._workshop_policy_facts(
            candidate=candidate,
            target=target,
        )
        loki_policy = self._loki_policy_facts(
            candidate=candidate,
            target=target,
        )
        self._record_builtin_fact(
            tool_call_id=tool_call_id,
            frozen=frozen,
            binding=binding,
            persisted_binding_id=str(persisted_binding["id"]),
            target=frozen_target,
            candidate=candidate,
            decision="ALLOWED",
            reason_code="exact_job_snapshot_allowed",
            correlation_id=correlation_id,
        )
        return AuthorizedJobContext(
            job_id=str(job["id"]),
            user_id=authoritative_user_id,
            project_code=authoritative_project_code,
            application_id=authoritative_application_id,
            application_publication_id=str(publication["id"]),
            handler_id=capability_code,
            handler_version=str(binding["handler_version"]),
            resource_revision_id=str(
                candidate.get("resource_revision_id") or ""
            ),
            execution_scope_key=str(
                frozen_target.get("target_key") or ""
            ),
            schema_version=3,
            snapshot_id=str(frozen["id"]),
            tool_execution_binding_id=str(persisted_binding["id"]),
            tool_release_id=str(binding["tool_release_id"]),
            implementation_digest=str(binding["implementation_digest"]),
            public_schema_hash=str(binding["public_schema_hash"]),
            actual_placement=str(candidate.get("placement") or ""),
            workshop_partition_policy_revision_id=workshop_policy["id"],
            workshop_partition_policy_content_hash=workshop_policy["hash"],
            database_table_prefix=workshop_policy["database_table_prefix"],
            redis_prefixes=workshop_policy["redis_prefixes"],
            loki_scope_policy_revision_id=loki_policy["id"],
            loki_scope_policy_content_hash=loki_policy["hash"],
            loki_scope_conditions=loki_policy["conditions"],
        )

    def _require_tool_call(
        self,
        *,
        tool_call_id: str,
        job_id: str,
        tool_identifier: str,
    ) -> None:
        if not tool_call_id:
            raise self._denied()
        row = self.database.execute_one(
            """
            select id from agent_tool_call
             where id = ? and job_id = ? and tool_name = ?
               and status = 'STARTED'
            """,
            (tool_call_id, job_id, tool_identifier),
        )
        if row is None:
            raise self._denied()

    @staticmethod
    def _select_candidate(
        *,
        candidates: list[dict[str, Any]],
        placement: str,
    ) -> tuple[dict[str, Any], str]:
        requested = placement.strip().lower()
        if requested and requested not in {"cloud", "edge"}:
            return {}, "placement_invalid"
        if len(candidates) == 1:
            candidate = candidates[0]
            frozen_placement = str(candidate.get("placement") or "")
            if requested and requested != frozen_placement:
                return {}, "placement_not_in_job_snapshot"
            return candidate, ""
        if not requested:
            return {}, "placement_required"
        matching = [
            candidate
            for candidate in candidates
            if str(candidate.get("placement") or "") == requested
        ]
        if len(matching) != 1:
            return {}, "placement_not_in_job_snapshot"
        return matching[0], ""

    def _record_builtin_fact(
        self,
        *,
        tool_call_id: str,
        frozen: dict[str, Any],
        binding: dict[str, Any],
        persisted_binding_id: str,
        target: dict[str, Any],
        candidate: dict[str, Any],
        decision: str,
        reason_code: str,
        correlation_id: str,
    ) -> None:
        selector_hash = snapshot_hash(
            {
                "target_hash": str(target.get("target_hash") or ""),
                "placement": str(candidate.get("placement") or ""),
                "resource_revision_id": str(
                    candidate.get("resource_revision_id") or ""
                ),
                "workshop_partition_policy_hash": str(
                    candidate.get("workshop_partition_policy_hash") or ""
                ),
                "loki_scope_policy_hash": str(
                    candidate.get("loki_scope_policy_hash") or ""
                ),
            }
        )
        self.database.execute(
            """
            insert into agent_tool_call_builtin_tool_fact
              (tool_call_id, snapshot_id, tool_execution_binding_id,
               tool_release_id, handler_version, implementation_digest,
               actual_placement, resource_revision_id,
               workshop_partition_policy_revision_id,
               loki_scope_policy_revision_id, effective_scope_hash,
               effective_selector_hash, authorization_decision,
               decision_reason_code, correlation_id, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    CURRENT_TIMESTAMP)
            on conflict(tool_call_id) do nothing
            """,
            (
                tool_call_id,
                frozen["id"],
                persisted_binding_id,
                binding["tool_release_id"],
                binding["handler_version"],
                binding["implementation_digest"],
                str(candidate.get("placement") or "") or None,
                str(candidate.get("resource_revision_id") or "")
                or None,
                str(
                    candidate.get(
                        "workshop_partition_policy_revision_id"
                    )
                    or ""
                )
                or None,
                str(
                    candidate.get("loki_scope_policy_revision_id")
                    or ""
                )
                or None,
                str(target["target_hash"]),
                selector_hash,
                decision,
                reason_code,
                correlation_id or "-",
            ),
        )

    def _workshop_policy_facts(
        self,
        *,
        candidate: dict[str, Any],
        target: TargetRef,
    ) -> dict[str, Any]:
        revision_id = str(
            candidate.get("workshop_partition_policy_revision_id")
            or ""
        )
        expected_hash = str(
            candidate.get("workshop_partition_policy_hash") or ""
        )
        empty: dict[str, Any] = {
            "id": "",
            "hash": "",
            "database_table_prefix": "",
            "redis_prefixes": (),
        }
        if not revision_id and not expected_hash:
            return empty
        row = self.database.execute_one(
            """
            select revision.content_hash, revision.status,
                   revision.database_rule_enabled,
                   revision.database_table_prefix,
                   revision.redis_rule_enabled,
                   environment.code as environment_code,
                   base.code as base_code, workshop.code as workshop_code
              from workshop_partition_policy_revision revision
              join workshop_partition_policy policy
                on policy.id = revision.policy_id
              join platform_workshop workshop
                on workshop.id = policy.workshop_id
              join platform_base base on base.id = workshop.base_id
              join platform_environment environment
                on environment.id = base.environment_id
             where revision.id = ?
            """,
            (revision_id,),
        )
        if (
            row is None
            or str(row["status"]) != "PUBLISHED"
            or str(row["content_hash"]) != expected_hash
            or str(row["environment_code"]) != target.environment
            or str(row["base_code"]) != target.base
            or str(row["workshop_code"]) != (target.workshop or "")
        ):
            raise self._denied()
        prefixes = self.database.execute(
            """
            select prefix
              from workshop_partition_policy_revision_redis_prefix
             where policy_revision_id = ?
             order by position
            """,
            (revision_id,),
        )
        return {
            "id": revision_id,
            "hash": expected_hash,
            "database_table_prefix": (
                str(row.get("database_table_prefix") or "")
                if bool(row.get("database_rule_enabled"))
                else ""
            ),
            "redis_prefixes": (
                tuple(str(value["prefix"]) for value in prefixes)
                if bool(row.get("redis_rule_enabled"))
                else ()
            ),
        }

    def _loki_policy_facts(
        self,
        *,
        candidate: dict[str, Any],
        target: TargetRef,
    ) -> dict[str, Any]:
        revision_id = str(
            candidate.get("loki_scope_policy_revision_id") or ""
        )
        expected_hash = str(
            candidate.get("loki_scope_policy_hash") or ""
        )
        empty: dict[str, Any] = {
            "id": "",
            "hash": "",
            "conditions": (),
        }
        if not revision_id and not expected_hash:
            return empty
        row = self.database.execute_one(
            """
            select revision.content_hash, revision.status,
                   revision.resource_revision_id,
                   environment.code as environment_code,
                   coalesce(base.code, '') as base_code
              from loki_scope_policy_revision revision
              join loki_scope_policy policy on policy.id = revision.policy_id
              join platform_environment environment
                on environment.id = policy.environment_id
              left join platform_base base on base.id = policy.base_id
             where revision.id = ?
            """,
            (revision_id,),
        )
        if (
            row is None
            or str(row["status"]) != "PUBLISHED"
            or str(row["content_hash"]) != expected_hash
            or str(row["resource_revision_id"])
            != str(candidate.get("resource_revision_id") or "")
            or str(row["environment_code"]) != target.environment
            or (
                str(row.get("base_code") or "")
                and str(row["base_code"]) != target.base
            )
        ):
            raise self._denied()
        conditions = self.database.execute(
            """
            select label_key, label_value
              from loki_scope_policy_revision_condition
             where policy_revision_id = ?
             order by position
            """,
            (revision_id,),
        )
        return {
            "id": revision_id,
            "hash": expected_hash,
            "conditions": tuple(
                (str(value["label_key"]), str(value["label_value"]))
                for value in conditions
            ),
        }

    @staticmethod
    def _target_matches_exact(
        target: TargetRef,
        values: dict[str, Any],
    ) -> bool:
        return (
            target.environment
            == str(values.get("environment_code") or "")
            and target.base == str(values.get("base_code") or "")
            and (target.workshop or "")
            == str(values.get("workshop_code") or "")
        )

    @staticmethod
    def _denied() -> AuthorizationError:
        return AuthorizationError("Agent Job authorization context is invalid")

    def close(self) -> None:
        self.database.close()
