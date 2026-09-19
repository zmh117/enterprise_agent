"""两个固定工具的适配与安全审计；不复制检索、目录或权限业务规则。"""

from collections.abc import Mapping
import json
import time
from typing import Any

from jsonschema import Draft202012Validator

from app.modules.knowledge.application.directory import KnowledgeDirectory
from app.modules.knowledge.application.search import KnowledgeSearch
from app.modules.mcp_audit import McpAuditCoordinator, McpAuditHandle
from app.shared.knowledge_tool_contracts import KNOWLEDGE_TOOL_CONTRACTS
from services.knowledge_mcp_server.auth import KnowledgeMcpAuth
from services.knowledge_mcp_server.errors import failure, safe_failure
from services.knowledge_mcp_server.execution import CallControl

MAX_RESPONSE_BYTES = 256 * 1024


class KnowledgeMcpTools:
    def __init__(
        self,
        auth: KnowledgeMcpAuth,
        directory: KnowledgeDirectory,
        search: KnowledgeSearch,
        audit: McpAuditCoordinator,
    ) -> None:
        self.auth, self.directory, self.search, self.audit = auth, directory, search, audit

    def list_tools(
        self, *, token: str, headers: Mapping[str, str], control: CallControl
    ) -> list[str]:
        # Gate 已要求目录/搜索/详情成套授权；同时验证两项完整 scope。
        for name in KNOWLEDGE_TOOL_CONTRACTS:
            control.check()
            self.auth.resolve(token, name, headers)
        control.check()
        return list(KNOWLEDGE_TOOL_CONTRACTS)

    def invoke(
        self,
        *,
        name: str,
        token: str,
        arguments: Any,
        headers: Mapping[str, str],
        control: CallControl,
    ) -> tuple[dict[str, Any], McpAuditHandle]:
        control.check()
        if name not in KNOWLEDGE_TOOL_CONTRACTS:
            raise failure("knowledge_mcp_tool_not_found")
        context = self.auth.resolve(token, name, headers)
        handle = self.audit.begin(context, business_request={"tool": name})
        started = time.monotonic()
        try:
            with self.auth.budget(context.job_id, control).activate():
                contract = KNOWLEDGE_TOOL_CONTRACTS[name]
                if not Draft202012Validator(contract.input_schema).is_valid(arguments):
                    raise failure("knowledge_mcp_input_invalid")
                result = (
                    self.directory.list_bases(token=token, arguments=arguments)
                    if name == "knowledge_list_bases"
                    else self.search.search(token=token, arguments=arguments)
                )
                if not Draft202012Validator(contract.output_schema).is_valid(result):
                    raise failure("knowledge_mcp_result_invalid")
                encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
                if len(encoded) > MAX_RESPONSE_BYTES:
                    raise failure("knowledge_mcp_result_invalid")
                control.check()
                self.auth.resolve(token, name, headers)
            # 不保存 query、cursor、库名称、命中/拒绝 ID 或正文，只记录授权后版本与计数。
            summary = (
                {"returned": len(result["items"]), "has_more": result["has_more"]}
                if name == "knowledge_list_bases"
                else {
                    key: result[key]
                    for key in ("knowledge_base_id", "resource_revision_id", "index_id", "partial")
                }
                | {"returned": len(result["documents"])}
            )
            control.check()
            self.audit.complete(
                handle,
                status="SUCCEEDED",
                business_response=summary,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            control.check()
            return result, handle
        except Exception as exc:
            error = safe_failure(exc)
            setattr(error, "mcp_audit_handle", handle)
            try:
                self.audit.complete(
                    handle,
                    status="FAILED",
                    business_response={"error_code": error.error_code},
                    error_code=error.error_code,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            except Exception:
                error = failure("knowledge_mcp_unavailable")
                setattr(error, "mcp_audit_handle", handle)
            raise error from None
