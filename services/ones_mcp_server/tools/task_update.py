from __future__ import annotations

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
    ONES_UPDATE_TASK_TOOL_IDENTIFIER,
    require_ones_tool_contract,
)
from services.ones_mcp_server.auth.principal import OnesPrincipalResolver, ResolvedOnesPrincipal
from services.ones_mcp_server.contracts import ones_tool_required_scope
from services.ones_mcp_server.credentials.refresh import OnesCredentialRefreshService
from services.ones_mcp_server.errors import OnesMcpError, OnesProviderUnauthorized, error_code
from services.ones_mcp_server.provider.task_update import OnesTaskUpdateProvider
from services.ones_mcp_server.task_update import CompiledTaskUpdate, compile_task_update
from services.ones_mcp_server.task_update_catalog import TaskUpdateFieldCatalog
from services.ones_mcp_server.tools.base import OnesToolResult


class OnesTaskUpdateService:
    tool_identifier = ONES_UPDATE_TASK_TOOL_IDENTIFIER
    read_only = False
    destructive = True
    idempotent = True
    open_world = False

    def __init__(
        self,
        *,
        resolver: OnesPrincipalResolver,
        provider: OnesTaskUpdateProvider,
        catalog: TaskUpdateFieldCatalog,
        external_actions: ExternalActionService,
        audit: McpAuditCoordinator,
        credentials: ExternalIdentityCredentialRepository,
        credential_refresh: OnesCredentialRefreshService,
    ) -> None:
        contract = require_ones_tool_contract(self.tool_identifier)
        if contract.effect != "mutation" or contract.confirmation_policy == "none":
            raise ValueError("ONES task-update Tool requires a mutation contract")
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
        errors = list(Draft202012Validator(self.input_schema).iter_errors(arguments))
        if errors:
            raise OnesMcpError(
                "ONES task-update request failed schema validation",
                safe_message="ONES 缺陷更新参数无效",
                error_code="ones_task_update_patch_invalid",
            )
        context = self.resolver.audit_context(
            claims,
            invocation_id=invocation_id,
            correlation_id=correlation_id,
            tool_identifier=self.tool_identifier,
        )
        handle = self.audit.begin(
            context,
            business_request={
                "task_uuid": str(arguments["uuid"]),
                "patch_fields": sorted(set(arguments) - {"uuid"}),
            },
        )
        started = time.monotonic()
        try:
            principal = self.resolver.resolve(claims, tool_identifier=self.tool_identifier)
            route = self.resolver.resolve_confirmation_route(principal)
            self.audit.append_event(
                handle,
                event_kind="AUTHORIZATION",
                status="SUCCEEDED",
                authorization_decision="ALLOW",
                authorization_reason="ones_identity_and_dingtalk_confirmation_route_allowed",
                business_request={"stage": "ones_task_update_prepare"},
            )
            compiled, snapshot = self._compile_with_refresh(
                claims=claims,
                handle=handle,
                principal=principal,
                arguments=arguments,
            )
            output: dict[str, Any]
            if compiled is None:
                output = {"status": "no_update"}
            else:
                summary = {
                    "operation": "更新缺陷",
                    "target": f"#{snapshot.number} {snapshot.title}",
                    "changes": list(compiled.changes),
                }
                # Rendering is the authoritative disclosure-budget check. A card
                # that cannot show every value never creates an Intent.
                render_confirmation_card(
                    {
                        "execution_provider_code": "ones",
                        "operation_code": self.contract.operation_code,
                        "target_resource_type": "task",
                    },
                    summary,
                )
                definition = MCP_TOOL_MANIFEST[self.tool_identifier]
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
                    target_resource_id=snapshot.uuid,
                    precondition={
                        "server_update_stamp": snapshot.server_update_stamp,
                        "issue_type_name": snapshot.issue_type_name,
                        "project_uuid": snapshot.project_uuid,
                        "confirmed_values": compiled.normalized_arguments,
                    },
                    field_catalog_version=self.catalog.catalog_version,
                    field_catalog_hash=self.catalog.content_sha256,
                )
                frozen = {
                    "request": compiled.normalized_arguments,
                    "provider_payload": compiled.provider_payload,
                    "changes": list(compiled.changes),
                }
                intent, _created = self.external_actions.prepare(
                    facts=facts,
                    arguments=frozen,
                    arguments_hash=json_hash(compiled.normalized_arguments),
                    safe_summary=summary,
                    mcp_call_id=str(handle.mcp_call_id),
                )
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
                business_response={"status": output["status"]},
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
                "ONES task-update preparation failed safely",
                safe_message="ONES 缺陷更新准备失败",
                error_code="ones_task_update_prepare_failed",
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

    def _compile_with_refresh(
        self,
        *,
        claims: dict[str, Any],
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> tuple[CompiledTaskUpdate | None, Any]:
        try:
            return self._compile_once(handle, principal, arguments, attempt=0)
        except OnesProviderUnauthorized:
            refreshed = self.credential_refresh.resolve_after_unauthorized(
                claims=claims,
                handle=handle,
                principal=principal,
                tool_identifier=self.tool_identifier,
            )
            try:
                result = self._compile_once(handle, refreshed, arguments, attempt=1)
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
            return result

    def _compile_once(
        self,
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
        *,
        attempt: int,
    ) -> tuple[CompiledTaskUpdate | None, Any]:
        started = time.monotonic()
        try:
            snapshot = self.provider.read_task(
                team_uuid=principal.team_id,
                task_uuid=str(arguments["uuid"]),
                provider_user_id=principal.provider_user_id,
                token=principal.credential.secrets.token,
            )
            resolved_entities = self.provider.resolve_entities(
                snapshot=snapshot,
                arguments=arguments,
                provider_user_id=principal.provider_user_id,
                token=principal.credential.secrets.token,
            )
            compiled = compile_task_update(
                arguments,
                snapshot=snapshot,
                catalog=self.catalog,
                resolved_entities=resolved_entities,
            )
            self.audit.append_event(
                handle,
                event_kind="PROVIDER",
                attempt=attempt,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request={"operation": "ones.task.update.preflight"},
                business_response={"changed": compiled is not None},
                credential_revision=principal.credential.revision,
            )
            if attempt == 0:
                self.credentials.mark_used(
                    credential_id=principal.credential.id,
                    expected_revision=principal.credential.revision,
                )
            return compiled, snapshot
        except AppError as exc:
            self.audit.append_event(
                handle,
                event_kind="PROVIDER",
                attempt=attempt,
                status="FAILED",
                error_code=error_code(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request={"operation": "ones.task.update.preflight"},
                credential_revision=principal.credential.revision,
            )
            raise
