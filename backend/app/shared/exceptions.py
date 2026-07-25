from __future__ import annotations

import re


_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")


class AppError(Exception):
    def __init__(
        self,
        message: str,
        *,
        safe_message: str | None = None,
        tool_events: list[dict[str, object]] | None = None,
        error_code: str = "",
        field_errors: list[dict[str, str]] | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.safe_message = _localized_safe_message(
            self.__class__.__name__,
            safe_message,
            message,
        )
        self.tool_events = tool_events or []
        self.error_code = error_code
        self.field_errors = [
            {
                **item,
                "message": _localized_field_message(str(item.get("message") or "")),
            }
            for item in (field_errors or [])
        ]
        self.diagnostics = diagnostics or {}


class PermissionDenied(AppError):
    pass


class ToolPolicyError(AppError):
    pass


class RetryableExecutionError(AppError):
    pass


class NonRetryableExecutionError(AppError):
    pass


class DiagnosticLoopExhausted(NonRetryableExecutionError):
    pass


class ExecutionPolicyExceeded(NonRetryableExecutionError):
    pass


class ExecutionTimeout(AppError):
    pass


class NotFound(AppError):
    pass


def _localized_safe_message(
    error_type: str,
    safe_message: str | None,
    internal_message: str,
) -> str:
    candidate = str(safe_message or "")
    if candidate and _CJK_PATTERN.search(candidate):
        return candidate
    if not safe_message and _CJK_PATTERN.search(internal_message):
        return internal_message
    fallbacks = {
        "NotFound": "未找到请求的资源",
        "PermissionDenied": "你无权执行此操作",
        "ToolPolicyError": "当前操作不符合工具安全策略",
        "ExecutionTimeout": "操作超时，请稍后重试",
        "RetryableExecutionError": "服务暂时不可用，请稍后重试",
        "DiagnosticLoopExhausted": "诊断已达到执行上限",
        "ExecutionPolicyExceeded": "Agent 执行已达到策略上限",
    }
    return fallbacks.get(error_type, "操作失败，请检查输入后重试")


def _localized_field_message(message: str) -> str:
    if _CJK_PATTERN.search(message):
        return message
    return "字段值无效"
