from __future__ import annotations

import json
from typing import Any

from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.modules.business_application.domain.policies import required_file_mcp_tools
from app.modules.job.infrastructure.repositories import now_iso
from app.shared.database import Database
from app.shared.dingtalk_card_templates import external_action_confirmation_card_binding
from app.shared.exceptions import NonRetryableExecutionError


class ApplicationMcpToolCompositionService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def management_catalog(self, *, agent_publication_ids: list[str]) -> dict[str, Any]:
        values: dict[str, list[dict[str, Any]]] = {}
        for publication_id in agent_publication_ids:
            rows = self.database.execute(
                """
                select server_code, tool_identifier, schema_hash, model_description
                  from agent_publication_mcp_tool
                 where agent_publication_id = ?
                 order by selection_order
                """,
                (publication_id,),
            )
            values[publication_id] = [
                {
                    "server_code": str(row["server_code"]),
                    "tool_identifier": str(row["tool_identifier"]),
                    "schema_hash": str(row["schema_hash"]),
                    "description": MCP_TOOL_MANIFEST[str(row["tool_identifier"])].description,
                    "resource_kind": MCP_TOOL_MANIFEST[str(row["tool_identifier"])].resource_kind,
                    "effect": MCP_TOOL_MANIFEST[str(row["tool_identifier"])].effect,
                    "confirmation_policy": MCP_TOOL_MANIFEST[
                        str(row["tool_identifier"])
                    ].confirmation_policy,
                    "operation_code": MCP_TOOL_MANIFEST[str(row["tool_identifier"])].operation_code,
                    "risk_level": MCP_TOOL_MANIFEST[str(row["tool_identifier"])].risk_level,
                    "target_policy": MCP_TOOL_MANIFEST[str(row["tool_identifier"])].target_policy,
                }
                for row in rows
                if str(row["tool_identifier"]) in MCP_TOOL_MANIFEST
            ]
        return {"mcp_tools_by_agent_publication": values}

    def prepare(
        self,
        *,
        agent_publication_id: str,
        raw_tools: list[Any],
    ) -> list[dict[str, Any]]:
        available = {
            str(row["tool_identifier"]): {
                "server_code": str(row["server_code"]),
                "schema_hash": str(row["schema_hash"]),
            }
            for row in self.database.execute(
                """
                select server_code, tool_identifier, schema_hash
                  from agent_publication_mcp_tool
                 where agent_publication_id = ?
                """,
                (agent_publication_id,),
            )
        }
        selected: list[str] = []
        for index, raw in enumerate(raw_tools):
            identifier = (
                str(raw.get("tool_identifier") or raw.get("identifier") or "")
                if isinstance(raw, dict)
                else str(raw)
            ).strip()
            if not identifier or identifier in selected:
                if identifier in selected:
                    continue
                raise self._invalid(index, "MCP Tool identifier 不能为空")
            definition = MCP_TOOL_MANIFEST.get(identifier)
            requested_server = (
                str(raw.get("server_code") or "").strip() if isinstance(raw, dict) else ""
            )
            published = available.get(identifier)
            if (
                definition is None
                or published is None
                or published["schema_hash"] != definition.schema_hash
                or published["server_code"] != definition.server_code
                or (requested_server and requested_server != definition.server_code)
            ):
                raise self._invalid(index, "所选 MCP Tool 不在 Agent 发布范围内或 Schema 已变化")
            selected.append(identifier)
        return [
            {
                "server_code": MCP_TOOL_MANIFEST[identifier].server_code,
                "tool_identifier": identifier,
                "schema_hash": MCP_TOOL_MANIFEST[identifier].schema_hash,
                "resource_kind": MCP_TOOL_MANIFEST[identifier].resource_kind,
                "effect": MCP_TOOL_MANIFEST[identifier].effect,
                "confirmation_policy": MCP_TOOL_MANIFEST[identifier].confirmation_policy,
                "operation_code": MCP_TOOL_MANIFEST[identifier].operation_code,
                "risk_level": MCP_TOOL_MANIFEST[identifier].risk_level,
                "target_policy": MCP_TOOL_MANIFEST[identifier].target_policy,
                "selection_order": index,
            }
            for index, identifier in enumerate(selected)
        ]

    def file_feature_errors(
        self,
        *,
        agent_publication_id: str,
        task_file_features: dict[str, bool],
        selected_tools: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        required = required_file_mcp_tools(task_file_features)
        if not required:
            return []
        available = {
            str(row["tool_identifier"])
            for row in self.database.execute(
                """
                select tool_identifier
                  from agent_publication_mcp_tool
                 where agent_publication_id = ?
                   and server_code = 'file-service'
                """,
                (agent_publication_id,),
            )
        }
        missing_agent = sorted(required - available)
        if missing_agent:
            summary = "、".join(missing_agent)
            return [
                {
                    "field": "agent_publication_id",
                    "message": f"所选 Agent 发布版本缺少任务文件工具：{summary}",
                },
                {
                    "field": "mcp_tools",
                    "message": "请先发布包含所需 File MCP 工具的新 Agent 版本",
                },
            ]
        selected = {
            str(tool.get("tool_identifier") or "")
            for tool in selected_tools
            if str(tool.get("server_code") or "") == "file-service"
        }
        missing_application = sorted(required - selected)
        if missing_application:
            return [
                {
                    "field": "mcp_tools",
                    "message": (
                        "任务文件功能已启用，必须选择 File MCP 工具："
                        + "、".join(missing_application)
                    ),
                }
            ]
        return []

    def dingtalk_feature_errors(
        self,
        *,
        selected_tools: list[dict[str, Any]],
        triggers: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        selected = {
            str(tool.get("tool_identifier") or "")
            for tool in selected_tools
            if str(tool.get("server_code") or "") == "dingtalk-mcp"
        }
        requires_confirmation_card = any(
            str(tool.get("confirmation_policy") or "") == "external_action_card_v1"
            or (
                (definition := MCP_TOOL_MANIFEST.get(str(tool.get("tool_identifier") or "")))
                is not None
                and definition.confirmation_policy == "external_action_card_v1"
            )
            for tool in selected_tools
        )
        if not selected and not requires_confirmation_card:
            return []
        dingtalk_triggers = [
            trigger
            for trigger in triggers
            if bool(trigger.get("enabled"))
            and str(trigger.get("trigger_type") or "") in {"dingtalk_private", "dingtalk_group"}
        ]
        if not dingtalk_triggers:
            return [
                {
                    "field": "mcp_tools",
                    "message": (
                        "钉钉 MCP 工具要求至少一个已启用的钉钉来源 Trigger"
                        if selected
                        else "需逐次确认的写入工具要求至少一个已启用的钉钉来源 Trigger"
                    ),
                }
            ]
        notice_tools = {
            "dingtalk_send_work_notification",
            "dingtalk_get_work_notification_progress",
            "dingtalk_get_work_notification_result",
        }
        batch_robot_tools = {"dingtalk_batch_send_message_to_users_by_robot"}
        requires_notice = bool(selected.intersection(notice_tools))
        requires_batch_robot = bool(selected.intersection(batch_robot_tools))
        missing_notice: list[str] = []
        missing_batch_robot: list[str] = []
        missing_confirmation_card: list[str] = []
        for trigger in dingtalk_triggers:
            connector_id = str(trigger.get("connector_id") or "")
            row = self.database.execute_one(
                """
                select name, metadata, revision from integration_connector
                 where id = ? and connector_type = 'dingtalk_enterprise_stream'
                   and enabled = 1 and deleted = 0
                """,
                (connector_id,),
            )
            metadata = self._json_object((row or {}).get("metadata"))
            connector_name = str((row or {}).get("name") or connector_id or "未知连接")
            if requires_notice and (
                row is None
                or self._positive_int(metadata.get("work_notification_agent_id")) is None
            ):
                missing_notice.append(connector_name)
            if requires_batch_robot and (
                row is None or not str(metadata.get("default_robot_code") or "").strip()
            ):
                missing_batch_robot.append(connector_name)
            if requires_confirmation_card and (
                row is None
                or external_action_confirmation_card_binding(
                    metadata,
                    connector_id=connector_id,
                    connector_revision=int((row or {}).get("revision") or 0),
                )
                is None
            ):
                missing_confirmation_card.append(connector_name)
        errors: list[dict[str, str]] = []
        if missing_notice:
            errors.append(
                {
                    "field": "mcp_tools",
                    "message": (
                        "工作通知工具要求所有钉钉来源连接配置正整数 Agent ID："
                        + "、".join(sorted(set(missing_notice)))[:300]
                    ),
                }
            )
        if missing_batch_robot:
            errors.append(
                {
                    "field": "mcp_tools",
                    "message": (
                        "批量用户机器人消息工具要求所有钉钉来源连接配置企业机器人 Code："
                        + "、".join(sorted(set(missing_batch_robot)))[:300]
                    ),
                }
            )
        if missing_confirmation_card:
            errors.append(
                {
                    "field": "mcp_tools",
                    "message": (
                        "需逐次确认的写入工具要求所有钉钉来源连接配置"
                        "外部操作确认卡片模板 ID："
                        + "、".join(sorted(set(missing_confirmation_card)))[:300]
                    ),
                }
            )
        return errors

    def persist_draft(
        self,
        *,
        application_revision_id: str,
        agent_publication_id: str,
        tools: list[dict[str, Any]],
    ) -> None:
        timestamp = now_iso()
        for tool in tools:
            self.database.execute(
                """
                insert into business_application_revision_mcp_tool
                  (application_revision_id, agent_publication_id, server_code,
                   tool_identifier, schema_hash, selection_order, created_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application_revision_id,
                    agent_publication_id,
                    tool["server_code"],
                    tool["tool_identifier"],
                    tool["schema_hash"],
                    tool["selection_order"],
                    timestamp,
                ),
            )

    def persist_publication(
        self,
        *,
        application_publication_id: str,
        agent_publication_id: str,
        tools: list[dict[str, Any]],
    ) -> None:
        existing = self.database.execute_one(
            "select 1 as present from business_application_publication_mcp_tool where application_publication_id = ? limit 1",
            (application_publication_id,),
        )
        if existing is not None:
            return
        timestamp = now_iso()
        for tool in tools:
            self.database.execute(
                """
                insert into business_application_publication_mcp_tool
                  (application_publication_id, agent_publication_id, server_code,
                   tool_identifier, schema_hash, selection_order, created_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application_publication_id,
                    agent_publication_id,
                    tool["server_code"],
                    tool["tool_identifier"],
                    tool["schema_hash"],
                    tool["selection_order"],
                    timestamp,
                ),
            )

    @staticmethod
    def snapshot(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "server_code": str(tool["server_code"]),
                "tool_identifier": str(tool["tool_identifier"]),
                "schema_hash": str(tool["schema_hash"]),
                "resource_kind": str(tool.get("resource_kind") or ""),
                "effect": str(tool.get("effect") or "read"),
                "confirmation_policy": str(tool.get("confirmation_policy") or "none"),
                "operation_code": str(tool.get("operation_code") or ""),
                "risk_level": str(tool.get("risk_level") or "low"),
                "target_policy": str(tool.get("target_policy") or ""),
            }
            for tool in tools
        ]

    @staticmethod
    def _invalid(index: int, message: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "Application MCP Tool selection is invalid",
            safe_message="业务应用 MCP 工具配置无效",
            error_code="validation_failed",
            field_errors=[{"field": f"mcp_tools.{index}", "message": message}],
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
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None
