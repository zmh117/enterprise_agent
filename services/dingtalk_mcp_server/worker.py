from __future__ import annotations

import json
import logging
import os
import socket
import time
from pathlib import Path
from typing import Any

from app.bootstrap import Container, build_worker_container
from app.modules.dingding.infrastructure.dingtalk_delivery_clients import DingTalkAccessTokenClient
from app.modules.external_action.card import render_confirmation_card
from app.modules.external_action.repository import ExternalActionRepository
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.dingtalk_card_templates import (
    EXTERNAL_ACTION_CONFIRMATION_CARD_CONTRACT_VERSION,
    EXTERNAL_ACTION_CONFIRMATION_CARD_PURPOSE,
    normalize_dingtalk_card_template_id,
)
from app.shared.dingtalk_tool_contracts import (
    DINGTALK_MUTATION_TOOL_IDENTIFIERS,
    DINGTALK_TOOL_CONTRACTS,
    DingTalkToolContract,
)
from app.shared.config import load_settings
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.logging import configure_logging
from services.dingtalk_mcp_server.contracts import SERVER_CODE
from services.dingtalk_mcp_server.provider import (
    DingTalkAiTableMutationClient,
    DingTalkAiTableReadClient,
    DingTalkCalendarMutationClient,
    DingTalkCardClient,
    DingTalkRobotMutationClient,
    DingTalkTodoClient,
    DingTalkWorkNotificationMutationClient,
)
from services.external_action_worker.ones_adapter import OnesExternalActionAdapter
from services.external_action_worker.runtime import (
    ExternalActionExecutionOutcome,
    ProviderNeutralExternalActionWorker,
)


logger = logging.getLogger(__name__)
HEARTBEAT_PATH = Path("/tmp/external-action-worker.heartbeat")


class _DingTalkExecutionAdapter:
    def __init__(self, worker: ExternalActionWorker) -> None:
        self.worker = worker

    def execute(self, intent: dict[str, Any]) -> ExternalActionExecutionOutcome:
        return self.worker._execute_dingtalk_provider(intent)

    @staticmethod
    def reconcile_interrupted(
        _intent: dict[str, Any],
    ) -> ExternalActionExecutionOutcome | None:
        return None


