from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.modules.audit.application.audit_service import AuditService
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST, McpToolDefinition
from app.shared.mcp_server_policy import (
    FILE_MCP_SERVER_CODE,
    MCP_SERVER_POLICIES,
    McpServerPolicy,
    mcp_invoke_scope,
    require_business_principal_server,
    validate_mcp_server_policies,
)
from app.shared.database import Database
from app.shared.exceptions import AppError, NonRetryableExecutionError


PRINCIPAL_ISSUER = "enterprise-agent-identity"
FILE_PRINCIPAL_AUDIENCE = FILE_MCP_SERVER_CODE
PRINCIPAL_AUTHORIZED_PARTY = "agent-runtime"
MAX_PRINCIPAL_TTL_SECONDS = 5 * 60
MAX_PRINCIPAL_TOKEN_BYTES = 8 * 1024
_AUTHORIZATION_HASH_LENGTH = 64
_ALLOWED_CLAIMS = frozenset(
    {
        "iss",
        "sub",
        "aud",
        "azp",
        "job_id",
        "session_id",
        "agent_publication_id",
        "application_publication_id",
        "scope",
        "authorization_hash",
        "jti",
        "iat",
        "nbf",
        "exp",
    }
)


class PrincipalTokenError(NonRetryableExecutionError):
    """Fail-closed Principal authentication/signing error with a stable safe surface."""


class PrincipalBusinessAuthorizationPort(Protocol):
    def require(
        self,
        *,
        user_id: str,
        application_id: str,
        tool_identifier: str,
        stage: str,
    ) -> dict[str, Any]: ...


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Principal JWK public key is invalid") from exc


def _public_jwk(public_key: Ed25519PublicKey) -> dict[str, str]:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    core = {"crv": "Ed25519", "kty": "OKP", "x": _b64url(raw)}
    thumbprint = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).digest()
    return {
        **core,
        "alg": "EdDSA",
        "use": "sig",
        "kid": _b64url(thumbprint),
    }


def _read_bounded_regular_file(path: str, *, label: str, max_bytes: int) -> tuple[Path, bytes, int]:
    configured = path.strip()
    if not configured:
        raise ValueError(f"{label} file is required")
    file_path = Path(configured)
    try:
        metadata = file_path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{label} file must be a regular non-symlink file")
        if not 32 <= metadata.st_size <= max_bytes:
            raise ValueError(f"{label} file size is invalid")
        return file_path, file_path.read_bytes(), stat.S_IMODE(metadata.st_mode)
    except OSError as exc:
        raise ValueError(f"{label} file is unreadable") from exc


class PrincipalSigningKey:
    __slots__ = ("_private_key", "_pem", "kid")

    def __init__(self, private_key: Ed25519PrivateKey, pem: bytes) -> None:
        self._private_key = private_key
        self._pem = pem
        self.kid = str(_public_jwk(private_key.public_key())["kid"])

    def __repr__(self) -> str:
        return f"PrincipalSigningKey(kid={self.kid!r}, private_key=<hidden>)"

    @classmethod
    def from_pem(cls, pem: bytes) -> PrincipalSigningKey:
        try:
            private_key = serialization.load_pem_private_key(pem, password=None)
        except (TypeError, ValueError) as exc:
            raise ValueError("Principal private key must be unencrypted PKCS8 PEM") from exc
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("Principal private key must be Ed25519")
        canonical = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        if pem.strip() != canonical.strip():
            raise ValueError("Principal private key must use canonical unencrypted PKCS8 PEM")
        return cls(private_key, canonical)

    @classmethod
    def from_file(cls, path: str, *, environment: str) -> PrincipalSigningKey:
        file_path, pem, mode = _read_bounded_regular_file(
            path,
            label="Principal private key",
            max_bytes=16 * 1024,
        )
        is_container_secret = str(file_path).startswith("/run/secrets/")
        if is_container_secret:
            if mode & 0o222:
                raise ValueError("Container Principal private key must be read-only")
        elif mode & 0o077:
            raise ValueError("Principal private key permissions must be owner-only")
        if environment not in {"local", "test", "testing"} and not path.strip():
            raise ValueError("Principal private key is required outside local test environments")
        return cls.from_pem(pem)

    def public_jwk(self) -> dict[str, str]:
        return _public_jwk(self._private_key.public_key())

    def public_jwks(self) -> dict[str, list[dict[str, str]]]:
        return {"keys": [self.public_jwk()]}

    def sign(self, claims: Mapping[str, Any]) -> str:
        return str(
            jwt.encode(
                dict(claims),
                self._pem,
                algorithm="EdDSA",
                headers={"alg": "EdDSA", "kid": self.kid, "typ": "JWT"},
            )
        )


