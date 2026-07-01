from __future__ import annotations


class AppError(Exception):
    def __init__(
        self,
        message: str,
        *,
        safe_message: str | None = None,
        tool_events: list[dict[str, object]] | None = None,
        error_code: str = "",
    ) -> None:
        super().__init__(message)
        self.safe_message = safe_message or message
        self.tool_events = tool_events or []
        self.error_code = error_code


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


class ExecutionTimeout(AppError):
    pass


class NotFound(AppError):
    pass
