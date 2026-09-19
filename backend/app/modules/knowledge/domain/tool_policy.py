"""知识工具依赖，不决定聊天模型的数据出口。"""

from collections.abc import Iterable
from typing import Any

KNOWLEDGE_TOOL_IDS = frozenset({"knowledge_list_bases", "knowledge_search"})


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
    if "knowledge_search" in names and "ones_get_work_item_detail" not in names:
        return [{"field": "mcp_tools", "message": "知识检索必须同时选择 ONES 工作项详情工具"}]
    return []
