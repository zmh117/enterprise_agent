from __future__ import annotations

from typing import Any, Never, Protocol

import jwt

from app.modules.file_workspace.authorization import (
    FileAuthorizationContext,
    FileAuthorizationService,
)
from app.modules.file_workspace.contracts import FILE_MCP_SERVER_CODE, FILE_TOOL_MANIFEST
from services.file_service.auth import FilePrincipalError, FilePrincipalVerifier


class JobToolSnapshotPort(Protocol):
    def verify(self, job_id: str) -> dict[str, Any]: ...


def file_tool_scope(tool_identifier: str) -> str:
    return f"mcp:{FILE_MCP_SERVER_CODE}:{tool_identifier}:invoke"


class FilePrincipalResolver:
    def __init__(
        self,
        verifier: FilePrincipalVerifier,
        snapshot_service: JobToolSnapshotPort,
        authorization: FileAuthorizationService,
    ) -> None:
        self.verifier = verifier
        self.snapshot_service = snapshot_service
        self.authorization = authorization

    def authenticate(
        self,
        token: str,
        *,
        tool_identifier: str = "task_workspace_get",
    ) -> tuple[dict[str, Any], FileAuthorizationContext, tuple[str, ...]]:
        job_id = self._untrusted_job_id(token)
        verified = self.snapshot_service.verify(job_id)
        snapshot = verified.get("snapshot")
        if not isinstance(snapshot, dict):
            self._deny("file_principal_snapshot_invalid")
        bindings = [
            dict(item)
            for item in snapshot.get("tools") or []
            if isinstance(item, dict)
            and item.get("server_code") == FILE_MCP_SERVER_CODE
            and item.get("tool_identifier") in FILE_TOOL_MANIFEST
        ]
        expected_scopes = frozenset(
            file_tool_scope(str(item["tool_identifier"])) for item in bindings
        )
        if not expected_scopes or file_tool_scope(tool_identifier) not in expected_scopes:
            self._deny("file_principal_tool_denied")
        for binding in bindings:
            definition = FILE_TOOL_MANIFEST[str(binding["tool_identifier"])]
            if str(binding.get("schema_hash") or "") != definition.schema_hash:
                self._deny("file_principal_schema_mismatch")
        claims = self.verifier.verify(token, required_scopes=expected_scopes)
        if (
            str(claims["job_id"]) != job_id
            or str(claims["authorization_hash"])
            != str(verified.get("authorization_hash") or "")
        ):
            self._deny("file_principal_snapshot_mismatch")
        context = self.authorization.require_job(
            claims=claims,
            tool_identifier=tool_identifier,
        )
        return claims, context, tuple(
            sorted(str(item["tool_identifier"]) for item in bindings)
        )

    @staticmethod
    def _untrusted_job_id(token: str) -> str:
        try:
            claims = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_aud": False,
                    "verify_iss": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise FilePrincipalError(
                "File Principal JWT cannot be routed",
                safe_message="平台文件身份凭证无效",
                error_code="file_principal_token_invalid",
            ) from exc
        job_id = claims.get("job_id") if isinstance(claims, dict) else None
        if not isinstance(job_id, str) or not job_id or len(job_id) > 128:
            FilePrincipalResolver._deny("file_principal_job_invalid")
        return job_id

    @staticmethod
    def _deny(code: str) -> Never:
        raise FilePrincipalError(
            "File Principal resolution denied",
            safe_message="当前任务的文件权限不可用",
            error_code=code,
        )
