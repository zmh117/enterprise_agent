from __future__ import annotations

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
    }
    return OnesMcpError(
        "ONES Provider response did not match the fixed schema",
        safe_message=messages.get(error_code, "ONES 返回了无效业务数据"),
        error_code=error_code,
    )
