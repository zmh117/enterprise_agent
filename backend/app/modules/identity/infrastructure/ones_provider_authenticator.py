from __future__ import annotations

import json
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import (
    HTTPRedirectHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
    build_opener,
)

from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError


ONES_LOGIN_PATH = "/project/api/project/auth/login"
PRODUCTION_ENVIRONMENTS = {"prod", "production"}


@dataclass(frozen=True, slots=True)
class AuthenticatedOnesSubject:
    external_user_id: str
    display_name: str
    teams: tuple[dict[str, str], ...]
    token: str


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


OpenResponse = Callable[[Request, float], Any]


class OnesProviderAuthenticator:
    """Authenticates only against a deployment-trusted Provider Instance."""

    def __init__(
        self,
        *,
        environment: str,
        timeout_seconds: int = 5,
        max_response_bytes: int = 64 * 1024,
        allow_insecure_local: bool = False,
        open_response: OpenResponse | None = None,
    ) -> None:
        self.environment = environment.strip().lower()
        self.timeout_seconds = max(1, min(int(timeout_seconds), 30))
        self.max_response_bytes = max(1024, min(int(max_response_bytes), 1024 * 1024))
        self.allow_insecure_local = allow_insecure_local
        self._open_response = open_response
        self._opener: OpenerDirector | None = None

    def authenticate(
        self,
        *,
        provider_instance: dict[str, Any],
        email: str,
        password: str,
    ) -> AuthenticatedOnesSubject:
        assert_external_io_allowed("ones_provider.authenticate")
        login_url = self._validated_login_url(provider_instance)
        request = Request(
            login_url,
            data=json.dumps(
                {"email": email.strip(), "password": password},
                ensure_ascii=False,
            ).encode(),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = self._open(request)
            with response:
                status = int(getattr(response, "status", 200))
                if status != 200:
                    raise self._status_error(status)
                raw = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            raise self._status_error(exc.code) from None
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise RetryableExecutionError(
                f"ONES authentication failed: {type(exc).__name__}",
                safe_message="ONES 身份验证暂时不可用",
                error_code="ones_connection_unavailable",
            ) from None
        finally:
            password = ""
        if len(raw) > self.max_response_bytes:
            raise self._invalid_response("response is too large")
        try:
            payload = json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise self._invalid_response("response is not valid JSON") from None
        return self._parse_subject(payload)

    def _open(self, request: Request) -> Any:
        if self._open_response is not None:
            return self._open_response(request, float(self.timeout_seconds))
        if self._opener is None:
            self._opener = build_opener(ProxyHandler({}), _NoRedirectHandler())
        return self._opener.open(request, timeout=float(self.timeout_seconds))

    def _validated_login_url(self, provider_instance: dict[str, Any]) -> str:
        if str(provider_instance.get("status") or "") != "ACTIVE":
            raise NonRetryableExecutionError(
                "Provider instance is unavailable",
                safe_message="ONES 身份验证不可用",
                error_code="provider_instance_unavailable",
            )
        base_url = str(provider_instance.get("base_url") or "").strip()
        parsed = urlparse(base_url)
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()
        allowed_hosts = {
            str(value).strip().lower()
            for value in provider_instance.get("allowed_hosts", ())
            if str(value).strip()
        }
        if (
            scheme not in {"http", "https"}
            or not hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or hostname not in allowed_hosts
        ):
            raise NonRetryableExecutionError(
                "Invalid ONES Provider Instance",
                safe_message="ONES 身份提供方配置无效",
                error_code="provider_instance_invalid",
            )
        if scheme != "https" and (
            self.environment in PRODUCTION_ENVIRONMENTS or not self.allow_insecure_local
        ):
            raise NonRetryableExecutionError(
                "ONES Provider Instance requires HTTPS",
                safe_message="ONES 身份提供方必须使用 HTTPS",
                error_code="provider_instance_invalid",
            )
        return urlunparse((scheme, parsed.netloc, ONES_LOGIN_PATH, "", "", ""))

    def _parse_subject(self, payload: object) -> AuthenticatedOnesSubject:
        if not isinstance(payload, dict):
            raise self._invalid_response("response root must be an object")
        user = payload.get("user")
        teams = payload.get("teams")
        if not isinstance(user, dict) or not isinstance(teams, list):
            raise self._invalid_response("response is missing user or teams")
        external_user_id = str(user.get("uuid") or "").strip()
        token = str(user.get("token") or "").strip()
        display_name = str(user.get("name") or "").strip() or "ONES 未返回用户名称"
        if not external_user_id or not token:
            raise self._invalid_response("response is missing user UUID or token")
        normalized_teams: list[dict[str, str]] = []
        seen: set[str] = set()
        for value in teams:
            if not isinstance(value, dict):
                raise self._invalid_response("response contains an invalid Team")
            team_id = str(value.get("uuid") or "").strip()
            if not team_id:
                raise self._invalid_response("response contains an invalid Team UUID")
            if team_id not in seen:
                seen.add(team_id)
                normalized_teams.append(
                    {"id": team_id, "name": str(value.get("name") or "").strip()}
                )
        if not normalized_teams:
            raise self._invalid_response("response contains no Team")
        return AuthenticatedOnesSubject(
            external_user_id=external_user_id,
            display_name=display_name,
            teams=tuple(normalized_teams),
            token=token,
        )

    @staticmethod
    def _status_error(status: int) -> NonRetryableExecutionError | RetryableExecutionError:
        if status in {401, 403}:
            return NonRetryableExecutionError(
                "ONES credentials were rejected",
                safe_message="ONES 邮箱或密码错误",
                error_code="ones_invalid_credentials",
            )
        if 300 <= status < 400:
            return OnesProviderAuthenticator._invalid_response("redirect was rejected")
        return RetryableExecutionError(
            f"ONES identity provider returned HTTP {status}",
            safe_message="ONES 身份验证暂时不可用",
            error_code="ones_connection_unavailable",
        )

    @staticmethod
    def _invalid_response(reason: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            f"Invalid ONES authentication response: {reason}",
            safe_message="ONES 身份提供方返回了无效响应",
            error_code="ones_response_invalid",
        )
