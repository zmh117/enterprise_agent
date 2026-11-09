"""知识工具依赖，不决定聊天模型的数据出口。"""

from collections.abc import Iterable
from typing import Any

BASE_KNOWLEDGE_TOOL_IDS = frozenset({"knowledge_list_bases", "knowledge_search"})
CODE_KNOWLEDGE_TOOL_IDS = frozenset(
    {
        "knowledge_get_code_answer",
        "knowledge_svn_update",
        "knowledge_svn_info",
        "knowledge_svn_log",
        "knowledge_svn_diff",
        "knowledge_svn_blame",
        "knowledge_get_source_operation",
        "knowledge_save_code_answer",
    }
)
KNOWLEDGE_TOOL_IDS = BASE_KNOWLEDGE_TOOL_IDS | CODE_KNOWLEDGE_TOOL_IDS


def uses_knowledge_tools(tools: Iterable[Any]) -> bool:
    return any(
        (
            tool.get("server_code") == "knowledge-mcp"
            or tool.get("tool_identifier") in KNOWLEDGE_TOOL_IDS
        )
        if isinstance(tool, dict)
        else tool in KNOWLEDGE_TOOL_IDS
        for tool in tools
    )


def knowledge_tool_dependency_errors(tools: Iterable[Any]) -> list[dict[str, str]]:
    names = {tool.get("tool_identifier") if isinstance(tool, dict) else tool for tool in tools}
    if names & KNOWLEDGE_TOOL_IDS and not BASE_KNOWLEDGE_TOOL_IDS <= names:
        return [{"field": "mcp_tools", "message": "知识库目录与知识检索工具必须同时选择"}]
    if names & CODE_KNOWLEDGE_TOOL_IDS and not CODE_KNOWLEDGE_TOOL_IDS <= names:
        return [{"field": "mcp_tools", "message": "代码答案、SVN 核验与保存工具必须成组选择"}]
    return []
