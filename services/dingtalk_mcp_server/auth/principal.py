from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.modules.identity.application.principal_jwt import PrincipalTokenVerifier
from app.modules.mcp_audit import McpAuditContext
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.dingtalk_tool_contracts import DingTalkToolContract
from app.shared.database import Database
from services.dingtalk_mcp_server.contracts import SERVER_CODE
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
    primary_calendar_id: str
    aitable_operator_id: str
    source_conversation_type: str
    source_conversation_id: str
    source_open_conversation_id: str
    source_robot_code: str
    enterprise_robot_code: str
    work_notification_agent_id: int | None
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

    def authenticate(self, token: str, contract: DingTalkToolContract) -> dict[str, Any]:
        return self.verifier.verify_for_running_job(
            token,
            self.database,
            self.snapshot_service,
            required_scope=contract.required_scope,
        )

    def resolve(
        self,
        claims: dict[str, Any],
        contract: DingTalkToolContract,
    ) -> ResolvedDingTalkPrincipal:
        job = self.database.execute_one(
            """
            select j.id, j.session_id, j.internal_user_id, j.business_application_id,
                   j.agent_publication_id, j.business_application_publication_id,
                   j.source_connector_id, s.application_publication_id,
                   s.source_connector_id as session_source_connector_id,
                   s.external_conversation_id, s.conversation_type,
                   s.bot_identity, s.reply_route_json,
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
            or str(job["application_publication_id"]) != claims["application_publication_id"]
            or str(job["session_source_connector_id"]) != str(job["source_connector_id"])
        ):
            raise self._denied("dingtalk_principal_provenance_mismatch")
        if str(job["user_status"]) != "enabled" or str(job["user_account_type"]) != "human":
            raise self._denied("dingtalk_principal_user_inactive")

        definition = MCP_TOOL_MANIFEST.get(contract.identifier)
        if (
            definition is None
            or definition.server_code != SERVER_CODE
            or definition.effect != contract.effect
            or definition.confirmation_policy != contract.confirmation_policy
            or definition.operation_code != contract.operation_code
            or definition.risk_level != contract.risk_level
            or definition.target_policy != contract.target_policy
        ):
            raise self._denied("dingtalk_tool_contract_drift")
        verified = self.snapshot_service.verify(str(job["id"]))
        matches = [
            item
            for item in verified["snapshot"].get("tools") or []
            if isinstance(item, dict)
            and item.get("server_code") == SERVER_CODE
            and item.get("tool_identifier") == contract.identifier
            and item.get("effect") == contract.effect
            and item.get("confirmation_policy") == definition.confirmation_policy
        ]
        if len(matches) != 1 or str(verified["authorization_hash"]) != claims["authorization_hash"]:
            raise self._denied("dingtalk_principal_snapshot_denied")
        self.business_authorization_service.require(
            user_id=claims["sub"],
            application_id=str(job["business_application_id"]),
            tool_identifier=contract.identifier,
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
        target_external_subject_id = str(identity.get("external_subject_id") or "")
        target_union_id = str(identity.get("union_id") or "")
        if not target_external_subject_id or (
            contract.requires_target_union_id and not target_union_id
        ):
            raise self._denied("dingtalk_identity_incomplete")
        connector_metadata = self._json_object(connector.get("metadata"))
        reply_route = self._json_object(job.get("reply_route_json"))
        route_target = self._json_object(reply_route.get("target"))
        route_connector_id = str(reply_route.get("connector_id") or "")
        if route_connector_id and route_connector_id != str(connector["id"]):
            raise self._denied("dingtalk_source_route_mismatch")
        conversation_type = str(job.get("conversation_type") or "")
        if conversation_type not in {"direct", "group"}:
            raise self._denied("dingtalk_source_route_invalid")
        source_conversation_id = str(job.get("external_conversation_id") or "")
        if not source_conversation_id:
            raise self._denied("dingtalk_source_route_invalid")
        source_open_conversation_id = (
            str(route_target.get("open_conversation_id") or "")
            if conversation_type == "group"
            else ""
        )
        source_robot_code = str(
            route_target.get("robot_code")
            or job.get("bot_identity")
            or connector_metadata.get("default_robot_code")
            or ""
        )
        enterprise_robot_code = str(connector_metadata.get("default_robot_code") or "")
        work_notification_agent_id = self._positive_int(
            connector_metadata.get("work_notification_agent_id")
        )
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
            target_external_subject_id=target_external_subject_id,
            target_union_id=target_union_id,
            primary_calendar_id="primary",
            aitable_operator_id=target_union_id,
            source_conversation_type=conversation_type,
            source_conversation_id=source_conversation_id,
            source_open_conversation_id=source_open_conversation_id,
            source_robot_code=source_robot_code,
            enterprise_robot_code=enterprise_robot_code,
            work_notification_agent_id=work_notification_agent_id,
            principal_jti=str(claims["jti"]),
        )

    def audit_context(
        self,
        claims: dict[str, Any],
        contract: DingTalkToolContract,
        *,
        invocation_id: str,
        correlation_id: str,
    ) -> McpAuditContext:
        principal = self.resolve(claims, contract)
        expected_invocation = self.database.execute_one(
            "select retry_count from agent_job where id = ? and status = 'RUNNING'",
            (principal.job_id,),
        )
        expected = (
            f"{principal.job_id}.attempt-{int((expected_invocation or {}).get('retry_count') or 0)}"
        )
        if not invocation_id or invocation_id != expected:
            raise self._denied("dingtalk_principal_provenance_mismatch")
        definition = MCP_TOOL_MANIFEST[contract.identifier]
        return McpAuditContext(
            correlation_id=(correlation_id.strip() or f"job:{principal.job_id}")[:128],
            job_id=principal.job_id,
            session_id=principal.session_id,
            invocation_id=invocation_id,
            actor_user_id=principal.actor_user_id,
            server_code=SERVER_CODE,
            tool_identifier=contract.identifier,
            tool_schema_hash=definition.schema_hash,
            agent_publication_id=principal.agent_publication_id,
            application_publication_id=principal.application_publication_id,
            operation=contract.operation_code,
            risk_level=contract.risk_level,
            principal_jti=principal.principal_jti,
            external_identity_id=principal.external_identity_id,
            provider="dingtalk",
            provider_user_id=(
                principal.target_union_id or principal.target_external_subject_id
            ),
        )

    @staticmethod
    def _denied(error_code: str) -> DingTalkMcpError:
        return DingTalkMcpError(
            "DingTalk Principal could not be resolved from current platform facts",
            safe_message="当前用户的钉钉身份、应用来源或权限不可用",
            error_code=error_code,
        )

    @staticmethod
    def _json_object(value: object) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _positive_int(value: object) -> int | None:
        try:
            parsed = int(str(value or ""))
        except ValueError:
            return None
        return parsed if parsed > 0 else None
