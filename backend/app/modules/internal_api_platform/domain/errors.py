from __future__ import annotations


class PlatformError(Exception):
    """Base platform error carrying an HTTP status, machine code, and retry hint."""

    status_code: int = 400
    code: str = "platform_error"
    retryable: bool = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    @property
    def body(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": self.code, "message": self.message}}


class ResolutionError(PlatformError):
    """Requested environment/base/workshop/resource does not exist in topology."""

    status_code = 404
    code = "target_not_resolvable"
    retryable = False


class AuthorizationError(PlatformError):
    """Caller is not allowed to access the requested target."""

    status_code = 403
    code = "access_denied"
    retryable = False


class PolicyViolation(PlatformError):
    """Request violates a read-only, table-prefix, or namespace policy."""

    status_code = 400
    code = "policy_violation"
    retryable = False


class UpstreamUnavailable(PlatformError):
    """Upstream data source failed transiently and the request may be retried."""

    status_code = 503
    code = "upstream_unavailable"
    retryable = True
