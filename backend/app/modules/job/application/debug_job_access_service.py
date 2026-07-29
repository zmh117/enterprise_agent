from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from app.modules.authorization_center import AuthorizationCenterRepository
from app.modules.business_application.application.service import SCHEMA_VERSION
from app.modules.business_application.domain.policies import verify_snapshot
from app.modules.identity.application import AuthorizationEvaluator
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
    CreateAgentJobService,
)
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.infrastructure.repositories import AgentRepository
from app.shared.database import Database
from app.shared.exceptions import NotFound, PermissionDenied


class DebugJobAccessService:
    """Strict option discovery and read authorization for the Debug Job API."""

    _APPLICATION_OPERATIONS_ACTIONS = ("edit", "publish", "activate")
    _DEBUG_DELIVERY_TYPES = ("dingtalk_group", "webhook_callback")

    def __init__(
        self,
        *,
        database: Database,
        agent_repository: AgentRepository,
        identity_repository: IdentityRepository,
        authorization_center_repository: AuthorizationCenterRepository,
        authorization_evaluator: AuthorizationEvaluator,
        create_job_service: CreateAgentJobService,
    ) -> None:
        self.database = database
        self.agent_repository = agent_repository
        self.identity_repository = identity_repository
        self.authorization_center_repository = authorization_center_repository
        self.authorization_evaluator = authorization_evaluator
        self.create_job_service = create_job_service

    def available_options(
        self,
        *,
        user_id: str,
        environment: str = "local",
    ) -> dict[str, Any]:
        user = self.identity_repository.get_user(user_id)
        if str(user["status"]) != "enabled" or not self._debug_allowed(user_id):
            return self._empty_options(environment)
        deployments = self.database.execute(
            """
            select a.id, a.code, a.name, a.project_code,
                   d.id as deployment_id, d.publication_id,
                   p.revision as publication_revision,
                   p.revision_id, p.schema_version, p.snapshot_json, p.config_hash
              from business_application_deployment d
              join business_application a on a.id = d.application_id
              join business_application_publication p on p.id = d.publication_id
             where d.environment = ? and d.active = 1 and a.status = 'enabled'
             order by a.name, a.code
            """,
            (environment,),
        )
        applications: list[dict[str, Any]] = []
        for deployment in deployments:
            accesses = self.authorization_center_repository.business_access_for_user(
                user_id=user_id,
                application_id=str(deployment["id"]),
            )
            scopes = self._execution_scopes(accesses, environment=environment)
            if not scopes:
                continue
            snapshot = self._verified_snapshot(deployment)
            if snapshot is None or not isinstance(snapshot.get("agent"), dict):
                continue
            delivery_rows = self.database.execute(
                """
                select id, binding_order, delivery_type, connector_id, config_json
                  from business_application_revision_delivery
                 where revision_id = ? and enabled = 1
                 order by binding_order, id
                """,
                (deployment["revision_id"],),
            )
            deliveries = [
                item
                for item in delivery_rows
                if self._debug_delivery_route(item) is not None
            ]
            applications.append(
                {
                    "id": str(deployment["id"]),
                    "code": str(deployment["code"]),
                    "name": str(deployment["name"]),
                    "project_code": str(deployment["project_code"]),
                    "deployment_id": str(deployment["deployment_id"]),
                    "publication_id": str(deployment["publication_id"]),
                    "publication_revision": int(deployment["publication_revision"]),
                    "config_hash": str(deployment["config_hash"]),
                    "execution_scopes": scopes,
                    "delivery_bindings": [
                        {
                            "binding_id": str(item["id"]),
                            "binding_order": int(item["binding_order"]),
                            "delivery_type": str(item["delivery_type"]),
                            "connector_id": str(item["connector_id"]),
                        }
                        for item in deliveries
                    ],
                }
            )
        return {
            "environment": environment,
            "default_delivery": {"type": "none", "binding_id": ""},
            "applications": applications,
        }

    def create_job(
        self,
        *,
        user_id: str,
        display_name: str,
        message: str,
        application_id: str,
        execution_scope_id: str,
        delivery_binding_id: str = "",
        idempotency_key: str = "",
        continue_session_id: str = "",
        correlation_id: str,
        environment: str = "local",
    ) -> tuple[AgentJob, str]:
        if not self._debug_allowed(user_id):
            raise PermissionDenied(
                "Debug execution capability is required",
                safe_message="无权发起 Agent 调试",
                error_code="debug_execution_denied",
            )
        selection = self._require_selection(
            user_id=user_id,
            application_id=application_id,
            execution_scope_id=execution_scope_id,
            delivery_binding_id=delivery_binding_id,
            environment=environment,
        )
        application = selection["application"]
        deployment = selection["deployment"]
        publication = selection["publication"]
        snapshot = selection["snapshot"]
        scope = selection["scope"]
        reply_route = selection["reply_route"]
        agent = dict(snapshot["agent"])
        session_policy = dict(snapshot.get("session_policy") or {})
        effective_session_policy = {
            **session_policy,
            "continuous_conversation_enabled": False,
        }
        user_key = idempotency_key or uuid.uuid4().hex
        scoped_idempotency_key = ":".join(
            (
                "debug",
                user_id,
                str(publication["id"]),
                execution_scope_id,
                user_key,
            )
        )
        conversation_id = f"debug:{user_id}:{uuid.uuid4().hex}"
        routing_context = {
            "project_code": str(application["project_code"]),
            "environment": str(scope["environment_code"]),
            "base": str(scope["base_code"]),
            "workshop": str(scope["workshop_code"]),
            "service": "",
            "execution_scope_id": execution_scope_id,
            "environment_id": str(scope["environment_id"]),
            "base_id": str(scope["base_id"]),
            "workshop_id": str(scope["workshop_id"]),
        }
        delivery_summary = {
            "binding_id": delivery_binding_id,
            "type": str(reply_route.get("type") or "none"),
            "connector_id": str(reply_route.get("connector_id") or ""),
        }
        command = CreateAgentJobCommand(
            idempotency_key=scoped_idempotency_key,
            requester_id=user_id,
            requester_display_name=display_name,
            external_conversation_id=conversation_id,
            user_message=message,
            project_code=str(application["project_code"]),
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            external_event_id=scoped_idempotency_key,
            routing_context=routing_context,
            reply_route=reply_route,
            correlation_id=correlation_id,
            conversation_type="direct",
            agent_code=str(agent.get("code") or ""),
            fixed_agent_publication_id=str(agent.get("id") or ""),
            fixed_agent_revision=(
                int(agent["revision"]) if agent.get("revision") is not None else None
            ),
            fixed_agent_config_hash=str(agent.get("config_hash") or ""),
            continuous_conversation_enabled=False,
            attachments_enabled=bool(
                effective_session_policy.get("attachments_enabled", False)
            ),
            business_application_id=str(application["id"]),
            business_application_code=str(application["code"]),
            business_application_publication_id=str(publication["id"]),
            business_application_deployment_id=str(deployment["id"]),
            business_application_config_hash=str(publication["config_hash"]),
            business_application_runtime_status="debug_ready",
            business_application_route_decision={
                "correlation_id": correlation_id,
                "resolution_outcome": "matched",
                "reason_code": "debug_selection_authorized",
                "runtime_status": "debug_ready",
                "trigger_type": "debug_api",
                "source_connector_id": "connector-debug-api",
                "business_application_code": str(application["code"]),
                "business_application_publication_id": str(publication["id"]),
                "business_application_publication_revision": int(
                    publication["revision"]
                ),
                "business_application_config_hash": str(publication["config_hash"]),
                "business_application_deployment_id": str(deployment["id"]),
                "execution_scope": {
                    key: value
                    for key, value in scope.items()
                    if key != "source_role_codes"
                },
                "delivery_binding": delivery_summary,
                "idempotency_context": {
                    "user_id": user_id,
                    "publication_id": str(publication["id"]),
                    "execution_scope_id": execution_scope_id,
                },
                "session_policy": effective_session_policy,
                "legacy_fallback": False,
            },
            conversation_mode=str(
                effective_session_policy.get("conversation_mode") or "channel"
            ),
            recent_message_limit=(
                int(effective_session_policy["recent_message_limit"])
                if effective_session_policy.get("recent_message_limit") is not None
                else None
            ),
            session_policy=effective_session_policy,
            application_execution_policy=dict(
                snapshot.get("execution_policy") or {}
            ),
            continue_session_id=continue_session_id,
        )
        return self.create_job_service.execute(command), scoped_idempotency_key

    def require_job_read(self, *, user_id: str, job_id: str) -> dict[str, Any]:
        try:
            detail = self.agent_repository.get_job_detail(job_id)
        except NotFound as exc:
            raise self._job_not_found(job_id) from exc
        creator_ids = {
            str(detail.get("internal_user_id") or ""),
            str(detail.get("requester_id") or ""),
            str(detail.get("user_id") or ""),
        }
        if user_id in creator_ids:
            return detail
        role_codes = self.identity_repository.role_codes_for_user(user_id)
        if "platform-admin" in role_codes:
            return detail
        application_code = str(detail.get("business_application_code") or "")
        if application_code and any(
            self.authorization_evaluator.decide(
                user_id=user_id,
                resource_type="business_application",
                resource_code=application_code,
                action=action,
            ).allowed
            for action in self._APPLICATION_OPERATIONS_ACTIONS
        ):
            return detail
        raise self._job_not_found(job_id)

    def _require_selection(
        self,
        *,
        user_id: str,
        application_id: str,
        execution_scope_id: str,
        delivery_binding_id: str,
        environment: str,
    ) -> dict[str, Any]:
        options = self.available_options(user_id=user_id, environment=environment)
        application_option = next(
            (
                item
                for item in options["applications"]
                if str(item["id"]) == application_id
            ),
            None,
        )
        if application_option is None:
            raise self._selection_denied()
        scope = next(
            (
                item
                for item in application_option["execution_scopes"]
                if str(item["id"]) == execution_scope_id
            ),
            None,
        )
        if scope is None:
            raise self._selection_denied()
        selected_delivery = None
        if delivery_binding_id:
            selected_delivery = next(
                (
                    item
                    for item in application_option["delivery_bindings"]
                    if str(item["binding_id"]) == delivery_binding_id
                ),
                None,
            )
            if selected_delivery is None:
                raise self._selection_denied()
        deployment = self.database.execute_one(
            """
            select d.*, p.revision_id, p.revision as publication_revision,
                   p.schema_version, p.snapshot_json, p.config_hash
              from business_application_deployment d
              join business_application_publication p on p.id = d.publication_id
             where d.id = ? and d.application_id = ? and d.environment = ?
               and d.active = 1 and p.id = ?
            """,
            (
                application_option["deployment_id"],
                application_id,
                environment,
                application_option["publication_id"],
            ),
        )
        application = self.database.execute_one(
            """
            select id, code, name, project_code from business_application
             where id = ? and status = 'enabled'
            """,
            (application_id,),
        )
        if deployment is None or application is None:
            raise self._selection_denied()
        snapshot = self._verified_snapshot(deployment)
        if snapshot is None or not isinstance(snapshot.get("agent"), dict):
            raise self._selection_denied()
        publication = {
            "id": str(deployment["publication_id"]),
            "revision_id": str(deployment["revision_id"]),
            "revision": int(deployment["publication_revision"]),
            "config_hash": str(deployment["config_hash"]),
        }
        reply_route: dict[str, Any] = {
            "type": "none",
            "connector_id": "",
            "target": {},
            "options": {},
        }
        if selected_delivery is not None:
            binding = self.database.execute_one(
                """
                select id, binding_order, delivery_type, connector_id, config_json
                  from business_application_revision_delivery
                 where id = ? and revision_id = ? and enabled = 1
                """,
                (delivery_binding_id, deployment["revision_id"]),
            )
            route = self._debug_delivery_route(binding or {})
            if binding is None or route is None:
                raise self._selection_denied()
            reply_route = route
        return {
            "application": application,
            "deployment": deployment,
            "publication": publication,
            "snapshot": snapshot,
            "scope": scope,
            "reply_route": reply_route,
        }

    def _debug_allowed(self, user_id: str) -> bool:
        return self.authorization_evaluator.decide(
            user_id=user_id,
            resource_type="agent_job",
            resource_code="*",
            action="debug_execute",
        ).allowed

    @staticmethod
    def _verified_snapshot(deployment: dict[str, Any]) -> dict[str, Any] | None:
        try:
            snapshot = json.loads(str(deployment.get("snapshot_json") or "{}"))
            schema_version = int(deployment.get("schema_version") or 0)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            not isinstance(snapshot, dict)
            or schema_version != SCHEMA_VERSION
            or not verify_snapshot(snapshot, str(deployment.get("config_hash") or ""))
        ):
            return None
        return snapshot

    @classmethod
    def _debug_delivery_route(
        cls,
        binding: dict[str, Any],
    ) -> dict[str, Any] | None:
        delivery_type = str(binding.get("delivery_type") or "")
        if delivery_type not in cls._DEBUG_DELIVERY_TYPES:
            return None
        try:
            config = json.loads(str(binding.get("config_json") or "{}"))
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(config, dict):
            return None
        connector_id = str(binding.get("connector_id") or "")
        binding_id = str(binding.get("id") or "")
        target_reference = str(config.get("target_reference") or "")
        if delivery_type == "dingtalk_group":
            route_type = "dingtalk_enterprise_robot"
            target = (
                {"open_conversation_id": target_reference}
                if target_reference
                else {}
            )
        else:
            route_type = "webhook"
            target = (
                {"target_reference": target_reference}
                if target_reference
                else {}
            )
        return {
            "type": route_type,
            "connector_id": connector_id,
            "target": target,
            "options": {
                "business_application_delivery_binding_id": binding_id,
                "business_application_delivery_type": delivery_type,
            },
        }

    @classmethod
    def _execution_scopes(
        cls,
        accesses: list[dict[str, Any]],
        *,
        environment: str,
    ) -> list[dict[str, Any]]:
        merged: dict[tuple[str, str, str], dict[str, Any]] = {}
        for access in accesses:
            role_code = str(access["role_code"])
            for scope in access["scopes"]:
                if str(scope["environment_code"]) != environment:
                    continue
                key = (
                    str(scope["environment_id"]),
                    str(scope.get("base_id") or ""),
                    str(scope.get("workshop_id") or ""),
                )
                if key not in merged:
                    digest = hashlib.sha256("|".join(key).encode("utf-8")).hexdigest()[:24]
                    merged[key] = {
                        "id": f"debug_scope_{digest}",
                        "scope_key": str(scope["scope_key"]),
                        "environment_id": key[0],
                        "environment_code": str(scope["environment_code"]),
                        "base_id": key[1],
                        "base_code": str(scope.get("base_code") or ""),
                        "workshop_id": key[2],
                        "workshop_code": str(scope.get("workshop_code") or ""),
                        "source_role_codes": [],
                    }
                merged[key]["source_role_codes"].append(role_code)
        for scope in merged.values():
            scope["source_role_codes"] = sorted(set(scope["source_role_codes"]))
        return sorted(
            merged.values(),
            key=lambda item: (
                item["environment_code"],
                item["base_code"],
                item["workshop_code"],
            ),
        )

    @staticmethod
    def _empty_options(environment: str) -> dict[str, Any]:
        return {
            "environment": environment,
            "default_delivery": {"type": "none", "binding_id": ""},
            "applications": [],
        }

    @staticmethod
    def _job_not_found(job_id: str) -> NotFound:
        return NotFound(
            f"Debug Agent Job not found or not authorized: {job_id}",
            safe_message="未找到 Agent Job",
        )

    @staticmethod
    def _selection_denied() -> PermissionDenied:
        return PermissionDenied(
            "Debug Business Application selection is not authorized or unavailable",
            safe_message="无权使用所选业务应用、执行范围或投递方式",
            error_code="debug_selection_denied",
        )
