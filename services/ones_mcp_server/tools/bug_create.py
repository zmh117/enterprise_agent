from __future__ import annotations

from dataclasses import replace
import json
import secrets
import string
import time
from typing import Any

from jsonschema import Draft202012Validator

from app.modules.external_action.card import render_confirmation_card
from app.modules.external_action.domain import ExternalActionIntentFacts, json_hash
from app.modules.external_action.service import ExternalActionService
from app.modules.identity.infrastructure.external_identity_credentials import (
    ExternalIdentityCredentialRepository,
)
from app.modules.mcp_audit import McpAuditCoordinator, McpAuditHandle
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.exceptions import AppError
from app.shared.ones_tool_contracts import (
    ONES_CREATE_BUG_TOOL_IDENTIFIER,
    require_ones_tool_contract,
)
from services.ones_mcp_server.auth.principal import OnesPrincipalResolver, ResolvedOnesPrincipal
from services.ones_mcp_server.bug_create import compile_bug_create, validate_bug_create_arguments
from services.ones_mcp_server.bug_create_catalog import BugCreateFieldCatalog
from services.ones_mcp_server.contracts import ones_tool_required_scope
from services.ones_mcp_server.credentials.refresh import OnesCredentialRefreshService
from services.ones_mcp_server.errors import OnesMcpError, OnesProviderUnauthorized, error_code
from services.ones_mcp_server.provider.bug_create import BugCreatePreflight, OnesBugCreateProvider
from services.ones_mcp_server.tools.base import OnesToolResult


_TASK_UUID_ALPHABET = string.ascii_letters + string.digits


def _new_task_uuid() -> str:
    return "".join(secrets.choice(_TASK_UUID_ALPHABET) for _ in range(16))


