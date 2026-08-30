from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.modules.external_action.domain import json_hash
from app.modules.external_action.service import ExternalActionService
from app.modules.mcp_audit import McpAuditCoordinator
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.dingtalk_tool_contracts import DingTalkToolContract
from app.shared.exceptions import AppError
from app.shared.tool_contract import canonical_json
from services.dingtalk_mcp_server.auth.principal import (
    DingTalkPrincipalResolver,
    ResolvedDingTalkPrincipal,
)
from services.dingtalk_mcp_server.errors import DingTalkMcpError, error_code
from services.dingtalk_mcp_server.tools.read_tool import (
    DingTalkToolResult,
    _safe_payload_summary,
    _validated_payload,
)


MutationNormalizer = Callable[
    [ResolvedDingTalkPrincipal, dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]
]
MutationPreflight = Callable[[ResolvedDingTalkPrincipal, dict[str, Any]], None]
MAX_EXTERNAL_ACTION_ARGUMENT_BYTES = 16 * 1024
MAX_EXTERNAL_ACTION_SUMMARY_BYTES = 4 * 1024


class DingTalkMutationToolService:
    def __init__(
        self,
        contract: DingTalkToolContract,
        resolver: DingTalkPrincipalResolver,
        external_actions: ExternalActionService,
        audit: McpAuditCoordinator,
        normalizer: MutationNormalizer,
        *,
        preflight: MutationPreflight | None = None,
    ) -> None:
        if contract.effect != "mutation" or contract.confirmation_policy == "none":
            raise ValueError("DingTalk mutation Tool requires a governed mutation contract")
        self.contract = contract
        self.resolver = resolver
        self.external_actions = external_actions
        self.audit = audit
        self.normalizer = normalizer
        self.preflight = preflight

    @property
    def tool_identifier(self) -> str:
        return self.contract.identifier

    @property
    def description(self) -> str:
        return self.contract.description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.contract.input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return self.contract.output_schema

    @property
    def required_scope(self) -> str:
        return self.contract.required_scope

    @property
    def operation_code(self) -> str:
        return self.contract.operation_code

    @property
    def read_only(self) -> bool:
        return self.contract.read_only

    @property
    def destructive(self) -> bool:
        return self.contract.destructive

    @property
    def idempotent(self) -> bool:
        return self.contract.idempotent

    @property
    def open_world(self) -> bool:
        return self.contract.open_world

    def authenticate(self, token: str) -> dict[str, Any]:
        return self.resolver.authenticate(token, self.contract)

    def invoke(
        self,
        *,
        claims: dict[str, Any],
        arguments: dict[str, Any],
        correlation_id: str,
        invocation_id: str,
    ) -> DingTalkToolResult:
        model_arguments = _validated_payload(
            arguments,
            self.contract.input_schema,
            kind="request",
        )
        context = self.resolver.audit_context(
            claims,
            self.contract,
            invocation_id=invocation_id,
            correlation_id=correlation_id,
        )
        handle = self.audit.begin(
            context,
            business_request=_safe_payload_summary(model_arguments),
        )
        started = time.monotonic()
        try:
            principal = self.resolver.resolve(claims, self.contract)
            self.audit.append_event(
                handle,
                event_kind="AUTHORIZATION",
                status="SUCCEEDED",
                authorization_decision="ALLOW",
                authorization_reason="principal_identity_snapshot_and_confirmation_policy_allowed",
                business_request={"stage": "dingtalk_principal_resolve"},
            )
            frozen_arguments, safe_summary = self.normalizer(principal, model_arguments)
            if (
                len(canonical_json(frozen_arguments).encode("utf-8"))
                > MAX_EXTERNAL_ACTION_ARGUMENT_BYTES
            ):
                raise DingTalkMcpError(
                    "DingTalk mutation arguments exceeded durable Intent limit",
                    safe_message="钉钉外部操作参数超过确认与执行上限",
                    error_code="dingtalk_mutation_arguments_too_large",
                )
            if (
                len(canonical_json(safe_summary).encode("utf-8"))
                > MAX_EXTERNAL_ACTION_SUMMARY_BYTES
            ):
                raise DingTalkMcpError(
                    "DingTalk mutation summary exceeded confirmation limit",
                    safe_message="钉钉外部操作确认摘要超过上限",
                    error_code="dingtalk_mutation_summary_too_large",
                )
            if self.preflight is not None:
                self.preflight(principal, frozen_arguments)
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
                "operation_code": definition.operation_code,
            }
            intent, _created = self.external_actions.prepare(
                facts=facts,
                arguments=frozen_arguments,
                arguments_hash=json_hash(frozen_arguments),
                safe_summary=safe_summary,
                mcp_call_id=handle.mcp_call_id,
            )
            output = _validated_payload(
                {
                    "status": "confirmation_required",
                    "action_intent_id": str(intent["id"]),
                    "revision": int(intent["revision"]),
                    "expires_at": str(intent["expires_at"]),
                    "summary": safe_summary,
                },
                self.contract.output_schema,
                kind="response",
            )
            self.audit.complete(
                handle,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response=_safe_payload_summary(output),
            )
            return DingTalkToolResult(output, handle)
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
            wrapped = DingTalkMcpError(
                "DingTalk mutation preparation failed safely",
                safe_message="钉钉外部操作准备失败",
                error_code="dingtalk_mutation_prepare_failed",
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
