from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.modules.identity.application.principal_jwt import PrincipalTokenVerifier
from app.modules.mcp_audit import McpAuditContext
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.database import Database
from services.dingtalk_mcp_server.contracts import (
    OPERATION_CODE,
    REQUIRED_SCOPE,
    SERVER_CODE,
    TOOL_IDENTIFIER,
)
from services.dingtalk_mcp_server.errors import DingTalkMcpError


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
class ResolvedDingTalkPrincipal:
    job_id: str
    session_id: str
    actor_user_id: str
    business_application_id: str
    agent_publication_id: str
    application_publication_id: str
    source_connector_id: str
    dingtalk_enterprise_id: str
    external_identity_id: str
    target_external_subject_id: str
    target_union_id: str
    principal_jti: str


class DingTalkPrincipalResolver:
    def __init__(
        self,
        database: Database,
        verifier: PrincipalTokenVerifier,
        snapshot_service: JobMcpToolSnapshotService,
        business_authorization_service: PrincipalBusinessAuthorizationPort,
    ) -> None:
        self.database = database
        self.verifier = verifier
        self.snapshot_service = snapshot_service
        self.business_authorization_service = business_authorization_service

    def authenticate(self, token: str) -> dict[str, Any]:
        return self.verifier.verify_for_running_job(
            token,
            self.database,
            self.snapshot_service,
            required_scope=REQUIRED_SCOPE,
        )

    def resolve(self, claims: dict[str, Any]) -> ResolvedDingTalkPrincipal:
        job = self.database.execute_one(
            """
            select j.id, j.session_id, j.internal_user_id, j.business_application_id,
                   j.agent_publication_id, j.business_application_publication_id,
                   j.source_connector_id, s.application_publication_id,
                   u.status as user_status, u.account_type as user_account_type
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
            or str(job["application_publication_id"])
            != claims["application_publication_id"]
        ):
            raise self._denied("dingtalk_principal_provenance_mismatch")
        if str(job["user_status"]) != "enabled" or str(job["user_account_type"]) != "human":
            raise self._denied("dingtalk_principal_user_inactive")

        definition = MCP_TOOL_MANIFEST[TOOL_IDENTIFIER]
        verified = self.snapshot_service.verify(str(job["id"]))
        matches = [
            item
            for item in verified["snapshot"].get("tools") or []
            if isinstance(item, dict)
            and item.get("server_code") == SERVER_CODE
            and item.get("tool_identifier") == TOOL_IDENTIFIER
            and item.get("effect") == "mutation"
            and item.get("confirmation_policy") == definition.confirmation_policy
        ]
        if len(matches) != 1 or str(verified["authorization_hash"]) != claims["authorization_hash"]:
            raise self._denied("dingtalk_principal_snapshot_denied")
        self.business_authorization_service.require(
            user_id=claims["sub"],
            application_id=str(job["business_application_id"]),
            tool_identifier=TOOL_IDENTIFIER,
            stage="dingtalk_principal_resolve",
        )

        connector = self.database.execute_one(
            """
            select c.*, e.status as enterprise_status, e.corp_id
              from integration_connector c
              join dingtalk_enterprise e on e.id = c.dingtalk_enterprise_id
             where c.id = ?
            """,
            (job["source_connector_id"],),
        )
        if (
            connector is None
            or str(connector["connector_type"]) != "dingtalk_enterprise_stream"
            or not bool(connector["enabled"])
            or not bool(connector["allow_ingress"])
            or str(connector["enterprise_status"]) != "ACTIVE"
            or not str(connector.get("corp_id") or "")
        ):
            raise self._denied("dingtalk_connector_unavailable")
        identities = self.database.execute(
            """
            select * from user_external_identity
             where user_id = ? and provider = 'dingtalk' and status = 'enabled'
               and dingtalk_enterprise_id = ?
             order by id
            """,
            (claims["sub"], connector["dingtalk_enterprise_id"]),
        )
        if len(identities) != 1:
            raise self._denied(
                "dingtalk_identity_missing" if not identities else "dingtalk_identity_ambiguous"
            )
        identity = identities[0]
        if not str(identity.get("external_subject_id") or "") or not str(
            identity.get("union_id") or ""
        ):
            raise self._denied("dingtalk_identity_incomplete")
        return ResolvedDingTalkPrincipal(
            job_id=str(job["id"]),
            session_id=str(job["session_id"]),
            actor_user_id=claims["sub"],
            business_application_id=str(job["business_application_id"]),
            agent_publication_id=str(job["agent_publication_id"]),
            application_publication_id=str(job["business_application_publication_id"]),
            source_connector_id=str(connector["id"]),
            dingtalk_enterprise_id=str(connector["dingtalk_enterprise_id"]),
            external_identity_id=str(identity["id"]),
            target_external_subject_id=str(identity["external_subject_id"]),
            target_union_id=str(identity["union_id"]),
            principal_jti=str(claims["jti"]),
        )

    def audit_context(
        self,
        claims: dict[str, Any],
        *,
        invocation_id: str,
        correlation_id: str,
    ) -> McpAuditContext:
        principal = self.resolve(claims)
        expected_invocation = self.database.execute_one(
            "select retry_count from agent_job where id = ? and status = 'RUNNING'",
            (principal.job_id,),
        )
        expected = f"{principal.job_id}.attempt-{int((expected_invocation or {}).get('retry_count') or 0)}"
        if not invocation_id or invocation_id != expected:
            raise self._denied("dingtalk_principal_provenance_mismatch")
        definition = MCP_TOOL_MANIFEST[TOOL_IDENTIFIER]
        return McpAuditContext(
            correlation_id=(correlation_id.strip() or f"job:{principal.job_id}")[:128],
            job_id=principal.job_id,
            session_id=principal.session_id,
            invocation_id=invocation_id,
            actor_user_id=principal.actor_user_id,
            server_code=SERVER_CODE,
            tool_identifier=TOOL_IDENTIFIER,
            tool_schema_hash=definition.schema_hash,
            agent_publication_id=principal.agent_publication_id,
            application_publication_id=principal.application_publication_id,
            operation=OPERATION_CODE,
            risk_level="medium",
            principal_jti=principal.principal_jti,
            external_identity_id=principal.external_identity_id,
            provider="dingtalk",
            provider_user_id=principal.target_union_id,
        )

    @staticmethod
    def _denied(error_code: str) -> DingTalkMcpError:
        return DingTalkMcpError(
            "DingTalk Principal could not be resolved from current platform facts",
            safe_message="当前用户的钉钉身份、应用来源或权限不可用",
            error_code=error_code,
        )