@dataclass(frozen=True)
class PrincipalPublicKey:
    kid: str
    key: Ed25519PublicKey
    jwk: Mapping[str, str]


class PrincipalJwks:
    def __init__(self, keys: Mapping[str, PrincipalPublicKey]) -> None:
        if not keys:
            raise ValueError("Principal JWKS must contain at least one key")
        self._keys = dict(keys)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PrincipalJwks:
        if set(value) != {"keys"} or not isinstance(value.get("keys"), list):
            raise ValueError("Principal JWKS document is invalid")
        keys: dict[str, PrincipalPublicKey] = {}
        for raw in value["keys"]:
            if not isinstance(raw, dict):
                raise ValueError("Principal JWKS key is invalid")
            if "d" in raw or set(raw) != {"alg", "crv", "kid", "kty", "use", "x"}:
                raise ValueError("Principal JWKS contains private or unsupported key fields")
            if (
                raw.get("kty") != "OKP"
                or raw.get("crv") != "Ed25519"
                or raw.get("alg") != "EdDSA"
                or raw.get("use") != "sig"
            ):
                raise ValueError("Principal JWKS key type is not Ed25519 signing")
            x = str(raw.get("x") or "")
            public_bytes = _b64url_decode(x)
            if len(public_bytes) != 32:
                raise ValueError("Principal JWKS Ed25519 public key length is invalid")
            public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
            expected = _public_jwk(public_key)
            kid = str(raw.get("kid") or "")
            if kid != expected["kid"]:
                raise ValueError("Principal JWKS kid is not its RFC7638 public key fingerprint")
            if kid in keys:
                raise ValueError("Principal JWKS kid must be unique")
            keys[kid] = PrincipalPublicKey(kid=kid, key=public_key, jwk=dict(expected))
        return cls(keys)

    @classmethod
    def from_file(cls, path: str) -> PrincipalJwks:
        _, content, _ = _read_bounded_regular_file(
            path,
            label="Principal JWKS",
            max_bytes=64 * 1024,
        )
        try:
            value = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Principal JWKS must be valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("Principal JWKS document is invalid")
        return cls.from_dict(value)

    def get(self, kid: str) -> PrincipalPublicKey | None:
        return self._keys.get(kid)

    def public_projection(self) -> dict[str, list[dict[str, str]]]:
        return {
            "keys": [dict(self._keys[kid].jwk) for kid in sorted(self._keys)],
        }


