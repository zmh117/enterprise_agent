"""固定知识工具的适配与安全审计；不复制检索、目录或权限业务规则。"""

from collections.abc import Mapping
import json
import time
from typing import Any

from jsonschema import Draft202012Validator

from app.modules.knowledge.application.directory import KnowledgeDirectory
from app.modules.knowledge.application.search import KnowledgeSearch
from app.modules.knowledge.application.code_query import CodeKnowledgeQuery
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.code_contracts import ID
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
        code: CodeKnowledgeQuery | None = None,
    ) -> None:
        self.auth, self.directory, self.search, self.audit = auth, directory, search, audit
        self.principal_client = principal_client
        self.code = code

    def keepalive(self, *, token: str, headers: Mapping[str, str], control: CallControl) -> None:
        """Renew only the running Job's existing identity; no business read or tool audit."""
        context = self.auth.resolve(token, "knowledge_list_bases", headers)
        with (
            self.auth.budget(context.job_id, control).activate(),
            InflightPrincipal(
                token, "knowledge_list_bases", self.auth.access, self.principal_client, control
            ) as principal,
        ):
            control.check()
            self.auth.resolve(principal.current, "knowledge_list_bases", headers)

    def list_tools(
        self, *, token: str, headers: Mapping[str, str], control: CallControl
    ) -> list[str]:
        self.auth.resolve(token, "knowledge_list_bases", headers)
        claims = self.auth.access.verifier.verify(
            token, required_scope=KNOWLEDGE_TOOL_CONTRACTS["knowledge_list_bases"].required_scope
        )
        selected = [
            name
            for name, contract in KNOWLEDGE_TOOL_CONTRACTS.items()
            if contract.required_scope in claims["scope"]
        ]
        for name in selected:
            control.check()
            self.auth.resolve(token, name, headers)
        control.check()
        return selected

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
        request_summary = {"tool": name}
        if (
            name == "knowledge_save_code_answer"
            and isinstance(arguments, dict)
            and Draft202012Validator(ID).is_valid(arguments.get("analysis_id"))
        ):
            request_summary["analysis_id"] = arguments["analysis_id"]
        handle = self.audit.begin(context, business_request=request_summary)
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
                if name == "knowledge_list_bases":
                    result = self.directory.list_bases(token=principal.current, arguments=arguments)
                elif name == "knowledge_search":
                    result = self.search.search(
                        token=principal.current, arguments=arguments, search_id=handle.root_audit_id
                    )
                elif self.code is not None:
                    result = self.code.invoke(
                        tool=name, token=principal.current, arguments=arguments
                    )
                else:
                    raise failure("knowledge_mcp_unavailable")
                # Host-only receipt metadata never enters the model-facing result.
                receipt = result.pop("_code_receipt", None)
                if receipt is not None and (
                    name != "knowledge_search" or receipt.get("search_id") != handle.root_audit_id
                ):
                    raise failure("knowledge_mcp_result_invalid")
                if not Draft202012Validator(contract.output_schema).is_valid(result):
                    raise failure("knowledge_mcp_result_invalid")
                encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
                if len(encoded) > MAX_RESPONSE_BYTES:
                    raise failure("knowledge_mcp_result_invalid")
                control.check()
                self.auth.resolve(principal.current, name, headers)
            summary = self._summary(name, result, receipt)
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

    @staticmethod
    def _summary(name: str, result: dict[str, Any], receipt: Any) -> dict[str, Any]:
        # No query/source/diff text in the ordinary tool audit.
        if name == "knowledge_list_bases":
            return {"returned": len(result["items"]), "has_more": result["has_more"]}
        if name == "knowledge_search":
            summary = {
                key: result[key]
                for key in (
                    "knowledge_base_id",
                    "resource_revision_id",
                    "index_id",
                    "partial",
                    "access_mode",
                )
            } | {"returned": len(result["documents"])}
            if receipt is not None:
                summary["code_search"] = receipt
            return summary
        if name == "knowledge_get_code_answer":
            return {
                "code_answer_read": {
                    key: result[key]
                    for key in (
                        "knowledge_base_id",
                        "environment_id",
                        "source_id",
                        "document_id",
                        "revision_id",
                        "requested_revision",
                        "matched_revision",
                        "match_kind",
                        "requires_verification",
                    )
                }
            }
        return {
            key: result[key]
            for key in (
                "analysis_id",
                "operation_id",
                "operation_kind",
                "state",
                "error_code",
                "svn_revision",
                "support_status",
                "saved",
            )
            if key in result
        }
