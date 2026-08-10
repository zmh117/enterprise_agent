from __future__ import annotations

import secrets
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import jwt


RUNTIME_TOOL_MCP_AUDIENCE = "runtime-tool-mcp"
_ISSUER = "enterprise-agent-worker"
_AUTHORIZED_PARTY = "agent-worker"
_MAX_TOKEN_SECONDS = 15 * 60
_MIN_KEY_BYTES = 32
_MAX_BINDINGS = 64
_BINDING_KEYS = {
    "tool_name",
    "required_scope",
    "tool_schema_hash",
    "resource_code",
    "resource_deployment_id",
    "resource_revision_id",
}


class RuntimeToolTokenError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load_runtime_tool_signing_key(path: str) -> bytes:
    configured = path.strip()
    if not configured:
        raise RuntimeToolTokenError(
            "runtime_tool_signing_key_missing",
            "Runtime Tool MCP signing key file is required",
        )
    key_path = Path(configured)
    try:
        size = key_path.stat().st_size
        key = key_path.read_bytes().rstrip(b"\r\n")
    except OSError as exc:
        raise RuntimeToolTokenError(
            "runtime_tool_signing_key_unreadable",
            "Runtime Tool MCP signing key file is unreadable",
        ) from exc
    if size > 4096 or len(key) < _MIN_KEY_BYTES:
        raise RuntimeToolTokenError(
            "runtime_tool_signing_key_invalid",
            "Runtime Tool MCP signing key has an invalid size",
        )
    return key


class RuntimeToolTokenIssuer:
    def __init__(self, key: bytes, *, now: Any | None = None) -> None:
        if len(key) < _MIN_KEY_BYTES:
            raise ValueError("Runtime Tool MCP signing key must contain at least 32 bytes")
        self._key = key
        self._now = now or (lambda: int(time.time()))

    @classmethod
    def from_file(cls, path: str) -> RuntimeToolTokenIssuer:
        return cls(load_runtime_tool_signing_key(path))

    def issue(
        self,
        *,
        app_user_id: str,
        job_id: str,
        application_publication_id: str,
        project_code: str,
        scopes: Iterable[str],
        job_timeout_seconds: int,
        tool_bindings: Iterable[dict[str, Any]] = (),
    ) -> str:
        issued_at = int(self._now())
        ordered_scopes = tuple(dict.fromkeys(str(scope) for scope in scopes if str(scope)))
        if not ordered_scopes or any(len(scope) > 160 for scope in ordered_scopes):
            raise RuntimeToolTokenError(
                "runtime_tool_scope_invalid",
                "Runtime Tool MCP scopes are missing or invalid",
            )
        normalized_bindings = _normalize_tool_bindings(
            tool_bindings,
            allowed_scopes=frozenset(ordered_scopes),
        )
        ttl_seconds = min(max(1, int(job_timeout_seconds) + 60), _MAX_TOKEN_SECONDS)
        claims = {
            "iss": _ISSUER,
            "aud": RUNTIME_TOOL_MCP_AUDIENCE,
            "azp": _AUTHORIZED_PARTY,
            "sub": app_user_id,
            "job_id": job_id,
            "application_publication_id": application_publication_id,
            "project_code": project_code,
            "scopes": ordered_scopes,
            "tool_bindings": normalized_bindings,
            "iat": issued_at,
            "nbf": issued_at - 1,
            "exp": issued_at + ttl_seconds,
            "jti": secrets.token_urlsafe(24),
        }
        return str(jwt.encode(claims, self._key, algorithm="HS256"))