class OnesBugCreateService:
    tool_identifier = ONES_CREATE_BUG_TOOL_IDENTIFIER
    read_only = False
    destructive = True
    idempotent = True
    open_world = False

    def __init__(
        self,
        *,
        resolver: OnesPrincipalResolver,
        provider: OnesBugCreateProvider,
        catalog: BugCreateFieldCatalog,
        external_actions: ExternalActionService,
        audit: McpAuditCoordinator,
        credentials: ExternalIdentityCredentialRepository,
        credential_refresh: OnesCredentialRefreshService,
    ) -> None:
        contract = require_ones_tool_contract(self.tool_identifier)
        if contract.operation_code != "ones.task.create" or contract.confirmation_policy == "none":
            raise ValueError("ONES bug-create Tool requires its governed mutation contract")
        self.contract = contract
        self.description = contract.description
        self.input_schema = contract.input_schema
        self.output_schema = contract.output_schema
        self.required_scope = ones_tool_required_scope(self.tool_identifier)
        self.resolver = resolver
        self.provider = provider
        self.catalog = catalog
        self.external_actions = external_actions
        self.audit = audit
        self.credentials = credentials
        self.credential_refresh = credential_refresh

    def authenticate(self, token: str) -> dict[str, Any]:
        return self.resolver.authenticate(token, required_scope=self.required_scope)

    def invoke(
        self,
        *,
        claims: dict[str, Any],
        arguments: dict[str, Any],
        correlation_id: str,
        invocation_id: str,
    ) -> OnesToolResult:
        normalized = validate_bug_create_arguments(arguments)
        context = self.resolver.audit_context(
            claims,
            invocation_id=invocation_id,
            correlation_id=correlation_id,
            tool_identifier=self.tool_identifier,
        )
        handle = self.audit.begin(
            context,
            business_request={
                "operation": "ones.task.create.prepare",
                "business_fields": sorted(normalized),
                "suggested_fields": sorted(
                    str(item["field"]) for item in normalized["field_provenance"]
                ),
            },
        )
        started = time.monotonic()
        try:
            principal = self.resolver.resolve(claims, tool_identifier=self.tool_identifier)
            route = self.resolver.resolve_confirmation_route(principal)
            handle = self.audit.enrich_context(
                handle,
                replace(
                    context,
                    principal_jti=principal.principal_jti,
                    external_identity_id=principal.external_identity_id,
                    credential_id=principal.credential.id,
                    credential_revision=principal.credential.revision,
                    provider="ones",
                    team_id=principal.team_id,
                    provider_email=principal.provider_email,
                    provider_user_id=principal.provider_user_id,
                ),
            )
            self.audit.append_event(
                handle,
                event_kind="AUTHORIZATION",
                status="SUCCEEDED",
                authorization_decision="ALLOW",
                authorization_reason="ones_identity_and_dingtalk_confirmation_route_allowed",
                business_request={"stage": "ones_bug_create_prepare"},
                credential_revision=principal.credential.revision,
            )
            preflight, principal = self._preflight_with_refresh(
                claims=claims,
                handle=handle,
                principal=principal,
                arguments=arguments,
            )
            task_uuid = _new_task_uuid()
            compiled = compile_bug_create(
                arguments,
                catalog=self.catalog,
                team_uuid=principal.team_id,
                task_uuid=task_uuid,
                current_user_uuid=principal.provider_user_id,
                display_values=preflight.display_values,
            )
            render_confirmation_card(
                {
                    "execution_provider_code": "ones",
                    "operation_code": self.contract.operation_code,
                    "target_resource_type": "task",
                },
                compiled.summary,
            )
            definition = MCP_TOOL_MANIFEST[self.tool_identifier]
            identity_row = self.resolver.database.execute_one(
                "select revision from user_external_identity where id = ?",
                (principal.external_identity_id,),
            )
            if identity_row is None:
                raise OnesMcpError(
                    "ONES identity disappeared before proposal",
                    safe_message="ONES 身份已变化，请重新发起",
                    error_code="ones_bug_create_identity_changed",
                )
            facts = ExternalActionIntentFacts(
                job_id=principal.job_id,
                session_id=principal.session_id,
                actor_user_id=principal.actor_user_id,
                business_application_id=principal.business_application_id,
                agent_publication_id=principal.agent_publication_id,
                application_publication_id=principal.application_publication_id,
                source_connector_id=route.source_connector_id,
                dingtalk_enterprise_id=route.dingtalk_enterprise_id,
                target_external_subject_id=route.target_external_subject_id,
                target_union_id=route.target_union_id,
                server_code=definition.server_code,
                tool_identifier=definition.identifier,
                schema_hash=definition.schema_hash,
                confirmation_policy=definition.confirmation_policy,
                operation_code=definition.operation_code,
                confirmation_channel_code="dingtalk",
                execution_provider_code="ones",
                execution_external_identity_id=principal.external_identity_id,
                execution_scope_id=principal.team_id,
                target_resource_type="task",
                target_resource_id=task_uuid,
                precondition={
                    "identity_revision": int(identity_row["revision"]),
                    "credential_revision": principal.credential.revision,
                    "layout_version": preflight.layout_version,
                    "validation_hash": preflight.validation_hash,
                    "display_values": preflight.display_values,
                    "confirmed_values": compiled.normalized_arguments,
                },
                field_catalog_version=self.catalog.catalog_version,
                field_catalog_hash=self.catalog.content_sha256,
                supersedes_intent_id=str(arguments.get("supersedes_intent_id") or ""),
            )
            frozen = {"request": compiled.normalized_arguments}
            intent, created = self.external_actions.prepare(
                facts=facts,
                arguments=frozen,
                arguments_hash=json_hash(compiled.normalized_arguments),
                safe_summary=compiled.summary,
                mcp_call_id=str(handle.mcp_call_id),
                ttl_seconds=900,
            )
            summary = compiled.summary
            if not created:
                stored = self._json_object(intent.get("confirmation_summary_json"))
                if stored:
                    summary = stored
            output = {
                "status": "confirmation_required",
                "action_intent_id": str(intent["id"]),
                "revision": int(intent["revision"]),
                "expires_at": str(intent["expires_at"]),
                "summary": summary,
            }
            Draft202012Validator(self.output_schema).validate(output)
            self.audit.complete(
                handle,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response={
                    "status": output["status"],
                    "action_intent_id": output["action_intent_id"],
                    "proposal_created": created,
                },
            )
            return OnesToolResult(output, handle)
        except AppError as exc:
            setattr(exc, "mcp_audit_handle", handle)
            self.audit.complete(
                handle,
                status="DENIED",
                error_code=error_code(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response={"error_code": error_code(exc)},
            )
            raise
        except Exception as exc:
            wrapped = OnesMcpError(
                "ONES bug-create preparation failed safely",
                safe_message="ONES 缺陷创建准备失败",
                error_code="ones_bug_create_prepare_failed",
            )
            setattr(wrapped, "mcp_audit_handle", handle)
            self.audit.complete(
                handle,
                status="FAILED",
                error_code=wrapped.error_code,
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response={"error_code": wrapped.error_code},
            )
            raise wrapped from exc

    def _preflight_with_refresh(
        self,
        *,
        claims: dict[str, Any],
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> tuple[BugCreatePreflight, ResolvedOnesPrincipal]:
        try:
            return self._preflight(handle, principal, arguments, attempt=0), principal
        except OnesProviderUnauthorized:
            refreshed = self.credential_refresh.resolve_after_unauthorized(
                claims=claims,
                handle=handle,
                principal=principal,
                tool_identifier=self.tool_identifier,
            )
            try:
                preflight = self._preflight(handle, refreshed, arguments, attempt=1)
            except OnesProviderUnauthorized:
                self.credential_refresh.reject_after_second_unauthorized(
                    handle=handle,
                    principal=refreshed,
                )
                raise AssertionError("credential refresh rejection must raise")
            self.credentials.mark_used(
                credential_id=refreshed.credential.id,
                expected_revision=refreshed.credential.revision,
            )
            return preflight, refreshed

    def _preflight(
        self,
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
        *,
        attempt: int,
    ) -> BugCreatePreflight:
        started = time.monotonic()
        try:
            result = self.provider.preflight_create(
                team_uuid=principal.team_id,
                provider_user_id=principal.provider_user_id,
                token=principal.credential.secrets.token,
                arguments=arguments,
            )
            self.audit.append_event(
                handle,
                event_kind="PROVIDER",
                attempt=attempt,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request={"operation": "ones.task.create.preflight"},
                business_response={
                    "layout_version": result.layout_version,
                    "validation_hash": result.validation_hash,
                },
                credential_revision=principal.credential.revision,
            )
            if attempt == 0:
                self.credentials.mark_used(
                    credential_id=principal.credential.id,
                    expected_revision=principal.credential.revision,
                )
            return result
        except AppError as exc:
            self.audit.append_event(
                handle,
                event_kind="PROVIDER",
                attempt=attempt,
                status="FAILED",
                error_code=error_code(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request={"operation": "ones.task.create.preflight"},
                credential_revision=principal.credential.revision,
            )
            raise

    @staticmethod
    def _json_object(value: object) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
