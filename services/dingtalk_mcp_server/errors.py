from __future__ import annotations

from app.shared.exceptions import NonRetryableExecutionError


class DingTalkMcpError(NonRetryableExecutionError):
    pass


def error_code(exc: Exception) -> str:
    return str(getattr(exc, "error_code", "") or "dingtalk_mcp_denied")

