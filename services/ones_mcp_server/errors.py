from __future__ import annotations

import re

from app.shared.exceptions import NonRetryableExecutionError


class OnesMcpError(NonRetryableExecutionError):
    """Stable, caller-safe ONES MCP failure."""


class OnesProviderUnauthorized(OnesMcpError):
    """The Provider rejected the currently resolved ONES Token."""


def error_code(exc: Exception) -> str:
    return str(getattr(exc, "error_code", "") or "ones_mcp_failed")[:128]


def invalid_provider_response(error_code: str) -> OnesMcpError:
    messages = {
        "ones_pagination_unstable": "ONES 分页期间数据发生变化或返回重复页，请重新查询",
        "ones_pagination_cursor_missing": "ONES 返回了后续页标记，但缺少有效游标或当前页为空",
        "ones_collection_size_exceeded": "ONES 查询结果超过临时文件大小上限，请缩小查询范围",
        "ones_collection_page_limit": "ONES 自动翻页达到请求次数上限，请缩小查询范围",
        "ones_provider_page_size_invalid": "ONES 返回条数与请求页大小不一致，已停止查询以避免漏数据",
        "ones_provider_graphql_error": "ONES GraphQL 返回查询错误，未采用可能不完整的数据",
    }
    return OnesMcpError(
        "ONES Provider response did not match the fixed schema",
        safe_message=messages.get(error_code, "ONES 返回了无效业务数据"),
        error_code=error_code,
    )


def invalid_provider_field(path: str, expected: str, value: object) -> OnesMcpError:
    """Only code-owned paths/constraints and value shapes may enter diagnostics."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.\[\]]{0,199}", path):
        path = "response"
    if value is None:
        actual = "null或缺失"
    elif isinstance(value, str):
        actual = f"字符串（长度{len(value)}）"
    elif type(value) is bool:
        actual = "布尔值"
    elif type(value) is int:
        actual = "整数"
    elif isinstance(value, float):
        actual = "浮点数"
    elif isinstance(value, list):
        actual = f"数组（{len(value)}项）"
    elif isinstance(value, dict):
        actual = "对象"
    else:
        actual = "不支持的类型"
    return OnesMcpError(
        "ONES Provider field did not match the fixed schema",
        safe_message=f"ONES 响应字段 {path} 无效：期望{expected}，实际为{actual}",
        error_code="ones_provider_schema_invalid",
    )
