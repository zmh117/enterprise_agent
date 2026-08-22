from __future__ import annotations

import re
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
    PROJECT_ROLE_MEMBER_LIMITS,
    PROJECT_ROLE_MEMBERS_INPUT_SCHEMA,
    PROJECT_ROLE_MEMBERS_OUTPUT_SCHEMA,
    PROJECT_ROLE_MEMBERS_REQUIRED_SCOPE,
    PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER,
)
from services.ones_mcp_server.credentials.refresh import OnesCredentialRefreshService
from services.ones_mcp_server.errors import (
    OnesMcpError,
    OnesProviderUnauthorized,
    error_code,
    invalid_provider_response,
)
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient
from services.ones_mcp_server.provider.rest.operations.project_role_members import (
    PROJECT_ROLE_MEMBERS_OPERATION,
    TEAM_USERS_OPERATION,
    ProjectRoleMembersOperation,
    TeamUsersOperation,
)


_PROJECT_UUID = re.compile(r"^[A-Za-z0-9_-]+$")


class OnesProjectRoleMembersResult(dict[str, Any]):
    def __init__(self, payload: dict[str, Any], audit_handle: McpAuditHandle) -> None:
        super().__init__(payload)
        self.audit_handle = audit_handle


class OnesProjectRoleMemberService:
    tool_identifier = PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER
    description = (
        "查询当前用户默认 Team 中指定项目的角色及成员姓名。"
        "只需提供 project_uuid，不要提供 Team、用户、Token、URL 或请求头。"
    )
    input_schema = PROJECT_ROLE_MEMBERS_INPUT_SCHEMA
    output_schema = PROJECT_ROLE_MEMBERS_OUTPUT_SCHEMA
    required_scope = PROJECT_ROLE_MEMBERS_REQUIRED_SCOPE
    read_only = True
    destructive = False
    idempotent = True
    open_world = False

    def __init__(
        self,
        resolver: OnesPrincipalResolver,
        http: OnesProviderHttpClient,
        credentials: ExternalIdentityCredentialRepository,
        audit: McpAuditCoordinator,
        credential_refresh: OnesCredentialRefreshService,
        *,
        role_members_operation: ProjectRoleMembersOperation = PROJECT_ROLE_MEMBERS_OPERATION,
        team_users_operation: TeamUsersOperation = TEAM_USERS_OPERATION,
    ) -> None:
        self.resolver = resolver
        self.http = http
        self.credentials = credentials
        self.audit = audit
        self.credential_refresh = credential_refresh
        self.role_members_operation = role_members_operation
        self.team_users_operation = team_users_operation

    def authenticate(self, token: str) -> dict[str, Any]:
        return self.resolver.authenticate(token, required_scope=self.required_scope)

    def invoke(
        self,
        *,
        claims: dict[str, Any],
        arguments: dict[str, Any],
        correlation_id: str,
        invocation_id: str,
    ) -> OnesProjectRoleMembersResult:
        tool_request = self._validate_arguments(arguments)
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
            output = self._execute_with_refresh(
                claims=claims,
                handle=handle,
                principal=principal,
                project_uuid=tool_request["project_uuid"],
            )
            self.audit.complete(
                handle,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response=output,
            )
            return OnesProjectRoleMembersResult(output, handle)
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

    def _execute_with_refresh(
        self,
        *,
        claims: dict[str, Any],
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        project_uuid: str,
    ) -> dict[str, Any]:
        try:
            return self._provider_attempt(handle, principal, project_uuid, attempt=0)
        except OnesProviderUnauthorized:
            pass
        refreshed = self.credential_refresh.resolve_after_unauthorized(
            claims=claims,
            handle=handle,
            principal=principal,
            tool_identifier=self.tool_identifier,
        )
        try:
            output = self._provider_attempt(handle, refreshed, project_uuid, attempt=1)
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
        project_uuid: str,
        *,
        attempt: int,
    ) -> dict[str, Any]:
        roles = self._load_roles(handle, principal, project_uuid, attempt=attempt)
        member_uuids = list(
            dict.fromkeys(
                member_uuid
                for role in roles
                for member_uuid in role["member_uuids"]
            )
        )
        if not member_uuids:
            if attempt == 0:
                self.credentials.mark_used(
                    credential_id=principal.credential.id,
                    expected_revision=principal.credential.revision,
                )
            return {
                "roles": [
                    {
                        "role_uuid": role["role_uuid"],
                        "role_name": role["role_name"],
                        "members": [],
                    }
                    for role in roles
                ],
                "untrusted_data": True,
            }

        users = self._load_users(handle, principal, member_uuids, attempt=attempt)
        output = {
            "roles": [
                {
                    "role_uuid": role["role_uuid"],
                    "role_name": role["role_name"],
                    "members": [
                        {"uuid": member_uuid, "name": users[member_uuid]}
                        for member_uuid in role["member_uuids"]
                    ],
                }
                for role in roles
            ],
            "untrusted_data": True,
        }
        if attempt == 0:
            self.credentials.mark_used(
                credential_id=principal.credential.id,
                expected_revision=principal.credential.revision,
            )
        return output

    def _load_roles(
        self,
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        project_uuid: str,
        *,
        attempt: int,
    ) -> list[dict[str, Any]]:
        started = time.monotonic()
        audit_attempt = attempt * 2
        request_summary = {
            "operation": self.role_members_operation.code,
            "project_uuid": project_uuid,
        }
        try:
            execution = self.role_members_operation.execute(
                self.http,
                team_uuid=principal.team_id,
                project_uuid=project_uuid,
                token=principal.credential.secrets.token,
                user_id=principal.provider_user_id,
            )
            roles = list(execution.output)
            self.audit.append_event(
                handle,
                event_kind="PROVIDER",
                attempt=audit_attempt,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request=request_summary,
                business_response={
                    "operation": self.role_members_operation.code,
                    "role_count": len(roles),
                    "member_reference_count": sum(len(role["member_uuids"]) for role in roles),
                },
                credential_revision=principal.credential.revision,
            )
            return roles
        except AppError as exc:
            self._record_provider_failure(
                handle,
                principal,
                attempt=audit_attempt,
                started=started,
                request_summary=request_summary,
                exc=exc,
            )
            raise

    def _load_users(
        self,
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        member_uuids: list[str],
        *,
        attempt: int,
    ) -> dict[str, str]:
        started = time.monotonic()
        audit_attempt = attempt * 2 + 1
        request_summary = {
            "operation": self.team_users_operation.code,
            "requested_user_count": len(member_uuids),
        }
        try:
            execution = self.team_users_operation.execute(
                self.http,
                team_uuid=principal.team_id,
                member_uuids=member_uuids,
                token=principal.credential.secrets.token,
                user_id=principal.provider_user_id,
            )
            users = dict(execution.output)
            if set(users) != set(member_uuids):
                raise invalid_provider_response("ones_provider_schema_invalid")
            self.audit.append_event(
                handle,
                event_kind="PROVIDER",
                attempt=audit_attempt,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request=request_summary,
                business_response={
                    "operation": self.team_users_operation.code,
                    "returned_user_count": len(users),
                },
                credential_revision=principal.credential.revision,
            )
            return users
        except AppError as exc:
            self._record_provider_failure(
                handle,
                principal,
                attempt=audit_attempt,
                started=started,
                request_summary=request_summary,
                exc=exc,
            )
            raise

    def _record_provider_failure(
        self,
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        *,
        attempt: int,
        started: float,
        request_summary: dict[str, Any],
        exc: AppError,
    ) -> None:
        self.audit.append_event(
            handle,
            event_kind="PROVIDER",
            attempt=attempt,
            status="FAILED",
            error_code=error_code(exc),
            duration_ms=int((time.monotonic() - started) * 1000),
            business_request=request_summary,
            credential_revision=principal.credential.revision,
        )

    @staticmethod
    def _validate_arguments(arguments: dict[str, Any]) -> dict[str, str]:
        if not isinstance(arguments, dict) or set(arguments) != {"project_uuid"}:
            raise OnesMcpError(
                "ONES Tool input fields are invalid",
                safe_message="ONES 项目参数无效",
                error_code="ones_tool_input_invalid",
            )
        project_uuid = arguments.get("project_uuid")
        if (
            not isinstance(project_uuid, str)
            or not 1 <= len(project_uuid) <= PROJECT_ROLE_MEMBER_LIMITS["project_uuid"]
            or _PROJECT_UUID.fullmatch(project_uuid) is None
        ):
            raise OnesMcpError(
                "ONES Tool project UUID is invalid",
                safe_message="ONES 项目参数无效",
                error_code="ones_tool_input_invalid",
            )
        return {"project_uuid": project_uuid}
