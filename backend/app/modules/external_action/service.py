from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.external_action.domain import ExternalActionIntentFacts
from app.modules.external_action.repository import ExternalActionRepository
from app.modules.mcp_audit import McpAuditCoordinator
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import NonRetryableExecutionError


@dataclass(frozen=True, slots=True)
class ActionCallbackResult:
    acknowledged: bool
    duplicate: bool
    status: str
    response: dict[str, Any]


class ExternalActionTokenSigner:
    def __init__(self, key: str) -> None:
        if len(key.encode("utf-8")) < 32:
            raise ValueError("External Action token key must be at least 32 bytes")
        self._key = key.encode("utf-8")

    def issue(self, intent_id: str, revision: int) -> str:
        message = f"{intent_id}:{revision}".encode("utf-8")
        digest = hmac.new(self._key, message, hashlib.sha256).hexdigest()
        return f"v1.{revision}.{digest}"

    def verify(self, token: str, *, intent_id: str, revision: int) -> bool:
        return hmac.compare_digest(token, self.issue(intent_id, revision))


def external_action_signing_key(master_key: str) -> str:
    if not master_key:
        raise ValueError("External Action requires the platform master key")
    return hashlib.sha256(f"enterprise-agent:external-action:v1:{master_key}".encode()).hexdigest()


