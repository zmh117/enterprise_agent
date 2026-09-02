from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.modules.identity.application.principal_jwt import PrincipalTokenVerifier
from app.modules.identity.infrastructure.external_identity_credentials import (
    ExternalIdentityCredentialRepository,
    ResolvedExternalCredential,
)
from app.modules.mcp_audit import McpAuditContext
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.database import Database
from services.ones_mcp_server.contracts import REQUIRED_SCOPE, SERVER_CODE, TOOL_IDENTIFIER
from services.ones_mcp_server.errors import OnesMcpError


class PrincipalBusinessAuthorizationPort(Protocol):
    def require(
        self,
        *,
        user_id: str,
        application_id: str,
        tool_identifier: str,
        stage: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ResolvedOnesPrincipal:
    job_id: str
    session_id: str
    actor_user_id: str
    business_application_id: str
    agent_publication_id: str
    application_publication_id: str
    principal_jti: str
    external_identity_id: str
    provider_user_id: str
    provider_email: str
    team_id: str
    credential: ResolvedExternalCredential


@dataclass(frozen=True, slots=True)
class ResolvedOnesConfirmationRoute:
    source_connector_id: str
    dingtalk_enterprise_id: str
    target_external_subject_id: str
    target_union_id: str
    conversation_type: str


class OnesPrincipalResolver:
    """Resolves a Principal JWT into current platform and ONES identity facts.

    Tool parameters are explicit extension points. Defaults preserve the accepted
    phase-one single-tool contract without making later tools depend on this file's
    constants.
    """

    def __init__(
        self,
        database: Database,
        verifier: PrincipalTokenVerifier,
        snapshot_service: JobMcpToolSnapshotService,
        business_authorization_service: PrincipalBusinessAuthorizationPort,
        credential_repository: ExternalIdentityCredentialRepository,
    ) -> None:
        self.database = database
        self.verifier = verifier
        self.snapshot_service = snapshot_service
        self.business_authorization_service = business_authorization_service
        self.credential_repository = credential_repository

    def authenticate(
        self,
        token: str,
        *,
        required_scope: str = REQUIRED_SCOPE,
    ) -> dict[str, Any]:
        return self.verifier.verify_for_running_job(
            token,
            self.database,
            self.snapshot_service,
            required_scope=required_scope,
        )

    def audit_context(
        self,
        claims: dict[str, Any],
        *,
        invocation_id: str,
        correlation_id: str,
        tool_identifier: str = TOOL_IDENTIFIER,
    ) -> McpAuditContext:
        job = self.database.execute_one(
            """
            select id, session_id, retry_count, internal_user_id,
                   agent_publication_id, business_application_publication_id
              from agent_job
             where id = ? and status = 'RUNNING'
            """,
            (claims["job_id"],),
        )
        if job is None or str(job["internal_user_id"]) != str(claims["sub"]):
            raise self._denied("ones_principal_provenance_mismatch")
        expected_invocation_id = f"{job['id']}.attempt-{int(job['retry_count'])}"
        effective_invocation_id = invocation_id or expected_invocation_id
        if (
            effective_invocation_id != expected_invocation_id
            or str(job["session_id"]) != str(claims["session_id"])
            or str(job["agent_publication_id"]) != str(claims["agent_publication_id"])
            or str(job["business_application_publication_id"])
            != str(claims["application_publication_id"])
        ):
            raise self._denied("ones_principal_provenance_mismatch")
        definition = MCP_TOOL_MANIFEST.get(tool_identifier)
        if definition is None or definition.server_code != SERVER_CODE:
            raise self._denied("ones_principal_snapshot_denied")
        return McpAuditContext(
            correlation_id=(correlation_id.strip() or f"job:{job['id']}")[:128],
            job_id=str(job["id"]),
            session_id=str(job["session_id"]),
            invocation_id=effective_invocation_id,
            actor_user_id=str(claims["sub"]),
            server_code=SERVER_CODE,
            tool_identifier=tool_identifier,
            tool_schema_hash=definition.schema_hash,
            agent_publication_id=str(job["agent_publication_id"]),
            application_publication_id=str(job["business_application_publication_id"]),
            provider="ones",
        )

    def resolve(
        self,
        claims: dict[str, Any],
        *,
        tool_identifier: str = TOOL_IDENTIFIER,
    ) -> ResolvedOnesPrincipal:
        job = self.database.execute_one(
            """
            select j.id, j.session_id, j.project_code, j.internal_user_id,
                   j.business_application_id,
                   j.agent_publication_id,
                   j.business_application_publication_id,
                   s.application_publication_id,
                   u.status as user_status,
                   u.account_type as user_account_type
              from agent_job j
              join agent_session s on s.id = j.session_id
              join app_user u on u.id = j.internal_user_id
             where j.id = ? and j.status = 'RUNNING'
            """,
            (claims["job_id"],),
        )
        if (
            job is None
            or str(job["internal_user_id"]) != claims["sub"]
            or str(job["session_id"]) != claims["session_id"]
            or str(job["agent_publication_id"]) != claims["agent_publication_id"]
            or str(job["business_application_publication_id"])
            != claims["application_publication_id"]
            or str(job["application_publication_id"]) != claims["application_publication_id"]
        ):
            raise self._denied("ones_principal_provenance_mismatch")
        if str(job["user_status"]) != "enabled" or str(job["user_account_type"]) != "human":
            raise self._denied("ones_principal_user_inactive")
        verified = self.snapshot_service.verify(str(job["id"]))
        snapshot = verified["snapshot"]
        matches = [
            item
            for item in snapshot.get("tools") or []
            if isinstance(item, dict)
            and item.get("server_code") == SERVER_CODE
            and item.get("tool_identifier") == tool_identifier
        ]
        if (
            len(matches) != 1
            or str(verified.get("authorization_hash") or "") != claims["authorization_hash"]
        ):
            raise self._denied("ones_principal_snapshot_denied")
        self.business_authorization_service.require(
            user_id=claims["sub"],
            application_id=str(job["business_application_id"]),
            tool_identifier=tool_identifier,
            stage="ones_principal_resolve",
        )
        identities = self.database.execute(
            """
            select * from user_external_identity
             where user_id = ? and provider = 'ones' and status = 'enabled'
             order by id
            """,
            (claims["sub"],),
        )
        if len(identities) != 1:
            raise self._denied(
                "ones_identity_missing" if not identities else "ones_identity_ambiguous"
            )
        identity = identities[0]
        try:
            metadata = json.loads(str(identity.get("metadata_json") or "{}"))
        except json.JSONDecodeError:
            raise self._denied("ones_identity_invalid") from None
        team_ids = metadata.get("team_uuids") if isinstance(metadata, dict) else None
        default_team_id = (
            str(metadata.get("default_team_id") or "").strip() if isinstance(metadata, dict) else ""
        )
        if (
            not isinstance(team_ids, list)
            or not default_team_id
            or team_ids.count(default_team_id) != 1
        ):
            raise self._denied("ones_default_team_invalid")
        credential_row = self.credential_repository.get_by_identity(str(identity["id"]))
        if credential_row is None or str(credential_row.get("status")) != "ACTIVE":
            raise self._denied("ones_credential_reverification_required")
        credential = self.credential_repository.resolve_active(str(credential_row["id"]))
        if credential.provider != "ones":
            raise self._denied("ones_credential_provider_mismatch")
        return ResolvedOnesPrincipal(
            job_id=str(job["id"]),
            session_id=str(job["session_id"]),
            actor_user_id=claims["sub"],
            business_application_id=str(job["business_application_id"]),
            agent_publication_id=str(job["agent_publication_id"]),
            application_publication_id=str(job["business_application_publication_id"]),
            principal_jti=claims["jti"],
            external_identity_id=str(identity["id"]),
            provider_user_id=str(identity["external_subject_id"]),
            provider_email=credential.secrets.email,
            team_id=default_team_id,
            credential=credential,
        )

    def resolve_confirmation_route(
        self,
        principal: ResolvedOnesPrincipal,
    ) -> ResolvedOnesConfirmationRoute:
        route = self.database.execute_one(
            """
            select j.source_connector_id, j.source_channel,
                   s.source_connector_id as session_source_connector_id,
                   s.conversation_type, s.external_conversation_id,
                   c.connector_type, c.enabled, c.allow_ingress,
                   c.dingtalk_enterprise_id, e.status as enterprise_status
              from agent_job j
              join agent_session s on s.id = j.session_id
              join integration_connector c on c.id = j.source_connector_id
              join dingtalk_enterprise e on e.id = c.dingtalk_enterprise_id
             where j.id = ? and j.session_id = ?
            """,
            (principal.job_id, principal.session_id),
        )
        if (
            route is None
            or str(route.get("source_channel") or "") not in {"dingtalk", "dingding"}
            or str(route.get("session_source_connector_id") or "")
            != str(route.get("source_connector_id") or "")
            or str(route.get("connector_type") or "") != "dingtalk_enterprise_stream"
            or not bool(route.get("enabled"))
            or not bool(route.get("allow_ingress"))
            or str(route.get("enterprise_status") or "") != "ACTIVE"
            or str(route.get("conversation_type") or "") not in {"direct", "group"}
            or not str(route.get("external_conversation_id") or "")
        ):
            raise self._denied("ones_mutation_dingtalk_source_required")
        identities = self.database.execute(
            """
            select external_subject_id, union_id
              from user_external_identity
             where user_id = ? and provider = 'dingtalk' and status = 'enabled'
               and dingtalk_enterprise_id = ?
             order by id
            """,
            (principal.actor_user_id, route["dingtalk_enterprise_id"]),
        )
        if len(identities) != 1 or not str(identities[0].get("external_subject_id") or ""):
            raise self._denied("ones_mutation_dingtalk_identity_required")
        identity = identities[0]
        external_subject_id = str(identity["external_subject_id"])
        return ResolvedOnesConfirmationRoute(
            source_connector_id=str(route["source_connector_id"]),
            dingtalk_enterprise_id=str(route["dingtalk_enterprise_id"]),
            target_external_subject_id=external_subject_id,
            target_union_id=str(identity.get("union_id") or external_subject_id),
            conversation_type=str(route["conversation_type"]),
        )

    @staticmethod
    def _denied(error_code: str) -> OnesMcpError:
        safe_messages = {
            "ones_mutation_dingtalk_source_required": (
                "ONES 缺陷更新仅支持从钉钉私聊或群聊会话发起"
            ),
            "ones_mutation_dingtalk_identity_required": (
                "当前用户缺少可接收确认卡片的钉钉身份"
            ),
        }
        return OnesMcpError(
            "ONES Principal could not be resolved from current platform facts",
            safe_message=safe_messages.get(
                error_code,
                "当前用户的 ONES 身份或权限不可用，请重新验证",
            ),
            error_code=error_code,
        )
