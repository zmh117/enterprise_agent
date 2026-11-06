"""Credential-file exchange client shared by isolated services; no control-plane imports."""

from __future__ import annotations

import json
import stat
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError
from app.shared.principal_token_contract import MAX_PRINCIPAL_TOKEN_BYTES

MAX_SERVICE_PRINCIPAL_TTL_SECONDS = 300
SERVICE_PRINCIPAL_TOKEN_PATH = "/api/internal/service-principal/token"


class ServicePrincipalTokenError(NonRetryableExecutionError):
    """Fail-closed service identity error without credential disclosure."""


class AccessTokenProvider(Protocol):
    def access_token(self) -> str: ...


def _read_bootstrap_credential(path: str, *, label: str) -> str:
    configured = path.strip()
    if not configured:
        raise ValueError(f"{label} file is required")
    file_path = Path(configured)
    try:
        metadata = file_path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{label} file must be a regular non-symlink file")
        if not 32 <= metadata.st_size <= 4096:
            raise ValueError(f"{label} file size is invalid")
        mode = stat.S_IMODE(metadata.st_mode)
        if str(file_path).startswith("/run/secrets/"):
            if mode & 0o222:
                raise ValueError(f"{label} container file must be read-only")
        elif mode & 0o077:
            raise ValueError(f"{label} file permissions must be owner-only")
        raw = file_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{label} file is unreadable") from exc
    try:
        credential = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} must be ASCII") from exc
    if credential != credential.strip() or any(character.isspace() for character in credential):
        raise ValueError(f"{label} format is invalid")
    return credential


class ServiceIdentityExchangeTransport(Protocol):
    def exchange(
        self,
        *,
        url: str,
        bootstrap_credential: str,
        timeout_seconds: float,
    ) -> Mapping[str, Any]: ...


class UrllibServiceIdentityExchangeTransport:
    def exchange(
        self,
        *,
        url: str,
        bootstrap_credential: str,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        from app.shared.ones_io_budget import has_ones_io_budget
        from app.shared.bounded_read_http import request_bytes
        from email.message import Message

        request = urllib.request.Request(
            url,
            data=b"",
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {bootstrap_credential}",
            },
        )
        try:
            if has_ones_io_budget():
                status, payload = request_bytes(
                    "POST",
                    url,
                    headers=dict(request.header_items()),
                    content=b"",
                    timeout=timeout_seconds,
                    max_bytes=64 * 1024,
                )
                if status != 200:
                    raise urllib.error.HTTPError(
                        url, status, "identity_exchange_failed", Message(), None
                    )
            else:
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    payload = response.read(64 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise ServicePrincipalTokenError(
                    "Service identity exchange was rejected",
                    safe_message="内部服务身份凭证无效",
                    error_code="service_principal_exchange_denied",
                ) from exc
            raise RetryableExecutionError(
                "Service identity exchange failed",
                safe_message="内部身份服务暂时不可用",
                error_code="service_identity_unavailable",
            ) from exc
        except (OSError, TimeoutError, ValueError) as exc:
            raise RetryableExecutionError(
                "Service identity exchange failed",
                safe_message="内部身份服务暂时不可用",
                error_code="service_identity_unavailable",
            ) from exc
        if len(payload) > 64 * 1024:
            raise RetryableExecutionError(
                "Service identity response exceeded its bound",
                safe_message="内部身份服务响应无效",
                error_code="service_identity_response_invalid",
            )
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RetryableExecutionError(
                "Service identity response is invalid",
                safe_message="内部身份服务响应无效",
                error_code="service_identity_response_invalid",
            ) from exc
        if not isinstance(value, dict):
            raise RetryableExecutionError(
                "Service identity response is invalid",
                safe_message="内部身份服务响应无效",
                error_code="service_identity_response_invalid",
            )
        return value


class ServicePrincipalTokenClient:
    """Role-local bootstrap exchange with bounded short-token caching."""

    def __init__(
        self,
        *,
        base_url: str,
        allowed_hosts: tuple[str, ...],
        bootstrap_credential_file: str,
        timeout_seconds: int = 5,
        refresh_skew_seconds: int = 60,
        transport: ServiceIdentityExchangeTransport | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.hostname not in allowed_hosts
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Service identity endpoint is invalid")
        if not bootstrap_credential_file or not 1 <= timeout_seconds <= 120:
            raise ValueError("Service identity client settings are invalid")
        if not 0 <= refresh_skew_seconds < MAX_SERVICE_PRINCIPAL_TTL_SECONDS:
            raise ValueError("Service identity refresh skew is invalid")
        self.url = base_url.rstrip("/") + SERVICE_PRINCIPAL_TOKEN_PATH
        self.bootstrap_credential_file = bootstrap_credential_file
        self.timeout_seconds = timeout_seconds
        self.refresh_skew_seconds = refresh_skew_seconds
        self.transport = transport or UrllibServiceIdentityExchangeTransport()
        self._now = now or time.monotonic
        self._token = ""
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"ServicePrincipalTokenClient(url={self.url!r}, credential=<hidden>, token=<hidden>)"

    def access_token(self) -> str:
        from app.shared.ones_io_budget import ones_io_timeout

        ones_io_timeout(60)
        now = self._now()
        if self._token and now < self._expires_at - self.refresh_skew_seconds:
            return self._token
        if not self._lock.acquire(timeout=ones_io_timeout(-1)):
            ones_io_timeout(0)
            raise RetryableExecutionError(
                "Service identity refresh wait timed out",
                safe_message="内部服务身份刷新等待超时",
                error_code="service_identity_unavailable",
            )
        try:
            ones_io_timeout(60)
            now = self._now()
            if self._token and now < self._expires_at - self.refresh_skew_seconds:
                return self._token
            try:
                response = self.transport.exchange(
                    url=self.url,
                    bootstrap_credential=_read_bootstrap_credential(
                        self.bootstrap_credential_file,
                        label="Service bootstrap credential",
                    ),
                    timeout_seconds=ones_io_timeout(self.timeout_seconds),
                )
                ones_io_timeout(60)
                token = response.get("access_token")
                token_type = response.get("token_type")
                expires_in = response.get("expires_in")
                if (
                    not isinstance(token, str)
                    or not token
                    or len(token.encode("ascii")) > MAX_PRINCIPAL_TOKEN_BYTES
                    or token_type != "Bearer"
                    or type(expires_in) is not int
                    or not 1 <= expires_in <= MAX_SERVICE_PRINCIPAL_TTL_SECONDS
                ):
                    raise ValueError("Service identity token response is invalid")
            except RetryableExecutionError:
                ones_io_timeout(60)
                if self._token and self._now() < self._expires_at - 5:
                    return self._token
                raise
            except (UnicodeError, ValueError) as exc:
                raise RetryableExecutionError(
                    "Service identity response is invalid",
                    safe_message="内部身份服务响应无效",
                    error_code="service_identity_response_invalid",
                ) from exc
            self._token = token
            self._expires_at = now + expires_in
            return token
        finally:
            self._lock.release()
