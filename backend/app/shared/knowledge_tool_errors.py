"""Knowledge tool failure projection: fixed codes and schema fields, never input values."""

import json
from itertools import islice
from typing import Any

from jsonschema import Draft202012Validator

from app.modules.knowledge.domain.code_operation_errors import CODE_OPERATION_MESSAGES
from app.shared.knowledge_tool_contracts import KNOWLEDGE_TOOL_CONTRACTS


MESSAGES = {
    **CODE_OPERATION_MESSAGES,
    "knowledge_tool_failed": "知识工具执行失败，未取得可核实结果；请检查服务状态",
    "knowledge_input_invalid": "知识工具参数不符合合同，请按 input_issues 修正字段后重试",
    "knowledge_mcp_input_invalid": "知识服务请求格式无效，请检查工具参数",
    "knowledge_job_denied": "当前任务未获准使用该知识工具或资源",
    "knowledge_resource_unavailable": "知识资源尚未发布或已停用",
    "knowledge_authorization_changed": "知识库授权已变化，不能继续本次操作",
    "knowledge_mcp_authentication_failed": "知识服务身份校验失败",
    "knowledge_mcp_context_invalid": "知识服务执行上下文不匹配",
    "knowledge_mcp_result_invalid": "知识服务返回结果未通过校验",
    "knowledge_mcp_unavailable": "知识服务暂时不可用；保存结果可能未确认，重试须保持原请求标识和内容",
    "knowledge_mcp_busy": "知识服务繁忙，请在原任务预算内重试",
    "knowledge_search_budget_exhausted": "知识查询或当前任务预算已耗尽",
    "knowledge_principal_refresh_failed": "知识服务身份续期失败",
    "knowledge_search_dependency_failed": "知识检索依赖服务异常",
    "knowledge_readability_failed": "知识来源可读性核验失败",
    "runtime_timeout": "当前任务执行预算已耗尽",
    "runtime_cancelled": "当前任务已取消",
    "CODE_ANSWER_INVALID": "答案结构无效，请检查标题、正文、条件和支持状态",
    "CODE_CLAIM_INVALID": "结论结构无效，每条需提供唯一 claim_id、conclusion、conditions 和 evidence_ids",
    "CODE_EVIDENCE_UNVERIFIED": "答案引用了未通过本任务核验的证据，不得编造或复用其他任务证据",
    "CODE_FILE_EVIDENCE_REQUIRED": "每条确定结论至少需要一条本任务实际 Read 的源码证据",
    "CODE_EVIDENCE_SCOPE_MISMATCH": "证据与当前 SVN 版本或授权范围不一致",
    "CODE_ANSWER_IDENTITY_MISMATCH": "答案身份与当前问题、条件或来源不一致",
    "CODE_REVISION_CONFLICT": "答案已被更新，请重新核验当前修订，不能盲目覆盖",
    "CODE_SOURCE_GRANT_DENIED": "源码读取授权校验失败，不能保存本次结论",
    "CODE_GRANT_REQUEST_INVALID": "源码读取授权请求无效",
}
TRANSIENT = frozenset(
    {"knowledge_mcp_unavailable", "knowledge_mcp_busy", "knowledge_search_dependency_failed"}
)
RULES = frozenset(
    {
        "required",
        "type",
        "enum",
        "const",
        "additionalProperties",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minimum",
        "maximum",
        "oneOf",
        "anyOf",
        "not",
        "allOf",
    }
)


def knowledge_failure(code: object) -> dict[str, str]:
    safe = code if isinstance(code, str) and code in MESSAGES else "knowledge_tool_failed"
    return {
        "code": safe,
        "retry_class": "TRANSIENT" if safe in TRANSIENT else "NEVER",
        "safe_message": MESSAGES[safe],
    }


def _field_path(schema: dict[str, Any], parts: Any) -> str:
    """Stop at free-form objects; arbitrary property names must never enter diagnostics."""
    result: list[str] = []
    for part in list(parts)[:12]:
        if isinstance(part, int) and 0 <= part < 10000 and isinstance(schema.get("items"), dict):
            result.append(str(part))
            schema = schema["items"]
        elif isinstance(part, str) and part in schema.get("properties", {}):
            result.append(part)
            schema = schema["properties"][part]
        else:
            break
    return "/".join(result) or "$"


def input_issues(name: str, arguments: Any) -> list[dict[str, str]]:
    schema = KNOWLEDGE_TOOL_CONTRACTS[name].input_schema
    issues = []
    for error in islice(Draft202012Validator(schema).iter_errors(arguments), 5):
        parts = list(error.absolute_path)
        if error.validator == "required" and isinstance(error.instance, dict):
            missing = next(
                (field for field in error.schema["required"] if field not in error.instance), None
            )
            if missing is not None:
                parts.append(missing)
        issues.append(
            {
                "path": _field_path(schema, parts),
                "rule": error.validator if error.validator in RULES else "schema",
            }
        )
    return issues


def safe_issues(name: str, value: Any) -> list[dict[str, str]]:
    if name not in KNOWLEDGE_TOOL_CONTRACTS or not isinstance(value, list):
        return []
    schema = KNOWLEDGE_TOOL_CONTRACTS[name].input_schema
    result = []
    for item in value[:5]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or len(item["path"]) > 250
        ):
            continue
        parts = [int(p) if p.isascii() and p.isdigit() else p for p in item["path"].split("/")]
        if item.get("rule") in RULES | {"schema"} and _field_path(schema, parts) == item["path"]:
            result.append({"path": item["path"], "rule": item["rule"]})
    return result


def error_payload(name: str, value: Any) -> dict[str, Any]:
    """Accept SDK JSON text or MCP blocks, but retain only allowlisted failure facts."""
    if isinstance(value, list):
        value = next(
            (v.get("text") for v in value[:4] if isinstance(v, dict) and v.get("type") == "text"),
            None,
        )
    if isinstance(value, str) and len(value) <= 16000:
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            value = None
    value = value if isinstance(value, dict) else {}
    failure = knowledge_failure(value.get("error_code"))
    result: dict[str, Any] = {"error_code": failure["code"], "error": failure["safe_message"]}
    issues = safe_issues(name, value.get("input_issues"))
    if failure["code"] == "knowledge_input_invalid" and issues:
        result["input_issues"] = issues
    return result
