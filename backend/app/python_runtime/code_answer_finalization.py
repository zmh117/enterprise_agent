"""Invocation-local question binding and a single bounded save reminder."""

from typing import Any

from app.modules.knowledge.domain.code_answers import normalized_question
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError


_TERMINAL_ERRORS = frozenset(
    {
        "knowledge_job_denied",
        "knowledge_authorization_changed",
        "knowledge_principal_refresh_failed",
        "knowledge_mcp_authentication_failed",
        "knowledge_mcp_context_invalid",
        "knowledge_resource_unavailable",
        "knowledge_resource_changed",
        "knowledge_source_unavailable",
        "knowledge_source_changed",
        "knowledge_search_budget_exhausted",
        "CODE_AUTHORIZATION_CHANGED",
        "CODE_EXECUTION_ENDED",
        "CODE_READ_GRANT_EXPIRED",
        "CODE_SOURCE_GRANT_CHANGED",
        "CODE_SOURCE_GRANT_DENIED",
        "CODE_SOURCE_CAPABILITY_CHANGED",
        "CODE_CONFIGURATION_CHANGED",
        "CODE_SAVE_GRANT_INVALID",
        "runtime_timeout",
        "runtime_cancelled",
    }
)


class CodeAnswerFinalization:
    def __init__(self) -> None:
        self.searches: dict[str, dict[str, Any]] = {}
        self.analyses: dict[str, dict[str, Any]] = {}
        self.reminded = False
        self.unavailable = False
        self.answer_before_reminder = ""

    def prepare(self, name: str, arguments: dict[str, Any]) -> None:
        if name == "knowledge_svn_update":
            search = self.searches.get(arguments["search_id"])
            if search is None:
                raise CodeKnowledgeError("CODE_SUCCESSFUL_SEARCH_REQUIRED")
            if (
                any(
                    arguments[key] != search[key]
                    for key in ("environment", "knowledge_base_id", "source_id", "checkout_id")
                )
                or arguments["revision"] != search["requested_revision"]
            ):
                raise CodeKnowledgeError("CODE_SEARCH_CONTEXT_CHANGED")
        elif name == "knowledge_save_code_answer":
            search = self.analyses.get(arguments["analysis_id"])
            if search is None:
                raise CodeKnowledgeError("CODE_SUCCESSFUL_SEARCH_REQUIRED")
            if any(arguments[key] != search[key] for key in ("environment", "knowledge_base_id")):
                raise CodeKnowledgeError("CODE_ANALYSIS_MISMATCH")
            # Keep the public schema and server hash validation. The host owns this
            # field; a paraphrase supplied by the model cannot change answer identity.
            arguments["question"] = search["question"]

    def observe(self, name: str, arguments: dict[str, Any], value: dict[str, Any]) -> None:
        if name == "knowledge_search" and value.get("source_kind") == "code":
            search = {
                key: value[key]
                for key in (
                    "environment",
                    "knowledge_base_id",
                    "source_id",
                    "checkout_id",
                    "requested_revision",
                )
            }
            search["question"] = normalized_question(arguments["query"])
            identifier = value["search_id"]
            previous = self.searches.setdefault(identifier, search)
            if previous != search:
                raise CodeKnowledgeError("CODE_SEARCH_CONTEXT_CHANGED")
        elif name == "knowledge_svn_update" and value.get("state") in {
            "queued",
            "running",
            "succeeded",
        }:
            self.prepare(name, arguments)
            search = self.searches[arguments["search_id"]]
            if value["svn_revision"] != search["requested_revision"]:
                raise CodeKnowledgeError("CODE_SEARCH_CONTEXT_CHANGED")
            previous = self.analyses.setdefault(value["analysis_id"], search)
            if previous != search:
                raise CodeKnowledgeError("CODE_ANALYSIS_MISMATCH")

    def failed(self, code: str) -> None:
        if code in _TERMINAL_ERRORS:
            self.unavailable = True

    def stop(
        self, analysis_id: str | None, *, budget_available: bool, answer: str
    ) -> dict[str, Any]:
        if (
            analysis_id not in self.analyses
            or self.reminded
            or self.unavailable
            or not budget_available
            or not answer.strip()
        ):
            return {}
        self.reminded = True
        self.answer_before_reminder = answer
        return {
            "decision": "block",
            "reason": (
                "本次源码分析尚无成功的结果保存回执。请在原任务剩余预算内调用一次 "
                "knowledge_save_code_answer，然后给出业务回答。question 由宿主绑定成功检索；"
                "只使用本次实际取得的证据，关键证据不足或矛盾时保存 partial/conflicted，"
                "不能为入库改成 supported。若之前的保存因传输故障结果不明，保持原 "
                "request_key 和完整内容；参数错误仅按实际证据纠正。"
                "本次只补救一次，失败仍可给出业务回答，不声称知识已保存。"
            ),
        }
