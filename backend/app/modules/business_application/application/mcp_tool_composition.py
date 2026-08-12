from __future__ import annotations

from typing import Any

from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.modules.job.infrastructure.repositories import now_iso
from app.shared.database import Database
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
                    "description": str(row.get("model_description") or ""),
                    "resource_kind": MCP_TOOL_MANIFEST[str(row["tool_identifier"])].resource_kind,
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
                "selection_order": index,
            }
            for index, identifier in enumerate(selected)
        ]

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