class PrincipalTokenIssuer:
    def __init__(
        self,
        database: Database,
        snapshot_service: JobMcpToolSnapshotService,
        business_authorization_service: PrincipalBusinessAuthorizationPort,
        signing_key: PrincipalSigningKey,
        audit_service: AuditService,
        *,
        ttl_seconds: int = MAX_PRINCIPAL_TTL_SECONDS,
        now: Callable[[], int] | None = None,
        jti_factory: Callable[[], str] | None = None,
        server_policies: Mapping[str, McpServerPolicy] | None = None,
        tool_manifest: Mapping[str, McpToolDefinition] | None = None,
    ) -> None:
        if not 1 <= ttl_seconds <= MAX_PRINCIPAL_TTL_SECONDS:
            raise ValueError("Principal JWT TTL must be between 1 and 300 seconds")
        self.database = database
        self.snapshot_service = snapshot_service
        self.business_authorization_service = business_authorization_service
        self.signing_key = signing_key
        self.audit_service = audit_service
        self.ttl_seconds = ttl_seconds
        self._now = now or (lambda: int(time.time()))
        self._jti_factory = jti_factory or (lambda: uuid.uuid4().hex)
        self._server_policies = (
            MCP_SERVER_POLICIES if server_policies is None else dict(server_policies)
        )
        validate_mcp_server_policies(self._server_policies)
        self._tool_manifest = MCP_TOOL_MANIFEST if tool_manifest is None else dict(tool_manifest)

    def issue_business_mcp_for_job(self, *, job_id: str, server_code: str) -> str:
        audit: dict[str, Any] = {
            "kid": self.signing_key.kid,
            "job_id": job_id,
            "audience": server_code if 0 < len(server_code) <= 63 else "",
        }
        try:
            try:
                require_business_principal_server(
                    server_code,
                    policies=self._server_policies,
                )
            except ValueError as exc:
                raise PrincipalTokenError(
                    "Principal JWT requires a fixed Business MCP server",
                    safe_message="当前 MCP 服务不能签发平台身份凭证",
                    error_code="principal_server_denied",
                ) from exc
            facts = self._job_facts(job_id)
            verified = self.snapshot_service.verify(job_id)
            tool_identifiers, authorization_hash = self._business_tools(
                facts,
                verified,
                server_code=server_code,
            )
            scopes = [mcp_invoke_scope(server_code, identifier) for identifier in tool_identifiers]
            audit["scope"] = scopes
            for tool_identifier in tool_identifiers:
                self.business_authorization_service.require(
                    user_id=facts["internal_user_id"],
                    application_id=facts["business_application_id"],
                    tool_identifier=tool_identifier,
                    stage="business_principal_jwt_issue",
                )
            issued_at = self._now()
            jti = self._jti_factory()
            if not jti or len(jti) > 128:
                raise PrincipalTokenError(
                    "Principal jti factory returned an invalid value",
                    safe_message="平台身份凭证签发失败",
                    error_code="principal_token_issue_failed",
                )
            claims: dict[str, Any] = {
                "iss": PRINCIPAL_ISSUER,
                "sub": facts["internal_user_id"],
                "aud": server_code,
                "azp": PRINCIPAL_AUTHORIZED_PARTY,
                "job_id": job_id,
                "session_id": facts["session_id"],
                "agent_publication_id": facts["agent_publication_id"],
                "application_publication_id": facts["business_application_publication_id"],
                "scope": scopes,
                "authorization_hash": authorization_hash,
                "jti": jti,
                "iat": issued_at,
                "nbf": issued_at - 1,
                "exp": issued_at + self.ttl_seconds,
            }
            token = self.signing_key.sign(claims)
            audit.update(
                {
                    "jti": jti,
                    "issued_at": issued_at,
                    "not_before": issued_at - 1,
                    "expires_at": issued_at + self.ttl_seconds,
                }
            )
            self.audit_service.record(
                "principal.jwt.issued",
                status="success",
                summary="Principal JWT issued for frozen Business MCP Tools",
                job_id=job_id,
                actor_id=facts["internal_user_id"],
                payload=audit,
            )
            return token
        except Exception as exc:
            error_code = str(getattr(exc, "error_code", "") or "principal_token_issue_denied")
            audit["error_code"] = error_code
            self.audit_service.record(
                "principal.jwt.issue_denied",
                status="denied",
                summary="Principal JWT issuance denied",
                job_id=job_id or None,
                payload=audit,
            )
            if isinstance(exc, AppError):
                raise
            raise PrincipalTokenError(
                "Principal JWT issuance failed",
                safe_message="平台身份凭证签发失败",
                error_code=error_code,
            ) from exc

    def issue_file_for_job(self, *, job_id: str) -> str:
        audit: dict[str, Any] = {
            "kid": self.signing_key.kid,
            "job_id": job_id,
            "audience": FILE_PRINCIPAL_AUDIENCE,
        }
        try:
            facts = self._job_facts(job_id)
            if not facts.get("task_workspace_id") or not facts.get("workspace_tenant_id"):
                raise PrincipalTokenError(
                    "File Principal requires a Job-bound task workspace",
                    safe_message="当前任务没有可用的文件工作区",
                    error_code="file_principal_workspace_missing",
                )
            verified = self.snapshot_service.verify(job_id)
            snapshot = verified.get("snapshot")
            if not isinstance(snapshot, dict):
                raise PrincipalTokenError(
                    "File Principal MCP snapshot is invalid",
                    safe_message="当前任务工具快照无效",
                    error_code="principal_snapshot_invalid",
                )
            if (
                str(snapshot.get("job_id") or "") != facts["id"]
                or str(snapshot.get("agent_publication_id") or "") != facts["agent_publication_id"]
                or str(snapshot.get("application_publication_id") or "")
                != facts["business_application_publication_id"]
            ):
                raise PrincipalTokenError(
                    "File Principal snapshot provenance does not match Job",
                    safe_message="当前任务工具快照与发布版本不一致",
                    error_code="principal_snapshot_invalid",
                )
            file_tools = sorted(
                {
                    str(item.get("tool_identifier") or "")
                    for item in snapshot.get("tools") or []
                    if isinstance(item, dict)
                    and item.get("server_code") == FILE_PRINCIPAL_AUDIENCE
                    and item.get("tool_identifier")
                }
            )
            if not file_tools:
                raise PrincipalTokenError(
                    "Frozen Job does not grant a File MCP Tool",
                    safe_message="当前任务没有冻结文件工具权限",
                    error_code="principal_scope_denied",
                )
            scopes = [
                f"mcp:{FILE_PRINCIPAL_AUDIENCE}:{tool_identifier}:invoke"
                for tool_identifier in file_tools
            ]
            for tool_identifier in file_tools:
                self.business_authorization_service.require(
                    user_id=facts["internal_user_id"],
                    application_id=facts["business_application_id"],
                    tool_identifier=tool_identifier,
                    stage="file_principal_jwt_issue",
                )
            authorization_hash = str(verified.get("authorization_hash") or "")
            if len(authorization_hash) != _AUTHORIZATION_HASH_LENGTH or any(
                character not in "0123456789abcdef" for character in authorization_hash
            ):
                raise PrincipalTokenError(
                    "File Principal authorization hash is invalid",
                    safe_message="当前任务授权摘要无效",
                    error_code="principal_snapshot_invalid",
                )
            issued_at = self._now()
            jti = self._jti_factory()
            if not jti or len(jti) > 128:
                raise PrincipalTokenError(
                    "Principal jti factory returned an invalid value",
                    safe_message="平台身份凭证签发失败",
                    error_code="principal_token_issue_failed",
                )
            token = self.signing_key.sign(
                {
                    "iss": PRINCIPAL_ISSUER,
                    "sub": facts["internal_user_id"],
                    "aud": FILE_PRINCIPAL_AUDIENCE,
                    "azp": PRINCIPAL_AUTHORIZED_PARTY,
                    "tenant_id": facts["workspace_tenant_id"],
                    "job_id": job_id,
                    "session_id": facts["session_id"],
                    "agent_publication_id": facts["agent_publication_id"],
                    "application_publication_id": facts["business_application_publication_id"],
                    "scope": scopes,
                    "authorization_hash": authorization_hash,
                    "jti": jti,
                    "iat": issued_at,
                    "nbf": issued_at - 1,
                    "exp": issued_at + self.ttl_seconds,
                }
            )
            audit.update(
                {
                    "scope": scopes,
                    "jti": jti,
                    "issued_at": issued_at,
                    "not_before": issued_at - 1,
                    "expires_at": issued_at + self.ttl_seconds,
                }
            )
            self.audit_service.record(
                "principal.jwt.issued",
                status="success",
                summary="Principal JWT issued for frozen File MCP Tools",
                job_id=job_id,
                actor_id=facts["internal_user_id"],
                payload=audit,
            )
            return token
        except Exception as exc:
            error_code = str(getattr(exc, "error_code", "") or "file_principal_token_issue_denied")
            audit["error_code"] = error_code
            self.audit_service.record(
                "principal.jwt.issue_denied",
                status="denied",
                summary="File Principal JWT issuance denied",
                job_id=job_id or None,
                payload=audit,
            )
            if isinstance(exc, AppError):
                raise
            raise PrincipalTokenError(
                "File Principal JWT issuance failed",
                safe_message="平台文件身份凭证签发失败",
                error_code=error_code,
            ) from exc

    def _job_facts(self, job_id: str) -> dict[str, str]:
        if not job_id:
            raise PrincipalTokenError(
                "Principal Job ID is required",
                safe_message="平台身份凭证签发失败",
                error_code="principal_job_invalid",
            )
        row = self.database.execute_one(
            """
            select j.id, j.status, j.session_id, j.project_code,
                   j.internal_user_id, j.business_application_id,
                   j.agent_publication_id,
                   j.business_application_publication_id,
                   j.task_workspace_id,
                   w.tenant_id as workspace_tenant_id,
                   u.status as user_status, u.account_type as user_account_type,
                   s.application_publication_id as session_application_publication_id
              from agent_job j
              join app_user u on u.id = j.internal_user_id
              join agent_session s on s.id = j.session_id
              left join task_workspace w on w.id = j.task_workspace_id
             where j.id = ?
            """,
            (job_id,),
        )
        if row is None:
            raise PrincipalTokenError(
                "Principal Job or internal user does not exist",
                safe_message="平台身份凭证签发失败",
                error_code="principal_job_invalid",
            )
        facts = {key: str(value or "") for key, value in row.items()}
        if facts["status"] != "RUNNING":
            raise PrincipalTokenError(
                "Principal JWT requires a running Job",
                safe_message="当前任务不能签发平台身份凭证",
                error_code="principal_job_not_running",
            )
        if facts["user_status"] != "enabled" or facts["user_account_type"] != "human":
            raise PrincipalTokenError(
                "Principal JWT requires an enabled human user",
                safe_message="当前用户不能签发平台身份凭证",
                error_code="principal_user_inactive",
            )
        required = (
            "session_id",
            "project_code",
            "internal_user_id",
            "business_application_id",
            "agent_publication_id",
            "business_application_publication_id",
        )
        if any(not facts[name] for name in required):
            raise PrincipalTokenError(
                "Principal Job provenance is incomplete",
                safe_message="当前任务身份上下文不完整",
                error_code="principal_job_invalid",
            )
        if (
            facts["session_application_publication_id"]
            != facts["business_application_publication_id"]
        ):
            raise PrincipalTokenError(
                "Principal Job and session publication do not match",
                safe_message="当前任务发布上下文不一致",
                error_code="principal_publication_mismatch",
            )
        return facts

    def _business_tools(
        self,
        facts: Mapping[str, str],
        verified: Mapping[str, Any],
        *,
        server_code: str,
    ) -> tuple[list[str], str]:
        snapshot = verified.get("snapshot")
        if not isinstance(snapshot, dict):
            raise PrincipalTokenError(
                "Principal MCP snapshot is invalid",
                safe_message="当前任务工具快照无效",
                error_code="principal_snapshot_invalid",
            )
        if (
            str(snapshot.get("job_id") or "") != facts["id"]
            or str(snapshot.get("agent_publication_id") or "") != facts["agent_publication_id"]
            or str(snapshot.get("application_publication_id") or "")
            != facts["business_application_publication_id"]
        ):
            raise PrincipalTokenError(
                "Principal MCP snapshot provenance does not match Job",
                safe_message="当前任务工具快照与发布版本不一致",
                error_code="principal_snapshot_invalid",
            )
        tools = snapshot.get("tools")
        if not isinstance(tools, list):
            raise PrincipalTokenError(
                "Principal MCP snapshot tools are invalid",
                safe_message="当前任务工具快照无效",
                error_code="principal_snapshot_invalid",
            )
        identifiers: list[str] = []
        seen: set[str] = set()
        for item in tools:
            if not isinstance(item, dict) or str(item.get("server_code") or "") != server_code:
                continue
            identifier = str(item.get("tool_identifier") or "")
            definition = self._tool_manifest.get(identifier)
            if (
                not identifier
                or identifier in seen
                or definition is None
                or definition.server_code != server_code
                or definition.schema_hash != str(item.get("schema_hash") or "")
            ):
                raise PrincipalTokenError(
                    "Frozen Business MCP Tool is duplicated or has drifted",
                    safe_message="当前任务业务工具快照无效",
                    error_code="principal_snapshot_invalid",
                )
            try:
                require_business_principal_server(
                    definition.server_code,
                    policies=self._server_policies,
                )
            except ValueError as exc:
                raise PrincipalTokenError(
                    "Frozen Tool does not belong to a Business Principal MCP server",
                    safe_message="当前任务业务工具鉴权策略无效",
                    error_code="principal_server_denied",
                ) from exc
            seen.add(identifier)
            identifiers.append(identifier)
        identifiers.sort()
        if not identifiers:
            raise PrincipalTokenError(
                "Frozen Job does not grant a Business MCP Tool for this server",
                safe_message="当前任务没有冻结对应业务工具权限",
                error_code="principal_scope_denied",
            )
        authorization_hash = str(verified.get("authorization_hash") or "")
        if len(authorization_hash) != _AUTHORIZATION_HASH_LENGTH or any(
            char not in "0123456789abcdef" for char in authorization_hash
        ):
            raise PrincipalTokenError(
                "Principal authorization hash is invalid",
                safe_message="当前任务授权摘要无效",
                error_code="principal_snapshot_invalid",
            )
        return identifiers, authorization_hash


