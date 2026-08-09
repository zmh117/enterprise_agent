from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Protocol

from services.mcp_common.auth import McpAuthenticationError
from services.mcp_common.contracts import (
    AuthorizedToolContext,
    JobContext,
    McpTokenClaims,
    PrincipalContext,
    SubjectSnapshot,
    ToolBindingContext,
)


class PlatformQuery(Protocol):
    def execute(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]: ...

    def execute_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None: ...

    def unit_of_work(self) -> AbstractContextManager[None]: ...


class McpRequestAuthorizer(Protocol):
    def authorize_request(self, claims: McpTokenClaims) -> JobContext: ...


class RejectingRequestAuthorizer:
    def authorize_request(self, claims: McpTokenClaims) -> JobContext:
        del claims
        raise McpAuthenticationError("MCP platform authorization is unavailable")


class PostgresPlatformQuery:
    """Small least-privilege query adapter for independently deployed MCP servers."""

    def __init__(self, dsn: str, *, max_size: int = 5, timeout_seconds: float = 5) -> None:
        if not dsn.startswith(("postgresql://", "postgres://")):
            raise ValueError("MCP servers require a PostgreSQL DATABASE_DSN")
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ModuleNotFoundError as exc:
            raise RuntimeError("psycopg pool is required by MCP servers") from exc
        self._pool = ConnectionPool(
            conninfo=dsn,
            min_size=0,
            max_size=max_size,
            timeout=timeout_seconds,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=False,
            name="enterprise-mcp-platform-store",
        )
        self._opened = False
        self._timeout_seconds = timeout_seconds
        self._local = threading.local()

    def _connection(self) -> AbstractContextManager[Any]:
        if not self._opened:
            self._pool.open(wait=True, timeout=self._timeout_seconds)
            self._opened = True
        return self._pool.connection(timeout=self._timeout_seconds)

    def execute(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        active_connection = getattr(self._local, "connection", None)
        if active_connection is not None:
            return self._execute(active_connection, sql, params)
        with self._connection() as connection:
            return self._execute(connection, sql, params)

    def execute_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self.execute(sql, params)
        return rows[0] if rows else None

    @contextmanager
    def unit_of_work(self) -> Iterator[None]:
        if getattr(self._local, "connection", None) is not None:
            raise RuntimeError("Nested MCP platform transactions are not supported")
        with self._connection() as connection:
            self._local.connection = connection
            try:
                with connection.transaction():
                    yield
            finally:
                del self._local.connection

    @staticmethod
    def _execute(connection: Any, sql: str, params: Iterable[Any]) -> list[dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(sql.replace("?", "%s"), tuple(params))
            return [dict(row) for row in cursor.fetchall()] if cursor.description else []

    def close(self) -> None:
        if self._opened:
            self._pool.close(timeout=self._timeout_seconds)
            self._opened = False


class PlatformRuntimeStore:
    def __init__(self, query: PlatformQuery, *, server_code: str) -> None:
        if server_code not in {"ones-mcp", "data-mcp"}:
            raise ValueError("Unsupported MCP server code")
        self.query = query
        self.server_code = server_code

    @classmethod
    def from_environment(cls, *, server_code: str) -> PlatformRuntimeStore:
        dsn = os.environ.get("DATABASE_DSN", "").strip()
        if not dsn:
            raise RuntimeError("DATABASE_DSN is required by MCP platform authorization")
        return cls(PostgresPlatformQuery(dsn), server_code=server_code)

    def authorize_request(self, claims: McpTokenClaims) -> JobContext:
        if claims.aud != self.server_code:
            raise McpAuthenticationError("MCP token audience does not match server")
        if (
            self.query.execute_one(
                "select jti from mcp_token_revocation where jti = ?",
                (claims.jti,),
            )
            is not None
        ):
            raise McpAuthenticationError("MCP token has been revoked")
        row = self.query.execute_one(
            """
            select id, status, user_id, internal_user_id,
                   business_application_publication_id
              from agent_job where id = ?
            """,
            (claims.job_id,),
        )
        if row is None or str(row["status"]) != "RUNNING":
            raise McpAuthenticationError("MCP Job is not currently executable")
        app_user_id = str(row.get("internal_user_id") or row.get("user_id") or "")
        if app_user_id != claims.sub:
            raise McpAuthenticationError("MCP Job subject does not match token")
        publication_id = str(row.get("business_application_publication_id") or "")
        if publication_id != claims.application_publication_id:
            raise McpAuthenticationError("MCP Job publication does not match token")
        snapshot = self.query.execute_one(
            "select * from mcp_job_subject_snapshot where job_id = ?",
            (claims.job_id,),
        )
        if snapshot is None or str(snapshot["app_user_id"]) != claims.sub:
            raise McpAuthenticationError("MCP Job subject snapshot is unavailable")
        _verify_subject_snapshot(snapshot)
        return JobContext(
            job_id=claims.job_id,
            app_user_id=claims.sub,
            application_publication_id=claims.application_publication_id,
            status="RUNNING",
            subject=SubjectSnapshot(
                external_identity_id=str(snapshot.get("external_identity_id") or ""),
                external_subject=str(snapshot.get("external_subject") or ""),
                provider_instance_id=str(snapshot.get("provider_instance_id") or ""),
                default_team_id=str(snapshot.get("default_team_id") or ""),
                binding_revision=int(snapshot.get("binding_revision") or 0),
            ),
        )

    def authorize_tool(
        self,
        *,
        claims: McpTokenClaims,
        tool_name: str,
        required_scope: str,
        correlation_id: str,
    ) -> AuthorizedToolContext:
        job = self.authorize_request(claims)
        if required_scope not in claims.scopes:
            raise McpAuthenticationError("MCP token scope is insufficient")
        rows = self.query.execute(
            """
            select b.*, s.id as subject_snapshot_id
              from mcp_job_tool_binding b
              join mcp_job_subject_snapshot s on s.job_id = b.job_id
              join mcp_tool_publication p on p.id = b.tool_publication_id
             where b.job_id = ? and b.server_code = ? and b.tool_name = ?
               and b.required_scope = ? and b.status = 'ELIGIBLE'
               and p.status = 'ACTIVE'
            """,
            (claims.job_id, self.server_code, tool_name, required_scope),
        )
        if len(rows) != 1:
            raise McpAuthenticationError("MCP tool is not uniquely authorized for this Job")
        row = rows[0]
        _verify_tool_binding(row)
        if self.server_code == "data-mcp":
            deployment = self.query.execute_one(
                """
                select d.status, d.resource_revision_id, d.current_generation_id,
                       r.lifecycle_status, rr.revision_status,
                       g.status as generation_status,
                       g.resource_revision_id as generation_resource_revision_id
                  from mcp_resource_deployment d
                  join mcp_resource r on r.id = d.resource_id
                  join mcp_resource_revision rr on rr.id = d.resource_revision_id
                  left join mcp_resource_generation g on g.id = d.current_generation_id
                 where d.id = ?
                """,
                (row["resource_deployment_id"],),
            )
            if deployment is None or any(
                (
                    str(deployment["status"]) != "ACTIVE",
                    str(deployment["lifecycle_status"]) != "ENABLED",
                    str(deployment["revision_status"]) != "PUBLISHED",
                    str(deployment["resource_revision_id"]) != str(row["resource_revision_id"]),
                    str(deployment.get("generation_status") or "") != "ACTIVE",
                    str(deployment.get("generation_resource_revision_id") or "")
                    != str(row["resource_revision_id"]),
                )
            ):
                raise McpAuthenticationError("MCP Resource deployment is unavailable")
        principal = PrincipalContext(
            app_user_id=claims.sub,
            job_id=claims.job_id,
            application_publication_id=claims.application_publication_id,
            audience=claims.aud,
            scopes=claims.scopes,
            token_id=claims.jti,
            correlation_id=correlation_id[:128],
        )
        return AuthorizedToolContext(
            principal=principal,
            job=job,
            binding=ToolBindingContext(
                binding_id=str(row["id"]),
                subject_snapshot_id=str(row["subject_snapshot_id"]),
                server_code=claims.aud,
                tool_name=tool_name,
                required_scope=required_scope,
                tool_schema_hash=str(row["tool_schema_hash"]),
                resource_code=str(row.get("resource_code") or ""),
                resource_deployment_id=str(row.get("resource_deployment_id") or ""),
                resource_revision_id=str(row.get("resource_revision_id") or ""),
            ),
        )


def _verify_subject_snapshot(row: dict[str, Any]) -> None:
    payload = {
        "job_id": row["job_id"],
        "app_user_id": row["app_user_id"],
        "external_identity_id": row["external_identity_id"],
        "external_subject": row["external_subject"],
        "provider_instance_id": row["provider_instance_id"],
        "default_team_id": row["default_team_id"],
        "binding_revision": int(row["binding_revision"]),
    }
    if _hash(payload) != str(row["snapshot_hash"]):
        raise McpAuthenticationError("MCP Job subject snapshot integrity failed")


def _verify_tool_binding(row: dict[str, Any]) -> None:
    payload = {
        key: row[key]
        for key in (
            "job_id",
            "tool_publication_id",
            "server_code",
            "tool_name",
            "required_scope",
            "tool_schema_hash",
            "resource_code",
            "resource_deployment_id",
            "resource_revision_id",
            "status",
            "reason_code",
        )
    }
    if _hash(payload) != str(row["snapshot_hash"]):
        raise McpAuthenticationError("MCP Job tool binding integrity failed")


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
