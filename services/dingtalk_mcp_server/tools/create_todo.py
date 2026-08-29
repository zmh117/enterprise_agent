from __future__ import annotations

import time
from typing import Any

from app.modules.external_action.domain import json_hash, normalize_todo_arguments
from app.modules.external_action.service import ExternalActionService
from app.modules.mcp_audit import McpAuditCoordinator, McpAuditHandle
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.exceptions import AppError
from services.dingtalk_mcp_server.auth.principal import DingTalkPrincipalResolver
from services.dingtalk_mcp_server.contracts import (
    OPERATION_CODE,
    REQUIRED_SCOPE,
    TOOL_CONTRACT,
    TOOL_IDENTIFIER,
)
from services.dingtalk_mcp_server.errors import error_code


class DingTalkActionResult(dict[str, Any]):
    def __init__(self, payload: dict[str, Any], audit_handle: McpAuditHandle) -> None:
        super().__init__(payload)
        self.audit_handle = audit_handle


class DingTalkCreateTodoService:
    tool_identifier = TOOL_IDENTIFIER
    description = TOOL_CONTRACT.description
    input_schema = TOOL_CONTRACT.input_schema
    output_schema = TOOL_CONTRACT.output_schema
    required_scope = REQUIRED_SCOPE
    operation_code = OPERATION_CODE
    read_only = False
    destructive = True
    idempotent = True
    open_world = False

    def __init__(
        self,
        resolver: DingTalkPrincipalResolver,
        external_actions: ExternalActionService,
        audit: McpAuditCoordinator,
    ) -> None:
        self.resolver = resolver
        self.external_actions = external_actions
        self.audit = audit

    def authenticate(self, token: str) -> dict[str, Any]:
        return self.resolver.authenticate(token)

    def invoke(
        self,
        *,
        claims: dict[str, Any],
        arguments: dict[str, Any],
        correlation_id: str,
        invocation_id: str,
    ) -> DingTalkActionResult:
        normalized = normalize_todo_arguments(arguments)
        business_request = normalized.as_dict()
        context = self.resolver.audit_context(
            claims,
            invocation_id=invocation_id,
            correlation_id=correlation_id,
        )
        handle = self.audit.begin(context, business_request=business_request)
        started = time.monotonic()
        try:
            principal = self.resolver.resolve(claims)
            self.audit.append_event(
                handle,
                event_kind="AUTHORIZATION",
                status="SUCCEEDED",
                authorization_decision="ALLOW",
                authorization_reason="principal_identity_snapshot_and_confirmation_policy_allowed",
                business_request={"stage": "dingtalk_principal_resolve"},
            )
            definition = MCP_TOOL_MANIFEST[self.tool_identifier]
            facts = {
                "job_id": principal.job_id,
                "session_id": principal.session_id,
                "actor_user_id": principal.actor_user_id,
                "business_application_id": principal.business_application_id,
                "agent_publication_id": principal.agent_publication_id,
                "application_publication_id": principal.application_publication_id,
                "source_connector_id": principal.source_connector_id,
                "dingtalk_enterprise_id": principal.dingtalk_enterprise_id,
                "target_external_subject_id": principal.target_external_subject_id,
                "target_union_id": principal.target_union_id,
                "server_code": definition.server_code,
                "tool_identifier": definition.identifier,
                "schema_hash": definition.schema_hash,
                "confirmation_policy": definition.confirmation_policy,
                "operation_code": self.operation_code,
            }
            safe_summary = {
                "operation": "创建钉钉待办",
                "subject": normalized.subject,
                "due_time": normalized.due_time,
            }
            intent, _created = self.external_actions.prepare(
                facts=facts,
                arguments=business_request,
                arguments_hash=json_hash(business_request),
                safe_summary=safe_summary,
                mcp_call_id=handle.mcp_call_id,
            )
            output = {
                "status": "confirmation_required",
                "action_intent_id": str(intent["id"]),
                "revision": int(intent["revision"]),
                "expires_at": str(intent["expires_at"]),
                "summary": safe_summary,
            }
            self.audit.complete(
                handle,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response=output,
            )
            return DingTalkActionResult(output, handle)
        except AppError as exc:
            setattr(exc, "mcp_audit_handle", handle)
            self.audit.complete(
                handle,
                status="DENIED",
                error_code=error_code(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response={
                    "error": str(exc.safe_message),
                    "error_code": error_code(exc),
                },
            )
            raise

