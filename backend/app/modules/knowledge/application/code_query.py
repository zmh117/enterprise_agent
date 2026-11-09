"""Read versioned answers or delegate controlled source operations to the API."""

from typing import Any

from app.modules.knowledge.application.code_answer_search import CodeSearchReceiptPort
from app.modules.knowledge.application.ports import PrincipalAccess, CodeHistoryPort
from app.modules.knowledge.application.principal import PrincipalToken
from app.modules.knowledge.application.resource_service import KnowledgeResourceReader
from app.modules.knowledge.application.retrieval_budget import knowledge_entry
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError, validate
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.shared.code_answer_tool_contracts import CODE_TOOL_SCHEMAS, ANSWER_FIELDS


class CodeKnowledgeQuery:
    def __init__(
        self,
        access: PrincipalAccess,
        resources: KnowledgeResourceReader,
        *,
        history: CodeHistoryPort | None = None,
        receipts: CodeSearchReceiptPort | None = None,
    ) -> None:
        self.access, self.resources = access, resources
        self.history, self.receipts = history, receipts

    @knowledge_entry
    def invoke(self, *, tool: str, token: PrincipalToken, arguments: Any) -> dict[str, Any]:
        if tool not in CODE_TOOL_SCHEMAS:
            raise CodeKnowledgeError("CODE_QUERY_TOOL_INVALID")
        validate(arguments, CODE_TOOL_SCHEMAS[tool][0])
        access = self.access.authenticate(token, tool)
        base = arguments["knowledge_base_id"]
        if base not in access.knowledge_base_ids:
            raise KnowledgeGovernanceError("knowledge_job_denied")
        budget = self.access.budget(access.job_id)
        with budget.activate():
            pin = self.resources.resolve(base)

            def check() -> None:
                budget.check()
                if self.access.authenticate(token, tool) != access:
                    raise KnowledgeGovernanceError("knowledge_authorization_changed")
                self.resources.recheck(pin)

            check()
            if tool != "knowledge_get_code_answer":
                if self.history is None:
                    raise CodeKnowledgeError("CODE_SOURCE_UNAVAILABLE")
                result = self.history.code_history(
                    token=token,
                    request={
                        "action": "tool",
                        "tool": tool,
                        "resource_revision_id": pin.revision_id,
                        "arguments": arguments,
                    },
                )
            else:
                if self.receipts is None:
                    raise CodeKnowledgeError("CODE_SUCCESSFUL_SEARCH_REQUIRED")
                receipt = self.receipts.read(arguments["search_id"], access=access, pin=pin)
                matches = [
                    m
                    for m in receipt["matches"]
                    if m["document_id"] == arguments["document_id"]
                    and m["revision_id"] == arguments["revision_id"]
                ]
                if len(matches) != 1:
                    raise CodeKnowledgeError("CODE_ANSWER_NOT_IN_SEARCH")
                config = self.resources.store.code_configuration(pin.revision_id)
                with self.resources.content_for(pin) as content:
                    if (
                        content.answers is None
                        or content.records.get("source", pin.source_id)["source_system"] != "svn"
                    ):
                        raise CodeKnowledgeError("CODE_SOURCE_UNAVAILABLE")
                    answer = content.answers.get(
                        base_id=base,
                        source_id=pin.source_id,
                        index_id=pin.index_id,
                        document_id=arguments["document_id"],
                        revision_id=arguments["revision_id"],
                        allowed_paths=config["allowed_paths_json"],
                    )
                    if answer["svn_revision"] != matches[0]["svn_revision"]:
                        raise CodeKnowledgeError("CODE_SEARCH_CONTEXT_CHANGED")
                    hint = receipt["version_mode"] == "next_higher_hint"
                    result = {
                        **{k: answer[k] for k in ANSWER_FIELDS},
                        **{k: answer[k] for k in ("body_text", "content_hash", "visibility_scope")},
                        "knowledge_base_id": base,
                        "search_id": arguments["search_id"],
                        "requested_revision": receipt["requested_revision"],
                        "matched_revision": receipt["matched_revision"],
                        "match_kind": "higher_revision_hint" if hint else "exact",
                        "requires_verification": hint,
                        "content_scope": "full_answer",
                    }
            check()
            return result
