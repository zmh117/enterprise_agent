"""Read successful MCP audit metadata as a search receipt, without persisting query text."""

from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_answers import code_authorization_hash
from app.modules.knowledge.domain.models import KnowledgeJobAccess, PinnedKnowledgeResource
from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.shared.database import Database


class CodeSearchReceipts:
    def __init__(self, database: Database) -> None:
        self.db = database

    def read(
        self,
        identifier: str,
        *,
        access: KnowledgeJobAccess,
        pin: PinnedKnowledgeResource,
        environment_id: str,
    ) -> dict[str, Any]:
        row = self.db.execute_one(
            "SELECT m.job_id,m.actor_user_id,m.invocation_id,m.business_response_json,"
            "m.response_truncated,m.status,a.status AS tool_status "
            "FROM mcp_operation_audit m JOIN agent_tool_call a ON a.id=m.agent_tool_call_id "
            "WHERE m.id=? AND m.parent_audit_id IS NULL AND m.server_code='knowledge-mcp' "
            "AND m.tool_identifier='knowledge_search'",
            (identifier,),
        )
        if (
            not row
            or row["job_id"] != access.job_id
            or row["actor_user_id"] != access.actor_id
            or row["status"] != "SUCCEEDED"
            or row["tool_status"] != "SUCCEEDED"
            or row["response_truncated"]
        ):
            raise CodeKnowledgeError("CODE_SUCCESSFUL_SEARCH_REQUIRED")
        response = json_value(row["business_response_json"])
        receipt = response.get("code_search") if isinstance(response, dict) else None
        if (
            not isinstance(receipt, dict)
            or receipt.get("contract") != "code-search-receipt/v2-environment"
            or receipt.get("environment_id") != environment_id
            or not environment_id
            or receipt.get("search_id") != identifier
            or receipt.get("authorization_hash") != code_authorization_hash(access)
            or receipt.get("knowledge_base_id") != pin.knowledge_base_id
            or receipt.get("resource_revision_id") != pin.revision_id
            or receipt.get("resource_fingerprint") != pin.fingerprint
            or receipt.get("source_id") != pin.source_id
            or receipt.get("index_id") != pin.index_id
        ):
            raise CodeKnowledgeError("CODE_SEARCH_CONTEXT_CHANGED")
        return {**receipt, "invocation_id": row["invocation_id"]}