class ExternalActionService:
    def __init__(
        self,
        repository: ExternalActionRepository,
        token_signer: ExternalActionTokenSigner,
        audit_service: AuditService,
    ) -> None:
        self.repository = repository
        self.token_signer = token_signer
        self.audit_service = audit_service

    @operation_unit_of_work(lambda service: service.repository.database)
    def prepare(
        self,
        *,
        facts: dict[str, str] | ExternalActionIntentFacts,
        arguments: dict[str, Any],
        arguments_hash: str,
        safe_summary: dict[str, Any],
        mcp_call_id: str,
        ttl_seconds: int = 900,
    ) -> tuple[dict[str, Any], bool]:
        repository_facts: dict[str, Any]
        if isinstance(facts, ExternalActionIntentFacts):
            repository_facts = facts.as_repository_facts(arguments_hash=arguments_hash)
        else:
            repository_facts = {
                **facts,
                "confirmation_channel_code": facts.get("confirmation_channel_code", "dingtalk"),
                "execution_provider_code": facts.get("execution_provider_code", "dingtalk"),
                "execution_external_identity_id": facts.get("execution_external_identity_id", ""),
                "execution_scope_id": facts.get("execution_scope_id", ""),
                "target_resource_type": facts.get("target_resource_type", ""),
                "target_resource_id": facts.get("target_resource_id", ""),
                "precondition": {},
                "precondition_hash": facts.get("precondition_hash", ""),
                "field_catalog_version": facts.get("field_catalog_version", ""),
                "field_catalog_hash": facts.get("field_catalog_hash", ""),
                "intent_fingerprint": facts.get("intent_fingerprint", ""),
            }
        McpAuditCoordinator.reject_auth_material(arguments)
        McpAuditCoordinator.reject_auth_material(safe_summary)
        McpAuditCoordinator.reject_auth_material(repository_facts)
        expires_at = (datetime.now(UTC) + timedelta(seconds=max(60, ttl_seconds))).isoformat()
        intent, created = self.repository.create_or_get(
            facts=repository_facts,
            arguments=arguments,
            arguments_hash=arguments_hash,
            safe_summary=safe_summary,
            expires_at=expires_at,
            mcp_call_id=mcp_call_id,
        )
        self.audit_service.record(
            "external_action.prepared" if created else "external_action.reused",
            status=str(intent["status"]),
            summary="External mutation is waiting for user confirmation",
            job_id=str(intent["job_id"]),
            actor_id=str(intent["actor_user_id"]),
            payload={
                "action_intent_id": str(intent["id"]),
                "tool_identifier": str(intent["tool_identifier"]),
                "revision": int(intent["revision"]),
            },
        )
        return intent, created

    @operation_unit_of_work(lambda service: service.repository.database)
    def handle_callback(
        self,
        *,
        connector_id: str,
        corp_id: str,
        out_track_id: str,
        user_id: str,
        action: str,
        revision: int,
        intent_token: str,
    ) -> ActionCallbackResult:
        intent = self.repository.get(out_track_id)
        if intent is None:
            raise self._denied("external_action_not_found", "确认操作不存在或已失效")
        if (
            str(intent["source_connector_id"]) != connector_id
            or str(intent["target_external_subject_id"]) != user_id
        ):
            raise self._denied("external_action_actor_mismatch", "当前用户不能确认此操作")
        enterprise = self.repository.database.execute_one(
            "select corp_id from dingtalk_enterprise where id = ?",
            (intent["dingtalk_enterprise_id"],),
        )
        if enterprise is None or str(enterprise.get("corp_id") or "") != corp_id:
            raise self._denied("external_action_enterprise_mismatch", "确认操作的企业不匹配")
        expected_revision = int(intent["revision"])
        if revision != expected_revision or not self.token_signer.verify(
            intent_token,
            intent_id=out_track_id,
            revision=revision,
        ):
            raise self._denied("external_action_revision_mismatch", "确认卡片版本已失效")
        if (
            str(intent["status"]) == "PENDING_CONFIRMATION"
            and str(intent["expires_at"]) <= datetime.now(UTC).isoformat()
        ):
            timestamp = datetime.now(UTC).isoformat()
            self.repository.database.execute(
                """
                update external_action_intent
                   set status = 'EXPIRED', updated_at = ?, completed_at = ?
                 where id = ? and status = 'PENDING_CONFIRMATION'
                """,
                (timestamp, timestamp, out_track_id),
            )
            self.audit_service.record(
                "external_action.expired",
                status="EXPIRED",
                summary="External action confirmation expired without execution",
                job_id=str(intent["job_id"]),
                actor_id=str(intent["actor_user_id"]),
                payload={"action_intent_id": out_track_id, "revision": revision},
            )
            return ActionCallbackResult(
                acknowledged=True,
                duplicate=False,
                status="EXPIRED",
                response={
                    "cardUpdateOptions": {
                        "updateCardDataByKey": True,
                        "updatePrivateDataByKey": True,
                    },
                    "cardData": {
                        "cardParamMap": {
                            "status": "expired",
                            "statusText": "确认已过期，不会执行",
                        }
                    },
                    "userPrivateData": {
                        "cardParamMap": {
                            "inputStatus": "disabled",
                            "errorText": "确认已过期，请重新发起操作",
                        }
                    },
                },
            )
        if action == "revise":
            self.audit_service.record(
                "external_action.revise_unsupported",
                status=str(intent["status"]),
                summary="External action revision was not executed in MVP",
                job_id=str(intent["job_id"]),
                actor_id=str(intent["actor_user_id"]),
                payload={"action_intent_id": out_track_id, "revision": revision},
            )
            return ActionCallbackResult(
                acknowledged=True,
                duplicate=False,
                status=str(intent["status"]),
                response={
                    "cardUpdateOptions": {
                        "updateCardDataByKey": False,
                        "updatePrivateDataByKey": True,
                    },
                    "userPrivateData": {
                        "cardParamMap": {
                            "inputStatus": "enabled",
                            "errorText": "MVP 暂不支持补充并重新生成，原操作尚未执行",
                        }
                    },
                },
            )
        if action not in {"agree", "reject"}:
            raise self._denied("external_action_unknown_action", "确认动作无效")
        updated, changed = self.repository.transition_from_callback(
            intent_id=out_track_id,
            expected_revision=revision,
            action=action,
        )
        if not updated:
            raise self._denied("external_action_not_found", "确认操作不存在或已失效")
        compatible_duplicate = (
            action == "agree"
            and str(updated["status"])
            in {"APPROVED", "EXECUTING", "SUCCEEDED", "FAILED", "FAILED_UNCERTAIN"}
        ) or (action == "reject" and str(updated["status"]) == "REJECTED")
        if not changed and not compatible_duplicate:
            raise self._denied(
                "external_action_state_conflict",
                "确认操作已由其他动作处理，不能再次变更",
            )
        accepted_status = "agree" if action == "agree" else "reject"
        status_text = "已确认，等待执行" if action == "agree" else "已取消，不会执行"
        self.audit_service.record(
            "external_action.approved" if action == "agree" else "external_action.rejected",
            status=str(updated["status"]),
            summary="External action card callback was durably accepted",
            job_id=str(updated["job_id"]),
            actor_id=str(updated["actor_user_id"]),
            payload={
                "action_intent_id": out_track_id,
                "revision": revision,
                "duplicate": not changed,
            },
        )
        return ActionCallbackResult(
            acknowledged=True,
            duplicate=not changed,
            status=str(updated["status"]),
            response={
                "cardUpdateOptions": {
                    "updateCardDataByKey": True,
                    "updatePrivateDataByKey": True,
                },
                "cardData": {
                    "cardParamMap": {"status": accepted_status, "statusText": status_text}
                },
                "userPrivateData": {"cardParamMap": {"inputStatus": "disabled", "errorText": ""}},
            },
        )

    @staticmethod
    def _denied(code: str, message: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(message, safe_message=message, error_code=code)
