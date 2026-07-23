from __future__ import annotations

from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.business_application.application.ports import (
    AgentPublicationReader,
    CapabilityCatalogReader,
    ChannelConnectorReader,
    ComponentReference,
    IdentitySubjectReader,
    WorkflowPublicationReader,
)
from app.modules.business_application.domain.policies import (
    canonical_json,
    normalize_routing_key,
    reject_dangerous_content,
    snapshot_hash,
    validate_code,
    validate_delivery,
    validate_environment,
    validate_execution_policy,
    validate_session_policy,
    validate_status,
    validate_trigger,
    verify_snapshot,
)
from app.modules.business_application.infrastructure import BusinessApplicationRepository
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.shared.exceptions import NonRetryableExecutionError, NotFound

SCHEMA_VERSION = 1


class BusinessApplicationService:
    def __init__(
        self,
        repository: BusinessApplicationRepository,
        authorization: AuthorizationEvaluator,
        audit_service: AuditService,
        agent_reader: AgentPublicationReader,
        workflow_reader: WorkflowPublicationReader,
        connector_reader: ChannelConnectorReader,
        identity_reader: IdentitySubjectReader,
        capability_reader: CapabilityCatalogReader,
    ) -> None:
        self.repository = repository
        self.authorization = authorization
        self.audit_service = audit_service
        self.agent_reader = agent_reader
        self.workflow_reader = workflow_reader
        self.connector_reader = connector_reader
        self.identity_reader = identity_reader
        self.capability_reader = capability_reader

    def list_applications(
        self,
        *,
        actor_id: str,
        project_code: str = "",
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        values = self.repository.list_applications(
            project_codes={project_code} if project_code else None,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
        return [
            self._summary(value)
            for value in values
            if self.authorization.decide(
                user_id=actor_id,
                resource_type="business_application",
                resource_code=str(value["code"]),
                action="read",
            ).allowed
        ]

    def detail(self, *, actor_id: str, code: str) -> dict[str, Any]:
        application = self.repository.get_by_code(validate_code(code))
        self._require(actor_id, code, "read")
        return self._detail(application)

    def create(
        self,
        *,
        actor_id: str,
        code: str,
        name: str,
        description: str,
        project_code: str,
        owner_user_id: str,
    ) -> dict[str, Any]:
        self._require(actor_id, "*", "create")
        normalized_code = validate_code(code)
        normalized_project = validate_code(project_code, field="project_code")
        self._validate_metadata(name, description, owner_user_id)
        application = self.repository.create(
            code=normalized_code,
            name=name.strip(),
            description=description.strip(),
            project_code=normalized_project,
            owner_user_id=owner_user_id.strip(),
            actor_id=actor_id,
        )
        self._audit("created", actor_id, application)
        return self._detail(application)

    def update_metadata(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        name: str,
        description: str,
        project_code: str,
        owner_user_id: str,
        status: str,
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "edit")
        self._validate_metadata(name, description, owner_user_id)
        current = self.repository.get_by_code(normalized_code)
        normalized_status = validate_status(status)
        application = self.repository.update_metadata(
            code=normalized_code,
            expected_revision=expected_revision,
            name=name.strip(),
            description=description.strip(),
            project_code=validate_code(project_code, field="project_code"),
            owner_user_id=owner_user_id.strip(),
            status=normalized_status,
        )
        event = (
            "status_changed"
            if str(current["status"]) != normalized_status
            else "updated"
        )
        self._audit(event, actor_id, application)
        return self._detail(application)

    def save_draft(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "edit")
        application = self.repository.get_by_code(normalized_code)
        if str(application["status"]) == "archived":
            raise NonRetryableExecutionError(
                "Archived Business Application cannot be edited",
                safe_message="Archived Business Application cannot be edited",
                error_code="invalid_lifecycle",
            )
        reject_dangerous_content(payload)
        session_policy = validate_session_policy(dict(payload.get("session_policy") or {}))
        execution_policy = validate_execution_policy(
            dict(payload.get("execution_policy") or {})
        )
        triggers = [
            validate_trigger(dict(value), index)
            for index, value in enumerate(payload.get("triggers") or [])
        ]
        deliveries = [
            validate_delivery(dict(value), index)
            for index, value in enumerate(payload.get("deliveries") or [])
        ]
        capabilities = self._normalize_capabilities(payload.get("capabilities") or [])
        normalized = {
            "agent_publication_id": str(payload.get("agent_publication_id") or "").strip(),
            "workflow_publication_id": str(
                payload.get("workflow_publication_id") or ""
            ).strip(),
            "session_policy": session_policy,
            "execution_policy": execution_policy,
            "triggers": triggers,
            "deliveries": deliveries,
            "capabilities": capabilities,
        }
        revision = self.repository.save_revision(
            code=normalized_code,
            expected_revision=expected_revision,
            actor_id=actor_id,
            config_hash=snapshot_hash(normalized),
            agent_publication_id=str(normalized["agent_publication_id"]),
            workflow_publication_id=str(normalized["workflow_publication_id"]),
            session_policy=session_policy,
            execution_policy=execution_policy,
            triggers=triggers,
            deliveries=deliveries,
            capabilities=capabilities,
        )
        self._audit("draft_saved", actor_id, application, revision=revision)
        return revision

    def validate(
        self,
        *,
        actor_id: str,
        code: str,
        revision_id: str = "",
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "edit")
        application = self.repository.get_by_code(normalized_code)
        revision = (
            self.repository.get_revision(revision_id)
            if revision_id
            else application.get("draft")
        )
        if not isinstance(revision, dict) or str(revision["application_id"]) != str(
            application["id"]
        ):
            raise NotFound(
                "Business Application revision not found",
                safe_message="Business Application revision not found",
            )
        errors, _components = self._validate_revision(application, revision)
        result = self.repository.set_validation(
            str(revision["id"]), valid=not errors, errors=errors
        )
        self._audit("validated", actor_id, application, revision=result)
        return result

    def publish(
        self,
        *,
        actor_id: str,
        code: str,
        revision_id: str,
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "publish")
        application = self.repository.get_by_code(normalized_code)
        if str(application["status"]) != "enabled":
            raise NonRetryableExecutionError(
                "Disabled or archived Business Application cannot be published",
                safe_message="Only enabled Business Applications can be published",
                error_code="invalid_lifecycle",
            )
        revision = self.repository.get_revision(revision_id)
        if str(revision["application_id"]) != str(application["id"]):
            raise NotFound(
                "Business Application revision not found",
                safe_message="Business Application revision not found",
            )
        errors, components = self._validate_revision(application, revision)
        self.repository.set_validation(str(revision["id"]), valid=not errors, errors=errors)
        if errors:
            raise NonRetryableExecutionError(
                "Business Application publication validation failed",
                safe_message="Business Application validation failed",
                error_code="validation_failed",
                field_errors=errors,
            )
        snapshot = self._snapshot(application, revision, components)
        publication = self.repository.create_publication(
            application_id=str(application["id"]),
            revision_id=str(revision["id"]),
            revision=int(revision["revision"]),
            snapshot=snapshot,
            config_hash=snapshot_hash(snapshot),
            actor_id=actor_id,
        )
        self._audit("published", actor_id, application, publication=publication)
        return publication

    def activate(
        self,
        *,
        actor_id: str,
        code: str,
        environment: str,
        publication_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        normalized_environment = validate_environment(environment)
        self._require(actor_id, normalized_code, "activate")
        application = self.repository.get_by_code(normalized_code)
        if str(application["status"]) != "enabled":
            raise NonRetryableExecutionError(
                "Business Application is not enabled",
                safe_message="Only enabled Business Applications can be activated",
                error_code="invalid_lifecycle",
            )
        publication = self._verified_publication(publication_id)
        if str(publication["application_id"]) != str(application["id"]):
            raise NotFound(
                "Business Application publication not found",
                safe_message="Business Application publication not found",
            )
        routes = [
            {
                "trigger_type": str(trigger["trigger_type"]),
                "connector_id": str(trigger["connector_id"]),
                "normalized_routing_key": str(trigger["normalized_routing_key"]),
            }
            for trigger in publication["snapshot"].get("triggers", [])
            if bool(trigger.get("enabled", True))
        ]
        old = self.repository.get_deployment(str(application["id"]), normalized_environment)
        deployment = self.repository.activate(
            application_id=str(application["id"]),
            environment=normalized_environment,
            publication_id=publication_id,
            expected_revision=expected_revision,
            actor_id=actor_id,
            routes=routes,
        )
        self._audit(
            "activated",
            actor_id,
            application,
            publication=publication,
            environment=normalized_environment,
            previous_publication_id=str((old or {}).get("publication_id") or ""),
        )
        return {**deployment, "runtime_wired": False}

    def deactivate(
        self,
        *,
        actor_id: str,
        code: str,
        environment: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        normalized_environment = validate_environment(environment)
        self._require(actor_id, normalized_code, "activate")
        application = self.repository.get_by_code(normalized_code)
        old = self.repository.get_deployment(str(application["id"]), normalized_environment)
        deployment = self.repository.deactivate(
            application_id=str(application["id"]),
            environment=normalized_environment,
            expected_revision=expected_revision,
            actor_id=actor_id,
        )
        self._audit(
            "deactivated",
            actor_id,
            application,
            environment=normalized_environment,
            previous_publication_id=str((old or {}).get("publication_id") or ""),
        )
        return {**deployment, "runtime_wired": False}

    def publications(self, *, actor_id: str, code: str) -> list[dict[str, Any]]:
        application = self.repository.get_by_code(validate_code(code))
        self._require(actor_id, code, "read")
        return [
            {**publication, "snapshot": self._snapshot_summary(publication["snapshot"])}
            for publication in self.repository.list_publications(str(application["id"]))
        ]

    def catalog(self, *, actor_id: str, code: str) -> dict[str, Any]:
        application = self.repository.get_by_code(validate_code(code))
        self._require(actor_id, code, "read")
        project_code = str(application["project_code"])
        return {
            "agents": [vars(item) for item in self.agent_reader.catalog(project_code)],
            "workflows": [vars(item) for item in self.workflow_reader.catalog(project_code)],
            "connectors": [vars(item) for item in self.connector_reader.catalog()],
            "capabilities": [],
            "capability_catalog_connected": False,
        }

    def _validate_revision(
        self, application: dict[str, Any], revision: dict[str, Any]
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        errors: list[dict[str, str]] = []
        components: dict[str, Any] = {}
        if str(application["status"]) != "enabled":
            errors.append({"field": "status", "message": "Application must be enabled"})
        agent = self._resolve_component(
            errors,
            "agent_publication_id",
            lambda: self.agent_reader.resolve(str(revision["agent_publication_id"])),
        )
        if agent:
            components["agent"] = agent
            self._validate_component_scope(errors, application, agent, "agent_publication_id")
        workflow_id = str(revision.get("workflow_publication_id") or "")
        if workflow_id:
            workflow = self._resolve_component(
                errors,
                "workflow_publication_id",
                lambda: self.workflow_reader.resolve(workflow_id),
            )
            if workflow:
                components["workflow"] = workflow
                self._validate_component_scope(
                    errors, application, workflow, "workflow_publication_id"
                )
        components["triggers"] = []
        for index, trigger in enumerate(revision["triggers"]):
            if not trigger["enabled"]:
                continue
            reference = self._resolve_component(
                errors,
                f"triggers.{index}.connector_id",
                lambda trigger=trigger: self.connector_reader.resolve(
                    str(trigger["connector_id"]), "ingress"
                ),
            )
            if reference:
                components["triggers"].append(reference)
            if str(trigger["actor_policy"]) == "SERVICE_ACCOUNT":
                account = self._resolve_component(
                    errors,
                    f"triggers.{index}.service_account_user_id",
                    lambda trigger=trigger: self.identity_reader.resolve_service_account(
                        str(trigger["service_account_user_id"])
                    ),
                )
                if account:
                    components.setdefault("actors", []).append(account)
        components["deliveries"] = []
        for index, delivery in enumerate(revision["deliveries"]):
            if not delivery["enabled"]:
                continue
            direction = (
                "ingress"
                if str(delivery["delivery_type"]) == "reply_original"
                else "delivery"
            )
            reference = self._resolve_component(
                errors,
                f"deliveries.{index}.connector_id",
                lambda delivery=delivery, direction=direction: self.connector_reader.resolve(
                    str(delivery["connector_id"]), direction
                ),
            )
            if reference:
                components["deliveries"].append(reference)
        for index, capability in enumerate(revision["capabilities"]):
            if not capability["enabled"]:
                continue
            self._resolve_component(
                errors,
                f"capabilities.{index}.capability_code",
                lambda capability=capability: self.capability_reader.resolve(
                    str(capability["capability_code"]),
                    str(capability["version_constraint"]),
                    "",
                ),
            )
        if agent is None and not str(revision.get("agent_publication_id") or ""):
            errors.append(
                {"field": "agent_publication_id", "message": "Agent Publication is required"}
            )
        return errors, components

    @staticmethod
    def _resolve_component(
        errors: list[dict[str, str]], field: str, resolve: Any
    ) -> ComponentReference | None:
        try:
            reference = resolve()
        except Exception as exc:
            field_errors = getattr(exc, "field_errors", [])
            errors.extend(field_errors or [{"field": field, "message": "Component is unavailable"}])
            return None
        if reference.status != "enabled":
            errors.append({"field": field, "message": "Component is disabled"})
            return None
        return reference if isinstance(reference, ComponentReference) else None

    @staticmethod
    def _validate_component_scope(
        errors: list[dict[str, str]],
        application: dict[str, Any],
        component: ComponentReference,
        field: str,
    ) -> None:
        if component.project_code and component.project_code != str(
            application["project_code"]
        ):
            errors.append({"field": field, "message": "Component project scope conflicts"})

    def _snapshot(
        self,
        application: dict[str, Any],
        revision: dict[str, Any],
        components: dict[str, Any],
    ) -> dict[str, Any]:
        def component(value: ComponentReference | None) -> dict[str, Any] | None:
            if value is None:
                return None
            return {
                "id": value.id,
                "code": value.code,
                "revision": value.revision,
                "project_code": value.project_code,
                "config_hash": value.config_hash,
            }

        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "application": {
                "id": application["id"],
                "code": application["code"],
                "name": application["name"],
                "description": application["description"],
                "project_code": application["project_code"],
                "owner_user_id": application["owner_user_id"],
            },
            "revision": int(revision["revision"]),
            "agent": component(components.get("agent")),
            "workflow": component(components.get("workflow")),
            "session_policy": revision["session_policy"],
            "execution_policy": revision["execution_policy"],
            "triggers": [
                {
                    "trigger_type": item["trigger_type"],
                    "connector_id": item["connector_id"],
                    "routing_key": item["routing_key"],
                    "normalized_routing_key": item["normalized_routing_key"],
                    "actor_policy": item["actor_policy"],
                    "service_account_user_id": item["service_account_user_id"],
                    "enabled": item["enabled"],
                    "config": item["config"],
                }
                for item in revision["triggers"]
            ],
            "deliveries": [
                {
                    "delivery_type": item["delivery_type"],
                    "connector_id": item["connector_id"],
                    "enabled": item["enabled"],
                    "config": item["config"],
                }
                for item in revision["deliveries"]
            ],
            "capabilities": [
                {
                    "capability_code": item["capability_code"],
                    "version_constraint": item["version_constraint"],
                    "enabled": item["enabled"],
                }
                for item in revision["capabilities"]
            ],
            "runtime_wired": True,
        }
        reject_dangerous_content(snapshot)
        canonical_json(snapshot)
        return snapshot

    def _verified_publication(self, publication_id: str) -> dict[str, Any]:
        publication = self.repository.get_publication(publication_id)
        if int(publication["schema_version"]) != SCHEMA_VERSION:
            raise NonRetryableExecutionError(
                "Unsupported Business Application publication schema",
                safe_message="Business Application publication schema is unsupported",
                error_code="integrity_error",
            )
        if not verify_snapshot(publication["snapshot"], str(publication["config_hash"])):
            raise NonRetryableExecutionError(
                "Business Application publication hash mismatch",
                safe_message="Business Application publication integrity check failed",
                error_code="integrity_error",
            )
        return publication

    @staticmethod
    def _normalize_capabilities(values: list[Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for index, raw in enumerate(values):
            if not isinstance(raw, dict):
                raise NonRetryableExecutionError(
                    "Capability reference must be an object",
                    safe_message="Business Application configuration is invalid",
                    error_code="validation_failed",
                    field_errors=[
                        {"field": f"capabilities.{index}", "message": "Must be an object"}
                    ],
                )
            unknown = set(raw) - {
                "capability_code",
                "version_constraint",
                "enabled",
            }
            if unknown:
                raise NonRetryableExecutionError(
                    "Unknown Capability reference fields",
                    safe_message="Business Application configuration is invalid",
                    error_code="validation_failed",
                    field_errors=[
                        {
                            "field": f"capabilities.{index}.{field}",
                            "message": "Unknown field",
                        }
                        for field in sorted(unknown)
                    ],
                )
            code = validate_code(
                str(raw.get("capability_code") or ""),
                field=f"capabilities.{index}.capability_code",
            )
            version = str(raw.get("version_constraint") or "").strip()
            if len(version) > 80:
                raise NonRetryableExecutionError(
                    "Capability version constraint is too long",
                    safe_message="Business Application configuration is invalid",
                    error_code="validation_failed",
                    field_errors=[
                        {
                            "field": f"capabilities.{index}.version_constraint",
                            "message": "Must be at most 80 characters",
                        }
                    ],
                )
            key = (code, version)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "capability_code": code,
                    "version_constraint": version,
                    "enabled": bool(raw.get("enabled", True)),
                }
            )
        return result

    @staticmethod
    def _validate_metadata(name: str, description: str, owner_user_id: str) -> None:
        if not name.strip() or len(name.strip()) > 200:
            raise NonRetryableExecutionError(
                "Business Application name is invalid",
                safe_message="Business Application metadata is invalid",
                error_code="validation_failed",
                field_errors=[
                    {"field": "name", "message": "Name is required and must be bounded"}
                ],
            )
        if len(description) > 4000 or len(owner_user_id) > 200:
            raise NonRetryableExecutionError(
                "Business Application metadata is too long",
                safe_message="Business Application metadata is invalid",
                error_code="validation_failed",
                field_errors=[{"field": "description", "message": "Metadata is too long"}],
            )

    def _require(self, actor_id: str, code: str, action: str) -> None:
        self.authorization.require(
            user_id=actor_id,
            resource_type="business_application",
            resource_code=code,
            action=action,
        )

    def _audit(
        self,
        event: str,
        actor_id: str,
        application: dict[str, Any],
        *,
        revision: dict[str, Any] | None = None,
        publication: dict[str, Any] | None = None,
        environment: str = "",
        previous_publication_id: str = "",
    ) -> None:
        self.audit_service.record(
            f"business_application.{event}",
            status="SUCCEEDED",
            summary=f"Business Application {event}",
            actor_id=actor_id,
            payload={
                "application_code": application["code"],
                "application_revision": application["revision"],
                "revision_id": (revision or {}).get("id", ""),
                "publication_id": (publication or {}).get("id", ""),
                "config_hash": (publication or revision or {}).get("config_hash", ""),
                "environment": environment,
                "previous_publication_id": previous_publication_id,
                "runtime_wired": False,
            },
        )

    def _summary(self, application: dict[str, Any]) -> dict[str, Any]:
        active_environments = sorted(
            str(deployment["environment"])
            for deployment in self.repository.list_deployments(
                str(application["id"])
            )
            if deployment["active"]
        )
        return {
            "id": application["id"],
            "code": application["code"],
            "name": application["name"],
            "description": application["description"],
            "project_code": application["project_code"],
            "owner_user_id": application["owner_user_id"],
            "status": application["status"],
            "revision": application["revision"],
            "latest_publication_revision": application.get("latest_publication_revision"),
            "active_environments": active_environments,
            "runtime_wired": False,
        }

    def _detail(self, application: dict[str, Any]) -> dict[str, Any]:
        return {
            **application,
            "runtime_wired": False,
            "capability_catalog_connected": False,
        }

    @staticmethod
    def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": snapshot.get("schema_version"),
            "application": snapshot.get("application"),
            "revision": snapshot.get("revision"),
            "agent": snapshot.get("agent"),
            "workflow": snapshot.get("workflow"),
            "trigger_count": len(snapshot.get("triggers") or []),
            "delivery_count": len(snapshot.get("deliveries") or []),
            "capability_count": len(snapshot.get("capabilities") or []),
            "runtime_wired": False,
        }


class BusinessApplicationResolver:
    def __init__(self, repository: BusinessApplicationRepository) -> None:
        self.repository = repository

    def resolve_active(self, application_code: str, environment: str) -> dict[str, Any]:
        application = self.repository.get_by_code(validate_code(application_code))
        if str(application["status"]) != "enabled":
            raise self.configuration_error("Business Application is not enabled")
        deployment = self.repository.get_deployment(
            str(application["id"]), validate_environment(environment)
        )
        if deployment is None or not deployment["active"] or not deployment["publication_id"]:
            raise self.configuration_error("Business Application is not active")
        publication = self._verified(str(deployment["publication_id"]))
        return {
            "application": {
                "id": application["id"],
                "code": application["code"],
                "project_code": application["project_code"],
            },
            "deployment": deployment,
            "publication": publication,
            "runtime_wired": True,
        }

    def resolve_trigger(
        self,
        environment: str,
        trigger_type: str,
        connector_id: str,
        routing_key: str,
    ) -> dict[str, Any]:
        route = self.repository.find_route(
            environment=validate_environment(environment),
            trigger_type=trigger_type,
            connector_id=connector_id,
            normalized_routing_key=normalize_routing_key(routing_key),
        )
        if route is None:
            raise self.configuration_error("No active Business Application route")
        application = self.repository.get_by_id(str(route["application_id"]))
        return self.resolve_active(str(application["code"]), environment)

    def resolve_trigger_optional(
        self,
        environment: str,
        trigger_type: str,
        connector_id: str,
        routing_key: str,
    ) -> dict[str, Any] | None:
        route = self.repository.find_route(
            environment=validate_environment(environment),
            trigger_type=trigger_type,
            connector_id=connector_id,
            normalized_routing_key=normalize_routing_key(routing_key),
        )
        if route is None:
            return None
        application = self.repository.get_by_id(str(route["application_id"]))
        return self.resolve_active(str(application["code"]), environment)

    def _verified(self, publication_id: str) -> dict[str, Any]:
        publication = self.repository.get_publication(publication_id)
        if int(publication["schema_version"]) != SCHEMA_VERSION or not verify_snapshot(
            publication["snapshot"], str(publication["config_hash"])
        ):
            raise self.configuration_error(
                "Business Application publication integrity check failed"
            )
        return publication

    @staticmethod
    def configuration_error(message: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            message,
            safe_message="Business Application runtime configuration is unavailable",
            error_code="business_application_configuration_error",
        )