class ExternalActionWorker:
    def __init__(self, runtime: Container, *, worker_id: str) -> None:
        self.runtime = runtime
        self.repository = ExternalActionRepository(runtime.database)
        self.worker_id = worker_id[:128]
        self._dispatchers = {
            "dingtalk.todo.create": self._execute_todo_create,
            "dingtalk.todo.update": self._execute_todo_update,
            "dingtalk.todo.complete": self._execute_todo_complete,
            "dingtalk.calendar.event.create": self._execute_calendar_create,
            "dingtalk.calendar.event.update": self._execute_calendar_update,
            "dingtalk.aitable.sheet.create": self._execute_aitable_sheet_create,
            "dingtalk.aitable.sheet.update": self._execute_aitable_sheet_update,
            "dingtalk.aitable.field.create": self._execute_aitable_field_create,
            "dingtalk.aitable.field.update": self._execute_aitable_field_update,
            "dingtalk.aitable.record.insert": self._execute_aitable_insert,
            "dingtalk.aitable.record.update": self._execute_aitable_update,
            "dingtalk.robot.group_message.send": self._execute_robot_group_send,
            "dingtalk.robot.batch_send_message_to_users": self._execute_robot_user_batch_send,
            "dingtalk.work_notification.send": self._execute_work_notification_send,
        }
        expected_operations = {
            DINGTALK_TOOL_CONTRACTS[identifier].operation_code
            for identifier in DINGTALK_MUTATION_TOOL_IDENTIFIERS
        }
        if set(self._dispatchers) != expected_operations:
            raise ValueError("External action dispatcher is incomplete")
        self._orchestrator = ProviderNeutralExternalActionWorker(
            runtime,
            worker_id=self.worker_id,
            repository=self.repository,
            card_dispatcher=self._dispatch_card,
            execution_adapters={
                "dingtalk": _DingTalkExecutionAdapter(self),
                "ones": OnesExternalActionAdapter(runtime),
            },
        )

    def run_once(self) -> bool:
        self._orchestrator.repository = self.repository
        return self._orchestrator.run_once()

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
            payload = self.repository.decode_json(outbox.get("payload_json"))
            if str(outbox["event_kind"]) == "CREATE":
                summary = self._confirmation_summary(intent)
                token = self._intent_token(str(intent["id"]), int(intent["revision"]))
                card_fields = self._confirmation_card_fields(intent, summary)
                client.create_confirmation(
                    card_template_id=self._confirmation_card_template_id(
                        intent=intent,
                        payload=payload,
                    ),
                    out_track_id=str(intent["id"]),
                    staff_id=str(intent["target_external_subject_id"]),
                    card_fields={
                        **card_fields,
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
                summary = self._confirmation_summary(intent)
                status = str(payload.get("status") or "failed")
                operation = str(summary.get("operation") or "钉钉操作")[:100]
                status_text = str(payload.get("statusText") or "").strip() or (
                    f"{operation}成功"
                    if status == "succeeded"
                    else f"{operation}失败，请联系管理员"
                )
                extra_fields = payload.get("cardFields")
                if not isinstance(extra_fields, dict):
                    extra_fields = {}
                allowed_extra = {"providerName", "operationName", "targetName", "detailText"}
                if set(extra_fields) - allowed_extra or any(
                    not isinstance(value, str) for value in extra_fields.values()
                ):
                    raise ValueError("External action result card fields are invalid")
                client.update(
                    out_track_id=str(intent["id"]),
                    card_fields={
                        **extra_fields,
                        "status": status,
                        "statusText": status_text[:200],
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

    @staticmethod
    def _confirmation_card_template_id(
        *,
        intent: dict[str, Any],
        payload: dict[str, Any],
    ) -> str:
        binding = payload.get("card_binding")
        if not isinstance(binding, dict):
            binding = {}
        template_id = normalize_dingtalk_card_template_id(binding.get("template_id"))
        connector_revision = binding.get("connector_revision")
        valid = (
            template_id
            and str(binding.get("purpose") or "") == EXTERNAL_ACTION_CONFIRMATION_CARD_PURPOSE
            and str(binding.get("contract_version") or "")
            == EXTERNAL_ACTION_CONFIRMATION_CARD_CONTRACT_VERSION
            and str(binding.get("connector_id") or "")
            == str(intent.get("source_connector_id") or "")
            and isinstance(connector_revision, int)
            and not isinstance(connector_revision, bool)
            and connector_revision > 0
        )
        if not valid:
            raise NonRetryableExecutionError(
                "Frozen DingTalk confirmation card binding is invalid",
                safe_message="外部操作确认卡片的冻结模板绑定无效",
                error_code="dingtalk_confirmation_card_binding_invalid",
            )
        return template_id

    def _confirmation_summary(self, intent: dict[str, Any]) -> dict[str, Any]:
        full = self.repository.decode_json(intent.get("confirmation_summary_json"))
        if full:
            return full
        return self.repository.decode_json(intent["safe_summary_json"])

    def _execute(self, intent: dict[str, Any]) -> None:
        self._orchestrator.repository = self.repository
        self._orchestrator.execute_intent(intent)

    def _execute_dingtalk_provider(
        self,
        intent: dict[str, Any],
    ) -> ExternalActionExecutionOutcome:
        contract = self._reauthorize(intent)
        client_id, client_secret = self._connector_credentials(intent)
        arguments = self.repository.decode_json(intent["arguments_json"])
        token_client = DingTalkAccessTokenClient(
            client_id=client_id,
            client_secret=client_secret,
            timeout_seconds=5,
        )
        dispatcher = self._dispatchers.get(contract.operation_code)
        if dispatcher is None:
            raise ValueError("External action operation is not registered")
        result = dispatcher(intent, arguments, token_client)
        return ExternalActionExecutionOutcome(
            result=result,
            provider_request_id=str(
                result.get("task_id")
                or result.get("event_id")
                or result.get("message_request_id")
                or ""
            ),
            card_status_text=self._success_card_status_text(contract, result),
        )

    @staticmethod
    def _success_card_status_text(
        contract: DingTalkToolContract,
        result: dict[str, Any],
    ) -> str:
        if contract.operation_code == "dingtalk.robot.group_message.send":
            return "群机器人消息请求已受理，最终送达以钉钉为准"
        if contract.operation_code == "dingtalk.robot.batch_send_message_to_users":
            accepted = max(0, int(result.get("accepted_count") or 0))
            rejected = max(0, int(result.get("not_accepted_count") or 0))
            if bool(result.get("fully_accepted")):
                return f"批量机器人消息请求已受理：{accepted} 人受理"
            return f"批量消息请求已受理：{accepted} 人受理，{rejected} 人未受理"
        if contract.operation_code == "dingtalk.work_notification.send":
            return "工作通知发送任务已提交，最终结果请查询发送进度"
        return ""

    def _reauthorize(self, intent: dict[str, Any]) -> DingTalkToolContract:
        tool_identifier = str(intent["tool_identifier"])
        contract = DINGTALK_TOOL_CONTRACTS.get(tool_identifier)
        definition = MCP_TOOL_MANIFEST.get(tool_identifier)
        if (
            contract is None
            or contract.effect != "mutation"
            or definition is None
            or str(intent["server_code"]) != SERVER_CODE
            or definition.server_code != SERVER_CODE
            or str(intent["schema_hash"]) != definition.schema_hash
            or str(intent["confirmation_policy"]) != definition.confirmation_policy
            or str(intent["operation_code"]) != definition.operation_code
            or definition.operation_code != contract.operation_code
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
            or str(job["business_application_id"]) != str(intent["business_application_id"])
            or str(job["source_connector_id"]) != str(intent["source_connector_id"])
            or str(job["user_status"]) != "enabled"
            or str(job["user_account_type"]) != "human"
        ):
            raise ValueError("External action actor facts are no longer eligible")
        verified = self.runtime.mcp_tool_snapshot_service.verify(str(intent["job_id"]))
        matches = [
            item
            for item in verified["snapshot"].get("tools") or []
            if isinstance(item, dict)
            and str(item.get("server_code") or "") == SERVER_CODE
            and str(item.get("tool_identifier") or "") == tool_identifier
            and str(item.get("schema_hash") or "") == definition.schema_hash
        ]
        if len(matches) != 1:
            raise ValueError("External action Tool is absent from the Job snapshot")
        self.runtime.business_authorization_service.require(
            user_id=str(intent["actor_user_id"]),
            application_id=str(intent["business_application_id"]),
            tool_identifier=tool_identifier,
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
        self._reauthorize_target(intent, contract)
        return contract

    def _execute_todo_create(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        result = DingTalkTodoClient(token_client).create_for_self(
            union_id=str(intent["target_union_id"]),
            arguments=arguments,
        )
        if not str(result.get("task_id") or ""):
            raise ValueError("DingTalk todo creation did not return a task ID")
        return result

    def _execute_todo_update(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        return DingTalkTodoClient(token_client).update_for_self(
            union_id=str(intent["target_union_id"]),
            arguments=arguments,
        )

    def _execute_todo_complete(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        return DingTalkTodoClient(token_client).complete_for_self(
            union_id=str(intent["target_union_id"]),
            arguments=arguments,
        )

    def _execute_calendar_create(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        result = DingTalkCalendarMutationClient(token_client).create_for_self(
            union_id=str(intent["target_union_id"]),
            arguments=arguments,
        )
        if not str(result.get("event_id") or ""):
            raise ValueError("DingTalk calendar creation did not return an event ID")
        return result

    def _execute_calendar_update(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        return DingTalkCalendarMutationClient(token_client).update_for_self(
            union_id=str(intent["target_union_id"]),
            arguments=arguments,
        )

    def _execute_aitable_sheet_create(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        operator_id = str(intent["target_union_id"])
        self._preflight_aitable(token_client, arguments, operator_id=operator_id)
        return DingTalkAiTableMutationClient(token_client).create_sheet(
            operator_id=operator_id,
            arguments=arguments,
        )

    def _execute_aitable_sheet_update(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        operator_id = str(intent["target_union_id"])
        self._preflight_aitable(token_client, arguments, operator_id=operator_id)
        return DingTalkAiTableMutationClient(token_client).update_sheet(
            operator_id=operator_id,
            arguments=arguments,
        )

    def _execute_aitable_field_create(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        operator_id = str(intent["target_union_id"])
        self._preflight_aitable(token_client, arguments, operator_id=operator_id)
        return DingTalkAiTableMutationClient(token_client).create_field(
            operator_id=operator_id,
            arguments=arguments,
        )

    def _execute_aitable_field_update(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        operator_id = str(intent["target_union_id"])
        self._preflight_aitable(token_client, arguments, operator_id=operator_id)
        return DingTalkAiTableMutationClient(token_client).update_field(
            operator_id=operator_id,
            arguments=arguments,
        )

    def _execute_aitable_insert(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        operator_id = str(intent["target_union_id"])
        self._preflight_aitable(token_client, arguments, operator_id=operator_id)
        return DingTalkAiTableMutationClient(token_client).insert_records(
            operator_id=operator_id,
            arguments=arguments,
        )

    def _execute_aitable_update(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        operator_id = str(intent["target_union_id"])
        self._preflight_aitable(token_client, arguments, operator_id=operator_id)
        return DingTalkAiTableMutationClient(token_client).update_records(
            operator_id=operator_id,
            arguments=arguments,
        )

    def _execute_robot_group_send(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        del intent
        return DingTalkRobotMutationClient(token_client).send_to_group(arguments=arguments)

    def _execute_robot_user_batch_send(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        del intent
        return DingTalkRobotMutationClient(token_client).batch_send_to_users(arguments=arguments)

    def _execute_work_notification_send(
        self,
        intent: dict[str, Any],
        arguments: dict[str, Any],
        token_client: DingTalkAccessTokenClient,
    ) -> dict[str, Any]:
        del intent
        result = DingTalkWorkNotificationMutationClient(token_client).send_to_self(
            arguments=arguments
        )
        if int(result.get("task_id") or 0) <= 0:
            raise ValueError("DingTalk work notification did not return a task ID")
        return result

    @staticmethod
    def _preflight_aitable(
        token_client: DingTalkAccessTokenClient,
        arguments: dict[str, Any],
        *,
        operator_id: str,
    ) -> None:
        client = DingTalkAiTableReadClient(token_client)
        base_id = str(arguments["base_id"])
        sheet_id = str(arguments.get("sheet_id") or "")
        if not sheet_id:
            client.list_sheets(operator_id=operator_id, base_id=base_id)
            return
        client.get_sheet(operator_id=operator_id, base_id=base_id, sheet_id=sheet_id)
        field_id = str(arguments.get("field_id") or "")
        if field_id:
            fields = client.list_fields(
                operator_id=operator_id,
                base_id=base_id,
                sheet_id=sheet_id,
            ).get("fields")
            if not isinstance(fields, list) or not any(
                isinstance(row, dict) and str(row.get("field_id") or "") == field_id
                for row in fields
            ):
                raise ValueError("External action AI table field is unavailable")

    def _reauthorize_target(
        self,
        intent: dict[str, Any],
        contract: DingTalkToolContract,
    ) -> None:
        target_policy = contract.target_policy
        if target_policy == "current_user_todo":
            return
        arguments = self.repository.decode_json(intent["arguments_json"])
        if target_policy == "current_user_primary_calendar":
            target = self._target(arguments)
            if target != {
                "union_id": str(intent["target_union_id"]),
                "calendar_id": "primary",
            }:
                raise ValueError("External action calendar target facts drifted")
            return
        if target_policy == "explicit_aitable_resource_for_current_operator":
            target = self._target(arguments)
            expected_target = {
                "operator_id": str(intent["target_union_id"]),
                "base_id": str(arguments.get("base_id") or ""),
            }
            for key in ("sheet_id", "field_id"):
                value = str(arguments.get(key) or "")
                if value:
                    expected_target[key] = value
            if target != expected_target:
                raise ValueError("External action AI table target facts drifted")
            return
        if target_policy == "current_source_group":
            if self._target(arguments) != self._current_robot_group_target(intent):
                raise ValueError("External action source group target facts drifted")
            return
        if target_policy == "explicit_enterprise_user_ids":
            user_ids = arguments.get("user_ids")
            target = self._target(arguments)
            robot_code = self._enterprise_robot_code(intent)
            if (
                not isinstance(user_ids, list)
                or not user_ids
                or any(not isinstance(user_id, str) or not user_id for user_id in user_ids)
                or not robot_code
                or type(target.get("recipient_count")) is not int
                or target
                != {
                    "robot_code": robot_code,
                    "recipient_count": len(user_ids),
                }
            ):
                raise ValueError("External action robot user batch target facts drifted")
            return
        if target_policy == "current_user_work_notification":
            target = self._target(arguments)
            connector = self.runtime.connector_registry.require_dingtalk_stream_ingress(
                str(intent["source_connector_id"])
            )
            agent_id = self._positive_int(
                self.runtime.connector_registry.metadata_value(
                    connector, "work_notification_agent_id"
                )
            )
            if (
                target
                != {
                    "agent_id": agent_id,
                    "staff_id": str(intent["target_external_subject_id"]),
                }
                or agent_id is None
            ):
                raise ValueError("External action work notification target facts drifted")
            return
        raise ValueError("External action target policy is unsupported")

    def _enterprise_robot_code(self, intent: dict[str, Any]) -> str:
        connector = self.runtime.connector_registry.require_dingtalk_stream_ingress(
            str(intent["source_connector_id"])
        )
        return str(
            self.runtime.connector_registry.metadata_value(connector, "default_robot_code") or ""
        )

    def _current_robot_group_target(self, intent: dict[str, Any]) -> dict[str, Any]:
        source = self.runtime.database.execute_one(
            """
            select s.conversation_type, s.external_conversation_id,
                   s.bot_identity, s.reply_route_json
              from agent_job j join agent_session s on s.id = j.session_id
             where j.id = ? and s.source_connector_id = j.source_connector_id
            """,
            (intent["job_id"],),
        )
        if source is None or not str(source.get("external_conversation_id") or ""):
            raise ValueError("External action source conversation is unavailable")
        route = self._json_object(source.get("reply_route_json"))
        route_connector = str(route.get("connector_id") or "")
        if route_connector and route_connector != str(intent["source_connector_id"]):
            raise ValueError("External action source connector facts drifted")
        route_target = route.get("target")
        route_target = route_target if isinstance(route_target, dict) else {}
        connector = self.runtime.connector_registry.require_dingtalk_stream_ingress(
            str(intent["source_connector_id"])
        )
        robot_code = str(
            route_target.get("robot_code")
            or source.get("bot_identity")
            or self.runtime.connector_registry.metadata_value(connector, "default_robot_code")
            or ""
        )
        if not robot_code:
            raise ValueError("External action robot identity is unavailable")
        conversation_type = str(source.get("conversation_type") or "")
        if conversation_type != "group":
            raise ValueError("External action source is not a group conversation")
        open_conversation_id = str(route_target.get("open_conversation_id") or "")
        if not open_conversation_id:
            raise ValueError("External action group target is unavailable")
        return {
            "open_conversation_id": open_conversation_id,
            "robot_code": robot_code,
        }

    @staticmethod
    def _target(arguments: dict[str, Any]) -> dict[str, Any]:
        target = arguments.get("_target")
        if not isinstance(target, dict):
            raise ValueError("External action target facts are missing")
        return target

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
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _connector_credentials(self, intent: dict[str, Any]) -> tuple[str, str]:
        connector = self.runtime.connector_registry.require_dingtalk_stream_ingress(
            str(intent["source_connector_id"])
        )
        enterprise = self.runtime.database.execute_one(
            """
            select e.status
              from integration_connector c
              join dingtalk_enterprise e on e.id = c.dingtalk_enterprise_id
             where c.id = ? and c.dingtalk_enterprise_id = ?
            """,
            (intent["source_connector_id"], intent["dingtalk_enterprise_id"]),
        )
        if enterprise is None or str(enterprise["status"]) != "ACTIVE":
            raise ValueError("DingTalk connector enterprise binding is no longer eligible")
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

    @classmethod
    def _confirmation_card_fields(
        cls,
        intent: dict[str, Any],
        summary: dict[str, Any],
    ) -> dict[str, str]:
        del cls
        return render_confirmation_card(intent, summary)


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
