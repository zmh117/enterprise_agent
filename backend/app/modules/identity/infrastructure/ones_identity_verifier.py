from __future__ import annotations

import json
import socket
from collections.abc import Callable
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

from app.modules.identity.application.ones_identity import (
    OnesIdentityVerifier,
    VerifiedOnesIdentity,
    VerifiedOnesTeam,
)
from app.shared.config import OnesIdentitySettings
from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError

ONES_LOGIN_PATH = "/project/api/project/auth/login"
PRODUCTION_ENVIRONMENTS = {"prod", "production"}


class NoRedirectHandler(HTTPRedirectHandler):
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


class UrllibOnesIdentityVerifier(OnesIdentityVerifier):
    def __init__(
        self,
        settings: OnesIdentitySettings,
        *,
        environment: str,
        open_response: OpenResponse | None = None,
    ) -> None:
        self.settings = settings
        self.environment = environment.strip().lower()
        self._url = self._validated_login_url()
        self._opener: OpenerDirector | None = None
        self._open_response = open_response

    @property
    def available(self) -> bool:
        return bool(self._url)

    def verify(self, *, email: str, password: str) -> VerifiedOnesIdentity:
        assert_external_io_allowed("ones_identity.verify")
        if not self._url:
            raise NonRetryableExecutionError(
                "ONES identity provider is not configured",
                safe_message="ONES 身份验证不可用",
                error_code="ones_connection_unavailable",
            )
        request = Request(
            self._url,
            data=json.dumps(
                {"email": email.strip(), "password": password},
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            response = self._open(request)
            with response:
                status = int(getattr(response, "status", 200))
                if status != 200:
                    raise self._status_error(status)
                raw = response.read(self.settings.max_response_bytes + 1)
        except HTTPError as exc:
            raise self._status_error(exc.code) from None
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise RetryableExecutionError(
                f"ONES identity verification failed: {type(exc).__name__}",
                safe_message="ONES 身份验证暂时不可用",
                error_code="ones_connection_unavailable",
            ) from None
        if len(raw) > self.settings.max_response_bytes:
            raise self._invalid_response("response is too large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise self._invalid_response("response is not valid JSON") from None
        return self._parse_identity(payload)

    def _open(self, request: Request) -> Any:
        if self._open_response is not None:
            return self._open_response(request, float(self.settings.timeout_seconds))
        if self._opener is None:
            self._opener = build_opener(ProxyHandler({}), NoRedirectHandler())
        return self._opener.open(request, timeout=float(self.settings.timeout_seconds))

    def _validated_login_url(self) -> str:
        base_url = self.settings.base_url.strip()
        if not base_url:
            return ""
        parsed = urlparse(base_url)
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()
        if (
            scheme not in {"http", "https"}
            or not hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise NonRetryableExecutionError(
                "Invalid ONES identity base URL",
                safe_message="ONES 身份提供方配置无效",
                error_code="ones_configuration_invalid",
            )
        allowed_hosts = {host.strip().lower() for host in self.settings.allowed_hosts if host.strip()}
        if not allowed_hosts or hostname not in allowed_hosts:
            raise NonRetryableExecutionError(
                f"ONES identity host is not allowed: {hostname}",
                safe_message="不允许使用此 ONES 身份提供方主机",
                error_code="ones_configuration_invalid",
            )
        if scheme != "https" and (
            self.environment in PRODUCTION_ENVIRONMENTS
            or not self.settings.allow_insecure_local
        ):
            raise NonRetryableExecutionError(
                "ONES identity provider requires HTTPS",
                safe_message="ONES 身份提供方必须使用 HTTPS",
                error_code="ones_configuration_invalid",
            )
        return urlunparse(
            (
                scheme,
                parsed.netloc,
                ONES_LOGIN_PATH,
                "",
                "",
                "",
            )
        )

    def _parse_identity(self, payload: object) -> VerifiedOnesIdentity:
        if not isinstance(payload, dict):
            raise self._invalid_response("response root must be an object")
        user = payload.get("user")
        teams = payload.get("teams")
        if not isinstance(user, dict) or not isinstance(teams, list):
            raise self._invalid_response("response is missing user or teams")
        user_uuid = user.get("uuid")
        display_name = user.get("name")
        if (
            not isinstance(user_uuid, str)
            or not user_uuid.strip()
            or not isinstance(display_name, str)
        ):
            raise self._invalid_response("response contains an invalid user")
        normalized_teams: list[VerifiedOnesTeam] = []
        seen_team_ids: set[str] = set()
        for team in teams:
            if not isinstance(team, dict):
                raise self._invalid_response("response contains an invalid team")
            team_uuid = team.get("uuid")
            if not isinstance(team_uuid, str) or not team_uuid.strip():
                raise self._invalid_response("response contains an invalid team UUID")
            normalized_team_id = team_uuid.strip()
            if normalized_team_id not in seen_team_ids:
                seen_team_ids.add(normalized_team_id)
                normalized_teams.append(
                    VerifiedOnesTeam(
                        id=normalized_team_id,
                        name=str(team.get("name") or "").strip(),
                    )
                )
        if not normalized_teams:
            raise self._invalid_response("response contains no team")
        return VerifiedOnesIdentity.create(
            user_uuid=user_uuid.strip(),
            display_name=display_name.strip(),
            teams=tuple(normalized_teams),
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
            return NonRetryableExecutionError(
                "ONES identity provider redirect was rejected",
                safe_message="ONES 身份提供方返回了无效响应",
                error_code="ones_response_invalid",
            )
        return RetryableExecutionError(
            f"ONES identity provider returned HTTP {status}",
            safe_message="ONES 身份验证暂时不可用",
            error_code="ones_connection_unavailable",
        )

    @staticmethod
    def _invalid_response(reason: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            f"Invalid ONES identity response: {reason}",
            safe_message="ONES 身份提供方返回了无效响应",
            error_code="ones_response_invalid",
        )