class RuntimeToolTokenVerifier:
    def __init__(self, key: bytes) -> None:
        if len(key) < _MIN_KEY_BYTES:
            raise ValueError("Runtime Tool MCP signing key must contain at least 32 bytes")
        self._key = key

    @classmethod
    def from_file(cls, path: str) -> RuntimeToolTokenVerifier:
        return cls(load_runtime_tool_signing_key(path))

    def verify(
        self,
        token: str,
        *,
        required_scope: str | None = None,
        tool_name: str = "",
        tool_schema_hash: str = "",
    ) -> dict[str, Any]:
        if not token or len(token) > 8192:
            raise RuntimeToolTokenError(
                "runtime_tool_token_invalid",
                "Runtime Tool MCP token is missing or invalid",
            )
        try:
            payload = jwt.decode(
                token,
                self._key,
                algorithms=["HS256"],
                audience=RUNTIME_TOOL_MCP_AUDIENCE,
                issuer=_ISSUER,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "azp",
                        "sub",
                        "job_id",
                        "application_publication_id",
                        "project_code",
                        "scopes",
                        "tool_bindings",
                        "iat",
                        "exp",
                        "jti",
                    ]
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise RuntimeToolTokenError(
                "runtime_tool_token_expired",
                "Runtime Tool MCP token is expired",
            ) from exc
        except (jwt.PyJWTError, TypeError, ValueError) as exc:
            raise RuntimeToolTokenError(
                "runtime_tool_token_invalid",
                "Runtime Tool MCP token is invalid",
            ) from exc
        if payload.get("azp") != _AUTHORIZED_PARTY:
            raise RuntimeToolTokenError(
                "runtime_tool_token_invalid",
                "Runtime Tool MCP token authorized party is invalid",
            )
        scopes = tuple(str(scope) for scope in payload.get("scopes") or ())
        if required_scope and required_scope not in scopes:
            raise RuntimeToolTokenError(
                "runtime_tool_scope_denied",
                "Runtime Tool MCP token scope is insufficient",
            )
        bindings = _normalize_tool_bindings(
            payload.get("tool_bindings") or (),
            allowed_scopes=frozenset(scopes),
        )
        if tool_name:
            if not required_scope or len(tool_schema_hash) != 64:
                raise RuntimeToolTokenError(
                    "runtime_tool_binding_invalid",
                    "Runtime Tool MCP binding check is incomplete",
                )
            matches = [
                binding
                for binding in bindings
                if binding["tool_name"] == tool_name
                and binding["required_scope"] == required_scope
                and binding["tool_schema_hash"] == tool_schema_hash
            ]
            if len(matches) != 1:
                raise RuntimeToolTokenError(
                    "runtime_tool_binding_denied",
                    "Runtime Tool MCP token does not bind this Tool schema",
                )
        if int(payload["exp"]) - int(payload["iat"]) > _MAX_TOKEN_SECONDS:
            raise RuntimeToolTokenError(
                "runtime_tool_token_invalid",
                "Runtime Tool MCP token lifetime exceeds policy",
            )
        return dict(payload)


def _normalize_tool_bindings(
    values: Iterable[dict[str, Any]],
    *,
    allowed_scopes: frozenset[str],
) -> tuple[dict[str, str], ...]:
    bindings = tuple(values)
    if len(bindings) > _MAX_BINDINGS:
        raise RuntimeToolTokenError(
            "runtime_tool_binding_invalid",
            "Runtime Tool MCP token contains too many Tool bindings",
        )
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in bindings:
        if not isinstance(value, dict) or not set(value).issubset(_BINDING_KEYS):
            raise RuntimeToolTokenError(
                "runtime_tool_binding_invalid",
                "Runtime Tool MCP token contains an invalid Tool binding",
            )
        required = {
            "tool_name": str(value.get("tool_name") or ""),
            "required_scope": str(value.get("required_scope") or ""),
            "tool_schema_hash": str(value.get("tool_schema_hash") or ""),
        }
        if (
            not required["tool_name"]
            or len(required["tool_name"]) > 128
            or required["tool_name"] in seen
            or required["required_scope"] not in allowed_scopes
            or len(required["tool_schema_hash"]) != 64
            or any(character not in "0123456789abcdef" for character in required["tool_schema_hash"])
        ):
            raise RuntimeToolTokenError(
                "runtime_tool_binding_invalid",
                "Runtime Tool MCP token contains an invalid Tool binding",
            )
        seen.add(required["tool_name"])
        for field in (
            "resource_code",
            "resource_deployment_id",
            "resource_revision_id",
        ):
            item = str(value.get(field) or "")
            if len(item) > 128:
                raise RuntimeToolTokenError(
                    "runtime_tool_binding_invalid",
                    "Runtime Tool MCP token contains an invalid Resource binding",
                )
            if item:
                required[field] = item
        normalized.append(required)
    return tuple(normalized)
