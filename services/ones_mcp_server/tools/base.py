from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import Any

from app.modules.identity.infrastructure.external_identity_credentials import (
    ExternalIdentityCredentialRepository,
)
from app.modules.mcp_audit import McpAuditCoordinator, McpAuditHandle
from app.shared.exceptions import AppError
from app.shared.ones_tool_contracts import require_ones_tool_contract
from services.ones_mcp_server.auth.principal import (
    OnesPrincipalResolver,
    ResolvedOnesPrincipal,
)
from services.ones_mcp_server.contracts import ones_tool_required_scope
from services.ones_mcp_server.credentials.refresh import OnesCredentialRefreshService
from services.ones_mcp_server.errors import OnesMcpError, OnesProviderUnauthorized, error_code


class OnesToolResult(dict[str, Any]):
    def __init__(self, payload: dict[str, Any], audit_handle: McpAuditHandle) -> None:
        super().__init__(payload)
        self.audit_handle = audit_handle


@dataclass(frozen=True, slots=True)
class ProviderCall:
    output: dict[str, Any]
    request_summary: dict[str, Any]
    response_summary: dict[str, Any]


class BaseOnesQueryService(ABC):
    tool_identifier: str
    read_only = True
    destructive = False
    idempotent = True
    open_world = False

    def __init__(
        self,
        resolver: OnesPrincipalResolver,
        credentials: ExternalIdentityCredentialRepository,
        audit: McpAuditCoordinator,
        credential_refresh: OnesCredentialRefreshService,
    ) -> None:
        contract = require_ones_tool_contract(self.tool_identifier)
        self.description = contract.description
        self.input_schema = contract.input_schema
        self.output_schema = contract.output_schema
        self.required_scope = ones_tool_required_scope(self.tool_identifier)
        self.resolver = resolver
        self.credentials = credentials
        self.audit = audit
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
        tool_request = self.validate_arguments(arguments)
        base_context = self.resolver.audit_context(
            claims,
            invocation_id=invocation_id,
            correlation_id=correlation_id,
            tool_identifier=self.tool_identifier,
        )
        handle = self.audit.begin(base_context, business_request=tool_request)
        started = time.monotonic()
        authorization_persisted = False
        try:
            principal = self.resolver.resolve(claims, tool_identifier=self.tool_identifier)
            handle = self.audit.enrich_context(
                handle,
                replace(
                    base_context,
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
                authorization_reason="principal_identity_and_scope_allowed",
                business_request={"stage": "ones_principal_resolve"},
            )
            authorization_persisted = True
            output = self._execute_with_refresh(
                claims=claims,
                handle=handle,
                principal=principal,
                arguments=tool_request,
            )
            self.audit.complete(
                handle,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response=output,
            )
            return OnesToolResult(output, handle)
        except AppError as exc:
            setattr(exc, "mcp_audit_handle", handle)
            if getattr(exc, "error_code", "") == "mcp_audit_unavailable":
                raise
            if not authorization_persisted:
                self.audit.append_event(
                    handle,
                    event_kind="AUTHORIZATION",
                    status="DENIED",
                    error_code=error_code(exc),
                    authorization_decision="DENY",
                    authorization_reason=error_code(exc),
                    business_request={"stage": "ones_principal_resolve"},
                )
            self.audit.complete(
                handle,
                status="DENIED" if not authorization_persisted else "FAILED",
                error_code=error_code(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response={
                    "error": str(exc.safe_message),
                    "error_code": error_code(exc),
                },
            )
            raise
        except Exception:
            failure = OnesMcpError(
                "ONES MCP query failed unexpectedly",
                safe_message="ONES 查询暂时不可用",
                error_code="ones_mcp_unavailable",
            )
            setattr(failure, "mcp_audit_handle", handle)
            if not authorization_persisted:
                self.audit.append_event(
                    handle,
                    event_kind="AUTHORIZATION",
                    status="DENIED",
                    error_code=failure.error_code,
                    authorization_decision="DENY",
                    authorization_reason=failure.error_code,
                    business_request={"stage": "ones_principal_resolve"},
                )
            self.audit.complete(
                handle,
                status="DENIED" if not authorization_persisted else "FAILED",
                error_code=failure.error_code,
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response={
                    "error": str(failure.safe_message),
                    "error_code": failure.error_code,
                },
            )
            raise failure from None

    def _execute_with_refresh(
        self,
        *,
        claims: dict[str, Any],
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return self._provider_attempt(handle, principal, arguments, attempt=0)
        except OnesProviderUnauthorized:
            pass
        refreshed = self.credential_refresh.resolve_after_unauthorized(
            claims=claims,
            handle=handle,
            principal=principal,
            tool_identifier=self.tool_identifier,
        )
        try:
            output = self._provider_attempt(handle, refreshed, arguments, attempt=1)
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
        return output

    def _provider_attempt(
        self,
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
        *,
        attempt: int,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            call = self.call_provider(principal, arguments)
            self.audit.append_event(
                handle,
                event_kind="PROVIDER",
                attempt=attempt,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request=call.request_summary,
                business_response=call.response_summary,
                credential_revision=principal.credential.revision,
            )
            if attempt == 0:
                self.credentials.mark_used(
                    credential_id=principal.credential.id,
                    expected_revision=principal.credential.revision,
                )
            return call.output
        except AppError as exc:
            self.audit.append_event(
                handle,
                event_kind="PROVIDER",
                attempt=attempt,
                status="FAILED",
                error_code=error_code(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request={"operation": self.tool_identifier},
                credential_revision=principal.credential.revision,
            )
            raise
        except Exception:
            self.audit.append_event(
                handle,
                event_kind="PROVIDER",
                attempt=attempt,
                status="FAILED",
                error_code="ones_mcp_unavailable",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request={"operation": self.tool_identifier},
                credential_revision=principal.credential.revision,
            )
            raise OnesMcpError(
                "ONES Provider operation failed unexpectedly",
                safe_message="ONES 查询暂时不可用",
                error_code="ones_mcp_unavailable",
            ) from None

    @staticmethod
    def response_summary(output: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {"result_keys": sorted(output)}
        for key in ("total", "returned", "truncated"):
            if key in output:
                summary[key] = output[key]
        return summary

    @abstractmethod
    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def call_provider(
        self,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> ProviderCall: ...
