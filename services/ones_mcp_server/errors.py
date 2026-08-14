from __future__ import annotations

from app.shared.exceptions import NonRetryableExecutionError


class OnesMcpError(NonRetryableExecutionError):
    """Stable, caller-safe ONES MCP failure."""


class OnesProviderUnauthorized(OnesMcpError):
    """The Provider rejected the currently resolved ONES Token."""


def error_code(exc: Exception) -> str:
    return str(getattr(exc, "error_code", "") or "ones_mcp_failed")[:128]


def invalid_provider_response(error_code: str) -> OnesMcpError:
    return OnesMcpError(
        "ONES Provider response did not match the fixed schema",
        safe_message="ONES 返回了无效业务数据",
        error_code=error_code,
    )
