"""两个固定工具的适配与安全审计；不复制检索、目录或权限业务规则。"""

from collections.abc import Mapping
import json
import time
from typing import Any

from jsonschema import Draft202012Validator

from app.modules.knowledge.application.directory import KnowledgeDirectory
from app.modules.knowledge.application.search import KnowledgeSearch
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.mcp_audit import McpAuditCoordinator, McpAuditHandle
from app.shared.knowledge_tool_contracts import KNOWLEDGE_TOOL_CONTRACTS
from app.shared.io_deadline import io_cleanup
from app.modules.knowledge.application.retrieval_timing import retrieval_timing, stage
from services.knowledge_mcp_server.auth import KnowledgeMcpAuth
from services.knowledge_mcp_server.errors import failure, safe_failure
from services.knowledge_mcp_server.execution import CallControl
from services.knowledge_mcp_server.storage_credentials import storage_principal
from services.knowledge_mcp_server.principal import InflightPrincipal
from app.modules.knowledge.infrastructure.readability_client import KnowledgeReadabilityClient

MAX_RESPONSE_BYTES = 512 * 1024


class KnowledgeMcpTools:
    def __init__(
        self,
        auth: KnowledgeMcpAuth,
        directory: KnowledgeDirectory,
        search: KnowledgeSearch,
        audit: McpAuditCoordinator,
        principal_client: KnowledgeReadabilityClient,
    ) -> None:
        self.auth, self.directory, self.search, self.audit = auth, directory, search, audit
        self.principal_client = principal_client

    def list_tools(
        self, *, token: str, headers: Mapping[str, str], control: CallControl
    ) -> list[str]:
        # Gate 已要求目录/搜索成套授权；同时验证两项完整 scope。
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
        with retrieval_timing(control.timing):
            return self._invoke(
                name=name, token=token, arguments=arguments, headers=headers, control=control
            )

    def _invoke(
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
        with stage("access_check"):
            context = self.auth.resolve(token, name, headers)
        handle = self.audit.begin(context, business_request={"tool": name})
        started = time.monotonic()
        principal = InflightPrincipal(token, name, self.auth.access, self.principal_client, control)
        try:
            with (
                self.auth.budget(context.job_id, control).activate(),
                principal,
                storage_principal(principal.current),
            ):
                contract = KNOWLEDGE_TOOL_CONTRACTS[name]
                if not Draft202012Validator(contract.input_schema).is_valid(arguments):
                    raise failure("knowledge_mcp_input_invalid")
                result = (
                    self.directory.list_bases(token=principal.current, arguments=arguments)
                    if name == "knowledge_list_bases"
                    else self.search.search(token=principal.current, arguments=arguments)
                )
                if not Draft202012Validator(contract.output_schema).is_valid(result):
                    raise failure("knowledge_mcp_result_invalid")
                encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
                if len(encoded) > MAX_RESPONSE_BYTES:
                    raise failure("knowledge_mcp_result_invalid")
                control.check()
                self.auth.resolve(principal.current, name, headers)
            # 不保存 query、cursor、库名称、命中/拒绝 ID 或正文，只记录授权后版本与计数。
            summary = (
                {"returned": len(result["items"]), "has_more": result["has_more"]}
                if name == "knowledge_list_bases"
                else {
                    key: result[key]
                    for key in (
                        "knowledge_base_id",
                        "resource_revision_id",
                        "index_id",
                        "partial",
                        "access_mode",
                    )
                }
                | {"returned": len(result["documents"])}
            )
            control.check()
            self.audit.complete(
                handle,
                status="SUCCEEDED",
                business_response={**summary, "retrieval_timing": control.timing.snapshot()},
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            control.check()
            return result, handle
        except Exception as exc:
            error = safe_failure(
                KnowledgeGovernanceError("knowledge_principal_refresh_failed")
                if principal.failed
                else exc
            )
            setattr(error, "mcp_audit_handle", handle)
            try:
                with io_cleanup():
                    self.audit.complete(
                        handle,
                        status="FAILED",
                        business_response={
                            "error_code": error.error_code,
                            "retrieval_timing": control.timing.snapshot(),
                        },
                        error_code=error.error_code,
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
            except Exception:
                error = failure("knowledge_mcp_unavailable")
                setattr(error, "mcp_audit_handle", handle)
            raise error from None
