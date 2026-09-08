from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from app.modules.identity.infrastructure.external_identity_credentials import (
    ExternalIdentityCredentialRepository,
)
from app.modules.mcp_audit import McpAuditCoordinator, McpAuditHandle
from app.shared.exceptions import AppError
from services.ones_mcp_server.auth.principal import (
    OnesPrincipalResolver,
    ResolvedOnesPrincipal,
)
from services.ones_mcp_server.contracts import (
    ISSUE_TYPES,
    PROVIDER_HEADERS,
    REQUIRED_SCOPE,
    TOOL_DESCRIPTION,
    TOOL_INPUT_SCHEMA,
    TOOL_IDENTIFIER,
    TOOL_OUTPUT_SCHEMA,
)
from services.ones_mcp_server.credentials.refresh import OnesCredentialRefreshService
from services.ones_mcp_server.errors import (
    OnesMcpError,
    OnesProviderUnauthorized,
    error_code,
    invalid_provider_response,
)
from services.ones_mcp_server.pagination import (
    MAX_WORK_ITEM_SEARCH_RESULTS,
    OnesWorkItemSearchCursorCodec,
    OnesWorkItemSearchPage,
)
from services.ones_mcp_server.provider.graphql.client import OnesGraphqlClient
from services.ones_mcp_server.provider.graphql.operations.work_item_search import (
    WORK_ITEM_SEARCH_OPERATION_CODE,
)


class OnesSearchResult(dict[str, Any]):
    def __init__(self, payload: dict[str, Any], audit_handle: McpAuditHandle) -> None:
        super().__init__(payload)
        self.audit_handle = audit_handle