class PrincipalTokenVerifier:
    def __init__(
        self,
        jwks: PrincipalJwks,
        *,
        expected_audience: str,
        audit_service: AuditService | None = None,
        now: Callable[[], int] | None = None,
        leeway_seconds: int = 5,
        server_policies: Mapping[str, McpServerPolicy] | None = None,
        tool_manifest: Mapping[str, McpToolDefinition] | None = None,
    ) -> None:
        if not 0 <= leeway_seconds <= 30:
            raise ValueError("Principal JWT leeway is invalid")
        selected_policies = (
            MCP_SERVER_POLICIES if server_policies is None else dict(server_policies)
        )
        validate_mcp_server_policies(selected_policies)
        require_business_principal_server(
            expected_audience,
            policies=selected_policies,
        )
        self.jwks = jwks
        self.expected_audience = expected_audience
        self.audit_service = audit_service
        self._now = now or (lambda: int(time.time()))
        self.leeway_seconds = leeway_seconds
        self._server_policies = selected_policies
        self._tool_manifest = MCP_TOOL_MANIFEST if tool_manifest is None else dict(tool_manifest)

    def verify(
        self,
        token: str,
        *,
        required_scope: str,
    ) -> dict[str, Any]:
        audit = self._untrusted_audit_projection(token)
        try:
            encoded = token.encode("ascii")
            if not 1 <= len(encoded) <= MAX_PRINCIPAL_TOKEN_BYTES:
                raise PrincipalTokenError(
                    "Principal JWT size is invalid",
                    safe_message="平台身份凭证无效",
                    error_code="principal_token_invalid",
                )
            header = jwt.get_unverified_header(token)
            if set(header) != {"alg", "kid", "typ"}:
                raise PrincipalTokenError(
                    "Principal JWT header fields are invalid",
                    safe_message="平台身份凭证无效",
                    error_code="principal_token_header_invalid",
                )
            if header.get("alg") != "EdDSA" or header.get("typ") != "JWT":
                raise PrincipalTokenError(
                    "Principal JWT algorithm or type is invalid",
                    safe_message="平台身份凭证无效",
                    error_code="principal_token_algorithm_invalid",
                )
            kid = header.get("kid")
            if not isinstance(kid, str) or not kid:
                raise PrincipalTokenError(
                    "Principal JWT kid is invalid",
                    safe_message="平台身份凭证无效",
                    error_code="principal_token_kid_invalid",
                )
            public_key = self.jwks.get(kid)
            if public_key is None:
                raise PrincipalTokenError(
                    "Principal JWT kid is unknown",
                    safe_message="平台身份凭证无效",
                    error_code="principal_token_kid_unknown",
                )
            claims = jwt.decode(
                token,
                key=public_key.key,
                algorithms=["EdDSA"],
                audience=self.expected_audience,
                issuer=PRINCIPAL_ISSUER,
                leeway=self.leeway_seconds,
                options={
                    "require": sorted(_ALLOWED_CLAIMS),
                    "verify_signature": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    # PyJWT reads wall-clock time directly. Temporal checks are
                    # performed below with the injected clock so tests and
                    # services share one explicit, bounded policy.
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            self._validate_claims(claims, required_scope=required_scope)
            return claims
        except PrincipalTokenError as exc:
            self._audit_rejection(audit, exc.error_code or "principal_token_invalid")
            raise
        except (jwt.PyJWTError, UnicodeError, ValueError) as exc:
            error_code = self._jwt_error_code(exc)
            self._audit_rejection(audit, error_code)
            raise PrincipalTokenError(
                "Principal JWT validation failed",
                safe_message="平台身份凭证无效",
                error_code=error_code,
            ) from exc

    def verify_for_running_job(
        self,
        token: str,
        database: Database,
        snapshot_service: JobMcpToolSnapshotService,
        *,
        required_scope: str,
    ) -> dict[str, Any]:
        claims = self.verify(token, required_scope=required_scope)
        row = database.execute_one(
            """
            select j.internal_user_id, j.status, j.session_id,
                   j.agent_publication_id,
                   j.business_application_publication_id,
                   s.application_publication_id as session_application_publication_id,
                   u.status as user_status,
                   u.account_type as user_account_type
              from agent_job j
              join app_user u on u.id = j.internal_user_id
              join agent_session s on s.id = j.session_id
             where j.id = ?
            """,
            (claims["job_id"],),
        )
        if (
            row is None
            or str(row.get("internal_user_id") or "") != claims["sub"]
            or str(row.get("status") or "") != "RUNNING"
            or str(row.get("user_status") or "") != "enabled"
            or str(row.get("user_account_type") or "") != "human"
            or str(row.get("session_id") or "") != claims["session_id"]
            or str(row.get("agent_publication_id") or "") != claims["agent_publication_id"]
            or str(row.get("business_application_publication_id") or "")
            != claims["application_publication_id"]
            or str(row.get("session_application_publication_id") or "")
            != claims["application_publication_id"]
        ):
            error_code = "principal_job_user_mismatch"
            self._audit_rejection(
                {
                    "kid": str(jwt.get_unverified_header(token).get("kid") or ""),
                    "jti": claims["jti"],
                    "job_id": claims["job_id"],
                    "audience": claims["aud"],
                    "scope": claims["scope"],
                    "issued_at": claims["iat"],
                    "not_before": claims["nbf"],
                    "expires_at": claims["exp"],
                },
                error_code,
            )
            raise PrincipalTokenError(
                "Principal JWT does not match an enabled user's running Job",
                safe_message="平台身份凭证与当前任务不匹配",
                error_code=error_code,
            )
        try:
            verified = snapshot_service.verify(str(claims["job_id"]))
            expected_scopes, authorization_hash = self._snapshot_scopes(
                claims,
                verified,
            )
        except (AppError, ValueError) as exc:
            self._audit_rejection(
                self._claims_audit_projection(claims, token),
                str(getattr(exc, "error_code", "") or "principal_snapshot_invalid"),
            )
            raise PrincipalTokenError(
                "Principal JWT Job snapshot validation failed",
                safe_message="平台身份凭证与当前任务不匹配",
                error_code="principal_snapshot_invalid",
            ) from exc
        if claims["scope"] != expected_scopes or claims["authorization_hash"] != authorization_hash:
            error_code = "principal_token_scope_invalid"
            self._audit_rejection(
                self._claims_audit_projection(claims, token),
                error_code,
            )
            raise PrincipalTokenError(
                "Principal JWT scope or authorization hash does not match the Job snapshot",
                safe_message="平台身份凭证权限与当前任务不匹配",
                error_code=error_code,
            )
        return claims

    def _validate_claims(self, claims: Mapping[str, Any], *, required_scope: str) -> None:
        if set(claims) != _ALLOWED_CLAIMS:
            raise PrincipalTokenError(
                "Principal JWT claim fields are invalid",
                safe_message="平台身份凭证无效",
                error_code="principal_token_claims_invalid",
            )
        string_claims = (
            "iss",
            "sub",
            "aud",
            "azp",
            "job_id",
            "session_id",
            "agent_publication_id",
            "application_publication_id",
            "authorization_hash",
            "jti",
        )
        if any(
            not isinstance(claims[name], str) or not claims[name] or len(claims[name]) > 256
            for name in string_claims
        ):
            raise PrincipalTokenError(
                "Principal JWT string claim type is invalid",
                safe_message="平台身份凭证无效",
                error_code="principal_token_claims_invalid",
            )
        if claims["azp"] != PRINCIPAL_AUTHORIZED_PARTY:
            raise PrincipalTokenError(
                "Principal JWT authorized party is invalid",
                safe_message="平台身份凭证无效",
                error_code="principal_token_azp_invalid",
            )
        scope = claims["scope"]
        prefix = f"mcp:{self.expected_audience}:"
        if (
            not isinstance(scope, list)
            or not 1 <= len(scope) <= 64
            or any(
                not isinstance(item, str)
                or not item.startswith(prefix)
                or not item.endswith(":invoke")
                or len(item) > 256
                for item in scope
            )
            or scope != sorted(set(scope))
            or required_scope not in scope
        ):
            raise PrincipalTokenError(
                "Principal JWT scope is invalid or expanded",
                safe_message="平台身份凭证权限无效",
                error_code="principal_token_scope_invalid",
            )
        authorization_hash = claims["authorization_hash"]
        if len(authorization_hash) != _AUTHORIZATION_HASH_LENGTH or any(
            char not in "0123456789abcdef" for char in authorization_hash
        ):
            raise PrincipalTokenError(
                "Principal JWT authorization hash is invalid",
                safe_message="平台身份凭证无效",
                error_code="principal_token_claims_invalid",
            )
        for name in ("iat", "nbf", "exp"):
            if type(claims[name]) is not int:
                raise PrincipalTokenError(
                    "Principal JWT time claim type is invalid",
                    safe_message="平台身份凭证无效",
                    error_code="principal_token_claims_invalid",
                )
        issued_at = claims["iat"]
        not_before = claims["nbf"]
        expires_at = claims["exp"]
        now = self._now()
        if expires_at <= now - self.leeway_seconds:
            raise PrincipalTokenError(
                "Principal JWT has expired",
                safe_message="平台身份凭证已失效",
                error_code="principal_token_expired",
            )
        if issued_at > now + self.leeway_seconds or not_before > now + self.leeway_seconds:
            raise PrincipalTokenError(
                "Principal JWT is not yet valid",
                safe_message="平台身份凭证尚未生效",
                error_code="principal_token_not_yet_valid",
            )
        if (
            not_before > issued_at
            or expires_at <= issued_at
            or expires_at - issued_at > MAX_PRINCIPAL_TTL_SECONDS
        ):
            raise PrincipalTokenError(
                "Principal JWT time window is invalid",
                safe_message="平台身份凭证已失效",
                error_code="principal_token_time_invalid",
            )

    @staticmethod
    def _jwt_error_code(exc: Exception) -> str:
        if isinstance(exc, jwt.ExpiredSignatureError):
            return "principal_token_expired"
        if isinstance(exc, jwt.ImmatureSignatureError):
            return "principal_token_not_yet_valid"
        if isinstance(exc, jwt.InvalidAudienceError):
            return "principal_token_audience_invalid"
        if isinstance(exc, jwt.InvalidIssuerError):
            return "principal_token_issuer_invalid"
        if isinstance(exc, jwt.InvalidSignatureError):
            return "principal_token_signature_invalid"
        return "principal_token_invalid"

    def _snapshot_scopes(
        self,
        claims: Mapping[str, Any],
        verified: Mapping[str, Any],
    ) -> tuple[list[str], str]:
        snapshot = verified.get("snapshot")
        if not isinstance(snapshot, dict):
            raise PrincipalTokenError(
                "Principal MCP snapshot is invalid",
                safe_message="当前任务工具快照无效",
                error_code="principal_snapshot_invalid",
            )
        if (
            str(snapshot.get("job_id") or "") != claims["job_id"]
            or str(snapshot.get("agent_publication_id") or "") != claims["agent_publication_id"]
            or str(snapshot.get("application_publication_id") or "")
            != claims["application_publication_id"]
        ):
            raise PrincipalTokenError(
                "Principal MCP snapshot provenance does not match claims",
                safe_message="当前任务工具快照与身份凭证不匹配",
                error_code="principal_snapshot_invalid",
            )
        raw_tools = snapshot.get("tools")
        if not isinstance(raw_tools, list):
            raise PrincipalTokenError(
                "Principal MCP snapshot tools are invalid",
                safe_message="当前任务工具快照无效",
                error_code="principal_snapshot_invalid",
            )
        scopes: list[str] = []
        seen: set[str] = set()
        for item in raw_tools:
            if (
                not isinstance(item, dict)
                or str(item.get("server_code") or "") != self.expected_audience
            ):
                continue
            identifier = str(item.get("tool_identifier") or "")
            definition = self._tool_manifest.get(identifier)
            if (
                not identifier
                or identifier in seen
                or definition is None
                or definition.server_code != self.expected_audience
                or definition.schema_hash != str(item.get("schema_hash") or "")
            ):
                raise PrincipalTokenError(
                    "Principal MCP snapshot Tool is duplicated or has drifted",
                    safe_message="当前任务工具快照无效",
                    error_code="principal_snapshot_invalid",
                )
            require_business_principal_server(
                definition.server_code,
                policies=self._server_policies,
            )
            seen.add(identifier)
            scopes.append(mcp_invoke_scope(self.expected_audience, identifier))
        scopes.sort()
        if not scopes:
            raise PrincipalTokenError(
                "Principal MCP snapshot has no Tool for this audience",
                safe_message="当前任务没有对应业务工具权限",
                error_code="principal_scope_denied",
            )
        authorization_hash = str(verified.get("authorization_hash") or "")
        if len(authorization_hash) != _AUTHORIZATION_HASH_LENGTH or any(
            char not in "0123456789abcdef" for char in authorization_hash
        ):
            raise PrincipalTokenError(
                "Principal authorization hash is invalid",
                safe_message="当前任务授权摘要无效",
                error_code="principal_snapshot_invalid",
            )
        return scopes, authorization_hash

    def _untrusted_audit_projection(self, token: str) -> dict[str, Any]:
        projection: dict[str, Any] = {"audience": self.expected_audience}
        if not token or len(token) > MAX_PRINCIPAL_TOKEN_BYTES:
            return projection
        try:
            header = jwt.get_unverified_header(token)
            claims = jwt.decode(token, options={"verify_signature": False})
        except (jwt.PyJWTError, ValueError):
            return projection
        for source, target in (
            (header.get("kid"), "kid"),
            (claims.get("jti"), "jti"),
            (claims.get("job_id"), "job_id"),
        ):
            if isinstance(source, str) and 0 < len(source) <= 256:
                projection[target] = source
        scope = claims.get("scope")
        if (
            isinstance(scope, list)
            and len(scope) <= 16
            and all(
                isinstance(item, str)
                and item.startswith(f"mcp:{self.expected_audience}:")
                and item.endswith(":invoke")
                and len(item) <= 256
                for item in scope
            )
        ):
            projection["scope"] = list(scope)
        for source, target in (
            (claims.get("iat"), "issued_at"),
            (claims.get("nbf"), "not_before"),
            (claims.get("exp"), "expires_at"),
        ):
            if type(source) is int:
                projection[target] = source
        return projection

    def _claims_audit_projection(
        self,
        claims: Mapping[str, Any],
        token: str,
    ) -> dict[str, Any]:
        projection = self._untrusted_audit_projection(token)
        projection.update(
            {
                "audience": self.expected_audience,
                "job_id": str(claims.get("job_id") or "")[:256],
                "jti": str(claims.get("jti") or "")[:256],
                "scope": list(claims.get("scope") or [])[:64],
            }
        )
        return projection

    def _audit_rejection(self, payload: dict[str, Any], error_code: str) -> None:
        if self.audit_service is None:
            return
        safe_payload = {**payload, "error_code": error_code}
        self.audit_service.record(
            "principal.jwt.validation_denied",
            status="denied",
            summary="Principal JWT validation denied",
            job_id=str(payload.get("job_id") or "") or None,
            payload=safe_payload,
        )


def write_public_jwks_file(signing_key: PrincipalSigningKey, path: str) -> None:
    """Deployment helper: atomically publish only the public JWKS projection."""

    destination = Path(path)
    parent = destination.parent
    parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = parent / f".{destination.name}.{os.getpid()}.tmp"
    content = json.dumps(
        signing_key.public_jwks(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(descriptor, "wb") as file_handle:
            file_handle.write(content)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
