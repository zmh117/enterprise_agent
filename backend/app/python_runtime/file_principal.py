from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from urllib.parse import urlsplit

import jwt

from app.shared.principal_token_contract import (
    FILE_PRINCIPAL_REFRESH_PATH,
    MAX_PRINCIPAL_TOKEN_BYTES,
)
from app.python_runtime.file_transfer import FileTransferBoundaryError


class FilePrincipalExchangeTransport(Protocol):
    def exchange(
        self,
        *,
        url: str,
        current_token: str,
        timeout_seconds: int,
    ) -> Mapping[str, Any]: ...


class UrllibFilePrincipalExchangeTransport:
    def exchange(
        self,
        *,
        url: str,
        current_token: str,
        timeout_seconds: int,
    ) -> Mapping[str, Any]:
        request = urllib.request.Request(
            url,
            data=b"",
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {current_token}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read(64 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            code = (
                "runtime_file_principal_refresh_denied"
                if 400 <= exc.code < 500
                else "runtime_file_principal_refresh_unavailable"
            )
            raise FileTransferBoundaryError(code, "File Principal refresh failed") from exc
        except (OSError, TimeoutError) as exc:
            raise FileTransferBoundaryError(
                "runtime_file_principal_refresh_unavailable",
                "File Principal refresh service is unavailable",
            ) from exc
        if len(payload) > 64 * 1024:
            raise FileTransferBoundaryError(
                "runtime_file_principal_refresh_response_invalid",
                "File Principal refresh response exceeded its bound",
            )
        try:
            value = json.loads(payload.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FileTransferBoundaryError(
                "runtime_file_principal_refresh_response_invalid",
                "File Principal refresh response is invalid",
            ) from exc
        if not isinstance(value, dict):
            raise FileTransferBoundaryError(
                "runtime_file_principal_refresh_response_invalid",
                "File Principal refresh response is invalid",
            )
        return value


class FilePrincipalTokenClient:
    """Invocation-local short-token cache backed by the Identity Service."""

    def __init__(
        self,
        *,
        base_url: str,
        allowed_hosts: tuple[str, ...],
        initial_token: str,
        job_id: str,
        timeout_seconds: int = 5,
        refresh_skew_seconds: int = 60,
        transport: FilePrincipalExchangeTransport | None = None,
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
            raise ValueError("File Principal refresh endpoint is invalid")
        if not 1 <= timeout_seconds <= 120:
            raise ValueError("File Principal refresh timeout is invalid")
        if not 5 <= refresh_skew_seconds < 300:
            raise ValueError("File Principal refresh skew is invalid")
        if not job_id or len(job_id) > 128:
            raise ValueError("File Principal refresh Job is invalid")
        self.url = base_url.rstrip("/") + FILE_PRINCIPAL_REFRESH_PATH
        self.job_id = job_id
        self.timeout_seconds = timeout_seconds
        self.refresh_skew_seconds = refresh_skew_seconds
        self.transport = transport or UrllibFilePrincipalExchangeTransport()
        self._now = now or time.time
        self._token = initial_token
        self._expires_at = self._token_expiry(initial_token)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._refresh_thread: threading.Thread | None = None

    def __repr__(self) -> str:
        return f"FilePrincipalTokenClient(url={self.url!r}, token=<hidden>)"

    def start(self) -> None:
        with self._lock:
            if self._refresh_thread is not None:
                return
            self._stop_event.clear()
            thread = threading.Thread(
                target=self._refresh_loop,
                name="file-principal-refresh",
                daemon=True,
            )
            self._refresh_thread = thread
            thread.start()

    def close(self) -> None:
        self._stop_event.set()
        with self._lock:
            thread = self._refresh_thread
            self._refresh_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=float(self.timeout_seconds) + 0.5)

    def access_token(self, *, force_refresh: bool = False) -> str:
        now = self._now()
        if not force_refresh and now < self._expires_at - self.refresh_skew_seconds:
            return self._token
        with self._lock:
            now = self._now()
            if not force_refresh and now < self._expires_at - self.refresh_skew_seconds:
                return self._token
            previous = self._token
            try:
                response = self.transport.exchange(
                    url=self.url,
                    current_token=previous,
                    timeout_seconds=self.timeout_seconds,
                )
                token = response.get("access_token")
                token_type = response.get("token_type")
                expires_in = response.get("expires_in")
                if (
                    not isinstance(token, str)
                    or not token
                    or len(token.encode("ascii")) > MAX_PRINCIPAL_TOKEN_BYTES
                    or token_type != "Bearer"
                    or type(expires_in) is not int
                    or not 1 <= expires_in <= 300
                ):
                    raise ValueError("File Principal refresh response is invalid")
                expires_at = self._token_expiry(token)
                if expires_at <= now + 5:
                    raise ValueError("Refreshed File Principal is already expired")
            except FileTransferBoundaryError:
                if not force_refresh and now < self._expires_at - 5:
                    return self._token
                raise
            except (UnicodeError, ValueError) as exc:
                if not force_refresh and now < self._expires_at - 5:
                    return self._token
                raise FileTransferBoundaryError(
                    "runtime_file_principal_refresh_response_invalid",
                    "File Principal refresh response is invalid",
                ) from exc
            self._token = token
            self._expires_at = expires_at
            return token

    def _refresh_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                expires_at = self._expires_at
            delay = max(0.0, expires_at - self.refresh_skew_seconds - self._now())
            if self._stop_event.wait(delay):
                return
            try:
                self.access_token(force_refresh=True)
            except FileTransferBoundaryError:
                with self._lock:
                    retry_deadline = self._expires_at - 5
                remaining = retry_deadline - self._now()
                if remaining <= 0:
                    return
                if self._stop_event.wait(min(5.0, remaining)):
                    return

    def _token_expiry(self, token: str) -> float:
        try:
            if not token or len(token.encode("ascii")) > MAX_PRINCIPAL_TOKEN_BYTES:
                raise ValueError("File Principal token size is invalid")
            claims = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_aud": False,
                    "verify_iss": False,
                },
            )
            if (
                not isinstance(claims, dict)
                or claims.get("job_id") != self.job_id
                or type(claims.get("exp")) is not int
            ):
                raise ValueError("File Principal token binding is invalid")
            return float(claims["exp"])
        except (jwt.PyJWTError, UnicodeError, ValueError, TypeError) as exc:
            raise ValueError("File Principal token is invalid") from exc
