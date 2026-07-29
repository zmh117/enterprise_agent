from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.modules.business_application.domain.policies import (
    verify_snapshot,
)
from app.modules.authorization_center.application import (
    BusinessAuthorizationService,
)
from app.modules.internal_tools.domain import (
    HandlerDefinition,
    HandlerRegistry,
    HandlerRegistryError,
)
from app.shared.database import Database
from app.shared.exceptions import PermissionDenied


class HandlerRoleAuthorizer(Protocol):
    def allows(
        self,
        *,
        user_id: str,
        application_id: str,
        capability_code: str,
        environment_code: str,
        base_code: str,
        workshop_code: str,
    ) -> bool: ...


class BusinessRoleAuthorizerAdapter:
    def __init__(
        self,
        service: BusinessAuthorizationService,
    ) -> None:
        self.service = service

    def allows(
        self,
        *,
        user_id: str,
        application_id: str,
        capability_code: str,
        environment_code: str,
        base_code: str,
        workshop_code: str,
    ) -> bool:
        return bool(
            self.service.decide(
                user_id=user_id,
                application_id=application_id,
                capability_code=capability_code,
                environment=environment_code,
                base=base_code,
                workshop=workshop_code,
                stage="handler_resolution",
            )["allowed"]
        )


@dataclass(frozen=True)
class HandlerResolutionRequest:
    user_id: str
    application_id: str
    application_publication_id: str
    agent_publication_id: str
    agent_classification: str
    capability_code: str
    handler_id: str
    handler_version: str
    environment_code: str
    base_code: str
    workshop_code: str = ""


@dataclass(frozen=True)
class ResolvedResourceSlot:
    slot_code: str
    resource_revision_id: str
    resource_id: str
    resource_code: str
    revision: int
    resource_kind: str
    scope_type: str
    environment_id: str
    environment_code: str
    base_id: str
    base_code: str
    workshop_id: str
    workshop_code: str
    constraints: dict[str, Any]
    binding_hash: str


@dataclass(frozen=True)
class ResolvedHandler:
    definition: HandlerDefinition
    handler_publication_id: str
    application_handler_id: str
    resources: tuple[ResolvedResourceSlot, ...]


