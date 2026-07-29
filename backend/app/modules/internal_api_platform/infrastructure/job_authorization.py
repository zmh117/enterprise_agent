from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.business_application.domain.policies import verify_snapshot
from app.modules.internal_tools.domain import (
    HandlerRegistry,
    HandlerRegistryError,
    build_builtin_handler_registry,
)
from app.shared.database import Database

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

    def authorize(
        self,
        *,
        job_id: str,
        user_id: str,
        project_code: str,
        application_id: str,
        capability_code: str,
        target: TargetRef,
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
        publication_id = str(
            job.get("business_application_publication_id") or ""
        )
        publication_hash = str(
            job.get("business_application_config_hash") or ""
        )
        runtime = self._runtime_facts(job)
        expected_publication = runtime.get("application_publication")
        if (
            not authoritative_application_id
            or not publication_id
            or not publication_hash
            or not isinstance(expected_publication, dict)
            or str(expected_publication.get("id") or "") != publication_id
            or str(expected_publication.get("application_id") or "")
            != authoritative_application_id
            or str(expected_publication.get("config_hash") or "")
            != publication_hash
        ):
            raise self._denied()

        publication_snapshot = self._publication_snapshot(
            publication_id=publication_id,
            application_id=authoritative_application_id,
            config_hash=publication_hash,
        )
        publication_capabilities = {
            str(item.get("capability_code") or "")
            for item in publication_snapshot.get("capabilities") or []
            if isinstance(item, dict) and bool(item.get("enabled", True))
        }
        if capability_code not in publication_capabilities:
            raise self._denied()
        agent = publication_snapshot.get("agent")
        agent_publication_id = (
            str(agent.get("id") or "") if isinstance(agent, dict) else ""
        )
        if (
            not agent_publication_id
            or str(runtime.get("agent_publication_id") or "")
            != agent_publication_id
        ):
            raise self._denied()

        requested_scope = runtime.get("requested_scope")
        if not isinstance(requested_scope, dict) or not self._target_matches_codes(
            target,
            requested_scope,
            allow_broader=True,
        ):
            raise self._denied()
        if int(runtime.get("schema_version") or 0) == 2:
            return self._authorize_governed(
                job=job,
                runtime=runtime,
                target=target,
                capability_code=capability_code,
                authoritative_user_id=authoritative_user_id,
                authoritative_project_code=authoritative_project_code,
                authoritative_application_id=(
                    authoritative_application_id
                ),
                publication_id=publication_id,
                agent_publication_id=agent_publication_id,
            )

        for binding in runtime.get("bindings") or []:
            if (
                not isinstance(binding, dict)
                or str(binding.get("capability_code") or "") != capability_code
            ):
                continue
            execution_scope = binding.get("execution_scope")
            if not isinstance(execution_scope, dict) or not self._target_matches_codes(
                target,
                execution_scope,
                allow_broader=True,
            ):
                continue
            handler_id = str(binding.get("handler_id") or "")
            handler_version = str(binding.get("handler_version") or "")
            if not self._handler_is_current(
                handler_id=handler_id,
                handler_version=handler_version,
                capability_code=capability_code,
                agent_publication_id=agent_publication_id,
            ):
                continue
            resource = self._matching_resource_revision(
                binding.get("resource_revisions"),
                target=target,
            )
            if resource is None:
                continue
            return AuthorizedJobContext(
                job_id=job_id,
                user_id=authoritative_user_id,
                project_code=authoritative_project_code,
                application_id=authoritative_application_id,
                application_publication_id=publication_id,
                handler_id=handler_id,
                handler_version=handler_version,
                resource_revision_id=str(resource["resource_revision_id"]),
                execution_scope_key=str(execution_scope.get("scope_key") or ""),
            )
        raise self._denied()

    def _runtime_facts(self, job: dict[str, Any]) -> dict[str, Any]:
        try:
            route_decision = json.loads(
                str(job.get("business_application_route_decision_json") or "{}")
            )
        except json.JSONDecodeError as exc:
            raise self._denied() from exc
        runtime = (
            route_decision.get("runtime_authorization")
            if isinstance(route_decision, dict)
            else None
        )
        if (
            not isinstance(runtime, dict)
            or int(runtime.get("schema_version") or 0)
            not in {1, 2}
        ):
            raise self._denied()
        return runtime

    def _authorize_governed(
        self,
        *,
        job: dict[str, Any],
        runtime: dict[str, Any],
        target: TargetRef,
        capability_code: str,
        authoritative_user_id: str,
        authoritative_project_code: str,
        authoritative_application_id: str,
        publication_id: str,
        agent_publication_id: str,
    ) -> AuthorizedJobContext:
        execution_scope_id = str(
            job.get("execution_scope_id") or ""
        )
        execution_scope_hash = str(
            job.get("execution_scope_hash") or ""
        )
        scope = self.database.execute_one(
            """
            select * from agent_job_execution_scope
             where id = ? and job_id = ?
            """,
            (execution_scope_id, str(job["id"])),
        )
        if (
            scope is None
            or str(scope["scope_hash"]) != execution_scope_hash
            or int(scope["schema_version"]) != 2
            or str(scope["business_application_id"])
            != authoritative_application_id
            or str(scope["application_publication_id"])
            != publication_id
            or str(scope["agent_publication_id"])
            != agent_publication_id
        ):
            raise self._denied()
        try:
            persisted_snapshot = json.loads(
                str(scope["snapshot_json"])
            )
        except json.JSONDecodeError as exc:
            raise self._denied() from exc
        expected_snapshot = {
            "job_id": str(job["id"]),
            **runtime,
        }
        canonical = json.dumps(
            expected_snapshot,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if (
            persisted_snapshot != expected_snapshot
            or hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            != execution_scope_hash
        ):
            raise self._denied()

        runtime_bindings = [
            value
            for value in runtime.get("bindings") or []
            if isinstance(value, dict)
            and str(value.get("capability_code") or "")
            == capability_code
        ]
        for runtime_binding in runtime_bindings:
            handler_id = str(
                runtime_binding.get("handler_id") or ""
            )
            handler_version = str(
                runtime_binding.get("handler_version") or ""
            )
            if not self._handler_is_current(
                handler_id=handler_id,
                handler_version=handler_version,
                capability_code=capability_code,
                agent_publication_id=agent_publication_id,
            ):
                continue
            resources = runtime_binding.get("resource_revisions")
            if not isinstance(resources, list):
                continue
            for resource in resources:
                if (
                    not isinstance(resource, dict)
                    or str(resource.get("resource_kind") or "")
                    != target.kind.value
                    or not self._target_matches_codes(
                        target,
                        resource,
                        allow_broader=False,
                    )
                ):
                    continue
                persisted = self.database.execute_one(
                    """
                    select eb.capability_code, eb.handler_id,
                           eb.handler_version, eb.resource_slot,
                           eb.resource_revision_id,
                           eb.constraints_json, eb.binding_hash,
                           rr.id as id, rr.revision, rr.status,
                           r.id as resource_id, r.code as code,
                           r.code as resource_code,
                           r.resource_kind, r.scope_type,
                           r.status as resource_status,
                           r.environment_id,
                           coalesce(r.base_id, '') as base_id,
                           coalesce(r.workshop_id, '') as workshop_id,
                           e.code as environment_code,
                           coalesce(b.code, '') as base_code,
                           coalesce(w.code, '') as workshop_code
                      from agent_job_execution_binding eb
                      join platform_resource_revision rr
                        on rr.id = eb.resource_revision_id
                      join platform_resource r on r.id = rr.resource_id
                      join platform_environment e
                        on e.id = r.environment_id
                      left join platform_base b on b.id = r.base_id
                      left join platform_workshop w
                        on w.id = r.workshop_id
                      join handler_publication hp
                        on hp.handler_id = eb.handler_id
                       and hp.handler_version = eb.handler_version
                       and hp.status = 'PUBLISHED'
                      join business_application_publication_handler ah
                        on ah.application_publication_id = ?
                       and ah.handler_publication_id = hp.id
                       and ah.capability_code = eb.capability_code
                      join business_application_publication_resource ar
                        on ar.application_handler_id = ah.id
                       and ar.resource_slot = eb.resource_slot
                       and ar.resource_revision_id =
                           eb.resource_revision_id
                       and ar.binding_hash = eb.binding_hash
                     where eb.execution_scope_id = ?
                       and eb.capability_code = ?
                       and eb.handler_id = ?
                       and eb.handler_version = ?
                       and eb.resource_slot = ?
                       and eb.resource_revision_id = ?
                    """,
                    (
                        publication_id,
                        execution_scope_id,
                        capability_code,
                        handler_id,
                        handler_version,
                        str(resource.get("resource_slot") or ""),
                        str(
                            resource.get(
                                "resource_revision_id"
                            )
                            or ""
                        ),
                    ),
                )
                if (
                    persisted is None
                    or persisted["status"] != "PUBLISHED"
                    or persisted["resource_status"] != "enabled"
                    or str(persisted["binding_hash"])
                    != str(resource.get("binding_hash") or "")
                    or not self._resource_matches_snapshot(
                        persisted,
                        resource,
                    )
                    or not self._target_matches_codes(
                        target,
                        persisted,
                        allow_broader=False,
                    )
                ):
                    continue
                try:
                    persisted_constraints = json.loads(
                        str(persisted["constraints_json"])
                    )
                except json.JSONDecodeError:
                    continue
                if persisted_constraints != (
                    resource.get("constraints") or {}
                ):
                    continue
                execution_scope = runtime_binding.get(
                    "execution_scope"
                )
                return AuthorizedJobContext(
                    job_id=str(job["id"]),
                    user_id=authoritative_user_id,
                    project_code=authoritative_project_code,
                    application_id=(
                        authoritative_application_id
                    ),
                    application_publication_id=publication_id,
                    handler_id=handler_id,
                    handler_version=handler_version,
                    resource_revision_id=str(
                        resource["resource_revision_id"]
                    ),
                    execution_scope_key=str(
                        (
                            execution_scope
                            if isinstance(execution_scope, dict)
                            else {}
                        ).get("scope_key")
                        or ""
                    ),
                    schema_version=2,
                )
        raise self._denied()

    def _publication_snapshot(
        self,
        *,
        publication_id: str,
        application_id: str,
        config_hash: str,
    ) -> dict[str, Any]:
        publication = self.database.execute_one(
            """
            select application_id, schema_version, snapshot_json, config_hash
              from business_application_publication
             where id = ?
            """,
            (publication_id,),
        )
        if (
            publication is None
            or str(publication.get("application_id") or "") != application_id
            or str(publication.get("config_hash") or "") != config_hash
            or int(publication.get("schema_version") or 0) != 1
        ):
            raise self._denied()
        try:
            snapshot = json.loads(str(publication.get("snapshot_json") or "{}"))
        except json.JSONDecodeError as exc:
            raise self._denied() from exc
        if not isinstance(snapshot, dict) or not verify_snapshot(snapshot, config_hash):
            raise self._denied()
        return snapshot

    def _handler_is_current(
        self,
        *,
        handler_id: str,
        handler_version: str,
        capability_code: str,
        agent_publication_id: str,
    ) -> bool:
        if not handler_id:
            return False
        if handler_version != "legacy-v1":
            try:
                definition = self.registry.require(
                    handler_id,
                    handler_version,
                )
            except HandlerRegistryError:
                return False
            row = self.database.execute_one(
                """
                select i.implementation_digest,
                       i.installation_status
                  from handler_installation i
                  join handler_publication p
                    on p.handler_id = i.handler_id
                   and p.handler_version = i.handler_version
                 where i.handler_id = ?
                   and i.handler_version = ?
                   and p.status = 'PUBLISHED'
                """,
                (handler_id, handler_version),
            )
            if (
                row is None
                or row["installation_status"] != "INSTALLED"
                or row["implementation_digest"]
                != definition.implementation_digest
                or capability_code
                not in definition.required_permissions
            ):
                return False
            return (
                self.database.execute_one(
                    """
                    select t.id
                      from tool_definition t
                      join agent_tool_binding b
                        on b.tool_name = t.name
                       and b.publication_id = ?
                     where t.name = ?
                       and t.enabled = 1 and t.read_only = 1
                    """,
                    (agent_publication_id, handler_id),
                )
                is not None
            )
        return (
            self.database.execute_one(
                """
                select t.id
                  from tool_definition t
                  join agent_tool_binding b
                    on b.tool_name = t.name and b.publication_id = ?
                 where t.id = ? and t.name = ?
                   and t.enabled = 1 and t.read_only = 1
                """,
                (
                    agent_publication_id,
                    handler_id,
                    capability_code,
                ),
            )
            is not None
        )

    def _matching_resource_revision(
        self,
        values: Any,
        *,
        target: TargetRef,
    ) -> dict[str, Any] | None:
        if not isinstance(values, list):
            return None
        for resource in values:
            if (
                not isinstance(resource, dict)
                or str(resource.get("resource_kind") or "") != target.kind.value
                or not self._target_matches_codes(
                    target,
                    resource,
                    allow_broader=False,
                )
            ):
                continue
            persisted = self.database.execute_one(
                """
                select r.id, r.code, r.revision, r.resource_kind, r.scope_type,
                       r.status, r.environment_id, r.base_id, r.workshop_id,
                       e.code as environment_code, b.code as base_code,
                       w.code as workshop_code
                  from platform_resource_binding r
                  left join platform_environment e on e.id = r.environment_id
                  left join platform_base b on b.id = r.base_id
                  left join platform_workshop w on w.id = r.workshop_id
                 where r.id = ?
                """,
                (str(resource.get("resource_revision_id") or ""),),
            )
            if persisted is not None and self._resource_matches_snapshot(
                persisted,
                resource,
            ):
                return resource
        return None

    @staticmethod
    def _resource_matches_snapshot(
        persisted: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> bool:
        resource_status = str(
            persisted.get("resource_status")
            or persisted.get("status")
            or ""
        )
        if resource_status != "enabled":
            return False
        string_fields = (
            ("id", "resource_revision_id"),
            ("code", "resource_code"),
            ("resource_kind", "resource_kind"),
            ("scope_type", "scope_type"),
            ("environment_id", "environment_id"),
            ("environment_code", "environment_code"),
            ("base_id", "base_id"),
            ("base_code", "base_code"),
            ("workshop_id", "workshop_id"),
            ("workshop_code", "workshop_code"),
        )
        return int(persisted.get("revision") or 0) == int(
            snapshot.get("revision") or 0
        ) and all(
            str(persisted.get(persisted_key) or "")
            == str(snapshot.get(snapshot_key) or "")
            for persisted_key, snapshot_key in string_fields
        )

    @staticmethod
    def _target_matches_codes(
        target: TargetRef,
        values: dict[str, Any],
        *,
        allow_broader: bool,
    ) -> bool:
        environment = str(values.get("environment_code") or "")
        base = str(values.get("base_code") or "")
        workshop = str(values.get("workshop_code") or "")
        if environment and environment != target.environment:
            return False
        if base and base != target.base:
            return False
        if workshop and workshop != (target.workshop or ""):
            return False
        if allow_broader:
            return True
        if not environment or not base:
            return False
        return not workshop or workshop == (target.workshop or "")

    @staticmethod
    def _denied() -> AuthorizationError:
        return AuthorizationError("Agent Job authorization context is invalid")

    def close(self) -> None:
        self.database.close()
