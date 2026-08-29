from __future__ import annotations

import logging
import os
import socket
import time
from pathlib import Path
from typing import Any

from app.bootstrap import Container, build_worker_container
from app.modules.dingding.infrastructure.dingtalk_delivery_clients import DingTalkAccessTokenClient
from app.modules.external_action.repository import ExternalActionRepository
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.config import load_settings
from app.shared.exceptions import RetryableExecutionError
from app.shared.logging import configure_logging
from services.dingtalk_mcp_server.contracts import SERVER_CODE, TOOL_IDENTIFIER
from services.dingtalk_mcp_server.provider import DingTalkCardClient, DingTalkTodoClient


logger = logging.getLogger(__name__)
HEARTBEAT_PATH = Path("/tmp/external-action-worker.heartbeat")


class ExternalActionWorker:
    def __init__(self, runtime: Container, *, worker_id: str) -> None:
        self.runtime = runtime
        self.repository = ExternalActionRepository(runtime.database)
        self.worker_id = worker_id[:128]

    def run_once(self) -> bool:
        card = self.repository.claim_card(worker_id=self.worker_id)
        if card is not None:
            self._dispatch_card(card)
            return True
        recovered = self.repository.recover_stale_execution()
        if recovered is not None:
            self.runtime.audit_service.record(
                "external_action.interrupted",
                status="FAILED_UNCERTAIN",
                summary="Interrupted external action requires manual reconciliation",
                job_id=str(recovered["job_id"]),
                actor_id=str(recovered["actor_user_id"]),
                payload={"action_intent_id": str(recovered["id"])},
            )
            return True
        intent = self.repository.claim_approved(worker_id=self.worker_id)
        if intent is not None:
            self._execute(intent)
            return True
        return False

    def _dispatch_card(self, outbox: dict[str, Any]) -> None:
        try:
            intent = self.repository.get(str(outbox["action_intent_id"]))
            if intent is None:
                raise ValueError("External action Intent is missing")
            client_id, client_secret = self._connector_credentials(intent)
            token_client = DingTalkAccessTokenClient(
                client_id=client_id, client_secret=client_secret, timeout_seconds=5
            )
            client = DingTalkCardClient(token_client)
            if str(outbox["event_kind"]) == "CREATE":
                summary = self.repository.decode_json(intent["safe_summary_json"])
                token = self._intent_token(str(intent["id"]), int(intent["revision"]))
                client.create_confirmation(
                    out_track_id=str(intent["id"]),
                    staff_id=str(intent["target_external_subject_id"]),
                    card_fields={
                        "providerName": "钉钉",
                        "operationName": "创建待办",
                        "targetName": "当前用户本人",
                        "detailText": self._detail_text(summary),
                        # The published template renders its request buttons only while
                        # status is empty. Non-empty values represent terminal/progress
                        # states and intentionally replace the buttons with status text.
                        "status": "",
                        "statusText": "等待你确认后执行",
                    },
                    private_fields={
                        "revisionNo": str(intent["revision"]),
                        "intentToken": token,
                        "supplement": "",
                        "inputStatus": "normal",
                        "errorText": "",
                    },
                )
            else:
                payload = self.repository.decode_json(outbox["payload_json"])
                client.update(
                    out_track_id=str(intent["id"]),
                    card_fields={
                        "status": str(payload.get("status") or "failed"),
                        "statusText": str(payload.get("statusText") or "操作状态已更新")[:200],
                        "inputStatus": "disabled",
                        "errorText": "",
                    },
                )
            self.repository.complete_card(str(outbox["id"]))
        except Exception as exc:
            self.repository.fail_card(
                str(outbox["id"]),
                error_code=str(getattr(exc, "error_code", "") or "card_delivery_failed"),
                error_summary=str(getattr(exc, "safe_message", "") or "卡片投放失败"),
            )

    def _execute(self, intent: dict[str, Any]) -> None:
        try:
            self._reauthorize(intent)
            client_id, client_secret = self._connector_credentials(intent)
            arguments = self.repository.decode_json(intent["arguments_json"])
            result = DingTalkTodoClient(
                DingTalkAccessTokenClient(
                    client_id=client_id, client_secret=client_secret, timeout_seconds=5
                )
            ).create_for_self(union_id=str(intent["target_union_id"]), arguments=arguments)
            self.repository.complete_execution(
                str(intent["id"]),
                result=result,
                provider_request_id=str(result.get("task_id") or ""),
            )
            self.runtime.audit_service.record(
                "external_action.executed",
                status="SUCCEEDED",
                summary="Confirmed external action executed",
                job_id=str(intent["job_id"]),
                actor_id=str(intent["actor_user_id"]),
                payload={"action_intent_id": str(intent["id"]), "operation_code": str(intent["operation_code"])},
            )
        except Exception as exc:
            uncertain = isinstance(exc, RetryableExecutionError)
            self.repository.fail_execution(
                str(intent["id"]),
                error_code=str(getattr(exc, "error_code", "") or "external_action_execution_failed"),
                error_summary=str(getattr(exc, "safe_message", "") or "外部操作执行失败"),
                uncertain=uncertain,
            )
            self.runtime.audit_service.record(
                "external_action.failed",
                status="FAILED_UNCERTAIN" if uncertain else "FAILED",
                summary="Confirmed external action failed safely",
                job_id=str(intent["job_id"]),
                actor_id=str(intent["actor_user_id"]),
                payload={
                    "action_intent_id": str(intent["id"]),
                    "error_code": str(getattr(exc, "error_code", "") or "external_action_execution_failed"),
                },
            )

    def _reauthorize(self, intent: dict[str, Any]) -> None:
        definition = MCP_TOOL_MANIFEST[TOOL_IDENTIFIER]
        if (
            str(intent["server_code"]) != SERVER_CODE
            or str(intent["tool_identifier"]) != TOOL_IDENTIFIER
            or str(intent["schema_hash"]) != definition.schema_hash
            or str(intent["confirmation_policy"]) != definition.confirmation_policy
        ):
            raise ValueError("External action manifest facts drifted")
        job = self.runtime.database.execute_one(
            """
            select j.internal_user_id, j.business_application_id, j.source_connector_id,
                   u.status as user_status, u.account_type as user_account_type
              from agent_job j join app_user u on u.id = j.internal_user_id
             where j.id = ?
            """,
            (intent["job_id"],),
        )
        if (
            job is None
            or str(job["internal_user_id"]) != str(intent["actor_user_id"])
            or str(job["business_application_id"])
            != str(intent["business_application_id"])
            or str(job["source_connector_id"]) != str(intent["source_connector_id"])
            or str(job["user_status"]) != "enabled"
            or str(job["user_account_type"]) != "human"
        ):
            raise ValueError("External action actor facts are no longer eligible")
        self.runtime.mcp_tool_snapshot_service.verify(str(intent["job_id"]))
        self.runtime.business_authorization_service.require(
            user_id=str(intent["actor_user_id"]),
            application_id=str(intent["business_application_id"]),
            tool_identifier=TOOL_IDENTIFIER,
            stage="dingtalk_external_action_execute",
        )
        identity = self.runtime.database.execute_one(
            """
            select id from user_external_identity
             where user_id = ? and provider = 'dingtalk' and status = 'enabled'
               and dingtalk_enterprise_id = ? and external_subject_id = ? and union_id = ?
            """,
            (
                intent["actor_user_id"],
                intent["dingtalk_enterprise_id"],
                intent["target_external_subject_id"],
                intent["target_union_id"],
            ),
        )
        if identity is None:
            raise ValueError("External action DingTalk identity is no longer eligible")

    def _connector_credentials(self, intent: dict[str, Any]) -> tuple[str, str]:
        connector = self.runtime.connector_registry.require_dingtalk_stream_ingress(
            str(intent["source_connector_id"])
        )
        enterprise = self.runtime.database.execute_one(
            "select status from dingtalk_enterprise where id = ?",
            (intent["dingtalk_enterprise_id"],),
        )
        if enterprise is None or str(enterprise["status"]) != "ACTIVE":
            raise ValueError("DingTalk enterprise is not active")
        client_id = self.runtime.connector_registry.metadata_value(connector, "client_id")
        client_secret = self.runtime.connector_registry.resolve_secret(connector)
        if not client_id or not client_secret:
            raise ValueError("DingTalk connector credentials are unavailable")
        return client_id, client_secret

    def _intent_token(self, intent_id: str, revision: int) -> str:
        from app.modules.external_action.service import (
            ExternalActionTokenSigner,
            external_action_signing_key,
        )

        master_key = str(self.runtime.settings.app_config_master_key)
        return str(
            ExternalActionTokenSigner(external_action_signing_key(master_key)).issue(
                intent_id, revision
            )
        )

    @staticmethod
    def _detail_text(summary: dict[str, Any]) -> str:
        due = str(summary.get("due_time") or "未设置")
        return f"待办：{str(summary.get('subject') or '')[:200]}\n截止：{due[:64]}"


def main() -> None:
    configure_logging()
    settings = load_settings()
    runtime = build_worker_container(
        settings, seed=settings.seed_local_config, service_name="external-action-worker"
    )
    worker = ExternalActionWorker(
        runtime,
        worker_id=f"{socket.gethostname()}:{os.getpid()}",
    )
    logger.info("External Action worker starting")
    while True:
        worked = worker.run_once()
        HEARTBEAT_PATH.touch()
        if not worked:
            time.sleep(1)


if __name__ == "__main__":
    main()