class HandlerExecutionResolver:
    """Resolve only the full installed/published/authorized intersection."""

    def __init__(
        self,
        database: Database,
        registry: HandlerRegistry,
        role_authorizer: HandlerRoleAuthorizer,
    ) -> None:
        self.database = database
        self.registry = registry
        self.role_authorizer = role_authorizer

    def resolve(
        self,
        request: HandlerResolutionRequest,
    ) -> ResolvedHandler:
        definition = self._installed_definition(request)
        if (
            definition.visibility == "internal_diagnostic"
            and request.agent_classification
            != "internal_diagnostic"
        ):
            raise self._denied(
                "Internal diagnostic Handler is not visible to this Agent"
            )
        publication = self._published_handler(request, definition)
        application_handler = self._application_handler(
            request,
            publication_id=str(publication["id"]),
        )
        self._assert_application_snapshot(request)
        self._assert_agent_allows(request)
        if not self.role_authorizer.allows(
            user_id=request.user_id,
            application_id=request.application_id,
            capability_code=request.capability_code,
            environment_code=request.environment_code,
            base_code=request.base_code,
            workshop_code=request.workshop_code,
        ):
            raise self._denied("Role authorization denied Handler")
        resources = self._resolve_resources(
            request,
            definition=definition,
            application_handler_id=str(application_handler["id"]),
        )
        return ResolvedHandler(
            definition=definition,
            handler_publication_id=str(publication["id"]),
            application_handler_id=str(application_handler["id"]),
            resources=resources,
        )

    def _installed_definition(
        self,
        request: HandlerResolutionRequest,
    ) -> HandlerDefinition:
        try:
            definition = self.registry.require(
                request.handler_id,
                request.handler_version,
            )
        except HandlerRegistryError as exc:
            raise self._denied("Handler is not installed in code") from exc
        installation = self.database.execute_one(
            """
            select implementation_digest, installation_status
              from handler_installation
             where handler_id = ? and handler_version = ?
            """,
            (request.handler_id, request.handler_version),
        )
        if (
            installation is None
            or installation["installation_status"] != "INSTALLED"
            or installation["implementation_digest"]
            != definition.implementation_digest
        ):
            raise self._denied(
                "Handler installation is missing or drifted"
            )
        return definition

    def _published_handler(
        self,
        request: HandlerResolutionRequest,
        definition: HandlerDefinition,
    ) -> dict[str, Any]:
        if request.capability_code not in definition.required_permissions:
            raise self._denied(
                "Capability does not satisfy Handler permission"
            )
        publication = self.database.execute_one(
            """
            select * from handler_publication
             where handler_id = ? and handler_version = ?
               and status = 'PUBLISHED'
            """,
            (request.handler_id, request.handler_version),
        )
        if publication is None:
            raise self._denied("Handler is not published")
        return publication

    def _application_handler(
        self,
        request: HandlerResolutionRequest,
        *,
        publication_id: str,
    ) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select * from business_application_publication_handler
             where application_publication_id = ?
               and handler_publication_id = ?
               and capability_code = ?
            """,
            (
                request.application_publication_id,
                publication_id,
                request.capability_code,
            ),
        )
        if row is None:
            raise self._denied(
                "Application publication does not bind Handler"
            )
        return row

    def _assert_application_snapshot(
        self,
        request: HandlerResolutionRequest,
    ) -> None:
        publication = self.database.execute_one(
            """
            select application_id, schema_version, snapshot_json, config_hash
              from business_application_publication
             where id = ?
            """,
            (request.application_publication_id,),
        )
        if (
            publication is None
            or publication["application_id"] != request.application_id
            or int(publication["schema_version"]) != 1
        ):
            raise self._denied("Application publication is invalid")
        try:
            snapshot = json.loads(str(publication["snapshot_json"]))
        except json.JSONDecodeError as exc:
            raise self._denied(
                "Application publication snapshot is invalid"
            ) from exc
        if not isinstance(snapshot, dict) or not verify_snapshot(
            snapshot,
            str(publication["config_hash"]),
        ):
            raise self._denied(
                "Application publication snapshot digest is invalid"
            )
        capabilities = {
            str(item.get("capability_code") or "")
            for item in snapshot.get("capabilities") or []
            if isinstance(item, dict)
            and bool(item.get("enabled", True))
        }
        agent = snapshot.get("agent")
        snapshot_agent_id = (
            str(agent.get("id") or "")
            if isinstance(agent, dict)
            else ""
        )
        if (
            request.capability_code not in capabilities
            or snapshot_agent_id != request.agent_publication_id
        ):
            raise self._denied(
                "Application snapshot does not allow Handler"
            )

    def _assert_agent_allows(
        self,
        request: HandlerResolutionRequest,
    ) -> None:
        row = self.database.execute_one(
            """
            select t.id
              from tool_definition t
              join agent_tool_binding b
                on b.tool_name = t.name
               and b.publication_id = ?
             where t.name = ? and t.enabled = 1 and t.read_only = 1
            """,
            (
                request.agent_publication_id,
                request.handler_id,
            ),
        )
        if row is None:
            raise self._denied("Agent publication does not allow Handler")

    def _resolve_resources(
        self,
        request: HandlerResolutionRequest,
        *,
        definition: HandlerDefinition,
        application_handler_id: str,
    ) -> tuple[ResolvedResourceSlot, ...]:
        rows = self.database.execute(
            """
            select ar.resource_slot, ar.resource_revision_id,
                   ar.constraints_json, ar.binding_hash,
                   rr.revision, r.id as resource_id,
                   r.code as resource_code, r.resource_kind, rr.status,
                   r.status as resource_status, r.scope_type,
                   r.environment_id,
                   coalesce(r.base_id, '') as base_id,
                   coalesce(r.workshop_id, '') as workshop_id,
                   e.code as environment_code,
                   coalesce(b.code, '') as base_code,
                   coalesce(w.code, '') as workshop_code
              from business_application_publication_resource ar
              join platform_resource_revision rr
                on rr.id = ar.resource_revision_id
              join platform_resource r on r.id = rr.resource_id
              join platform_environment e on e.id = r.environment_id
              left join platform_base b on b.id = r.base_id
              left join platform_workshop w on w.id = r.workshop_id
             where ar.application_handler_id = ?
            """,
            (application_handler_id,),
        )
        by_slot = {str(row["resource_slot"]): row for row in rows}
        resolved: list[ResolvedResourceSlot] = []
        for slot in definition.resource_slots:
            row = by_slot.get(slot.code)
            if row is None:
                if slot.required:
                    raise self._denied(
                        "Required Handler resource slot is not bound"
                    )
                continue
            if (
                row["resource_kind"] != slot.resource_kind
                or row["status"] != "PUBLISHED"
                or row["resource_status"] != "enabled"
                or row["scope_type"] not in slot.allowed_scope_types
            ):
                raise self._denied(
                    "Handler resource binding is unavailable"
                )
            try:
                constraints = json.loads(
                    str(row["constraints_json"] or "{}")
                )
            except json.JSONDecodeError as exc:
                raise self._denied(
                    "Handler resource constraints are invalid"
                ) from exc
            if not isinstance(constraints, dict):
                raise self._denied(
                    "Handler resource constraints are invalid"
                )
            self._assert_scope(request, row, constraints)
            resolved.append(
                ResolvedResourceSlot(
                    slot_code=slot.code,
                    resource_revision_id=str(
                        row["resource_revision_id"]
                    ),
                    resource_id=str(row["resource_id"]),
                    resource_code=str(row["resource_code"]),
                    revision=int(row["revision"]),
                    resource_kind=str(row["resource_kind"]),
                    scope_type=str(row["scope_type"]),
                    environment_id=str(row["environment_id"]),
                    environment_code=str(row["environment_code"]),
                    base_id=str(row["base_id"]),
                    base_code=str(row["base_code"]),
                    workshop_id=str(row["workshop_id"]),
                    workshop_code=str(row["workshop_code"]),
                    constraints=constraints,
                    binding_hash=str(row["binding_hash"]),
                )
            )
        if set(by_slot).difference(
            slot.code for slot in definition.resource_slots
        ):
            raise self._denied(
                "Application binds undeclared Handler resource slots"
            )
        return tuple(resolved)

    @staticmethod
    def _assert_scope(
        request: HandlerResolutionRequest,
        row: dict[str, Any],
        constraints: dict[str, Any],
    ) -> None:
        expected = {
            "environment_code": request.environment_code,
            "base_code": request.base_code,
            "workshop_code": request.workshop_code,
        }
        if row["environment_code"] != request.environment_code:
            raise HandlerExecutionResolver._denied(
                "Handler Resource environment is outside scope"
            )
        if row["base_code"] and row["base_code"] != request.base_code:
            raise HandlerExecutionResolver._denied(
                "Handler Resource base is outside scope"
            )
        if (
            row["workshop_code"]
            and row["workshop_code"] != request.workshop_code
        ):
            raise HandlerExecutionResolver._denied(
                "Handler Resource workshop is outside scope"
            )
        allowed_keys = set(expected).union(
            {
                "max_rows",
                "max_bytes",
                "timeout_seconds",
                "key_prefix",
                "label_selector",
            }
        )
        if set(constraints).difference(allowed_keys):
            raise HandlerExecutionResolver._denied(
                "Handler Resource constraints contain unknown scope"
            )
        for key, value in constraints.items():
            if (
                key in expected
                and str(value or "") != expected[key]
            ):
                raise HandlerExecutionResolver._denied(
                    "Handler Resource constraint is outside scope"
                )
            if key in {
                "max_rows",
                "max_bytes",
                "timeout_seconds",
            } and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise HandlerExecutionResolver._denied(
                    "Handler Resource numeric constraint is invalid"
                )
            if key in {
                "key_prefix",
                "label_selector",
            } and not isinstance(value, str):
                raise HandlerExecutionResolver._denied(
                    "Handler Resource string constraint is invalid"
                )

    @staticmethod
    def _denied(reason: str) -> PermissionDenied:
        return PermissionDenied(
            reason,
            safe_message="Handler 不满足完整治理与授权交集",
            error_code="handler_access_denied",
        )