class OnesWorkItemSearchService:
    tool_identifier = TOOL_IDENTIFIER
    description = TOOL_DESCRIPTION
    input_schema = TOOL_INPUT_SCHEMA
    output_schema = TOOL_OUTPUT_SCHEMA
    required_scope = REQUIRED_SCOPE
    operation_code = WORK_ITEM_SEARCH_OPERATION_CODE
    read_only = True
    destructive = False
    idempotent = True
    open_world = False

    def __init__(
        self,
        resolver: OnesPrincipalResolver,
        graphql: OnesGraphqlClient,
        credentials: ExternalIdentityCredentialRepository,
        audit: McpAuditCoordinator,
        credential_refresh: OnesCredentialRefreshService,
    ) -> None:
        self.resolver = resolver
        self.graphql = graphql
        self.credentials = credentials
        self.audit = audit
        self.credential_refresh = credential_refresh

    def authenticate(self, token: str) -> dict[str, Any]:
        return self.resolver.authenticate(token, required_scope=self.required_scope)

    def search(
        self,
        *,
        claims: dict[str, Any],
        arguments: dict[str, Any],
        correlation_id: str,
        invocation_id: str = "",
    ) -> OnesSearchResult:
        tool_request = self._validate_arguments(arguments)
        base_context = self.resolver.audit_context(
            claims,
            invocation_id=invocation_id,
            correlation_id=correlation_id,
            tool_identifier=self.tool_identifier,
        )
        handle = self.audit.begin(
            base_context,
            business_request=tool_request,
        )
        started = time.monotonic()
        authorization_persisted = False
        try:
            principal = self.resolver.resolve(
                claims,
                tool_identifier=self.tool_identifier,
            )
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
            page = OnesWorkItemSearchCursorCodec.decode(
                str(tool_request.get("cursor") or ""),
                claims=claims,
                principal=principal,
                request=tool_request,
            )
            provider_request = {
                "keyword": tool_request["keyword"],
                "issue_type": tool_request["issue_type"],
                "limit": min(int(tool_request["limit"]), page.remaining),
                "provider_cursor": page.provider_cursor,
                "cumulative_returned": page.cumulative_returned,
            }
            provider_output = self._search_with_refresh(
                claims=claims,
                handle=handle,
                principal=principal,
                tool_request=provider_request,
            )
            output = self._public_page_output(
                provider_output,
                claims=claims,
                principal=principal,
                tool_request=tool_request,
                page=page,
            )
            self.audit.complete(
                handle,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response=output,
            )
            return OnesSearchResult(output, handle)
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

    def invoke(
        self,
        *,
        claims: dict[str, Any],
        arguments: dict[str, Any],
        correlation_id: str,
        invocation_id: str,
    ) -> OnesSearchResult:
        return self.search(
            claims=claims,
            arguments=arguments,
            correlation_id=correlation_id,
            invocation_id=invocation_id,
        )

    def _search_with_refresh(
        self,
        *,
        claims: dict[str, Any],
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        tool_request: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return self._provider_attempt(handle, principal, tool_request, attempt=0)
        except OnesProviderUnauthorized:
            pass
        refreshed = self.credential_refresh.resolve_after_unauthorized(
            claims=claims,
            handle=handle,
            principal=principal,
            tool_identifier=self.tool_identifier,
        )
        try:
            output = self._provider_attempt(handle, refreshed, tool_request, attempt=1)
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
        tool_request: dict[str, Any],
        *,
        attempt: int,
    ) -> dict[str, Any]:
        started = time.monotonic()
        context = {
            "user_id": principal.provider_user_id,
            "team_id": principal.team_id,
        }
        provider_request = self.graphql.build_request(
            self.operation_code,
            arguments=tool_request,
            context=context,
        )
        try:
            execution = self.graphql.execute(
                self.operation_code,
                arguments=tool_request,
                context=context,
                headers={
                    PROVIDER_HEADERS["token"]: principal.credential.secrets.token,
                    PROVIDER_HEADERS["user"]: principal.provider_user_id,
                },
            )
            self.audit.append_event(
                handle,
                event_kind="PROVIDER",
                attempt=attempt,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request=execution.request,
                business_response={
                    "provider_response": execution.response,
                    "tool": {
                        key: value
                        for key, value in execution.output.items()
                        if not key.startswith("_provider_")
                    },
                },
                credential_revision=principal.credential.revision,
            )
            if attempt == 0:
                self.credentials.mark_used(
                    credential_id=principal.credential.id,
                    expected_revision=principal.credential.revision,
                )
            return execution.output
        except AppError as exc:
            self.audit.append_event(
                handle,
                event_kind="PROVIDER",
                attempt=attempt,
                status="FAILED",
                error_code=error_code(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request=provider_request,
                credential_revision=principal.credential.revision,
            )
            raise

    @staticmethod
    def _public_page_output(
        provider_output: dict[str, Any],
        *,
        claims: dict[str, Any],
        principal: ResolvedOnesPrincipal,
        tool_request: dict[str, Any],
        page: OnesWorkItemSearchPage,
    ) -> dict[str, Any]:
        items = provider_output.get("items")
        total = provider_output.get("total")
        truncated = provider_output.get("truncated")
        provider_cursor = provider_output.get("_provider_cursor")
        if (
            not isinstance(items, list)
            or type(total) is not int
            or total < 0
            or type(truncated) is not bool
            or not isinstance(provider_cursor, str)
        ):
            raise invalid_provider_response("ones_provider_schema_invalid")
        returned = len(items)
        cumulative_returned = page.cumulative_returned + returned
        if (
            returned > int(tool_request["limit"])
            or cumulative_returned > MAX_WORK_ITEM_SEARCH_RESULTS
        ):
            raise invalid_provider_response("ones_provider_schema_invalid")
        pagination_limit_reached = (
            truncated and cumulative_returned >= MAX_WORK_ITEM_SEARCH_RESULTS
        )
        output: dict[str, Any] = {
            "items": items,
            "total": total,
            "returned": returned,
            "cumulative_returned": cumulative_returned,
            "truncated": truncated,
            "pagination_limit_reached": pagination_limit_reached,
            "untrusted_data": True,
        }
        if truncated and not pagination_limit_reached:
            if not provider_cursor:
                raise invalid_provider_response("ones_provider_schema_invalid")
            output["next_cursor"] = OnesWorkItemSearchCursorCodec.encode(
                provider_cursor=provider_cursor,
                cumulative_returned=cumulative_returned,
                claims=claims,
                principal=principal,
                request=tool_request,
            )
        return output

    @staticmethod
    def _validate_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        if (
            not isinstance(arguments, dict)
            or not {"keyword", "issue_type", "limit"}.issubset(arguments)
            or not set(arguments).issubset({"keyword", "issue_type", "limit", "cursor"})
        ):
            raise OnesMcpError(
                "ONES Tool input fields are invalid",
                safe_message="ONES 查询参数无效",
                error_code="ones_tool_input_invalid",
            )
        keyword = arguments.get("keyword")
        issue_type = arguments.get("issue_type")
        limit = arguments.get("limit")
        cursor = arguments.get("cursor", "")
        if (
            not isinstance(keyword, str)
            or not 1 <= len(keyword) <= 200
            or issue_type not in ISSUE_TYPES
            or type(limit) is not int
            or not 1 <= limit <= 50
            or not isinstance(cursor, str)
            or len(cursor) > 4096
        ):
            raise OnesMcpError(
                "ONES Tool input values are invalid",
                safe_message="ONES 查询参数无效",
                error_code="ones_tool_input_invalid",
            )
        return {
            "keyword": keyword,
            "issue_type": issue_type,
            "limit": limit,
            **({"cursor": cursor} if cursor else {}),
        }
