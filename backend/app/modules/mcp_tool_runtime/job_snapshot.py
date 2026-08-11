from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import ToolPolicyError

from .manifest import MCP_TOOL_MANIFEST


class JobMcpToolSnapshotService:
    """Freeze MCP Tool and target facts; Resource resolution is invocation-time only."""

    def __init__(self, database: Database, *_: Any, **__: Any) -> None:
        self.database = database

    def freeze(
        self,
        *,
        job_id: str,
        requester_id: str,
        application_id: str,
        application_publication_id: str,
        application_config_hash: str,
        agent_publication_id: str,
        routing_context: dict[str, Any],
        business_authorization: dict[str, Any],
        runtime_authorization: dict[str, Any],
    ) -> dict[str, Any]:
        del requester_id, application_id, application_config_hash, business_authorization
        tools = self.database.execute(
            """
            select tool_identifier, schema_hash
              from business_application_publication_mcp_tool
             where application_publication_id = ?
               and agent_publication_id = ?
             order by tool_identifier
            """,
            (application_publication_id, agent_publication_id),
        )
        granted = {
            str(value.get("tool_identifier") or "")
            for value in runtime_authorization.get("tool_grants") or []
            if value.get("source_role_codes")
        }
        tools = [row for row in tools if str(row["tool_identifier"]) in granted]
        return self._persist(
            job_id=job_id,
            application_publication_id=application_publication_id,
            agent_publication_id=agent_publication_id,
            routing_context=routing_context,
            tools=tools,
            authorization=runtime_authorization,
        )

    def freeze_agent_only(
        self,
        *,
        job_id: str,
        requester_id: str,
        agent_publication_id: str,
        routing_context: dict[str, Any],
        business_authorization: dict[str, Any],
        runtime_authorization: dict[str, Any],
    ) -> dict[str, Any]:
        del requester_id, business_authorization
        tools = self.database.execute(
            """
            select tool_identifier, schema_hash
              from agent_publication_mcp_tool
             where agent_publication_id = ?
             order by tool_identifier
            """,
            (agent_publication_id,),
        )
        return self._persist(
            job_id=job_id,
            application_publication_id="",
            agent_publication_id=agent_publication_id,
            routing_context=routing_context,
            tools=tools,
            authorization=runtime_authorization,
        )

    def verify(self, job_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from agent_job_mcp_tool_snapshot where job_id = ?",
            (job_id,),
        )
        if row is None:
            raise ToolPolicyError(
                "Job MCP Tool Snapshot is missing",
                safe_message="此 Job 缺少 MCP 工具快照",
                error_code="mcp_tool_snapshot_missing",
            )
        snapshot = self._json(row["snapshot_json"])
        expected = self._hash(snapshot)
        if expected != str(row["snapshot_hash"]):
            raise ToolPolicyError(
                "Job MCP Tool Snapshot integrity failed",
                safe_message="Job MCP 工具快照完整性校验失败",
                error_code="mcp_tool_snapshot_integrity_failed",
            )
        for tool in snapshot.get("tools") or []:
            definition = MCP_TOOL_MANIFEST.get(str(tool.get("tool_identifier") or ""))
            if definition is None or definition.schema_hash != str(tool.get("schema_hash") or ""):
                raise ToolPolicyError(
                    "Job MCP Tool schema drift detected",
                    safe_message="MCP 工具 Schema 已变化，请重新发布 Agent 和应用",
                    error_code="mcp_tool_schema_drift",
                )
        return {
            "id": str(row["id"]),
            "job_id": job_id,
            "snapshot": snapshot,
            "snapshot_hash": str(row["snapshot_hash"]),
            "authorization_hash": str(row["authorization_hash"]),
        }

    def tool_binding(
        self,
        *,
        job_id: str,
        tool_identifier: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        verified = self.verify(job_id)
        snapshot = verified["snapshot"]
        matches = [
            value
            for value in snapshot.get("tools") or []
            if str(value.get("tool_identifier") or "") == tool_identifier
        ]
        if len(matches) != 1:
            return None
        definition = MCP_TOOL_MANIFEST[tool_identifier]
        return (
            dict(snapshot.get("target") or {}),
            [
                {
                    "tool_identifier": tool_identifier,
                    "public_schema_hash": definition.schema_hash,
                    "schema_hash": definition.schema_hash,
                    "resource_kind": definition.resource_kind,
                    "resource_slot": "",
                    "candidates": [],
                    "available_placements": list(
                        snapshot.get("allowed_placements") or []
                    ),
                }
            ],
        )

    def _persist(
        self,
        *,
        job_id: str,
        application_publication_id: str,
        agent_publication_id: str,
        routing_context: dict[str, Any],
        tools: list[dict[str, Any]],
        authorization: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self.database.execute_one(
            "select id from agent_job_mcp_tool_snapshot where job_id = ?",
            (job_id,),
        )
        if existing is not None:
            return self.verify(job_id)
        target = {
            "environment_code": str(routing_context.get("environment") or ""),
            "base_code": str(routing_context.get("base") or ""),
            "workshop_code": str(routing_context.get("workshop") or ""),
        }
        placement = str(routing_context.get("placement") or "").strip().lower()
        allowed_placements = [placement] if placement in {"cloud", "edge"} else []
        normalized_tools = []
        for row in tools:
            identifier = str(row["tool_identifier"])
            definition = MCP_TOOL_MANIFEST.get(identifier)
            if definition is None:
                continue
            schema_hash = str(row.get("schema_hash") or definition.schema_hash)
            if schema_hash != definition.schema_hash:
                raise ToolPolicyError(
                    "Publication MCP Tool schema does not match the code manifest",
                    safe_message="发布版本中的 MCP 工具 Schema 已失效，请重新发布",
                    error_code="mcp_tool_schema_drift",
                )
            normalized_tools.append(
                {
                    "server_code": "tool-mcp",
                    "tool_identifier": identifier,
                    "schema_hash": definition.schema_hash,
                    "resource_kind": definition.resource_kind,
                }
            )
        snapshot = {
            "schema_version": 1,
            "job_id": job_id,
            "application_publication_id": application_publication_id,
            "agent_publication_id": agent_publication_id,
            "target": target,
            "allowed_placements": allowed_placements,
            "tools": normalized_tools,
        }
        authorization_hash = self._hash(authorization)
        snapshot_hash = self._hash(snapshot)
        snapshot_id = new_id("job_mcp_tools")
        self.database.execute(
            """
            insert into agent_job_mcp_tool_snapshot
              (id, job_id, application_publication_id, agent_publication_id,
               schema_version, snapshot_json, snapshot_hash,
               authorization_hash, created_at)
            values (?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                job_id,
                application_publication_id or None,
                agent_publication_id,
                self._json_text(snapshot),
                snapshot_hash,
                authorization_hash,
                now_iso(),
            ),
        )
        return {
            "id": snapshot_id,
            "job_id": job_id,
            "snapshot": snapshot,
            "snapshot_hash": snapshot_hash,
            "authorization_hash": authorization_hash,
        }

    @staticmethod
    def _json(value: Any) -> dict[str, Any]:
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _json_text(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _hash(cls, value: Any) -> str:
        return hashlib.sha256(cls._json_text(value).encode("utf-8")).hexdigest()
