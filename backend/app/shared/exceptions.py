from __future__ import annotations


class AppError(Exception):
    def __init__(self, message: str, *, safe_message: str | None = None) -> None:
        super().__init__(message)
        self.safe_message = safe_message or message


class PermissionDenied(AppError):
    pass


class ToolPolicyError(AppError):
    pass


class RetryableExecutionError(AppError):
    pass


class NonRetryableExecutionError(AppError):
    pass


class ExecutionTimeout(AppError):
    pass


class NotFound(AppError):
    pass
